import json
from table_scraper.domain.models import NormalizedTable
from table_scraper.entity_recognition import EntityRecognizer
from table_scraper.understanding.header_analyzer import HeaderAnalyzer

with open('workspaces/b362c51a89b67ff4/extraction/cross_subsidy_surcharge/normalized.json', encoding='utf-8') as f:
    tbl_data = json.load(f)

# Reconstruct NormalizedTable dataclass
tbl = NormalizedTable(
    parameter_id=tbl_data['parameter_id'],
    rows=tbl_data['rows'],
    row_count=tbl_data['row_count'],
    column_count=tbl_data['column_count'],
    normalization_steps=tbl_data['normalization_steps'],
    cleanup_stats=tbl_data['cleanup_stats'],
    row_labels=tbl_data.get('row_labels'),
    normalized_at=tbl_data['normalized_at']
)

recognizer = EntityRecognizer()
header_analyzer = HeaderAnalyzer(recognizer)

try:
    depth = header_analyzer.detect_header_depth(tbl)
    print(f"Header depth detected: {depth}")
    header_tree = header_analyzer.build_header_tree(tbl, depth)
    print("Header tree built successfully.")
    columns = header_analyzer.resolve_column_semantics(header_tree, tbl.parameter_id)
    print(f"Columns resolved: {len(columns)}")
except Exception as e:
    import traceback
    traceback.print_exc()
