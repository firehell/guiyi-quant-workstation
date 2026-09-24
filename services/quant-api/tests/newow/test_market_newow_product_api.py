from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from guiyi_quant.newow.product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductFrequency,
)
from guiyi_quant.newow.product_identity import InputQualityPolicy
from app.market_data.domain import BarFrequency

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.market_data_service import MarketDataError
from app.market_data.newow.product_release import (
    candidate_input_quality_policy,
    require_open_weekly_product,
)
from app.market_data.newow.product_service import (
    NewowProductService,
    NewowProductServiceError,
    ProductServiceQuery,
)
from app.market_data.newow.historical_snapshot import HistoricalSnapshot
from app.market_data.newow.daily_snapshot import DailySnapshot
from app.market_data.newow.weekly_snapshot import WeeklySnapshot
from app.market_data.newow.resource_gate import NewowResourceBusy
from app.schemas.market_newow_product import (
    NewowProductResponse,
    ProductActionOut,
    ReferenceTradeOut,
)


def _service_result(product_cases):
    from newow.test_product_service import _service

    service, _reader, _build, clear = _service(product_cases, "1d")
    result = service.query(
        ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end, chart_limit=10)
    )
    return result, clear.bar_end


def _initial_clear_service_result(product_cases):
    reader, _query, fake = product_cases.paged_reader(
        prefix_bars=36, page_size=20, frequency="1d"
    )
    values = (*(["100"] * 35), "90")
    physical = tuple(
        replace(bar, open=value, high=value, low=value, close=value)
        for bar, value in zip(
            fake.physical[("RB2605", BarFrequency.D1)], values, strict=True
        )
    )
    fake.physical[("RB2605", BarFrequency.D1)] = physical
    fake.expected_physical[("RB2605", BarFrequency.D1)] = physical
    fake.actual[BarFrequency.D1] = tuple(
        bar for bar in physical if bar.trading_day >= fake.segments[0].start_trading_day
    )
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        now=lambda: fake.as_of,
    )
    return service.query(
        ProductServiceQuery(
            "rb", "main_rise", "1d", as_of=fake.as_of, chart_limit=2
        )
    )


def test_daily_weekly_release_capabilities_are_public_without_database_access():
    with TestClient(app) as client:
        response = client.get("/api/v1/market/newow/product-capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "newow_product_capabilities_v18",
        "release_stage": "daily_weekly",
        "open_frequencies": ["1d", "1w"],
        "weekly_products": [
            "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c", "cf", "cj", "cu",
            "eb", "ec", "eg", "fg", "fu", "hc", "i", "j", "jd", "jm", "l", "lc",
            "lh", "m", "ma", "ni", "oi", "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps", "pt", "rb",
            "rm", "rs", "ru", "sa", "sc", "si", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
        ],
        "deferred_frequencies": [
            {"frequency": "60m", "reason_code": "NEWOW_HOURLY_RELEASE_PENDING"},
        ],
        "open_sections": ["chart", "auxiliary", "reference", "comparator"],
        "deferred_sections": [
            {
                "section": "explanation",
                "reason_code": "NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN",
            }
        ],
    }


