"""Score table features against signatures to produce PatternClassification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from table_scraper.domain.enums import ArtifactKind, ParserFamily, TablePattern, RoutingSource, SessionStage, StageStatus
from table_scraper.domain.models import NormalizedTable, PatternClassification
from table_scraper.patterns.features import extract_features
from table_scraper.patterns.signatures import load_pattern_signatures


def _resolve_parser_routing(pattern: TablePattern) -> tuple[ParserFamily | None, str | None]:
    """Map a TablePattern layout family to its parser registration info."""
    if pattern == TablePattern.SIMPLE_MATRIX:
        return ParserFamily.SIMPLE_MATRIX, "simple_matrix_v1"
    if pattern == TablePattern.NUMERIC_MATRIX:
        return ParserFamily.NUMERIC_MATRIX, "numeric_matrix_v1"
    if pattern == TablePattern.STATE_BLOCK_MATRIX:
        return ParserFamily.STATE_BLOCK_MATRIX, "state_block_matrix_v1"
    if pattern == TablePattern.WIDE_TABLE:
        return ParserFamily.WIDE_TO_LONG, "wide_to_long_v1"
    if pattern == TablePattern.KEY_VALUE:
        return ParserFamily.KEY_VALUE, "key_value_v1"
    if pattern == TablePattern.HIERARCHICAL_PARENT_CHILD:
        return ParserFamily.NARRATIVE, "narrative_v1"
    return None, None


def _evaluate_rule(val: float, op: str, threshold: float) -> bool:
    """Check if the signature condition matches the feature value."""
    if op == "equals":
        return abs(val - threshold) < 1e-6
    if op == "greater_than":
        return val > threshold
    if op == "less_than":
        return val < threshold
    if op == "not_equals":
        return abs(val - threshold) >= 1e-6
    return False


def classify_table(
    normalized: NormalizedTable,
    config: Any,
) -> PatternClassification:
    """Classify table pattern and suggest parser routing.

    Scores extracted features against expectations for each layout family.
    Supports config/manual overrides, auto-thresholding, and FTS tracing.

    Args:
        normalized: Input NormalizedTable containing structural data.
        config: Application settings profile.

    Returns:
        PatternClassification routing result.
    """
    # 1. Compute table lineage hash
    raw_str = json.dumps(normalized.rows)
    input_table_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    # 2. Check for manual overrides or parameter config overrides
    force_pattern: TablePattern | None = None
    routing_source = RoutingSource.CLASSIFIER

    # Check config parameter force_pattern
    try:
        from table_scraper.config.loader import load_parameter_config
        param_cfg = load_parameter_config(normalized.parameter_id)
        if hasattr(param_cfg, "force_pattern") and param_cfg.force_pattern is not None:
            force_pattern = param_cfg.force_pattern
            routing_source = RoutingSource.CONFIG_OVERRIDE
    except Exception:
        pass

    # Check config properties directly
    if not force_pattern:
        if hasattr(config, "force_pattern") and config.force_pattern is not None:
            force_pattern = config.force_pattern
            routing_source = RoutingSource.CONFIG_OVERRIDE
        elif isinstance(config, dict) and "force_pattern" in config and config["force_pattern"] is not None:
            force_pattern = config["force_pattern"]
            routing_source = RoutingSource.CONFIG_OVERRIDE

    # Check user manual patterns dictionary if passed
    if not force_pattern:
        confirmed_patterns = None
        if hasattr(config, "confirmed_patterns") and config.confirmed_patterns is not None:
            confirmed_patterns = config.confirmed_patterns
        elif isinstance(config, dict) and "confirmed_patterns" in config:
            confirmed_patterns = config["confirmed_patterns"]

        if confirmed_patterns and isinstance(confirmed_patterns, dict):
            if normalized.parameter_id in confirmed_patterns:
                force_pattern = confirmed_patterns[normalized.parameter_id]
                routing_source = RoutingSource.USER_CONFIRMED

    # Apply override if present
    if force_pattern:
        family, parser_id = _resolve_parser_routing(force_pattern)
        classification = PatternClassification(
            parameter_id=normalized.parameter_id,
            pattern=force_pattern,
            confidence=1.0,
            classified_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            routing_source=routing_source,
            parser_family=family,
            parser_id=parser_id,
            signals={},
            requires_user_confirmation=False,
            input_table_hash=input_table_hash,
        )
    else:
        # 3. Compute automatic feature signatures scoring
        features = extract_features(normalized)
        signatures = load_pattern_signatures()

        pattern_mapping = {
            "key_value": TablePattern.KEY_VALUE,
            "numeric_matrix": TablePattern.NUMERIC_MATRIX,
            "state_block_matrix": TablePattern.STATE_BLOCK_MATRIX,
            "wide_table": TablePattern.WIDE_TABLE,
            "simple_matrix": TablePattern.SIMPLE_MATRIX,
            "hierarchical_parent_child": TablePattern.HIERARCHICAL_PARENT_CHILD,
        }

        raw_scores: dict[TablePattern, float] = {}

        for sig_key, sig_data in signatures.items():
            pattern_enum = pattern_mapping.get(sig_key)
            if not pattern_enum:
                continue

            score = 0.0
            # Apply weights
            weights = sig_data.get("weights", {})
            for feat_name, w in weights.items():
                score += features.get(feat_name, 0.0) * float(w)

            # Apply rules
            rules = sig_data.get("rules", [])
            for r in rules:
                feat_name = r.get("feature")
                op = r.get("operator")
                val = r.get("value")
                rule_score = r.get("score", 0.0)
                if feat_name and op and val is not None:
                    feat_val = features.get(feat_name, 0.0)
                    if _evaluate_rule(feat_val, op, float(val)):
                        score += float(rule_score)

            raw_scores[pattern_enum] = score

        # 4. Softmax normalization for confidence values
        max_score = max(raw_scores.values()) if raw_scores else 0.0
        exp_sum = 0.0
        exp_scores: dict[TablePattern, float] = {}
        for p, s in raw_scores.items():
            val = math.exp(s - max_score)
            exp_scores[p] = val
            exp_sum += val

        confidences = {p: v / exp_sum for p, v in exp_scores.items()} if exp_sum > 0 else {}

        # Sort descending by confidence
        sorted_conf = sorted(confidences.items(), key=lambda x: x[1], reverse=True)

        if sorted_conf:
            best_pattern, confidence = sorted_conf[0]
            runner_up_pattern = sorted_conf[1][0] if len(sorted_conf) > 1 else None
            runner_up_confidence = sorted_conf[1][1] if len(sorted_conf) > 1 else None
        else:
            best_pattern = TablePattern.UNKNOWN
            confidence = 0.0
            runner_up_pattern = None
            runner_up_confidence = None

        # Resolve configured confidence threshold
        threshold = 0.6
        if hasattr(config, "classification_threshold") and config.classification_threshold is not None:
            threshold = float(config.classification_threshold)
        elif isinstance(config, dict) and "classification_threshold" in config and config["classification_threshold"] is not None:
            threshold = float(config["classification_threshold"])

        assigned_pattern = best_pattern
        requires_user_confirmation = False

        if confidence < threshold:
            requires_user_confirmation = True
            if confidence < 0.3:
                assigned_pattern = TablePattern.UNKNOWN

        family, parser_id = _resolve_parser_routing(assigned_pattern)

        classification = PatternClassification(
            parameter_id=normalized.parameter_id,
            pattern=assigned_pattern,
            confidence=confidence,
            classified_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            routing_source=RoutingSource.CLASSIFIER,
            parser_family=family,
            parser_id=parser_id,
            signals=features,
            runner_up_pattern=runner_up_pattern,
            runner_up_confidence=runner_up_confidence,
            requires_user_confirmation=requires_user_confirmation,
            input_table_hash=input_table_hash,
        )

    # 5. Persist to ArtifactStore and update Workspace Stage if available
    workspace = None
    if hasattr(config, "workspace") and config.workspace is not None:
        workspace = config.workspace
    elif isinstance(config, dict) and "workspace" in config:
        workspace = config["workspace"]

    if workspace is not None:
        try:
            from table_scraper.storage.artifact_store import ArtifactStore
            store = ArtifactStore(workspace)
            store.write(ArtifactKind.PATTERN, classification)

            # Update workspace manifest classify stage
            if hasattr(workspace, "manifest") and workspace.manifest is not None:
                workspace.manifest.stage_status[SessionStage.CLASSIFY] = StageStatus.COMPLETE
                workspace.manifest.save()
        except Exception:
            pass

    return classification

