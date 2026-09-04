from __future__ import annotations

from datetime import UTC, date, datetime
import os
from pathlib import Path
import subprocess
import sys
import json
from types import SimpleNamespace

import pytest

from app.market_data.newow.futures_evidence_discovery import (
    DiscoveryRequest,
    ReadOnlyDiscoveryError,
    canonical_file_manifest,
    build_discovery_result,
    discover_coverage_candidates,
    validate_candidate_market_data,
    read_only_session,
    run_discovery_with_dependencies,
    write_discovery_artifacts,
    validate_discovery_request,
    validate_select_only_privileges,
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
    def __init__(self, *, missing_frequency: str | None = None) -> None:
        self.missing_frequency = missing_frequency
        self.requests: list[object] = []

    def actual_dominant_segments(
        self, _product: str, _since: date, _through: date
    ) -> tuple[object, ...]:
        return (
            SimpleNamespace(contract="J2401"),
            SimpleNamespace(contract="J2405"),
            SimpleNamespace(contract="J2409"),
        )

    def query_actual_dominant_trading_days(self, request: object) -> object:
        self.requests.append(request)
        bars = () if request.frequency.value == self.missing_frequency else (object(),)
        return SimpleNamespace(bars=bars)


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


def test_discovery_result_selects_frozen_sector_candidates_before_any_strategy_work() -> None:
    products = ("j", "ma", "a")
    maps = {product: _map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    result = build_discovery_result(
        _Catalog(maps, partitions),
        _MarketData(),
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
    maps = {product: _map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_partition(),)
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
        market_data_factory=lambda catalog: _MarketData(),
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
    maps = {product: _map(product) for product in products}
    partitions = {
        (product, row.contract, frequency): (_partition(),)
        for product in products
        for row in maps[product]
        for frequency in ("1d", "1w", "60m")
    }
    result = build_discovery_result(
        _Catalog(maps, partitions),
        _MarketData(),
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
        "coverage.csv",
        "input_hashes.json",
        "zero_write_proof.json",
    }
    selection = json.loads((output / "selection.json").read_text(encoding="utf-8"))
    assert selection["selected_products"] == ["j", "ma", "a"]
