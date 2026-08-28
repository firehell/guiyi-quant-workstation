"""Immutable schema-v3 SuBing performance snapshot domain and strict codec."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

from ..domain import BarFrequency, SeriesKind
from .cache import subing_strategy_episode_payload
from .contracts import SUBING_STRATEGY_ID
from .contracts import SubingStrategyEpisode
from .performance import (
    SubingStrategyPerformanceProjection,
    SubingStrategyPerformanceStats,
    SubingStrategyPerformanceSummary,
)


SCHEMA_VERSION = 3
_FIXED_FORMULA_VERSION = "subing_strategy_15m_v1"
_FIXED_SERIES_KIND = SeriesKind.ACTUAL_DOMINANT
_FIXED_FREQUENCY = BarFrequency.M15

_IDENTITY_FIELDS = frozenset(
    {
        "strategy_id",
        "formula_version",
        "engine_identity_sha256",
        "symbol",
        "series_kind",
        "frequency",
        "coverage_since",
        "coverage_through",
        "resolved_cutoff",
        "source_manifest_sha256",
    }
)
_PAYLOAD_FIELDS = frozenset(
    {
        "segment_count",
        "bar_count_15m",
        "context_unavailable_count",
        "immutable_prefix_segment_count",
        "immutable_prefix_counts",
        "segment_facts",
        "summary",
        "episodes",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "identity",
        "identity_sha256",
        "generated_at",
        "payload",
        "payload_sha256",
        "snapshot_sha256",
    }
)
_PREFIX_COUNT_FIELDS = frozenset(
    {
        "bar_count_1m",
        "bar_count_5m",
        "bar_count_15m",
        "context_unavailable_count",
    }
)
_SEGMENT_FACT_FIELDS = frozenset(
    {
        "contract",
        "effective_start",
        "effective_end",
        "loaded_through",
        "bar_count_1m",
        "bar_count_5m",
        "bar_count_15m",
        "context_unavailable_count",
        "source_identity",
    }
)
_SUMMARY_FIELDS = frozenset(
    {
        "overall",
        "long",
        "short",
        "open_episodes",
        "exit_reason_counts",
    }
)
_STATS_FIELDS = frozenset(
    {
        "completed",
        "positive",
        "negative",
        "flat",
        "positive_rate_percent",
        "mean_reference_change_percent",
        "median_reference_change_percent",
        "best_reference_change_percent",
        "worst_reference_change_percent",
        "mean_holding_15m_bars",
    }
)
_EXIT_REASON_FIELDS = frozenset({"reason_code", "count"})


class SubingStrategyPerformanceSnapshotError(RuntimeError):
    code = "SUBING_STRATEGY_CACHE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyPerformanceSnapshotMissingError(
    SubingStrategyPerformanceSnapshotError
):
    pass


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformancePrefixCounts:
    bar_count_1m: int
    bar_count_5m: int
    bar_count_15m: int
    context_unavailable_count: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.bar_count_1m,
                self.bar_count_5m,
                self.bar_count_15m,
                self.context_unavailable_count,
            )
        ):
            raise SubingStrategyPerformanceSnapshotError()


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSegmentFact:
    contract: str
    effective_start: date
    effective_end: date
    loaded_through: date
    bar_count_1m: int
    bar_count_5m: int
    bar_count_15m: int
    context_unavailable_count: int
    source_identity: str

    def __post_init__(self) -> None:
        if (
            not self.contract
            or _contains_path_token(self.contract)
            or type(self.effective_start) is not date
            or type(self.effective_end) is not date
            or type(self.loaded_through) is not date
            or self.effective_start > self.effective_end
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.bar_count_1m,
                    self.bar_count_5m,
                    self.bar_count_15m,
                    self.context_unavailable_count,
                )
            )
            or not _is_sha256(self.source_identity)
        ):
            raise SubingStrategyPerformanceSnapshotError()


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSnapshot:
    symbol: str
    coverage_since: date
    coverage_through: date
    resolved_cutoff: datetime
    projection: SubingStrategyPerformanceProjection
    immutable_prefix_segment_count: int
    immutable_prefix_counts: SubingStrategyPerformancePrefixCounts
    segment_facts: tuple[SubingStrategyPerformanceSegmentFact, ...]
    source_manifest_sha256: str
    engine_identity_sha256: str
    identity_sha256: str
    payload_sha256: str
    snapshot_sha256: str
    generated_at: datetime

    def __post_init__(self) -> None:
        if (
            not _is_valid_symbol(self.symbol)
            or type(self.coverage_since) is not date
            or type(self.coverage_through) is not date
            or self.coverage_since > self.coverage_through
            or not _is_utc_aware(self.resolved_cutoff)
            or not _is_utc_aware(self.generated_at)
            or type(self.immutable_prefix_segment_count) is not int
            or self.immutable_prefix_segment_count < 0
            or not _is_sha256(self.source_manifest_sha256)
            or not _is_sha256(self.engine_identity_sha256)
            or not _is_sha256(self.identity_sha256)
            or not _is_sha256(self.payload_sha256)
            or not _is_sha256(self.snapshot_sha256)
            or self.projection.strategy_id != SUBING_STRATEGY_ID
            or self.projection.formula_version != _FIXED_FORMULA_VERSION
            or self.projection.symbol != self.symbol
            or self.projection.series_kind is not _FIXED_SERIES_KIND
            or self.projection.frequency is not _FIXED_FREQUENCY
            or self.projection.coverage_since != self.coverage_since
            or self.projection.coverage_through != self.coverage_through
            or self.projection.resolved_cutoff != self.resolved_cutoff
            or (
                self.segment_facts
                and self.segment_facts[-1].loaded_through != self.coverage_through
            )
        ):
            raise SubingStrategyPerformanceSnapshotError()


def subing_strategy_performance_snapshot_from_projection(
    projection: SubingStrategyPerformanceProjection,
    *,
    immutable_prefix_segment_count: int,
    immutable_prefix_counts: SubingStrategyPerformancePrefixCounts,
    segment_facts: tuple[SubingStrategyPerformanceSegmentFact, ...],
    source_manifest_sha256: str,
    generated_at: datetime,
    engine_identity_sha256: str,
) -> SubingStrategyPerformanceSnapshot:
    if (
        projection.strategy_id != SUBING_STRATEGY_ID
        or projection.formula_version != _FIXED_FORMULA_VERSION
        or projection.series_kind is not _FIXED_SERIES_KIND
        or projection.frequency is not _FIXED_FREQUENCY
        or not _is_valid_symbol(projection.symbol)
        or projection.coverage_since > projection.coverage_through
        or type(immutable_prefix_segment_count) is not int
        or immutable_prefix_segment_count < 0
        or not _is_sha256(source_manifest_sha256)
        or not _is_sha256(engine_identity_sha256)
        or not _is_utc_aware(generated_at)
    ):
        raise SubingStrategyPerformanceSnapshotError()
    identity_payload = _identity_payload(
        symbol=projection.symbol,
        coverage_since=projection.coverage_since,
        coverage_through=projection.coverage_through,
        resolved_cutoff=projection.resolved_cutoff,
        source_manifest_sha256=source_manifest_sha256,
        engine_identity_sha256=engine_identity_sha256,
    )
    payload_payload = _payload_payload(
        projection=projection,
        immutable_prefix_segment_count=immutable_prefix_segment_count,
        immutable_prefix_counts=immutable_prefix_counts,
        segment_facts=segment_facts,
    )
    identity_sha256 = sha256(_canonical_bytes(identity_payload)).hexdigest()
    payload_sha256 = sha256(_canonical_bytes(payload_payload)).hexdigest()
    generated_at_text = generated_at.astimezone(UTC).isoformat()
    snapshot_sha256 = _snapshot_sha256(
        identity_sha256=identity_sha256,
        generated_at=generated_at_text,
        payload_sha256=payload_sha256,
    )
    return SubingStrategyPerformanceSnapshot(
        symbol=projection.symbol,
        coverage_since=projection.coverage_since,
        coverage_through=projection.coverage_through,
        resolved_cutoff=projection.resolved_cutoff,
        projection=projection,
        immutable_prefix_segment_count=immutable_prefix_segment_count,
        immutable_prefix_counts=immutable_prefix_counts,
        segment_facts=segment_facts,
        source_manifest_sha256=source_manifest_sha256,
        engine_identity_sha256=engine_identity_sha256,
        identity_sha256=identity_sha256,
        payload_sha256=payload_sha256,
        snapshot_sha256=snapshot_sha256,
        generated_at=generated_at.astimezone(UTC),
    )


def subing_strategy_performance_projection_from_snapshot(
    snapshot: SubingStrategyPerformanceSnapshot,
) -> SubingStrategyPerformanceProjection:
    return replace(snapshot.projection, cache_state="hit")


def encode_subing_strategy_performance_snapshot(
    snapshot: SubingStrategyPerformanceSnapshot,
) -> bytes:
    identity_payload = _identity_payload(
        symbol=snapshot.symbol,
        coverage_since=snapshot.coverage_since,
        coverage_through=snapshot.coverage_through,
        resolved_cutoff=snapshot.resolved_cutoff,
        source_manifest_sha256=snapshot.source_manifest_sha256,
        engine_identity_sha256=snapshot.engine_identity_sha256,
    )
    payload_payload = _payload_payload(
        projection=snapshot.projection,
        immutable_prefix_segment_count=snapshot.immutable_prefix_segment_count,
        immutable_prefix_counts=snapshot.immutable_prefix_counts,
        segment_facts=snapshot.segment_facts,
    )
    identity_sha256 = sha256(_canonical_bytes(identity_payload)).hexdigest()
    payload_sha256 = sha256(_canonical_bytes(payload_payload)).hexdigest()
    if (
        identity_sha256 != snapshot.identity_sha256
        or payload_sha256 != snapshot.payload_sha256
    ):
        raise SubingStrategyPerformanceSnapshotError()
    generated_at_text = snapshot.generated_at.astimezone(UTC).isoformat()
    snapshot_sha256 = _snapshot_sha256(
        identity_sha256=identity_sha256,
        generated_at=generated_at_text,
        payload_sha256=payload_sha256,
    )
    if snapshot_sha256 != snapshot.snapshot_sha256:
        raise SubingStrategyPerformanceSnapshotError()
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity_payload,
        "identity_sha256": identity_sha256,
        "generated_at": generated_at_text,
        "payload": payload_payload,
        "payload_sha256": payload_sha256,
        "snapshot_sha256": snapshot_sha256,
    }
    return _canonical_bytes(envelope)


def parse_subing_strategy_performance_snapshot(
    content: bytes | str | Mapping[str, object],
) -> SubingStrategyPerformanceSnapshot:
    try:
        if isinstance(content, Mapping):
            envelope = dict(content)
        elif isinstance(content, str):
            envelope = json.loads(
                content,
                object_pairs_hook=_reject_duplicate_keys,
            )
        else:
            envelope = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        if not isinstance(envelope, dict):
            raise SubingStrategyPerformanceSnapshotError()
        _reject_unknown_keys(envelope, _ENVELOPE_FIELDS)
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise SubingStrategyPerformanceSnapshotError()
        identity = envelope.get("identity")
        payload = envelope.get("payload")
        if not isinstance(identity, dict) or not isinstance(payload, dict):
            raise SubingStrategyPerformanceSnapshotError()
        _reject_unknown_keys(identity, _IDENTITY_FIELDS)
        _reject_unknown_keys(payload, _PAYLOAD_FIELDS)
        _reject_path_tokens(identity)
        _reject_path_tokens(payload)
        _validate_fixed_identity(identity)
        symbol = str(identity["symbol"])
        coverage_since = date.fromisoformat(str(identity["coverage_since"]))
        coverage_through = date.fromisoformat(str(identity["coverage_through"]))
        resolved_cutoff = datetime.fromisoformat(str(identity["resolved_cutoff"]))
        if not _is_utc_aware(resolved_cutoff):
            raise SubingStrategyPerformanceSnapshotError()
        source_manifest_sha256 = str(identity["source_manifest_sha256"])
        engine_identity_sha256 = str(identity["engine_identity_sha256"])
        identity_payload = _identity_payload(
            symbol=symbol,
            coverage_since=coverage_since,
            coverage_through=coverage_through,
            resolved_cutoff=resolved_cutoff,
            source_manifest_sha256=source_manifest_sha256,
            engine_identity_sha256=engine_identity_sha256,
        )
        identity_sha256 = sha256(_canonical_bytes(identity_payload)).hexdigest()
        if envelope.get("identity_sha256") != identity_sha256:
            raise SubingStrategyPerformanceSnapshotError()
        immutable_prefix_segment_count = int(payload["immutable_prefix_segment_count"])
        immutable_prefix_counts = _parse_prefix_counts(
            payload["immutable_prefix_counts"]
        )
        segment_facts = _parse_segment_facts(payload["segment_facts"])
        projection = _parse_projection_payload(
            payload,
            symbol=symbol,
            coverage_since=coverage_since,
            coverage_through=coverage_through,
            resolved_cutoff=resolved_cutoff,
        )
        payload_payload = _payload_payload(
            projection=projection,
            immutable_prefix_segment_count=immutable_prefix_segment_count,
            immutable_prefix_counts=immutable_prefix_counts,
            segment_facts=segment_facts,
        )
        payload_sha256 = sha256(_canonical_bytes(payload_payload)).hexdigest()
        if envelope.get("payload_sha256") != payload_sha256:
            raise SubingStrategyPerformanceSnapshotError()
        generated_at = datetime.fromisoformat(str(envelope["generated_at"]))
        if not _is_utc_aware(generated_at):
            raise SubingStrategyPerformanceSnapshotError()
        generated_at_text = generated_at.astimezone(UTC).isoformat()
        snapshot_sha256 = _snapshot_sha256(
            identity_sha256=identity_sha256,
            generated_at=generated_at_text,
            payload_sha256=payload_sha256,
        )
        if envelope.get("snapshot_sha256") != snapshot_sha256:
            raise SubingStrategyPerformanceSnapshotError()
        return SubingStrategyPerformanceSnapshot(
            symbol=symbol,
            coverage_since=coverage_since,
            coverage_through=coverage_through,
            resolved_cutoff=resolved_cutoff.astimezone(UTC),
            projection=projection,
            immutable_prefix_segment_count=immutable_prefix_segment_count,
            immutable_prefix_counts=immutable_prefix_counts,
            segment_facts=segment_facts,
            source_manifest_sha256=source_manifest_sha256,
            engine_identity_sha256=engine_identity_sha256,
            identity_sha256=identity_sha256,
            payload_sha256=payload_sha256,
            snapshot_sha256=snapshot_sha256,
            generated_at=generated_at.astimezone(UTC),
        )
    except SubingStrategyPerformanceSnapshotError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise SubingStrategyPerformanceSnapshotError() from None


def _identity_payload(
    *,
    symbol: str,
    coverage_since: date,
    coverage_through: date,
    resolved_cutoff: datetime,
    source_manifest_sha256: str,
    engine_identity_sha256: str,
) -> dict[str, object]:
    return {
        "strategy_id": SUBING_STRATEGY_ID,
        "formula_version": _FIXED_FORMULA_VERSION,
        "engine_identity_sha256": engine_identity_sha256,
        "symbol": symbol,
        "series_kind": _FIXED_SERIES_KIND.value,
        "frequency": _FIXED_FREQUENCY.value,
        "coverage_since": coverage_since.isoformat(),
        "coverage_through": coverage_through.isoformat(),
        "resolved_cutoff": resolved_cutoff.astimezone(UTC).isoformat(),
        "source_manifest_sha256": source_manifest_sha256,
    }


def _payload_payload(
    *,
    projection: SubingStrategyPerformanceProjection,
    immutable_prefix_segment_count: int,
    immutable_prefix_counts: SubingStrategyPerformancePrefixCounts,
    segment_facts: tuple[SubingStrategyPerformanceSegmentFact, ...],
) -> dict[str, object]:
    return {
        "segment_count": projection.segment_count,
        "bar_count_15m": projection.bar_count_15m,
        "context_unavailable_count": projection.context_unavailable_count,
        "immutable_prefix_segment_count": immutable_prefix_segment_count,
        "immutable_prefix_counts": _prefix_counts_payload(immutable_prefix_counts),
        "segment_facts": [_segment_fact_payload(fact) for fact in segment_facts],
        "summary": _summary_payload(projection.summary),
        "episodes": [
            subing_strategy_episode_payload(episode) for episode in projection.episodes
        ],
    }


def _prefix_counts_payload(
    counts: SubingStrategyPerformancePrefixCounts,
) -> dict[str, object]:
    return {
        "bar_count_1m": counts.bar_count_1m,
        "bar_count_5m": counts.bar_count_5m,
        "bar_count_15m": counts.bar_count_15m,
        "context_unavailable_count": counts.context_unavailable_count,
    }


def _segment_fact_payload(
    fact: SubingStrategyPerformanceSegmentFact,
) -> dict[str, object]:
    return {
        "contract": fact.contract,
        "effective_start": fact.effective_start.isoformat(),
        "effective_end": fact.effective_end.isoformat(),
        "loaded_through": fact.loaded_through.isoformat(),
        "bar_count_1m": fact.bar_count_1m,
        "bar_count_5m": fact.bar_count_5m,
        "bar_count_15m": fact.bar_count_15m,
        "context_unavailable_count": fact.context_unavailable_count,
        "source_identity": fact.source_identity,
    }


def _summary_payload(summary: SubingStrategyPerformanceSummary) -> dict[str, object]:
    return {
        "overall": _stats_payload(summary.overall),
        "long": _stats_payload(summary.long),
        "short": _stats_payload(summary.short),
        "open_episodes": summary.open_episodes,
        "exit_reason_counts": [
            {"reason_code": code, "count": count}
            for code, count in summary.exit_reason_counts
        ],
    }


def _stats_payload(stats: SubingStrategyPerformanceStats) -> dict[str, object]:
    return {
        "completed": stats.completed,
        "positive": stats.positive,
        "negative": stats.negative,
        "flat": stats.flat,
        "positive_rate_percent": _decimal_text(stats.positive_rate_percent),
        "mean_reference_change_percent": _decimal_text(
            stats.mean_reference_change_percent
        ),
        "median_reference_change_percent": _decimal_text(
            stats.median_reference_change_percent
        ),
        "best_reference_change_percent": _decimal_text(
            stats.best_reference_change_percent
        ),
        "worst_reference_change_percent": _decimal_text(
            stats.worst_reference_change_percent
        ),
        "mean_holding_15m_bars": _decimal_text(stats.mean_holding_15m_bars),
    }


def _parse_prefix_counts(payload: object) -> SubingStrategyPerformancePrefixCounts:
    if not isinstance(payload, dict):
        raise SubingStrategyPerformanceSnapshotError()
    _reject_unknown_keys(payload, _PREFIX_COUNT_FIELDS)
    return SubingStrategyPerformancePrefixCounts(
        bar_count_1m=int(payload["bar_count_1m"]),
        bar_count_5m=int(payload["bar_count_5m"]),
        bar_count_15m=int(payload["bar_count_15m"]),
        context_unavailable_count=int(payload["context_unavailable_count"]),
    )


def _parse_segment_facts(
    payload: object,
) -> tuple[SubingStrategyPerformanceSegmentFact, ...]:
    if not isinstance(payload, list):
        raise SubingStrategyPerformanceSnapshotError()
    facts: list[SubingStrategyPerformanceSegmentFact] = []
    for item in payload:
        if not isinstance(item, dict):
            raise SubingStrategyPerformanceSnapshotError()
        _reject_unknown_keys(item, _SEGMENT_FACT_FIELDS)
        _reject_path_tokens(item)
        facts.append(
            SubingStrategyPerformanceSegmentFact(
                contract=str(item["contract"]),
                effective_start=date.fromisoformat(str(item["effective_start"])),
                effective_end=date.fromisoformat(str(item["effective_end"])),
                loaded_through=date.fromisoformat(str(item["loaded_through"])),
                bar_count_1m=int(item["bar_count_1m"]),
                bar_count_5m=int(item["bar_count_5m"]),
                bar_count_15m=int(item["bar_count_15m"]),
                context_unavailable_count=int(item["context_unavailable_count"]),
                source_identity=str(item["source_identity"]),
            )
        )
    return tuple(facts)


def _parse_projection_payload(
    payload: Mapping[str, object],
    *,
    symbol: str,
    coverage_since: date,
    coverage_through: date,
    resolved_cutoff: datetime,
) -> SubingStrategyPerformanceProjection:
    summary = _parse_summary(payload["summary"])
    episodes = tuple(
        _parse_episode(item)
        for item in payload["episodes"]  # type: ignore[arg-type]
    )
    return SubingStrategyPerformanceProjection(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version=_FIXED_FORMULA_VERSION,
        symbol=symbol,
        series_kind=_FIXED_SERIES_KIND,
        frequency=_FIXED_FREQUENCY,
        coverage_since=coverage_since,
        coverage_through=coverage_through,
        resolved_cutoff=resolved_cutoff.astimezone(UTC),
        segment_count=int(payload["segment_count"]),
        bar_count_15m=int(payload["bar_count_15m"]),
        context_unavailable_count=int(payload["context_unavailable_count"]),
        cache_state="hit",
        summary=summary,
        episodes=episodes,
    )


def _parse_summary(payload: object) -> SubingStrategyPerformanceSummary:
    if not isinstance(payload, dict):
        raise SubingStrategyPerformanceSnapshotError()
    _reject_unknown_keys(payload, _SUMMARY_FIELDS)
    exit_reason_counts = payload["exit_reason_counts"]
    if not isinstance(exit_reason_counts, list):
        raise SubingStrategyPerformanceSnapshotError()
    reasons: list[tuple[str, int]] = []
    for item in exit_reason_counts:
        if not isinstance(item, dict):
            raise SubingStrategyPerformanceSnapshotError()
        _reject_unknown_keys(item, _EXIT_REASON_FIELDS)
        reasons.append((str(item["reason_code"]), int(item["count"])))
    return SubingStrategyPerformanceSummary(
        overall=_parse_stats(payload["overall"]),
        long=_parse_stats(payload["long"]),
        short=_parse_stats(payload["short"]),
        open_episodes=int(payload["open_episodes"]),
        exit_reason_counts=tuple(reasons),
    )


def _parse_stats(payload: object) -> SubingStrategyPerformanceStats:
    if not isinstance(payload, dict):
        raise SubingStrategyPerformanceSnapshotError()
    _reject_unknown_keys(payload, _STATS_FIELDS)
    return SubingStrategyPerformanceStats(
        completed=int(payload["completed"]),
        positive=int(payload["positive"]),
        negative=int(payload["negative"]),
        flat=int(payload["flat"]),
        positive_rate_percent=_optional_decimal(payload["positive_rate_percent"]),
        mean_reference_change_percent=_optional_decimal(
            payload["mean_reference_change_percent"]
        ),
        median_reference_change_percent=_optional_decimal(
            payload["median_reference_change_percent"]
        ),
        best_reference_change_percent=_optional_decimal(
            payload["best_reference_change_percent"]
        ),
        worst_reference_change_percent=_optional_decimal(
            payload["worst_reference_change_percent"]
        ),
        mean_holding_15m_bars=_optional_decimal(payload["mean_holding_15m_bars"]),
    )


def _parse_episode(payload: object) -> SubingStrategyEpisode:
    from .cache import _parse_episode

    try:
        return _parse_episode(payload)
    except Exception:
        raise SubingStrategyPerformanceSnapshotError() from None


def _validate_fixed_identity(identity: Mapping[str, object]) -> None:
    if (
        identity.get("strategy_id") != SUBING_STRATEGY_ID
        or identity.get("formula_version") != _FIXED_FORMULA_VERSION
        or identity.get("series_kind") != _FIXED_SERIES_KIND.value
        or identity.get("frequency") != _FIXED_FREQUENCY.value
        or not _is_valid_symbol(str(identity.get("symbol", "")))
        or not _is_sha256(str(identity.get("source_manifest_sha256", "")))
        or not _is_sha256(identity.get("engine_identity_sha256"))
    ):
        raise SubingStrategyPerformanceSnapshotError()


def _snapshot_sha256(
    *,
    identity_sha256: str,
    generated_at: str,
    payload_sha256: str,
) -> str:
    return sha256(
        _canonical_bytes(
            {
                "identity_sha256": identity_sha256,
                "generated_at": generated_at,
                "payload_sha256": payload_sha256,
            }
        )
    ).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise SubingStrategyPerformanceSnapshotError()
    return dict(pairs)


def _reject_unknown_keys(
    payload: Mapping[str, object], allowed: frozenset[str]
) -> None:
    if set(payload) - allowed:
        raise SubingStrategyPerformanceSnapshotError()


def _reject_path_tokens(value: object) -> None:
    if isinstance(value, str):
        if _contains_path_token(value):
            raise SubingStrategyPerformanceSnapshotError()
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_path_tokens(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_path_tokens(item)


def _contains_path_token(value: str) -> bool:
    return value.startswith("/") or ".." in value


def _is_valid_symbol(value: str) -> bool:
    return bool(
        value and value.isascii() and value.isalpha() and value == value.lower()
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_utc_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SubingStrategyPerformanceSnapshotError()
    try:
        result = Decimal(value)
    except Exception:
        raise SubingStrategyPerformanceSnapshotError() from None
    if not result.is_finite():
        raise SubingStrategyPerformanceSnapshotError()
    return result


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
