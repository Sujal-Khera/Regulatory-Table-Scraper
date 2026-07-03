import json
with open('workspaces/b362c51a89b67ff4/extraction/cross_subsidy_surcharge/raw_merged.json', encoding='utf-8') as f:
    data = json.load(f)

rows_to_check = [0, 1, 2, 48, 49, 50, 86, 87, 88, 94, 95, 96, 164, 165, 166, 281, 282, 283]
for idx in rows_to_check:
    if idx < len(data['rows']):
        row = data['rows'][idx]
        row_str = str(row[:10]).encode('ascii', errors='ignore').decode('ascii')
        print(f"Row {idx}: {row_str}")
