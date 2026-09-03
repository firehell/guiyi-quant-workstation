"""Controlled repair seam for RQData minute-session anchor correction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Protocol

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.domain import BarFrequency, DatasetKey
from app.market_data.historical_data_manager import BarFetchRequest
from app.market_data.session_clock import session_windows_for_trading_day
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Instrument, MarketDataset, MarketPartition, TradingSession


_INTRADAY = frozenset({"1m", "5m", "15m", "30m", "60m"})
_RUNTIME_LABELS = (
    "com.guiyi.quant-api",
    "com.guiyi.quant-web",
    "com.guiyi.quant-live",
    "com.guiyi.quant-after-market",
    "com.guiyi.quant-alert",
)


class SessionAnchorRepairError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BarProvider(Protocol):
    def fetch_many(self, requests): ...


def local_runtime_stopped(
    *,
    run: Callable[..., object] = subprocess.run,
    uid: int | None = None,
) -> bool:
    """Require every production launchd service to be unloaded before publish."""
    user_id = os.getuid() if uid is None else uid
    for label in _RUNTIME_LABELS:
        result = run(
            ["launchctl", "print", f"gui/{user_id}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if getattr(result, "returncode", None) == 0:
            return False
    return True


def run_session_anchor_migration() -> None:
    """Run only the exact forward session-anchor migration."""
    from alembic import command
    from alembic.config import Config

    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    command.upgrade(Config(str(config_path)), "20260903_0045")


@dataclass(frozen=True, slots=True)
class SessionAnchorRepairPlan:
    status: str
    readonly: bool
    session_count: int
    dataset_count: int
    partition_count: int
    missing_first_minute_count: int
    scope_sha256: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.session-anchor-repair",
            "phase": "plan",
            "status": self.status,
            "readonly": self.readonly,
            "session_count": self.session_count,
            "dataset_count": self.dataset_count,
            "partition_count": self.partition_count,
            "missing_first_minute_count": self.missing_first_minute_count,
            "scope_sha256": self.scope_sha256,
        }


@dataclass(frozen=True, slots=True)
class SessionAnchorPrepareResult:
    status: str
    readonly: bool
    partition_count: int
    scope_sha256: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.session-anchor-repair",
            "phase": "prepare",
            "status": self.status,
            "readonly": self.readonly,
            "partition_count": self.partition_count,
            "scope_sha256": self.scope_sha256,
        }


@dataclass(frozen=True, slots=True)
class SessionAnchorPublishResult:
    status: str
    readonly: bool
    forward_only: bool
    rollback_root: Path

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.session-anchor-repair",
            "phase": "publish",
            "status": self.status,
            "readonly": self.readonly,
            "forward_only": self.forward_only,
            "rollback_root": str(self.rollback_root),
        }


@dataclass(frozen=True, slots=True)
class _Partition:
    dataset_id: int
    key: DatasetKey
    year: int
    month: int
    coverage_start: object
    coverage_end: object
    file_uri: str
    row_count: int


class SessionAnchorRepairService:
    """Plan, prepare and publish one exact session-anchor repair."""

    def __init__(
        self,
        session: Session,
        *,
        canonical_root: Path,
        provider: BarProvider,
        runtime_stopped: Callable[[], bool] | None = None,
        migration_runner: Callable[[], None] | None = None,
        live_cleanup: Callable[[date], None] | None = None,
    ) -> None:
        self.session = session
        self.canonical_root = canonical_root.resolve()
        self.provider = provider
        self.runtime_stopped = runtime_stopped or (lambda: False)
        self.migration_runner = migration_runner
        self.live_cleanup = live_cleanup

    def plan(self) -> SessionAnchorRepairPlan:
        self._require_revision("20260902_0044")
        partitions = self._partitions()
        one_minute = tuple(item for item in partitions if item.key.frequency is BarFrequency.M1)
        missing = 0
        store = CanonicalMonthlyStore(self.canonical_root)
        for item in one_minute:
            bars = store.read_month(item.key, item.year, item.month)
            days = tuple(sorted({bar.trading_day for bar in bars}))
            expected = self._minute_ends(item.key.symbol, days)
            baseline = self._provider_label_minute_ends(item.key.symbol, days)
            existing = tuple(bar.bar_end for bar in bars)
            missing_anchors = set(expected) - set(baseline)
            if (
                existing != baseline
                or not _catalog_matches_bars(item, bars)
                or not set(baseline) <= set(expected)
                or not missing_anchors
            ):
                raise SessionAnchorRepairError("SESSION_ANCHOR_BASE_INVALID")
            missing += len(missing_anchors)
        session_count = int(self.session.scalar(
            select(text("count(*)"))
            .select_from(TradingSession)
            .where(TradingSession.provider == "rqdata")
        ) or 0)
        scope_sha256 = _scope_sha(partitions)
        return SessionAnchorRepairPlan(
            status="planned",
            readonly=True,
            session_count=session_count,
            dataset_count=len({item.dataset_id for item in partitions}),
            partition_count=len(partitions),
            missing_first_minute_count=missing,
            scope_sha256=scope_sha256,
        )

    def prepare(
        self,
        *,
        shadow_root: Path,
        manifest_path: Path,
        apply: bool,
    ) -> SessionAnchorPrepareResult:
        if not apply:
            raise SessionAnchorRepairError("SESSION_ANCHOR_APPLY_REQUIRED")
        plan = self.plan()
        shadow = self._shadow_path(shadow_root)
        manifest = self._manifest_path(manifest_path, shadow)
        if shadow.exists() or manifest.exists():
            raise SessionAnchorRepairError("SESSION_ANCHOR_TARGET_EXISTS")
        partitions = self._partitions()
        by_identity = {
            (
                item.key.kind,
                item.key.symbol,
                item.key.series_or_contract,
                item.key.frequency,
                item.year,
                item.month,
            ): item
            for item in partitions
        }
        copied = False
        try:
            shutil.copytree(self.canonical_root, shadow, copy_function=shutil.copy2)
            copied = True
            active_store = CanonicalMonthlyStore(self.canonical_root)
            shadow_store = CanonicalMonthlyStore(shadow)
            entries: list[dict[str, object]] = []
            processed: set[tuple[object, ...]] = set()
            latest_days: set[date] = set()
            one_minute = tuple(
                item for item in partitions if item.key.frequency is BarFrequency.M1
            )
            for item in one_minute:
                current = active_store.read_month(item.key, item.year, item.month)
                trading_days = tuple(sorted({bar.trading_day for bar in current}))
                if not trading_days:
                    raise SessionAnchorRepairError("SESSION_ANCHOR_BASE_INVALID")
                latest_days.add(trading_days[-1])
                sessions = tuple(
                    window
                    for day in trading_days
                    for window in self._corrected_sessions(item.key.symbol, day)
                )
                expected = self._minute_ends(item.key.symbol, trading_days)
                baseline = self._provider_label_minute_ends(
                    item.key.symbol, trading_days
                )
                current_by_end = {bar.bar_end: bar for bar in current}
                missing = tuple(value for value in expected if value not in set(baseline))
                if (
                    tuple(current_by_end) != baseline
                    or len(current_by_end) != len(current)
                    or not _catalog_matches_bars(item, current)
                    or not set(baseline) <= set(expected)
                    or not missing
                ):
                    raise SessionAnchorRepairError("SESSION_ANCHOR_BASE_INVALID")
                batch = self.provider.fetch_many((BarFetchRequest(item.key, missing),))[0]
                fetched = {bar.bar_end: bar for bar in batch.bars}
                if set(fetched) != set(missing) or len(fetched) != len(batch.bars):
                    raise SessionAnchorRepairError("SESSION_ANCHOR_PROVIDER_INVALID")
                merged = tuple(
                    (current_by_end | fetched)[bar_end] for bar_end in expected
                )
                published = shadow_store.publish(PublishRequest(
                    item.key,
                    item.year,
                    item.month,
                    merged,
                    expected,
                ))
                entries.append(self._manifest_entry(item, published, shadow))
                processed.add(self._identity(item))
                for frequency in (
                    BarFrequency.M5,
                    BarFrequency.M15,
                    BarFrequency.M30,
                    BarFrequency.H1,
                ):
                    derived_key = DatasetKey(
                        item.key.kind,
                        item.key.symbol,
                        item.key.series_or_contract,
                        frequency,
                    )
                    derived_item = by_identity.get((
                        derived_key.kind,
                        derived_key.symbol,
                        derived_key.series_or_contract,
                        derived_key.frequency,
                        item.year,
                        item.month,
                    ))
                    if derived_item is None:
                        raise SessionAnchorRepairError("SESSION_ANCHOR_SCOPE_INVALID")
                    derived = aggregate_from_1m(
                        merged,
                        target_frequency=frequency,
                        sessions=sessions,
                    )
                    derived_expected = _derived_ends(sessions, frequency)
                    derived_published = shadow_store.publish(PublishRequest(
                        derived_key,
                        item.year,
                        item.month,
                        derived,
                        derived_expected,
                    ))
                    entries.append(
                        self._manifest_entry(derived_item, derived_published, shadow)
                    )
                    processed.add(self._identity(derived_item))
            if processed != {self._identity(item) for item in partitions}:
                raise SessionAnchorRepairError("SESSION_ANCHOR_SCOPE_INVALID")
            payload = {
                "schema_version": 1,
                "status": "prepared",
                "source_revision": "20260902_0044",
                "target_revision": "20260903_0045",
                "formula_version": "subing_ths_15m_v3",
                "canonical_root": str(self.canonical_root),
                "shadow_root": str(shadow),
                "scope_sha256": plan.scope_sha256,
                "latest_trading_days": [
                    value.isoformat() for value in _latest_cleanup_days(latest_days)
                ],
                "partitions": sorted(entries, key=lambda value: str(value["identity"])),
                "unchanged_daily_weekly_sha256": self._unchanged_hashes(shadow),
            }
            _write_json_atomic(manifest, payload)
        except Exception:
            if copied and not manifest.exists():
                # Keep the incomplete shadow for inspection; it is never publishable
                # without the final external manifest.
                pass
            raise
        return SessionAnchorPrepareResult(
            status="prepared",
            readonly=False,
            partition_count=plan.partition_count,
            scope_sha256=plan.scope_sha256,
        )

    def publish(
        self,
        *,
        shadow_root: Path,
        manifest_path: Path,
        apply: bool,
    ) -> SessionAnchorPublishResult:
        if not apply:
            raise SessionAnchorRepairError("SESSION_ANCHOR_APPLY_REQUIRED")
        if not self.runtime_stopped():
            raise SessionAnchorRepairError("RUNTIME_NOT_STOPPED")
        if self.migration_runner is None or self.live_cleanup is None:
            raise SessionAnchorRepairError("SESSION_ANCHOR_PUBLISH_UNAVAILABLE")
        shadow = self._shadow_path(shadow_root)
        manifest = self._manifest_path(manifest_path, shadow)
        payload = _read_manifest(manifest)
        self._require_revision("20260902_0044")
        partitions = self._partitions()
        scope_sha256 = _scope_sha(partitions)
        if (
            payload.get("status") != "prepared"
            or payload.get("source_revision") != "20260902_0044"
            or payload.get("target_revision") != "20260903_0045"
            or payload.get("formula_version") != "subing_ths_15m_v3"
            or payload.get("canonical_root") != str(self.canonical_root)
            or payload.get("shadow_root") != str(shadow)
            or payload.get("scope_sha256") != scope_sha256
        ):
            raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
        entries = payload.get("partitions")
        latest_days = payload.get("latest_trading_days")
        unchanged = payload.get("unchanged_daily_weekly_sha256")
        if (
            not isinstance(entries, list)
            or len(entries) != len(partitions)
            or not isinstance(latest_days, list)
            or not isinstance(unchanged, dict)
            or not shadow.is_dir()
        ):
            raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
        self._validate_manifest_files(entries, unchanged, shadow)
        rollback = self.canonical_root.with_name(
            f"{self.canonical_root.name}.pre-session-anchor-0045"
        )
        if rollback.exists():
            raise SessionAnchorRepairError("SESSION_ANCHOR_ROLLBACK_EXISTS")
        swapped = False
        catalog_published = False
        try:
            self.canonical_root.rename(rollback)
            try:
                shadow.rename(self.canonical_root)
            except Exception:
                rollback.rename(self.canonical_root)
                raise
            swapped = True
            self._publish_catalog(entries)
            self.session.commit()
            catalog_published = True
            self.migration_runner()
            self.session.expire_all()
            self._require_revision("20260903_0045")
        except Exception as exc:
            self.session.rollback()
            revision = self._current_revision()
            if swapped and revision == "20260902_0044":
                if catalog_published:
                    self._restore_catalog(entries)
                    self.session.commit()
                self.canonical_root.rename(shadow)
                rollback.rename(self.canonical_root)
            elif revision != "20260902_0044":
                raise SessionAnchorRepairError(
                    "SESSION_ANCHOR_FORWARD_RECOVERY_REQUIRED"
                ) from exc
            if isinstance(exc, SessionAnchorRepairError):
                raise
            raise SessionAnchorRepairError("SESSION_ANCHOR_PUBLISH_FAILED") from None
        try:
            for value in latest_days:
                if not isinstance(value, str):
                    raise ValueError
                self.live_cleanup(date.fromisoformat(value))
        except Exception as exc:
            raise SessionAnchorRepairError(
                "SESSION_ANCHOR_FORWARD_RECOVERY_REQUIRED"
            ) from exc
        return SessionAnchorPublishResult(
            status="published",
            readonly=False,
            forward_only=True,
            rollback_root=rollback,
        )

    def _partitions(self) -> tuple[_Partition, ...]:
        rows = self.session.execute(
            select(MarketDataset, MarketPartition)
            .join(MarketPartition, MarketPartition.dataset_id == MarketDataset.id)
            .where(MarketDataset.frequency.in_(sorted(_INTRADAY)))
            .order_by(
                MarketDataset.kind,
                MarketDataset.symbol,
                MarketDataset.series_or_contract,
                MarketDataset.frequency,
                MarketPartition.year,
                MarketPartition.month,
            )
        ).all()
        return tuple(
            _Partition(
                dataset.id,
                DatasetKey(
                    dataset.kind,
                    dataset.symbol,
                    dataset.series_or_contract,
                    dataset.frequency,
                ),
                partition.year,
                partition.month,
                partition.coverage_start,
                partition.coverage_end,
                partition.file_uri,
                partition.row_count,
            )
            for dataset, partition in rows
        )

    def _minute_ends(
        self,
        symbol: str,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]:
        return tuple(
            window.start + timedelta(minutes=offset)
            for day in trading_days
            for window in self._corrected_sessions(symbol, day)
            for offset in range(
                1,
                int((window.end - window.start).total_seconds() // 60) + 1,
            )
        )

    def _provider_label_minute_ends(
        self,
        symbol: str,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]:
        return tuple(
            window.start + timedelta(minutes=offset)
            for day in trading_days
            for window in self._provider_label_sessions(symbol, day)
            for offset in range(
                1,
                int((window.end - window.start).total_seconds() // 60) + 1,
            )
        )

    def _corrected_sessions(self, symbol: str, trading_day: date) -> tuple[SessionWindow, ...]:
        windows = self._provider_label_sessions(symbol, trading_day)
        return tuple(
            SessionWindow(window.start - timedelta(minutes=1), window.end)
            for window in windows
        )

    def _provider_label_sessions(
        self,
        symbol: str,
        trading_day: date,
    ) -> tuple[SessionWindow, ...]:
        exchange_code = self.session.scalar(
            select(Instrument.exchange_code).where(Instrument.symbol == symbol)
        )
        if exchange_code is None:
            raise SessionAnchorRepairError("SESSION_ANCHOR_BASE_INVALID")
        return session_windows_for_trading_day(
            self.session,
            exchange=exchange_code,
            symbol=symbol,
            trading_day=trading_day,
        )

    def _identity(self, item: _Partition) -> tuple[object, ...]:
        return (
            item.key.kind,
            item.key.symbol,
            item.key.series_or_contract,
            item.key.frequency,
            item.year,
            item.month,
        )

    def _manifest_entry(self, item: _Partition, published, shadow: Path) -> dict[str, object]:
        active_path = self.canonical_root / item.file_uri
        new_path = shadow / item.file_uri
        if published.parquet_path != new_path.resolve() or not active_path.is_file():
            raise SessionAnchorRepairError("SESSION_ANCHOR_PHYSICAL_INVALID")
        return {
            "identity": "/".join((
                item.key.kind.value,
                item.key.symbol,
                item.key.series_or_contract,
                item.key.frequency.value,
                f"{item.year:04d}-{item.month:02d}",
            )),
            "dataset_id": item.dataset_id,
            "year": item.year,
            "month": item.month,
            "file_uri": item.file_uri,
            "old_coverage_start": _iso(item.coverage_start),
            "old_coverage_end": _iso(item.coverage_end),
            "old_row_count": item.row_count,
            "old_sha256": _file_sha256(active_path),
            "new_coverage_start": published.coverage_start.isoformat(),
            "new_coverage_end": published.coverage_end.isoformat(),
            "new_row_count": published.row_count,
            "new_sha256": _file_sha256(new_path),
        }

    def _unchanged_hashes(self, shadow: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        for path in sorted(self.canonical_root.rglob("part.parquet")):
            relative = path.relative_to(self.canonical_root)
            text_value = relative.as_posix()
            if "/frequency=1d/" not in f"/{text_value}" and "/frequency=1w/" not in f"/{text_value}":
                continue
            copied = shadow / relative
            digest = _file_sha256(path)
            if _file_sha256(copied) != digest:
                raise SessionAnchorRepairError("SESSION_ANCHOR_UNCHANGED_COPY_INVALID")
            values[text_value] = digest
        return values

    def _shadow_path(self, value: Path) -> Path:
        shadow = value.resolve()
        if shadow == self.canonical_root or self.canonical_root in shadow.parents or shadow in self.canonical_root.parents:
            raise SessionAnchorRepairError("SESSION_ANCHOR_PATH_INVALID")
        return shadow

    def _manifest_path(self, value: Path, shadow: Path) -> Path:
        manifest = value.resolve()
        if (
            manifest == self.canonical_root
            or self.canonical_root in manifest.parents
            or manifest == shadow
            or shadow in manifest.parents
        ):
            raise SessionAnchorRepairError("SESSION_ANCHOR_PATH_INVALID")
        return manifest

    def _require_revision(self, expected: str) -> None:
        try:
            revisions = tuple(self.session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars())
        except SQLAlchemyError:
            raise SessionAnchorRepairError("SESSION_ANCHOR_PREFLIGHT_FAILED") from None
        if revisions != (expected,):
            raise SessionAnchorRepairError("SESSION_ANCHOR_PREFLIGHT_FAILED")

    def _current_revision(self) -> str | None:
        try:
            values = tuple(self.session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars())
        except SQLAlchemyError:
            return None
        return values[0] if len(values) == 1 and isinstance(values[0], str) else None

    def _validate_manifest_files(
        self,
        entries: list[object],
        unchanged: dict[object, object],
        shadow: Path,
    ) -> None:
        for raw in entries:
            if not isinstance(raw, dict):
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
            uri = raw.get("file_uri")
            old_digest = raw.get("old_sha256")
            new_digest = raw.get("new_sha256")
            if not all(isinstance(value, str) for value in (uri, old_digest, new_digest)):
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
            assert isinstance(uri, str) and isinstance(old_digest, str) and isinstance(new_digest, str)
            active_path = _relative_file(self.canonical_root, uri)
            shadow_path = _relative_file(shadow, uri)
            if _file_sha256(active_path) != old_digest or _file_sha256(shadow_path) != new_digest:
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_DRIFT")
        for raw_uri, raw_digest in unchanged.items():
            if not isinstance(raw_uri, str) or not isinstance(raw_digest, str):
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
            if (
                _file_sha256(_relative_file(self.canonical_root, raw_uri)) != raw_digest
                or _file_sha256(_relative_file(shadow, raw_uri)) != raw_digest
            ):
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_DRIFT")

    def _publish_catalog(self, entries: list[object]) -> None:
        for raw in entries:
            if not isinstance(raw, dict):
                raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
            row = self._catalog_row(raw)
            self._assert_catalog(row, raw, prefix="old")
            row.coverage_start = _datetime_value(raw.get("new_coverage_start"))
            row.coverage_end = _datetime_value(raw.get("new_coverage_end"))
            row.row_count = _int_value(raw.get("new_row_count"))
        self.session.flush()

    def _restore_catalog(self, entries: list[object]) -> None:
        for raw in entries:
            assert isinstance(raw, dict)
            row = self._catalog_row(raw)
            row.coverage_start = _datetime_value(raw.get("old_coverage_start"))
            row.coverage_end = _datetime_value(raw.get("old_coverage_end"))
            row.row_count = _int_value(raw.get("old_row_count"))
        self.session.flush()

    def _catalog_row(self, raw: dict[object, object]) -> MarketPartition:
        dataset_id = _int_value(raw.get("dataset_id"))
        year = _int_value(raw.get("year"))
        month = _int_value(raw.get("month"))
        row = self.session.scalar(select(MarketPartition).where(
            MarketPartition.dataset_id == dataset_id,
            MarketPartition.year == year,
            MarketPartition.month == month,
        ))
        if row is None:
            raise SessionAnchorRepairError("SESSION_ANCHOR_CATALOG_INVALID")
        return row

    @staticmethod
    def _assert_catalog(
        row: MarketPartition,
        raw: dict[object, object],
        *,
        prefix: str,
    ) -> None:
        if (
            row.file_uri != raw.get("file_uri")
            or _aware(row.coverage_start) != _datetime_value(raw.get(f"{prefix}_coverage_start"))
            or _aware(row.coverage_end) != _datetime_value(raw.get(f"{prefix}_coverage_end"))
            or row.row_count != _int_value(raw.get(f"{prefix}_row_count"))
        ):
            raise SessionAnchorRepairError("SESSION_ANCHOR_CATALOG_DRIFT")


def _scope_sha(partitions: tuple[_Partition, ...]) -> str:
    payload = [
        [
            item.key.kind.value,
            item.key.symbol,
            item.key.series_or_contract,
            item.key.frequency.value,
            item.year,
            item.month,
        ]
        for item in partitions
    ]
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _catalog_matches_bars(
    item: _Partition,
    bars: tuple[object, ...],
) -> bool:
    if not bars or len(bars) != item.row_count:
        return False
    first_end = getattr(bars[0], "bar_end", None)
    last_end = getattr(bars[-1], "bar_end", None)
    return (
        isinstance(first_end, datetime)
        and isinstance(last_end, datetime)
        and isinstance(item.coverage_start, datetime)
        and isinstance(item.coverage_end, datetime)
        and _aware(first_end - timedelta(minutes=1)) == _aware(item.coverage_start)
        and _aware(last_end) == _aware(item.coverage_end)
    )


def _latest_cleanup_days(values: set[date]) -> tuple[date, ...]:
    """Restrict Redis cleanup to the one current trading day in the repair scope."""
    return (max(values),) if values else ()


def _derived_ends(
    sessions: tuple[SessionWindow, ...],
    frequency: BarFrequency,
) -> tuple[datetime, ...]:
    width = {
        BarFrequency.M5: 5,
        BarFrequency.M15: 15,
        BarFrequency.M30: 30,
        BarFrequency.H1: 60,
    }[frequency]
    return tuple(
        window.start + timedelta(minutes=min(offset, count))
        for window in sessions
        for count in (int((window.end - window.start).total_seconds() // 60),)
        for offset in range(width, count + width, width)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso(value: object) -> str:
    if not isinstance(value, datetime):
        raise SessionAnchorRepairError("SESSION_ANCHOR_CATALOG_INVALID")
    return _aware(value).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID") from None
    if not isinstance(value, dict):
        raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
    return value


def _relative_file(root: Path, uri: str) -> Path:
    path = (root / uri).resolve()
    if root != path and root not in path.parents:
        raise SessionAnchorRepairError("SESSION_ANCHOR_PATH_INVALID")
    if not path.is_file():
        raise SessionAnchorRepairError("SESSION_ANCHOR_PHYSICAL_INVALID")
    return path


def _datetime_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID") from None
    return _aware(result)


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionAnchorRepairError("SESSION_ANCHOR_MANIFEST_INVALID")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
