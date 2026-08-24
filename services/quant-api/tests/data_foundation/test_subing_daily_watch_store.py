from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchItem,
    SubingDailyWatchSnapshot,
)
from app.market_data.subing_daily_watch_store import (
    SUBING_OBSERVATION_ROOT_ENV,
    SubingDailyWatchStore,
    SubingDailyWatchStoreError,
    resolve_subing_observation_root,
)
from app.market_data.subing_ema_trend import PriceSide, SubingEmaTrendSnapshot


_SOURCE_DAY = date(2026, 8, 21)
_TARGET_DAY = date(2026, 8, 24)
_GENERATED_AT = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)


class _FakeMountInspector:
    def __init__(
        self,
        *,
        mounted: bool = True,
        symlinks: tuple[Path, ...] = (),
    ) -> None:
        self.mounted = mounted
        self.symlinks = frozenset(symlinks)
        self.mount_checks: list[Path] = []
        self.symlink_checks: list[Path] = []

    def is_mount(self, path: Path) -> bool:
        self.mount_checks.append(path)
        return self.mounted

    def is_symlink(self, path: Path) -> bool:
        self.symlink_checks.append(path)
        return path in self.symlinks


@pytest.mark.parametrize(
    ("environ", "expected_code"),
    [
        ({}, "OBSERVATION_ROOT_UNCONFIGURED"),
        ({SUBING_OBSERVATION_ROOT_ENV: ""}, "OBSERVATION_ROOT_UNCONFIGURED"),
        (
            {SUBING_OBSERVATION_ROOT_ENV: "relative/subing-daily-v1"},
            "OBSERVATION_ROOT_UNAVAILABLE",
        ),
        (
            {SUBING_OBSERVATION_ROOT_ENV: "/Users/test/subing-daily-v1"},
            "OBSERVATION_ROOT_UNAVAILABLE",
        ),
    ],
)
def test_root_policy_rejects_unconfigured_or_non_extension_paths_without_mount_io(
    environ: Mapping[str, str],
    expected_code: str,
) -> None:
    """Catches a missing or system-disk root silently receiving a fallback."""
    inspector = _FakeMountInspector()

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        resolve_subing_observation_root(environ=environ, inspector=inspector)

    assert raised.value.code == expected_code
    assert inspector.mount_checks == []
    assert inspector.symlink_checks == []


def test_root_policy_rejects_an_unmounted_volume_before_parent_inspection() -> None:
    """Catches feature-path inspection or creation before mount validation."""
    configured = Path("/Volumes/Fake/observations/subing-daily-v1")
    inspector = _FakeMountInspector(mounted=False)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        resolve_subing_observation_root(
            environ={SUBING_OBSERVATION_ROOT_ENV: str(configured)},
            inspector=inspector,
        )

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert inspector.mount_checks == [Path("/Volumes/Fake")]
    assert inspector.symlink_checks == []


@pytest.mark.parametrize(
    "symlink",
    [
        Path("/Volumes/Fake"),
        Path("/Volumes/Fake/observations"),
    ],
)
def test_root_policy_rejects_symlinked_volume_or_parent(symlink: Path) -> None:
    """Catches a mounted root escaping through a symlinked path component."""
    configured = Path("/Volumes/Fake/observations/subing-daily-v1")
    inspector = _FakeMountInspector(symlinks=(symlink,))

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        resolve_subing_observation_root(
            environ={SUBING_OBSERVATION_ROOT_ENV: str(configured)},
            inspector=inspector,
        )

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert inspector.mount_checks == [Path("/Volumes/Fake")]
    assert symlink in inspector.symlink_checks


def test_root_policy_returns_validated_path_without_creating_it() -> None:
    """Catches production resolution creating the feature directory as a side effect."""
    configured = Path("/Volumes/Fake/observations/subing-daily-v1")
    inspector = _FakeMountInspector()

    resolved = resolve_subing_observation_root(
        environ={SUBING_OBSERVATION_ROOT_ENV: str(configured)},
        inspector=inspector,
    )

    assert resolved == configured
    assert inspector.mount_checks == [Path("/Volumes/Fake")]
    assert inspector.symlink_checks == [
        Path("/Volumes/Fake"),
        Path("/Volumes/Fake/observations"),
        configured,
    ]


