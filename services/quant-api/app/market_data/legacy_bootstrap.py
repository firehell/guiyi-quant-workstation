"""Temporary, allowlisted Parquet reader for the one-time candidate bootstrap.

This adapter is deliberately absent from the default daily composition.  It
reads one candidate file per requested window and never arbitrates row values
across files.  All returned bars still pass through HistoricalDataManager and
the canonical six-check publisher.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from app.market_data.catalog import MainMapFact
from app.market_data.domain import (
    DERIVED_FREQUENCIES,
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    DatasetKind,
)
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
            prior = (
                self.previous_canonical_root
                / "provider/rqdata/dataset_kind/actual_dominant"
                / f"symbol/{key.symbol}"
                / f"contract_or_series/{key.series_or_contract}"
                / f"frequency/{key.frequency.value}"
            )
            roots = (self.contract_root, self.previous_canonical_root)
            candidates = (
                *(base.glob("*.parquet") if base.is_dir() else ()),
                *prior.rglob("*.parquet"),
            )
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


def plan_gate_a_scope(
    *,
    products: tuple[str, ...],
    starts: Mapping[str, date],
    through: date,
    candidate_root: Path,
    active_canonical_root: Path,
    trading_days: Mapping[str, tuple[date, ...]],
    main_map: tuple[MainMapFact, ...],
    legacy_coverages: Mapping[DatasetKey, tuple[tuple[Path, tuple[date, ...]], ...]],
    legacy_roots: tuple[Path, ...],
) -> dict[str, Any]:
    """Build the immutable, no-write Gate A candidate scope.

    Coverage is intentionally calculated at trading-day granularity.  The
    canonical publisher remains responsible for intraday/session validation;
    a failed candidate month is later replaced by an exact provider window.
    """

    normalized_products = tuple(sorted({value.strip().lower() for value in products}))
    if not normalized_products or len(normalized_products) != len(products):
        raise LegacyBootstrapError("GATE_A_UNIVERSE_INVALID")
    candidate = candidate_root.resolve()
    active = active_canonical_root.resolve()
    if candidate == active or candidate in active.parents or active in candidate.parents:
        raise LegacyBootstrapError("GATE_A_CANDIDATE_ROOT_OVERLAPS_ACTIVE")

    days_by_product: dict[str, tuple[date, ...]] = {}
    for symbol in normalized_products:
        start = starts.get(symbol)
        if start is None or start > through:
            raise LegacyBootstrapError("GATE_A_PRODUCT_WINDOW_INVALID")
        days = tuple(sorted(set(trading_days.get(symbol, ()))))
        if not days:
            raise LegacyBootstrapError("GATE_A_TRADING_CALENDAR_MISSING")
        days_by_product[symbol] = days

    map_by_day: dict[tuple[str, date], str] = {}
    for fact in main_map:
        symbol = fact.symbol.strip().lower()
        if symbol not in days_by_product or fact.trade_date > through:
            continue
        identity = (symbol, fact.trade_date)
        contract = fact.contract.strip().upper()
        previous = map_by_day.get(identity)
        if previous is not None and previous != contract:
            raise LegacyBootstrapError("GATE_A_MAIN_MAP_CONFLICT")
        map_by_day[identity] = contract

    desired: dict[DatasetKey, set[date]] = defaultdict(set)
    for symbol in normalized_products:
        start = starts[symbol]
        all_days = days_by_product[symbol]
        direct_days = tuple(day for day in all_days if start <= day <= through)
        week_ends = _complete_week_ends(all_days, start=start, through=through)
        for frequency, values in (
            (BarFrequency.M1, direct_days),
            (BarFrequency.D1, direct_days),
            (BarFrequency.W1, week_ends),
        ):
            desired[DatasetKey(DatasetKind.CONTINUOUS, symbol, "MAIN", frequency)].update(
                values
            )
        for day in direct_days:
            contract = map_by_day.get((symbol, day))
            if contract is None:
                continue
            for frequency in (BarFrequency.M1, BarFrequency.D1):
                desired[DatasetKey(DatasetKind.CONTRACT, symbol, contract, frequency)].add(day)
        for day in week_ends:
            contract = map_by_day.get((symbol, day))
            if contract is not None:
                desired[DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)].add(
                    day
                )

    month_targets: list[tuple[DatasetKey, int, int, tuple[date, ...]]] = []
    for key, values in desired.items():
        by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
        for day in values:
            by_month[(day.year, day.month)].append(day)
        for (year, month), month_days in by_month.items():
            month_targets.append((key, year, month, tuple(sorted(month_days))))
    month_targets.sort(key=lambda item: (*item[0].as_tuple(), item[1], item[2]))

    selected: list[dict[str, Any]] = []
    provider_windows: list[dict[str, Any]] = []
    fully_covered = 0
    for key, year, month, month_days in month_targets:
        desired_set = set(month_days)
        ranked: list[tuple[int, str, Path, set[date]]] = []
        for path, covered_days in legacy_coverages.get(key, ()):
            covered = {
                day
                for day in covered_days
                if day.year == year and day.month == month and day in desired_set
            }
            if covered:
                ranked.append((len(covered), path.resolve().as_posix(), path.resolve(), covered))
        chosen_path: Path | None = None
        covered: set[date] = set()
        if ranked:
            _, _, chosen_path, covered = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
            selected.append(
                {
                    "dataset": list(key.as_tuple()),
                    "year": year,
                    "month": month,
                    "path": chosen_path.as_posix(),
                    "covered_trading_days": len(covered),
                    "desired_trading_days": len(month_days),
                }
            )
        missing = tuple(day for day in month_days if day not in covered)
        if not missing:
            fully_covered += 1
        else:
            for window_start, window_end, count in _missing_windows(month_days, missing):
                provider_windows.append(
                    {
                        "dataset": list(key.as_tuple()),
                        "year": year,
                        "month": month,
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                        "missing_trading_days": count,
                        "reason": "LEGACY_WINDOW_UNCOVERED",
                    }
                )

    direct_keys = set(desired)
    direct_months = {(key, year, month) for key, year, month, _ in month_targets}
    derived_keys: set[DatasetKey] = set()
    derived_months: set[tuple[DatasetKey, int, int]] = set()
    for key, year, month in direct_months:
        if key.frequency is not BarFrequency.M1:
            continue
        for frequency in sorted(DERIVED_FREQUENCIES, key=lambda value: value.value):
            derived = DatasetKey(key.kind, key.symbol, key.series_or_contract, frequency)
            derived_keys.add(derived)
            derived_months.add((derived, year, month))

    provider_windows.sort(
        key=lambda item: (*item["dataset"], item["year"], item["month"], item["start"])
    )
    counts = {
        "products": len(normalized_products),
        "direct_datasets": len(direct_keys),
        "derived_datasets": len(derived_keys),
        "physical_datasets": len(direct_keys | derived_keys),
        "direct_month_partitions": len(direct_months),
        "derived_month_partitions": len(derived_months),
        "month_partitions": len(direct_months | derived_months),
        "legacy_selected_month_targets": len(selected),
        "legacy_fully_covered_month_targets": fully_covered,
        "rqdata_windows": len(provider_windows),
        "rqdata_missing_trading_days": sum(
            int(item["missing_trading_days"]) for item in provider_windows
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "mode": "gate_a_exact_scope_dry_run",
        "read_only": True,
        "through": through.isoformat(),
        "candidate_root": candidate.as_posix(),
        "active_canonical_root": active.as_posix(),
        "products": list(normalized_products),
        "legacy_roots": [path.resolve().as_posix() for path in legacy_roots],
        "counts": counts,
        "legacy_selected_month_targets": selected,
        "rqdata_windows": provider_windows,
    }
    payload["scope_digest"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def scan_legacy_coverages(
    *,
    contract_root: Path,
    continuous_raw_root: Path,
    previous_canonical_root: Path,
    products: tuple[str, ...],
) -> tuple[
    dict[DatasetKey, tuple[tuple[Path, tuple[date, ...]], ...]],
    tuple[str, ...],
]:
    """Read only direct-frequency day identities from the migration allowlist."""

    roots = tuple(
        path.resolve()
        for path in (contract_root, continuous_raw_root, previous_canonical_root)
    )
    if any(not root.is_dir() or root.is_symlink() for root in roots):
        raise LegacyBootstrapError("LEGACY_BOOTSTRAP_ROOT_INVALID")
    product_set = {value.strip().lower() for value in products}
    if not product_set:
        raise LegacyBootstrapError("GATE_A_UNIVERSE_INVALID")

    collected: dict[DatasetKey, list[tuple[Path, tuple[date, ...]]]] = defaultdict(list)
    invalid: list[str] = []
    for root_index, root in enumerate(roots):
        for path in sorted(root.rglob("*.parquet")):
            resolved = path.resolve()
            if path.is_symlink() or root not in resolved.parents:
                raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PATH_ESCAPE")
            try:
                key = _legacy_identity(root_index, resolved.relative_to(root), product_set)
                if key is None:
                    continue
                parquet = pq.ParquetFile(resolved)
                names = set(parquet.schema_arrow.names)
                if not {"open", "high", "low", "close", "volume"}.issubset(names):
                    raise LegacyBootstrapError("LEGACY_BOOTSTRAP_SCHEMA_INVALID")
                day_column = next(
                    (name for name in ("trading_day", "trading_date", "date") if name in names),
                    None,
                )
                if day_column is None:
                    raise LegacyBootstrapError("LEGACY_BOOTSTRAP_TRADING_DAY_INVALID")
                values = parquet.read(columns=[day_column]).column(day_column).to_pylist()
                days = tuple(sorted({_day(value) for value in values if value is not None}))
                if not days:
                    raise LegacyBootstrapError("LEGACY_BOOTSTRAP_EMPTY")
            except Exception:  # noqa: BLE001 - report candidate; do not mutate or stop scan
                invalid.append(resolved.as_posix())
                continue
            collected[key].append((resolved, days))
    return (
        {
            key: tuple(sorted(values, key=lambda item: item[0].as_posix()))
            for key, values in collected.items()
        },
        tuple(sorted(invalid)),
    )


def _legacy_identity(
    root_index: int,
    relative: Path,
    products: set[str],
) -> DatasetKey | None:
    parts = relative.parts
    if root_index in {0, 1}:
        values = {
            part.split("=", 1)[0]: part.split("=", 1)[1]
            for part in parts
            if "=" in part
        }
        symbol = values.get("product", "").lower()
        frequency = values.get("frequency", "")
        if symbol not in products or frequency not in {"1m", "1d", "1w"}:
            return None
        if root_index == 0:
            contract = values.get("contract", "").upper()
            if not contract:
                return None
            return DatasetKey(DatasetKind.CONTRACT, symbol, contract, frequency)
        return DatasetKey(DatasetKind.CONTINUOUS, symbol, "MAIN", frequency)

    def value_after(name: str) -> str | None:
        try:
            return parts[parts.index(name) + 1]
        except (ValueError, IndexError):
            return None

    kind = value_after("dataset_kind")
    symbol = (value_after("symbol") or "").lower()
    series = value_after("contract_or_series")
    frequency = value_after("frequency")
    if (
        kind not in {"actual_dominant", "continuous"}
        or symbol not in products
        or series is None
        or frequency not in {"1m", "1d", "1w"}
    ):
        return None
    if kind == "continuous":
        return DatasetKey(DatasetKind.CONTINUOUS, symbol, "MAIN", frequency)
    return DatasetKey(DatasetKind.CONTRACT, symbol, series, frequency)


def _complete_week_ends(
    days: tuple[date, ...],
    *,
    start: date,
    through: date,
) -> tuple[date, ...]:
    by_week: dict[tuple[int, int], list[date]] = defaultdict(list)
    for day in days:
        iso = day.isocalendar()
        by_week[(iso.year, iso.week)].append(day)
    result = []
    for values in by_week.values():
        week_end = max(values)
        if start <= week_end <= through:
            result.append(week_end)
    return tuple(sorted(result))


def _missing_windows(
    desired: tuple[date, ...], missing: tuple[date, ...]
) -> tuple[tuple[date, date, int], ...]:
    missing_set = set(missing)
    windows: list[tuple[date, date, int]] = []
    start: date | None = None
    end: date | None = None
    count = 0
    for day in desired:
        if day in missing_set:
            if start is None:
                start = day
            end = day
            count += 1
        elif start is not None and end is not None:
            windows.append((start, end, count))
            start = end = None
            count = 0
    if start is not None and end is not None:
        windows.append((start, end, count))
    return tuple(windows)


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
