from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol, cast

from .domain import BarFrequency
from .subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchError,
    SubingDailyWatchItem,
    SubingDailyWatchSnapshot,
)
from .subing_ema_trend import PriceSide, SubingEmaTrendSnapshot


SUBING_OBSERVATION_ROOT_ENV = "GUIYI_SUBING_OBSERVATION_ROOT"

_SCHEMA_VERSION = 1
_PROJECTION_VERSION = "subing_daily_watch_v1"
_FORMULA_VERSION = "subing_ema21_trend_v1"
_SERIES_KIND = "actual_dominant"
_FREQUENCIES = ["1d", "60m"]
_EMA_PERIOD = 21
_SLOPE_WINDOWS = [5, 10]
_GENERATION_ERROR_CODES = frozenset(
    {
        "ACTIVE_OPERATIONAL_SCOPE_MISMATCH",
        "NEXT_TRADING_DAY_UNAVAILABLE",
        "OBSERVATION_ROOT_UNCONFIGURED",
        "OBSERVATION_ROOT_UNAVAILABLE",
        "OBSERVATION_ROOT_NOT_WRITABLE",
        "SNAPSHOT_INVALID",
        "SNAPSHOT_IDENTITY_CONFLICT",
        "CURRENT_TARGET_REGRESSION",
        "OBSERVATION_ATOMIC_WRITE_FAILED",
    }
)


class SubingDailyWatchStoreError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MountInspector(Protocol):
    def is_mount(self, path: Path) -> bool: ...

    def is_symlink(self, path: Path) -> bool: ...

    def exists(self, path: Path) -> bool: ...

    def is_dir(self, path: Path) -> bool: ...

    def is_writable(self, path: Path) -> bool: ...


class PathMountInspector:
    def is_mount(self, path: Path) -> bool:
        return path.is_mount()

    def is_symlink(self, path: Path) -> bool:
        return path.is_symlink()

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def is_writable(self, path: Path) -> bool:
        return os.access(path, os.W_OK | os.X_OK)


@dataclass(frozen=True, slots=True)
class SubingDailyWatchPublishResult:
    status: Literal["published", "idempotent"]
    target_trading_day: date


