from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.market_data.newow.futures_evidence_discovery import (
    DiscoveryRequest,
    ReadOnlyDiscoveryError,
    assert_manifest_covers_actual_reads,
    catalog_paths_for_candidates,
    canonical_file_manifest,
    build_discovery_result,
    discover_coverage_candidates,
    validate_candidate_market_data,
    validate_canonical_read_window,
    read_only_session,
    run_discovery_with_dependencies,
    only_approved_report_paths,
    write_discovery_artifacts,
    validate_discovery_request,
    validate_select_only_privileges,
    calendar_proven_natural_year_folds,
)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


class _Session:
    def __init__(self, *, read_only: object = "on", dirty: bool = False) -> None:
        self.read_only = read_only
        self.new = set()
        self.dirty = {object()} if dirty else set()
        self.deleted = set()
        self.statements: list[str] = []
        self.rolled_back = False
        self.closed = False

    def execute(self, statement: object) -> _ScalarResult:
        self.statements.append(str(statement))
        return _ScalarResult(self.read_only)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _request(output_dir: Path) -> DiscoveryRequest:
    return DiscoveryRequest(
        base_sha="a" * 40,
        owner_approved_run_id="run-001",
        frequencies=("1d", "1w", "60m"),
        minimum_rollovers=2,
        output_dir=output_dir,
    )


def test_rejects_discovery_request_when_base_is_not_exact(tmp_path: Path) -> None:
    request = _request(tmp_path / "reports" / "run-001")

    with pytest.raises(ReadOnlyDiscoveryError, match="BASE_SHA_DRIFT"):
        validate_discovery_request(
            request,
            expected_base_sha="b" * 40,
            report_root=tmp_path / "reports",
            canonical_root=tmp_path / "canonical",
        )


