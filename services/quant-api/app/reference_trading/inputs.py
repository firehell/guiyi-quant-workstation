"""Typed historical-input seam for P4 reference replay.

Implementations must obtain these facts from the existing MarketDataService readers.
The seam intentionally has no provider, Redis, or write capability.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from collections.abc import Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Callable, Protocol

from guiyi_quant.reference_trading import ReferenceBoundary, StreamIdentity
from app.reference_trading.json_spool import JsonSpoolSequence, encode_product_bar, decode_product_bar
from app.reference_trading.packed_fingerprints import (
    PackedFingerprintBuilder, packed_fingerprints_sha256,
)

if TYPE_CHECKING:
    from app.market_data.newow.product_reader import ResolvedPerformanceWindow
    from guiyi_quant.newow.product_contracts import ProductIdentity

NEWOW_D1_REFERENCE_BOUNDARY_POLICY = "owner_eligible_quality_boundary_v1"


@dataclass(frozen=True, slots=True)
class HistoricalInputBar:
    bar_end: datetime
    trading_day: date
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    reference_price: Decimal
    fingerprint: str
    payload: object
    boundaries: tuple[ReferenceBoundary, ...] = ()
    strategy_input: bool = True

    def __post_init__(self) -> None:
        if self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ValueError("bar_end must be timezone-aware")
        if type(self.trading_day) is not date:
            raise ValueError("trading_day must be a date")
        for name in ("physical_contract", "owner_segment_id", "calculation_segment_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")
        if (
            not isinstance(self.reference_price, Decimal)
            or not self.reference_price.is_finite()
            or self.reference_price <= 0
        ):
            raise ValueError("reference_price must be a positive finite Decimal")
        if (
            not isinstance(self.fingerprint, str)
            or len(self.fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.fingerprint)
        ):
            raise ValueError("fingerprint must be a lowercase sha256")
        object.__setattr__(self, "boundaries", tuple(self.boundaries))
        if not all(isinstance(item, ReferenceBoundary) for item in self.boundaries):
            raise TypeError("boundaries must contain ReferenceBoundary")
        if type(self.strategy_input) is not bool:
            raise TypeError("strategy_input must be bool")
        if not self.strategy_input and not self.boundaries:
            raise ValueError("boundary-only input must contain a boundary")


class ProductBarView(Sequence):
    """Read only strategy inputs from a sealed historical snapshot."""

    def __init__(self, bars: Sequence[HistoricalInputBar], count: int):
        if type(count) is not int or count < 0:
            raise ValueError("REFERENCE_PROJECTION_INPUT_COUNT_INVALID")
        self._bars = bars
        self._count = count

    def __len__(self) -> int:
        return self._count

    def __iter__(self):
        for item in self._bars:
            if item.strategy_input:
                yield item.payload.bar

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self._count)
            positions = range(start, stop, step)
            if len(positions) > 256:
                raise ValueError("REFERENCE_PROJECTION_SLICE_EXCEEDED")
            return tuple(self[position] for position in positions)
        if type(index) is not int:
            raise TypeError("projection index must be an integer")
        if index < 0:
            index += self._count
        if not 0 <= index < self._count:
            raise IndexError(index)
        for position, bar in enumerate(self):
            if position == index:
                return bar
        raise ValueError("REFERENCE_PROJECTION_INPUT_COUNT_CONFLICT")


@dataclass(frozen=True, slots=True)
class NewowProjectionContext:
    """Small market metadata; the replay Bar view is constructed on demand."""

    page_identity: ProductIdentity
    resolved: ResolvedPerformanceWindow
    owners: tuple[object, ...]
    boundaries: tuple[object, ...]
    data_interruptions: tuple[object, ...]
    lifecycle_evidence: tuple[object, ...]
    sources: object
    input_quality_policy: object
    reference_source_evidence_sha256: str
    strategy_input_count: int

    def read_view(self, bars: Sequence[HistoricalInputBar]):
        from types import SimpleNamespace
        return SimpleNamespace(
            replay_bars=ProductBarView(bars, self.strategy_input_count),
            as_of=self.resolved.cutoff, frequency=self.page_identity.frequency,
            owners=self.owners, boundaries=self.boundaries,
            data_interruptions=self.data_interruptions,
            lifecycle_evidence=self.lifecycle_evidence, sources=self.sources,
            input_quality_policy=self.input_quality_policy,
            reference_source_evidence_sha256=self.reference_source_evidence_sha256,
        )


@dataclass(frozen=True, slots=True)
class HistoricalInputSnapshot:
    stream: StreamIdentity
    storage_start: date
    completed_through: datetime | None
    bars: Sequence[HistoricalInputBar]
    dependency_manifest: dict[str, object]
    source_token: str
    input_bytes: int
    projection_context: NewowProjectionContext | None = None
    source_integrity: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.bars, HistoricalInputSpool):
            object.__setattr__(self, "bars", tuple(self.bars))
        if not isinstance(self.stream, StreamIdentity):
            raise TypeError("stream must be StreamIdentity")
        if type(self.storage_start) is not date:
            raise ValueError("storage_start must be a date")
        if self.completed_through is not None and (
            self.completed_through.tzinfo is None
            or self.completed_through.utcoffset() is None
        ):
            raise ValueError("completed_through must be timezone-aware")
        if not isinstance(self.dependency_manifest, dict) or not self.dependency_manifest:
            raise ValueError("dependency_manifest must be non-empty")
        if not isinstance(self.source_token, str) or not self.source_token:
            raise ValueError("source_token must be non-empty text")
        if type(self.input_bytes) is not int or self.input_bytes < 0:
            raise ValueError("input_bytes must be a non-negative integer")
        if self.projection_context is not None and not isinstance(
            self.projection_context, NewowProjectionContext
        ):
            raise TypeError("projection_context must be NewowProjectionContext")
        if (self.projection_context is None) != (self.source_integrity is None):
            raise ValueError("projection context and source integrity must occur together")
        if isinstance(self.bars, HistoricalInputSpool):
            if not self.bars.sealed:
                raise ValueError("historical input spool must be sealed")
            latest = self.bars.latest_bar_end
        else:
            previous_by_segment: dict[tuple[str, str, str], datetime] = {}
            fingerprints: set[str] = set()
            latest = None
            for bar in self.bars:
                if not isinstance(bar, HistoricalInputBar):
                    raise TypeError("bars must contain HistoricalInputBar")
                key = (
                    bar.physical_contract, bar.owner_segment_id,
                    bar.calculation_segment_id,
                )
                previous = previous_by_segment.get(key)
                if previous is not None and bar.bar_end <= previous:
                    raise ValueError("calculation-segment inputs must be strictly ordered")
                if bar.fingerprint in fingerprints:
                    raise ValueError("historical input fingerprints must be unique")
                previous_by_segment[key] = bar.bar_end
                fingerprints.add(bar.fingerprint)
                latest = max(latest, bar.bar_end) if latest is not None else bar.bar_end
        if self.bars and self.completed_through != latest:
            raise ValueError("completed_through must equal the latest input event")

    def close(self) -> None:
        close = getattr(self.bars, "close", None)
        if callable(close):
            close()


class HistoricalInputReader(Protocol):
    def estimate_stream(self, request: object) -> tuple[int, int]: ...

    def plan_stream(self, request: object) -> HistoricalInputSnapshot: ...

    def load_stream(
        self, request: object, *, expected_source_token: str,
    ) -> HistoricalInputSnapshot: ...

    def revalidate(self, request: object, *, expected_source_token: str) -> bool: ...


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
    )


def _stream_manifest_sha256(value: object) -> tuple[str, int]:
    """Same canonical bytes as _canonical without a second whole-manifest string."""
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
    )
    digest = sha256()
    count = 0
    for part in encoder.iterencode(value):
        chunk = part.encode()
        digest.update(chunk)
        count += len(chunk)
    return digest.hexdigest(), count


def _identity_wire(identity):
    return {
        "product": identity.product, "strategy": identity.strategy.value,
        "frequency": identity.frequency.value,
        "formula_versions": list(identity.formula_versions),
        "series_kind": identity.series_kind, "profile_id": identity.profile_id,
        "input_quality_policy": identity.input_quality_policy.value,
    }


def _identity_from_wire(raw):
    from guiyi_quant.newow.product_contracts import ProductIdentity
    if not isinstance(raw, dict) or set(raw) != {
        "product", "strategy", "frequency", "formula_versions", "series_kind",
        "profile_id", "input_quality_policy",
    }:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    return ProductIdentity(**{**raw, "formula_versions": tuple(raw["formula_versions"])})


def _action_wire(action):
    return {
        "identity": _identity_wire(action.identity),
        "physical_contract": action.physical_contract,
        "segment_id": action.segment_id,
        "bar_end": action.bar_end.isoformat(),
        "trading_day": action.trading_day.isoformat(),
        "kind": action.kind.value,
        "reference_price": str(action.reference_price),
        "anchor_price": None if action.anchor_price is None else str(action.anchor_price),
        "sequence": action.sequence,
        "related_build_id": action.related_build_id,
        "source_marker_id": action.source_marker_id,
        "source_related_marker_ids": list(action.source_related_marker_ids),
        "trade_eligibility": action.trade_eligibility.value,
        "calculation_segment_id": action.calculation_segment_id,
        "signal_id": action.signal_id,
    }


def _action_from_wire(raw):
    from guiyi_quant.newow.product_contracts import StrategyAction
    if not isinstance(raw, dict) or set(raw) != {
        "identity", "physical_contract", "segment_id", "bar_end", "trading_day",
        "kind", "reference_price", "anchor_price", "sequence", "related_build_id",
        "source_marker_id", "source_related_marker_ids", "trade_eligibility",
        "calculation_segment_id", "signal_id",
    }:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    action = StrategyAction(
        identity=_identity_from_wire(raw["identity"]),
        physical_contract=raw["physical_contract"], segment_id=raw["segment_id"],
        bar_end=datetime.fromisoformat(raw["bar_end"]),
        trading_day=date.fromisoformat(raw["trading_day"]),
        kind=raw["kind"], reference_price=Decimal(raw["reference_price"]),
        anchor_price=None if raw["anchor_price"] is None else Decimal(raw["anchor_price"]),
        sequence=raw["sequence"], related_build_id=raw["related_build_id"],
        source_marker_id=raw["source_marker_id"],
        source_related_marker_ids=tuple(raw["source_related_marker_ids"]),
        trade_eligibility=raw["trade_eligibility"],
        calculation_segment_id=raw["calculation_segment_id"],
    )
    if action.signal_id != raw["signal_id"]:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    return action


def _historical_bar_wire(item: HistoricalInputBar):
    from app.reference_trading.service import NewowHistoricalPayload
    from app.reference_trading.newow_fusion import FusionHistoricalPayload
    if item.payload is None:
        payload = None
    elif isinstance(item.payload, NewowHistoricalPayload):
        payload = {"kind": "newow", "identity": _identity_wire(item.payload.identity),
                   "bar": encode_product_bar(item.payload.bar),
                   "verified_lifecycle": item.payload.verified_lifecycle}
    elif isinstance(item.payload, FusionHistoricalPayload):
        payload = {"kind": "fusion", "bar": encode_product_bar(item.payload.bar),
                   "source_actions": [_action_wire(action) for action in item.payload.source_actions]}
    else:
        raise TypeError("REFERENCE_SPOOL_PAYLOAD_UNSUPPORTED")
    return {
        "v": 1, "bar_end": item.bar_end.isoformat(),
        "trading_day": item.trading_day.isoformat(),
        "physical_contract": item.physical_contract,
        "owner_segment_id": item.owner_segment_id,
        "calculation_segment_id": item.calculation_segment_id,
        "reference_price": str(item.reference_price),
        "fingerprint": item.fingerprint,
        "payload": payload,
        "boundaries": [{
            "reason": boundary.reason.value,
            "physical_contract": boundary.physical_contract,
            "owner_segment_id": boundary.owner_segment_id,
            "calculation_segment_id": boundary.calculation_segment_id,
            "bar_end": boundary.bar_end.isoformat(),
            "trading_day": boundary.trading_day.isoformat(),
        } for boundary in item.boundaries],
        "strategy_input": item.strategy_input,
    }


def _historical_bar_from_wire(raw, stream: StreamIdentity):
    from app.reference_trading.service import NewowHistoricalPayload
    from app.reference_trading.newow_fusion import FusionHistoricalPayload
    if not isinstance(raw, dict) or raw.get("v") != 1 or set(raw) != {
        "v", "bar_end", "trading_day", "physical_contract", "owner_segment_id",
        "calculation_segment_id", "reference_price", "fingerprint", "payload",
        "boundaries", "strategy_input",
    }:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    payload_raw = raw["payload"]
    payload: object
    if payload_raw is None:
        payload = None
    elif payload_raw.get("kind") == "newow" and set(payload_raw) == {
        "kind", "identity", "bar", "verified_lifecycle",
    }:
        payload = NewowHistoricalPayload(
            _identity_from_wire(payload_raw["identity"]),
            decode_product_bar(payload_raw["bar"]),
            payload_raw["verified_lifecycle"],
        )
    elif payload_raw.get("kind") == "fusion" and set(payload_raw) == {
        "kind", "bar", "source_actions",
    }:
        payload = FusionHistoricalPayload(
            decode_product_bar(payload_raw["bar"]),
            tuple(_action_from_wire(action) for action in payload_raw["source_actions"]),
        )
    else:
        raise ValueError("REFERENCE_SPOOL_CODEC_INVALID")
    boundaries = tuple(ReferenceBoundary(
        stream, boundary["reason"], boundary["physical_contract"],
        boundary["owner_segment_id"], boundary["calculation_segment_id"],
        datetime.fromisoformat(boundary["bar_end"]),
        date.fromisoformat(boundary["trading_day"]),
    ) for boundary in raw["boundaries"])
    return HistoricalInputBar(
        datetime.fromisoformat(raw["bar_end"]),
        date.fromisoformat(raw["trading_day"]), raw["physical_contract"],
        raw["owner_segment_id"], raw["calculation_segment_id"],
        Decimal(raw["reference_price"]), raw["fingerprint"], payload,
        boundaries, raw["strategy_input"],
    )


class HistoricalInputSpool(JsonSpoolSequence[HistoricalInputBar]):
    """Validated, uniquely indexed replay bars with bounded process memory."""

    def __init__(self, stream: StreamIdentity):
        self.latest_bar_end: datetime | None = None
        self.min_trading_day: date | None = None
        self.max_trading_day: date | None = None
        self._previous_by_segment: dict[tuple[str, str, str], datetime] = {}
        super().__init__(
            encode=_historical_bar_wire,
            decode=lambda raw: _historical_bar_from_wire(raw, stream),
            unique_key=lambda item: item.fingerprint,
        )

    def append(self, item: HistoricalInputBar) -> None:
        if not isinstance(item, HistoricalInputBar):
            raise TypeError("bars must contain HistoricalInputBar")
        key = (item.physical_contract, item.owner_segment_id,
               item.calculation_segment_id)
        previous = self._previous_by_segment.get(key)
        if previous is not None and item.bar_end <= previous:
            raise ValueError("calculation-segment inputs must be strictly ordered")
        super().append(item)
        self._previous_by_segment[key] = item.bar_end
        self.latest_bar_end = (max(self.latest_bar_end, item.bar_end)
                               if self.latest_bar_end is not None else item.bar_end)
        self.min_trading_day = (min(self.min_trading_day, item.trading_day)
                                if self.min_trading_day is not None else item.trading_day)
        self.max_trading_day = (max(self.max_trading_day, item.trading_day)
                                if self.max_trading_day is not None else item.trading_day)


def _newow_input_fingerprint(
    *, source_bar_sha256: str, bar_end: datetime, physical_contract: str,
    owner_segment_id: str, calculation_segment_id: str, quality_policy: str,
) -> str:
    """Identify one calculation input even when warm-up reuses a physical Bar."""
    return sha256(_canonical({
        "source": source_bar_sha256,
        "bar_end": bar_end,
        "physical_contract": physical_contract,
        "owner_segment_id": owner_segment_id,
        "calculation_segment_id": calculation_segment_id,
        "quality_policy": quality_policy,
    }).encode()).hexdigest()


def _newow_replay_fingerprints(
    replay_bars: tuple[object, ...], quality_policy: str,
) -> tuple[str, ...]:
    return tuple(
        _newow_input_fingerprint(
            source_bar_sha256=item.source_bar_sha256,
            bar_end=item.bar.bar_end,
            physical_contract=item.bar.physical_contract,
            owner_segment_id=item.bar.segment_id,
            calculation_segment_id=item.calculation_segment_id,
            quality_policy=quality_policy,
        ) for item in replay_bars
    )


def _boundary_input(
    anchor: HistoricalInputBar, boundary: ReferenceBoundary,
) -> HistoricalInputBar:
    """Create an explicit replay event when no physical Bar exists at a boundary."""
    fingerprint = sha256(_canonical({
        "kind": "reference_boundary",
        "stream": boundary.stream.stream_id,
        "reason": boundary.reason.value,
        "physical_contract": boundary.physical_contract,
        "owner_segment_id": boundary.owner_segment_id,
        "calculation_segment_id": boundary.calculation_segment_id,
        "bar_end": boundary.bar_end,
        "trading_day": boundary.trading_day,
    }).encode()).hexdigest()
    return HistoricalInputBar(
        boundary.bar_end,
        boundary.trading_day,
        boundary.physical_contract,
        boundary.owner_segment_id,
        boundary.calculation_segment_id,
        anchor.reference_price,
        fingerprint,
        None,
        (boundary,),
        False,
    )


def _boundary_fingerprint(
    source_fingerprint: str, boundary: ReferenceBoundary,
) -> str:
    """Bind same-Bar metadata events to the immutable replay input identity."""
    return sha256(_canonical({
        "source_input_fingerprint": source_fingerprint,
        "boundary": {
            "stream_id": boundary.stream.stream_id,
            "reason": boundary.reason.value,
            "physical_contract": boundary.physical_contract,
            "owner_segment_id": boundary.owner_segment_id,
            "calculation_segment_id": boundary.calculation_segment_id,
            "bar_end": boundary.bar_end,
            "trading_day": boundary.trading_day,
        },
    }).encode()).hexdigest()


def _daily_owner_reference_boundaries(boundaries, labeled_bars, owners):
    """Separate physical warm-up quality facts from authoritative owner events."""
    from guiyi_quant.reference_trading import BoundaryReason

    first_eligible = {}
    known_owners = set()
    for item in labeled_bars:
        key = (item.bar.physical_contract, item.bar.segment_id)
        known_owners.add(key)
        if item.bar.observation_eligible:
            first_eligible[key] = min(first_eligible.get(key, item.bar.trading_day), item.bar.trading_day)
    result = []
    for boundary in boundaries:
        if boundary.reason is not BoundaryReason.DATA_INTERRUPTED:
            result.append(boundary)
            continue
        key = (boundary.physical_contract, boundary.owner_segment_id)
        candidates = [owner for owner in owners if owner.contract == boundary.physical_contract]
        first = first_eligible.get(key)
        if first is not None:
            candidates = [owner for owner in candidates if owner.start_trading_day <= first <= owner.end_trading_day]
        if key not in known_owners or len(candidates) != 1:
            raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
        owner = candidates[0]
        if boundary.trading_day < owner.start_trading_day:
            continue  # Raw quality facts still split the indicator lifecycle.
        if boundary.trading_day > owner.end_trading_day:
            raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
        result.append(boundary)
    return result


def _insert_boundaries(
    bars: list[HistoricalInputBar], boundaries: tuple[ReferenceBoundary, ...],
) -> list[HistoricalInputBar]:
    """Insert each boundary after the last preceding Bar of its owner segment."""
    insertions: dict[int, list[HistoricalInputBar]] = {}
    for boundary in sorted(boundaries, key=lambda item: item.bar_end):
        exact = [
            (index, bar)
            for index, bar in enumerate(bars)
            if bar.strategy_input
            and bar.physical_contract == boundary.physical_contract
            and bar.owner_segment_id == boundary.owner_segment_id
            and bar.bar_end == boundary.bar_end
        ]
        if exact:
            index, anchor = exact[-1]
            normalized = ReferenceBoundary(
                boundary.stream,
                boundary.reason,
                boundary.physical_contract,
                boundary.owner_segment_id,
                anchor.calculation_segment_id,
                boundary.bar_end,
                boundary.trading_day,
            )
            bars[index] = replace(
                anchor,
                fingerprint=_boundary_fingerprint(anchor.fingerprint, normalized),
                boundaries=(*anchor.boundaries, normalized),
            )
            continue
        candidates = [
            (index, bar)
            for index, bar in enumerate(bars)
            if bar.strategy_input
            and bar.physical_contract == boundary.physical_contract
            and bar.owner_segment_id == boundary.owner_segment_id
            and bar.bar_end < boundary.bar_end
        ]
        if not candidates:
            raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
        index, anchor = candidates[-1]
        normalized = ReferenceBoundary(
            boundary.stream,
            boundary.reason,
            boundary.physical_contract,
            boundary.owner_segment_id,
            anchor.calculation_segment_id,
            boundary.bar_end,
            boundary.trading_day,
        )
        insertions.setdefault(index, []).append(_boundary_input(anchor, normalized))
    output: list[HistoricalInputBar] = []
    for index, bar in enumerate(bars):
        output.append(bar)
        output.extend(sorted(
            insertions.get(index, ()), key=lambda item: item.bar_end,
        ))
    return output


def _iter_insert_boundaries(bars, boundaries):
    """Preserve _insert_boundaries order without holding all replay inputs."""
    by_owner = {}
    for boundary in sorted(boundaries, key=lambda item: item.bar_end):
        by_owner.setdefault((boundary.physical_contract,
                             boundary.owner_segment_id), []).append(boundary)
    positions = {owner: 0 for owner in by_owner}
    current_owner = None
    anchor = None
    seen_owners = set()

    def normalize(boundary, source):
        return ReferenceBoundary(
            boundary.stream, boundary.reason, boundary.physical_contract,
            boundary.owner_segment_id, source.calculation_segment_id,
            boundary.bar_end, boundary.trading_day,
        )

    def finish(owner, prior):
        if owner is None:
            return
        pending = by_owner.get(owner, ())
        for boundary in pending[positions.get(owner, 0):]:
            if prior is None or boundary.bar_end <= prior.bar_end:
                raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
            yield _boundary_input(prior, normalize(boundary, prior))
        positions[owner] = len(pending)

    for bar in bars:
        if not bar.strategy_input:
            raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
        owner = (bar.physical_contract, bar.owner_segment_id)
        if owner != current_owner:
            yield from finish(current_owner, anchor)
            if owner in seen_owners:
                raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
            seen_owners.add(owner)
            current_owner = owner
            anchor = None
        pending = by_owner.get(owner, ())
        position = positions.get(owner, 0)
        while position < len(pending) and pending[position].bar_end < bar.bar_end:
            if anchor is None:
                raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
            yield _boundary_input(anchor, normalize(pending[position], anchor))
            position += 1
        while position < len(pending) and pending[position].bar_end == bar.bar_end:
            boundary = normalize(pending[position], bar)
            bar = replace(bar,
                fingerprint=_boundary_fingerprint(bar.fingerprint, boundary),
                boundaries=(*bar.boundaries, boundary))
            position += 1
        positions[owner] = position
        yield bar
        anchor = bar
    yield from finish(current_owner, anchor)
    if any(positions[owner] != len(items) for owner, items in by_owner.items()):
        raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")


def _raw_bar_fingerprints(raw_inputs: object) -> dict[tuple[str, str, str], str]:
    """Index complete MDS bar records while retaining their source segment identity."""
    output: dict[tuple[str, str, str], str] = {}

    def walk(value: object, context: dict[str, str]) -> None:
        if isinstance(value, dict):
            current = dict(context)
            for key in ("contract", "segment_id", "calculation_segment_id"):
                found = value.get(key)
                if isinstance(found, str) and found:
                    current[key] = found
            bar_end = value.get("bar_end")
            if bar_end is not None and "contract" in current:
                segment = current.get("calculation_segment_id") or current.get("segment_id")
                if segment is not None:
                    instant = (
                        bar_end.isoformat()
                        if hasattr(bar_end, "isoformat")
                        else str(bar_end)
                    )
                    source_key = (current["contract"], segment, instant)
                    digest = sha256(_canonical(value).encode()).hexdigest()
                    if source_key in output and output[source_key] != digest:
                        raise ValueError("REFERENCE_SOURCE_BAR_CONFLICT")
                    output[source_key] = digest
            for item in value.values():
                walk(item, current)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, context)

    walk(raw_inputs, {})
    return output


class MarketDataHistoricalInputReader:
    """Adapt the existing Newow/Subing MDS readers to the P4 input contract."""

    def __init__(
        self,
        *,
        newow_reader: object,
        subing_service: object,
        read_guard: Callable[[], AbstractContextManager[object]] = nullcontext,
        pin_verified_inputs: bool = False,
        compact_intraday_inputs: bool = False,
        fusion_sources: object | None = None,
    ) -> None:
        self._fusion_sources = fusion_sources
        self._newow = newow_reader
        self._subing = subing_service
        self._read_guard = read_guard
        self._compact_intraday_inputs = compact_intraday_inputs
        self._pin_verified_inputs = pin_verified_inputs
        self._pinned_request = None
        self._pinned_snapshot = None

    def _guard(self):
        return nullcontext() if self._pinned_snapshot is not None else self._read_guard()

    @contextmanager
    def pin_stream(self, request, *, expected_manifest=None, expected_source_token=None):
        """Reuse immutable inputs only while the Canonical maintenance lease is held.

        No cache survives the lease or an interrupted build. The production
        composition enables this only with the authoritative maintenance lock.
        """
        if (expected_manifest is None) != (expected_source_token is None):
            raise ValueError("REFERENCE_INPUT_PIN_PROOF_INCOMPLETE")
        if expected_manifest is not None and (
            not isinstance(expected_manifest, dict)
            or not isinstance(expected_source_token, str)
            or not expected_source_token
        ):
            raise ValueError("REFERENCE_INPUT_PIN_PROOF_INVALID")
        if not self._pin_verified_inputs:
            yield
            return
        if self._pinned_snapshot is not None:
            raise ValueError("REFERENCE_INPUT_LEASE_ALREADY_HELD")
        with self._read_guard():
            snapshot = None
            try:
                snapshot = self._read_uncached(request)
                if expected_manifest is not None:
                    if (
                        snapshot.source_token != expected_source_token
                        or snapshot.dependency_manifest != expected_manifest
                        or _stream_manifest_sha256(snapshot.dependency_manifest)
                        != _stream_manifest_sha256(expected_manifest)
                    ):
                        raise ValueError("SOURCE_CHANGED")
                    # The fresh read has proved the plan's exact manifest. Rebind
                    # the snapshot instead of retaining a second large v5 vector.
                    object.__setattr__(snapshot, "dependency_manifest", expected_manifest)
                self._pinned_request = request
                self._pinned_snapshot = snapshot
                yield
            finally:
                if snapshot is not None:
                    close = getattr(snapshot, "close", None)
                    if callable(close):
                        close()
                self._pinned_snapshot = None
                self._pinned_request = None

    def pin_verified_stream(self, request, *, expected_manifest, expected_source_token):
        return self.pin_stream(
            request, expected_manifest=expected_manifest,
            expected_source_token=expected_source_token,
        )

    def _newow_for(self, identity: StreamIdentity) -> object:
        return self._newow(identity) if callable(self._newow) else self._newow

    def plan_stream(self, request: object) -> HistoricalInputSnapshot:
        with self._guard():
            return self._read(request)

    @contextmanager
    def planned_stream(self, request: object):
        snapshot = self.plan_stream(request)
        try:
            yield snapshot
        finally:
            self.release_snapshot(snapshot)

    def estimate_stream(self, request: object) -> tuple[int, int]:
        """Conservative pre-materialization ceiling for explicit work budgets."""
        from app.reference_trading.planning import HistoricalStreamRequest

        if not isinstance(request, HistoricalStreamRequest):
            raise TypeError("request must be HistoricalStreamRequest")
        normalized = request.identity.strategy_code.replace("-", "_")
        if normalized == "subing_reference":
            bound_reader = getattr(self._subing, "historical_input_bound", None)
            arguments: dict[str, object] = {
                "symbol": request.identity.product.lower(),
                "frequency": request.identity.frequency,
            }
        elif normalized.startswith("newow_"):
            market_reader = self._newow_for(request.identity)
            bound_reader = getattr(market_reader, "historical_spool_bound", None)
            bounded_spool = callable(bound_reader)
            if not bounded_spool:
                bound_reader = getattr(market_reader, "historical_input_bound", None)
            arguments = {
                "product": request.identity.product.lower(),
                "frequency": request.identity.frequency,
            }
            if bounded_spool:
                arguments.update(
                    formula_versions=request.identity.formula_versions,
                    reference_model_version=request.identity.reference_model_version,
                    fusion=normalized == "newow_dual_fusion",
                )
        else:
            raise ValueError("REFERENCE_CAPABILITY_UNSUPPORTED")
        if not callable(bound_reader):
            raise ValueError("REFERENCE_INPUT_BOUND_UNAVAILABLE")
        bound = bound_reader(
            **arguments,
            since=request.since,
            through=request.through,
            as_of=request.as_of,
        )
        if (
            not isinstance(bound, tuple)
            or len(bound) != 2
            or type(bound[0]) is not int
            or type(bound[1]) is not int
            or bound[0] <= 0
            or bound[1] <= 0
        ):
            raise ValueError("REFERENCE_INPUT_BOUND_UNAVAILABLE")
        return bound

    def load_stream(
        self, request: object, *, expected_source_token: str,
    ) -> HistoricalInputSnapshot:
        with self._guard():
            snapshot = self._read(request)
        if snapshot.source_token != expected_source_token:
            self.release_snapshot(snapshot)
            raise ValueError("SOURCE_CHANGED")
        return snapshot

    def release_snapshot(self, snapshot: HistoricalInputSnapshot) -> None:
        if snapshot is not self._pinned_snapshot:
            close = getattr(snapshot, "close", None)
            if callable(close):
                close()

    def revalidate(self, request: object, *, expected_source_token: str) -> bool:
        try:
            snapshot = self._read(request)
            try:
                return snapshot.source_token == expected_source_token
            finally:
                self.release_snapshot(snapshot)
        except (TypeError, ValueError):
            return False

    def source_guard(self, request: object, *, expected_source_token: str):
        reader = self

        class Guard:
            def __enter__(self):
                self._guard = reader._guard()
                self._guard.__enter__()
                try:
                    snapshot = reader._read(request)
                    try:
                        matches = snapshot.source_token == expected_source_token
                    finally:
                        reader.release_snapshot(snapshot)
                    if not matches:
                        raise ValueError("SOURCE_CHANGED")
                except BaseException as error:
                    self._guard.__exit__(type(error), error, error.__traceback__)
                    raise
                return self

            def __exit__(self, exc_type, exc, tb):
                return self._guard.__exit__(exc_type, exc, tb)

        return Guard()

    def _read(self, request: object) -> HistoricalInputSnapshot:
        if self._pinned_snapshot is not None and request == self._pinned_request:
            return self._pinned_snapshot
        return self._read_uncached(request)

    def _read_uncached(self, request: object) -> HistoricalInputSnapshot:
        from app.reference_trading.planning import HistoricalStreamRequest

        if not isinstance(request, HistoricalStreamRequest):
            raise TypeError("request must be HistoricalStreamRequest")
        normalized = request.identity.strategy_code.replace("-", "_")
        if normalized == "newow_dual_fusion":
            return self._read_fusion(request)
        if normalized == "subing_reference":
            return self._read_subing(request)
        if normalized.startswith("newow_"):
            return self._read_newow(request)
        raise ValueError("REFERENCE_CAPABILITY_UNSUPPORTED")

    def _read_fusion(self, request):
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
        from app.reference_trading.newow_fusion import fusion_input_policy
        if not callable(self._fusion_sources) or not self._compact_intraday_inputs:
            raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
        policy = fusion_input_policy(request.identity)
        product = build_product_identity(request.identity.product,ProductStrategy.TREND,ProductFrequency(request.identity.frequency),input_quality_policy=policy)
        shadow_identity = replace(request.identity,strategy_code="newow_trend",formula_versions=product.formula_versions,profile_id=product.profile_id,reference_model_version=REFERENCE_MODEL_VERSION,futures_adaptation_version=futures_adaptation_version(request.identity.frequency,policy))
        shadow = self._read_newow(replace(request,identity=shadow_identity))
        try:
            return self._read_fusion_loaded(request, shadow, policy, shadow_identity)
        finally:
            shadow.close()

    def _read_fusion_loaded(self, request, shadow, policy, shadow_identity):
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from app.reference_trading.newow_fusion import FusionHistoricalPayload

        if (
            shadow.dependency_manifest.get("reader") != "newow_product_reader_prefix_v5"
            or not isinstance(shadow.dependency_manifest.get("input_fingerprints"), dict)
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_REBUILD_REQUIRED")
        source_manifests = {"trend": shadow.dependency_manifest}
        oscillator_snapshot = None
        if "input_fingerprints" in shadow.dependency_manifest:
            oscillator = build_product_identity(request.identity.product,ProductStrategy.OSCILLATION,
                ProductFrequency(request.identity.frequency),input_quality_policy=policy)
            oscillator_identity = replace(shadow_identity,strategy_code="newow_oscillation",
                formula_versions=oscillator.formula_versions,profile_id=oscillator.profile_id)
            oscillator_snapshot = self._read_newow(replace(request,identity=oscillator_identity))
            try:
                if oscillator_snapshot.source_integrity != shadow.source_integrity:
                    raise ValueError("REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT")
                # Boundary fingerprints include the stream identity. Verify each
                # saved strategy against its own authoritative replay.
                for key in ("calendar_session_effective_fingerprints", "calendar_session_source_evidence",
                            "rank1", "boundaries", "data_interruptions", "lifecycle_owners",
                            "market_source_identity", "input_policy_version", "quality_policy",
                            "reference_boundary_policy_version"):
                    if oscillator_snapshot.dependency_manifest.get(key) != shadow.dependency_manifest.get(key):
                        raise ValueError("REFERENCE_FUSION_SOURCE_SNAPSHOT_CONFLICT")
                source_manifests["oscillation"] = oscillator_snapshot.dependency_manifest
            finally:
                oscillator_snapshot.close()
        target_day = (shadow.projection_context.resolved.actual_through
            if shadow.projection_context is not None else
            max((item.trading_day for item in shadow.bars), default=None))
        actions, dependencies = self._fusion_sources(request,shadow.dependency_manifest,
            source_manifests=source_manifests, source_integrity=shadow.source_integrity,
            target_completed_through=shadow.completed_through, target_trading_day=target_day)
        source_manifests.clear()
        oscillator_snapshot = None  # Release its large manifest before fusion projection.
        bars = None
        try:
            bars = HistoricalInputSpool(request.identity)
            execution_fingerprints = PackedFingerprintBuilder()
            for item in shadow.bars:
                source_actions=tuple(actions.get((item.bar_end,item.physical_contract,item.owner_segment_id,item.calculation_segment_id),())) if item.strategy_input else ()
                payload=FusionHistoricalPayload(item.payload.bar,source_actions) if item.strategy_input else item.payload
                fingerprint=sha256(_canonical([item.fingerprint,[(action.signal_id,str(action.reference_price),action.trade_eligibility.value) for action in source_actions]]).encode()).hexdigest()
                bars.append(replace(item,payload=payload,fingerprint=fingerprint,boundaries=tuple(replace(boundary,stream=request.identity) for boundary in item.boundaries)))
                execution_fingerprints.add(fingerprint)
            bars.seal()
            execution_proof = execution_fingerprints.finish()
            return self._finish_fusion_snapshot(request, shadow, bars, execution_proof, dependencies)
        except BaseException:
            if bars is not None:
                bars.close()
            raise
        finally:
            if isinstance(actions, dict):
                actions.clear()  # Existing small fixture adapters use a plain mapping.
            else:
                actions.close()

    def _finish_fusion_snapshot(self, request, shadow, bars, execution_proof, dependencies):
        manifest={**shadow.dependency_manifest,"query_through":request.through.isoformat(),"query_as_of":request.as_of.isoformat(),"input_count":len(bars),"source_reader":shadow.dependency_manifest["reader"],"reader":"newow_fusion_saved_sources_v3","source_dependencies":dependencies,"formula_versions":list(request.identity.formula_versions),"reference_model_version":request.identity.reference_model_version,"input_sha256":packed_fingerprints_sha256(execution_proof)}
        # Full manifests bind execution inputs and their exact source leaves.
        manifest["source_input_fingerprints"] = manifest["input_fingerprints"]
        manifest["input_fingerprints"] = execution_proof
        token, manifest_bytes = _stream_manifest_sha256(manifest)
        return HistoricalInputSnapshot(
            request.identity, shadow.storage_start, shadow.completed_through,
            bars, manifest, token, manifest_bytes + len(bars) * 256,
            shadow.projection_context, shadow.source_integrity,
        )

    def _read_subing(self, request):
        from app.market_data.domain import BarFrequency
        from app.reference_trading.service import SubingHistoricalPayload
        from guiyi_quant.reference_trading import BoundaryReason

        frequency = BarFrequency(request.identity.frequency)
        segments, raw_inputs, quality, cutoff = self._subing.load_historical_inputs(
            symbol=request.identity.product.lower(),
            frequency=frequency,
            since=request.since,
            through=request.through,
            as_of=request.as_of,
        )
        bars: list[HistoricalInputBar] = []
        boundaries: list[ReferenceBoundary] = []
        source_bars = _raw_bar_fingerprints(raw_inputs)
        for segment in segments:
            calculation = segment.calculation_segment_id or segment.segment_id
            for bar in segment.bars:
                if bar.bar_end > cutoff or bar.trading_day > request.through:
                    continue
                source_sha = source_bars.get((
                    segment.physical_contract, calculation, bar.bar_end.isoformat(),
                ))
                if source_sha is None:
                    raise ValueError("REFERENCE_SOURCE_BAR_IDENTITY_MISSING")
                fingerprint = sha256(_canonical({
                    "stream": request.identity.stream_id,
                    "segment": segment.segment_id,
                    "calculation": calculation,
                    "owner_since": segment.owner_since,
                    "bar_end": bar.bar_end,
                    "trading_day": bar.trading_day,
                    "close": bar.close,
                    "source_bar_sha256": source_sha,
                    "since": request.since,
                }).encode()).hexdigest()
                bars.append(HistoricalInputBar(
                    bar.bar_end,
                    bar.trading_day,
                    segment.physical_contract,
                    segment.segment_id,
                    calculation,
                    bar.close,
                    fingerprint,
                    SubingHistoricalPayload(
                        segment, bar, request.since, request.through,
                        frequency is BarFrequency.D1,
                    ),
                ))
            if (
                segment.quality_interrupted_at is not None
                and segment.quality_interrupted_at <= cutoff
            ):
                if segment.quality_interruption_trading_day is None:
                    raise ValueError("REFERENCE_BOUNDARY_TRADING_DAY_MISSING")
                boundaries.append(ReferenceBoundary(
                    request.identity,
                    BoundaryReason.DATA_INTERRUPTED,
                    segment.physical_contract,
                    segment.segment_id,
                    calculation,
                    segment.quality_interrupted_at,
                    segment.quality_interruption_trading_day,
                ))
            elif (
                segment.interrupted_at is not None
                and segment.interrupted_at <= cutoff
                and segment.owner_through < request.through
            ):
                boundaries.append(ReferenceBoundary(
                    request.identity,
                    BoundaryReason.ROLLOVER,
                    segment.physical_contract,
                    segment.segment_id,
                    calculation,
                    segment.interrupted_at,
                    segment.owner_through,
                ))
        bars = _insert_boundaries(bars, tuple(boundaries))
        metadata_reader = getattr(self._subing, "historical_metadata_evidence", None)
        if not callable(metadata_reader):
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = metadata_reader(
            symbol=request.identity.product.lower(),
            since=min(bar.trading_day for segment in segments for bar in segment.bars),
            through=request.through,
        )
        if not isinstance(metadata_evidence, dict) or not metadata_evidence:
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = {
            key: value for key, value in metadata_evidence.items()
            if key != "through"
        }
        manifest = {
            "reader": "subing_mds_historical_v1",
            "market_source_identity": "canonical_catalog_mds_v1",
            "query_since": request.since.isoformat(),
            # Re-reading and comparing this complete ordered prefix is the
            # bounded proof used when Catalog cannot attest an immutable
            # in-month append.  Do not replace it with a mutable directory or
            # whole-window digest: those cannot distinguish append from edit.
            "input_fingerprints": [bar.fingerprint for bar in bars],
            "calendar_session_effective_fingerprints": [
                sha256(_canonical((bar.bar_end, bar.trading_day)).encode()).hexdigest()
                for bar in bars if bar.strategy_input
            ],
            "calendar_session_source_evidence": metadata_evidence,
            "quality_policy_version": quality.get("quality_policy_version"),
            "quality_interruptions": [
                sha256(_canonical(item).encode()).hexdigest()
                for item in quality.get("quality_interruptions", ())
            ],
            "rank1": [
                [
                    segment.physical_contract,
                    segment.owner_since.isoformat(),
                    segment.owner_through.isoformat(),
                ]
                for segment in segments
            ],
            "formula_versions": list(request.identity.formula_versions),
            "reference_model_version": request.identity.reference_model_version,
        }
        token = sha256(_canonical(manifest).encode()).hexdigest()
        return HistoricalInputSnapshot(
            request.identity,
            min(bar.trading_day for segment in segments for bar in segment.bars),
            max((bar.bar_end for bar in bars), default=None),
            tuple(bars),
            manifest,
            token,
            len(_canonical(raw_inputs).encode()),
        )

    def _read_newow(self, request):
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from app.market_data.newow.product_query import NewowProductQuery

        strategy = ProductStrategy(request.identity.strategy_code.replace("-", "_").removeprefix("newow_"))
        frequency = ProductFrequency(request.identity.frequency)
        query = NewowProductQuery(
            request.identity.product.lower(), strategy, frequency,
            request.since, request.through,
            request.since, request.through, request.as_of,
        )
        newow_reader = self._newow_for(request.identity)
        historical = getattr(newow_reader, "load_historical", None)
        read = historical(query, request.as_of) if callable(historical) else newow_reader.load(query, request.as_of)
        try:
            return self._read_newow_loaded(
                request, query, newow_reader, read, frequency, strategy,
                production_historical=callable(historical),
            )
        finally:
            close = getattr(read, "close", None)
            if callable(close):
                close()

    def _read_newow_loaded(self, request, query, newow_reader, read, frequency, strategy,
                           *, production_historical):
        from guiyi_quant.newow.product_adapters import (
            build_product_identity, iter_label_calculation_segments,
        )
        from guiyi_quant.newow.product_contracts import ProductFrequency
        from guiyi_quant.newow.product_identity import futures_adaptation_version
        from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary
        from app.reference_trading.service import NewowHistoricalPayload

        identity = build_product_identity(
            query.product, strategy, frequency,
            input_quality_policy=read.input_quality_policy,
        )
        if (
            request.identity.product != identity.product
            or request.identity.formula_versions != identity.formula_versions
            or request.identity.profile_id != identity.profile_id
            or request.identity.futures_adaptation_version
            != futures_adaptation_version(frequency.value, identity.input_quality_policy)
        ):
            raise ValueError("REFERENCE_INPUT_IDENTITY_CONFLICT")
        boundaries: list[ReferenceBoundary] = []
        for boundary in read.boundaries:
            boundaries.append(ReferenceBoundary(
                request.identity,
                BoundaryReason.ROLLOVER,
                boundary.old_contract,
                boundary.old_segment_id,
                boundary.old_segment_id,
                boundary.effective_at,
                boundary.effective_trading_day,
            ))
        for gap in read.data_interruptions:
            boundaries.append(ReferenceBoundary(
                request.identity,
                BoundaryReason.DATA_INTERRUPTED,
                gap.physical_contract,
                gap.segment_id,
                gap.segment_id,
                gap.effective_at,
                gap.trading_day,
            ))
        evidence_owners = {
            (item.physical_contract, item.segment_id)
            for item in read.lifecycle_evidence
        }
        def labeled_bars():
            return iter_label_calculation_segments(
                identity, read.replay_bars, read.data_interruptions,
            )
        if frequency is ProductFrequency.WEEKLY:
            first_eligible: dict[tuple[str, str], datetime] = {}
            for item in labeled_bars():
                if item.bar.observation_eligible:
                    owner = (item.bar.physical_contract, item.bar.segment_id)
                    first_eligible[owner] = min(
                        first_eligible.get(owner, item.bar.bar_end), item.bar.bar_end,
                    )
            # A rank-1 owner can begin and end before it has an eligible W1 Bar.
            # It cannot hold a reference trade, so its rollover has no replay event.
            # Likewise, an early quality gap cannot interrupt a trade before
            # the owner's first eligible Bar. Raw gaps remain in the manifest;
            # the product reader still exposes them for partial coverage.
            def eligible_before(boundary: ReferenceBoundary) -> bool:
                first = first_eligible.get((
                    boundary.physical_contract, boundary.owner_segment_id,
                ))
                return first is not None and first <= boundary.bar_end

            boundaries = [
                boundary for boundary in boundaries
                if not (
                    boundary.reason is BoundaryReason.ROLLOVER
                    and (boundary.physical_contract, boundary.owner_segment_id)
                    not in first_eligible
                ) and not (
                    boundary.reason is BoundaryReason.DATA_INTERRUPTED
                    and not eligible_before(boundary)
                )
            ]
            for boundary in boundaries:
                if (
                    boundary.reason is BoundaryReason.ROLLOVER
                    and not eligible_before(boundary)
                ):
                    raise ValueError("REFERENCE_BOUNDARY_CONTEXT_MISSING")
        if frequency is ProductFrequency.DAILY:
            boundaries = _daily_owner_reference_boundaries(boundaries, labeled_bars(), read.owners)
        def raw_bars():
            for item in labeled_bars():
                yield HistoricalInputBar(
                    item.bar.bar_end, item.bar.trading_day,
                    item.bar.physical_contract, item.bar.segment_id,
                    item.calculation_segment_id, item.bar.close,
                    _newow_input_fingerprint(
                        source_bar_sha256=item.source_bar_sha256,
                        bar_end=item.bar.bar_end,
                        physical_contract=item.bar.physical_contract,
                        owner_segment_id=item.bar.segment_id,
                        calculation_segment_id=item.calculation_segment_id,
                        quality_policy=read.input_quality_policy.value,
                    ),
                    NewowHistoricalPayload(
                        identity, item,
                        (item.bar.physical_contract, item.bar.segment_id) in evidence_owners,
                    ),
                )
        bars = HistoricalInputSpool(request.identity)
        input_fingerprints = PackedFingerprintBuilder()
        calendar_fingerprints = PackedFingerprintBuilder()
        try:
            for item in _iter_insert_boundaries(raw_bars(), tuple(boundaries)):
                bars.append(item)
                input_fingerprints.add(item.fingerprint)
                if item.strategy_input:
                    calendar_fingerprints.add(sha256(
                        _canonical((item.bar_end, item.trading_day)).encode()
                    ).hexdigest())
            bars.seal()
        except Exception:
            bars.close()
            raise
        if not bars:
            bars.close()
            raise ValueError("REFERENCE_INPUT_INCOMPLETE")
        try:
            input_proof = input_fingerprints.finish()
            calendar_proof = calendar_fingerprints.finish()
            return self._finish_newow_snapshot(
                request, query, newow_reader, read, frequency, bars,
                input_proof, calendar_proof, identity,
                production_historical=production_historical,
            )
        except BaseException:
            bars.close()
            raise

    def _finish_newow_snapshot(self, request, query, newow_reader, read, frequency, bars,
                                input_proof, calendar_proof, identity,
                                *, production_historical):
        from guiyi_quant.newow.product_contracts import ProductFrequency

        metadata_reader = getattr(newow_reader, "historical_metadata_evidence", None)
        if not callable(metadata_reader):
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = metadata_reader(
            product=query.product,
            since=bars.min_trading_day,
            through=bars.max_trading_day,
        )
        if not isinstance(metadata_evidence, dict) or not metadata_evidence:
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = {
            key: value for key, value in metadata_evidence.items()
            if key != "through"
        }
        manifest = {
            "reader": "newow_product_reader_v2",
            "query_since": request.since.isoformat(),
            "input_fingerprints": input_proof,
            "calendar_session_effective_fingerprints": calendar_proof,
            "calendar_session_source_evidence": metadata_evidence,
            "rank1": [
                [owner.contract, owner.start_trading_day.isoformat(), owner.end_trading_day.isoformat()]
                for owner in read.owners
            ],
            "boundaries": [
                sha256(_canonical(boundary).encode()).hexdigest()
                for boundary in read.boundaries
            ],
            "data_interruptions": [
                sha256(_canonical(interruption).encode()).hexdigest()
                for interruption in read.data_interruptions
            ],
            "lifecycle_owners": sorted([
                [item.physical_contract, item.segment_id]
                for item in read.lifecycle_evidence
            ]),
            "quality_policy": read.input_quality_policy.value,
            "market_source_identity": read.sources[frequency].source_identity,
            "input_policy_version": read.sources[frequency].input_policy_version,
            "formula_versions": list(request.identity.formula_versions),
            "reference_model_version": request.identity.reference_model_version,
        }
        if frequency is ProductFrequency.DAILY:
            manifest["reference_boundary_policy_version"] = NEWOW_D1_REFERENCE_BOUNDARY_POLICY
        source_integrity = None
        projection_context = None
        if production_historical:
            from app.market_data.newow.product_reader import ResolvedPerformanceWindow

            source_request = {
                "product": query.product, "frequency": frequency.value,
                "since": request.since.isoformat(),
                "through": request.through.isoformat(),
                "as_of": request.as_of.isoformat(),
            }
            source_evidence = newow_reader.historical_source_evidence(
                product=query.product, frequency=frequency.value,
                since=request.since, through=request.through, as_of=request.as_of,
            )
            if not isinstance(source_evidence, dict) or not isinstance(
                source_evidence.get("schema"), str
            ):
                raise ValueError("REFERENCE_SOURCE_INTEGRITY_MISSING")
            evidence_sha256, _ = _stream_manifest_sha256(source_evidence)
            source_integrity = {
                "schema": "reference_mds_source_integrity_v1",
                "source_schema": source_evidence["schema"],
                "request": source_request,
                "evidence_sha256": evidence_sha256,
            }
            projection_context = NewowProjectionContext(
                page_identity=identity,
                resolved=ResolvedPerformanceWindow(
                    request.since, request.through, bars.max_trading_day,
                    bars.latest_bar_end, True,
                ),
                owners=tuple(read.owners), boundaries=tuple(read.boundaries),
                data_interruptions=tuple(read.data_interruptions),
                lifecycle_evidence=tuple(read.lifecycle_evidence),
                sources=read.sources,
                input_quality_policy=read.input_quality_policy,
                reference_source_evidence_sha256=evidence_sha256,
                strategy_input_count=calendar_proof["count"],
            )
        elif self._compact_intraday_inputs and frequency.value in {"1m", "5m", "15m", "30m", "60m"}:
            # Preserve the historical fixture path's source check.
            newow_reader.historical_source_evidence(
                product=query.product, frequency=frequency.value,
                since=request.since, through=request.through, as_of=request.as_of,
            )
        # Versioned semantic proof: partition bytes remain verified by MDS, but
        # appending to a monthly partition must not invalidate an old input prefix.
        manifest["reader"] = "newow_product_reader_prefix_v5"
        if read.data_interruptions:
            semantic_gaps = getattr(read, "semantic_gap_hashes", None)
            if (
                not isinstance(semantic_gaps, tuple)
                or len(semantic_gaps) != len(read.data_interruptions)
                or any(
                    not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                    for value in semantic_gaps
                )
            ):
                raise ValueError("REFERENCE_SEMANTIC_QUALITY_PROOF_MISSING")
            manifest["data_interruptions"] = list(semantic_gaps)
        else:
            manifest["data_interruptions"] = []
        actual_day = bars.max_trading_day
        manifest["rank1"] = [
            [owner.contract, owner.start_trading_day.isoformat(),
             min(owner.end_trading_day, actual_day).isoformat()]
            for owner in read.owners if owner.start_trading_day <= actual_day
        ]
        token, manifest_bytes = _stream_manifest_sha256(manifest)
        return HistoricalInputSnapshot(
            request.identity,
            bars.min_trading_day,
            bars.latest_bar_end,
            bars,
            manifest,
            token,
            manifest_bytes + len(bars) * 256,
            projection_context,
            source_integrity,
        )