def test_formal_sr_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("sr")
    assert candidate_input_quality_policy(
        "sr", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_formal_rs_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("rs")
    assert candidate_input_quality_policy(
        "rs", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_formal_pk_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("pk")
    assert candidate_input_quality_policy(
        "pk", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_formal_pf_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("pf")
    assert candidate_input_quality_policy(
        "pf", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_formal_pl_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("pl")
    assert candidate_input_quality_policy(
        "pl", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_formal_pr_weekly_scope_uses_v2_and_keeps_other_four_closed():
    require_open_weekly_product("pr")
    assert candidate_input_quality_policy(
        "pr", ProductFrequency.WEEKLY, candidate_weekly=False
    ) is InputQualityPolicy.WEEKLY_V2
    for product in ("px", "sf", "sh", "sm"):
        with pytest.raises(ValueError, match="NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"):
            require_open_weekly_product(product)


def test_daily_snapshot_endpoint_returns_exact_verified_cutoff_and_pending_day(monkeypatch):
    requested = datetime(2026, 9, 18, 8, tzinfo=UTC)
    cutoff = datetime(2026, 9, 17, 7, 0, 0, 1, tzinfo=UTC)

    class Resolver:
        def resolve(self, product, strategy, frequency):
            assert (product, strategy.value, frequency.value) == ("rb", "trend", "1d")
            return DailySnapshot(
                product, strategy, frequency, requested,
                date(2026, 9, 18), date(2026, 9, 17), cutoff, "pending_update"
            )

    monkeypatch.setattr(market_newow, "_build_daily_resolver", lambda *_args: Resolver())
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/market/newow/daily-snapshot", params={
                "product": "rb", "strategy": "trend", "frequency": "1d"
            })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "newow_daily_snapshot_v1",
        "product": "rb", "strategy": "trend", "frequency": "1d",
        "series_kind": "actual_dominant",
        "requested_at": "2026-09-18T08:00:00Z",
        "expected_trading_day": "2026-09-18",
        "available_trading_day": "2026-09-17",
        "as_of": "2026-09-17T07:00:00.000001Z",
        "freshness": "pending_update",
    }


def test_weekly_snapshot_endpoint_returns_shared_cutoff_and_separate_current_owner(monkeypatch):
    requested = datetime(2026, 9, 18, 8, tzinfo=UTC)
    newer = datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC)
    older = datetime(2026, 9, 11, 7, 0, 0, 1, tzinfo=UTC)

    class Resolver:
        def resolve(self, product, strategy, frequency):
            assert (product, strategy.value, frequency.value) == ("rb", "trend", "1w")
            return WeeklySnapshot(
                product, strategy, frequency, requested, newer, older, older,
                "pending_update", {"status": "unknown", "physical_contract": None},
            )

    monkeypatch.setattr(market_newow, "_build_weekly_resolver", lambda *_args: Resolver(), raising=False)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/market/newow/weekly-snapshot", params={
                "product": "rb", "strategy": "trend", "frequency": "1w",
            })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "newow_weekly_snapshot_v1",
        "product": "rb", "strategy": "trend", "frequency": "1w",
        "series_kind": "actual_dominant", "requested_at": "2026-09-18T08:00:00Z",
        "expected_period_end": "2026-09-18T07:00:00.000001Z",
        "available_period_end": "2026-09-11T07:00:00.000001Z",
        "as_of": "2026-09-11T07:00:00.000001Z",
        "freshness": "pending_update",
        "current_context": {"status": "unknown", "physical_contract": None},
    }


@pytest.mark.parametrize("frequency", ["60m"])
def test_daily_release_rejects_deferred_product_frequencies_before_service(
    monkeypatch, frequency
):
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("deferred frequency reached product service")
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": frequency,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_FREQUENCY_NOT_OPEN"}}