def test_rejects_discovery_output_inside_canonical_root(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    request = _request(canonical_root / "reports" / "run-001")

    with pytest.raises(ReadOnlyDiscoveryError, match="EVIDENCE_OUTPUT_PATH_INVALID"):
        validate_discovery_request(
            request,
            expected_base_sha="a" * 40,
            report_root=tmp_path / "reports",
            canonical_root=canonical_root,
        )


def test_rejects_discovery_output_that_does_not_match_owner_run_id(tmp_path: Path) -> None:
    request = _request(tmp_path / "reports" / "different-run")

    with pytest.raises(ReadOnlyDiscoveryError, match="EVIDENCE_OUTPUT_PATH_INVALID"):
        validate_discovery_request(
            request,
            expected_base_sha="a" * 40,
            report_root=tmp_path / "reports",
            canonical_root=tmp_path / "canonical",
        )


def test_rejects_frequency_or_rollover_mutation(tmp_path: Path) -> None:
    request = DiscoveryRequest(
        base_sha="a" * 40,
        owner_approved_run_id="run-001",
        frequencies=("1d", "60m", "1w"),
        minimum_rollovers=1,
        output_dir=tmp_path / "reports" / "run-001",
    )

    with pytest.raises(ReadOnlyDiscoveryError, match="DISCOVERY_PARAMETERS_INVALID"):
        validate_discovery_request(
            request,
            expected_base_sha="a" * 40,
            report_root=tmp_path / "reports",
            canonical_root=tmp_path / "canonical",
        )


def test_read_only_session_sets_guard_and_always_rolls_back() -> None:
    session = _Session()

    with read_only_session(lambda: session) as actual:
        assert actual is session

    assert "SET TRANSACTION READ ONLY" in session.statements[0]
    assert "SHOW transaction_read_only" in session.statements[1]
    assert session.rolled_back
    assert session.closed


def test_read_only_session_rejects_mutable_or_dirty_session() -> None:
    session = _Session(read_only="off", dirty=True)

    with pytest.raises(ReadOnlyDiscoveryError, match="READ_ONLY_SESSION_INVALID"):
        with read_only_session(lambda: session):
            pass

    assert session.rolled_back
    assert session.closed


def test_select_only_privilege_gate_requires_exact_allowed_tables() -> None:
    allowed = {
        table: {"SELECT"}
        for table in (
            "contracts",
            "instruments",
            "trading_calendars",
            "trading_sessions",
            "main_contract_map",
            "market_datasets",
            "market_partitions",
        )
    }

    validate_select_only_privileges(allowed)

    allowed["contracts"] = {"SELECT", "UPDATE"}
    with pytest.raises(ReadOnlyDiscoveryError, match="READ_ONLY_ROLE_INVALID"):
        validate_select_only_privileges(allowed)

    allowed["contracts"] = {"SELECT", "TRUNCATE"}
    with pytest.raises(ReadOnlyDiscoveryError, match="READ_ONLY_ROLE_INVALID"):
        validate_select_only_privileges(allowed)


def test_canonical_manifest_hashes_only_catalog_resolved_files(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    file_path = canonical_root / "kind=contract" / "part.parquet"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"canonical-bytes")

    manifest = canonical_file_manifest((file_path,), canonical_root=canonical_root)

    assert manifest[0].relative_path == "kind=contract/part.parquet"
    assert manifest[0].sha256 == "77b08d303821794feed7d5c213090d47b4e46165dabb86f4cb9dbfc1d6d1d66a"

    with pytest.raises(ReadOnlyDiscoveryError, match="CANONICAL_PATH_INVALID"):
        canonical_file_manifest((tmp_path / "outside.parquet",), canonical_root=canonical_root)


def test_canonical_manifest_rejects_catalog_path_that_is_a_symlink(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"outside")
    linked = canonical_root / "linked.parquet"
    linked.symlink_to(outside)

    with pytest.raises(ReadOnlyDiscoveryError, match="CANONICAL_PATH_INVALID"):
        canonical_file_manifest((linked,), canonical_root=canonical_root)


def test_canonical_manifest_rejects_an_internal_symlink(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    target = canonical_root / "target.parquet"
    target.write_bytes(b"canonical")
    linked = canonical_root / "linked.parquet"
    linked.symlink_to(target)

    with pytest.raises(ReadOnlyDiscoveryError, match="CANONICAL_PATH_INVALID"):
        canonical_file_manifest((linked,), canonical_root=canonical_root)


class _Catalog:
    def __init__(self, maps: dict[str, tuple[object, ...]], partitions: dict[tuple[str, str, str], tuple[object, ...]]) -> None:
        self._maps = maps
        self._partitions = partitions
        self.requested_keys: list[object] = []

    def main_map_before(self, product: str, _before: object) -> tuple[object, ...]:
        return self._maps[product]

    def all_partitions(self, key: object) -> tuple[object, ...]:
        self.requested_keys.append(key)
        return self._partitions.get(
            (key.symbol, key.series_or_contract, key.frequency.value),
            (),
        )

    def calendar_days(
        self,
        _product: str,
        start: date,
        end: date,
    ) -> tuple[tuple[date, bool], ...]:
        return tuple(
            (start + timedelta(days=offset), True)
            for offset in range((end - start).days + 1)
        )


def _map(product: str) -> tuple[object, ...]:
    return tuple(
        SimpleNamespace(symbol=product, trade_date=day, contract=contract)
        for day, contract in (
            (date(2024, 1, 2), f"{product.upper()}2401"),
            (date(2024, 3, 1), f"{product.upper()}2405"),
            (date(2024, 5, 2), f"{product.upper()}2409"),
        )
    )


def _partition() -> object:
    return SimpleNamespace(
        coverage_start=datetime(2024, 1, 1, tzinfo=UTC),
        coverage_end=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _long_partition() -> object:
    return SimpleNamespace(
        coverage_start=datetime(2020, 1, 1, tzinfo=UTC),
        coverage_end=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _long_map(product: str) -> tuple[object, ...]:
    return tuple(
        SimpleNamespace(symbol=product, trade_date=day, contract=contract)
        for day, contract in (
            (date(2020, 1, 2), f"{product.upper()}2005"),
            (date(2021, 5, 4), f"{product.upper()}2109"),
            (date(2022, 9, 1), f"{product.upper()}2301"),
            (date(2023, 12, 1), f"{product.upper()}2405"),
            (date(2024, 12, 31), f"{product.upper()}2501"),
        )
    )


def _late_utc_partition() -> object:
    return SimpleNamespace(
        coverage_start=datetime(2024, 1, 1, 16, tzinfo=UTC),
        coverage_end=datetime(2024, 6, 1, tzinfo=UTC),
    )


def test_discovers_only_mapped_contracts_with_all_frozen_frequencies() -> None:
    products = ("j", "ma", "a")
    maps = {product: _map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    catalog = _Catalog(maps, partitions)
    taxonomy = {
        "j": SimpleNamespace(sector="black"),
        "ma": SimpleNamespace(sector="chemical"),
        "a": SimpleNamespace(sector="agriculture"),
    }

    candidates = discover_coverage_candidates(
        catalog,
        operational_products=products,
        taxonomy=taxonomy,
    )

    assert tuple(candidate.product for candidate in candidates) == products
    assert all(candidate.rollover_count == 2 for candidate in candidates)
    assert all(candidate.frequencies == ("1d", "1w", "60m") for candidate in candidates)
    assert {
        (key.symbol, key.series_or_contract, key.frequency.value)
        for key in catalog.requested_keys
    } == set(partitions)


def test_calendar_proven_folds_require_complete_years_for_every_selected_product() -> None:
    selected = (
        SimpleNamespace(product="j", common_since=date(2020, 6, 1), common_through=date(2024, 8, 31)),
        SimpleNamespace(product="ma", common_since=date(2020, 7, 1), common_through=date(2024, 7, 31)),
        SimpleNamespace(product="a", common_since=date(2020, 8, 1), common_through=date(2024, 6, 30)),
    )
    catalog = _Catalog({}, {})

    folds = calendar_proven_natural_year_folds(catalog, selected)

    assert tuple(fold.name for fold in folds) == ("test-2022", "test-2023")
    assert folds[0].train_since == date(2020, 8, 1)


def test_calendar_proven_folds_fail_when_any_exchange_calendar_has_a_gap() -> None:
    selected = (
        SimpleNamespace(product="j", common_since=date(2020, 1, 1), common_through=date(2023, 12, 31)),
        SimpleNamespace(product="ma", common_since=date(2020, 1, 1), common_through=date(2023, 12, 31)),
        SimpleNamespace(product="a", common_since=date(2020, 1, 1), common_through=date(2023, 12, 31)),
    )

    class _GappedCalendarCatalog(_Catalog):
        def calendar_days(
            self,
            product: str,
            start: date,
            end: date,
        ) -> tuple[tuple[date, bool], ...]:
            values = list(super().calendar_days(product, start, end))
            if product == "ma":
                values.pop(10)
            return tuple(values)

    with pytest.raises(ReadOnlyDiscoveryError, match="NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED"):
        calendar_proven_natural_year_folds(_GappedCalendarCatalog({}, {}), selected)


def test_discovery_result_freezes_common_calendar_proven_folds() -> None:
    products = ("j", "ma", "a")
    maps = {product: _long_map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_long_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }

    result = build_discovery_result(
        _Catalog(maps, partitions),
        _long_market_data(),
        operational_products=products,
        taxonomy={
            "j": SimpleNamespace(sector="black"),
            "ma": SimpleNamespace(sector="chemical"),
            "a": SimpleNamespace(sector="agriculture"),
        },
    )

    assert result.common_since == date(2020, 1, 2)
    assert result.common_through == date(2024, 12, 31)
    assert result.complete_years == (2021, 2022, 2023, 2024)
    assert tuple(fold.name for fold in result.folds) == ("test-2022", "test-2023", "test-2024")


def test_excludes_a_product_when_one_mapped_contract_frequency_is_missing() -> None:
    maps = {"j": _map("j")}
    partitions = {
        ("j", row.contract, frequency): (_partition(),)
        for row in maps["j"]
        for frequency in ("1d", "1w", "60m")
        if not (row.contract == "J2405" and frequency == "1w")
    }

    candidates = discover_coverage_candidates(
        _Catalog(maps, partitions),
        operational_products=("j",),
        taxonomy={"j": SimpleNamespace(sector="black")},
    )

    assert candidates == ()


def test_excludes_utc_previous_day_coverage_for_the_prior_shanghai_trading_day() -> None:
    maps = {"j": _map("j")}
    partitions = {
        ("j", row.contract, frequency): (_late_utc_partition(),)
        for row in maps["j"]
        for frequency in ("1d", "1w", "60m")
    }
    maps["j"] = (
        SimpleNamespace(symbol="j", trade_date=date(2024, 1, 1), contract="J2401"),
        *maps["j"][1:],
    )

    candidates = discover_coverage_candidates(
        _Catalog(maps, partitions),
        operational_products=("j",),
        taxonomy={"j": SimpleNamespace(sector="black")},
    )

    assert candidates == ()


def test_uses_longest_complete_coverage_run_instead_of_requiring_all_history() -> None:
    maps = {
        "j": (
            SimpleNamespace(symbol="j", trade_date=date(2024, 1, 2), contract="J2401"),
            SimpleNamespace(symbol="j", trade_date=date(2024, 3, 1), contract="J2405"),
            SimpleNamespace(symbol="j", trade_date=date(2024, 5, 2), contract="J2409"),
            SimpleNamespace(symbol="j", trade_date=date(2024, 7, 1), contract="J2411"),
        )
    }
    partitions = {
        (
            "j",
            row.contract,
            frequency,
        ): (
            SimpleNamespace(
                coverage_start=datetime(2024, 1, 1, tzinfo=UTC),
                coverage_end=datetime(2024, 8, 1, tzinfo=UTC),
            ),
        )
        for row in maps["j"][1:]
        for frequency in ("1d", "1w", "60m")
    }

    candidates = discover_coverage_candidates(
        _Catalog(maps, partitions),
        operational_products=("j",),
        taxonomy={"j": SimpleNamespace(sector="black")},
    )

    assert candidates[0].common_since == date(2024, 3, 1)
    assert candidates[0].common_through == date(2024, 7, 1)
    assert candidates[0].rollover_count == 2


def test_runner_help_is_available_without_opening_a_database_session() -> None:
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "scripts/newow_page_v2_futures_evidence.py", "--help"],
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": f"{root / 'services/quant-api'}:{root / 'packages/quant-core'}",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "discover" in result.stdout


class _MarketData:
    def __init__(
        self,
        *,
        missing_frequency: str | None = None,
        wrong_identity: bool = False,
    ) -> None:
        self.missing_frequency = missing_frequency
        self.wrong_identity = wrong_identity
        self.requests: list[object] = []
        self.segments = (
            SimpleNamespace(
                contract="J2401",
                start_trading_day=date(2024, 1, 2),
                end_trading_day=date(2024, 2, 29),
            ),
            SimpleNamespace(
                contract="J2405",
                start_trading_day=date(2024, 3, 1),
                end_trading_day=date(2024, 5, 1),
            ),
            SimpleNamespace(
                contract="J2409",
                start_trading_day=date(2024, 5, 2),
                end_trading_day=date(2024, 5, 2),
            ),
        )

    def actual_dominant_segments(
        self, _product: str, _since: date, _through: date
    ) -> tuple[object, ...]:
        return self.segments

    def query_actual_dominant_trading_days(self, request: object) -> object:
        self.requests.append(request)
        bars = (
            ()
            if request.frequency.value == self.missing_frequency
            else (
                SimpleNamespace(
                    trading_day=date(2024, 1, 2),
                    bar_end=datetime(2024, 1, 2, tzinfo=UTC),
                ),
                SimpleNamespace(
                    trading_day=date(2024, 5, 2),
                    bar_end=datetime(2024, 5, 2, tzinfo=UTC),
                ),
            )
        )
        return SimpleNamespace(
            request_identity={
                "series_kind": "continuous" if self.wrong_identity else "actual_dominant",
                "symbol": request.symbol,
                "contract": None,
                "frequency": request.frequency.value,
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2024-06-01T00:00:00+00:00",
            },
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=self.segments,
            requested_trading_day_window=(request.since, request.through),
        )


def _long_market_data() -> _MarketData:
    class _LongMarketData(_MarketData):
        def __init__(self) -> None:
            super().__init__()
            self.segments = (
                SimpleNamespace(contract="J2005", start_trading_day=date(2020, 1, 2), end_trading_day=date(2021, 5, 3)),
                SimpleNamespace(contract="J2109", start_trading_day=date(2021, 5, 4), end_trading_day=date(2022, 8, 31)),
                SimpleNamespace(contract="J2301", start_trading_day=date(2022, 9, 1), end_trading_day=date(2023, 11, 30)),
                SimpleNamespace(contract="J2405", start_trading_day=date(2023, 12, 1), end_trading_day=date(2024, 12, 30)),
                SimpleNamespace(contract="J2501", start_trading_day=date(2024, 12, 31), end_trading_day=date(2024, 12, 31)),
            )

        def query_actual_dominant_trading_days(self, request: object) -> object:
            self.requests.append(request)
            bars = (
                SimpleNamespace(trading_day=date(2020, 1, 2), bar_end=datetime(2020, 1, 2, tzinfo=UTC)),
                SimpleNamespace(trading_day=date(2024, 12, 31), bar_end=datetime(2024, 12, 31, tzinfo=UTC)),
            )
            return SimpleNamespace(
                request_identity={
                    "series_kind": "actual_dominant",
                    "symbol": request.symbol,
                    "contract": None,
                    "frequency": request.frequency.value,
                    "start": "2020-01-01T00:00:00+00:00",
                    "end": "2025-01-01T00:00:00+00:00",
                },
                bars=bars,
                coverage=(bars[0].bar_end, bars[-1].bar_end),
                resolved_contract_segments=self.segments,
                requested_trading_day_window=(request.since, request.through),
            )

    return _LongMarketData()


def test_candidate_validation_reads_each_frozen_frequency_and_uses_authoritative_rolls() -> None:
    candidate = _candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )
    market_data = _MarketData()

    validate_candidate_market_data(market_data, candidate)

    assert tuple(request.frequency.value for request in market_data.requests) == (
        "1d",
        "1w",
        "60m",
    )


def test_candidate_validation_rejects_missing_actual_dominant_bars() -> None:
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )

    with pytest.raises(ReadOnlyDiscoveryError, match="ACTUAL_DOMINANT_COVERAGE_INVALID"):
        validate_candidate_market_data(_MarketData(missing_frequency="1w"), candidate)


def test_candidate_validation_rejects_wrong_actual_dominant_identity() -> None:
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )

    with pytest.raises(ReadOnlyDiscoveryError, match="ACTUAL_DOMINANT_COVERAGE_INVALID"):
        validate_candidate_market_data(_MarketData(wrong_identity=True), candidate)


def test_candidate_validation_accepts_clipped_weekly_segment_subset() -> None:
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )

    class _ClippedWeeklyMarketData(_MarketData):
        def query_actual_dominant_trading_days(self, request: object) -> object:
            result = super().query_actual_dominant_trading_days(request)
            if request.frequency.value != "1w":
                return result
            weekly_bar = SimpleNamespace(
                trading_day=date(2024, 5, 2),
                bar_end=datetime(2024, 5, 2, tzinfo=UTC),
            )
            return SimpleNamespace(
                request_identity=result.request_identity,
                bars=(weekly_bar,),
                coverage=(weekly_bar.bar_end, weekly_bar.bar_end),
                resolved_contract_segments=(
                    SimpleNamespace(
                        contract="J2409",
                        start_trading_day=date(2024, 5, 2),
                        end_trading_day=date(2024, 5, 2),
                    ),
                ),
                requested_trading_day_window=result.requested_trading_day_window,
            )

    validate_candidate_market_data(_ClippedWeeklyMarketData(), candidate)


