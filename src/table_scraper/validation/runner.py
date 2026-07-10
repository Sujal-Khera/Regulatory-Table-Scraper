"""Run validation rule set for a parameter and return ValidationReport."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from table_scraper.domain.enums import ArtifactKind, SessionStage, StageStatus, ValidationSeverity
from table_scraper.domain.models import ParseResult, ValidationCheck, ValidationReport
from table_scraper.validation.rules.base import check_required_fields, check_numeric_range


def validate_parse_result(result: ParseResult, parameter_config: Any) -> ValidationReport:
    """Execute configured validation rules against a ParseResult.

    Runs required fields checks, duplicate detection, canonical state matching,
    numeric range validation, and missing value ratio gates, compiling the final
    report to qualify or block Excel warehouse delivery.

    Args:
        result: The ParseResult object containing records to validate.
        parameter_config: Active profile/parameter configuration.

    Returns:
        ValidationReport specifying checker metrics and gate pass outcome.
    """
    import re
    checks: list[ValidationCheck] = []

    # Load canonical catalogs for validation & confidence recalibration
    canonical_states = set()
    state_aliases = {}
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        catalogs = loader.load_catalogs()
        canonical_states = set(s.lower() for s in catalogs.states.states)
        state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
    except Exception:
        pass

    # Helper to check if value is null (None or empty string)
    def is_null(v: Any) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    # 0. Confidence Recalibration
    for record in result.records:
        utility_val = record.fields.get("utility", "")
        state_val = record.fields.get("state", "")
        
        # Check if all fields are populated (exclude record_id, parameter_id, confidence)
        all_populated = True
        for k, v in record.fields.items():
            if k in ("record_id", "parameter_id", "confidence"):
                continue
            if is_null(v):
                all_populated = False
                break
                
        if all_populated:
            conf = 0.95
        else:
            conf = 0.8
            
        # Non-canonical state recalibration
        if isinstance(state_val, str):
            state_clean = state_val.strip().lower()
            if not state_clean or (state_clean not in canonical_states and state_clean not in state_aliases):
                conf = min(conf, 0.5)
                
        # "Col N" utility recalibration
        if isinstance(utility_val, str):
            if re.match(r"^col\s+\d+", utility_val.strip().lower()):
                conf = min(conf, 0.3)
                
        record.confidence = conf

    # Load thresholds from configs
    min_records = 0
    max_warnings = 10
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        
        # Defaults overrides
        defaults_yaml = loader._load_yaml("defaults.yaml")
        if isinstance(defaults_yaml, dict) and "validation" in defaults_yaml:
            val_defaults = defaults_yaml["validation"]
            if isinstance(val_defaults, dict):
                max_warnings = int(val_defaults.get("max_warnings", max_warnings))
                
        # Parameter specific overrides
        param_yaml = loader._load_yaml(f"parsers/parameters/{result.parameter_id}.yaml")
        if isinstance(param_yaml, dict) and "validation" in param_yaml:
            val_param = param_yaml["validation"]
            if isinstance(val_param, dict):
                min_records = int(val_param.get("min_records", min_records))
                max_warnings = int(val_param.get("max_warnings", max_warnings))
    except Exception:
        pass

    # 1. Required Fields Validation (Severity: WARNING)
    required = ["state", "consumer_category", "charge_value"]
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        param_yaml = loader._load_yaml(f"parsers/parameters/{result.parameter_id}.yaml")
        if isinstance(param_yaml, dict):
            if "validation" in param_yaml and isinstance(param_yaml["validation"], dict) and "required_fields" in param_yaml["validation"]:
                required = list(param_yaml["validation"]["required_fields"])
            elif "output_schema" in param_yaml and isinstance(param_yaml["output_schema"], dict) and "columns" in param_yaml["output_schema"]:
                required = list(param_yaml["output_schema"]["columns"])
    except Exception:
        pass

    if hasattr(parameter_config, "required_fields") and getattr(parameter_config, "required_fields") is not None:
        required = list(getattr(parameter_config, "required_fields"))
    elif isinstance(parameter_config, dict) and "required_fields" in parameter_config:
        required = parameter_config["required_fields"]

    field_mapping = {
        "category": "consumer_category",
        "value": "charge_value",
        "year_label": "year",
    }
    mapped_required = [field_mapping.get(f, f) for f in required]

    missing_counts: dict[str, int] = {f: 0 for f in required}
    for record in result.records:
        # Check required using mapped keys but report using original schema key names
        for orig_f, mapped_f in zip(required, mapped_required):
            if mapped_f not in record.fields or record.fields[mapped_f] is None:
                missing_counts[orig_f] += 1
            elif isinstance(record.fields[mapped_f], str) and not record.fields[mapped_f].strip():
                missing_counts[orig_f] += 1

    total_missing = sum(missing_counts.values())
    checks.append(
        ValidationCheck(
            rule_id="required_fields",
            severity=ValidationSeverity.ERROR,
            passed=(total_missing == 0),
            message=f"Missing required fields: {missing_counts}" if total_missing > 0 else "All required fields are populated.",
            details={"missing_counts": missing_counts},
        )
    )

    # 2. Duplicate Record Detection (Severity: ERROR)
    seen_ids = set()
    duplicates = []
    for record in result.records:
        if record.record_id in seen_ids:
            duplicates.append(record.record_id)
        else:
            seen_ids.add(record.record_id)

    checks.append(
        ValidationCheck(
            rule_id="duplicate_records",
            severity=ValidationSeverity.ERROR,
            passed=(len(duplicates) == 0),
            message=f"Discovered {len(duplicates)} duplicate record IDs." if duplicates else "No duplicate records detected.",
            details={"duplicate_ids": duplicates},
        )
    )

    # 2.5 Composite Key Duplicate Detection (Severity: WARNING by default)
    composite_severity = ValidationSeverity.WARNING
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        param_yaml = loader._load_yaml(f"parsers/parameters/{result.parameter_id}.yaml")
        if isinstance(param_yaml, dict) and "validation" in param_yaml:
            val_cfg = param_yaml["validation"]
            if isinstance(val_cfg, dict) and "composite_duplication_severity" in val_cfg:
                composite_severity = ValidationSeverity(val_cfg["composite_duplication_severity"])
    except Exception:
        pass

    composite_keys = ["state", "utility", "discom", "year", "voltage_level", "consumer_category"]
    seen_composite = {}
    composite_duplicates = []
    
    for record in result.records:
        key_parts = []
        for k in composite_keys:
            if k in record.fields:
                val = record.fields[k]
                key_parts.append(f"{k}:{str(val).strip().lower()}")
        if key_parts:
            key_tuple = tuple(key_parts)
            if key_tuple in seen_composite:
                composite_duplicates.append(record.record_id)
            else:
                seen_composite[key_tuple] = record.record_id

    checks.append(
        ValidationCheck(
            rule_id="composite_duplication",
            severity=composite_severity,
            passed=(len(composite_duplicates) == 0),
            message=f"Discovered {len(composite_duplicates)} composite key duplicates." if composite_duplicates else "No composite key duplicates detected.",
            details={"duplicate_ids": composite_duplicates},
        )
    )

    # 3. State Name Validation (Severity: WARNING)
    invalid_states = []
    for record in result.records:
        state_val = record.fields.get("state", "")
        if isinstance(state_val, str):
            state_clean = state_val.strip().lower()
            if state_clean and state_clean not in canonical_states and state_clean not in state_aliases:
                invalid_states.append(state_val)

    checks.append(
        ValidationCheck(
            rule_id="state_validation",
            severity=ValidationSeverity.ERROR,
            passed=(len(invalid_states) == 0),
            message=f"Found {len(invalid_states)} records with invalid state names." if invalid_states else "All state names are canonical.",
            details={"invalid_states": list(set(invalid_states))},
        )
    )

    # 4. Numeric Range Validation (Severity: WARNING)
    min_charge = 0.0
    max_charge = 1000.0
    if hasattr(parameter_config, "validation") and parameter_config.validation is not None:
        val_cfg = parameter_config.validation
        if hasattr(val_cfg, "min_value") and val_cfg.min_value is not None:
            min_charge = float(val_cfg.min_value)
        if hasattr(val_cfg, "max_value") and val_cfg.max_value is not None:
            max_charge = float(val_cfg.max_value)
    elif isinstance(parameter_config, dict) and "validation" in parameter_config:
        val_cfg = parameter_config["validation"]
        if isinstance(val_cfg, dict):
            min_charge = float(val_cfg.get("min_value", min_charge))
            max_charge = float(val_cfg.get("max_value", max_charge))

    out_of_range = []
    for record in result.records:
        val = record.fields.get("charge_value")
        if isinstance(val, (int, float)):
            if not check_numeric_range(float(val), min_charge, max_charge):
                out_of_range.append((record.record_id, float(val)))

    checks.append(
        ValidationCheck(
            rule_id="numeric_range",
            severity=ValidationSeverity.WARNING,
            passed=(len(out_of_range) == 0),
            message=f"Discovered {len(out_of_range)} out-of-range numeric charge values." if out_of_range else f"All numeric charges fall within [{min_charge}, {max_charge}].",
            details={"out_of_range_records": out_of_range},
        )
    )

    # 5. Missing Values / Null Rate Check (Severity: ERROR)
    total_records = len(result.records)
    
    state_null_count = sum(1 for r in result.records if is_null(r.fields.get("state")))
    utility_null_count = sum(1 for r in result.records if is_null(r.fields.get("utility")))
    
    value_fields = ["charge_value", "additional_surcharge", "wheeling_charge", "long_medium_charge", "short_term_charge", "charge"]
    value_null_count = 0
    total_value_fields_checked = 0
    for r in result.records:
        for f in value_fields:
            if f in r.fields:
                total_value_fields_checked += 1
                if is_null(r.fields[f]):
                    value_null_count += 1
                    
    state_null_rate = state_null_count / total_records if total_records > 0 else 0.0
    value_null_rate = value_null_count / total_value_fields_checked if total_value_fields_checked > 0 else 0.0
    
    utility_field_key = None
    if result.records:
        for key in ["utility", "discom"]:
            if key in result.records[0].fields:
                utility_field_key = key
                break
                
    if utility_field_key is not None:
        utility_null_count = sum(1 for r in result.records if is_null(r.fields.get(utility_field_key)))
        utility_null_rate = utility_null_count / total_records if total_records > 0 else 0.0
        passed_utility = (utility_null_rate <= 0.10)
    else:
        utility_null_count = 0
        utility_null_rate = 0.0
        passed_utility = True

    checks.append(
        ValidationCheck(
            rule_id="state_null_rate",
            severity=ValidationSeverity.ERROR,
            passed=(state_null_rate <= 0.05),
            message=f"State null rate is {state_null_rate:.2%} (limit is 5.00%).",
            details={"null_count": state_null_count, "total_records": total_records, "null_rate": state_null_rate},
        )
    )
    
    checks.append(
        ValidationCheck(
            rule_id="utility_null_rate",
            severity=ValidationSeverity.ERROR,
            passed=passed_utility,
            message=f"Utility null rate is {utility_null_rate:.2%} (limit is 10.00%)." if utility_field_key else "Utility column not present in schema; skipped.",
            details={"null_count": utility_null_count, "total_records": total_records, "null_rate": utility_null_rate},
        )
    )
    
    value_null_limit = 0.20
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        param_yaml = loader._load_yaml(f"parsers/parameters/{result.parameter_id}.yaml")
        if isinstance(param_yaml, dict) and "validation" in param_yaml:
            val_cfg = param_yaml["validation"]
            if isinstance(val_cfg, dict):
                value_null_limit = float(val_cfg.get("max_null_rate", value_null_limit))
    except Exception:
        pass

    checks.append(
        ValidationCheck(
            rule_id="value_null_rate",
            severity=ValidationSeverity.ERROR,
            passed=(value_null_rate <= value_null_limit),
            message=f"Value fields null rate is {value_null_rate:.2%} (limit is {value_null_limit:.2%}).",
            details={"null_count": value_null_count, "total_checked": total_value_fields_checked, "null_rate": value_null_rate},
        )
    )

    # 6. Minimum Records Check (Severity: ERROR)
    checks.append(
        ValidationCheck(
            rule_id="min_records",
            severity=ValidationSeverity.ERROR,
            passed=(total_records >= min_records),
            message=f"Emitted {total_records} records (minimum required is {min_records})." if total_records < min_records else f"Emitted {total_records} records, which satisfies the minimum of {min_records}.",
            details={"min_records": min_records, "actual_records": total_records},
        )
    )

    # 7. State Coverage Check (Severity: ERROR)
    min_states = 20 if result.parameter_id == "cross_subsidy_surcharge" else 10
    canonical_states_in_records = set()
    for record in result.records:
        state_val = record.fields.get("state", "")
        if isinstance(state_val, str):
            state_clean = state_val.strip().lower()
            if state_clean in canonical_states or state_clean in state_aliases:
                canonical_state = state_aliases.get(state_clean, state_clean).title()
                canonical_states_in_records.add(canonical_state)
                
    passed_state_coverage = (len(canonical_states_in_records) >= min_states)
    checks.append(
        ValidationCheck(
            rule_id="state_coverage",
            severity=ValidationSeverity.ERROR,
            passed=passed_state_coverage,
            message=f"Found {len(canonical_states_in_records)} canonical states (minimum required is {min_states})." if not passed_state_coverage else f"Found {len(canonical_states_in_records)} canonical states, satisfying the minimum of {min_states}.",
            details={"min_states": min_states, "actual_states_count": len(canonical_states_in_records), "states": list(canonical_states_in_records)},
        )
    )

    # 8. Aggregate report summary
    error_count = sum(1 for c in checks if c.severity == ValidationSeverity.ERROR and not c.passed)
    warning_count = sum(1 for c in checks if c.severity == ValidationSeverity.WARNING and not c.passed)
    passed = (error_count == 0)
    export_allowed = (error_count == 0) and (warning_count <= max_warnings)

    states_covered = sorted(list(set(r.fields.get("state") for r in result.records if r.fields.get("state"))))
    utilities_covered = sorted(list(set(r.fields.get("utility") for r in result.records if r.fields.get("utility"))))

    summary = {
        "record_count": total_records,
        "null_rate": value_null_rate,
        "states_covered": states_covered,
        "utilities_covered": utilities_covered,
        "state_count": len(states_covered),
        "utility_count": len(utilities_covered),
    }

    expected_thresholds = {
        "required_fields": required,
        "min_value": min_charge,
        "max_value": max_charge,
        "min_records": min_records,
        "max_warnings": max_warnings,
        "min_states": min_states,
    }

    parse_result_str = "".join(r.record_id for r in result.records)
    parse_result_hash = hashlib.sha256(parse_result_str.encode("utf-8")).hexdigest()

    report = ValidationReport(
        parameter_id=result.parameter_id,
        validated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        passed=passed,
        error_count=error_count,
        warning_count=warning_count,
        checks=checks,
        parse_result_hash=parse_result_hash,
        summary=summary,
        expected_thresholds=expected_thresholds,
        export_allowed=export_allowed,
    )

    # 7. Persist to ArtifactStore and update Workspace Stage if available
    workspace = None
    if hasattr(parameter_config, "workspace") and parameter_config.workspace is not None:
        workspace = parameter_config.workspace
    elif isinstance(parameter_config, dict) and "workspace" in parameter_config:
        workspace = parameter_config["workspace"]

    if workspace is not None:
        try:
            from table_scraper.storage.artifact_store import ArtifactStore
            store = ArtifactStore(workspace)
            store.write(ArtifactKind.VALIDATION, report, result.parameter_id)

            if hasattr(workspace, "manifest") and workspace.manifest is not None:
                workspace.manifest.stage_status[SessionStage.VALIDATE] = StageStatus.COMPLETE
                workspace.manifest.save()
        except Exception:
            pass

    return report

