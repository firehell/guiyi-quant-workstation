from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from stat import S_IMODE

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
from app.market_data.subing_strategy.performance_snapshot_store import (
    SubingStrategyPerformanceFileSnapshotStore,
    SubingStrategyPerformanceSnapshotReceipt,
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
        engine_identity_sha256="e" * 64,
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
        engine_identity_sha256="e" * 64,
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
        (
            lambda envelope: envelope["payload"]["segment_facts"][0].update(
                {"unknown": "x"}
            ),
        ),
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
            engine_identity_sha256="e" * 64,
        )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        subing_strategy_performance_snapshot_from_projection(
            replace(projection, coverage_through=date(2026, 8, 25)),
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(_segment_fact(),),
            source_manifest_sha256="b" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
            engine_identity_sha256="e" * 64,
        )

    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        subing_strategy_performance_snapshot_from_projection(
            projection,
            immutable_prefix_segment_count=1,
            immutable_prefix_counts=_prefix_counts(),
            segment_facts=(_segment_fact(),),
            source_manifest_sha256="b" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC).replace(tzinfo=None),
            engine_identity_sha256="e" * 64,
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
        engine_identity_sha256=str(identity["engine_identity_sha256"]),
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
            engine_identity_sha256="e" * 64,
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


def _ordered_segment_facts_with_stale_tail() -> tuple[
    SubingStrategyPerformanceSegmentFact,
    SubingStrategyPerformanceSegmentFact,
]:
    return (
        replace(
            _segment_fact(),
            contract="jm2505",
            effective_start=date(2025, 1, 5),
            effective_end=date(2025, 12, 31),
            loaded_through=date(2026, 8, 26),
            source_identity="c" * 64,
        ),
        replace(
            _segment_fact(),
            loaded_through=date(2026, 8, 25),
            source_identity="d" * 64,
        ),
    )


def _stale_ordered_tail_artifact_bytes() -> bytes:
    snapshot = _snapshot()
    envelope = json.loads(encode_subing_strategy_performance_snapshot(snapshot))
    segment_facts = _ordered_segment_facts_with_stale_tail()
    identity = envelope["identity"]
    identity_payload = _identity_payload(
        symbol=str(identity["symbol"]),
        coverage_since=date.fromisoformat(str(identity["coverage_since"])),
        coverage_through=date.fromisoformat(str(identity["coverage_through"])),
        resolved_cutoff=datetime.fromisoformat(str(identity["resolved_cutoff"])),
        source_manifest_sha256=str(identity["source_manifest_sha256"]),
        engine_identity_sha256=str(identity["engine_identity_sha256"]),
    )
    identity_sha256 = sha256(_canonical_bytes(identity_payload)).hexdigest()
    projection = _projection()
    payload_payload = _payload_payload(
        projection=projection,
        immutable_prefix_segment_count=snapshot.immutable_prefix_segment_count,
        immutable_prefix_counts=snapshot.immutable_prefix_counts,
        segment_facts=segment_facts,
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


def test_snapshot_post_init_rejects_stale_last_segment_when_earlier_segment_is_current() -> (
    None
):
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
            segment_facts=_ordered_segment_facts_with_stale_tail(),
            source_manifest_sha256="b" * 64,
            engine_identity_sha256="e" * 64,
            identity_sha256="a" * 64,
            payload_sha256="c" * 64,
            snapshot_sha256="d" * 64,
            generated_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
        )

    assert str(exc_info.value) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def test_parse_rejects_hash_consistent_stale_last_segment_when_earlier_segment_is_current() -> (
    None
):
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        parse_subing_strategy_performance_snapshot(_stale_ordered_tail_artifact_bytes())

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


_STORE_MODULE = "app.market_data.subing_strategy.performance_snapshot_store"


def _file_store(root: Path) -> SubingStrategyPerformanceFileSnapshotStore:
    return SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
    )


def _snapshot_relative_path(snapshot: SubingStrategyPerformanceSnapshot) -> str:
    return (
        f"snapshots/{snapshot.symbol}/"
        f"{snapshot.coverage_through.isoformat()}/"
        f"{snapshot.snapshot_sha256}.json"
    )