def test_candidate_validation_rejects_daily_omitted_middle_segment() -> None:
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )

    class _OmittedDailyMarketData(_MarketData):
        def query_actual_dominant_trading_days(self, request: object) -> object:
            result = super().query_actual_dominant_trading_days(request)
            if request.frequency.value != "1d":
                return result
            return SimpleNamespace(
                request_identity=result.request_identity,
                bars=result.bars,
                coverage=result.coverage,
                resolved_contract_segments=(self.segments[0], self.segments[2]),
                requested_trading_day_window=result.requested_trading_day_window,
            )

    with pytest.raises(ReadOnlyDiscoveryError, match="ACTUAL_DOMINANT_COVERAGE_INVALID"):
        validate_candidate_market_data(_OmittedDailyMarketData(), candidate)


def test_failed_read_still_hashes_after_and_fails_closed_on_canonical_drift(
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    partition_path = canonical_root / "partition.parquet"
    partition_path.parent.mkdir(parents=True)
    partition_path.write_bytes(b"before")
    partition = SimpleNamespace(file_path=partition_path)
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
        rollover_count=2,
    )

    class _MutatingFailureStore:
        def read_catalog_partition(self, _partition: object) -> object:
            partition_path.write_bytes(b"after")
            raise RuntimeError("simulated read failure")

    class _ReadFailureMarketData(_MarketData):
        def __init__(self) -> None:
            super().__init__()
            self.store = _MutatingFailureStore()

        def query_actual_dominant_trading_days(self, request: object) -> object:
            self.store.read_catalog_partition(partition)
            raise AssertionError("unreachable")

    with pytest.raises(ReadOnlyDiscoveryError, match="CANONICAL_MANIFEST_DRIFT"):
        validate_canonical_read_window(
            _ReadFailureMarketData(),
            (candidate,),
            paths=(partition_path,),
            canonical_root=canonical_root,
        )


