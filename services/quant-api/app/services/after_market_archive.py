from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.data_center import DataDownloadTask, utc_now
from app.services.rqdata_ingest.actual_contract_bars_pilot import resolve_main_mapping, run_actual_contract_bars_pilot_write
from app.services.trading_session_clock import TradingSessionClock

ARCHIVE_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


class AfterMarketArchiveService:
    """Controlled JM archive orchestrator without poll-live bar对照."""

    def __init__(
        self,
        *,
        session: Session,
        client: Any,
        output_root: Path,
        now: datetime | None = None,
        trading_clock: TradingSessionClock | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.output_root = output_root
        self.now = now or datetime.now(UTC)
        self.trading_clock = trading_clock or TradingSessionClock(session)

    def archive_once(
        self,
        *,
        trading_day: date,
        enabled: bool,
        confirmed: bool,
        product: str = "jm",
    ) -> dict[str, Any]:
        normalized_product = str(product).strip().lower()
        if normalized_product != "jm":
            raise ValueError("V1 after-market archive only permits product=jm")
        if not enabled:
            return _blocked_payload(normalized_product, trading_day, "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED is false")
        if not confirmed:
            return _blocked_payload(normalized_product, trading_day, "explicit archive confirmation is required")

        mapping = resolve_main_mapping(self.session, product=normalized_product, trade_date=trading_day)
        actual_contract = mapping.contract_code
        exchange = "DCE"
        if not self.trading_clock.trading_day_closed(
            trading_day,
            product=normalized_product,
            exchange=exchange,
            now=self.now,
        ):
            return _blocked_payload(normalized_product, trading_day, "trading day is not closed")

        from sqlalchemy import select

        task_no = f"archive:{normalized_product}:{actual_contract}:{trading_day.isoformat()}"
        task = self.session.scalar(select(DataDownloadTask).where(DataDownloadTask.task_no == task_no))
        if task is not None and task.status == "success":
            return {"status": "already_archived", "task_no": task_no, "result": task.result}
        if task is None:
            task = DataDownloadTask(
                task_no=task_no,
                provider="rqdata",
                data_type="after_market_archive",
                instrument_symbol=normalized_product,
                contract_code=actual_contract,
                period="1m_bundle",
                start_time=datetime.combine(trading_day, time.min),
                end_time=datetime.combine(trading_day, time.max),
                status="running",
                progress=0,
                result={},
                started_at=utc_now(),
            )
            self.session.add(task)
        else:
            task.status = "running"
            task.error_message = None
            task.started_at = utc_now()
            task.finished_at = None
        self.session.flush()

        expected_rows = self.trading_clock.expected_minute_count(
            trading_day,
            product=normalized_product,
            exchange=exchange,
        )
        try:
            archive = run_actual_contract_bars_pilot_write(
                session=self.session,
                client=self.client,
                output_root=self.output_root,
                product=normalized_product,
                trade_date=trading_day,
                start_date=trading_day,
                end_date=trading_day,
                periods=ARCHIVE_PERIODS,
                jm_only=True,
                local_daily=True,
                expected_source_rows=expected_rows,
            )
        except Exception as exc:
            task.status = "failed"
            task.error_message = _safe_error_message(exc)
            task.finished_at = utc_now()
            task.result = {
                "quality_gate": "failed",
                "error_type": type(exc).__name__,
            }
            self.session.flush()
            return {"status": "failed", "task_no": task_no, "result": task.result}

        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "quality_gate": archive["quality_gate"],
            "manifest_path": archive["manifest_path"],
            "periods": archive["periods"],
            "historical_active_source": "rqdata_after_market_direct",
        }
        self.session.flush()
        return {"status": "success", "task_no": task_no, "result": task.result}


def _blocked_payload(product: str, trading_day: date, reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "product": product,
        "trading_day": trading_day.isoformat(),
        "reason": reason,
        "would_call_rqdata": False,
        "would_write_database": False,
        "would_write_parquet": False,
        "would_register_primary": False,
    }


def _safe_error_message(exc: Exception) -> str | None:
    value = str(exc).strip()
    if not value:
        return None
    lowered = value.lower()
    if any(part in lowered for part in ("password", "secret", "token", "webhook", "license", "cookie", "key")):
        return None
    return value[:200]