def _file_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_public_error(exc: BaseException) -> None:
    assert str(exc) == "SUBING_STRATEGY_CACHE_UNAVAILABLE"
    assert getattr(exc, "code") == "SUBING_STRATEGY_CACHE_UNAVAILABLE"


def _assert_same_snapshot(
    restored: SubingStrategyPerformanceSnapshot,
    original: SubingStrategyPerformanceSnapshot,
) -> None:
    assert restored.snapshot_sha256 == original.snapshot_sha256
    assert restored.identity_sha256 == original.identity_sha256
    assert restored.payload_sha256 == original.payload_sha256
    assert restored.symbol == original.symbol
    assert restored.coverage_through == original.coverage_through
    assert restored.segment_facts == original.segment_facts
    assert restored.projection.episodes == original.projection.episodes
    assert restored.projection.summary == original.projection.summary
    assert restored.projection.cache_state == "hit"


def _manifest_body(
    snapshot: SubingStrategyPerformanceSnapshot,
    *,
    snapshot_path: str | None = None,
) -> dict[str, object]:
    return {
        "generated_at": snapshot.generated_at.astimezone(UTC).isoformat(),
        "identity_sha256": snapshot.identity_sha256,
        "payload_sha256": snapshot.payload_sha256,
        "schema_version": 1,
        "snapshot_path": snapshot_path or _snapshot_relative_path(snapshot),
        "snapshot_sha256": snapshot.snapshot_sha256,
        "symbol": snapshot.symbol,
        "through": snapshot.coverage_through.isoformat(),
    }


def _write_manifest(path: Path, body: dict[str, object]) -> None:
    envelope = dict(body)
    envelope["manifest_sha256"] = sha256(_canonical_bytes(body)).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(envelope))
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)


def test_publish_writes_immutable_snapshot_before_current_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    replaced: list[str] = []
    real_replace = os.replace

    def track_replace(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        replaced.append(Path(target).relative_to(tmp_path).as_posix())
        real_replace(source, target)

    monkeypatch.setattr(f"{_STORE_MODULE}.os.replace", track_replace)

    receipt = store.publish_current(snapshot)

    assert replaced == [
        _snapshot_relative_path(snapshot),
        "current/jm.json",
    ]
    assert isinstance(receipt, SubingStrategyPerformanceSnapshotReceipt)
    assert receipt.symbol == "jm"
    assert receipt.through == date(2026, 8, 26)
    assert receipt.snapshot_path == _snapshot_relative_path(snapshot)
    assert receipt.snapshot_sha256 == snapshot.snapshot_sha256
    assert receipt.identity_sha256 == snapshot.identity_sha256
    assert receipt.payload_sha256 == snapshot.payload_sha256
    assert len(receipt.manifest_sha256) == 64
    assert receipt.generated_at == snapshot.generated_at
    snapshot_path = tmp_path / _snapshot_relative_path(snapshot)
    manifest_path = tmp_path / "current" / "jm.json"
    assert snapshot_path.is_file()
    assert manifest_path.is_file()
    assert not snapshot_path.is_symlink()
    assert not manifest_path.is_symlink()
    assert S_IMODE(snapshot_path.stat().st_mode) == 0o600
    assert S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert snapshot_path.stat().st_uid == os.getuid()
    assert manifest_path.stat().st_uid == os.getuid()
    for directory in (
        tmp_path / "snapshots",
        tmp_path / "snapshots" / "jm",
        tmp_path / "snapshots" / "jm" / "2026-08-26",
        tmp_path / "current",
    ):
        assert directory.is_dir()
        assert not directory.is_symlink()
        assert S_IMODE(directory.stat().st_mode) == 0o700
        assert directory.stat().st_uid == os.getuid()
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["schema_version"] == 1
    assert manifest["symbol"] == "jm"
    assert manifest["through"] == "2026-08-26"
    assert manifest["snapshot_path"] == _snapshot_relative_path(snapshot)
    assert manifest["snapshot_sha256"] == snapshot.snapshot_sha256
    assert manifest["identity_sha256"] == snapshot.identity_sha256
    assert manifest["payload_sha256"] == snapshot.payload_sha256
    assert manifest["generated_at"] == "2026-08-27T08:00:00+00:00"
    assert manifest["manifest_sha256"] == receipt.manifest_sha256
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert sha256(_canonical_bytes(body)).hexdigest() == receipt.manifest_sha256


def test_publish_then_read_current_uses_same_parser(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()

    store.publish_current(snapshot)
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_same_snapshot(restored, snapshot)
    encoded = (tmp_path / _snapshot_relative_path(snapshot)).read_bytes()
    assert parse_subing_strategy_performance_snapshot(encoded) == restored


def test_read_current_performs_no_write(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    store.publish_current(_snapshot())
    before = _file_tree(tmp_path)

    store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    assert _file_tree(tmp_path) == before


def test_read_current_does_not_select_by_glob_or_mtime(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    decoy_dir = tmp_path / "snapshots" / "jm" / "2026-08-27"
    decoy_dir.mkdir(parents=True)
    os.chmod(decoy_dir, 0o700)
    decoy = decoy_dir / f"{'f' * 64}.json"
    decoy.write_bytes(b'{"schema_version":3}')
    os.chmod(decoy, 0o600)
    os.utime(decoy, None)

    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    assert restored.snapshot_sha256 == snapshot.snapshot_sha256
    assert restored.coverage_through == date(2026, 8, 26)


def test_read_current_rejects_missing_current_snapshot(tmp_path: Path) -> None:
    store = _file_store(tmp_path)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.parametrize(
    "expected_through",
    [date(2026, 8, 25), date(2026, 8, 27)],
)
def test_read_current_rejects_stale_or_future_expected_through(
    tmp_path: Path,
    expected_through: date,
) -> None:
    store = _file_store(tmp_path)
    store.publish_current(_snapshot())

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=expected_through)

    _assert_public_error(exc_info.value)


def test_read_current_for_refresh_allows_older_through_and_http_read_stays_strict(
    tmp_path: Path,
) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)

    restored = store.read_current_for_refresh(
        symbol="jm",
        expected_through=date(2026, 8, 27),
    )
    assert restored.coverage_through == date(2026, 8, 26)
    assert restored.snapshot_sha256 == snapshot.snapshot_sha256

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 27))
    _assert_public_error(exc_info.value)


