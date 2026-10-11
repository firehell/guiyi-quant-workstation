from copy import deepcopy

import pytest

from scripts.newow_p0_acceptance import export_segments, verify_owner_binding, verify_payload
from app.api.market_newow import _product_response
from app.market_data.newow.product_reader import ResolvedPerformanceWindow
from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
from guiyi_quant.newow.product_adapters import build_product_identity


def fixture_collection(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    identity = build_product_identity("rb", "trend", "60m")
    resolved = ResolvedPerformanceWindow(query.since, query.through, query.through, fake.as_of)
    segments, input_hash = export_segments(read, identity, resolved)
    service = NewowProductService(lambda *_: reader, now=lambda: fake.as_of)
    result = service.query(ProductServiceQuery("rb", "trend", "60m", section="reference", include_fusion=True,
        performance_since=query.since, performance_through=query.through, as_of=fake.as_of))
    body = _product_response(result).model_dump(mode="json")
    return body, segments, input_hash, fake.as_of


def test_real_reader_full_prefix_and_api_source_owner_binding(product_cases):
    body, segments, input_hash, cutoff = fixture_collection(product_cases)
    verify_payload(body, "rb", "60m", cutoff, "trend")
    page = body["reference"]["value"]["page_performance"]
    verify_owner_binding(page, segments, input_hash, cutoff)
    assert len(segments[0]["bars"]) > len(page["ordinary"]["dates"])
    assert segments[0]["bars"][0]["date"].endswith("+08:00")


@pytest.mark.parametrize("field,value", [("product", "hc"), ("frequency", "5m"), ("strategy", "oscillation")])
def test_api_identity_substitution_rejected(product_cases, field, value):
    body, segments, input_hash, cutoff = fixture_collection(product_cases)
    body["meta"]["identity"][field] = value
    with pytest.raises(ValueError, match="P0_API_IDENTITY_MISMATCH"):
        verify_payload(body, "rb", "60m", cutoff, "trend")


def test_api_foreign_owner_or_hash_rejected(product_cases):
    body, segments, input_hash, cutoff = fixture_collection(product_cases)
    page = body["reference"]["value"]["page_performance"]
    wrong = deepcopy(page)
    wrong["input_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="P0_FULL_PREFIX_INPUT_HASH_MISMATCH"):
        verify_owner_binding(wrong, segments, input_hash, cutoff)
    wrong = deepcopy(page)
    wrong["ordinary"]["segment_ids"][0] = "foreign-owner"
    with pytest.raises(ValueError, match="P0_API_OWNER_INPUT_MISMATCH"):
        verify_owner_binding(wrong, segments, input_hash, cutoff)


def native_point(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy
    from app.reference_trading.presentation import presentation_point
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    identity = build_product_identity("rb", "oscillation", "60m")
    resolved = ResolvedPerformanceWindow(query.since, query.through, query.through, fake.as_of)
    segments, input_hash = export_segments(read, identity, resolved)
    replay = replay_strategy(identity, read.replay_bars, lifecycle_evidence=read.lifecycle_evidence)
    action = next(action for action in replay.actions if action.trade_eligibility.value == "ELIGIBLE")
    point = presentation_point(kind="action", value=action, trading_day=action.trading_day,
        formula_versions=identity.formula_versions)
    return point, segments, identity, fake.as_of


def test_native_saved_action_matches_eligible_physical_prefix(product_cases):
    from scripts.newow_p0_acceptance import verify_native_actions
    point, segments, identity, cutoff = native_point(product_cases)
    verify_native_actions([point], segments, identity, cutoff)


@pytest.mark.parametrize("change", ("owner", "formula", "warmup", "price", "duplicate"))
def test_native_saved_action_rejects_foreign_or_unproven_facts(product_cases, change):
    from scripts.newow_p0_acceptance import verify_native_actions
    point, segments, identity, cutoff = native_point(product_cases)
    if change == "owner":
        point["value"]["physical_contract"] = "RB2901"
    elif change == "formula":
        point["formula_versions"] = ["unfrozen_formula"]
    elif change == "warmup":
        for segment in segments:
            for bar in segment["bars"]:
                bar["observation_eligible"] = False
    elif change == "price":
        point["value"]["reference_price"] = "NaN"
    points = [point, point] if change == "duplicate" else [point]
    with pytest.raises(ValueError, match="P0_NATIVE_ACTION_"):
        verify_native_actions(points, segments, identity, cutoff)


def test_native_warmup_witness_preserved_but_never_claims_eligible_signal(product_cases):
    from scripts.newow_p0_acceptance import verify_native_actions
    point, segments, identity, cutoff = native_point(product_cases)
    point["value"]["trade_eligibility"] = "WARMUP_ONLY"
    for segment in segments:
        for bar in segment["bars"]:
            bar["observation_eligible"] = False
    verify_native_actions([point], segments, identity, cutoff)
    point["value"]["trade_eligibility"] = "ELIGIBLE"
    with pytest.raises(ValueError, match="P0_NATIVE_ACTION_ELIGIBILITY_MISMATCH"):
        verify_native_actions([point], segments, identity, cutoff)


def test_legacy_main_rise_typed_projection_is_independent_without_fusion(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="1d")
    service = NewowProductService(lambda *_: reader, now=lambda: fake.as_of)
    result = service.query(ProductServiceQuery("rb", "main_rise", "1d", section="reference", include_fusion=False,
        performance_since=query.since, performance_through=query.through, as_of=fake.as_of))
    body = _product_response(result).model_dump(mode="json")
    verify_payload(body, "rb", "1d", fake.as_of, "main_rise", include_fusion=False)
    assert body["reference"]["value"]["page_performance"]["strategy"] == "main_rise"
    assert body["reference"]["value"].get("fusion_comparison") is None
    with pytest.raises(ValueError, match="P0_API_IDENTITY_MISMATCH"):
        verify_payload(body, "rb", "1d", fake.as_of, "main_rise", include_fusion=True)