class SubingDailyWatchStore:
    def __init__(
        self,
        root: Path,
        *,
        root_validator: Callable[[], Path] | None = None,
    ) -> None:
        self._root = root
        self._root_validator = root_validator
        self._history = root / "history"
        self._current = root / "current.json"
        self._generation_status = root / "generation-status.json"

    def publish(
        self,
        snapshot: SubingDailyWatchSnapshot,
        *,
        started_at: datetime,
    ) -> SubingDailyWatchPublishResult:
        self._revalidate_root()
        if not _is_aware(started_at) or started_at > snapshot.generated_at:
            raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
        snapshot_bytes = _snapshot_bytes(snapshot)
        current_bytes = (
            _read_bytes(self._current) if self._current.exists() else None
        )
        current = (
            _parse_snapshot_bytes(current_bytes)
            if current_bytes is not None
            else None
        )
        if (
            current is not None
            and current.target_trading_day > snapshot.target_trading_day
        ):
            raise SubingDailyWatchStoreError("CURRENT_TARGET_REGRESSION")
        if (
            current is not None
            and current.target_trading_day == snapshot.target_trading_day
            and current_bytes != snapshot_bytes
        ):
            raise SubingDailyWatchStoreError("SNAPSHOT_IDENTITY_CONFLICT")

        self._ensure_directories()
        history_path = self._history / f"{snapshot.target_trading_day.isoformat()}.json"
        status: Literal["published", "idempotent"] = "published"
        if history_path.exists():
            existing = _read_bytes(history_path)
            if existing != snapshot_bytes:
                _parse_snapshot_bytes(existing)
                raise SubingDailyWatchStoreError("SNAPSHOT_IDENTITY_CONFLICT")
            status = "idempotent"
        else:
            _atomic_write(
                history_path,
                snapshot_bytes,
                preflight=self._revalidate_root,
            )

        if current_bytes != snapshot_bytes:
            _atomic_write(
                self._current,
                snapshot_bytes,
                preflight=self._revalidate_root,
            )
        _atomic_write(
            self._generation_status,
            _canonical_bytes(
                _passed_status_payload(snapshot, started_at=started_at)
            ),
            preflight=self._revalidate_root,
        )
        return SubingDailyWatchPublishResult(
            status=status,
            target_trading_day=snapshot.target_trading_day,
        )

    def read_current(self) -> SubingDailyWatchSnapshot | None:
        if not self._current.exists():
            return None
        snapshot = _parse_snapshot_bytes(_read_bytes(self._current))
        status = self.read_generation_status()
        last_run = status.get("last_run") if status is not None else None
        if (
            status is None
            or status.get("last_successful_target_trading_day")
            != snapshot.target_trading_day.isoformat()
            or (
                isinstance(last_run, Mapping)
                and last_run.get("status") == "failed"
                and last_run.get("target_trading_day")
                == snapshot.target_trading_day.isoformat()
            )
        ):
            raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
        return snapshot

    def read_generation_status(self) -> Mapping[str, object] | None:
        if not self._generation_status.exists():
            return None
        return _parse_generation_status(_read_bytes(self._generation_status))

    def record_failure(
        self,
        *,
        source_trading_day: date,
        target_trading_day: date | None,
        started_at: datetime,
        finished_at: datetime,
        error_code: str,
    ) -> None:
        self._revalidate_root()
        if (
            not isinstance(error_code, str)
            or error_code not in _GENERATION_ERROR_CODES
            or not _is_aware(started_at)
            or not _is_aware(finished_at)
            or finished_at < started_at
        ):
            raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
        self._ensure_directories()
        existing = self.read_generation_status()
        last_successful = (
            existing.get("last_successful_target_trading_day")
            if existing is not None
            else None
        )
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "projection_version": _PROJECTION_VERSION,
            "last_run": {
                "source_trading_day": source_trading_day.isoformat(),
                "target_trading_day": (
                    target_trading_day.isoformat()
                    if target_trading_day is not None
                    else None
                ),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "status": "failed",
                "error_code": error_code,
            },
            "last_successful_target_trading_day": last_successful,
        }
        _atomic_write(
            self._generation_status,
            _canonical_bytes(payload),
            preflight=self._revalidate_root,
        )

    def _revalidate_root(self) -> None:
        if self._root_validator is None:
            return
        if self._root_validator() != self._root:
            raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")

    def _ensure_directories(self) -> None:
        try:
            if self._root.is_symlink() or self._history.is_symlink():
                raise SubingDailyWatchStoreError(
                    "OBSERVATION_ROOT_UNAVAILABLE"
                )
            self._revalidate_root()
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self._root.is_symlink() or self._history.is_symlink():
                raise SubingDailyWatchStoreError(
                    "OBSERVATION_ROOT_UNAVAILABLE"
                )
            self._revalidate_root()
            self._root.chmod(0o700)
            self._revalidate_root()
            self._history.mkdir(exist_ok=True, mode=0o700)
            if self._history.is_symlink():
                raise SubingDailyWatchStoreError(
                    "OBSERVATION_ROOT_UNAVAILABLE"
                )
            self._revalidate_root()
            self._history.chmod(0o700)
        except SubingDailyWatchStoreError:
            raise
        except (OSError, NotImplementedError) as exc:
            raise SubingDailyWatchStoreError(
                "OBSERVATION_ROOT_NOT_WRITABLE"
            ) from exc