def test_read_current_rejects_symbol_mismatch(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    store.publish_current(_snapshot())

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="rb", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_read_current_rejects_symlink_manifest_and_snapshot(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    manifest = tmp_path / "current" / "jm.json"
    snapshot_path = tmp_path / _snapshot_relative_path(snapshot)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(manifest.read_bytes())
    os.chmod(elsewhere, 0o600)
    manifest.unlink()
    manifest.symlink_to(elsewhere)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)

    manifest.unlink()
    store.publish_current(snapshot)
    shadow = tmp_path / "shadow-snapshot.json"
    shadow.write_bytes(snapshot_path.read_bytes())
    os.chmod(shadow, 0o600)
    snapshot_path.unlink()
    snapshot_path.symlink_to(shadow)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_read_current_rejects_absolute_or_parent_snapshot_path(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    snapshot_path = tmp_path / _snapshot_relative_path(snapshot)
    manifest = tmp_path / "current" / "jm.json"
    outside = tmp_path / "escape.json"
    outside.write_bytes(snapshot_path.read_bytes())
    os.chmod(outside, 0o600)

    _write_manifest(manifest, _manifest_body(snapshot, snapshot_path=str(outside)))
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_public_error(exc_info.value)
    assert str(outside) not in str(exc_info.value)

    _write_manifest(
        manifest,
        _manifest_body(snapshot, snapshot_path="../escape.json"),
    )
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_public_error(exc_info.value)


def test_read_current_rejects_non_regular_manifest(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    store.publish_current(_snapshot())
    manifest = tmp_path / "current" / "jm.json"
    manifest.unlink()
    manifest.mkdir(mode=0o700)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_read_current_rejects_insecure_file_mode(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    os.chmod(tmp_path / _snapshot_relative_path(snapshot), 0o644)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_read_current_rejects_corrupt_or_hash_mismatched_manifest(
    tmp_path: Path,
) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    manifest = tmp_path / "current" / "jm.json"

    manifest.write_bytes(b"{")
    os.chmod(manifest, 0o600)
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_public_error(exc_info.value)

    body = _manifest_body(snapshot)
    envelope = dict(body)
    envelope["manifest_sha256"] = "0" * 64
    manifest.write_bytes(_canonical_bytes(envelope))
    os.chmod(manifest, 0o600)
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_public_error(exc_info.value)

    mismatched = _manifest_body(snapshot)
    mismatched["payload_sha256"] = "0" * 64
    _write_manifest(manifest, mismatched)
    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_public_error(exc_info.value)


def test_read_current_rejects_duplicate_manifest_keys(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    manifest = tmp_path / "current" / "jm.json"
    body = _manifest_body(snapshot)
    digest = sha256(_canonical_bytes(body)).hexdigest()
    raw = (
        b'{"generated_at":"'
        + str(body["generated_at"]).encode()
        + b'","generated_at":"'
        + str(body["generated_at"]).encode()
        + b'","identity_sha256":"'
        + str(body["identity_sha256"]).encode()
        + b'","manifest_sha256":"'
        + digest.encode()
        + b'","payload_sha256":"'
        + str(body["payload_sha256"]).encode()
        + b'","schema_version":1,"snapshot_path":"'
        + str(body["snapshot_path"]).encode()
        + b'","snapshot_sha256":"'
        + str(body["snapshot_sha256"]).encode()
        + b'","symbol":"jm","through":"2026-08-26"}'
    )
    manifest.write_bytes(raw)
    os.chmod(manifest, 0o600)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_publish_collision_requires_byte_identical_content(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    first = store.publish_current(snapshot)
    prior_manifest = (tmp_path / "current" / "jm.json").read_bytes()
    snapshot_path = tmp_path / _snapshot_relative_path(snapshot)
    snapshot_path.write_bytes(b'{"not":"the-same"}')
    os.chmod(snapshot_path, 0o600)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.publish_current(snapshot)

    _assert_public_error(exc_info.value)
    assert (tmp_path / "current" / "jm.json").read_bytes() == prior_manifest
    assert first.snapshot_sha256 == snapshot.snapshot_sha256


def test_identical_collision_is_reused_without_overwrite(tmp_path: Path) -> None:
    store = _file_store(tmp_path)
    snapshot = _snapshot()
    first = store.publish_current(snapshot)
    snapshot_path = tmp_path / _snapshot_relative_path(snapshot)
    before = snapshot_path.read_bytes()
    inode = snapshot_path.stat().st_ino

    second = store.publish_current(snapshot)

    assert second.snapshot_sha256 == first.snapshot_sha256
    assert snapshot_path.read_bytes() == before
    assert snapshot_path.stat().st_ino == inode
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_same_snapshot(restored, snapshot)


@pytest.mark.parametrize("fail_at", ["write", "fsync", "replace", "readback", "hash"])
def test_failed_snapshot_mutation_preserves_prior_manifest_and_cleans_tempfiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
) -> None:
    store = _file_store(tmp_path)
    first = _snapshot()
    store.publish_current(first)
    prior_manifest = (tmp_path / "current" / "jm.json").read_bytes()
    later = _snapshot(generated_at=datetime(2026, 8, 27, 9, tzinfo=UTC))
    real_replace = os.replace
    real_fsync = os.fsync
    real_parse = parse_subing_strategy_performance_snapshot

    if fail_at == "write":

        def fail_mkstemp(*_args: object, **_kwargs: object) -> tuple[int, str]:
            raise OSError("targeted test failure")

        monkeypatch.setattr(f"{_STORE_MODULE}.tempfile.mkstemp", fail_mkstemp)
    elif fail_at == "fsync":

        def fail_fsync(_fd: int) -> None:
            raise OSError("targeted test failure")

        monkeypatch.setattr(f"{_STORE_MODULE}.os.fsync", fail_fsync)
    elif fail_at == "replace":

        def fail_snapshot_replace(
            source: str | os.PathLike[str],
            target: str | os.PathLike[str],
        ) -> None:
            if "snapshots" in Path(target).parts:
                raise OSError("targeted test failure")
            real_replace(source, target)

        monkeypatch.setattr(f"{_STORE_MODULE}.os.replace", fail_snapshot_replace)
    elif fail_at == "readback":

        def fail_parse(
            content: bytes | str | object,
        ) -> SubingStrategyPerformanceSnapshot:
            raise SubingStrategyPerformanceSnapshotError()

        monkeypatch.setattr(
            f"{_STORE_MODULE}.parse_subing_strategy_performance_snapshot",
            fail_parse,
        )
    else:

        def mismatch_parse(
            content: bytes | str | object,
        ) -> SubingStrategyPerformanceSnapshot:
            if isinstance(content, (bytes, str)):
                parsed = real_parse(content)
                if parsed.generated_at == later.generated_at:
                    return first
                return parsed
            raise SubingStrategyPerformanceSnapshotError()

        monkeypatch.setattr(
            f"{_STORE_MODULE}.parse_subing_strategy_performance_snapshot",
            mismatch_parse,
        )

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.publish_current(later)

    _assert_public_error(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)
    assert later.snapshot_sha256 not in str(exc_info.value)
    assert (tmp_path / "current" / "jm.json").read_bytes() == prior_manifest
    assert list(tmp_path.rglob("*.tmp")) == []
    monkeypatch.setattr(
        f"{_STORE_MODULE}.parse_subing_strategy_performance_snapshot",
        real_parse,
    )
    monkeypatch.setattr(f"{_STORE_MODULE}.os.fsync", real_fsync)
    monkeypatch.setattr(f"{_STORE_MODULE}.os.replace", real_replace)
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_same_snapshot(restored, first)
    if fail_at in {"write", "fsync", "replace"}:
        assert not (tmp_path / _snapshot_relative_path(later)).exists()


def test_failed_manifest_replace_leaves_snapshot_and_preserves_prior_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _file_store(tmp_path)
    first = _snapshot()
    store.publish_current(first)
    prior_manifest = (tmp_path / "current" / "jm.json").read_bytes()
    later = _snapshot(generated_at=datetime(2026, 8, 27, 9, tzinfo=UTC))
    real_replace = os.replace

    def fail_manifest_replace(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
    ) -> None:
        if Path(target) == tmp_path / "current" / "jm.json":
            raise OSError("targeted test failure")
        real_replace(source, target)

    monkeypatch.setattr(f"{_STORE_MODULE}.os.replace", fail_manifest_replace)

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.publish_current(later)

    _assert_public_error(exc_info.value)
    assert (tmp_path / "current" / "jm.json").read_bytes() == prior_manifest
    assert (tmp_path / _snapshot_relative_path(later)).is_file()
    assert list(tmp_path.rglob("*.tmp")) == []
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))
    _assert_same_snapshot(restored, first)


def test_store_rejects_symlink_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(target, target_is_directory=True)
    store = SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
    )

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.publish_current(_snapshot())

    _assert_public_error(exc_info.value)
    assert not list(target.rglob("*.json"))


def test_store_rejects_root_validator_drift(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    store = SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: tmp_path / "other",
    )

    with pytest.raises(SubingStrategyPerformanceSnapshotError) as exc_info:
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_public_error(exc_info.value)


def test_publish_creates_namespace_below_trusted_base(tmp_path: Path) -> None:
    base = tmp_path / "observation"
    base.mkdir(mode=0o700)
    os.chmod(base, 0o700)
    root = base / "cache" / "subing-strategy-v1" / "performance"
    store = SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
        trusted_base_validator=lambda: base,
    )
    snapshot = _snapshot()

    store.publish_current(snapshot)
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_same_snapshot(restored, snapshot)
    assert S_IMODE(root.stat().st_mode) == 0o700
    assert S_IMODE((root / "current" / "jm.json").stat().st_mode) == 0o600
    assert "performance/" not in _snapshot_relative_path(snapshot)
    assert not (root / "jm").exists()


def _prefix_source() -> str:
    return "1" * 64


def _tail_source() -> str:
    return "2" * 64


def _legacy_identity():
    from app.market_data.subing_strategy.cache import (
        SubingStrategyPerformanceCacheIdentity,
    )

    projection = _projection()
    return SubingStrategyPerformanceCacheIdentity(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version="subing_strategy_15m_v1",
        engine_identity_sha256="e" * 64,
        symbol=projection.symbol,
        since=projection.coverage_since,
        through=projection.coverage_through,
        resolved_cutoff=projection.resolved_cutoff,
        segment_identity_sha256s=(_prefix_source(), _tail_source()),
    )


def _legacy_lineage():
    from app.market_data.subing_strategy.performance_lineage import (
        SubingStrategyPerformanceLineage,
        SubingStrategyPerformanceSourceSegment,
    )

    projection = _projection()
    return SubingStrategyPerformanceLineage(
        symbol=projection.symbol,
        coverage_since=projection.coverage_since,
        coverage_through=projection.coverage_through,
        ordered_segments=(
            SubingStrategyPerformanceSourceSegment(
                contract="jm2505",
                effective_start=date(2020, 1, 2),
                effective_end=date(2026, 1, 4),
                source_identity=_prefix_source(),
            ),
            SubingStrategyPerformanceSourceSegment(
                contract="jm2605",
                effective_start=date(2026, 1, 5),
                effective_end=date(2026, 8, 26),
                source_identity=_tail_source(),
            ),
        ),
        source_manifest_sha256="b" * 64,
    )


def _tail_projection():
    lineage = _legacy_lineage()
    tail = lineage.ordered_segments[-1]
    return type(
        "Tail",
        (),
        {
            "segment_summaries": (
                type(
                    "Segment",
                    (),
                    {
                        "contract": tail.contract,
                        "start_trading_day": tail.effective_start,
                        "end_trading_day": tail.effective_end,
                        "loaded_through": lineage.coverage_through,
                        "bar_count_1m": 500,
                        "bar_count_5m": 100,
                        "bar_count_15m": 12,
                        "source_identity_sha256": tail.source_identity,
                    },
                )(),
            ),
            "context_unavailable": (object(),),
            "engine_identity_sha256": "e" * 64,
        },
    )()


class _LineageResolver:
    def __init__(self, lineage) -> None:
        self.lineage = lineage

    def resolve(self, symbol: str, *, through: date | None = None):
        assert symbol == self.lineage.symbol
        assert through == self.lineage.coverage_through
        return self.lineage


class _Historical:
    def __init__(self, tail) -> None:
        self.tail = tail
        self.calls: list[tuple[object, bool]] = []

    def history(self, request, *, publish_cache: bool = False):
        self.calls.append((request, publish_cache))
        return self.tail


class _RecordingStore:
    def __init__(self, inner: SubingStrategyPerformanceFileSnapshotStore) -> None:
        self.inner = inner
        self.published: list[object] = []

    def publish_current(self, snapshot):
        self.published.append(snapshot)
        return self.inner.publish_current(snapshot)

    def read_current(
        self,
        *,
        symbol: str,
        expected_through: date,
    ):
        return self.inner.read_current(
            symbol=symbol,
            expected_through=expected_through,
        )

    def read_current_for_refresh(
        self,
        *,
        symbol: str,
        expected_through: date,
    ):
        return self.inner.read_current_for_refresh(
            symbol=symbol,
            expected_through=expected_through,
        )


def _legacy_payload(*, include_intraday_totals: bool = True) -> dict[str, object]:
    from app.market_data.subing_strategy.performance import (
        _performance_snapshot_payload,
    )

    payload = _performance_snapshot_payload(_projection())
    if include_intraday_totals:
        payload["bar_count_1m"] = 1500
        payload["bar_count_5m"] = 300
    return payload


def _adopter(
    tmp_path: Path,
    *,
    historical=None,
    lineage=None,
    payload: dict[str, object] | None = None,
    identity=None,
    engine_identity_sha256: str | None = None,
):
    from app.market_data.subing_strategy.cache import SubingStrategyPerformanceCache
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceAdopter,
    )

    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True)
    store_root = cache_root / "performance"
    cache = SubingStrategyPerformanceCache(
        cache_root,
        root_validator=lambda: cache_root,
        now=lambda: datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    inner_store = SubingStrategyPerformanceFileSnapshotStore(
        store_root,
        root_validator=lambda: store_root,
        trusted_base_validator=lambda: cache_root,
    )
    store = _RecordingStore(inner_store)
    published_identity = identity or _legacy_identity()
    cache.publish(
        published_identity, payload if payload is not None else _legacy_payload()
    )
    hist = historical or _Historical(_tail_projection())
    return (
        SubingStrategyPerformanceAdopter(
            cache=cache,
            store=store,
            lineage=lineage or _LineageResolver(_legacy_lineage()),
            historical=hist,
            now=lambda: datetime(2026, 8, 27, 9, tzinfo=UTC),
            engine_identity_sha256=engine_identity_sha256
            or published_identity.engine_identity_sha256,
        ),
        cache,
        store,
        hist,
    )


def _assert_rebuild(exc: BaseException) -> None:
    assert str(exc) == "SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED"
    assert getattr(exc, "code") == "SUBING_STRATEGY_PERFORMANCE_FULL_REBUILD_REQUIRED"


def test_adoption_publishes_schema_v3_and_leaves_legacy_bytes_unchanged(
    tmp_path: Path,
) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceAdopter,
    )
    from app.market_data.subing_strategy.service import SubingStrategyHistoricalRequest

    adopter, cache, store, historical = _adopter(tmp_path)
    identity = _legacy_identity()
    legacy_path = cache.path_for(identity)
    before = legacy_path.read_bytes()
    lineage = _legacy_lineage()

    snapshot = adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    assert isinstance(adopter, SubingStrategyPerformanceAdopter)
    assert legacy_path.read_bytes() == before
    assert snapshot.immutable_prefix_segment_count == 1
    prefix = snapshot.immutable_prefix_counts
    tail = snapshot.segment_facts[0]
    assert prefix.bar_count_1m == 1000
    assert prefix.bar_count_5m == 200
    assert prefix.bar_count_15m == 12
    assert prefix.context_unavailable_count == 0
    assert prefix.bar_count_1m + tail.bar_count_1m == 1500
    assert prefix.bar_count_5m + tail.bar_count_5m == 300
    assert (
        prefix.bar_count_15m + tail.bar_count_15m == snapshot.projection.bar_count_15m
    )
    assert (
        prefix.context_unavailable_count + tail.context_unavailable_count
        == snapshot.projection.context_unavailable_count
    )
    assert snapshot.segment_facts[0].source_identity == _tail_source()
    assert historical.calls == [
        (
            SubingStrategyHistoricalRequest(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol="jm",
                frequency=BarFrequency.M15,
                since=lineage.ordered_segments[-1].effective_start,
                through=date(2026, 8, 26),
            ),
            True,
        )
    ]
    _assert_same_snapshot(restored, snapshot)


