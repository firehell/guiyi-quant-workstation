"""Freeze one PK2611 source request, then use the existing verifier."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/quant-api"), str(ROOT / "packages/quant-core"), str(ROOT)]
from dotenv import load_dotenv
load_dotenv(Path.home() / "Library/Application Support/GuiyiQuant/project.env", override=True)

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_market_data_service
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from scripts.newow_weekly_conflict_diagnosis import _diagnose
from scripts.newow_weekly_conflict_source_plan import build_source_plan

cutoff = datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00")
with SessionLocal() as session, readonly_transaction(session, timeout_seconds=300):
    before = catalog_revision(session, ("pk",), cutoff.date(), ("1d", "1w"))
    result = _diagnose(build_market_data_service(session), {"symbol": "pk", "contract": "PK2611", "through": "2026-09-18"}, cutoff)
    after = catalog_revision(session, ("pk",), cutoff.date(), ("1d", "1w"))
    if before != after:
        raise RuntimeError("CATALOG_REVISION_CHANGED")
    weeks = [week for week in result["conflict_weeks"] if week["trading_day"] == "2026-08-14"]
    if len(weeks) != 1 or weeks[0]["numeric_conflict_fields"] != ["turnover"]:
        raise RuntimeError("TARGET_CONFLICT_NOT_REPRODUCED")
    result["conflict_weeks"] = weeks
    result["conflict_week_count"] = 1
    body = {"schema_version": "newow_weekly_conflict_diagnosis_v2", "status": "diagnosed", "catalog_revision_stable": True,
            "catalog_revision_before": before, "catalog_revision_after": after,
            "as_of": cutoff.isoformat(), "code_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
            "input_sha256": hashlib.sha256(b"PK2611 2026-08-14 targeted conflict").hexdigest(), "contracts": [result]}
plan = build_source_plan(body)
out = Path(__file__).parent
(out / "pk2611-20260814-source-diagnosis.json").write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
(out / "pk2611-20260814-source-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"status": "planned", "catalog_revision": before, "plan_sha256": plan["plan_sha256"], "request_count": plan["request_count"], "expected_dates": plan["requests"][0]["expected_dates"]}))