def resolve_subing_observation_root(
    *,
    environ: Mapping[str, str],
    inspector: MountInspector,
) -> Path:
    configured = environ.get(SUBING_OBSERVATION_ROOT_ENV, "").strip()
    if not configured:
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNCONFIGURED")
    root = Path(configured)
    parts = root.parts
    if (
        not root.is_absolute()
        or len(parts) < 4
        or parts[0] != "/"
        or parts[1] != "Volumes"
        or not parts[2]
        or any(part in {".", ".."} for part in parts)
    ):
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")

    volume = Path("/Volumes") / parts[2]
    if not inspector.is_mount(volume):
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
    candidate = volume
    for part in parts[3:]:
        if inspector.is_symlink(candidate):
            raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
        candidate /= part
    if inspector.is_symlink(candidate):
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
    writable_parent = root
    while not inspector.exists(writable_parent):
        parent = writable_parent.parent
        if parent == writable_parent:
            raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
        writable_parent = parent
    if not inspector.is_dir(writable_parent) or not inspector.is_writable(
        writable_parent
    ):
        raise SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
    return root


def _snapshot_bytes(snapshot: SubingDailyWatchSnapshot) -> bytes:
    _validate_snapshot(snapshot)
    return _canonical_bytes(_snapshot_payload(snapshot))


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _snapshot_payload(snapshot: SubingDailyWatchSnapshot) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "projection_version": _PROJECTION_VERSION,
        "formula_version": _FORMULA_VERSION,
        "source_trading_day": snapshot.source_trading_day.isoformat(),
        "target_trading_day": snapshot.target_trading_day.isoformat(),
        "generated_at": snapshot.generated_at.isoformat(),
        "series_kind": _SERIES_KIND,
        "frequencies": _FREQUENCIES,
        "ema_period": _EMA_PERIOD,
        "slope_windows": _SLOPE_WINDOWS,
        "counts": snapshot.counts,
        "items": [_item_payload(item) for item in snapshot.items],
    }


def _item_payload(item: SubingDailyWatchItem) -> dict[str, object]:
    return {
        "symbol": item.symbol,
        "product_name": item.product_name,
        "sector": item.sector,
        "decision": item.decision.value,
        "reason_codes": list(item.reason_codes),
        "daily": _trend_payload(item.daily),
        "hourly": _trend_payload(item.hourly),
        "unavailable_reasons": list(item.unavailable_reasons),
    }


def _trend_payload(trend: SubingEmaTrendSnapshot | None) -> object:
    if trend is None:
        return None
    return {
        "bar_end": trend.bar_end.isoformat(),
        "trading_day": trend.trading_day.isoformat(),
        "physical_contract": trend.contract,
        "segment_start_trading_day": trend.segment_start_trading_day.isoformat(),
        "close": _decimal_string(trend.close),
        "ema21": _decimal_string(trend.ema21),
        "price_side": trend.price_side.value,
        "slope_5_raw": _decimal_string(trend.slope_5_raw),
        "slope_10_raw": _decimal_string(trend.slope_10_raw),
        "slope_5_bps_per_bar": _decimal_string(trend.slope_5_bps_per_bar),
        "slope_10_bps_per_bar": _decimal_string(trend.slope_10_bps_per_bar),
    }


def _validate_snapshot(snapshot: SubingDailyWatchSnapshot) -> None:
    symbols = tuple(item.symbol for item in snapshot.items)
    if not symbols or len(set(symbols)) != len(symbols):
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
    for item in snapshot.items:
        for timeframe, trend in (
            (BarFrequency.D1, item.daily),
            (BarFrequency.H1, item.hourly),
        ):
            if trend is not None and (
                trend.timeframe is not timeframe
                or trend.trading_day != snapshot.source_trading_day
                or not _is_aware(trend.bar_end)
            ):
                raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
        if item.daily is not None and item.hourly is not None and (
            item.daily.contract != item.hourly.contract
            or item.daily.segment_start_trading_day
            != item.hourly.segment_start_trading_day
        ):
            raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")


