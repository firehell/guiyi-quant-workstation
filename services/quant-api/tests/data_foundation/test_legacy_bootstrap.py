from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.market_data.catalog import MainMapFact
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data import legacy_bootstrap
from app.market_data.legacy_bootstrap import LegacyBootstrapAdapter, LegacyBootstrapError
from app.market_data.maintenance import BarBatch


def _roots(tmp_path: Path):
    contract = tmp_path / "actual_contract_bars"
    continuous = tmp_path / "dominant_contract_bars"
    previous = tmp_path / "canonical"
    for root in (contract, continuous, previous):
        root.mkdir()
    return contract, continuous, previous


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_legacy_adapter_uses_one_best_allowlisted_candidate_and_normalizes(tmp_path) -> None:
    contract, continuous, previous = _roots(tmp_path)
    base = contract / "product=jm/contract=JM2509/frequency=1d"
    _write(base / "partial.parquet", [_row(2, 100)])
    _write(base / "complete.parquet", [_row(2, 100), _row(3, 101)])
    adapter = LegacyBootstrapAdapter(
        contract_root=contract,
        continuous_raw_root=continuous,
        previous_canonical_root=previous,
    )
    expected = (
        datetime(2025, 1, 2, 7, tzinfo=UTC),
        datetime(2025, 1, 3, 7, tzinfo=UTC),
    )

    batch = adapter.fetch(DatasetKey("contract", "jm", "JM2509", "1d"), expected)

    assert batch is not None
    assert tuple(bar.bar_end for bar in batch.bars) == expected
    assert batch.source_kind == "legacy_staging"
    assert len(batch.source_digest) == 64


def test_legacy_adapter_rejects_unapproved_or_symlink_root(tmp_path) -> None:
    contract, continuous, previous = _roots(tmp_path)
    with pytest.raises(LegacyBootstrapError, match="LEGACY_BOOTSTRAP_ROOT_INVALID"):
        LegacyBootstrapAdapter(
            contract_root=contract,
            continuous_raw_root=continuous,
            previous_canonical_root=previous,
            allowed_roots=(contract, continuous),
        )


def test_legacy_adapter_can_fill_contract_window_from_prior_actual_dominant(
    tmp_path,
) -> None:
    contract, continuous, previous = _roots(tmp_path)
    path = (
        previous
        / "provider/rqdata/dataset_kind/actual_dominant"
        / "symbol/jm/contract_or_series/JM2509/frequency/1d"
        / "adjustment/none/schema_version/canonical-bar-v1/data_version/v1/window"
        / "part-00000.parquet"
    )
    _write(path, [{**_row(2, 100), "bar_end": datetime(2025, 1, 2, 7, tzinfo=UTC), "trading_day": date(2025, 1, 2)}])
    adapter = LegacyBootstrapAdapter(
        contract_root=contract,
        continuous_raw_root=continuous,
        previous_canonical_root=previous,
    )

    batch = adapter.fetch(
        DatasetKey("contract", "jm", "JM2509", "1d"),
        (datetime(2025, 1, 2, 7, tzinfo=UTC),),
    )

    assert batch is not None
    assert batch.bars[0].trading_day == date(2025, 1, 2)


def test_gate_a_scope_reports_month_partitions_and_exact_provider_windows(
    tmp_path,
) -> None:
    planner = getattr(legacy_bootstrap, "plan_gate_a_scope", lambda **_kwargs: {})
    days = (
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
        date(2025, 1, 9),
        date(2025, 1, 10),
        date(2025, 1, 13),
        date(2025, 1, 14),
        date(2025, 1, 15),
        date(2025, 1, 16),
        date(2025, 1, 17),
    )
    mapped = tuple(MainMapFact("jm", day, "JM2509") for day in days[:7])
    continuous = {
        frequency: DatasetKey(DatasetKind.CONTINUOUS, "jm", "MAIN", frequency)
        for frequency in (BarFrequency.M1, BarFrequency.D1, BarFrequency.W1)
    }
    contract = {
        frequency: DatasetKey(DatasetKind.CONTRACT, "jm", "JM2509", frequency)
        for frequency in (BarFrequency.M1, BarFrequency.D1, BarFrequency.W1)
    }
    coverage = {
        continuous[BarFrequency.M1]: ((tmp_path / "continuous-1m.parquet", days[:6]),),
        continuous[BarFrequency.D1]: ((tmp_path / "continuous-1d.parquet", days[:7]),),
        continuous[BarFrequency.W1]: ((tmp_path / "continuous-1w.parquet", (days[1],)),),
        contract[BarFrequency.M1]: ((tmp_path / "contract-1m.parquet", days[:7]),),
        contract[BarFrequency.D1]: ((tmp_path / "contract-1d.parquet", days[:6]),),
        contract[BarFrequency.W1]: ((tmp_path / "contract-1w.parquet", (days[1], days[6])),),
    }

    result = planner(
        products=("jm",),
        starts={"jm": days[0]},
        through=days[6],
        candidate_root=tmp_path / "candidate",
        active_canonical_root=tmp_path / "active",
        trading_days={"jm": days},
        main_map=mapped,
        legacy_coverages=coverage,
        legacy_roots=(tmp_path / "contracts", tmp_path / "continuous", tmp_path / "active"),
    )

    assert result["counts"] == {
        "products": 1,
        "direct_datasets": 6,
        "derived_datasets": 8,
        "physical_datasets": 14,
        "direct_month_partitions": 6,
        "derived_month_partitions": 8,
        "month_partitions": 14,
        "legacy_selected_month_targets": 6,
        "legacy_fully_covered_month_targets": 3,
        "rqdata_windows": 3,
        "rqdata_missing_trading_days": 3,
    }
    assert {
        (tuple(item["dataset"]), item["start"], item["end"])
        for item in result["rqdata_windows"]
    } == {
        (continuous[BarFrequency.M1].as_tuple(), "2025-01-10", "2025-01-10"),
        (continuous[BarFrequency.W1].as_tuple(), "2025-01-10", "2025-01-10"),
        (contract[BarFrequency.D1].as_tuple(), "2025-01-10", "2025-01-10"),
    }
    assert len(result["scope_digest"]) == 64


