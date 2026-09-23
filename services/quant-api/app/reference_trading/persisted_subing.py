"""DTO adapter for the existing SuBing historical page in persisted mode."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from typing import Callable

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.market_data.subing_reference import SubingReferenceQuery, SubingReferenceService
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict, _decode
from app.reference_trading.repository import _identity_from_row
from app.reference_trading.source_identity import verify_saved_input_prefix


class PersistedSubingReference:
    def __init__(
        self, session_factory, market_service: SubingReferenceService,
        check_cancelled: Callable[[], None] | None = None,
    ) -> None:
        self._factory = session_factory
        self._market = market_service
        self._query = HistoricalReferenceQuery(session_factory)
        self._check_cancelled = check_cancelled or (lambda: None)

    def _stored_manifest(
        self, *, stream_id: str, revision_id: str, seq: int,
    ) -> tuple[object, dict[str, object]]:
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            row = session.get(ReferenceStream, stream_id)
            batch = session.scalar(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.seq <= seq,
                ReferenceBatch.kind.in_(("seed_seal", "calculation")),
            ).order_by(ReferenceBatch.seq.desc()).limit(1))
            if row is None or batch is None:
                raise QueryConflict("SNAPSHOT_CONFLICT")
            return _identity_from_row(row), dict(batch.dependency_manifest)

    @staticmethod
    def _all_points(
        query: HistoricalReferenceQuery, stream_id: str, *, kind: str,
        since: date, through: date, cutoff: datetime, snapshot: str,
        check_cancelled: Callable[[], None] | None = None,
    ) -> list[dict[str, object]]:
        points: list[dict[str, object]] = []
        cursor = None
        while True:
            if check_cancelled is not None:
                check_cancelled()
            page = query.signals(
                stream_id, since=since, through=through, cutoff=cutoff,
                snapshot_token=snapshot, cursor=cursor, limit=200,
                point_kind=kind,
            )
            points.extend(page["items"])
            if len(points) > 10_000:
                raise QueryConflict("PRESENTATION_BUDGET_EXCEEDED")
            cursor = page["next_cursor"]
            if cursor is None:
                return points

    def query(self, request: SubingReferenceQuery) -> dict[str, object]:
        self._check_cancelled()
        since, through, cutoff, as_of = self._market.resolve_read_window(request)
        matches = self._query.streams(
            strategy="subing_reference", product=request.symbol.upper(),
            frequency=request.frequency,
        )
        if not matches:
            raise QueryConflict("NOT_BUILT")
        if len(matches) != 1:
            raise QueryConflict("STREAM_IDENTITY_AMBIGUOUS")
        stream = matches[0]
        stream_id = stream["stream_id"]
        saved_snapshot = None
        if request.before is not None:
            saved_cursor = _decode(request.before, kind="trades")
            saved_snapshot = saved_cursor.get("snapshot")
            if not isinstance(saved_snapshot, str):
                raise QueryConflict("CURSOR_CONFLICT")
        trades = self._query.trades(
            stream_id, since=since, through=through, cutoff=cutoff,
            limit=request.limit, snapshot_token=saved_snapshot,
            cursor=request.before,
        )
        snapshot = trades["snapshot"]
        identity, manifest = self._stored_manifest(
            stream_id=stream_id, revision_id=trades["revision_id"], seq=trades["seq"],
        )
        storage_start = manifest.get("query_since")
        if not isinstance(storage_start, str):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        try:
            source_request = HistoricalStreamRequest(
                identity, date.fromisoformat(storage_start), through, as_of,
            )
            source = MarketDataHistoricalInputReader(
                newow_reader=None, subing_service=self._market,
            ).plan_stream(source_request)
        except (TypeError, ValueError) as exc:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from exc
        verify_saved_input_prefix(manifest, source.dependency_manifest, through)
        self._check_cancelled()
        stats = self._query.summary(
            stream_id, since=since, through=through, cutoff=cutoff,
            snapshot_token=snapshot,
        )
        signals = self._all_points(
            self._query, stream_id, kind="signal", since=since, through=through,
            cutoff=cutoff, snapshot=snapshot, check_cancelled=self._check_cancelled,
        )
        indicators = self._all_points(
            self._query, stream_id, kind="indicator", since=since, through=through,
            cutoff=cutoff, snapshot=snapshot, check_cancelled=self._check_cancelled,
        )
        boundaries = self._all_points(
            self._query, stream_id, kind="boundary", since=since, through=through,
            cutoff=cutoff, snapshot=snapshot, check_cancelled=self._check_cancelled,
        )
        self._check_cancelled()
        quality = (
            self._market.read_daily_quality_presentation(
                symbol=request.symbol, since=since, through=through, cutoff=cutoff,
            ) if request.frequency == "1d" else {}
        )
        boundary_by_segment = {
            (point["value"]["physical_contract"], point["value"]["owner_segment_id"],
             point["value"]["calculation_segment_id"]): point
            for point in boundaries
        }
        quality_by_time = {
            (item["physical_contract"], item["segment_id"], item["bar_end"]): item
            for item in quality.get("quality_interruptions", [])
        }
        items = []
        for trade in trades["items"]:
            self._check_cancelled()
            status = trade["status"]
            boundary = boundary_by_segment.get((
                trade["physical_contract"], trade["owner_segment_id"],
                trade["calculation_segment_id"],
            )) if status not in ("OPEN", "CLOSED") else None
            if status not in ("OPEN", "CLOSED") and boundary is None:
                raise QueryConflict("PRESENTATION_CORRUPT")
            interrupted_at = None if boundary is None else boundary["value"]["bar_end"]
            quality_fact = quality_by_time.get((
                trade["physical_contract"], trade["owner_segment_id"], interrupted_at,
            )) if status == "DATA_INTERRUPTED" else None
            if status == "DATA_INTERRUPTED" and quality_fact is None:
                raise QueryConflict("PRESENTATION_CORRUPT")
            entry_signal = trade["entry_action_id"].removesuffix(":open")
            exit_signal = trade["exit_action_id"]
            items.append({
                "reference_trade_id": trade["public_reference_trade_id"],
                "side": trade["side"], "physical_contract": trade["physical_contract"],
                "segment_id": trade["owner_segment_id"],
                "calculation_segment_id": trade["calculation_segment_id"],
                "entry_signal_id": entry_signal,
                "entry_bar_end": trade["entry_bar_end"],
                "entry_trading_day": trade["entry_trading_day"],
                "entry_reference_price": trade["entry_reference_price"],
                "exit_signal_id": None if exit_signal is None else exit_signal.removesuffix(":close"),
                "exit_bar_end": trade["exit_bar_end"],
                "exit_trading_day": trade["exit_trading_day"],
                "exit_reference_price": trade["exit_reference_price"],
                "status": status, "holding_bars": trade["holding_bars"],
                "reference_return_pct": trade["reference_return"],
                "mark_bar_end": trade["mark_bar_end"],
                "mark_reference_price": trade["mark_reference_price"],
                "mark_change_pct": trade["mark_return"],
                "interrupted_at": interrupted_at,
                "interruption_reason": None if quality_fact is None else quality_fact["classification"],
                "interruption_trading_day": None if quality_fact is None else quality_fact["trading_day"],
                "initial": trade["entry_trading_day"] < since.isoformat(),
            })
        summary = {key: stats[key] for key in (
            "closed_count", "win_count", "loss_count", "flat_count", "open_count",
            "interrupted_count", "rollover_interrupted_count", "data_interrupted_count",
            "initial_count", "win_rate_pct", "mean_return_pct",
            "sum_return_percentage_points",
        )}
        signal_values = [point["value"] for point in signals]
        indicator_values = [point["value"] for point in indicators]
        if request.frequency != "1d":
            summary.pop("rollover_interrupted_count")
            summary.pop("data_interrupted_count")
            for value in (*signal_values, *indicator_values, *items):
                value.pop("calculation_segment_id", None)
            for item in items:
                item.pop("interruption_reason")
                item.pop("interruption_trading_day")
        readiness = (
            (quality.get("coverage_intervals") or [{}])[-1].get("status", "WARMING")
            if request.frequency == "1d" else
            "ready" if any(point["value"].get("macd") is not None for point in indicators)
            else "warming"
        )
        if readiness in ("PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"):
            readiness = "WARMING"
        return {
            "symbol": request.symbol, "frequency": request.frequency,
            "series_kind": "actual_dominant",
            "formula_version": stream["formula_versions"][0],
            "reference_model_version": stream["reference_model_version"],
            "as_of": as_of.isoformat(),
            "performance_since": since.isoformat(),
            "performance_through": through.isoformat(),
            "reference_cutoff": cutoff.isoformat(),
            "input_snapshot_hash": sha256(snapshot.encode()).hexdigest(),
            "executable": False, "auto_order": False, "source": "historical_replay",
            "storage_mode": "persisted",
            "research_status": readiness, "summary": summary,
            "signals": signal_values, "indicators": indicator_values,
            "items": items, "next_before": trades["next_cursor"],
            **quality,
        }