def _parse_snapshot_bytes(raw: bytes) -> SubingDailyWatchSnapshot:
    payload = _load_object(raw)
    try:
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "projection_version",
                "formula_version",
                "source_trading_day",
                "target_trading_day",
                "generated_at",
                "series_kind",
                "frequencies",
                "ema_period",
                "slope_windows",
                "counts",
                "items",
            },
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _SCHEMA_VERSION
            or payload["projection_version"] != _PROJECTION_VERSION
            or payload["formula_version"] != _FORMULA_VERSION
            or payload["series_kind"] != _SERIES_KIND
            or payload["frequencies"] != _FREQUENCIES
            or payload["ema_period"] != _EMA_PERIOD
            or payload["slope_windows"] != _SLOPE_WINDOWS
        ):
            raise ValueError
        items_value = payload["items"]
        if not isinstance(items_value, list):
            raise ValueError
        source_day = _parse_date(payload["source_trading_day"])
        snapshot = SubingDailyWatchSnapshot(
            source_trading_day=source_day,
            target_trading_day=_parse_date(payload["target_trading_day"]),
            generated_at=_parse_datetime(payload["generated_at"]),
            items=tuple(_parse_item(item, source_day) for item in items_value),
        )
        _validate_snapshot(snapshot)
        _validate_counts(payload["counts"], snapshot.counts)
        if _snapshot_bytes(snapshot) != raw:
            raise ValueError
        return snapshot
    except (KeyError, TypeError, ValueError, SubingDailyWatchError) as exc:
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID") from exc


def _parse_item(value: object, source_day: date) -> SubingDailyWatchItem:
    item = _as_object(value)
    _require_exact_keys(
        item,
        {
            "symbol",
            "product_name",
            "sector",
            "decision",
            "reason_codes",
            "daily",
            "hourly",
            "unavailable_reasons",
        },
    )
    reason_codes = _string_tuple(item["reason_codes"])
    unavailable_reasons = _string_tuple(item["unavailable_reasons"])
    return SubingDailyWatchItem(
        symbol=_string(item["symbol"]),
        product_name=_string(item["product_name"]),
        sector=_string(item["sector"]),
        decision=SubingDailyWatchDecision(_string(item["decision"])),
        reason_codes=reason_codes,
        daily=_parse_trend(item["daily"], BarFrequency.D1, source_day),
        hourly=_parse_trend(item["hourly"], BarFrequency.H1, source_day),
        unavailable_reasons=unavailable_reasons,
    )


def _parse_trend(
    value: object,
    timeframe: BarFrequency,
    source_day: date,
) -> SubingEmaTrendSnapshot | None:
    if value is None:
        return None
    trend = _as_object(value)
    _require_exact_keys(
        trend,
        {
            "bar_end",
            "trading_day",
            "physical_contract",
            "segment_start_trading_day",
            "close",
            "ema21",
            "price_side",
            "slope_5_raw",
            "slope_10_raw",
            "slope_5_bps_per_bar",
            "slope_10_bps_per_bar",
        },
    )
    trading_day = _parse_date(trend["trading_day"])
    if trading_day != source_day:
        raise ValueError
    return SubingEmaTrendSnapshot(
        timeframe=timeframe,
        bar_end=_parse_datetime(trend["bar_end"]),
        trading_day=trading_day,
        contract=_nonempty_string(trend["physical_contract"]),
        segment_start_trading_day=_parse_date(
            trend["segment_start_trading_day"]
        ),
        close=_parse_decimal_string(trend["close"]),
        ema21=_parse_decimal_string(trend["ema21"]),
        price_side=PriceSide(_string(trend["price_side"])),
        slope_5_raw=_parse_decimal_string(trend["slope_5_raw"]),
        slope_10_raw=_parse_decimal_string(trend["slope_10_raw"]),
        slope_5_bps_per_bar=_parse_decimal_string(
            trend["slope_5_bps_per_bar"]
        ),
        slope_10_bps_per_bar=_parse_decimal_string(
            trend["slope_10_bps_per_bar"]
        ),
    )