def test_scan_legacy_coverages_recognizes_only_direct_allowlisted_identities(
    tmp_path,
) -> None:
    contract, continuous, previous = _roots(tmp_path)
    _write(
        contract / "product=jm/contract=JM2509/frequency=1d/raw.parquet",
        [_row(2, 100)],
    )
    _write(
        continuous / "product=jm/frequency=1m/version=v1/raw.parquet",
        [_row(3, 101)],
    )
    prior = (
        previous
        / "provider/rqdata/dataset_kind/actual_dominant"
        / "symbol/jm/contract_or_series/JM2509/frequency/1w"
        / "adjustment/none/schema_version/canonical-bar-v1/data_version/v1/window"
        / "part-00000.parquet"
    )
    _write(
        prior,
        [
            {
                **_row(3, 101),
                "bar_end": datetime(2025, 1, 3, 7, tzinfo=UTC),
                "trading_day": date(2025, 1, 3),
            }
        ],
    )
    _write(
        previous / "provider/rqdata/dataset_kind/actual_dominant/symbol/jm/contract_or_series/JM2509/frequency/5m/ignored.parquet",
        [_row(3, 101)],
    )

    coverage, invalid = legacy_bootstrap.scan_legacy_coverages(
        contract_root=contract,
        continuous_raw_root=continuous,
        previous_canonical_root=previous,
        products=("jm",),
    )

    assert invalid == ()
    assert {key.as_tuple() for key in coverage} == {
        ("contract", "jm", "JM2509", "1d"),
        ("continuous", "jm", "MAIN", "1m"),
        ("contract", "jm", "JM2509", "1w"),
    }
    assert coverage[DatasetKey("contract", "jm", "JM2509", "1w")][0][1] == (
        date(2025, 1, 3),
    )


def test_exact_scope_provider_matches_friday_night_to_monday_window() -> None:
    class Delegate:
        def __init__(self) -> None:
            self.calls = []

        def fetch(self, key, expected):
            self.calls.append((key, expected))
            bars = tuple(
                CanonicalBar(
                    value,
                    date(2010, 1, 4),
                    100,
                    101,
                    99,
                    100,
                    1,
                    10,
                    20,
                )
                for value in expected
            )
            return BarBatch(bars, "a" * 64, "rqdata")

    key = DatasetKey("continuous", "a", "MAIN", "1m")
    provider = legacy_bootstrap.ExactScopeProvider(
        Delegate(),
        {
            "rqdata_windows": [
                {
                    "dataset": list(key.as_tuple()),
                    "start": "2010-01-04",
                    "end": "2010-01-04",
                }
            ]
        },
    )
    # Friday night Shanghai (UTC+8) belonging to Monday 2010-01-04.
    night = datetime(2009, 12, 31, 13, 1, tzinfo=UTC)
    batch = provider.fetch(key, (night,))
    assert batch.bars[0].bar_end == night


def test_exact_scope_provider_splits_calls_and_rejects_days_outside_plan() -> None:
    class Delegate:
        def __init__(self) -> None:
            self.calls = []

        def fetch(self, key, expected):
            self.calls.append((key, expected))
            bars = tuple(
                CanonicalBar(
                    value,
                    value.date(),
                    100,
                    101,
                    99,
                    100,
                    1,
                    10,
                    20,
                )
                for value in expected
            )
            return BarBatch(bars, "a" * 64, "rqdata")

    key = DatasetKey("continuous", "jm", "MAIN", "1m")
    delegate = Delegate()
    provider_type = getattr(legacy_bootstrap, "ExactScopeProvider", None)
    assert provider_type is not None
    provider = provider_type(
        delegate,
        {
            "rqdata_windows": [
                {"dataset": list(key.as_tuple()), "start": "2025-01-02", "end": "2025-01-02"},
                {"dataset": list(key.as_tuple()), "start": "2025-01-04", "end": "2025-01-04"},
            ]
        },
    )
    expected = (
        datetime(2025, 1, 1, 13, 1, tzinfo=UTC),
        datetime(2025, 1, 2, 7, tzinfo=UTC),
        datetime(2025, 1, 4, 7, tzinfo=UTC),
    )

    batch = provider.fetch(key, expected)

    assert batch.bars[0].bar_end == expected[0]
    assert len(delegate.calls) == 2
    assert provider.request_count == 2
    # Unscoped leftovers fall back to RQData instead of hard-failing: day-level
    # exact-scope can mark legacy months complete while minute bars remain open.
    leftover = provider.fetch(key, (datetime(2025, 1, 3, 7, tzinfo=UTC),))
    assert leftover.bars[0].bar_end == datetime(2025, 1, 3, 7, tzinfo=UTC)
    assert provider.fallback_request_count == 1


def _row(day: int, close: int) -> dict:
    return {
        "date": datetime(2025, 1, day),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 10,
        "total_turnover": 1000,
        "open_interest": 20,
    }
