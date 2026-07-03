"""Quick audit script to analyze record quality across all parameters."""
import json, os

base = "workspaces/b362c51a89b67ff4/parsing"

for param in sorted(os.listdir(base)):
    records_path = os.path.join(base, param, "records.json")
    if not os.path.exists(records_path):
        continue
    with open(records_path) as f:
        data = json.load(f)
    recs = data.get("records", [])
    print(f"\n{'='*60}")
    print(f"PARAMETER: {param}")
    print(f"  Record count: {len(recs)}")
    print(f"  Status: {data.get('status')}")
    print(f"  Parser: {data.get('parser_id')}")
    print(f"  Blocks used: {len(data.get('state_blocks_used', []))}")
    
    if not recs:
        print("  *** NO RECORDS EMITTED ***")
        continue
    
    # Analyze fields
    all_fields = set()
    for r in recs:
        all_fields.update(r["fields"].keys())
    print(f"  Fields: {sorted(all_fields)}")
    
    # State analysis
    states = sorted(set(r["fields"].get("state", "") for r in recs))
    print(f"  Unique states ({len(states)}):")
    for s in states[:30]:
        print(f"    {s}")
    if len(states) > 30:
        print(f"    ... and {len(states)-30} more")
    
    # Utility analysis
    utils = sorted(set(r["fields"].get("utility", "") for r in recs))
    print(f"  Unique utilities ({len(utils)}):")
    for u in utils:
        print(f"    {u}")
    
    # Empty field analysis
    for field in sorted(all_fields):
        empty = sum(1 for r in recs if not r["fields"].get(field))
        if empty > 0:
            print(f"  Empty '{field}': {empty}/{len(recs)} ({100*empty/len(recs):.0f}%)")
    
    # Consumer category analysis
    cats = sorted(set(r["fields"].get("consumer_category", "") for r in recs))
    if cats:
        print(f"  Unique consumer_categories ({len(cats)}):")
        for c in cats[:15]:
            print(f"    '{c}'")
        if len(cats) > 15:
            print(f"    ... and {len(cats)-15} more")
