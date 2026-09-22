"""Typed historical-input seam for P4 reference replay.

Implementations must obtain these facts from the existing MarketDataService readers.
The seam intentionally has no provider, Redis, or write capability.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from contextlib import AbstractContextManager, nullcontext
from hashlib import sha256
import json
from typing import Callable, Protocol

from guiyi_quant.reference_trading import ReferenceBoundary, StreamIdentity


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


@dataclass(frozen=True, slots=True)
class HistoricalInputSnapshot:
    stream: StreamIdentity
    storage_start: date
    completed_through: datetime | None
    bars: tuple[HistoricalInputBar, ...]
    dependency_manifest: dict[str, object]
    source_token: str
    input_bytes: int

    def __post_init__(self) -> None:
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
        previous_by_segment: dict[tuple[str, str, str], datetime] = {}
        fingerprints: set[str] = set()
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
        if self.bars and self.completed_through != max(
            bar.bar_end for bar in self.bars
        ):
            raise ValueError("completed_through must equal the latest input event")


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
                anchor, boundaries=(*anchor.boundaries, normalized),
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
    ) -> None:
        self._newow = newow_reader
        self._subing = subing_service
        self._read_guard = read_guard

    def plan_stream(self, request: object) -> HistoricalInputSnapshot:
        with self._read_guard():
            return self._read(request)

    def estimate_stream(self, request: object) -> tuple[int, int]:
        """Conservative pre-materialization ceiling for explicit work budgets."""
        from app.reference_trading.planning import HistoricalStreamRequest

        if not isinstance(request, HistoricalStreamRequest):
            raise TypeError("request must be HistoricalStreamRequest")
        normalized = request.identity.strategy_code.replace("-", "_")
        if normalized == "subing_reference":
            start_reader = getattr(self._subing, "historical_storage_start", None)
            product = request.identity.product.lower()
        elif normalized.startswith("newow_"):
            start_reader = getattr(self._newow, "historical_storage_start", None)
            product = request.identity.product.lower()
        else:
            raise ValueError("REFERENCE_CAPABILITY_UNSUPPORTED")
        if not callable(start_reader):
            raise ValueError("REFERENCE_INPUT_BOUND_UNAVAILABLE")
        storage_start = start_reader(product)
        if type(storage_start) is not date or storage_start > request.through:
            raise ValueError("REFERENCE_INPUT_BOUND_UNAVAILABLE")
        days = (request.through - storage_start).days + 1
        minutes = {"15m": 15, "30m": 30, "60m": 60}.get(
            request.identity.frequency
        )
        per_day = 1 if minutes is None else 1440 // minutes
        # One additional event per day covers authoritative boundaries.  Four
        # KiB per event bounds the typed payload plus manifest representation.
        max_events = days * (per_day + 1)
        return max_events, max_events * 4096

    def load_stream(
        self, request: object, *, expected_source_token: str,
    ) -> HistoricalInputSnapshot:
        with self._read_guard():
            snapshot = self._read(request)
        if snapshot.source_token != expected_source_token:
            raise ValueError("SOURCE_CHANGED")
        return snapshot

    def revalidate(self, request: object, *, expected_source_token: str) -> bool:
        try:
            return self._read(request).source_token == expected_source_token
        except (TypeError, ValueError):
            return False

    def source_guard(self, request: object, *, expected_source_token: str):
        reader = self

        class Guard:
            def __enter__(self):
                self._guard = reader._read_guard()
                self._guard.__enter__()
                if reader._read(request).source_token != expected_source_token:
                    self._guard.__exit__(None, None, None)
                    raise ValueError("SOURCE_CHANGED")
                return self

            def __exit__(self, exc_type, exc, tb):
                return self._guard.__exit__(exc_type, exc, tb)

        return Guard()

    def _read(self, request: object) -> HistoricalInputSnapshot:
        from app.reference_trading.planning import HistoricalStreamRequest

        if not isinstance(request, HistoricalStreamRequest):
            raise TypeError("request must be HistoricalStreamRequest")
        normalized = request.identity.strategy_code.replace("-", "_")
        if normalized == "subing_reference":
            return self._read_subing(request)
        if normalized.startswith("newow_"):
            return self._read_newow(request)
        raise ValueError("REFERENCE_CAPABILITY_UNSUPPORTED")

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
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary
        from app.market_data.newow.product_query import NewowProductQuery
        from app.reference_trading.service import NewowHistoricalPayload

        strategy = ProductStrategy(request.identity.strategy_code.replace("-", "_").removeprefix("newow_"))
        frequency = ProductFrequency(request.identity.frequency)
        query = NewowProductQuery(
            request.identity.product.lower(), strategy, frequency,
            request.since, request.through,
            request.since, request.through, request.as_of,
        )
        read = self._newow.load(query, request.as_of)
        identity = build_product_identity(
            query.product, strategy, frequency,
            input_quality_policy=read.input_quality_policy,
        )
        if (
            request.identity.product != identity.product
            or request.identity.formula_versions != identity.formula_versions
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
        bars = [HistoricalInputBar(
            item.bar.bar_end,
            item.bar.trading_day,
            item.bar.physical_contract,
            item.bar.segment_id,
            item.calculation_segment_id,
            item.bar.close,
            sha256(_canonical({
                "source": item.source_bar_sha256,
                "bar_end": item.bar.bar_end,
                "quality_policy": read.input_quality_policy.value,
            }).encode()).hexdigest(),
            NewowHistoricalPayload(
                identity,
                item,
                (item.bar.physical_contract, item.bar.segment_id) in evidence_owners,
            ),
        ) for item in read.replay_bars]
        bars = _insert_boundaries(bars, tuple(boundaries))
        metadata_reader = getattr(self._newow, "historical_metadata_evidence", None)
        if not callable(metadata_reader):
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = metadata_reader(
            product=query.product,
            since=min(bar.trading_day for bar in bars),
            through=request.through,
        )
        if not isinstance(metadata_evidence, dict) or not metadata_evidence:
            raise ValueError("REFERENCE_METADATA_EVIDENCE_MISSING")
        metadata_evidence = {
            key: value for key, value in metadata_evidence.items()
            if key != "through"
        }
        manifest = {
            "reader": "newow_product_reader_v1",
            "query_since": request.since.isoformat(),
            "input_fingerprints": [bar.fingerprint for bar in bars],
            "calendar_session_effective_fingerprints": [
                sha256(_canonical((bar.bar_end, bar.trading_day)).encode()).hexdigest()
                for bar in bars if bar.strategy_input
            ],
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
        token = sha256(_canonical(manifest).encode()).hexdigest()
        return HistoricalInputSnapshot(
            request.identity,
            min(bar.trading_day for bar in bars),
            max((bar.bar_end for bar in bars), default=None),
            tuple(bars),
            manifest,
            token,
            len(_canonical(manifest).encode()) + len(bars) * 256,
        )
