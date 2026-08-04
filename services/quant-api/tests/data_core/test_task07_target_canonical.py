from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import (
    BarFrequency,
    BarsResult,
    DataGapError,
    DatasetKind,
    ManifestMismatchError,
)
from app.data_core.task07_target_canonical import (
    MainContractTarget,
    TargetCanonicalStatus,
    TargetContract,
    TargetSession,
    TargetValidation,
    assess_target_specs,
    build_target_specs,
    load_target_contract,
    market_data_probe,
    require_complete_mapping_window,
)
from app.services.market_data_service import MarketDataService


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _write_contract(path: Path, *, frequencies: str) -> Path:
    path.write_text(
        f"""schema_version: 1
targets:
  - target_id: jm_historical_canonical_v1
    provider: rqdata
    symbol: jm
    continuous_series: JM.MAIN
    dataset_kinds: [continuous, actual_dominant]
    frequencies: [{frequencies}]
    adjustment: none
    schema_version: canonical-bar-v1
    start_trading_day: 2013-03-22
    end_policy: latest_complete_main_contract_map_day
    main_contract:
      provider: rqdata
      rank: 1
      rule: volume_open_interest
""",
        encoding="utf-8",
    )
    return path


def test_target_contract_accepts_only_the_frozen_jm_seven_frequency_scope(
    tmp_path: Path,
) -> None:
    contract = load_target_contract(
        _write_contract(
            tmp_path / "targets.yaml",
            frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w",
        )
    )

    assert contract.symbol == "jm"
    assert contract.continuous_series == "JM.MAIN"
    assert contract.start_trading_day == date(2013, 3, 22)
    assert tuple(item.value for item in contract.frequencies) == (
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    )

    invalid = _write_contract(
        tmp_path / "invalid.yaml",
        frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w, 4h",
    )
    with pytest.raises(ValueError, match="TASK07_TARGET_CONTRACT_INVALID"):
        load_target_contract(invalid)


def test_repository_target_contract_is_the_frozen_jm_scope() -> None:
    contract = load_target_contract(
        Path(__file__).resolve().parents[4] / "config" / "data_core_v2_targets.yaml"
    )

    assert contract == TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=tuple(BarFrequency),
        start_trading_day=date(2013, 3, 22),
    )


def test_target_window_rejects_main_map_that_starts_after_config() -> None:
    contract = TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=tuple(BarFrequency),
        start_trading_day=date(2013, 3, 22),
    )

    with pytest.raises(ValueError, match="TASK07_MAIN_CONTRACT_MAP_INCOMPLETE"):
        require_complete_mapping_window(
            contract,
            (MainContractTarget(date(2013, 3, 25), "JM1309"),),
        )


def test_target_specs_come_only_from_config_and_explicit_main_map_segments(
    tmp_path: Path,
) -> None:
    contract = load_target_contract(
        _write_contract(
            tmp_path / "targets.yaml",
            frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w",
        )
    )
    mappings = (
        MainContractTarget(date(2026, 7, 29), "JM2609"),
        MainContractTarget(date(2026, 7, 30), "JM2609"),
        MainContractTarget(date(2026, 7, 31), "JM2701"),
    )
    sessions = (
        TargetSession(
            date(2026, 7, 29),
            _dt("2026-07-28T13:00:00+00:00"),
            _dt("2026-07-29T07:00:00+00:00"),
        ),
        TargetSession(
            date(2026, 7, 30),
            _dt("2026-07-29T13:00:00+00:00"),
            _dt("2026-07-30T07:00:00+00:00"),
        ),
        TargetSession(
            date(2026, 7, 31),
            _dt("2026-07-30T13:00:00+00:00"),
            _dt("2026-07-31T07:00:00+00:00"),
        ),
    )

    specs = build_target_specs(contract, mappings=mappings, sessions=sessions)

    assert len(specs) == 20
    assert {
        (
            item.dataset.dataset_kind.value,
            item.dataset.contract_or_series,
            item.dataset.frequency.value,
        )
        for item in specs
    } == {
        (kind, contract_code, frequency)
        for kind, contract_codes in (
            ("continuous", ("JM.MAIN",)),
            ("actual_dominant", ("JM2609", "JM2701")),
        )
        for contract_code in contract_codes
        for frequency in (
            ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
            if contract_code != "JM2609"
            else ("1m", "5m", "15m", "30m", "60m", "1d")
        )
    }
    actual_1m = [
        item
        for item in specs
        if item.dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT
        and item.dataset.frequency is BarFrequency.M1
    ]
    assert [(item.dataset.contract_or_series, item.start, item.end) for item in actual_1m] == [
        (
            "JM2609",
            _dt("2026-07-28T13:00:00+00:00"),
            _dt("2026-07-30T07:00:00+00:00"),
        ),
        (
            "JM2701",
            _dt("2026-07-30T13:00:00+00:00"),
            _dt("2026-07-31T07:00:00+00:00"),
        ),
    ]


