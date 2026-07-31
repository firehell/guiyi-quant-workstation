from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.data_core.catalog import CatalogError, PartitionManifest
from app.data_core.contracts import (
    BarFrequency,
    ContractValidationError,
    DataGapError,
    DatasetKey,
    DatasetKind,
)
from app.data_core.historical_sync import (
    HistoricalSynchronizer,
    CanonicalBatchPublisher,
    execute_with_retries,
    plan_missing_windows,
)
from app.data_core.rqdata_adapter import TradingSessionCoverage
from app.data_core.rqdata_adapter import MainMapRequest, MainMapRow


def _dataset() -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def test_plan_missing_windows_subtracts_catalog_coverage_as_half_open_intervals() -> None:
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 10, tzinfo=UTC)

    windows = plan_missing_windows(
        dataset=_dataset(),
        start=start,
        end=end,
        covered_windows=(
            (datetime(2026, 7, 1, 1, 2, tzinfo=UTC), datetime(2026, 7, 1, 1, 4, tzinfo=UTC)),
            (datetime(2026, 7, 1, 1, 6, tzinfo=UTC), datetime(2026, 7, 1, 1, 8, tzinfo=UTC)),
        ),
    )

    assert windows == (
        (start, datetime(2026, 7, 1, 1, 2, tzinfo=UTC)),
        (datetime(2026, 7, 1, 1, 4, tzinfo=UTC), datetime(2026, 7, 1, 1, 6, tzinfo=UTC)),
        (datetime(2026, 7, 1, 1, 8, tzinfo=UTC), end),
    )


def test_execute_with_retries_allows_one_initial_attempt_and_three_retries() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise TimeoutError("provider unavailable")
        return "published"

    assert execute_with_retries(operation) == "published"
    assert attempts == 4


def test_execute_with_retries_does_not_retry_unclassified_provider_or_quality_failure() -> None:
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("deterministic provider shape failure")

    with pytest.raises(RuntimeError, match="deterministic provider shape failure"):
        execute_with_retries(operation)

    assert attempts == 1


def test_synchronizer_dry_run_plans_missing_windows_without_provider_or_catalog_writes() -> None:
    calls: list[str] = []

    class Catalog:
        def list_partitions(self, _dataset: DatasetKey) -> tuple[object, ...]:
            return ()

        def record_gap(self, *_args: object) -> None:
            calls.append("gap")

        def clear_gaps_covered_by(self, *_args: object, **_kwargs: object) -> int:
            calls.append("clear")
            return 0

    class Adapter:
        def fetch_bars(self, _request: object) -> object:
            calls.append("fetch")
            raise AssertionError("dry-run must not fetch")

    synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=lambda _dataset, _start, _end: (),
        publish_batch=lambda _batch: (_ for _ in ()).throw(
            AssertionError("dry-run must not publish")
        ),
    )
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 10, tzinfo=UTC)

    result = synchronizer.sync(
        dataset=_dataset(),
        start=start,
        end=end,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.planned_windows == ((start, end),)
    assert result.published_windows == ()
    assert result.gap_windows == ()
    assert calls == []


def test_synchronizer_publishes_each_missing_window_then_clears_only_covered_gaps() -> None:
    calls: list[object] = []
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 10, tzinfo=UTC)

    class Catalog:
        def list_partitions(self, _dataset: DatasetKey) -> tuple[object, ...]:
            return ()

        def record_gap(self, *_args: object) -> None:
            calls.append("gap")

        def clear_gaps_covered_by(self, _dataset: DatasetKey, **kwargs: object) -> int:
            calls.append(("clear", kwargs))
            return 1

    class Adapter:
        def fetch_bars(self, request: object) -> object:
            calls.append(("fetch", request))
            return object()

    def session_provider(
        _dataset: DatasetKey,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[TradingSessionCoverage, ...]:
        return (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=window_start,
                end=window_end,
                expected_bar_ends=(window_end,),
            ),
        )

    def publish_batch(_batch: object) -> PartitionManifest:
        calls.append("publish")
        return PartitionManifest(
            coverage_start=start,
            coverage_end=end,
            manifest_version="canonical-manifest-v1",
            manifest_uri="manifests/jm.json",
            manifest_digest="a" * 64,
            file_uri="bars/jm.parquet",
            checksum="b" * 64,
            row_count=10,
        )

    result = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=session_provider,
        publish_batch=publish_batch,
    ).sync(dataset=_dataset(), start=start, end=end)

    assert result.published_windows == ((start, end),)
    assert result.gap_windows == ()
    assert [entry if isinstance(entry, str) else entry[0] for entry in calls] == [
        "fetch",
        "publish",
        "clear",
    ]