@pytest.mark.parametrize("frequency", ["60m"])
def test_daily_release_rejects_deferred_historical_frequencies_before_resolver(
    monkeypatch, frequency
):
    monkeypatch.setattr(
        market_newow,
        "_build_historical_resolver",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("deferred frequency reached historical resolver")
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/historical-snapshot",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": frequency,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_FREQUENCY_NOT_OPEN"}}


def test_formal_weekly_release_rejects_product_outside_open_set_before_resolver(monkeypatch):
    monkeypatch.setattr(
        market_newow,
        "_build_weekly_resolver",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("out-of-scope product reached weekly resolver")
        ),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/weekly-snapshot",
                params={"product": "px", "strategy": "trend", "frequency": "1w"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"}
    }


def test_daily_release_admits_daily_product_frequency_to_service(monkeypatch):
    seen: list[str] = []

    class Fake:
        def query(self, query):
            seen.append(query.frequency.value)
            raise NewowProductServiceError("NEWOW_DATA_UNAVAILABLE")

    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda *_args, **_kwargs: Fake(),
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert seen == ["1d"]
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_UNAVAILABLE"}}


@pytest.mark.parametrize("frequency", ["1d"])
def test_daily_release_defers_cross_frequency_explanation_before_service(
    monkeypatch, frequency
):
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("deferred section reached product service")
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": frequency,
                    "section": "explanation",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_SECTION_NOT_OPEN"}}


def test_strategy_detail_returns_only_requested_typed_section(
    monkeypatch, product_cases
):
    result, as_of = _service_result(product_cases)
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session, _cancelled=None: type(
            "Fake", (), {"query": lambda _self, _query: result}
        )(),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "as_of": as_of.isoformat(),
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["section"] == "chart"
    assert body["chart"]["delivery"] == "delivered"
    assert body["reference"] == {
        "delivery": "not_requested",
        "status": None,
        "value": None,
    }
    assert isinstance(body["chart"]["value"]["bars"][0]["close"], str)
    assert (
        body["chart"]["value"]["chart_from"] <= body["chart"]["value"]["chart_through"]
    )
    assert len(body["chart"]["value"]["page_identity"]) == 64
    assert body["meta"]["schema_version"] == "newow_product_detail_v3"
    assert "input_quality_policy" not in body["meta"]["identity"]
    assert (
        body["meta"]["reference_model_version"]
        == "newow_marker_reference_zero_cost_v3"
    )
    assert body["chart"]["value"]["next_older_window"] is None
    assert body["chart"]["value"]["formal_signal_eligible"] is True
    channel = body["chart"]["value"]["trend_channel"]
    assert channel["kind"] == "trend_channel"
    assert channel["period"] == 10
    assert channel["formula_version"] == "newow_hhv_llv_channel_page_v1"
    assert len(channel["points"]) == len(body["chart"]["value"]["bars"])
    for point, bar in zip(channel["points"], body["chart"]["value"]["bars"], strict=True):
        assert point["bar_end"] == bar["bar_end"]
        assert point["physical_contract"] == bar["physical_contract"]
        assert point["segment_id"] == bar["segment_id"]
        assert point["source_identity"] == bar["source_identity"]
        assert point["formula_version"] == "newow_hhv_llv_channel_page_v1"
        assert point["status"]["status"] == "ready"
        assert isinstance(point["upper"], str)
        assert isinstance(point["lower"], str)
    assert "newow_hhv_llv_channel_page_v1" not in body["meta"]["identity"]["formula_versions"]
    assert all(
        isinstance(action["sequence"], int)
        for action in body["chart"]["value"]["actions"]
    )


@pytest.mark.parametrize("product", ["AU", "JM"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_strategy_detail_normalizes_ascii_product_before_service(
    monkeypatch, product_cases, product, strategy
):
    result, _as_of = _service_result(product_cases)
    seen = []

    class FakeService:
        def query(self, query):
            seen.append(query)
            return result

    monkeypatch.setattr(
        market_newow, "_build_product_service", lambda *_args: FakeService()
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": product,
                    "strategy": strategy,
                    "frequency": "1d",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [query.product for query in seen] == [product.lower()]


@pytest.mark.parametrize("product", [" au", "au ", "a1", "ＡＵ", "a-b", ""])
def test_strategy_detail_rejects_non_ascii_or_ambiguous_product_before_service(
    monkeypatch, product
):
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid product reached product service")
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": product,
                    "strategy": "trend",
                    "frequency": "1d",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "NEWOW_INVALID_PRODUCT"}}


def test_historical_snapshot_normalizes_ascii_product_before_resolver(monkeypatch):
    seen = []

    class Resolver:
        def resolve(self, product, strategy, frequency):
            seen.append(product)
            return HistoricalSnapshot(
                product,
                strategy,
                frequency,
                date(2026, 9, 7),
                datetime(2026, 9, 7, 7, tzinfo=UTC),
            )

    monkeypatch.setattr(
        market_newow, "_build_historical_resolver", lambda *_args: Resolver()
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/newow/historical-snapshot",
                params={"product": "JM", "strategy": "trend", "frequency": "1d"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["product"] == "jm"
    assert seen == ["jm"]


def test_typed_api_serializes_verified_initial_clear_without_entry(product_cases):
    result = _initial_clear_service_result(product_cases)
    payload = market_newow._product_response(result).model_dump(mode="json")

    assert payload["meta"]["schema_version"] == "newow_product_detail_v3"
    assert (
        payload["meta"]["reference_model_version"]
        == "newow_marker_reference_zero_cost_v3"
    )
    assert payload["chart"]["value"]["actions"] == [
        {
            **payload["chart"]["value"]["actions"][0],
            "kind": "CLEAR",
            "related_build_id": None,
            "trade_eligibility": "INITIAL_CLEAR_NO_ENTRY",
            "sequence": 0,
        }
    ]


def test_quality_policy_is_omitted_for_v1_and_explicit_for_weekly_v2(product_cases):
    from newow.test_product_service import _service

    service, _reader, build, clear = _service(product_cases)
    reference = service.query(
        ProductServiceQuery(
            "rb", "trend", "1d", section="reference",
            performance_since=build.trading_day,
            performance_through=clear.trading_day,
            as_of=clear.bar_end,
        )
    )
    trade = reference.reference.value.items[0]

    legacy_payload = market_newow._trade(trade, 0)
    assert "input_quality_policy" not in legacy_payload
    assert "input_quality_policy" not in ReferenceTradeOut.model_validate(
        legacy_payload
    ).model_dump(mode="json")
    candidate = replace(
        trade,
        input_quality_policy=InputQualityPolicy.WEEKLY_V2,
        futures_adaptation_version="newow_futures_weekly_quality_segment_v2",
    )
    candidate_payload = market_newow._trade(candidate, 0)
    assert candidate_payload["input_quality_policy"] == (
        "newow_weekly_input_quality_v2"
    )
    assert ReferenceTradeOut.model_validate(candidate_payload).model_dump(mode="json")[
        "input_quality_policy"
    ] == "newow_weekly_input_quality_v2"


@pytest.mark.parametrize(
    ("field", "value"),
    (("kind", "BUILD"), ("related_build_id", "forged-build"), ("sequence", 7)),
)
def test_typed_action_rejects_invalid_initial_clear_cross_fields(field, value):
    payload = {
        "signal_id": "initial-clear",
        "kind": "CLEAR",
        "bar_end": "2026-08-14T07:00:00Z",
        "trading_day": "2026-08-14",
        "reference_price": "100.100",
        "physical_contract": "PT2610",
        "segment_id": "pt:PT2610:2025-01-01T00:00:00+00:00",
        "calculation_segment_id": "pt:PT2610:2025-01-01T00:00:00+00:00",
        "related_build_id": None,
        "trade_eligibility": "INITIAL_CLEAR_NO_ENTRY",
        "sequence": 0,
    }
    payload[field] = value

    with pytest.raises(ValidationError, match="INITIAL_CLEAR_NO_ENTRY"):
        ProductActionOut.model_validate(payload)


def test_typed_v2_rejects_v1_reference_model_in_meta_and_trade(product_cases):
    result, _as_of = _service_result(product_cases)
    payload = market_newow._product_response(result).model_dump(mode="json")
    payload["meta"]["reference_model_version"] = (
        "newow_marker_reference_zero_cost_v1"
    )
    with pytest.raises(ValidationError):
        NewowProductResponse.model_validate(payload)

    from newow.test_product_service import _service

    service, _reader, build, clear = _service(product_cases)
    reference = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=clear.trading_day,
            as_of=clear.bar_end,
        )
    )
    trade = market_newow._product_response(reference).model_dump(mode="json")[
        "reference"
    ]["value"]["items"][0]
    trade["reference_model_version"] = "newow_marker_reference_zero_cost_v1"
    with pytest.raises(ValidationError):
        ReferenceTradeOut.model_validate(trade)


def test_strategy_detail_serializes_unavailable_channel_point_without_values(
    product_cases,
):
    result, _as_of = _service_result(product_cases)
    chart = result.chart.value
    assert chart is not None and chart.trend_channel is not None
    first = chart.trend_channel.points[0]
    unavailable = replace(
        first,
        upper=None,
        lower=None,
        availability=FeatureStatus(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
            "NEWOW_TREND_CHANNEL_BAR_MISSING",
        ),
    )
    layer = replace(
        chart.trend_channel,
        points=(unavailable, *chart.trend_channel.points[1:]),
    )
    payload = market_newow._product_response(
        replace(result, chart=replace(result.chart, value=replace(chart, trend_channel=layer)))
    ).model_dump(mode="json")

    point = payload["chart"]["value"]["trend_channel"]["points"][0]
    assert point["upper"] is None
    assert point["lower"] is None
    assert point["status"] == {
        "status": "unavailable",
        "evidence_status": "ACTIVE_CODE_VERIFIED",
        "reason_code": "NEWOW_TREND_CHANNEL_BAR_MISSING",
    }


def test_historical_snapshot_strict_query_and_exact_cutoff(monkeypatch):
    cutoff = datetime(2026, 9, 7, 7, 0, 0, 1, tzinfo=UTC)

    class Resolver:
        def resolve(self, product, strategy, frequency):
            return HistoricalSnapshot(
                product, strategy, frequency, date(2026, 9, 7), cutoff
            )

    monkeypatch.setattr(
        market_newow, "_build_historical_resolver", lambda *_args: Resolver()
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        ok = client.get(
            "/api/v1/market/newow/historical-snapshot",
            params={"product": "rb", "strategy": "trend", "frequency": "1d"},
        )
        duplicate = client.get(
            "/api/v1/market/newow/historical-snapshot?product=rb&product=ag&strategy=trend&frequency=1w"
        )
        unknown = client.get(
            "/api/v1/market/newow/historical-snapshot",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "as_of": cutoff.isoformat(),
            },
        )
    app.dependency_overrides.clear()
    assert ok.status_code == 200
    assert ok.json()["as_of"].endswith(".000001Z")
    assert ok.json()["validated_sections"] == ["chart", "zhaoyao_mirror"]
    assert duplicate.status_code == unknown.status_code == 422


def test_older_chart_window_round_trip_and_invalid_binding(monkeypatch, product_cases):
    from newow.test_older_chart_windows import setup_service

    service, _, facts = setup_service(product_cases, "1d")
    monkeypatch.setattr(market_newow, "_build_product_service", lambda *_args: service)
    app.dependency_overrides[get_db] = lambda: object()
    params = {"product": "rb", "strategy": "trend", "frequency": "1d"}
    try:
        with TestClient(app) as client:
            first = client.get("/api/v1/market/newow/strategy-detail", params=params)
            assert first.status_code == 200
            body = first.json()
            older_params = {**params, "snapshot_token": body["meta"]["snapshot_token"],
                            "chart_older_window": body["chart"]["value"]["next_older_window"]}
            older = client.get("/api/v1/market/newow/strategy-detail", params=older_params)
            forged = client.get("/api/v1/market/newow/strategy-detail",
                params={**older_params, "chart_older_window": "not-issued"})
            mixed = client.get("/api/v1/market/newow/strategy-detail",
                params={**older_params, "chart_before": "another-cursor"})
        assert older.status_code == 200
        assert older.json()["meta"]["snapshot_token"] == body["meta"]["snapshot_token"]
        assert older.json()["chart"]["value"]["bars"][-1]["bar_end"] < body["chart"]["value"]["bars"][0]["bar_end"]
        assert forged.status_code == 409
        assert forged.json()["detail"] == {"code": "NEWOW_CHART_CURSOR_INVALID"}
        assert mixed.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_historical_resolver_reuses_shared_resource_controls(monkeypatch):
    monkeypatch.setattr(market_newow, "build_market_data_service", lambda _session: object())
    monkeypatch.setattr(market_newow, "build_database_coverage_source", lambda _session: object())
    monkeypatch.setattr(market_newow, "load_active_products", lambda: ("rb",))
    now = datetime(2026, 9, 8, 8, tzinfo=UTC)
    resolver = market_newow._build_historical_resolver(
        object(), lambda: False, lambda: now
    )
    service = resolver._service_factory(lambda: False)
    assert service._cache is market_newow._PRODUCT_CACHE
    assert service._gate is market_newow._PRODUCT_GATE
    assert service._inflight is market_newow._PRODUCT_INFLIGHT


def test_historical_snapshot_preserves_typed_resource_and_service_errors(monkeypatch):
    class Resolver:
        error = None
        def resolve(self, *_args):
            raise self.error

    resolver = Resolver()
    monkeypatch.setattr(market_newow, "_build_historical_resolver", lambda *_args: resolver)
    app.dependency_overrides[get_db] = lambda: object()
    cases = (
        (NewowResourceBusy("NEWOW_RESOURCE_BUSY"), 429, "NEWOW_RESOURCE_BUSY"),
        (NewowProductServiceError("NEWOW_SNAPSHOT_GENERATION_CONFLICT"), 409, "NEWOW_SNAPSHOT_GENERATION_CONFLICT"),
        (NewowProductServiceError("NEWOW_SECTION_PARAMETER_INVALID"), 422, "NEWOW_SECTION_PARAMETER_INVALID"),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for error, status, code in cases:
            resolver.error = error
            response = client.get(
                "/api/v1/market/newow/historical-snapshot",
                params={"product": "rb", "strategy": "trend", "frequency": "1d"},
            )
            assert response.status_code == status
            assert response.json() == {"detail": {"code": code}}
    app.dependency_overrides.clear()


def test_strategy_detail_rejects_unknown_or_cross_section_inputs(monkeypatch):
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session: (_ for _ in ()).throw(
            AssertionError("invalid request reached service")
        ),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "evidence": "forged",
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "history_limit": 3,
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "as_of": "2026-01-01T00:00:00",
                },
            ).status_code
            == 422
        )
    app.dependency_overrides.clear()


