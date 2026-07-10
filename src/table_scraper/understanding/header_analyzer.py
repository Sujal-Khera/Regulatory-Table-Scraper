"""Header Intelligence Engine — multi-row header detection and tree semantics."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.enums import RowLabel
from table_scraper.domain.models import NormalizedTable
from table_scraper.entity_recognition import EntityRecognizer
from table_scraper.understanding.models import (
    ColumnDescriptor,
    ColumnRole,
    EntityType,
    HeaderTree,
)


class HeaderAnalyzer:
    """Analyzes multi-row table headers to construct a HeaderTree and ColumnDescriptors."""

    def __init__(self, recognizer: EntityRecognizer) -> None:
        self.recognizer = recognizer

    def detect_header_depth(self, table: NormalizedTable) -> int:
        """Detect the number of rows at the top of the table that act as headers."""
        if not table.rows:
            return 0

        # Heuristic 1: If row labels exist and label is RowLabel.HEADER, count it.
        labelled_headers = 0
        if table.row_labels:
            for label in table.row_labels:
                if label == RowLabel.HEADER:
                    labelled_headers += 1
                else:
                    break

        # Heuristic 2: Auto-detect by scanning rows from 0 down
        detected_depth = 0
        max_scan = min(5, len(table.rows))  # cap header scan to 5 rows

        for i in range(max_scan):
            row = table.rows[i]
            # A row is a header candidate if:
            # - It contains mostly text, years, units, empty cells.
            # - It does NOT contain floats that represent typical charge values.
            # Let's count numeric cells that are NOT years or voltages
            non_header_numeric_count = 0
            for cell in row:
                cleaned_cell = cell.strip()
                if not cleaned_cell:
                    continue
                # Try parsing as float
                try:
                    val = float(cleaned_cell.replace(",", "").replace("%", "").strip())
                    # Check if it looks like a year (e.g. 2023)
                    is_year = (1990 <= val <= 2100) or ("-" in cleaned_cell) or ("/" in cleaned_cell)
                    if not is_year:
                        non_header_numeric_count += 1
                except ValueError:
                    pass

            # If we see any non-header numeric value in the row, it's a data row, so we stop.
            if non_header_numeric_count > 0:
                break
            detected_depth = i + 1

        # Use the maximum of labelled headers and auto-detected depth, capped appropriately
        final_depth = max(labelled_headers, detected_depth)
        return max(1, min(final_depth, len(table.rows)))

    def build_header_tree(self, table: NormalizedTable, depth: int) -> HeaderTree:
        """Construct a HeaderTree from the header rows, handling merged spans."""
        header_rows = table.rows[:depth]
        width = table.column_count

        # Build clean grid with cell padding/propagation
        grid = [[header_rows[r][c].strip() for c in range(width)] for r in range(depth)]

        # Horizontal propagation for row 0
        for c in range(width):
            if not grid[0][c] and c > 0:
                grid[0][c] = grid[0][c - 1]

        # Vertical and horizontal propagation for subsequent rows
        for r in range(1, depth):
            for c in range(width):
                if not grid[r][c]:
                    # Prefer vertical inheritance from above first
                    if grid[r - 1][c]:
                        grid[r][c] = grid[r - 1][c]
                    elif c > 0:
                        grid[r][c] = grid[r][c - 1]

        # Convert grid structure into nested dictionary for tree representation
        tree_dict: dict[str, Any] = {}
        for col_idx in range(width):
            path = []
            for r_idx in range(depth):
                cell_val = grid[r_idx][col_idx]
                if cell_val and cell_val not in ["/", "\\", "-"]:
                    path.append(cell_val)
            
            # De-duplicate adjacent identical items in the path
            dedup_path = []
            for item in path:
                if not dedup_path or dedup_path[-1] != item:
                    dedup_path.append(item)

            curr = tree_dict
            for i, step in enumerate(dedup_path):
                if step not in curr:
                    curr[step] = {"cols": [], "children": {}}
                if col_idx not in curr[step]["cols"]:
                    curr[step]["cols"].append(col_idx)
                curr = curr[step]["children"]

        return HeaderTree(raw_rows=header_rows, depth=depth, tree_data=tree_dict)

    def resolve_column_semantics(
        self, tree: HeaderTree, parameter_id: str
    ) -> list[ColumnDescriptor]:
        """Map columns to semantic roles, units, years, and clean display names."""
        depth = tree.depth
        width = len(tree.raw_rows[0]) if depth > 0 else 0

        # Build propagated grid again to easily extract column paths
        grid = [[tree.raw_rows[r][c].strip() for c in range(width)] for r in range(depth)]

        # Horizontal/vertical propagation
        for c in range(width):
            if depth > 0 and not grid[0][c] and c > 0:
                grid[0][c] = grid[0][c - 1]
        for r in range(1, depth):
            for c in range(width):
                if not grid[r][c]:
                    if grid[r - 1][c]:
                        grid[r][c] = grid[r - 1][c]
                    elif c > 0:
                        grid[r][c] = grid[r][c - 1]

        descriptors: list[ColumnDescriptor] = []

        for col_idx in range(width):
            # Extract raw cells for this column
            raw_headers = [grid[r][col_idx] for r in range(depth)]
            
            # Clean parts: remove meaningless symbols
            cleaned_parts = []
            for r_idx, part in enumerate(raw_headers):
                p_clean = re.sub(r'^[\s/*+-]+|[\s/*+-]+$', '', part).strip()
                if p_clean and p_clean not in ["/", "\\", "-", "State/UT"]:
                    if r_idx < depth - 1 and p_clean in ("11", "33", "66", "132", "220", "200"):
                        continue
                    cleaned_parts.append(p_clean)

            # De-duplicate adjacent parts
            dedup_parts = []
            for part in cleaned_parts:
                if not dedup_parts or dedup_parts[-1] != part:
                    dedup_parts.append(part)

            # Reconstruct display name
            if not dedup_parts:
                # If everything was empty or stripped, check if row 2 had "State/UT"
                has_state_ut = any("state" in str(r).lower() or "ut" in str(r).lower() for r in raw_headers)
                if col_idx == 0 and has_state_ut:
                    display_name = "State/UT"
                else:
                    display_name = f"Column {col_idx}"
            else:
                display_name = " - ".join(dedup_parts)

            # Resolve year, unit, and group
            year_val = None
            unit_val = None
            group_val = dedup_parts[0] if len(dedup_parts) > 1 else None

            # Detect year or unit from any of the raw header cells
            for part in raw_headers:
                # Year recognition
                year_match = self.recognizer.recognize_year(part)
                if year_match:
                    year_val = year_match.canonical_value

                # Unit recognition
                unit_match = self.recognizer.recognize_unit(part)
                if unit_match:
                    unit_val = unit_match.canonical_value

            # Determine ColumnRole
            role = ColumnRole.UNKNOWN
            entity_type = None

            # Check if it is a state column
            is_state_col = False
            for part in raw_headers:
                if any(kw in part.lower() for kw in ["state", "union territory", "ut"]):
                    is_state_col = True
                    break
                state_match = self.recognizer.recognize_state(part)
                if state_match:
                    is_state_col = True
                    break

            if col_idx == 0 and (is_state_col or "state" in display_name.lower()):
                role = ColumnRole.STATE
                entity_type = EntityType.STATE
            elif "utility" in display_name.lower() or "discom" in display_name.lower() or "licensee" in display_name.lower():
                role = ColumnRole.UTILITY
                entity_type = EntityType.UTILITY
            elif "voltage" in display_name.lower() or "kv" in display_name.lower() or "tension" in display_name.lower():
                role = ColumnRole.VOLTAGE
                entity_type = EntityType.VOLTAGE
            elif "category" in display_name.lower() or "consumer" in display_name.lower():
                role = ColumnRole.CATEGORY
                entity_type = EntityType.CATEGORY
            elif "s.no" in display_name.lower() or "sl.no" in display_name.lower() or display_name.lower() == "sno":
                role = ColumnRole.SERIAL_NUMBER
                entity_type = EntityType.SERIAL_NUMBER
            elif unit_val or year_val or "charge" in display_name.lower() or "surcharge" in display_name.lower() or "value" in display_name.lower():
                role = ColumnRole.VALUE
                entity_type = EntityType.PERCENTAGE if unit_val == "%" else EntityType.CHARGE
            else:
                # Fallback role deduction
                if year_val:
                    role = ColumnRole.VALUE
                    entity_type = EntityType.CHARGE
                else:
                    role = ColumnRole.UNKNOWN
                    entity_type = EntityType.UNKNOWN

            # Create ColumnDescriptor
            descriptors.append(
                ColumnDescriptor(
                    index=col_idx,
                    raw_headers=raw_headers,
                    display_name=display_name,
                    semantic_role=role,
                    entity_type=entity_type,
                    unit=unit_val,
                    year=year_val,
                    group=group_val,
                )
            )

        return descriptors
