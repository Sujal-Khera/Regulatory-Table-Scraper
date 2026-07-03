"""Metadata Recognition Engine — cell semantic annotation."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.models import NormalizedTable
from table_scraper.entity_recognition import EntityRecognizer
from table_scraper.entity_recognition import EntityType as RecognizerEntityType
from table_scraper.entity_recognition import RecognitionContext as RecognizerContext
from table_scraper.understanding.models import (
    AnnotatedTable,
    CellAnnotation,
    ColumnDescriptor,
    ColumnRole,
    EntityType,
)


class MetadataAnnotator:
    """Annotates cells in a NormalizedTable with semantic types, canonical values, and types."""

    def __init__(self, recognizer: EntityRecognizer) -> None:
        self.recognizer = recognizer

    def _parse_numeric(self, val: str) -> float | None:
        """Helper to parse raw string into float value."""
        if not val:
            return None
        cleaned = val.replace(",", "").strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
        return None

    def annotate_table(
        self,
        table: NormalizedTable,
        columns: list[ColumnDescriptor],
        header_depth: int,
    ) -> AnnotatedTable:
        """Produce an AnnotatedTable with parallel CellAnnotation grid."""
        annotations: list[list[CellAnnotation]] = []
        num_rows = table.row_count
        num_cols = table.column_count

        # Identify state column index (default to 0)
        state_col_idx = 0
        for col in columns:
            if col.semantic_role == ColumnRole.STATE:
                state_col_idx = col.index
                break

        for r_idx in range(num_rows):
            row_annotations = []
            is_header = r_idx < header_depth

            # Find active state for the current row to provide context
            active_state = None
            if not is_header and state_col_idx < len(table.rows[r_idx]):
                state_val = table.rows[r_idx][state_col_idx]
                state_match = self.recognizer.recognize_state(state_val)
                if state_match:
                    active_state = state_match.canonical_value

            for c_idx in range(num_cols):
                val = table.rows[r_idx][c_idx]
                col_desc = columns[c_idx] if c_idx < len(columns) else None

                # 1. Header cells
                if is_header:
                    row_annotations.append(
                        CellAnnotation(
                            entity_type=EntityType.HEADER,
                            canonical_value=val,
                            confidence=1.0,
                            is_numeric=False,
                            numeric_value=None,
                            unit=None,
                            flags=["header_row"],
                        )
                    )
                    continue

                # 2. Empty cells
                cleaned_val = val.strip()
                if not cleaned_val or cleaned_val in ["NA", "N/A", "na", "n/a", "-"]:
                    row_annotations.append(
                        CellAnnotation(
                            entity_type=EntityType.EMPTY,
                            canonical_value=None,
                            confidence=1.0,
                            is_numeric=False,
                            numeric_value=None,
                            unit=None,
                            flags=["empty"],
                        )
                    )
                    continue

                # 3. Data cells - build context
                context = RecognizerContext(
                    active_state=active_state,
                    column_header=col_desc.display_name if col_desc else None,
                    row_index=r_idx,
                    col_index=c_idx,
                )

                # Recognize using EntityRecognizer
                rec_match = self.recognizer.recognize(cleaned_val, context)

                # Map entity types
                e_type = EntityType.UNKNOWN
                canon_val = rec_match.canonical_value
                conf = rec_match.confidence
                flags = []

                if rec_match.entity_type == RecognizerEntityType.STATE:
                    e_type = EntityType.STATE
                    flags.append("state")
                elif rec_match.entity_type == RecognizerEntityType.UTILITY:
                    e_type = EntityType.UTILITY
                    flags.append("utility")
                elif rec_match.entity_type == RecognizerEntityType.VOLTAGE:
                    e_type = EntityType.VOLTAGE
                    flags.append("voltage")
                elif rec_match.entity_type == RecognizerEntityType.YEAR:
                    e_type = EntityType.YEAR
                    flags.append("year")
                elif rec_match.entity_type == RecognizerEntityType.UNIT:
                    e_type = EntityType.UNIT
                    flags.append("unit")
                elif rec_match.entity_type == RecognizerEntityType.CATEGORY:
                    e_type = EntityType.CATEGORY
                    flags.append("category")

                # If unknown type, check if it's a numeric value
                num_val = self._parse_numeric(cleaned_val)
                is_num = num_val is not None

                if e_type == EntityType.UNKNOWN and is_num:
                    # Leverage column semantic role to classify
                    if col_desc:
                        if col_desc.semantic_role == ColumnRole.SERIAL_NUMBER:
                            e_type = EntityType.SERIAL_NUMBER
                            flags.append("serial_number")
                        elif col_desc.semantic_role == ColumnRole.VOLTAGE:
                            e_type = EntityType.VOLTAGE
                            flags.append("voltage")
                            canon_val = f"{int(num_val)} kV"
                        elif col_desc.semantic_role == ColumnRole.VALUE:
                            if col_desc.unit == "%" or "%" in cleaned_val:
                                e_type = EntityType.PERCENTAGE
                                flags.append("percentage")
                            else:
                                e_type = EntityType.CHARGE
                                flags.append("charge")
                        else:
                            e_type = EntityType.CHARGE
                            flags.append("charge")
                    else:
                        e_type = EntityType.CHARGE
                        flags.append("charge")
                    
                    conf = 0.95

                # Apply strict context-aware numeric rule:
                # Prevent Years, Voltages, Header labels, Serial numbers from ever becoming charge values.
                if e_type in [EntityType.YEAR, EntityType.VOLTAGE, EntityType.HEADER, EntityType.SERIAL_NUMBER, EntityType.STATE, EntityType.UTILITY]:
                    # These can NEVER be charge values, so numeric_value is set to None
                    is_num_for_charge = False
                    num_val_for_charge = None
                else:
                    is_num_for_charge = is_num
                    num_val_for_charge = num_val

                # Resolve unit
                resolved_unit = None
                if e_type == EntityType.PERCENTAGE:
                    resolved_unit = "%"
                elif e_type == EntityType.CHARGE:
                    resolved_unit = (col_desc.unit if col_desc else None) or "Rs/kWh"

                if is_num_for_charge:
                    flags.append("numeric")

                row_annotations.append(
                    CellAnnotation(
                        entity_type=e_type,
                        canonical_value=canon_val,
                        confidence=conf,
                        is_numeric=is_num_for_charge,
                        numeric_value=num_val_for_charge,
                        unit=resolved_unit,
                        flags=flags,
                    )
                )

            annotations.append(row_annotations)

        return AnnotatedTable(
            parameter_id=table.parameter_id,
            table=table,
            columns=columns,
            annotations=annotations,
        )
