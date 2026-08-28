from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.subing_research import SubingDirection
from app.market_data.subing_strategy.contracts import (
    SUBING_STRATEGY_ID,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyEpisodeState,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
    SubingStrategyPerformanceStats,
    SubingStrategyPerformanceSummary,
    summarize_subing_strategy_episodes,
)
from app.market_data.subing_strategy.performance_snapshot import (
    SCHEMA_VERSION,
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    SubingStrategyPerformanceSnapshot,
    SubingStrategyPerformanceSnapshotError,
    _canonical_bytes,
    _identity_payload,
    _payload_payload,
    _snapshot_sha256,
    encode_subing_strategy_performance_snapshot,
    parse_subing_strategy_performance_snapshot,
    subing_strategy_performance_projection_from_snapshot,
    subing_strategy_performance_snapshot_from_projection,
)

from research.subing_strategy_fixtures import action_fixture


def _stats(**overrides: object) -> SubingStrategyPerformanceStats:
    base = SubingStrategyPerformanceStats(
        completed=2,
        positive=1,
        negative=1,
        flat=0,
        positive_rate_percent=Decimal("50"),
        mean_reference_change_percent=Decimal("0.5"),
        median_reference_change_percent=Decimal("0.5"),
        best_reference_change_percent=Decimal("2"),
        worst_reference_change_percent=Decimal("-1"),
        mean_holding_15m_bars=Decimal("3"),
    )
    return replace(base, **overrides)


def _summary() -> SubingStrategyPerformanceSummary:
    return SubingStrategyPerformanceSummary(
        overall=_stats(),
        long=_stats(completed=1, positive=1, negative=0, flat=0),
        short=_stats(completed=1, positive=0, negative=1, flat=0),
        open_episodes=0,
        exit_reason_counts=(("EMA21_BREACH_LONG", 2),),
    )


def _episode(change: str) -> SubingStrategyEpisode:
    entry = action_fixture(kind=SubingStrategyActionKind.OPEN_LONG)
    exit_action = replace(
        action_fixture(
            kind=SubingStrategyActionKind.CLOSE_LONG,
            episode_id=entry.episode_id,
        ),
        reason_codes=("EMA21_BREACH_LONG",),
    )
    return SubingStrategyEpisode(
        episode_id=entry.episode_id,
        direction=SubingDirection.LONG,
        entry_action=entry,
        exit_action=exit_action,
        state=SubingStrategyEpisodeState.CLOSED,
        holding_bar_count=4,
        reference_change_percent=Decimal(change),
        current_reference_change_percent=None,
        latest_reference_price=None,
        exit_reason_codes=exit_action.reason_codes,
        structure_exit_available=False,
    )


def _projection() -> SubingStrategyPerformanceProjection:
    episodes = (_episode("2"), _episode("-1"))
    return SubingStrategyPerformanceProjection(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M15,
        coverage_since=date(2020, 1, 2),
        coverage_through=date(2026, 8, 26),
        resolved_cutoff=datetime(2026, 8, 26, 7, tzinfo=UTC),
        segment_count=2,
        bar_count_15m=24,
        context_unavailable_count=1,
        cache_state="unavailable",
        summary=summarize_subing_strategy_episodes(episodes),
        episodes=episodes,
    )


def _prefix_counts() -> SubingStrategyPerformancePrefixCounts:
    return SubingStrategyPerformancePrefixCounts(
        bar_count_1m=1000,
        bar_count_5m=200,
        bar_count_15m=12,
        context_unavailable_count=0,
    )


def _segment_fact() -> SubingStrategyPerformanceSegmentFact:
    return SubingStrategyPerformanceSegmentFact(
        contract="jm2605",
        effective_start=date(2026, 1, 5),
        effective_end=date(2026, 8, 26),
        loaded_through=date(2026, 8, 26),
        bar_count_1m=500,
        bar_count_5m=100,
        bar_count_15m=12,
        context_unavailable_count=1,
        source_identity="a" * 64,
    )


def _snapshot(
    *,
    generated_at: datetime | None = None,
) -> SubingStrategyPerformanceSnapshot:
    return subing_strategy_performance_snapshot_from_projection(
        _projection(),
        immutable_prefix_segment_count=1,
        immutable_prefix_counts=_prefix_counts(),
        segment_facts=(_segment_fact(),),
        source_manifest_sha256="b" * 64,
        generated_at=generated_at or datetime(2026, 8, 27, 8, tzinfo=UTC),
    )


