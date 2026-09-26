"""Read-only PF W1 readiness against the actual post-apply Catalog pointer."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.newow.readiness_composition import build_newow_readiness
from guiyi_quant.newow.product_contracts import ProductFrequency
from scripts.newow_weekly_recovery import load_private_readonly_settings

here = Path(__file__).resolve().parent
settings, _ = load_private_readonly_settings(
    Path.home() / "Library/Application Support/GuiyiQuant/project.env"
)
engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
try:
    with Session(engine, autoflush=False) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        report = build_newow_readiness(session, request=ReadinessRequest(
            products=("pf",),
            as_of=datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00"),
            matrix=True, max_work=100000, timeout_seconds=600,
            frequencies=(ProductFrequency.WEEKLY,), candidate_weekly=True,
        ))
        cases = [case for case in report["cases"] if case["frequency"] == "1w"]
        summary = {
            "status": report["status"], "complete": report["complete"],
            "budget_exhausted": report["budget_exhausted"],
            "weekly": [{
                "strategy": case["strategy"], "main": case["main"],
                "sections": case["sections"],
            } for case in cases],
            "basis": "actual post-apply Catalog read; candidate weekly policy; no Scope change",
        }
        (here / "pf-post-apply-readiness.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        print(json.dumps({
            "status": summary["status"], "complete": summary["complete"],
            "weekly": [(
                case["strategy"], case["main"]["status"],
                case["sections"]["reference"]["status"],
            ) for case in cases],
        }))
        session.rollback()
finally:
    engine.dispose()