def test_adoption_rejects_temporary_or_multiple_candidates(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    adopter, cache, _store, _hist = _adopter(tmp_path)
    directory = cache.directory_for(symbol="jm", through=date(2026, 8, 26))
    (directory / ".partial.json.tmp").write_text("{}", encoding="utf-8")

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(exc_info.value)

    (directory / ".partial.json.tmp").unlink()
    (directory / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as extra:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(extra.value)


def test_adoption_rejects_symlink_and_segment_mismatch(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )
    from app.market_data.subing_strategy.performance_lineage import (
        SubingStrategyPerformanceSourceSegment,
    )

    adopter, cache, _store, _hist = _adopter(tmp_path)
    identity = _legacy_identity()
    legacy_path = cache.path_for(identity)
    sibling = legacy_path.with_name("link.json")
    sibling.symlink_to(legacy_path)
    legacy_path.unlink()
    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as linked:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(linked.value)

    sibling.unlink()
    cache.publish(identity, _projection_payload())
    original = _legacy_lineage()
    drifted = replace(
        original,
        ordered_segments=(
            original.ordered_segments[1],
            SubingStrategyPerformanceSourceSegment(
                contract="jm2505",
                effective_start=date(2020, 1, 2),
                effective_end=date(2026, 1, 4),
                source_identity=_prefix_source(),
            ),
        ),
    )
    adopter, _cache, _store, _hist = _adopter(
        tmp_path / "drift",
        lineage=_LineageResolver(drifted),
    )
    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as mismatch:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(mismatch.value)


def _projection_payload():
    return _legacy_payload()


def _assert_no_current(store) -> None:
    from app.market_data.subing_strategy.performance_snapshot import (
        SubingStrategyPerformanceSnapshotError,
    )

    assert store.published == []
    with pytest.raises(SubingStrategyPerformanceSnapshotError):
        store.read_current(symbol="jm", expected_through=date(2026, 8, 26))


def _tamper_legacy_envelope(path: Path, mutator) -> None:
    from app.market_data.subing_strategy.cache import _canonical_bytes

    envelope = json.loads(path.read_bytes())
    mutator(envelope)
    path.write_bytes(_canonical_bytes(envelope))
    os.chmod(path, 0o600)


def test_adoption_rejects_missing_1m_5m_full_totals(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    adopter, _cache, store, _hist = _adopter(
        tmp_path,
        payload=_legacy_payload(include_intraday_totals=False),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))

    _assert_rebuild(exc_info.value)
    _assert_no_current(store)


def test_adoption_rejects_different_engine_identity(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    adopter, _cache, store, _hist = _adopter(
        tmp_path,
        engine_identity_sha256="f" * 64,
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))

    _assert_rebuild(exc_info.value)
    _assert_no_current(store)


@pytest.mark.parametrize(
    "field",
    ("identity_sha256", "payload_sha256", "snapshot_sha256"),
)
def test_adoption_rejects_wrong_hashes(tmp_path: Path, field: str) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    adopter, cache, store, _hist = _adopter(tmp_path)
    path = cache.path_for(_legacy_identity())
    _tamper_legacy_envelope(path, lambda envelope: envelope.update({field: "a" * 64}))

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))

    _assert_rebuild(exc_info.value)
    _assert_no_current(store)