def test_reference_uses_decimal_strings_and_null_empty_closed_metrics(
    monkeypatch, product_cases
):
    from newow.test_product_service import _service

    service, _reader, build, clear = _service(product_cases, "1d")
    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=build.trading_day,
            as_of=clear.bar_end,
        )
    )
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session, _cancelled=None: type(
            "Fake", (), {"query": lambda _self, _query: result}
        )(),
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "section": "reference",
                "performance_since": build.trading_day.isoformat(),
                "performance_through": build.trading_day.isoformat(),
                "as_of": clear.bar_end.isoformat(),
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    value = response.json()["reference"]["value"]
    assert "storage_mode" not in value
    assert value["summary"]["closed_count"] == 0
    assert value["summary"]["win_rate_pct"] is None
    assert isinstance(value["items"][0]["entry_reference_price"], str)
    assert isinstance(value["items"][0]["entry_sequence"], int)
    assert value["executable"] is False
    assert value["auto_order"] is False


def test_strategy_detail_maps_future_as_of_and_safe_internal_errors(monkeypatch):
    class Fake:
        def query(self, _query):
            raise RuntimeError("password token SQL /private/path")

    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session, _cancelled=None: Fake(),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app, raise_server_exceptions=False) as client:
        future = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "as_of": datetime(2100, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
        internal = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": "rb", "strategy": "trend", "frequency": "1d"},
        )
    app.dependency_overrides.clear()
    assert future.status_code == 422
    assert internal.status_code == 500
    assert internal.json() == {"detail": {"code": "NEWOW_INTERNAL_ERROR"}}
    assert "password" not in internal.text


