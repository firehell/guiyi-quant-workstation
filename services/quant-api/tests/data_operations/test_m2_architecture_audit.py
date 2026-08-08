"""M2 retained-universe architecture audit contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.guiyi_cli.data_commands import build_data_operation_request
from app.guiyi_cli.main import build_parser
from app.services.data_operations.audit_v2 import AuditV2ApplicationService
from app.services.data_operations.contracts import (
    AuditRequest,
    AuditScope,
    CliArgumentInvalid,
    CommandStatus,
)


START = datetime(2026, 8, 3, tzinfo=UTC)
END = START + timedelta(days=1)


def test_m2_is_a_first_class_readonly_audit_scope() -> None:
    assert AuditScope.M2.value == "m2"


def test_m2_cli_resolves_the_retained_active_universe() -> None:
    args = build_parser().parse_args(
        ["data", "audit", "--scope", "m2", "--universe", "active"]
    )

    request = build_data_operation_request(args)

    assert isinstance(request, AuditRequest)
    assert request.scope is AuditScope.M2
    assert len(request.symbols) == 69


def test_m2_cli_refuses_to_downgrade_to_a_single_product() -> None:
    args = build_parser().parse_args(
        ["data", "audit", "--scope", "m2", "--symbol", "jm"]
    )

    with pytest.raises(CliArgumentInvalid, match="M2_ACTIVE_UNIVERSE_REQUIRED"):
        build_data_operation_request(args)


def test_non_m2_audit_refuses_the_m2_universe_flag() -> None:
    args = build_parser().parse_args(
        ["data", "audit", "--scope", "catalog", "--universe", "active"]
    )

    with pytest.raises(CliArgumentInvalid, match="AUDIT_UNIVERSE_SCOPE_INVALID"):
        build_data_operation_request(args)


def _dataset(
    *,
    kind: DatasetKind,
    frequency: BarFrequency,
    contract: str,
) -> object:
    return SimpleNamespace(
        provider="rqdata",
        dataset_kind=kind.value,
        symbol="jm",
        contract_or_series=contract,
        frequency=frequency.value,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _partition() -> object:
    return SimpleNamespace(
        coverage_start=START,
        coverage_end=END,
        manifest_uri="manifest.json",
        manifest_digest="a" * 64,
        file_uri="part.parquet",
        checksum="b" * 64,
        row_count=1,
        overlap_reason=None,
    )


def test_m2_audit_passes_when_all_required_identities_are_verified() -> None:
    from app.services.data_operations.m2_architecture_audit import (
        build_m2_audit_checker,
    )
    datasets = [
        _dataset(
            kind=DatasetKind.CONTINUOUS,
            frequency=frequency,
            contract="JM.MAIN",
        )
        for frequency in BarFrequency
    ] + [
        _dataset(
            kind=DatasetKind.ACTUAL_DOMINANT,
            frequency=frequency,
            contract="JM2609",
        )
        for frequency in BarFrequency
    ]

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return datasets if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            return [_partition()]

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, *, instrument_symbol: str, start_date: date):
            assert instrument_symbol == "jm"
            assert start_date == START.date()
            return (
                SimpleNamespace(
                    symbol="jm", trading_day=START.date(), actual_contract="JM2609"
                ),
            )

    observed: list[DatasetKey] = []

    def verify_partition(key: DatasetKey, _partition: object) -> object:
        observed.append(key)
        return SimpleNamespace(
            lineage=SimpleNamespace(
                origin=(
                    "provider_direct"
                    if key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                    else "preaggregated_from_1m"
                ),
                source_frequency=(
                    None
                    if key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                    else BarFrequency.M1
                ),
            )
        )

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=verify_partition,
                market_data_readable=lambda _key, _start, _end, _position: True,
            )
        }
    )

    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))

    assert result.status is CommandStatus.PASSED
    assert result.effects.any_mutating is False
    assert len(observed) == 14
    assert result.extras["m2_summary"] == {
        "product_count": 1,
        "dataset_count": 14,
        "partition_count": 14,
        "physical_verification_count": 14,
        "reader_probe_count": 14,
        "finding_count": 0,
    }


def test_m2_market_data_probes_are_bounded_to_first_last_and_one_rollover() -> None:
    """Actual-contract probes must not grow with the historical contract count."""
    from app.services.data_operations.m2_architecture_audit import _limited_probe_targets

    continuous = DatasetKey(
        provider="rqdata", dataset_kind=DatasetKind.CONTINUOUS, symbol="jm",
        contract_or_series="JM.MAIN", frequency=BarFrequency.M1, adjustment="none",
        schema_version="canonical-bar-v1",
    )
    actual = [
        DatasetKey(
            provider="rqdata", dataset_kind=DatasetKind.ACTUAL_DOMINANT, symbol="jm",
            contract_or_series=f"JM{2601 + index}", frequency=BarFrequency.M1,
            adjustment="none", schema_version="canonical-bar-v1",
        )
        for index in range(42)
    ]
    partitions = {continuous: (_partition(),)}
    for index, dataset in enumerate(actual):
        start = START + timedelta(days=index)
        partitions[dataset] = (
            SimpleNamespace(coverage_start=start, coverage_end=start + timedelta(hours=1)),
        )

    targets = _limited_probe_targets(partitions)
    actual_targets = [item for item in targets if item[0].dataset_kind is DatasetKind.ACTUAL_DOMINANT]

    assert len(actual_targets) == 3
    assert {item[0].contract_or_series for item in actual_targets} == {
        "JM2601", "JM2602", "JM2642"
    }
    assert len(targets) == 4


def test_m2_audit_fails_when_a_derived_dataset_has_noncanonical_lineage() -> None:
    from app.services.data_operations.m2_architecture_audit import (
        build_m2_audit_checker,
    )
    dataset = _dataset(
        kind=DatasetKind.CONTINUOUS,
        frequency=BarFrequency.M5,
        contract="JM.MAIN",
    )

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return [dataset] if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            return [_partition()]

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, **_kwargs: object):
            return ()

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: SimpleNamespace(
                    lineage=SimpleNamespace(origin="provider_direct", source_frequency=None)
                ),
                market_data_readable=lambda _key, _start, _end, _position: True,
            )
        }
    )

    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))

    assert result.status is CommandStatus.ERROR
    assert "M2_DERIVED_LINEAGE_INVALID" in {
        item["code"] for item in result.extras["findings"]
    }


def test_m2_audit_requires_all_actual_dominant_frequencies() -> None:
    from app.services.data_operations.m2_architecture_audit import (
        build_m2_audit_checker,
    )
    dataset = _dataset(
        kind=DatasetKind.ACTUAL_DOMINANT,
        frequency=BarFrequency.M1,
        contract="JM2609",
    )

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return [dataset] if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            return [_partition()]

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, **_kwargs: object):
            return (
                SimpleNamespace(
                    symbol="jm", trading_day=START.date(), actual_contract="JM2609"
                ),
            )

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: SimpleNamespace(
                    lineage=SimpleNamespace(
                        origin="provider_direct", source_frequency=None
                    )
                ),
                market_data_readable=lambda _key, _start, _end, _position: True,
            )
        }
    )

    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))

    missing_actual = [
        item
        for item in result.extras["findings"]
        if item["code"] == "M2_ACTUAL_DOMINANT_DATASET_MISSING"
    ]
    assert {item["facts"]["frequency"] for item in missing_actual} == {
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    }


def test_m2_audit_fails_closed_when_a_retired_product_guard_is_missing() -> None:
    from app.services.data_operations.m2_architecture_audit import (
        build_m2_audit_checker,
    )

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return []

        def list_effective_partitions(self, _key: DatasetKey):
            return []

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, **_kwargs: object):
            return []

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: object(),
                market_data_readable=lambda _key, _start, _end, _position: True,
                retired_identity_rejected=lambda product: product != "ad",
            )
        }
    )

    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))

    assert "M2_RETIRED_IDENTITY_GUARD_MISSING" in {
        item["code"] for item in result.extras["findings"]
    }


def test_m2_audit_reports_invalid_catalog_identity_without_crashing() -> None:
    from app.services.data_operations.m2_architecture_audit import (
        build_m2_audit_checker,
    )

    invalid = _dataset(
        kind=DatasetKind.CONTINUOUS,
        frequency=BarFrequency.M1,
        contract="JM.MAIN",
    )
    invalid.provider = "other"

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return [invalid] if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            raise AssertionError("invalid identities must not reach partitions")

        def list_gaps(self, _key: DatasetKey):
            raise AssertionError("invalid identities must not reach gaps")

        def list_main_contract_mappings(self, **_kwargs: object):
            return []

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: object(),
                market_data_readable=lambda _key, _start, _end, _position: True,
            )
        }
    )

    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))

    assert result.status is CommandStatus.ERROR
    assert "M2_DATASET_IDENTITY_INVALID" in {
        item["code"] for item in result.extras["findings"]
    }


def test_m2_unreadable_finding_includes_probe_reason_code() -> None:
    from app.services.data_operations.market_data_probe import ProbeOutcome, ProbeReasonCode
    from app.services.data_operations.m2_architecture_audit import build_m2_audit_checker

    datasets = [
        *[_dataset(kind=DatasetKind.CONTINUOUS, frequency=freq, contract="JM.MAIN") for freq in BarFrequency],
        *[_dataset(kind=DatasetKind.ACTUAL_DOMINANT, frequency=freq, contract="JM2609") for freq in BarFrequency],
    ]

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return datasets if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            return [_partition()]

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, **_kwargs: object):
            return (SimpleNamespace(symbol="jm", actual_contract="JM2609", trading_day=START.date()),)

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: SimpleNamespace(
                    lineage=SimpleNamespace(
                        origin=(
                            "provider_direct"
                            if _key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                            else "local_aggregate"
                        ),
                        source_frequency=(
                            None
                            if _key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                            else BarFrequency.M1
                        ),
                    )
                ),
                market_data_readable=lambda *_args: ProbeOutcome(
                    False, reason_code=ProbeReasonCode.CALENDAR_MISSING.value
                ),
            )
        }
    )
    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))
    unreadables = [
        item for item in result.extras["findings"] if item["code"] == "M2_MARKET_DATA_UNREADABLE"
    ]
    assert unreadables
    assert all(item["facts"]["reason_code"] == "calendar_missing" for item in unreadables)


def test_m2_mapped_contract_dataset_missing_is_distinct_from_invalid_map() -> None:
    from app.services.data_operations.m2_architecture_audit import build_m2_audit_checker

    datasets = [
        *[_dataset(kind=DatasetKind.CONTINUOUS, frequency=freq, contract="JM.MAIN") for freq in BarFrequency],
        *[_dataset(kind=DatasetKind.ACTUAL_DOMINANT, frequency=freq, contract="JM2609") for freq in BarFrequency],
    ]

    class Catalog:
        def list_datasets(self, *, symbol: str):
            return datasets if symbol == "jm" else []

        def list_effective_partitions(self, _key: DatasetKey):
            return [_partition()]

        def list_gaps(self, _key: DatasetKey):
            return []

        def list_main_contract_mappings(self, **_kwargs: object):
            return (SimpleNamespace(symbol="jm", actual_contract="JM2701", trading_day=START.date()),)

    service = AuditV2ApplicationService(
        checkers={
            AuditScope.M2: build_m2_audit_checker(
                catalog=Catalog(),
                verify_partition=lambda _key, _partition: SimpleNamespace(
                    lineage=SimpleNamespace(
                        origin=(
                            "provider_direct"
                            if _key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                            else "local_aggregate"
                        ),
                        source_frequency=(
                            None
                            if _key.frequency in {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
                            else BarFrequency.M1
                        ),
                    )
                ),
                market_data_readable=lambda *_args: True,
            )
        }
    )
    result = service.run(AuditRequest(scope=AuditScope.M2, symbols=("jm",)))
    codes = {item["code"] for item in result.extras["findings"]}
    assert "M2_MAPPED_CONTRACT_DATASET_MISSING" in codes
    assert "M2_MAIN_CONTRACT_MAP_INVALID" not in codes