def test_schema_version_constant_is_three() -> None:
    assert SCHEMA_VERSION == 3


def test_snapshot_error_exposes_fixed_public_code() -> None:
    exc = SubingStrategyPerformanceSnapshotError()

    assert str(exc) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"
    assert exc.code == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def test_round_trip_preserves_projection_episodes_prefix_and_segment_facts() -> None:
    snapshot = _snapshot()
    encoded = encode_subing_strategy_performance_snapshot(snapshot)
    restored = parse_subing_strategy_performance_snapshot(encoded)
    projection = subing_strategy_performance_projection_from_snapshot(restored)

    assert restored.symbol == "jm"
    assert restored.coverage_since == date(2020, 1, 2)
    assert restored.coverage_through == date(2026, 8, 26)
    assert restored.resolved_cutoff == datetime(2026, 8, 26, 7, tzinfo=UTC)
    assert restored.generated_at == datetime(2026, 8, 27, 8, tzinfo=UTC)
    assert restored.immutable_prefix_segment_count == 1
    assert restored.immutable_prefix_counts == _prefix_counts()
    assert restored.segment_facts == (_segment_fact(),)
    assert restored.source_manifest_sha256 == "b" * 64
    assert len(restored.identity_sha256) == 64
    assert restored.identity_sha256 == snapshot.identity_sha256
    assert restored.payload_sha256 == snapshot.payload_sha256
    assert restored.snapshot_sha256 == snapshot.snapshot_sha256
    assert projection.episodes == _projection().episodes
    assert projection.summary == _projection().summary
    assert projection.segment_count == 2
    assert projection.bar_count_15m == 24
    assert projection.context_unavailable_count == 1


def test_encode_hash_is_independent_of_dict_insertion_order() -> None:
    first = _snapshot()
    second = subing_strategy_performance_snapshot_from_projection(
        _projection(),
        immutable_prefix_segment_count=1,
        immutable_prefix_counts=_prefix_counts(),
        segment_facts=(_segment_fact(),),
        source_manifest_sha256="b" * 64,
        generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
    )

    assert encode_subing_strategy_performance_snapshot(first) == (
        encode_subing_strategy_performance_snapshot(second)
    )


def test_encoded_artifact_excludes_sensitive_or_internal_fields() -> None:
    text = encode_subing_strategy_performance_snapshot(_snapshot()).decode("utf-8")

    assert "/Users/" not in text
    assert "/var/" not in text
    assert "token" not in text
    assert "password" not in text
    assert "provider" not in text
    assert "machine_state" not in text
    assert "order_id" not in text
    assert "account_id" not in text


