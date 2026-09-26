"""Persisted Newow reference section over the existing bounded MDS read."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict, _decode
from app.reference_trading.repository import _identity_from_row
from app.reference_trading.source_identity import verify_saved_input_prefix


class PersistedNewowReference:
    def __init__(self, session_factory) -> None:
        self._factory = session_factory
        self._query = HistoricalReferenceQuery(session_factory)

    def _manifest(self, stream_id: str, revision_id: str, seq: int):
        with self._factory() as session, readonly_transaction(session, timeout_seconds=30):
            stream = session.get(ReferenceStream, stream_id)
            batch = session.scalar(select(ReferenceBatch).where(
                ReferenceBatch.stream_id == stream_id,
                ReferenceBatch.revision_id == revision_id,
                ReferenceBatch.seq <= seq,
                ReferenceBatch.kind.in_(("seed_seal", "calculation")),
            ).order_by(ReferenceBatch.seq.desc()).limit(1))
            if stream is None or batch is None:
                raise QueryConflict("SNAPSHOT_CONFLICT")
            return _identity_from_row(stream), dict(batch.dependency_manifest)

    def _points(
        self, stream_id: str, kind: str, since: date, through: date,
        cutoff: datetime, snapshot: str,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        cursor = None
        while True:
            page = self._query.signals(
                stream_id, since=since, through=through, cutoff=cutoff,
                snapshot_token=snapshot, cursor=cursor, limit=200,
                point_kind=kind,
            )
            result.extend(page["items"])
            if len(result) > 10_000:
                raise QueryConflict("PRESENTATION_BUDGET_EXCEEDED")
            cursor = page["next_cursor"]
            if cursor is None:
                return result

    @staticmethod
    def _coverage(points, gaps, since: date, through: date):
        events = []
        for point in points:
            value = point["value"]
            events.append((
                point["trading_day"],
                "VALID" if value["status"] == "ready" else "WARMING",
                value["physical_contract"], value["segment_id"],
                value["calculation_segment_id"],
            ))
        for gap in gaps:
            if since <= gap.trading_day <= through:
                events.append((
                    gap.trading_day.isoformat(), "PRICE_UNAVAILABLE",
                    gap.physical_contract, gap.segment_id, None,
                ))
        grouped: dict[str, list[tuple]] = {}
        for event in events:
            grouped.setdefault(event[0], []).append(event)
        intervals: list[dict[str, object]] = []
        for day in sorted(grouped):
            same = grouped[day]
            if len({(item[2], item[3], item[4]) for item in same}) > 1:
                raise QueryConflict("COVERAGE_IDENTITY_CONFLICT")
            status = (
                "PRICE_UNAVAILABLE" if any(item[1] == "PRICE_UNAVAILABLE" for item in same)
                else "WARMING" if any(item[1] == "WARMING" for item in same)
                else "VALID"
            )
            event = same[0]
            current = {
                "since": day, "through": day, "status": status,
                "physical_contract": event[2], "segment_id": event[3],
                "calculation_segment_id": event[4],
            }
            if intervals and all(
                intervals[-1][key] == current[key]
                for key in ("status", "physical_contract", "segment_id", "calculation_segment_id")
            ):
                intervals[-1]["through"] = day
            else:
                intervals.append(current)
        return intervals

    @staticmethod
    def _hint_ids(trades, actions, hints, cutoff: datetime):
        positions = set()
        action_bars = set()
        for point in actions:
            value = point["value"]
            key = (value["physical_contract"], value["segment_id"], value["bar_end"])
            action_bars.add(key)
            positions.add((*key, value["sequence"]))
        attached = {item["reference_trade_id"]: [] for item in trades}
        for point in hints:
            hint = point["value"]
            if (
                hint.get("retrospective") is not False
                or str(hint.get("kind", "")).casefold() in {"control_mirror", "zhaoyaojing"}
            ):
                raise QueryConflict("PRESENTATION_CORRUPT")
            known_at = datetime.fromisoformat(hint["known_at"])
            if known_at > cutoff:
                continue
            key = (hint["physical_contract"], hint["segment_id"], hint["bar_end"])
            sequence = hint.get("sequence")
            if (sequence is None and key in action_bars) or (*key, sequence) in positions:
                continue
            matches = []
            for trade in trades:
                if key[:2] != (trade["physical_contract"], trade["owner_segment_id"]):
                    continue
                if hint.get("calculation_segment_id", hint["segment_id"]) != trade.get(
                    "calculation_segment_id", trade["owner_segment_id"],
                ):
                    continue
                at = datetime.fromisoformat(hint["bar_end"])
                entry = datetime.fromisoformat(trade["entry_bar_end"])
                if sequence is None:
                    if at <= entry:
                        continue
                elif (at, sequence) <= (entry, trade["entry_sequence"]):
                    continue
                if trade["status"] == "CLOSED":
                    exit_at = datetime.fromisoformat(trade["exit_bar_end"])
                    if sequence is None:
                        if at >= exit_at:
                            continue
                    elif (at, sequence) >= (exit_at, trade["exit_sequence"]):
                        continue
                elif trade["status"] in {"ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"}:
                    interrupted = datetime.fromisoformat(trade["interrupted_at"])
                    if at > interrupted:
                        continue
                elif at > cutoff:
                    continue
                matches.append(trade["reference_trade_id"])
            if len(matches) == 1:
                attached[matches[0]].append(hint["hint_id"])
        return attached

    def section(self, request, read, identity, reader, fact_key, _page_identity, resolved):
        from guiyi_quant.newow.product_contracts import (
            EvidenceStatus, FeatureRuntimeStatus, FeatureStatus,
        )
        from app.market_data.newow.product_service import (
            PersistedReferenceSectionValue, SectionDelivery, _has_unresolved_tail_gap,
        )

        matches = self._query.streams(
            strategy=f"newow_{request.strategy.value}", product=request.product,
            frequency=request.frequency.value,
        )
        if not matches:
            raise QueryConflict("NOT_BUILT")
        if len(matches) != 1:
            raise QueryConflict("STREAM_IDENTITY_AMBIGUOUS")
        stream_id = matches[0]["stream_id"]
        since, through, cutoff = (
            resolved.requested_since, resolved.requested_through, resolved.cutoff,
        )
        saved_snapshot = None
        if request.history_before is not None:
            cursor = _decode(request.history_before, kind="trades")
            saved_snapshot = cursor.get("snapshot")
            if not isinstance(saved_snapshot, str):
                raise QueryConflict("CURSOR_CONFLICT")
        page = self._query.trades(
            stream_id, since=since, through=through, cutoff=cutoff,
            limit=request.history_limit, snapshot_token=saved_snapshot,
            cursor=request.history_before,
        )
        snapshot = page["snapshot"]
        stream_identity, manifest = self._manifest(
            stream_id, page["revision_id"], page["seq"],
        )
        storage_start = manifest.get("query_since")
        if not isinstance(storage_start, str):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        try:
            source_request = HistoricalStreamRequest(
                stream_identity, date.fromisoformat(storage_start),
                resolved.actual_through, cutoff,
            )
            source = MarketDataHistoricalInputReader(
                newow_reader=reader, subing_service=None,
            ).plan_stream(source_request)
        except (TypeError, ValueError) as exc:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED") from exc
        verify_saved_input_prefix(
            manifest, source.dependency_manifest, resolved.actual_through,
            frozenset((bar.physical_contract, bar.owner_segment_id)
                      for bar in source.bars if bar.strategy_input),
        )
        stats = self._query.summary(
            stream_id, since=since, through=through, cutoff=cutoff,
            snapshot_token=snapshot,
        )
        availability = self._points(stream_id, "availability", since, resolved.actual_through, cutoff, snapshot)
        boundaries = self._points(stream_id, "boundary", since, resolved.actual_through, cutoff, snapshot)
        hints = self._points(stream_id, "hint", date.fromisoformat(storage_start), resolved.actual_through, cutoff, snapshot)
        actions = self._points(stream_id, "action", date.fromisoformat(storage_start), resolved.actual_through, cutoff, snapshot)
        boundary_by_owner = {
            (item["value"]["physical_contract"], item["value"]["owner_segment_id"]): item
            for item in boundaries
        }
        for item in page["items"]:
            if item["status"] not in ("OPEN", "CLOSED") and item.get("interrupted_at") is None:
                boundary = boundary_by_owner.get((item["physical_contract"], item["owner_segment_id"]))
                if boundary is None:
                    raise QueryConflict("PRESENTATION_CORRUPT")
                item["interrupted_at"] = boundary["value"]["bar_end"]
        hint_ids = self._hint_ids(page["items"], actions, hints, cutoff)
        output_items = []
        for item in page["items"]:
            status = item["status"]
            has_prior_mark = item.get("prior_mark_bar_end") is not None
            reason = None
            if status not in ("OPEN", "CLOSED"):
                reason = (
                    "SOURCE_PRICE_UNAVAILABLE" if status == "DATA_INTERRUPTED"
                    else "OWNER_BOUNDARY"
                ) if has_prior_mark else "OWNER_BOUNDARY_MARK_UNAVAILABLE"
            output_items.append({
                "reference_trade_id": item["public_reference_trade_id"],
                "product": request.product, "strategy_code": request.strategy.value,
                "frequency": request.frequency.value,
                "physical_contract": item["physical_contract"],
                "segment_id": item["owner_segment_id"],
                "calculation_segment_id": item["calculation_segment_id"],
                "formula_versions": list(identity.formula_versions),
                "reference_model_version": matches[0]["reference_model_version"],
                "futures_adaptation_version": matches[0]["futures_adaptation_version"],
                **({"input_quality_policy": identity.input_quality_policy.value}
                   if identity.input_quality_policy.value != "newow_input_quality_v1" else {}),
                "entry_signal_id": item["entry_action_id"],
                "entry_sequence": item["entry_sequence"],
                "entry_bar_end": item["entry_bar_end"],
                "entry_trading_day": item["entry_trading_day"],
                "entry_reference_price": item["entry_reference_price"],
                "exit_signal_id": item["exit_action_id"],
                "exit_bar_end": item["exit_bar_end"],
                "exit_trading_day": item["exit_trading_day"],
                "exit_reference_price": item["exit_reference_price"],
                "status": status, "holding_bars": item["holding_bars"],
                "reference_return_pct": item["reference_return"],
                "mark_bar_end": item["mark_bar_end"] if status == "OPEN" else item.get("prior_mark_bar_end"),
                "mark_reference_price": item["mark_reference_price"] if status == "OPEN" else item.get("prior_mark_reference_price"),
                "mark_change_pct": item["mark_return"] if status == "OPEN" else item.get("prior_mark_change_pct"),
                "interrupted_at": item.get("interrupted_at"),
                "interruption_reason": reason,
                "statistics_membership": "initial_before_window" if item["entry_trading_day"] < since.isoformat() else "entry_in_window_v1",
                "hint_ids": hint_ids.get(item["reference_trade_id"], []),
            })
        intervals = self._coverage(availability, read.data_interruptions, since, resolved.actual_through)
        unavailable = sorted({
            gap.trading_day.isoformat() for gap in read.data_interruptions
            if since <= gap.trading_day <= resolved.actual_through
        })
        payload = {
            "performance_since": since.isoformat(),
            "performance_through": through.isoformat(),
            "actual_available_through": resolved.actual_through.isoformat(),
            "reference_cutoff": cutoff.isoformat(),
            "reference_input_sha256": fact_key,
            "history_coverage": "PARTIAL" if any(i["status"] != "VALID" for i in intervals) else "FULL",
            "unavailable_days": unavailable, "coverage_intervals": intervals,
            "summary": {**{key: stats[key] for key in (
                "closed_count", "win_count", "loss_count", "flat_count",
                "win_rate_pct", "mean_return_pct", "sum_return_percentage_points",
                "open_count", "interrupted_count", "rollover_interrupted_count",
                "data_interrupted_count", "initial_count",
            )}, "membership_policy": "entry_in_window_v1"},
            "items": output_items, "next_before": page["next_cursor"],
            "executable": False, "auto_order": False,
            "storage_mode": "persisted",
            "allowed_uses": ["page_parity_reference", "research_display"],
        }
        warming = (
            not resolved.complete or _has_unresolved_tail_gap(read)
            or bool(availability and availability[-1]["value"]["status"] != "ready")
        )
        status = FeatureStatus(
            FeatureRuntimeStatus.WARMING if warming else FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
            (resolved.reason_code or "NEWOW_REFERENCE_WINDOW_PARTIAL") if warming else None,
        )
        return SectionDelivery(
            "delivered", status, PersistedReferenceSectionValue(payload),
        )
