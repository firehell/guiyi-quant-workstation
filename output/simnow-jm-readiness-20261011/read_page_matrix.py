"""Read-only JM page comparison at one fixed completed-input cutoff."""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import (
    build_database_coverage_source,
    build_market_data_service,
)
from app.market_data.newow.experiments import ExperimentQuery, NewowExperimentService
from app.market_data.newow.product_reader import NewowProductReader
from app.market_data.newow.product_release import candidate_input_quality_policy
from app.market_data.newow.product_service import NewowProductService, ProductSection, ProductServiceQuery
from app.market_data.operational_universe import load_active_products
from guiyi_quant.newow.oscillation_experiments import ExperimentKind
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

ROOT = Path(__file__).resolve().parent
SINCE = date(2025, 10, 11)
THROUGH = date(2026, 10, 10)
AS_OF = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,100}\Z")


def failure(exc: Exception) -> dict[str, str]:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not SAFE_CODE.fullmatch(code):
        message = str(exc)
        code = message if SAFE_CODE.fullmatch(message) else type(exc).__name__
    return {"status": "BLOCKED", "code": code}


def save(frequency: str, rows: list[dict]) -> None:
    target = ROOT / f"{frequency}.json"
    temporary = ROOT / f"{frequency}.json.tmp"
    temporary.write_text(json.dumps({
        "head": "c89a612fa61e01342b8c70cd421618d7969322e5",
        "product": "jm", "frequency": frequency,
        "requested_window": [SINCE.isoformat(), THROUGH.isoformat()],
        "as_of_utc": AS_OF.isoformat(), "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)


def main(frequency: str) -> None:
    selected = ProductFrequency(frequency)
    rows: list[dict] = []
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=900):
        market = build_market_data_service(session)
        coverage = build_database_coverage_source(session)
        active = load_active_products()
        policy = candidate_input_quality_policy("jm", selected, candidate_weekly=False)

        def make_reader(context=(), cancelled=None):
            return NewowProductReader(
                market, coverage=coverage, active_products=active,
                context_frequencies=context, cancelled=cancelled,
                input_quality_policy=policy,
            )

        service = NewowProductService(make_reader, quality_policy=policy, reuse_read_inputs=True)
        for name, strategy, fusion in (
            ("trend", ProductStrategy.TREND, False),
            ("oscillation", ProductStrategy.OSCILLATION, False),
            ("dual_fusion", ProductStrategy.TREND, True),
        ):
            try:
                result = service.query(ProductServiceQuery(
                    product="jm", strategy=strategy, frequency=selected,
                    section=ProductSection.REFERENCE,
                    performance_since=SINCE, performance_through=THROUGH,
                    as_of=AS_OF, include_fusion=fusion,
                ))
                value = result.reference.value
                if value is None:
                    raise ValueError("NEWOW_REFERENCE_VALUE_MISSING")
                if fusion:
                    fusion_value = value.fusion_comparison
                    performance = fusion_value["page_performance"]
                else:
                    performance = value.page_performance
                ordinary = performance.get("ordinary") if performance else None
                rows.append({
                    "strategy": name, "status": "OK" if ordinary else "NO_SEGMENT",
                    "page_version": performance.get("version") if performance else None,
                    "page_parity": performance.get("page_parity") if performance else None,
                    "executable": performance.get("executable") if performance else None,
                    "request_formula_versions": list(result.meta.identity.formula_versions),
                    "fusion_source_formula_versions": fusion_value.get("source_formula_versions") if fusion else None,
                    "fusion_source_profiles": fusion_value.get("source_profiles") if fusion else None,
                    "fusion_reference_model_version": fusion_value.get("reference_model_version") if fusion else None,
                    "fusion_reference_revision": fusion_value.get("reference_revision") if fusion else None,
                    "input_sha256": performance.get("input_sha256") if performance else None,
                    "source_evidence_sha256": performance.get("source_evidence_sha256") if performance else None,
                    "actual_available_through": value.actual_available_through.isoformat(),
                    "cutoff_utc": value.reference_cutoff.isoformat(),
                    "history_coverage": value.history_coverage,
                    "unavailable_days": [day.isoformat() for day in value.unavailable_days],
                    "coverage_interval_statuses": [interval.status for interval in value.coverage_intervals],
                    "summary": ordinary.get("summary") if ordinary else None,
                    "interrupted_count": performance.get("ordinary_interrupted_count") if performance else None,
                    "segment_count": performance.get("segment_count") if performance else None,
                })
            except Exception as exc:
                rows.append({"strategy": name, **failure(exc)})
            save(frequency, rows)

        experiment = NewowExperimentService(make_reader(), now=lambda: datetime.now(UTC))
        for kind in ExperimentKind:
            try:
                result = experiment.query(ExperimentQuery(
                    "jm", selected, kind, AS_OF, SINCE, THROUGH, 500, False,
                ))
                segments = result["segments"]
                summaries = [s["ordinary"]["summary"] for s in segments if s.get("ordinary")]
                last_completed_bar = max(
                    (datetime.fromisoformat(s["statistics_window"]["through"]) for s in segments
                     if s.get("statistics_window")), default=None,
                )
                rows.append({
                    "strategy": kind.value, "status": "OK" if summaries else "NO_SEGMENT",
                    "formula_version": result["formula_version"],
                    "page_parity": result["page_parity"],
                    "executable": result["executable"],
                    "input_snapshot_hash": result["input_snapshot_hash"],
                    "requested_through": result["window"]["through"],
                    "last_completed_bar_utc": last_completed_bar.isoformat() if last_completed_bar else None,
                    "last_completed_trading_date_shanghai": last_completed_bar.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() if last_completed_bar else None,
                    "terminal_eligible": result["window"]["terminal_eligible"],
                    "segment_count": len(segments),
                    "readiness": result["readiness"],
                    "segment_readiness": [s["readiness"] for s in segments],
                    "summary_segment_sum_rounded_pp": str(sum((Decimal(s["cum_return_percentage_points"]) for s in summaries), Decimal(0))),
                    "summary_segment_trade_count": sum(s["trade_count"] for s in summaries),
                    "summary_max_segment_drawdown_pp": str(max((Decimal(s["max_drawdown_percentage_points"]) for s in summaries), default=Decimal(0))),
                    "segment_summaries": summaries,
                    "segment_statuses": [s["status"] for s in segments],
                })
            except Exception as exc:
                rows.append({"strategy": kind.value, **failure(exc)})
            save(frequency, rows)


if __name__ == "__main__":
    frequencies = ("60m", "1d", "1w", "5m", "15m", "30m")
    if len(sys.argv) != 2 or sys.argv[1] not in {*frequencies, "all"}:
        raise SystemExit("frequency required")
    for frequency in frequencies if sys.argv[1] == "all" else (sys.argv[1],):
        try:
            main(frequency)
        except Exception as exc:
            save(frequency, [{"strategy": "_source", **failure(exc)}])
