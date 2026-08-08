"""Temporary, allowlisted Parquet reader for the one-time candidate bootstrap.

FROZEN / migration-only: pending removal after Gate C.
This path MUST NOT gain new features, MUST NOT be used as the new Gate A data
source, and MUST NOT be wired into daily composition. New Gate A uses
``build_candidate_historical_data_manager`` (RQData-only, legacy=None).

This adapter is deliberately absent from the default daily composition.  It
reads one candidate file per requested window and never arbitrates row values
across files.  All returned bars still pass through HistoricalDataManager and
the canonical six-check publisher.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, time
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
    RQDATA_INTRADAY_HISTORY_START,
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
        exact_scope: Mapping[str, Any] | None = None,
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
        self._selected = _selected_candidates(exact_scope or {})
        self._row_cache: dict[Path, tuple[dict[str, Any], ...]] = {}

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
        candidates = self._exact_candidates(key, expected)
        for path in candidates:
            bars = self._read_candidate(path, expected)
            matches = tuple(bar for bar in bars if bar.bar_end in expected_set)
            if matches:
                ranked.append((len(matches), path.as_posix(), matches, path))
        if not ranked:
            return None
        _, _, bars, path = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
        return BarBatch(bars, _sha256(path), "legacy_staging")

    def _exact_candidates(
        self,
        key: DatasetKey,
        expected: tuple[datetime, ...],
    ) -> tuple[Path, ...]:
        if not self._selected:
            return self._candidates(key)
        logical_end = max(value.astimezone(SHANGHAI).date() for value in expected)
        path = self._selected.get((*key.as_tuple(), logical_end.year, logical_end.month))
        if path is None:
            return ()
        resolved = path.resolve()
        roots = (self.contract_root, self.continuous_raw_root, self.previous_canonical_root)
        if path.is_symlink() or not any(root in resolved.parents for root in roots):
            raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PATH_ESCAPE")
        if not resolved.is_file():
            raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PARQUET_INVALID")
        return (resolved,)

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
        resolved = path.resolve()
        rows = self._row_cache.get(resolved)
        if rows is None:
            try:
                rows = tuple(pq.ParquetFile(resolved).read().to_pylist())
            except Exception as exc:  # noqa: BLE001 - convert file failures to a stable code
                raise LegacyBootstrapError("LEGACY_BOOTSTRAP_PARQUET_INVALID") from exc
            self._row_cache[resolved] = rows
        expected_by_day: dict[date, list[datetime]] = {}
        for value in expected:
            expected_by_day.setdefault(value.astimezone(SHANGHAI).date(), []).append(value)
        needed_days = set(expected_by_day)
        expected_set = set(expected)
        bars: dict[datetime, CanonicalBar] = {}
        for index, row in enumerate(rows):
            trading_day = _day(row.get("trading_day", row.get("trading_date", row.get("date"))))
            if needed_days and trading_day not in needed_days:
                continue
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
            if expected_set and bar_end not in expected_set:
                continue
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
        return tuple(bars[value] for value in sorted(bars) if value in expected_set or not expected_set)


class ExactScopeProvider:
    """Allow Gate A provider reads only inside the digest-bound dry-run windows."""

    def __init__(self, delegate: Any, exact_scope: Mapping[str, Any]) -> None:
        self.delegate = delegate
        self._windows: dict[DatasetKey, list[tuple[int, date, date]]] = defaultdict(list)
        raw_windows = exact_scope.get("rqdata_windows")
        if not isinstance(raw_windows, list):
            raise LegacyBootstrapError("GATE_A_PROVIDER_SCOPE_INVALID")
        for index, item in enumerate(raw_windows):
            try:
                identity = item["dataset"]
                key = DatasetKey(*identity)
                start = date.fromisoformat(item["start"])
                end = date.fromisoformat(item["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise LegacyBootstrapError("GATE_A_PROVIDER_SCOPE_INVALID") from exc
            if key.frequency not in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}:
                raise LegacyBootstrapError("GATE_A_PROVIDER_SCOPE_INVALID")
            if start > end:
                raise LegacyBootstrapError("GATE_A_PROVIDER_SCOPE_INVALID")
            self._windows[key].append((index, start, end))
        self._used: set[int] = set()
        self.request_count = 0
        self.fallback_request_count = 0

    @property
    def planned_window_count(self) -> int:
        return sum(len(values) for values in self._windows.values())

    @property
    def unused_window_count(self) -> int:
        return self.planned_window_count - len(self._used)

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        groups: dict[int, list[datetime]] = defaultdict(list)
        unscoped: list[datetime] = []
        bounds = {index: (start, end) for index, start, end in self._windows.get(key, ())}
        for value in expected:
            local_value = value.astimezone(SHANGHAI)
            local_day = local_value.date()
            windows = self._windows.get(key, ())
            day_matches = [
                index for index, start, end in windows if start <= local_day <= end
            ]
            if len(day_matches) == 1:
                groups[day_matches[0]].append(value)
                continue
            if (
                not day_matches
                and key.frequency is BarFrequency.M1
                and local_value.time() >= time(18)
            ):
                # Night sessions may open up to ~3 calendar days before the
                # trading day (Friday night -> Monday). Prefer the nearest
                # following window start when multiple candidates exist.
                night_matches = [
                    (index, start)
                    for index, start, end in windows
                    if start.toordinal() - 4
                    <= local_day.toordinal()
                    < start.toordinal()
                ]
                if night_matches:
                    matched = min(night_matches, key=lambda item: item[1])[0]
                    groups[matched].append(value)
                    continue
            # Day-level exact-scope can mark legacy months as fully covered while
            # minute bars remain incomplete; refill leftovers via RQData.
            unscoped.append(value)
        bars: dict[datetime, CanonicalBar] = {}
        digests: list[str] = []
        for index in sorted(groups, key=lambda value: bounds[value]):
            batch = self.delegate.fetch(key, tuple(groups[index]))
            self.request_count += 1
            self._used.add(index)
            digests.append(batch.source_digest)
            for bar in batch.bars:
                previous = bars.get(bar.bar_end)
                if previous is not None and previous != bar:
                    raise LegacyBootstrapError("GATE_A_PROVIDER_DUPLICATE_CONFLICT")
                bars[bar.bar_end] = bar
        if unscoped:
            batch = self.delegate.fetch(key, tuple(unscoped))
            self.request_count += 1
            self.fallback_request_count += 1
            digests.append(batch.source_digest)
            for bar in batch.bars:
                previous = bars.get(bar.bar_end)
                if previous is not None and previous != bar:
                    raise LegacyBootstrapError("GATE_A_PROVIDER_DUPLICATE_CONFLICT")
                bars[bar.bar_end] = bar
        digest = hashlib.sha256(
            json.dumps(sorted(digests), separators=(",", ":")).encode()
        ).hexdigest()
        return BarBatch(tuple(bars[value] for value in sorted(bars) if value in bars), digest, "rqdata")


def _selected_candidates(
    exact_scope: Mapping[str, Any],
) -> dict[tuple[str, str, str, str, int, int], Path]:
    raw = exact_scope.get("legacy_selected_month_targets")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise LegacyBootstrapError("GATE_A_LEGACY_SCOPE_INVALID")
    result: dict[tuple[str, str, str, str, int, int], Path] = {}
    for item in raw:
        try:
            key = DatasetKey(*item["dataset"])
            identity = (*key.as_tuple(), int(item["year"]), int(item["month"]))
            path = Path(item["path"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LegacyBootstrapError("GATE_A_LEGACY_SCOPE_INVALID") from exc
        if identity in result and result[identity] != path:
            raise LegacyBootstrapError("GATE_A_LEGACY_SCOPE_CONFLICT")
        result[identity] = path
    return result


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
        mapped_contract = fact.contract.strip().upper()
        previous = map_by_day.get(identity)
        if previous is not None and previous != mapped_contract:
            raise LegacyBootstrapError("GATE_A_MAIN_MAP_CONFLICT")
        map_by_day[identity] = mapped_contract

    desired: dict[DatasetKey, set[date]] = defaultdict(set)
    for symbol in normalized_products:
        start = starts[symbol]
        all_days = days_by_product[symbol]
        daily_days = tuple(day for day in all_days if start <= day <= through)
        minute_start = max(start, RQDATA_INTRADAY_HISTORY_START)
        minute_days = tuple(day for day in all_days if minute_start <= day <= through)
        week_ends = _complete_week_ends(all_days, start=start, through=through)
        for frequency, direct_values in (
            (BarFrequency.M1, minute_days),
            (BarFrequency.D1, daily_days),
            (BarFrequency.W1, week_ends),
        ):
            desired[DatasetKey(DatasetKind.CONTINUOUS, symbol, "MAIN", frequency)].update(
                direct_values
            )
        for day in daily_days:
            daily_contract = map_by_day.get((symbol, day))
            if daily_contract is None:
                continue
            desired[
                DatasetKey(DatasetKind.CONTRACT, symbol, daily_contract, BarFrequency.D1)
            ].add(day)
            if day >= minute_start:
                desired[
                    DatasetKey(DatasetKind.CONTRACT, symbol, daily_contract, BarFrequency.M1)
                ].add(day)
        for day in week_ends:
            weekly_contract = map_by_day.get((symbol, day))
            if weekly_contract is not None:
                desired[
                    DatasetKey(DatasetKind.CONTRACT, symbol, weekly_contract, BarFrequency.W1)
                ].add(day)

    month_targets: list[tuple[DatasetKey, int, int, tuple[date, ...]]] = []
    for key, desired_days in desired.items():
        by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
        for day in desired_days:
            by_month[(day.year, day.month)].append(day)
        for (year, month), collected_days in by_month.items():
            month_targets.append((key, year, month, tuple(sorted(collected_days))))
    month_targets.sort(key=lambda item: (*item[0].as_tuple(), item[1], item[2]))

    selected: list[dict[str, Any]] = []
    provider_windows: list[dict[str, Any]] = []
    fully_covered = 0
    for key, year, month, month_days in month_targets:
        desired_set = set(month_days)
        ranked: list[tuple[int, str, Path, set[date]]] = []
        for path, covered_days in legacy_coverages.get(key, ()):
            candidate_covered = {
                day
                for day in covered_days
                if day.year == year and day.month == month and day in desired_set
            }
            if candidate_covered:
                ranked.append(
                    (
                        len(candidate_covered),
                        path.resolve().as_posix(),
                        path.resolve(),
                        candidate_covered,
                    )
                )
        chosen_path: Path | None = None
        selected_covered: set[date] = set()
        if ranked:
            _, _, chosen_path, selected_covered = sorted(
                ranked, key=lambda item: (-item[0], item[1])
            )[0]
            selected.append(
                {
                    "dataset": list(key.as_tuple()),
                    "year": year,
                    "month": month,
                    "path": chosen_path.as_posix(),
                    "covered_trading_days": len(selected_covered),
                    "desired_trading_days": len(month_days),
                }
            )
        missing = tuple(day for day in month_days if day not in selected_covered)
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
        raw_frequency = values.get("frequency", "")
        if symbol not in products or raw_frequency not in {"1m", "1d", "1w"}:
            return None
        if root_index == 0:
            contract = values.get("contract", "").upper()
            if not contract:
                return None
            return DatasetKey(
                DatasetKind.CONTRACT,
                symbol,
                contract,
                BarFrequency(raw_frequency),
            )
        return DatasetKey(
            DatasetKind.CONTINUOUS,
            symbol,
            "MAIN",
            BarFrequency(raw_frequency),
        )

    def value_after(name: str) -> str | None:
        try:
            return parts[parts.index(name) + 1]
        except (ValueError, IndexError):
            return None

    kind = value_after("dataset_kind")
    symbol = (value_after("symbol") or "").lower()
    series = value_after("contract_or_series")
    canonical_frequency = value_after("frequency")
    if (
        kind not in {"actual_dominant", "continuous"}
        or symbol not in products
        or series is None
        or canonical_frequency not in {"1m", "1d", "1w"}
    ):
        return None
    if kind == "continuous":
        return DatasetKey(
            DatasetKind.CONTINUOUS,
            symbol,
            "MAIN",
            BarFrequency(canonical_frequency),
        )
    return DatasetKey(
        DatasetKind.CONTRACT,
        symbol,
        series,
        BarFrequency(canonical_frequency),
    )


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
