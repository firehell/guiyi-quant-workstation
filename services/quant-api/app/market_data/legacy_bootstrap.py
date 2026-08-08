"""Temporary, allowlisted Parquet reader for the one-time candidate bootstrap.

This adapter is deliberately absent from the default daily composition.  It
reads one candidate file per requested window and never arbitrates row values
across files.  All returned bars still pass through HistoricalDataManager and
the canonical six-check publisher.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.maintenance import BarBatch


SHANGHAI = ZoneInfo("Asia/Shanghai")


class LegacyBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LegacyBootstrapAdapter:
    """Read only the three explicitly approved migration roots."""

    def __init__(
        self,
        *,
        contract_root: Path,
        continuous_raw_root: Path,
        previous_canonical_root: Path,
        allowed_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self.contract_root = contract_root.resolve()
        self.continuous_raw_root = continuous_raw_root.resolve()
        self.previous_canonical_root = previous_canonical_root.resolve()
        approved = tuple(path.resolve() for path in (allowed_roots or (
            contract_root,
            continuous_raw_root,
            previous_canonical_root,
        )))
        roots = (self.contract_root, self.continuous_raw_root, self.previous_canonical_root)
        if any(root not in approved or not root.is_dir() or root.is_symlink() for root in roots):
            raise LegacyBootstrapError("LEGACY_BOOTSTRAP_ROOT_INVALID")

    def fetch(
        self,
        key: DatasetKey,
        expected: tuple[datetime, ...],
    ) -> BarBatch | None:
        if key.frequency not in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}:
            raise LegacyBootstrapError("LEGACY_BOOTSTRAP_DIRECT_ONLY")
        expected_set = set(expected)
        if not expected_set:
            return None
        ranked: list[tuple[int, str, tuple[CanonicalBar, ...], Path]] = []
        for path in self._candidates(key):
            bars = self._read_candidate(path, expected)
            matches = tuple(bar for bar in bars if bar.bar_end in expected_set)
            if matches:
                ranked.append((len(matches), path.as_posix(), matches, path))
        if not ranked:
            return None
        _, _, bars, path = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
        return BarBatch(bars, _sha256(path), "legacy_staging")

    def _candidates(self, key: DatasetKey) -> tuple[Path, ...]:
        roots: tuple[Path, ...]
        candidates: tuple[Path, ...]
        if key.kind is DatasetKind.CONTRACT:
            base = (
                self.contract_root
                / f"product={key.symbol}"
                / f"contract={key.series_or_contract}"
                / f"frequency={key.frequency.value}"
            )
            roots = (self.contract_root,)
            candidates = tuple(base.glob("*.parquet")) if base.is_dir() else ()
        else:
            raw = (
                self.continuous_raw_root
                / f"product={key.symbol}"
                / f"frequency={key.frequency.value}"
            )
            prior = (
                self.previous_canonical_root
                / "provider/rqdata/dataset_kind/continuous"
                / f"symbol/{key.symbol}"
                / f"contract_or_series/{key.symbol.upper()}.MAIN"
                / f"frequency/{key.frequency.value}"
            )
            roots = (self.continuous_raw_root, self.previous_canonical_root)
            candidates = (*raw.rglob("*.parquet"), *prior.rglob("*.parquet"))
        result = []
        for path in candidates:
            resolved = path.resolve()
            if path.is_symlink() or not any(root == resolved.parent or root in resolved.parents for root in roots):
                raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PATH_ESCAPE")
            result.append(resolved)
        return tuple(sorted(result))

    def _read_candidate(
        self,
        path: Path,
        expected: tuple[datetime, ...],
    ) -> tuple[CanonicalBar, ...]:
        try:
            rows = pq.ParquetFile(path).read().to_pylist()
        except Exception as exc:  # noqa: BLE001 - convert file failures to a stable code
            raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PARQUET_INVALID") from exc
        expected_by_day: dict[date, list[datetime]] = {}
        for value in expected:
            expected_by_day.setdefault(value.astimezone(SHANGHAI).date(), []).append(value)
        bars: dict[datetime, CanonicalBar] = {}
        for index, row in enumerate(rows):
            trading_day = _day(row.get("trading_day", row.get("trading_date", row.get("date"))))
            if "bar_end" in row:
                bar_end = _aware(row["bar_end"])
            elif "datetime" in row:
                bar_end = _aware(row["datetime"])
            else:
                matches = expected_by_day.get(trading_day)
                if not matches and index < len(expected):
                    matches = [expected[index]]
                if not matches:
                    continue
                bar_end = matches[-1]
            bar = CanonicalBar(
                bar_end=bar_end,
                trading_day=trading_day,
                open=_decimal(row, "open"),
                high=_decimal(row, "high"),
                low=_decimal(row, "low"),
                close=_decimal(row, "close"),
                volume=_decimal(row, "volume"),
                turnover=_optional_decimal(row.get("turnover", row.get("total_turnover"))),
                open_interest=_optional_decimal(row.get("open_interest")),
            )
            previous = bars.get(bar_end)
            if previous is not None and previous != bar:
                raise LegacyBootstrapError("LEGACY_BOOTSTRAP_DUPLICATE_CONFLICT")
            bars[bar_end] = bar
        return tuple(bars[value] for value in sorted(bars))


def _aware(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise LegacyBootstrapError("LEGACY_BOOTSTRAP_TIME_INVALID")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(ZoneInfo("UTC"))


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise LegacyBootstrapError("LEGACY_BOOTSTRAP_TRADING_DAY_INVALID")


def _decimal(row: dict[str, Any], field: str) -> Decimal:
    value = _optional_decimal(row.get(field))
    if value is None:
        raise LegacyBootstrapError("LEGACY_BOOTSTRAP_VALUE_MISSING")
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
