from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, StrategySignal
from app.services.market_data_reader import MarketDataReader


@dataclass(frozen=True)
class ReviewLineageError(ValueError):
    code: str
    context: dict[str, Any]

    def __str__(self) -> str:
        return self.code


def resolve_review_source_lineage(session: Session, *, source_type: str, source_id: int) -> dict[str, Any]:
    raw_snapshot: dict[str, Any] | None
    bar_start: datetime | str | None = None
    bar_end: datetime | str | None = None
    htdy_event_identity: tuple[str, str, str] | None = None
    if source_type == "backtest_report":
        report = session.get(BacktestReportModel, source_id)
        if report is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        raw_snapshot = report.binding_snapshot if isinstance(report.binding_snapshot, dict) else None
        metadata = (report.summary or {}).get("report_metadata")
        if isinstance(metadata, dict):
            bar_start = metadata.get("start")
            bar_end = metadata.get("end")
    elif source_type == "backtest_trade":
        trade = session.get(BacktestTradeModel, source_id)
        if trade is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        report = session.get(BacktestReportModel, trade.report_id)
        raw_snapshot = report.binding_snapshot if report and isinstance(report.binding_snapshot, dict) else None
        bar_start, bar_end = trade.open_time, trade.close_time
    elif source_type == "strategy_signal":
        signal = session.get(StrategySignal, source_id)
        if signal is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        value = (signal.features or {}).get("formal_lineage")
        raw_snapshot = value if isinstance(value, dict) else None
        bar_start, bar_end = signal.bar_start, signal.bar_end
    elif source_type == "signal_event":
        event = session.get(SignalEvent, source_id)
        if event is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        value = (event.payload or {}).get("formal_lineage")
        raw_snapshot = value if isinstance(value, dict) else None
        bar_start, bar_end = event.bar_start, event.bar_end
        if (
            event.strategy_name == "htdy_original_realtime_first_seen"
            or event.source_mode == "live_realtime_repainting"
        ):
            htdy_event_identity = (
                event.strategy_name,
                event.strategy_version,
                event.source_mode,
            )
    else:
        raise _error("REVIEW_SOURCE_TYPE_UNSUPPORTED", source_type, source_id)

    if not raw_snapshot:
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", source_type, source_id)
    if htdy_event_identity is not None and (
        htdy_event_identity
        != (
            "htdy_original_realtime_first_seen",
            "v1.0",
            "live_realtime_repainting",
        )
        or raw_snapshot.get("schema_version")
        != "signal_review_lineage_v2"
    ):
        raise _error(
            "REVIEW_HTDY_LINEAGE_SCHEMA_INVALID",
            source_type,
            source_id,
        )
    primary = raw_snapshot.get("primary")
    if not isinstance(primary, dict):
        raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id)
    if not isinstance(primary.get("market_data_file_id"), int):
        raise _error("REVIEW_MARKET_FILE_MISSING", source_type, source_id)
    if primary.get("data_role") != "primary" or primary.get("quality_status") != "passed":
        raise _error("REVIEW_LINEAGE_QUALITY_BLOCKED", source_type, source_id)

    raw_bar = raw_snapshot.get("bar") if isinstance(raw_snapshot.get("bar"), dict) else {}
    start_value = _iso(bar_start) or raw_bar.get("bar_start") or primary.get("coverage_start")
    end_value = _iso(bar_end) or raw_bar.get("bar_end") or primary.get("coverage_end")
    if not start_value or not end_value:
        raise _error("REVIEW_BAR_WINDOW_MISSING", source_type, source_id)
    return {
        "schema_version": "review_source_lineage_v1",
        "source_type": source_type,
        "source_id": source_id,
        "source_snapshot_schema_version": raw_snapshot.get("schema_version"),
        "resolver_name": raw_snapshot.get("resolver_name"),
        "resolver_contract_version": raw_snapshot.get("resolver_contract_version"),
        "quality_policy": raw_snapshot.get("quality_policy"),
        "primary": deepcopy(primary),
        "context_assets": deepcopy(raw_snapshot.get("context_assets") or raw_snapshot.get("auxiliary") or []),
        "bar": {
            "bar_start": start_value,
            "bar_end": end_value,
            "trigger_price": raw_bar.get("trigger_price"),
            "confirmation_mode": raw_bar.get("confirmation_mode"),
        },
    }


def load_review_bars(
    session: Session,
    note: ReviewNote,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    lineage = (note.extra or {}).get("formal_lineage")
    if not isinstance(lineage, dict):
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", note.source_type, int(note.source_id or 0))
    primary = lineage.get("primary")
    bar = lineage.get("bar")
    if not isinstance(primary, dict) or not isinstance(bar, dict):
        raise _error("REVIEW_LINEAGE_INVALID", note.source_type, int(note.source_id or 0))
    try:
        rows = MarketDataReader(session, project_root=project_root).load_bars_from_market_file(
            market_data_file_id=int(primary["market_data_file_id"]),
            symbol=str(primary["instrument_symbol"]),
            contract=str(primary["contract_code"]),
            period=str(primary["period"]),
            start=_datetime(bar["bar_start"]),
            end=_datetime(bar["bar_end"]),
            passed_only=True,
            expected_provider=str(primary["provider"]),
            expected_data_role=str(primary["data_role"]),
            expected_quality_status=str(primary["quality_status"]),
            expected_data_version=str(primary["data_version"]),
            expected_checksum=str(primary["checksum"]) if primary.get("checksum") is not None else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _error("REVIEW_EXACT_BARS_UNAVAILABLE", note.source_type, int(note.source_id or 0)) from exc
    if not rows:
        raise _error("REVIEW_EXACT_BARS_UNAVAILABLE", note.source_type, int(note.source_id or 0))
    return {"lineage": deepcopy(lineage), "bars": rows}


def _error(code: str, source_type: str, source_id: int) -> ReviewLineageError:
    return ReviewLineageError(code=code, context={"source_type": source_type, "source_id": source_id})


def _iso(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