def test_actual_weekly_target_uses_the_last_trading_day_mapping(
    tmp_path: Path,
) -> None:
    contract = load_target_contract(
        _write_contract(
            tmp_path / "targets.yaml",
            frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w",
        )
    )
    mappings = (
        MainContractTarget(date(2026, 7, 30), "JM2609"),
        MainContractTarget(date(2026, 7, 31), "JM2701"),
    )
    sessions = (
        TargetSession(
            date(2026, 7, 30),
            _dt("2026-07-29T13:00:00+00:00"),
            _dt("2026-07-30T07:00:00+00:00"),
        ),
        TargetSession(
            date(2026, 7, 31),
            _dt("2026-07-30T13:00:00+00:00"),
            _dt("2026-07-31T07:00:00+00:00"),
        ),
    )

    weekly = tuple(
        item
        for item in build_target_specs(contract, mappings=mappings, sessions=sessions)
        if item.dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT
        and item.dataset.frequency is BarFrequency.W1
    )

    assert len(weekly) == 1
    assert weekly[0].dataset.contract_or_series == "JM2701"
    assert weekly[0].start == _dt("2026-07-29T13:00:00+00:00")
    assert weekly[0].end == _dt("2026-07-31T07:00:00+00:00")


def test_all_valid_targets_require_no_data_write(tmp_path: Path) -> None:
    contract = load_target_contract(
        _write_contract(tmp_path / "targets.yaml", frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w")
    )
    specs = build_target_specs(
        contract,
        mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
        sessions=(
            TargetSession(
                date(2026, 7, 30),
                _dt("2026-07-29T13:00:00+00:00"),
                _dt("2026-07-30T07:00:00+00:00"),
            ),
        ),
    )

    result = assess_target_specs(
        specs,
        probe=lambda _spec: TargetValidation(valid=True, reason="validated"),
    )

    assert result["Stage_C"] == "NO_DATA_WRITE_REQUIRED"
    assert result["writes_authorized"] is False
    assert result["repair_count"] == 0
    assert {item["status"] for item in result["targets"]} == {
        TargetCanonicalStatus.KEEP_CANONICAL.value
    }


@pytest.mark.parametrize(
    ("frequency", "target_reason", "source_valid", "expected"),
    [
        ("1d", "catalog_coverage_missing", True, "REDOWNLOAD_DIRECT"),
        ("5m", "manifest_checksum_mismatch", True, "REBUILD_AGGREGATE"),
        ("5m", "manifest_checksum_mismatch", False, "REGISTER_DATA_GAP"),
    ],
)
def test_invalid_targets_produce_only_the_exact_allowed_gap_action(
    frequency: str,
    target_reason: str,
    source_valid: bool,
    expected: str,
    tmp_path: Path,
) -> None:
    contract = load_target_contract(
        _write_contract(tmp_path / "targets.yaml", frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w")
    )
    specs = build_target_specs(
        contract,
        mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
        sessions=(
            TargetSession(
                date(2026, 7, 30),
                _dt("2026-07-29T13:00:00+00:00"),
                _dt("2026-07-30T07:00:00+00:00"),
            ),
        ),
    )
    target = next(
        item
        for item in specs
        if item.dataset.dataset_kind is DatasetKind.CONTINUOUS
        and item.dataset.frequency.value == frequency
    )

    def probe(spec):
        if spec == target:
            return TargetValidation(valid=False, reason=target_reason)
        if spec.dataset.frequency is BarFrequency.M1:
            return TargetValidation(valid=source_valid, reason="source_missing")
        return TargetValidation(valid=True, reason="validated")

    result = assess_target_specs((target,), probe=probe)

    assert result["Stage_C"] == "EXACT_GAP_PLAN_REQUIRED"
    assert result["writes_authorized"] is False
    assert result["targets"] == [
        {
            "dataset": {
                "provider": "rqdata",
                "dataset_kind": "continuous",
                "symbol": "jm",
                "contract_or_series": "JM.MAIN",
                "frequency": frequency,
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
            "window": {
                "start": "2026-07-29T13:00:00+00:00",
                "end": "2026-07-30T07:00:00+00:00",
            },
            "status": expected,
            "reason": target_reason if expected != "REGISTER_DATA_GAP" else "canonical_1m_untrusted",
            "authorized": False,
        }
    ]


def test_market_data_probe_reads_all_seven_targets_at_the_same_frequency(
    tmp_path: Path,
) -> None:
    contract = load_target_contract(
        _write_contract(
            tmp_path / "targets.yaml",
            frequencies="1m, 5m, 15m, 30m, 60m, 1d, 1w",
        )
    )
    specs = tuple(
        item
        for item in build_target_specs(
            contract,
            mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
            sessions=(
                TargetSession(
                    date(2026, 7, 30),
                    _dt("2026-07-29T13:00:00+00:00"),
                    _dt("2026-07-30T07:00:00+00:00"),
                ),
            ),
        )
        if item.dataset.dataset_kind is DatasetKind.CONTINUOUS
    )
    observed: list[BarFrequency] = []

    class Reader:
        def get_bars(self, query):
            observed.append(query.frequency)
            dataset = next(item.dataset for item in specs if item.dataset.frequency is query.frequency)
            return BarsResult(
                bars=(_bar(dataset, query.end),),
                source_datasets=(dataset,),
                manifest_digests=("a" * 64,),
                requested_window=(query.start, query.end),
                data_type=query.dataset_kind,
                derived_frequency=None,
                source_data_versions=("canonical-v1",),
            )

    probe = market_data_probe(
        MarketDataService(object(), canonical_reader=Reader())  # type: ignore[arg-type]
    )

    assert all(probe(spec).valid for spec in specs)
    assert observed == list(contract.frequencies)


def test_market_data_probe_treats_catalog_gap_as_exact_direct_redownload() -> None:
    contract = TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=(BarFrequency.D1,),
        start_trading_day=date(2013, 3, 22),
    )
    spec = build_target_specs(
        contract,
        mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
        sessions=(
            TargetSession(
                date(2026, 7, 30),
                _dt("2026-07-29T13:00:00+00:00"),
                _dt("2026-07-30T07:00:00+00:00"),
            ),
        ),
    )[0]

    class Reader:
        def get_bars(self, _query):
            raise DataGapError(facts={"reason": "catalog_gap"})

    probe = market_data_probe(
        MarketDataService(object(), canonical_reader=Reader())  # type: ignore[arg-type]
    )
    validation = probe(spec)

    assert validation == TargetValidation(
        valid=False,
        reason="catalog_gap",
        explicit_gap=False,
    )
    result = assess_target_specs((spec,), probe=probe)
    assert result["targets"][0]["status"] == "REDOWNLOAD_DIRECT"
    assert result["repair_count"] == 1


@pytest.mark.parametrize(
    "unexpected_error",
    [
        OSError("permission denied"),
        ValueError("bug"),
        ManifestMismatchError(facts={"reason": "canonical_path_escape"}),
    ],
)
def test_market_data_probe_propagates_non_data_failures(
    unexpected_error: Exception,
) -> None:
    contract = TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=(BarFrequency.D1,),
        start_trading_day=date(2013, 3, 22),
    )
    spec = build_target_specs(
        contract,
        mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
        sessions=(
            TargetSession(
                date(2026, 7, 30),
                _dt("2026-07-29T13:00:00+00:00"),
                _dt("2026-07-30T07:00:00+00:00"),
            ),
        ),
    )[0]

    class Reader:
        def get_bars(self, _query):
            raise unexpected_error

    probe = market_data_probe(
        MarketDataService(object(), canonical_reader=Reader())  # type: ignore[arg-type]
    )

    with pytest.raises(type(unexpected_error), match=str(unexpected_error)):
        probe(spec)


def test_market_data_probe_rejects_invalid_service_result_type() -> None:
    spec = _single_direct_spec()

    class Reader:
        def get_bars(self, _query):
            return object()

    probe = market_data_probe(
        MarketDataService(object(), canonical_reader=Reader())  # type: ignore[arg-type]
    )

    with pytest.raises(TypeError, match="TASK07_MARKET_DATA_RESULT_INVALID"):
        probe(spec)


def test_market_data_probe_rejects_result_window_mismatch() -> None:
    spec = _single_direct_spec()
    mismatched_result = BarsResult(
        bars=(_bar(spec.dataset, spec.end),),
        source_datasets=(spec.dataset,),
        manifest_digests=("a" * 64,),
        requested_window=(spec.start - timedelta(minutes=1), spec.end),
        data_type=spec.dataset.dataset_kind,
        derived_frequency=None,
        source_data_versions=("canonical-v1",),
    )

    class Reader:
        def get_bars(self, _query):
            return mismatched_result

    probe = market_data_probe(
        MarketDataService(object(), canonical_reader=Reader())  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="TASK07_MARKET_DATA_RESULT_MISMATCH"):
        probe(spec)


def _single_direct_spec():
    contract = TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=(BarFrequency.D1,),
        start_trading_day=date(2013, 3, 22),
    )
    return build_target_specs(
        contract,
        mappings=(MainContractTarget(date(2026, 7, 30), "JM2609"),),
        sessions=(
            TargetSession(
                date(2026, 7, 30),
                _dt("2026-07-29T13:00:00+00:00"),
                _dt("2026-07-30T07:00:00+00:00"),
            ),
        ),
    )[0]


def _bar(dataset, bar_end: datetime) -> CanonicalBar:
    return CanonicalBar(
        provider=dataset.provider,
        dataset_kind=dataset.dataset_kind,
        symbol=dataset.symbol,
        contract_or_series=dataset.contract_or_series,
        frequency=dataset.frequency,
        bar_end=bar_end,
        trading_day=bar_end.date(),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        open_interest=Decimal("10"),
        adjustment=dataset.adjustment,
        schema_version=dataset.schema_version,
    )