def _trend(
    timeframe: BarFrequency,
    *,
    contract: str,
    close: str,
    ema21: str,
    price_side: PriceSide,
    slope_5: str,
    slope_10: str,
) -> SubingEmaTrendSnapshot:
    return SubingEmaTrendSnapshot(
        timeframe=timeframe,
        bar_end=datetime(2026, 8, 21, 7, tzinfo=UTC),
        trading_day=_SOURCE_DAY,
        contract=contract,
        segment_start_trading_day=date(2026, 7, 1),
        close=Decimal(close),
        ema21=Decimal(ema21),
        price_side=price_side,
        slope_5_raw=Decimal(slope_5),
        slope_10_raw=Decimal(slope_10),
        slope_5_bps_per_bar=Decimal(slope_5) / Decimal("10"),
        slope_10_bps_per_bar=Decimal(slope_10) / Decimal("10"),
    )


def _snapshot(
    *,
    target: date = _TARGET_DAY,
    generated_at: datetime = _GENERATED_AT,
) -> SubingDailyWatchSnapshot:
    return SubingDailyWatchSnapshot(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=target,
        generated_at=generated_at,
        items=(
            SubingDailyWatchItem(
                symbol="a",
                product_name="豆一",
                sector="农产品",
                decision=SubingDailyWatchDecision.LONG_WATCH,
                reason_codes=("D1_H1_LONG_ALIGNED",),
                daily=_trend(
                    BarFrequency.D1,
                    contract="A2609",
                    close="102.50",
                    ema21="100.25",
                    price_side=PriceSide.ABOVE,
                    slope_5="1.20",
                    slope_10="2.40",
                ),
                hourly=_trend(
                    BarFrequency.H1,
                    contract="A2609",
                    close="102.50",
                    ema21="101.25",
                    price_side=PriceSide.ABOVE,
                    slope_5="0.80",
                    slope_10="1.60",
                ),
                unavailable_reasons=(),
            ),
            SubingDailyWatchItem(
                symbol="b",
                product_name="豆二",
                sector="农产品",
                decision=SubingDailyWatchDecision.UNAVAILABLE,
                reason_codes=(),
                daily=None,
                hourly=None,
                unavailable_reasons=("DOMINANT_SEGMENT_UNAVAILABLE",),
            ),
        ),
    )