def test_strategy_detail_normalizes_mds_failure_to_public_conflict(monkeypatch):
    class Fake:
        def query(self, _query):
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session, _cancelled=None: Fake(),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": "rb", "strategy": "trend", "frequency": "1d"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {
        "code": "NEWOW_DATA_UNAVAILABLE",
        "diagnostic": {"reason": "MAIN_CONTRACT_MAP_MISSING", "context": {"symbol": "rb", "frequency": "1d"},
                       "historical_candidate_recoverable": True},
    }}


def test_all_research_sections_validate_against_explicit_wire_models(product_cases):
    from newow.test_product_service import _MultiReader

    bars = {
        frequency: product_cases.primitive_input("trend", frequency).bars
        for frequency in ProductFrequency
    }
    as_of = min(items[-1].bar.bar_end for items in bars.values())
    multi = NewowProductService(
        lambda _context, _cancelled: _MultiReader(bars), now=lambda: as_of
    )
    explanation = market_newow._product_response(
        multi.query(
            ProductServiceQuery("rb", "trend", "1d", section="explanation", as_of=as_of)
        )
    )
    assert explanation.explanation.value is not None

    daily = product_cases.primitive_input("oscillation", "1d")
    single = NewowProductService(
        lambda _context, _cancelled: _MultiReader({ProductFrequency.DAILY: daily.bars}),
        now=lambda: daily.bars[-1].bar.bar_end,
    )
    comparator = market_newow._product_response(
        single.query(
            ProductServiceQuery(
                "rb",
                "oscillation",
                "1d",
                section="comparator",
                as_of=daily.bars[-1].bar.bar_end,
            )
        )
    )
    assert comparator.comparator.value is not None

    trend = product_cases.primitive_input("trend", "1d")
    auxiliary_service = NewowProductService(
        lambda _context, _cancelled: _MultiReader({ProductFrequency.DAILY: trend.bars}),
        now=lambda: trend.bars[-1].bar.bar_end,
    )
    for component in (
        "main_force_control",
        "up_down_energy",
        "zhaoyao_mirror",
        "cup_handle",
    ):
        response = market_newow._product_response(
            auxiliary_service.query(
                ProductServiceQuery(
                    "rb",
                    "trend",
                    "1d",
                    section="auxiliary",
                    component=component,
                    as_of=trend.bars[-1].bar.bar_end,
                )
            )
        )
        assert response.auxiliary.value is not None
