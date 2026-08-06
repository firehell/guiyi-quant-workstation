"""Read-only M2 retained-universe historical architecture audit."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol, Sequence

from app.data_core.contracts import (
    DIRECT_FREQUENCIES,
    BarFrequency,
    DatasetKey,
    DatasetKind,
    DatasetOrigin,
)
from app.data_core.product_retirement import RETIRED_PRODUCTS, is_retired_identity
from app.services.data_operations.audit_v2 import AuditFinding
from app.services.data_operations.contracts import AuditRequest, AuditScope


class _Catalog(Protocol):
    def list_datasets(self, *, symbol: str) -> Sequence[object]: ...

    def list_effective_partitions(self, key: DatasetKey) -> Sequence[object]: ...

    def list_gaps(self, key: DatasetKey) -> Sequence[object]: ...

    def list_main_contract_mappings(
        self, *, instrument_symbol: str, start_date: object
    ) -> Sequence[object]: ...


def build_m2_audit_checker(
    *,
    catalog: _Catalog,
    verify_partition: Callable[[DatasetKey, object], object],
    market_data_readable: Callable[[DatasetKey, datetime, datetime], bool],
    retired_identity_rejected: Callable[[str], bool] = lambda product: is_retired_identity(
        product=product
    ),
) -> Callable[[AuditRequest], Sequence[AuditFinding]]:
    """Return the single M2 checker; it never creates provider or writer deps."""

    summary: dict[str, int] = {}

    def check(request: AuditRequest) -> Sequence[AuditFinding]:
        summary.clear()
        summary.update(
            product_count=len(request.symbols),
            dataset_count=0,
            partition_count=0,
            physical_verification_count=0,
            reader_probe_count=0,
            finding_count=0,
        )
        findings: list[AuditFinding] = []
        for retired_product in RETIRED_PRODUCTS:
            if not retired_identity_rejected(retired_product):
                findings.append(
                    _finding("M2_RETIRED_IDENTITY_GUARD_MISSING", retired_product)
                )
        for symbol in request.symbols:
            findings.extend(
                _audit_product(
                    catalog=catalog,
                    symbol=symbol,
                    verify_partition=verify_partition,
                    market_data_readable=market_data_readable,
                    summary=summary,
                )
            )
        if not request.symbols:
            findings.append(AuditFinding("M2_PRODUCTS_REQUIRED", AuditScope.M2))
        summary["finding_count"] = len(findings)
        return tuple(findings)

    setattr(check, "m2_summary", summary)
    return check


def _audit_product(
    *,
    catalog: _Catalog,
    symbol: str,
    verify_partition: Callable[[DatasetKey, object], object],
    market_data_readable: Callable[[DatasetKey, datetime, datetime], bool],
    summary: dict[str, int],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    try:
        rows = tuple(catalog.list_datasets(symbol=symbol))
    except Exception:  # noqa: BLE001 - unavailable catalog cannot pass M2
        return [_finding("M2_CATALOG_READ_FAILED", symbol)]
    try:
        datasets = tuple(_dataset_key(row) for row in rows)
    except Exception:  # noqa: BLE001 - catalog identity is an audit finding
        return [_finding("M2_DATASET_IDENTITY_INVALID", symbol)]
    summary["dataset_count"] += len(datasets)
    continuous = {
        item.frequency: item
        for item in datasets
        if item.dataset_kind is DatasetKind.CONTINUOUS
        and item.contract_or_series == f"{symbol.upper()}.MAIN"
    }
    for frequency in BarFrequency:
        if frequency not in continuous:
            findings.append(
                _finding("M2_CONTINUOUS_DATASET_MISSING", symbol, frequency)
            )

    actual = tuple(
        item for item in datasets if item.dataset_kind is DatasetKind.ACTUAL_DOMINANT
    )
    actual_frequencies = {item.frequency for item in actual}
    for frequency in BarFrequency:
        if frequency not in actual_frequencies:
            findings.append(
                _finding("M2_ACTUAL_DOMINANT_DATASET_MISSING", symbol, frequency)
            )

    all_partitions: dict[DatasetKey, tuple[object, ...]] = {}
    for dataset in datasets:
        try:
            partitions = tuple(catalog.list_effective_partitions(dataset))
        except Exception:  # noqa: BLE001 - catalog failures cannot pass M2
            findings.append(
                _finding("M2_PARTITION_CATALOG_READ_FAILED", symbol, dataset.frequency)
            )
            all_partitions[dataset] = ()
            continue
        all_partitions[dataset] = partitions
        summary["partition_count"] += len(partitions)
        if not partitions:
            findings.append(_finding("M2_PARTITION_MISSING", symbol, dataset.frequency))
            continue
        try:
            gaps = tuple(catalog.list_gaps(dataset))
        except Exception:  # noqa: BLE001 - gap state must be knowable
            findings.append(_finding("M2_GAP_CATALOG_READ_FAILED", symbol, dataset.frequency))
            continue
        if gaps:
            findings.append(_finding("M2_DATA_GAP_PRESENT", symbol, dataset.frequency))
        for partition in partitions:
            try:
                verified = verify_partition(dataset, partition)
                summary["physical_verification_count"] += 1
            except Exception:  # noqa: BLE001 - stable bounded finding
                findings.append(
                    _finding("M2_PHYSICAL_VERIFY_FAILED", symbol, dataset.frequency)
                )
                break
            findings.extend(_lineage_findings(symbol, dataset, verified, datasets))

    _mapping_findings(catalog, symbol, actual, all_partitions, findings)
    _probe_findings(
        symbol, all_partitions, market_data_readable, findings, summary
    )
    return findings


def _dataset_key(row: object) -> DatasetKey:
    return DatasetKey(
        provider=getattr(row, "provider"),
        dataset_kind=DatasetKind(getattr(row, "dataset_kind")),
        symbol=getattr(row, "symbol"),
        contract_or_series=getattr(row, "contract_or_series"),
        frequency=BarFrequency(getattr(row, "frequency")),
        adjustment=getattr(row, "adjustment"),
        schema_version=getattr(row, "schema_version"),
    )


def _lineage_findings(
    symbol: str,
    dataset: DatasetKey,
    verified: object,
    datasets: Sequence[DatasetKey],
) -> list[AuditFinding]:
    lineage = getattr(verified, "lineage", None)
    origin = getattr(lineage, "origin", None)
    source_frequency = getattr(lineage, "source_frequency", None)
    if dataset.frequency in DIRECT_FREQUENCIES:
        return (
            []
            if origin == DatasetOrigin.PROVIDER_DIRECT
            else [_finding("M2_DIRECT_LINEAGE_INVALID", symbol, dataset.frequency)]
        )
    source_key = DatasetKey(
        provider=dataset.provider,
        dataset_kind=dataset.dataset_kind,
        symbol=dataset.symbol,
        contract_or_series=dataset.contract_or_series,
        frequency=BarFrequency.M1,
        adjustment=dataset.adjustment,
        schema_version=dataset.schema_version,
    )
    if (
        origin != DatasetOrigin.PREAGGREGATED_FROM_1M
        or source_frequency != BarFrequency.M1
        or source_key not in datasets
    ):
        return [_finding("M2_DERIVED_LINEAGE_INVALID", symbol, dataset.frequency)]
    return []


def _mapping_findings(
    catalog: _Catalog,
    symbol: str,
    actual: Sequence[DatasetKey],
    partitions: dict[DatasetKey, tuple[object, ...]],
    findings: list[AuditFinding],
) -> None:
    if not actual:
        return
    coverage_starts = tuple(
        getattr(partition, "coverage_start")
        for dataset in actual
        for partition in partitions[dataset]
    )
    if not coverage_starts:
        findings.append(_finding("M2_MAIN_CONTRACT_MAP_INVALID", symbol))
        return
    start = min(coverage_starts)
    try:
        mappings = tuple(
            catalog.list_main_contract_mappings(
                instrument_symbol=symbol, start_date=start.date()
            )
        )
    except Exception:  # noqa: BLE001
        findings.append(_finding("M2_MAIN_CONTRACT_MAP_INVALID", symbol))
        return
    contracts = {item.contract_or_series for item in actual}
    if not mappings or any(
        getattr(item, "symbol", None) != symbol
        or getattr(item, "actual_contract", None) not in contracts
        for item in mappings
    ):
        findings.append(_finding("M2_MAIN_CONTRACT_MAP_INVALID", symbol))


def _probe_findings(
    symbol: str,
    partitions: dict[DatasetKey, tuple[object, ...]],
    market_data_readable: Callable[[DatasetKey, datetime, datetime], bool],
    findings: list[AuditFinding],
    summary: dict[str, int],
) -> None:
    unreadable_frequencies: set[tuple[DatasetKind, BarFrequency]] = set()
    for dataset, partition in _limited_probe_targets(partitions):
        identity = (dataset.dataset_kind, dataset.frequency)
        if identity in unreadable_frequencies:
            continue
        try:
            summary["reader_probe_count"] += 1
            readable = market_data_readable(
                dataset,
                getattr(partition, "coverage_start"),
                getattr(partition, "coverage_end"),
            )
        except Exception:  # noqa: BLE001
            readable = False
        if not readable:
            unreadable_frequencies.add(identity)
            findings.append(
                _finding("M2_MARKET_DATA_UNREADABLE", symbol, dataset.frequency)
            )


def _limited_probe_targets(
    partitions: dict[DatasetKey, tuple[object, ...]],
) -> tuple[tuple[DatasetKey, object], ...]:
    """Select a fixed audit sample, never one MarketData read per contract.

    Every partition still receives physical metadata/checksum/schema/row-count
    validation.  Reader probes instead establish that the unified reader can
    resolve the two edge windows, with one explicit M1 rollover pair for actual
    dominant data.  The selection is bounded per product even when its contract
    history is very long.
    """
    selected: list[tuple[DatasetKey, object]] = []

    def add(dataset: DatasetKey, partition: object) -> None:
        identity = (
            dataset,
            getattr(partition, "coverage_start"),
            getattr(partition, "coverage_end"),
            getattr(partition, "manifest_uri", None),
        )
        if not any(
            identity
            == (
                existing_dataset,
                getattr(existing_partition, "coverage_start"),
                getattr(existing_partition, "coverage_end"),
                getattr(existing_partition, "manifest_uri", None),
            )
            for existing_dataset, existing_partition in selected
        ):
            selected.append((dataset, partition))

    actual_by_frequency: dict[BarFrequency, list[tuple[DatasetKey, object]]] = {}
    for dataset, rows in partitions.items():
        if not rows:
            continue
        ordered_rows = tuple(
            sorted(rows, key=lambda row: (getattr(row, "coverage_start"), getattr(row, "coverage_end")))
        )
        if dataset.dataset_kind is DatasetKind.CONTINUOUS:
            add(dataset, ordered_rows[0])
            add(dataset, ordered_rows[-1])
        elif dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
            actual_by_frequency.setdefault(dataset.frequency, []).extend(
                (dataset, row) for row in ordered_rows
            )

    for frequency, candidates in actual_by_frequency.items():
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    getattr(item[1], "coverage_start"),
                    getattr(item[1], "coverage_end"),
                    item[0].contract_or_series,
                ),
            )
        )
        add(*ordered[0])
        add(*ordered[-1])
        if frequency is BarFrequency.M1:
            for before, after in zip(ordered, ordered[1:]):
                if before[0].contract_or_series != after[0].contract_or_series:
                    add(*before)
                    add(*after)
                    break
    return tuple(selected)


def _finding(
    code: str, symbol: str, frequency: BarFrequency | None = None
) -> AuditFinding:
    facts: dict[str, object] = {"symbol": symbol}
    if frequency is not None:
        facts["frequency"] = frequency.value
    return AuditFinding(code, AuditScope.M2, facts)