def test_manifest_scope_includes_all_catalog_partitions_for_mapped_contracts(
    tmp_path: Path,
) -> None:
    maps = {"j": _map("j")}
    partitions = {
        ("j", row.contract, frequency): (
            SimpleNamespace(
                coverage_start=datetime(2024, 1, 1, tzinfo=UTC),
                coverage_end=datetime(2024, 6, 1, tzinfo=UTC),
                file_path=tmp_path / f"{row.contract}-{frequency}-warmup.parquet",
            ),
            SimpleNamespace(
                coverage_start=datetime(2024, 1, 1, tzinfo=UTC),
                coverage_end=datetime(2024, 6, 1, tzinfo=UTC),
                file_path=tmp_path / f"{row.contract}-{frequency}-owner.parquet",
            ),
        )
        for row in maps["j"]
        for frequency in ("1d", "1w", "60m")
    }
    candidate = SimpleNamespace(
        product="j",
        common_since=date(2024, 1, 2),
        common_through=date(2024, 5, 2),
    )

    paths = catalog_paths_for_candidates(_Catalog(maps, partitions), (candidate,))

    assert len(paths) == 18
    assert any(path.name.endswith("warmup.parquet") for path in paths)


def test_manifest_scope_rejects_an_actual_read_outside_the_prehashed_scope(
    tmp_path: Path,
) -> None:
    prehashed = tmp_path / "prehashed.parquet"
    omitted = tmp_path / "omitted-prefix.parquet"

    with pytest.raises(ReadOnlyDiscoveryError, match="CANONICAL_MANIFEST_SCOPE_INVALID"):
        assert_manifest_covers_actual_reads((prehashed,), {prehashed, omitted})