def test_synchronizer_records_gap_only_after_all_retry_attempts_fail() -> None:
    calls: list[str] = []
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 10, tzinfo=UTC)

    class Catalog:
        def list_partitions(self, _dataset: DatasetKey) -> tuple[object, ...]:
            return ()

        def record_gap(self, _dataset: DatasetKey, gap: object) -> None:
            calls.append("gap")
            assert getattr(gap, "gap_start") == start
            assert getattr(gap, "gap_end") == end
            assert getattr(gap, "reason_code") == "historical_sync_retry_exhausted"
            assert dict(getattr(gap, "details")) == {
                "attempt_count": 4,
                "last_error_type": "TimeoutError",
                "last_error_code": "provider_timeout",
            }

        def clear_gaps_covered_by(self, *_args: object, **_kwargs: object) -> int:
            calls.append("clear")
            return 0

    class Adapter:
        def fetch_bars(self, _request: object) -> object:
            calls.append("fetch")
            raise TimeoutError("temporary provider failure")

    def session_provider(
        _dataset: DatasetKey,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[TradingSessionCoverage, ...]:
        return (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=window_start,
                end=window_end,
                expected_bar_ends=(window_end,),
            ),
        )

    result = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=session_provider,
        publish_batch=lambda _batch: (_ for _ in ()).throw(
            AssertionError("publish must not run")
        ),
    ).sync(dataset=_dataset(), start=start, end=end)

    assert result.published_windows == ()
    assert result.gap_windows == ((start, end),)
    assert calls == ["fetch", "fetch", "fetch", "fetch", "gap"]


def test_synchronizer_does_not_retry_or_mask_catalog_conflicts_as_data_gaps() -> None:
    calls: list[str] = []
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)

    class Catalog:
        def list_partitions(self, _dataset: DatasetKey) -> tuple[object, ...]:
            return ()

        def record_gap(self, *_args: object) -> None:
            calls.append("gap")

        def clear_gaps_covered_by(self, *_args: object, **_kwargs: object) -> int:
            return 0

    synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=SimpleNamespace(
            fetch_bars=lambda _request: calls.append("fetch") or object()
        ),
        session_provider=lambda _dataset, window_start, window_end: (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=window_start,
                end=window_end,
                expected_bar_ends=(window_end,),
            ),
        ),
        publish_batch=lambda _batch: (_ for _ in ()).throw(
            CatalogError("CATALOG_PARTITION_CONFLICT")
        ),
    )

    with pytest.raises(CatalogError, match="CATALOG_PARTITION_CONFLICT"):
        synchronizer.sync(dataset=_dataset(), start=start, end=end)

    assert calls == ["fetch"]


def test_canonical_batch_publisher_binds_publish_expectation_to_validated_stage() -> None:
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 1, 10, tzinfo=UTC)
    source = SimpleNamespace(
        dataset=_dataset(),
        coverage_start=start,
        coverage_end=end,
        row_count=10,
        data_version="provider-final-20260701",
    )
    staged = SimpleNamespace(
        source=source,
        file_checksum="a" * 64,
        canonical_logical_fingerprint="b" * 64,
    )
    captured: list[object] = []

    class Store:
        def stage(self, batch: object) -> object:
            captured.append(("stage", batch))
            return staged

        def publish(self, actual_staged: object, expectation: object) -> object:
            captured.append(("publish", actual_staged, expectation))
            return SimpleNamespace(
                partition_manifest=PartitionManifest(
                    coverage_start=start,
                    coverage_end=end,
                    manifest_version="canonical-manifest-v1",
                    manifest_uri="manifests/jm.json",
                    manifest_digest="c" * 64,
                    file_uri="bars/jm.parquet",
                    checksum="a" * 64,
                    row_count=10,
                )
            )

    manifest = CanonicalBatchPublisher(Store())(object())

    assert manifest.checksum == "a" * 64
    expectation = captured[1][2]
    assert expectation.dataset == _dataset()
    assert expectation.coverage_start == start
    assert expectation.coverage_end == end
    assert expectation.row_count == 10


