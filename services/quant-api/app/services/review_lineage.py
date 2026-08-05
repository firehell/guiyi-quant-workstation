from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.data_core.consumer_identity import (
    CanonicalConsumerInput,
    build_canonical_consumer_input,
)
from app.data_core.contracts import DataCoreError
from app.db.session import PROJECT_ROOT
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, StrategySignal
from app.services.canonical_market_data import build_canonical_reader
from app.services.market_data_service import MarketDataService
from app.signal.formal_identity import parse_formal_auxiliary_identities


@dataclass
class ReviewLineageError(ValueError):
    code: str
    context: dict[str, Any]

    def __str__(self) -> str:
        return self.code


def resolve_review_source_lineage(session: Session, *, source_type: str, source_id: int) -> dict[str, Any]:
    raw_snapshot: dict[str, Any] | None
    source_row: StrategySignal | SignalEvent | None = None
    source_input_snapshot: dict[str, Any] | None = None
    bar_start: datetime | str | None = None
    bar_end: datetime | str | None = None
    strategy_version: str | None = None
    if source_type == "strategy_signal":
        signal = session.get(StrategySignal, source_id)
        if signal is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        value = (signal.features or {}).get("formal_lineage")
        raw_snapshot = value if isinstance(value, dict) else None
        source_row = signal
        source_value = (signal.features or {}).get("input_identity")
        source_input_snapshot = source_value if isinstance(source_value, dict) else None
        strategy_version = signal.strategy_version
        bar_start, bar_end = signal.bar_start, signal.bar_end
    elif source_type == "signal_event":
        event = session.get(SignalEvent, source_id)
        if event is None:
            raise _error("REVIEW_SOURCE_NOT_FOUND", source_type, source_id)
        value = (event.payload or {}).get("formal_lineage")
        raw_snapshot = value if isinstance(value, dict) else None
        source_row = event
        source_value = (event.payload or {}).get("input_identity")
        source_input_snapshot = source_value if isinstance(source_value, dict) else None
        strategy_version = event.strategy_version
        bar_start, bar_end = event.bar_start, event.bar_end
    else:
        raise _error("REVIEW_SOURCE_TYPE_UNSUPPORTED", source_type, source_id)

    if not raw_snapshot:
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", source_type, source_id)
    input_snapshot = _canonical_input_snapshot(raw_snapshot)
    if input_snapshot is not None:
        auxiliary_snapshots = _canonical_auxiliary_snapshots(
            raw_snapshot,
            source_type=source_type,
            source_id=source_id,
        )
        try:
            identity = CanonicalConsumerInput.from_snapshot(input_snapshot)
        except (DataCoreError, TypeError, ValueError) as exc:
            raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id) from exc
        if source_row is not None:
            try:
                parse_formal_auxiliary_identities(identity, auxiliary_snapshots)
            except (TypeError, ValueError) as exc:
                raise _error(
                    "REVIEW_SOURCE_IDENTITY_MISMATCH",
                    source_type,
                    source_id,
                ) from exc
            _validate_canonical_signal_source(
                source_row,
                identity=identity,
                formal_input_snapshot=input_snapshot,
                source_input_snapshot=source_input_snapshot,
                source_type=source_type,
                source_id=source_id,
            )
        else:
            try:
                auxiliary_identities = {
                    period: CanonicalConsumerInput.from_snapshot(snapshot)
                    for period, snapshot in auxiliary_snapshots.items()
                }
            except (DataCoreError, TypeError, ValueError) as exc:
                raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id) from exc
            if any(
                period != auxiliary.request.frequency.value
                or auxiliary.strategy_input_version
                != identity.strategy_input_version
                for period, auxiliary in auxiliary_identities.items()
            ):
                raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id)
        if (
            not strategy_version
            or _identity_strategy_version(identity) != strategy_version
            or (
                raw_snapshot.get("strategy_version") is not None
                and raw_snapshot.get("strategy_version") != strategy_version
            )
        ):
            raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id)
        return {
            "schema_version": "review_canonical_lineage_v1",
            "source_type": source_type,
            "source_id": source_id,
            "strategy_version": strategy_version,
            "input_digest": identity.digest,
            "dataset_keys": deepcopy(input_snapshot["source_datasets"]),
            "manifest_digests": list(identity.manifest_digests),
            "window": {
                "start": identity.request.start.isoformat(),
                "end": identity.request.end.isoformat(),
            },
            "source_window": {
                "start": _iso(bar_start),
                "end": _iso(bar_end),
            },
            "input_identity": deepcopy(input_snapshot),
            "auxiliary_input_identities": deepcopy(auxiliary_snapshots),
        }
    if raw_snapshot.get("schema_version") != "signal_review_lineage_v2" and not _is_live_snapshot(raw_snapshot):
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", source_type, source_id)
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
    resolved = {
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
    if raw_snapshot.get("schema_version") == "signal_review_lineage_v2":
        resolved["source_snapshot"] = deepcopy(raw_snapshot)
    return resolved


def load_review_bars(
    session: Session,
    note: ReviewNote,
    *,
    project_root: Path = PROJECT_ROOT,
    market_data: MarketDataService | None = None,
) -> dict[str, Any]:
    del project_root
    lineage = (note.extra or {}).get("formal_lineage")
    if not isinstance(lineage, dict):
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", note.source_type, int(note.source_id or 0))
    if lineage.get("schema_version") == "review_canonical_lineage_v1":
        input_snapshot = lineage.get("input_identity")
        if not isinstance(input_snapshot, dict):
            raise _error("REVIEW_LINEAGE_INVALID", note.source_type, int(note.source_id or 0))
        auxiliary_snapshots = lineage.get("auxiliary_input_identities")
        if not isinstance(auxiliary_snapshots, dict):
            raise _error("REVIEW_LINEAGE_UNAVAILABLE", note.source_type, int(note.source_id or 0))
        try:
            identity = CanonicalConsumerInput.from_snapshot(input_snapshot)
            if note.source_type in {"strategy_signal", "signal_event"}:
                auxiliary_identities = parse_formal_auxiliary_identities(
                    identity,
                    auxiliary_snapshots,
                )
            else:
                auxiliary_identities = {
                    str(period): CanonicalConsumerInput.from_snapshot(snapshot)
                    for period, snapshot in auxiliary_snapshots.items()
                    if isinstance(period, str) and isinstance(snapshot, dict)
                }
                if len(auxiliary_identities) != len(auxiliary_snapshots):
                    raise ValueError("invalid auxiliary identity")
            service = market_data or MarketDataService(
                session,
                canonical_reader=build_canonical_reader(session),
            )
            result = service.get_bars(identity.request)
            confirmed = build_canonical_consumer_input(
                identity.request,
                result,
                strategy_input_version=identity.strategy_input_version,
            )
            auxiliary_results: dict[str, Any] = {}
            confirmed_auxiliary: dict[str, CanonicalConsumerInput] = {}
            for period, auxiliary in sorted(auxiliary_identities.items()):
                if note.source_type not in {"strategy_signal", "signal_event"} and (
                    period != auxiliary.request.frequency.value
                    or auxiliary.strategy_input_version != identity.strategy_input_version
                ):
                    raise ValueError("invalid auxiliary identity")
                auxiliary_result = service.get_bars(auxiliary.request)
                auxiliary_results[period] = auxiliary_result
                confirmed_auxiliary[period] = build_canonical_consumer_input(
                    auxiliary.request,
                    auxiliary_result,
                    strategy_input_version=auxiliary.strategy_input_version,
                )
        except (DataCoreError, TypeError, ValueError) as exc:
            raise _error(
                "REVIEW_EXACT_BARS_UNAVAILABLE",
                note.source_type,
                int(note.source_id or 0),
            ) from exc
        auxiliary_changed = any(
            confirmed_auxiliary[period].to_snapshot() != auxiliary_snapshots[period]
            for period in auxiliary_identities
        )
        if (
            confirmed.to_snapshot() != input_snapshot
            or lineage.get("input_digest") != identity.digest
            or lineage.get("strategy_version") != note.strategy_version
            or _identity_strategy_version(identity) != note.strategy_version
            or auxiliary_changed
        ):
            raise _error(
                "REVIEW_EXACT_BARS_IDENTITY_CHANGED",
                note.source_type,
                int(note.source_id or 0),
            )
        return {
            "lineage": deepcopy(lineage),
            "bars": [_canonical_review_bar(bar) for bar in result.bars],
            "auxiliary_bars": {
                period: [_canonical_review_bar(bar) for bar in auxiliary_results[period].bars]
                for period in auxiliary_identities
            },
        }
    source_snapshot = lineage.get("source_snapshot")
    if (
        lineage.get("source_snapshot_schema_version")
        == "signal_review_lineage_v2"
        and isinstance(source_snapshot, dict)
    ):
        raw_bar = source_snapshot.get("bar")
        detection = source_snapshot.get("live_detection_snapshot")
        if not isinstance(raw_bar, dict) or not isinstance(detection, dict):
            raise _error(
                "REVIEW_LINEAGE_INVALID",
                note.source_type,
                int(note.source_id or 0),
            )
        observed = raw_bar.get("observed_ohlcv")
        source_1m = detection.get("source_1m")
        if not isinstance(observed, dict) or not isinstance(source_1m, list):
            raise _error(
                "REVIEW_LINEAGE_INVALID",
                note.source_type,
                int(note.source_id or 0),
            )
        bar = {
            "datetime": raw_bar.get("bar_start"),
            "bar_end": raw_bar.get("bar_end"),
            **deepcopy(observed),
            "status": raw_bar.get("bar_status"),
        }
        return {
            "lineage": deepcopy(lineage),
            "bars": [bar],
            "source_1m": deepcopy(source_1m),
        }
    raise _error("REVIEW_LINEAGE_UNAVAILABLE", note.source_type, int(note.source_id or 0))


def _error(code: str, source_type: str, source_id: int) -> ReviewLineageError:
    return ReviewLineageError(code=code, context={"source_type": source_type, "source_id": source_id})


def _iso(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _datetime(value: Any) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_input_snapshot(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    if snapshot.get("schema_version") == "signal_canonical_inputs_v1":
        value = snapshot.get("input_identity")
        return value if isinstance(value, dict) else None
    return None


def _canonical_auxiliary_snapshots(
    snapshot: dict[str, Any],
    *,
    source_type: str,
    source_id: int,
) -> dict[str, dict[str, Any]]:
    value = snapshot.get("auxiliary_input_identities")
    if not isinstance(value, dict):
        raise _error("REVIEW_LINEAGE_UNAVAILABLE", source_type, source_id)
    if any(not isinstance(period, str) or not isinstance(item, dict) for period, item in value.items()):
        raise _error("REVIEW_LINEAGE_INVALID", source_type, source_id)
    return {period: item for period, item in value.items()}


def _identity_strategy_version(identity: CanonicalConsumerInput) -> str | None:
    parts = identity.strategy_input_version.rsplit(":", 2)
    return parts[1] if len(parts) == 3 else None


def _validate_canonical_signal_source(
    source: StrategySignal | SignalEvent,
    *,
    identity: CanonicalConsumerInput,
    formal_input_snapshot: dict[str, Any],
    source_input_snapshot: dict[str, Any] | None,
    source_type: str,
    source_id: int,
) -> None:
    request = identity.request
    contract = request.contract_or_series
    source_symbol = source.symbol.lower() if isinstance(source.symbol, str) else ""
    actual_contract = (
        source.actual_contract.upper()
        if isinstance(source.actual_contract, str)
        else ""
    )
    source_datasets_match = bool(contract) and all(
        dataset.symbol == source_symbol
        and dataset.contract_or_series == actual_contract
        for dataset in identity.source_datasets
    )
    try:
        bar_start = _datetime(source.bar_start)
        bar_end = _datetime(source.bar_end)
        signal_time = _datetime(source.signal_time)
    except (TypeError, ValueError):
        raise _error("REVIEW_SOURCE_IDENTITY_MISMATCH", source_type, source_id) from None
    if (
        source_input_snapshot != formal_input_snapshot
        or source.data_role != "primary"
        or source_symbol != request.symbol
        or actual_contract != contract
        or source.period != request.frequency.value
        or not source_datasets_match
        or not (request.start <= bar_start < bar_end <= request.end)
        or signal_time != bar_end
    ):
        raise _error("REVIEW_SOURCE_IDENTITY_MISMATCH", source_type, source_id)


def _is_live_snapshot(snapshot: dict[str, Any]) -> bool:
    source_mode = snapshot.get("source_mode")
    return isinstance(source_mode, str) and source_mode.startswith("live_")


def _canonical_review_bar(bar: Any) -> dict[str, Any]:
    return {
        "datetime": bar.bar_end,
        "bar_end": bar.bar_end,
        "trading_day": bar.trading_day,
        "symbol": bar.symbol,
        "contract": bar.contract_or_series,
        "provider": bar.provider,
        "dataset_kind": bar.dataset_kind.value,
        "period": bar.frequency.value,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "open_interest": bar.open_interest,
    }
