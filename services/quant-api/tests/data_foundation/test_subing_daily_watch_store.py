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
    PathMountInspector,
    SubingDailyWatchStore,
    SubingDailyWatchStoreError,
    resolve_subing_observation_root,
)
from app.market_data.subing_ema_trend import PriceSide, SubingEmaTrendSnapshot


_SOURCE_DAY = date(2026, 8, 21)
_TARGET_DAY = date(2026, 8, 24)
_GENERATED_AT = datetime(2026, 8, 21, 18, 30, tzinfo=UTC)
_STARTED_AT = datetime(2026, 8, 21, 18, 25, tzinfo=UTC)


class _FakeMountInspector:
    def __init__(
        self,
        *,
        mounted: bool = True,
        symlinks: tuple[Path, ...] = (),
        missing: tuple[Path, ...] = (),
        non_directories: tuple[Path, ...] = (),
        unwritable: tuple[Path, ...] = (),
        unsearchable: tuple[Path, ...] = (),
    ) -> None:
        self.mounted = mounted
        self.symlinks = frozenset(symlinks)
        self.missing = frozenset(missing)
        self.non_directories = frozenset(non_directories)
        self.unwritable = frozenset(unwritable)
        self.unsearchable = frozenset(unsearchable)
        self.mount_checks: list[Path] = []
        self.symlink_checks: list[Path] = []
        self.exists_checks: list[Path] = []
        self.directory_checks: list[Path] = []
        self.writable_checks: list[Path] = []

    def is_mount(self, path: Path) -> bool:
        self.mount_checks.append(path)
        return self.mounted

    def is_symlink(self, path: Path) -> bool:
        self.symlink_checks.append(path)
        return path in self.symlinks

    def exists(self, path: Path) -> bool:
        self.exists_checks.append(path)
        return path not in self.missing

    def is_dir(self, path: Path) -> bool:
        self.directory_checks.append(path)
        return path not in self.non_directories

    def is_writable(self, path: Path) -> bool:
        self.writable_checks.append(path)
        return path not in self.unwritable and path not in self.unsearchable


def test_path_mount_inspector_requires_write_and_search_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches a write-only directory being treated as usable for child entries."""
    observed_modes: list[int] = []

    def access(_path: Path, mode: int) -> bool:
        observed_modes.append(mode)
        return mode == os.W_OK | os.X_OK

    monkeypatch.setattr("app.market_data.subing_daily_watch_store.os.access", access)

    assert PathMountInspector().is_writable(tmp_path)
    assert observed_modes == [os.W_OK | os.X_OK]


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
    inspector = _FakeMountInspector(missing=(configured,))

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
    assert inspector.exists_checks == [configured, configured.parent]
    assert inspector.directory_checks == [configured.parent]
    assert inspector.writable_checks == [configured.parent]


@pytest.mark.parametrize(
    "inspector",
    [
        _FakeMountInspector(
            non_directories=(
                Path("/Volumes/Fake/observations/subing-daily-v1"),
            )
        ),
        _FakeMountInspector(
            unwritable=(Path("/Volumes/Fake/observations/subing-daily-v1"),)
        ),
        _FakeMountInspector(
            missing=(Path("/Volumes/Fake/observations/subing-daily-v1"),),
            unwritable=(Path("/Volumes/Fake/observations"),),
        ),
        _FakeMountInspector(
            unsearchable=(Path("/Volumes/Fake/observations/subing-daily-v1"),)
        ),
        _FakeMountInspector(
            missing=(Path("/Volumes/Fake/observations/subing-daily-v1"),),
            unsearchable=(Path("/Volumes/Fake/observations"),),
        ),
    ],
    ids=(
        "root-is-file",
        "root-is-readonly",
        "nearest-parent-is-readonly",
        "root-is-unsearchable",
        "nearest-parent-is-unsearchable",
    ),
)
def test_root_policy_rejects_non_directory_or_unwritable_target(
    inspector: _FakeMountInspector,
) -> None:
    """Catches an unusable configured root surviving until generation or write."""
    configured = Path("/Volumes/Fake/observations/subing-daily-v1")

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        resolve_subing_observation_root(
            environ={SUBING_OBSERVATION_ROOT_ENV: str(configured)},
            inspector=inspector,
        )

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"


def test_publish_revalidates_production_root_before_creating_directories(
    tmp_path: Path,
) -> None:
    """Catches a volume disappearing between composition and publication."""
    root = tmp_path / "must-not-be-created"

    def reject_unmounted_root() -> Path:
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")

    store = SubingDailyWatchStore(root, root_validator=reject_unmounted_root)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert not root.exists()


@pytest.mark.parametrize("fail_on_check", [2, 3])
def test_publish_revalidates_root_at_each_mutation_boundary(
    tmp_path: Path,
    fail_on_check: int,
) -> None:
    """Catches mount loss after publish starts but before directories or files."""
    root = tmp_path / "must-not-receive-artifacts"
    checks = 0

    def root_until_unmounted() -> Path:
        nonlocal checks
        checks += 1
        if checks == fail_on_check:
            raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
        return root

    store = SubingDailyWatchStore(root, root_validator=root_until_unmounted)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    if root.exists():
        assert list(root.rglob("*.json")) == []


def test_atomic_write_revalidates_root_before_replace(tmp_path: Path) -> None:
    """Catches mount loss after temp fsync but before final pathname replace."""
    root = tmp_path / "must-not-publish-artifacts"

    def reject_after_temp_creation() -> Path:
        if root.exists() and tuple(root.rglob(".*.tmp")):
            raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
        return root

    store = SubingDailyWatchStore(root, root_validator=reject_after_temp_creation)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert list(root.rglob("*.json")) == []
    assert list(root.rglob("*.tmp")) == []


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

    result = store.publish(snapshot, started_at=_STARTED_AT)

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
            "started_at": "2026-08-21T18:25:00+00:00",
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


def test_store_round_trips_non_alphabetical_active_order(tmp_path: Path) -> None:
    """Catches the store replacing active_products order with alphabetic order."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = replace(_snapshot(), items=tuple(reversed(_snapshot().items)))

    store.publish(snapshot, started_at=_STARTED_AT)

    assert store.read_current() == snapshot
    assert tuple(item.symbol for item in store.read_current().items) == ("b", "a")