@pytest.mark.parametrize(
    ("mutator",),
    [
        (lambda envelope: envelope.update({"schema_version": 2}),),
        (lambda envelope: envelope.update({"schema_version": 4}),),
        (lambda envelope: envelope["identity"].update({"strategy_id": "other"}),),
        (lambda envelope: envelope["identity"].update({"series_kind": "continuous"}),),
        (lambda envelope: envelope["identity"].update({"frequency": "5m"}),),
        (lambda envelope: envelope["identity"].update({"symbol": "rb"}),),
        (
            lambda envelope: envelope["identity"].update(
                {"coverage_through": "2026-08-25"}
            ),
        ),
        (lambda envelope: envelope.update({"generated_at": "2026-08-27T08:00:00"}),),
        (lambda envelope: envelope["identity"].update({"unknown": "x"}),),
        (lambda envelope: envelope["payload"].update({"unknown": "x"}),),
        (lambda envelope: envelope.update({"unknown": "x"}),),
        (lambda envelope: envelope["payload"]["segment_facts"][0].update({"unknown": "x"}),),
        (lambda envelope: envelope.update({"identity_sha256": "0" * 64}),),
        (lambda envelope: envelope.update({"payload_sha256": "0" * 64}),),
        (lambda envelope: envelope.update({"snapshot_sha256": "0" * 64}),),
        (
            lambda envelope: envelope["payload"]["segment_facts"][0].update(
                {"contract": "/tmp/jm2605"}
            ),
        ),
        (
            lambda envelope: envelope["payload"]["segment_facts"][0].update(
                {"contract": "../jm2605"}
            ),
        ),
    ],
)
def test_parse_rejects_malformed_or_mismatched_artifacts(
    mutator: object,
) -> None:
    envelope = json.loads(encode_subing_strategy_performance_snapshot(_snapshot()))
    mutator(envelope)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        parse_subing_strategy_performance_snapshot(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

    assert str(exc_info.value) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def test_parse_rejects_duplicate_json_keys() -> None:
    raw = (
        b'{"schema_version":3,"schema_version":3,'
        b'"identity":{},"identity_sha256":"0","generated_at":"2026-08-27T08:00:00+00:00",'
        b'"payload":{},"payload_sha256":"0","snapshot_sha256":"0"}'
    )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        parse_subing_strategy_performance_snapshot(raw)


def test_snapshot_constructor_rejects_invalid_symbol_or_dates() -> None:
    projection = _projection()
    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        subing_strategy_performance_snapshot_from_projection(
            replace(projection, symbol="JM"),
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(_segment_fact(),),
            source_manifest_sha256="b" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        subing_strategy_performance_snapshot_from_projection(
            replace(projection, coverage_through=date(2026, 8, 25)),
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(_segment_fact(),),
            source_manifest_sha256="b" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        subing_strategy_performance_snapshot_from_projection(
            projection,
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(_segment_fact(),),
            source_manifest_sha256="b" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC).replace(tzinfo=None),
        )


def test_prefix_counts_reject_negative_values() -> None:
    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        SubingStrategyPerformancePrefixCounts(
            bar_count_1m=-1,
            bar_count_5m=0,
            bar_count_15m=0,
            context_unavailable_count=0,
        )


def _stale_tail_artifact_bytes() -> bytes:
    snapshot = _snapshot()
    envelope = json.loads(encode_subing_strategy_performance_snapshot(snapshot))
    envelope["payload"]["segment_facts"][0]["loaded_through"] = "2026-08-25"
    identity = envelope["identity"]
    identity_payload = _identity_payload(
        symbol=str(identity["symbol"]),
        coverage_since=date.fromisoformat(str(identity["coverage_since"])),
        coverage_through=date.fromisoformat(str(identity["coverage_through"])),
        resolved_cutoff=datetime.fromisoformat(str(identity["resolved_cutoff"])),
        source_manifest_sha256=str(identity["source_manifest_sha256"]),
    )
    identity_sha256 = sha256(_canonical_bytes(identity_payload)).hexdigest()
    projection = _projection()
    stale_fact = replace(_segment_fact(), loaded_through=date(2026, 8, 25))
    payload_payload = _payload_payload(
        projection=projection,
        immutable_prefix_segment_count=snapshot.immutable_prefix_segment_count,
        immutable_prefix_counts=snapshot.immutable_prefix_counts,
        segment_facts=(stale_fact,),
    )
    payload_sha256 = sha256(_canonical_bytes(payload_payload)).hexdigest()
    generated_at_text = str(envelope["generated_at"])
    snapshot_sha256 = _snapshot_sha256(
        identity_sha256=identity_sha256,
        generated_at=generated_at_text,
        payload_sha256=payload_sha256,
    )
    envelope["identity"] = identity_payload
    envelope["identity_sha256"] = identity_sha256
    envelope["payload"] = payload_payload
    envelope["payload_sha256"] = payload_sha256
    envelope["snapshot_sha256"] = snapshot_sha256
    return _canonical_bytes(envelope)


def test_snapshot_post_init_rejects_stale_tail_loaded_through() -> None:
    projection = _projection()
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        SubingStrategyPerformanceSnapshot(
            symbol=projection.symbol,
            coverage_since=projection.coverage_since,
            coverage_through=projection.coverage_through,
            resolved_cutoff=projection.resolved_cutoff,
            projection=projection,
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(replace(_segment_fact(), loaded_through=date(2026, 8, 25)),),
            source_manifest_sha256="b" * 64,
            identity_sha256="a" * 64,
            payload_sha256="c" * 64,
            snapshot_sha256="d" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        )

    assert str(exc_info.value) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def test_parse_rejects_hash_consistent_stale_tail_loaded_through() -> None:
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        parse_subing_strategy_performance_snapshot(_stale_tail_artifact_bytes())

    assert str(exc_info.value) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def test_round_trip_projection_reports_cache_hit() -> None:
    snapshot = _snapshot()
    encoded = encode_subing_strategy_performance_snapshot(snapshot)
    restored = parse_subing_strategy_performance_snapshot(encoded)
    projection = subing_strategy_performance_projection_from_snapshot(restored)

    assert projection.cache_state == "hit"
    assert projection.cache_identity_sha256 is None
    assert projection.cache_generated_at is None
    assert "cache_state" not in encoded.decode("utf-8")