def test_publish_writes_canonical_snapshot_current_and_status(tmp_path: Path) -> None:
    """Catches incomplete publication or lossy/noncanonical Decimal serialization."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()

    result = store.publish(snapshot)

    history = tmp_path / "history" / "2026-08-24.json"
    current = tmp_path / "current.json"
    status_path = tmp_path / "generation-status.json"
    assert result.status == "published"
    assert result.target_trading_day == _TARGET_DAY
    assert history.read_bytes() == current.read_bytes()
    assert current.read_bytes().endswith(b"\n")
    assert not current.read_bytes().endswith(b"\n\n")

    payload = json.loads(current.read_bytes())
    assert payload["schema_version"] == 1
    assert payload["projection_version"] == "subing_daily_watch_v1"
    assert payload["formula_version"] == "subing_ema21_trend_v1"
    assert payload["series_kind"] == "actual_dominant"
    assert payload["frequencies"] == ["1d", "60m"]
    assert payload["ema_period"] == 21
    assert payload["slope_windows"] == [5, 10]
    assert payload["counts"] == {
        "universe": 2,
        "long_watch": 1,
        "short_watch": 0,
        "excluded": 0,
        "unavailable": 1,
    }
    daily = payload["items"][0]["daily"]
    assert daily == {
        "bar_end": "2026-08-21T07:00:00+00:00",
        "close": "102.50",
        "ema21": "100.25",
        "physical_contract": "A2609",
        "price_side": "above",
        "segment_start_trading_day": "2026-07-01",
        "slope_10_bps_per_bar": "0.24",
        "slope_10_raw": "2.40",
        "slope_5_bps_per_bar": "0.12",
        "slope_5_raw": "1.20",
        "trading_day": "2026-08-21",
    }
    assert store.read_current() == snapshot
    assert store.read_generation_status() == json.loads(status_path.read_bytes())
    assert store.read_generation_status() == {
        "last_run": {
            "error_code": None,
            "finished_at": "2026-08-21T18:30:00+00:00",
            "source_trading_day": "2026-08-21",
            "started_at": "2026-08-21T18:30:00+00:00",
            "status": "passed",
            "target_trading_day": "2026-08-24",
        },
        "last_successful_target_trading_day": "2026-08-24",
        "projection_version": "subing_daily_watch_v1",
        "schema_version": 1,
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"
    assert current.read_bytes() == canonical


def test_publish_sets_private_modes_where_supported(tmp_path: Path) -> None:
    """Catches observation artifacts becoming group/world-readable."""
    store = SubingDailyWatchStore(tmp_path)

    store.publish(_snapshot())

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "history").stat().st_mode) == 0o700
    for artifact in (
        tmp_path / "history" / "2026-08-24.json",
        tmp_path / "current.json",
        tmp_path / "generation-status.json",
    ):
        assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


def test_publish_expands_decimal_exponents_to_plain_strings(tmp_path: Path) -> None:
    """Catches scientific notation leaking into the persisted Decimal contract."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    first = snapshot.items[0]
    assert first.daily is not None
    exponential = replace(
        snapshot,
        items=(
            replace(first, daily=replace(first.daily, close=Decimal("1E+2"))),
            snapshot.items[1],
        ),
    )

    store.publish(exponential)

    payload = json.loads((tmp_path / "current.json").read_bytes())
    assert payload["items"][0]["daily"]["close"] == "100"
    assert store.read_current() == exponential