def test_only_approved_report_paths_rejects_sibling_run_directory() -> None:
    assert only_approved_report_paths(
        ("?? data/reports/newow/run-001/",),
        "data/reports/newow/run-001",
    )
    assert not only_approved_report_paths(
        ("?? data/reports/newow/run-001-extra/",),
        "data/reports/newow/run-001",
    )


def test_discovery_result_selects_frozen_sector_candidates_before_any_strategy_work() -> None:
    products = ("j", "ma", "a")
    maps = {product: _long_map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_long_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    result = build_discovery_result(
        _Catalog(maps, partitions),
        _long_market_data(),
        operational_products=products,
        taxonomy={
            "j": SimpleNamespace(sector="black"),
            "ma": SimpleNamespace(sector="chemical"),
            "a": SimpleNamespace(sector="agriculture"),
        },
    )

    assert tuple(candidate.product for candidate in result.selected) == products
    assert tuple(candidate.product for candidate in result.candidates) == products


def test_dependency_runner_validates_read_only_session_before_catalog_discovery(
    tmp_path: Path,
) -> None:
    products = ("j", "ma", "a")
    maps = {product: _long_map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_long_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    session = _Session()
    result = run_discovery_with_dependencies(
        _request(tmp_path / "reports" / "run-001"),
        expected_base_sha="a" * 40,
        report_root=tmp_path / "reports",
        canonical_root=tmp_path / "canonical",
        session_factory=lambda: session,
        table_privileges={
            table: {"SELECT"}
            for table in (
                "contracts",
                "instruments",
                "trading_calendars",
                "trading_sessions",
                "main_contract_map",
                "market_datasets",
                "market_partitions",
            )
        },
        catalog_factory=lambda _session: _Catalog(maps, partitions),
        market_data_factory=lambda catalog: _long_market_data(),
        operational_products=products,
        taxonomy={
            "j": SimpleNamespace(sector="black"),
            "ma": SimpleNamespace(sector="chemical"),
            "a": SimpleNamespace(sector="agriculture"),
        },
    )

    assert tuple(candidate.product for candidate in result.selected) == products
    assert session.rolled_back
    assert session.closed
    assert not (tmp_path / "reports" / "run-001").exists()


def test_discovery_artifacts_are_limited_to_the_approved_run_directory(tmp_path: Path) -> None:
    products = ("j", "ma", "a")
    maps = {product: _long_map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_long_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    result = build_discovery_result(
        _Catalog(maps, partitions),
        _long_market_data(),
        operational_products=products,
        taxonomy={
            "j": SimpleNamespace(sector="black"),
            "ma": SimpleNamespace(sector="chemical"),
            "a": SimpleNamespace(sector="agriculture"),
        },
    )
    output = tmp_path / "reports" / "run-001"

    write_discovery_artifacts(output, result, canonical_manifest=())

    assert {path.name for path in output.iterdir()} == {
        "selection.json",
        "folds.json",
        "coverage.csv",
        "input_hashes.json",
        "zero_write_proof.json",
    }
    selection = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert selection["selected_products"] == ["j", "ma", "a"]
    folds = json.loads((output / "folds.json").read_text(encoding="utf-8"))
    assert folds["complete_years"] == [2021, 2022, 2023, 2024]
