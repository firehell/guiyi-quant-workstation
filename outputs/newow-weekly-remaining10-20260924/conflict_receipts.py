"""Read-only mapping from frozen D1/W1 conflicts to local apply receipts."""

import collections
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AUDIT = json.loads((HERE / "physical-causes.json").read_text())
receipts = collections.defaultdict(list)
for path in (ROOT / "outputs/newow-weekly-recovery-attempts").rglob("unit-result.json"):
    try:
        row = json.loads(path.read_text())
        if row.get("result", {}).get("status") != "passed":
            continue
        for item in row.get("readback", {}).get("catalog_partitions", ()):
            dataset = item.get("dataset", ())
            if len(dataset) != 4 or dataset[3] != "1d":
                continue
            key = (dataset[1], dataset[2], item["year"], item["month"],
                   item.get("file_sha256"))
            receipts[key].append(str(path.relative_to(ROOT)))
    except (ValueError, KeyError, TypeError):
        continue

rows = []
for contract in AUDIT["contracts"]:
    lineage = {(part["frequency"], part["year"], part["month"]): part
               for part in contract.get("lineage", ())}
    for issue in contract.get("issues", ()):
        if issue["kind"] != "D1_W1_VALUE_CONFLICT":
            continue
        week_end = date.fromisoformat(issue["week_end"])
        months = sorted({(day.year, day.month)
                         for offset in range(7)
                         if (day := week_end - timedelta(days=offset)).isocalendar()[:2]
                         == week_end.isocalendar()[:2]})
        daily = []
        for year, month in months:
            part = lineage.get(("1d", year, month))
            if part is None:
                daily.append({"year": year, "month": month, "status": "NO_PARTITION"})
                continue
            name = part["file"]
            digest = name[5:-8] if name.startswith("part.") and name.endswith(".parquet") else None
            matches = receipts.get((contract["symbol"], contract["contract"],
                                    year, month, digest), ())
            daily.append({"year": year, "month": month, "file": name,
                          "matching_receipts": matches})
        weekly = lineage.get(("1w", week_end.year, week_end.month))
        rows.append({"symbol": contract["symbol"], "contract": contract["contract"],
                     "week_end": issue["week_end"], "fields": issue["fields"],
                     "daily_partitions": daily,
                     "weekly_file": weekly["file"] if weekly else None,
                     "all_daily_receipted": bool(daily) and all(
                         part.get("matching_receipts") for part in daily),
                     "stored": issue["stored"], "from_current_d1": issue["expected"]})

result = {"catalog_revision": AUDIT["catalog_revision"],
          "code_sha_at_audit": AUDIT["code_sha"],
          "receipt_search_root": "outputs/newow-weekly-recovery-attempts",
          "receipt_scope": "local successful D1 unit-result readback with exact partition SHA",
          "rows": rows}
(HERE / "conflict-receipt-map.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"conflicts": len(rows),
                  "all_daily_receipted": sum(row["all_daily_receipted"] for row in rows),
                  "weekly_files": dict(collections.Counter(row["weekly_file"] for row in rows))}))
