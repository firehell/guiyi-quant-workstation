"""Shared display reuse requires exact full inputs, independently of strategy."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import DataInterruption
from guiyi_quant.newow.product_identity import InputQualityPolicy

from app.api.newow_presentation import _product_response
from app.market_data.domain import ResolvedContractSegment
from app.market_data.newow.product_query import ProductReadWindow
from app.market_data.newow.product_reader import ProductReadSet, ProductReadSource
from app.market_data.newow.product_service import (
    AuxiliaryComponent,
    ProductServiceQuery,
    _fingerprint,
    _shared_input_proof,
)


@pytest.fixture
def proof_read(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    window = ProductReadWindow(case.bars[-10].bar.trading_day, case.bars[-1].bar.trading_day)
    return ProductReadSet(
        case.identity.frequency, {case.identity.frequency: case.bars}, (), (),
        window, window, {}, case.bars[-1].bar.bar_end,
    ), case.identity


def test_market_proof_is_shared_across_strategy_but_legacy_identity_is_not(proof_read):
    read, identity = proof_read
    alternative = build_product_identity(identity.product, "oscillation", identity.frequency)
    assert _fingerprint(read, identity) != _fingerprint(read, alternative)
    assert _shared_input_proof(read, identity) == _shared_input_proof(read, alternative)
    assert _shared_input_proof(read, identity).auxiliary_input_sha256 is None


@pytest.mark.parametrize("changed", ["warmup", "mapping", "window", "performance", "cutoff", "quality", "segment", "source"])
def test_full_authoritative_input_changes_invalidate_market_proof(proof_read, changed):
    read, identity = proof_read
    if changed in {"warmup", "segment", "source"}:
        first, *rest = read.replay_bars
        if changed == "warmup":
            assert first.bar.trading_day < read.display_window.since
            first = replace(first, bar=replace(first.bar, close=first.bar.close + Decimal("0.01")))
        elif changed == "segment":
            first = replace(first, calculation_segment_id="changed-calculation-segment")
        else:
            first = replace(first, source_bar_sha256="b" * 64)
        revised = replace(read, bars_by_frequency={read.frequency: (first, *rest)})
    elif changed == "mapping":
        revised = replace(read, owners=(ResolvedContractSegment("RB2605", read.display_window.since, read.display_window.through),))
    elif changed == "window":
        revised = replace(read, display_window=replace(read.display_window, since=read.display_window.since + timedelta(days=1)))
    elif changed == "performance":
        revised = replace(read, performance_window=replace(read.performance_window, since=read.performance_window.since + timedelta(days=1)))
    elif changed == "cutoff":
        revised = replace(read, as_of=read.as_of + timedelta(seconds=1))
    else:
        revised = replace(read, input_quality_policies_by_frequency={read.frequency: InputQualityPolicy.DAILY_V2})
    assert _shared_input_proof(read, identity).market_input_sha256 != _shared_input_proof(revised, identity).market_input_sha256


def test_auxiliary_proof_binds_its_component_and_formula_but_not_strategy(proof_read):
    read, identity = proof_read
    alternative = build_product_identity(identity.product, "oscillation", identity.frequency)
    proof = _shared_input_proof(read, identity, AuxiliaryComponent.MACD, "macd-v1")
    assert proof == _shared_input_proof(read, alternative, AuxiliaryComponent.MACD, "macd-v1")
    assert proof.auxiliary_input_sha256 != _shared_input_proof(read, identity, AuxiliaryComponent.MACD, "macd-v2").auxiliary_input_sha256
    assert proof.auxiliary_input_sha256 != _shared_input_proof(read, identity, AuxiliaryComponent.MAIN_FORCE_CONTROL, "macd-v1").auxiliary_input_sha256
    assert _shared_input_proof(read, identity, AuxiliaryComponent.CUP_HANDLE, "cup-v1") != _shared_input_proof(read, alternative, AuxiliaryComponent.CUP_HANDLE, "cup-v1")


@pytest.mark.parametrize("changed", ["lifecycle", "gap", "source_cutoff"])
def test_market_proof_binds_lifecycle_quality_gaps_and_source_cutoffs(proof_read, product_cases, changed):
    read, identity = proof_read
    first = read.replay_bars[0].bar
    if changed == "lifecycle":
        evidence = product_cases.synthetic_lifecycle_evidence(read.replay_bars)
        read = replace(read, lifecycle_evidence_by_frequency={read.frequency: (evidence,)})
        revised = replace(read, lifecycle_evidence_by_frequency={read.frequency: (replace(evidence, input_sha256="c" * 64),)})
    elif changed == "gap":
        gap = DataInterruption(identity.product, read.frequency, first.physical_contract,
            first.segment_id, first.trading_day, first.bar_end, "quality-evidence")
        revised = replace(read, data_interruptions_by_frequency={read.frequency: (gap,)})
    else:
        source = ProductReadSource(read.frequency, "canonical", read.as_of, read.as_of,
            "policy-v1", len(read.replay_bars), len(read.replay_bars), 0)
        read = replace(read, sources={read.frequency: source})
        revised = replace(read, sources={read.frequency: replace(source, as_of=source.as_of + timedelta(seconds=1))})
    assert _shared_input_proof(read, identity).market_input_sha256 != _shared_input_proof(revised, identity).market_input_sha256


def test_cached_result_cannot_retain_a_superseded_full_input_proof(product_cases):
    from .test_product_service import _service

    service, reader, _, clear = _service(product_cases)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end)
    first = service.query(request)
    original_load = reader.load
    reader.load = lambda query, as_of: replace(
        original_load(query, as_of),
        input_quality_policies_by_frequency={query.frequency: InputQualityPolicy.V1},
    )
    revised = service.query(request)
    assert first.meta.shared_input_proof != revised.meta.shared_input_proof


def test_wire_proof_is_optional_for_legacy_and_serialized_for_new_results(product_cases):
    from .test_product_service import _service

    service, _, _, clear = _service(product_cases)
    chart = service.query(ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end))
    wire = _product_response(chart).model_dump(mode="json")
    proof = wire["meta"]["shared_input_proof"]
    assert proof["schema_version"] == "newow_shared_input_proof_v1"
    assert len(proof["market_input_sha256"]) == 64
    assert proof["auxiliary_input_sha256"] is None
    auxiliary = service.query(ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end, section="auxiliary", component="macd"))
    auxiliary_wire = _product_response(auxiliary).model_dump(mode="json")
    assert len(auxiliary_wire["meta"]["shared_input_proof"]["auxiliary_input_sha256"]) == 64
    legacy = replace(chart, meta=replace(chart.meta, shared_input_proof=None))
    assert "shared_input_proof" not in _product_response(legacy).model_dump(mode="json")["meta"]