def test_synchronizer_registers_only_rank_one_mapping_rows_from_provider() -> None:
    registered: list[MainMapRow] = []

    class Catalog:
        def register_main_contract_mapping(self, row: MainMapRow) -> None:
            registered.append(row)

    class Adapter:
        def fetch_rank1_map(self, request: MainMapRequest) -> tuple[MainMapRow, ...]:
            assert request.symbol == "jm"
            return (
                MainMapRow(
                    symbol="jm",
                    trading_day=date(2026, 7, 30),
                    actual_contract="JM2609",
                    rank=1,
                    data_version="rqdata-rank1-20260730",
                ),
            )

    synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=lambda _dataset, _start, _end: (),
        publish_batch=lambda _batch: (_ for _ in ()).throw(AssertionError()),
    )

    result = synchronizer.sync_rank1_mapping(
        symbol="jm",
        start_day=date(2026, 7, 30),
        end_day=date(2026, 7, 30),
        expected_trading_days=(date(2026, 7, 30),),
    )

    assert result.dry_run is False
    assert result.rows == tuple(registered)


def test_mapping_sync_fails_closed_when_an_expected_trading_day_is_missing() -> None:
    class Catalog:
        def register_main_contract_mapping(self, row: MainMapRow) -> None:
            raise AssertionError(f"must not register partial mapping: {row}")

    class Adapter:
        def fetch_rank1_map(self, request: MainMapRequest) -> tuple[MainMapRow, ...]:
            return (
                MainMapRow(
                    symbol=request.symbol,
                    trading_day=date(2026, 7, 30),
                    actual_contract="JM2609",
                    rank=1,
                    data_version="rqdata-rank1-20260730",
                ),
            )

    synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=lambda _dataset, _start, _end: (),
        publish_batch=lambda _batch: (_ for _ in ()).throw(AssertionError()),
    )

    with pytest.raises(DataGapError) as raised:
        synchronizer.sync_rank1_mapping(
            symbol="jm",
            start_day=date(2026, 7, 30),
            end_day=date(2026, 7, 31),
            expected_trading_days=(date(2026, 7, 30), date(2026, 7, 31)),
        )

    assert raised.value.facts["reason"] == "main_contract_mapping_missing"


def test_mapping_sync_rejects_contract_outside_approved_scope_before_register() -> None:
    registered: list[MainMapRow] = []

    class Catalog:
        def register_main_contract_mapping(self, row: MainMapRow) -> None:
            registered.append(row)

    class Adapter:
        def fetch_rank1_map(self, request: MainMapRequest) -> tuple[MainMapRow, ...]:
            return (
                MainMapRow(
                    symbol=request.symbol,
                    trading_day=date(2026, 7, 30),
                    actual_contract="JM9999",
                    rank=1,
                    data_version="rqdata-rank1-20260730",
                ),
            )

    synchronizer = HistoricalSynchronizer(
        catalog=Catalog(),
        adapter=Adapter(),
        session_provider=lambda _dataset, _start, _end: (),
        publish_batch=lambda _batch: (_ for _ in ()).throw(AssertionError()),
    )

    with pytest.raises(ContractValidationError) as raised:
        synchronizer.sync_rank1_mapping(
            symbol="jm",
            start_day=date(2026, 7, 30),
            end_day=date(2026, 7, 30),
            expected_trading_days=(date(2026, 7, 30),),
            allowed_contracts=("JM2609",),
        )

    assert raised.value.facts["reason"] == "outside_approved_scope"
    assert registered == []