def test_adoption_rejects_wrong_identities(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.cache import (
        SubingStrategyPerformanceCacheIdentity,
    )
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    wrong_strategy = replace(_legacy_identity(), strategy_id="other_strategy")
    adopter, _cache, store, _hist = _adopter(tmp_path, identity=wrong_strategy)

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(exc_info.value)
    _assert_no_current(store)

    wrong_engine = replace(
        _legacy_identity(),
        engine_identity_sha256="d" * 64,
    )
    assert isinstance(wrong_engine, SubingStrategyPerformanceCacheIdentity)
    adopter, _cache, store, _hist = _adopter(
        tmp_path / "engine",
        identity=wrong_engine,
        engine_identity_sha256="e" * 64,
    )
    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as engine:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))
    _assert_rebuild(engine.value)
    _assert_no_current(store)


def test_adoption_rejects_bad_payload(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    adopter, _cache, store, _hist = _adopter(
        tmp_path,
        payload={"broken": True},
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))

    _assert_rebuild(exc_info.value)
    _assert_no_current(store)


def test_adoption_rejects_missing_segments(tmp_path: Path) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceFullRebuildRequired,
    )

    original = _legacy_lineage()
    missing = replace(original, ordered_segments=(original.ordered_segments[-1],))
    adopter, _cache, store, _hist = _adopter(
        tmp_path,
        lineage=_LineageResolver(missing),
    )

    with pytest.raises(SubingStrategyPerformanceFullRebuildRequired) as exc_info:
        adopter.adopt(symbol="jm", through=date(2026, 8, 26))

    _assert_rebuild(exc_info.value)
    _assert_no_current(store)


def test_read_current_never_invokes_adopter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.market_data.subing_strategy.performance_adoption import (
        SubingStrategyPerformanceAdopter,
    )
    from app.market_data.subing_strategy.performance_snapshot import (
        encode_subing_strategy_performance_snapshot,
        parse_subing_strategy_performance_snapshot,
    )

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("adopter must not run on the store read path")

    monkeypatch.setattr(SubingStrategyPerformanceAdopter, "adopt", forbid)
    monkeypatch.setattr(SubingStrategyPerformanceAdopter, "__init__", forbid)

    store = _file_store(tmp_path)
    snapshot = _snapshot()
    store.publish_current(snapshot)
    restored = store.read_current(symbol="jm", expected_through=date(2026, 8, 26))

    _assert_same_snapshot(restored, snapshot)
    parsed = parse_subing_strategy_performance_snapshot(
        encode_subing_strategy_performance_snapshot(snapshot)
    )
    _assert_same_snapshot(parsed, snapshot)