def test_same_canonical_snapshot_is_idempotent(tmp_path: Path) -> None:
    """Catches a retry rewriting immutable history or reporting a new publish."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot)
    history = tmp_path / "history" / "2026-08-24.json"
    original_stat = history.stat()

    result = store.publish(snapshot)

    assert result.status == "idempotent"
    assert history.stat().st_ino == original_stat.st_ino
    assert history.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert store.read_current() == snapshot


def test_same_target_with_different_canonical_bytes_fails_closed(
    tmp_path: Path,
) -> None:
    """Catches an immutable target being overwritten by a conflicting generation."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot)
    history = tmp_path / "history" / "2026-08-24.json"
    current = tmp_path / "current.json"
    original_history = history.read_bytes()
    original_current = current.read_bytes()
    conflict = replace(
        snapshot,
        generated_at=snapshot.generated_at + timedelta(seconds=1),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(conflict)

    assert raised.value.code == "SNAPSHOT_IDENTITY_CONFLICT"
    assert history.read_bytes() == original_history
    assert current.read_bytes() == original_current


def test_same_target_conflict_in_current_fails_before_recreating_missing_history(
    tmp_path: Path,
) -> None:
    """Catches a same-day current conflict being normalized by an overwrite."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot)
    history = tmp_path / "history" / "2026-08-24.json"
    history.unlink()
    original_current = (tmp_path / "current.json").read_bytes()
    conflict = replace(
        snapshot,
        generated_at=snapshot.generated_at + timedelta(seconds=1),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(conflict)

    assert raised.value.code == "SNAPSHOT_IDENTITY_CONFLICT"
    assert not history.exists()
    assert (tmp_path / "current.json").read_bytes() == original_current


def test_target_older_than_current_fails_before_creating_history(tmp_path: Path) -> None:
    """Catches a delayed generation moving current backward or adding stale history."""
    store = SubingDailyWatchStore(tmp_path)
    newer = _snapshot(target=date(2026, 8, 25))
    store.publish(newer)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(target=date(2026, 8, 24)))

    assert raised.value.code == "CURRENT_TARGET_REGRESSION"
    assert not (tmp_path / "history" / "2026-08-24.json").exists()
    assert store.read_current() == newer


@pytest.mark.parametrize("artifact", ["current.json", "history/2026-08-24.json"])
def test_invalid_existing_snapshot_fails_closed(
    tmp_path: Path,
    artifact: str,
) -> None:
    """Catches malformed current/history being treated as absent or replaceable."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot())
    invalid = tmp_path / artifact
    invalid.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot())

    assert raised.value.code == "SNAPSHOT_INVALID"
    assert invalid.read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(schema_version=True),
        lambda payload: payload.update(projection_version="other"),
        lambda payload: payload.update(formula_version="other"),
        lambda payload: payload["items"].reverse(),
        lambda payload: payload["items"].__setitem__(
            1, {**payload["items"][1], "symbol": "a"}
        ),
        lambda payload: payload["counts"].update(universe=3),
        lambda payload: payload["counts"].update(unavailable=True),
    ],
)
def test_read_current_strictly_rejects_contract_drift(
    tmp_path: Path,
    mutate: object,
) -> None:
    """Catches version, order, identity, or count drift entering the read path."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot())
    current = tmp_path / "current.json"
    payload = json.loads(current.read_bytes())
    assert callable(mutate)
    mutate(payload)
    current.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.read_current()

    assert raised.value.code == "SNAPSHOT_INVALID"


def test_record_failure_preserves_last_success_without_touching_snapshot_files(
    tmp_path: Path,
) -> None:
    """Catches a failed run erasing the last successful identity or current data."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot)
    current = tmp_path / "current.json"
    history = tmp_path / "history" / "2026-08-24.json"
    original_current = current.read_bytes()
    original_history = history.read_bytes()

    store.record_failure(
        source_trading_day=date(2026, 8, 22),
        target_trading_day=date(2026, 8, 25),
        started_at=datetime(2026, 8, 22, 18, 20, tzinfo=UTC),
        finished_at=datetime(2026, 8, 22, 18, 21, tzinfo=UTC),
        error_code="NEXT_TRADING_DAY_UNAVAILABLE",
    )

    assert store.read_generation_status() == {
        "last_run": {
            "error_code": "NEXT_TRADING_DAY_UNAVAILABLE",
            "finished_at": "2026-08-22T18:21:00+00:00",
            "source_trading_day": "2026-08-22",
            "started_at": "2026-08-22T18:20:00+00:00",
            "status": "failed",
            "target_trading_day": "2026-08-25",
        },
        "last_successful_target_trading_day": "2026-08-24",
        "projection_version": "subing_daily_watch_v1",
        "schema_version": 1,
    }
    assert current.read_bytes() == original_current
    assert history.read_bytes() == original_history


def test_atomic_replace_failure_preserves_last_valid_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a failed current replace destroying the last readable generation."""
    store = SubingDailyWatchStore(tmp_path)
    first = _snapshot()
    store.publish(first)
    current = tmp_path / "current.json"
    status_path = tmp_path / "generation-status.json"
    original_current = current.read_bytes()
    original_status = status_path.read_bytes()
    real_replace = os.replace

    def fail_current_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == current:
            raise OSError("targeted test failure")
        real_replace(source, target)

    monkeypatch.setattr(
        "app.market_data.subing_daily_watch_store.os.replace",
        fail_current_replace,
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(target=date(2026, 8, 25)))

    assert raised.value.code == "OBSERVATION_ATOMIC_WRITE_FAILED"
    assert current.read_bytes() == original_current
    assert status_path.read_bytes() == original_status
    assert (tmp_path / "history" / "2026-08-25.json").exists()
    assert list(tmp_path.rglob("*.tmp")) == []