def _passed_status_payload(
    snapshot: SubingDailyWatchSnapshot,
    *,
    started_at: datetime,
) -> dict[str, object]:
    finished_at = snapshot.generated_at.isoformat()
    return {
        "schema_version": _SCHEMA_VERSION,
        "projection_version": _PROJECTION_VERSION,
        "last_run": {
            "source_trading_day": snapshot.source_trading_day.isoformat(),
            "target_trading_day": snapshot.target_trading_day.isoformat(),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at,
            "status": "passed",
            "error_code": None,
        },
        "last_successful_target_trading_day": snapshot.target_trading_day.isoformat(),
    }


def _parse_generation_status(raw: bytes) -> Mapping[str, object]:
    payload = _load_object(raw)
    try:
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "projection_version",
                "last_run",
                "last_successful_target_trading_day",
            },
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _SCHEMA_VERSION
            or payload["projection_version"] != _PROJECTION_VERSION
        ):
            raise ValueError
        last_run = _as_object(payload["last_run"])
        _require_exact_keys(
            last_run,
            {
                "source_trading_day",
                "target_trading_day",
                "started_at",
                "finished_at",
                "status",
                "error_code",
            },
        )
        _parse_date(last_run["source_trading_day"])
        if last_run["target_trading_day"] is not None:
            _parse_date(last_run["target_trading_day"])
        started = _parse_datetime(last_run["started_at"])
        finished = _parse_datetime(last_run["finished_at"])
        if finished < started or last_run["status"] not in {"passed", "failed"}:
            raise ValueError
        error_code = last_run["error_code"]
        if (last_run["status"] == "passed" and error_code is not None) or (
            last_run["status"] == "failed"
            and error_code not in _GENERATION_ERROR_CODES
        ):
            raise ValueError
        successful = payload["last_successful_target_trading_day"]
        if successful is not None:
            _parse_date(successful)
        if last_run["status"] == "passed" and (
            last_run["target_trading_day"] is None
            or successful != last_run["target_trading_day"]
        ):
            raise ValueError
        if _canonical_bytes(payload) != raw:
            raise ValueError
        return payload
    except (KeyError, TypeError, ValueError) as exc:
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID") from exc


def _load_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
        return _as_object(value)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID") from exc


def _as_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError
    return cast(dict[str, object], value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError


def _validate_counts(value: object, expected: Mapping[str, int]) -> None:
    counts = _as_object(value)
    _require_exact_keys(counts, set(expected))
    if any(type(count) is not int or count < 0 for count in counts.values()):
        raise ValueError
    if counts != expected:
        raise ValueError


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _nonempty_string(value: object) -> str:
    result = _string(value)
    if not result:
        raise ValueError
    return result


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError
    return tuple(value)


def _parse_date(value: object) -> date:
    return date.fromisoformat(_string(value))


def _parse_datetime(value: object) -> datetime:
    serialized = _string(value)
    result = datetime.fromisoformat(serialized)
    if not _is_aware(result) or result.isoformat() != serialized:
        raise ValueError
    return result


def _parse_decimal_string(value: object) -> Decimal:
    serialized = _string(value)
    try:
        result = Decimal(serialized)
    except InvalidOperation as exc:
        raise ValueError from exc
    if not result.is_finite() or _decimal_string(result) != serialized:
        raise ValueError
    return result


def _decimal_string(value: Decimal) -> str:
    if not value.is_finite():
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID")
    return format(value, "f")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SubingDailyWatchStoreError("SNAPSHOT_INVALID") from exc


def _atomic_write(
    target: Path,
    content: bytes,
    *,
    preflight: Callable[[], None] | None = None,
) -> None:
    temporary_path: Path | None = None
    descriptor = -1
    try:
        if preflight is not None:
            preflight()
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = -1
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        if preflight is not None:
            preflight()
        os.replace(temporary_path, target)
        temporary_path = None
    except (OSError, NotImplementedError) as exc:
        raise SubingDailyWatchStoreError("OBSERVATION_ATOMIC_WRITE_FAILED") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