def test_publish_sets_private_modes_where_supported(tmp_path: Path) -> None:
    """Catches observation artifacts becoming group/world-readable."""
    store = SubingDailyWatchStore(tmp_path)

    store.publish(_snapshot(), started_at=_STARTED_AT)

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
            replace(
                first,
                daily=replace(first.daily, close=Decimal("1.025E+2")),
            ),
            snapshot.items[1],
        ),
    )

    store.publish(exponential, started_at=_STARTED_AT)

    payload = json.loads((tmp_path / "current.json").read_bytes())
    assert payload["items"][0]["daily"]["close"] == "102.5"
    assert store.read_current() == exponential


def test_same_canonical_snapshot_is_idempotent(tmp_path: Path) -> None:
    """Catches a retry rewriting immutable history or reporting a new publish."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot, started_at=_STARTED_AT)
    history = tmp_path / "history" / "2026-08-24.json"
    original_stat = history.stat()

    result = store.publish(snapshot, started_at=_STARTED_AT)

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
    store.publish(snapshot, started_at=_STARTED_AT)
    history = tmp_path / "history" / "2026-08-24.json"
    current = tmp_path / "current.json"
    original_history = history.read_bytes()
    original_current = current.read_bytes()
    conflict = replace(
        snapshot,
        generated_at=snapshot.generated_at + timedelta(seconds=1),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(conflict, started_at=_STARTED_AT)

    assert raised.value.code == "SNAPSHOT_IDENTITY_CONFLICT"
    assert history.read_bytes() == original_history
    assert current.read_bytes() == original_current


def test_same_target_conflict_in_current_fails_before_recreating_missing_history(
    tmp_path: Path,
) -> None:
    """Catches a same-day current conflict being normalized by an overwrite."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot, started_at=_STARTED_AT)
    history = tmp_path / "history" / "2026-08-24.json"
    history.unlink()
    original_current = (tmp_path / "current.json").read_bytes()
    conflict = replace(
        snapshot,
        generated_at=snapshot.generated_at + timedelta(seconds=1),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(conflict, started_at=_STARTED_AT)

    assert raised.value.code == "SNAPSHOT_IDENTITY_CONFLICT"
    assert not history.exists()
    assert (tmp_path / "current.json").read_bytes() == original_current


def test_target_older_than_current_fails_before_creating_history(tmp_path: Path) -> None:
    """Catches a delayed generation moving current backward or adding stale history."""
    store = SubingDailyWatchStore(tmp_path)
    newer = _snapshot(target=date(2026, 8, 25))
    store.publish(newer, started_at=_STARTED_AT)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(
            _snapshot(target=date(2026, 8, 24)),
            started_at=_STARTED_AT,
        )

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
    store.publish(_snapshot(), started_at=_STARTED_AT)
    invalid = tmp_path / artifact
    invalid.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "SNAPSHOT_INVALID"
    assert invalid.read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(schema_version=True),
        lambda payload: payload.update(projection_version="other"),
        lambda payload: payload.update(formula_version="other"),
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
    """Catches version, identity, or count drift entering the read path."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: (
            payload["items"][0].update(
                decision="short_watch",
                reason_codes=["D1_H1_SHORT_ALIGNED"],
            ),
            payload["counts"].update(long_watch=0, short_watch=1),
        ),
        lambda payload: (
            payload["items"][0].update(
                decision="excluded",
                reason_codes=["D1_TREND_NEUTRAL"],
            ),
            payload["items"][0]["daily"].update(price_side="below"),
            payload["counts"].update(long_watch=0, excluded=1),
        ),
        lambda payload: payload["items"][1].update(
            unavailable_reasons=["UNKNOWN_UNAVAILABLE_REASON"]
        ),
        lambda payload: (
            payload["items"][0].update(
                decision="unavailable",
                reason_codes=[],
                hourly=None,
                unavailable_reasons=["D1_HISTORY_INSUFFICIENT"],
            ),
            payload["counts"].update(long_watch=0, unavailable=2),
        ),
    ],
    ids=(
        "decision-disagrees-with-trends",
        "price-side-disagrees-with-close",
        "unavailable-reason-not-allowlisted",
        "unavailable-reason-disagrees-with-present-fact",
    ),
)
def test_read_current_rejects_semantically_inconsistent_items(
    tmp_path: Path,
    mutate: object,
) -> None:
    """Catches canonical JSON whose decision or reasons contradict its facts."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
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


@pytest.mark.parametrize(
    ("artifact", "mutate"),
    [
        (
            "current.json",
            lambda payload: payload.update(generated_at="2026-08-21T18:30:00Z"),
        ),
        (
            "current.json",
            lambda payload: payload["items"][0]["daily"].update(
                bar_end="2026-08-21T07:00:00Z"
            ),
        ),
        (
            "generation-status.json",
            lambda payload: payload["last_run"].update(
                started_at="2026-08-21T18:25:00Z"
            ),
        ),
    ],
    ids=("generated-at-z", "bar-end-z", "status-started-at-z"),
)
def test_read_current_rejects_alternate_datetime_spelling(
    tmp_path: Path,
    artifact: str,
    mutate: object,
) -> None:
    """Catches an alternate ISO spelling decoding as a canonical snapshot."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
    path = tmp_path / artifact
    payload = json.loads(path.read_bytes())
    assert callable(mutate)
    mutate(payload)
    path.write_text(
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
    store.publish(snapshot, started_at=_STARTED_AT)
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


def test_same_target_failure_invalidates_current_projection(tmp_path: Path) -> None:
    """Catches a conflicting run exposing the preserved same-target current."""
    store = SubingDailyWatchStore(tmp_path)
    snapshot = _snapshot()
    store.publish(snapshot, started_at=_STARTED_AT)

    store.record_failure(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        started_at=_STARTED_AT,
        finished_at=_GENERATED_AT + timedelta(minutes=1),
        error_code="SNAPSHOT_IDENTITY_CONFLICT",
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.read_current()

    assert raised.value.code == "SNAPSHOT_INVALID"
    assert (tmp_path / "current.json").exists()
    assert (tmp_path / "history" / "2026-08-24.json").exists()


def test_atomic_replace_failure_preserves_last_valid_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a failed current replace destroying the last readable generation."""
    store = SubingDailyWatchStore(tmp_path)
    first = _snapshot()
    store.publish(first, started_at=_STARTED_AT)
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
        store.publish(
            _snapshot(target=date(2026, 8, 25)),
            started_at=_STARTED_AT,
        )

    assert raised.value.code == "OBSERVATION_ATOMIC_WRITE_FAILED"
    assert current.read_bytes() == original_current
    assert status_path.read_bytes() == original_status
    assert (tmp_path / "history" / "2026-08-25.json").exists()
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.parametrize(
    "error_code",
    [
        "provider failed: secret-token",
        "/Volumes/private/path",
        "NEXT_TRADING_DAY_UNAVAILABLE\nexception detail",
    ],
)
def test_record_failure_rejects_non_allowlisted_error_codes(
    tmp_path: Path,
    error_code: str,
) -> None:
    """Catches exception text, paths, or secrets entering generation status."""
    store = SubingDailyWatchStore(tmp_path)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.record_failure(
            source_trading_day=_SOURCE_DAY,
            target_trading_day=_TARGET_DAY,
            started_at=_STARTED_AT,
            finished_at=_GENERATED_AT,
            error_code=error_code,
        )

    assert raised.value.code == "SNAPSHOT_INVALID"
    assert not (tmp_path / "generation-status.json").exists()


def test_generation_status_parser_rejects_non_allowlisted_error_code(
    tmp_path: Path,
) -> None:
    """Catches a pre-existing unsafe status string crossing the read boundary."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
    status_path = tmp_path / "generation-status.json"
    payload = json.loads(status_path.read_bytes())
    payload["last_run"]["status"] = "failed"
    payload["last_run"]["error_code"] = "database password leaked"
    status_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.read_generation_status()

    assert raised.value.code == "SNAPSHOT_INVALID"


def test_failed_status_replace_prevents_new_current_from_being_served(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a partially published target being exposed after status failure."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
    status_path = tmp_path / "generation-status.json"
    real_replace = os.replace

    def fail_status_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == status_path:
            raise OSError("targeted test failure")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(
            "app.market_data.subing_daily_watch_store.os.replace",
            fail_status_replace,
        )
        with pytest.raises(SubingDailyWatchStoreError) as raised:
            store.publish(
                _snapshot(target=date(2026, 8, 25)),
                started_at=_STARTED_AT,
            )

    assert raised.value.code == "OBSERVATION_ATOMIC_WRITE_FAILED"
    with pytest.raises(SubingDailyWatchStoreError) as unreadable:
        store.read_current()
    assert unreadable.value.code == "SNAPSHOT_INVALID"


def test_publish_persists_required_truthful_started_at(tmp_path: Path) -> None:
    """Catches successful status fabricating start time from generated time."""
    store = SubingDailyWatchStore(tmp_path)

    store.publish(_snapshot(), started_at=_STARTED_AT)

    status = store.read_generation_status()
    assert status is not None
    assert status["last_run"]["started_at"] == _STARTED_AT.isoformat()
    assert status["last_run"]["finished_at"] == _GENERATED_AT.isoformat()


@pytest.mark.parametrize(
    "started_at",
    [
        datetime(2026, 8, 21, 18, 25),
        datetime(2026, 8, 21, 18, 31, tzinfo=UTC),
    ],
)
def test_publish_rejects_unaware_or_late_started_at_before_writes(
    tmp_path: Path,
    started_at: datetime,
) -> None:
    """Catches invalid run chronology entering status or snapshot files."""
    store = SubingDailyWatchStore(tmp_path)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=started_at)

    assert raised.value.code == "SNAPSHOT_INVALID"
    assert list(tmp_path.iterdir()) == []


def test_malformed_decimal_is_mapped_to_typed_snapshot_invalid(
    tmp_path: Path,
) -> None:
    """Catches decimal.InvalidOperation escaping the strict store boundary."""
    store = SubingDailyWatchStore(tmp_path)
    store.publish(_snapshot(), started_at=_STARTED_AT)
    current = tmp_path / "current.json"
    payload = json.loads(current.read_bytes())
    payload["items"][0]["daily"]["close"] = "not-a-decimal"
    current.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.read_current()

    assert raised.value.code == "SNAPSHOT_INVALID"


def test_store_rejects_symlinked_root_before_chmod_or_write(tmp_path: Path) -> None:
    """Catches root chmod/write escaping through an existing directory symlink."""
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    outside.chmod(0o755)
    root = tmp_path / "store-link"
    root.symlink_to(outside, target_is_directory=True)
    store = SubingDailyWatchStore(root)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert list(outside.iterdir()) == []


def test_store_rejects_symlinked_history_before_chmod_or_write(
    tmp_path: Path,
) -> None:
    """Catches history publication escaping through an existing symlink."""
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside-history"
    outside.mkdir(mode=0o755)
    outside.chmod(0o755)
    (root / "history").symlink_to(outside, target_is_directory=True)
    store = SubingDailyWatchStore(root)

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        store.publish(_snapshot(), started_at=_STARTED_AT)

    assert raised.value.code == "OBSERVATION_ROOT_UNAVAILABLE"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755
    assert list(outside.iterdir()) == []
