"""Offline diagnostics must distinguish recoverable gaps from corrupt facts."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.domain import BarFrequency
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.newow.historical_snapshot import (
    is_historical_candidate_unavailable,
)
from app.market_data.newow.product_reader import NewowProductReadError, _product_bar


DAY = date(2026, 9, 7)
END = datetime(2026, 9, 7, 7, tzinfo=UTC)
EXPECTED = tuple((END - timedelta(hours=i), DAY) for i in (2, 1, 0))


@pytest.mark.parametrize(
    "indices,reason,recoverable",
    [
        ((1, 2), "REPLAY_PREFIX_MISSING", True),
        ((0, 2), "REPLAY_ENDPOINTS_MISSING", True),
        ((0, 1), "REPLAY_ENDPOINTS_MISSING", True),
        ((0, 1, 2, 2), "REPLAY_ORDER_INVALID", False),
        ((1, 0, 2), "REPLAY_ORDER_INVALID", False),
        ((-1, 0, 1, 2), "REPLAY_ENDPOINTS_EXTRA", False),
    ],
)
def test_replay_gap_diagnostics_never_hide_integrity(indices, reason, recoverable):
    service = object.__new__(MarketDataService)
    service.expected_contract_replay_endpoints = lambda **_kwargs: EXPECTED
    points = (EXPECTED[0][0] - timedelta(hours=1), DAY), *EXPECTED
    bars = tuple(
        SimpleNamespace(bar_end=points[i + 1][0], trading_day=points[i + 1][1])
        for i in indices
    )
    with pytest.raises(MarketDataError) as raised:
        service.validate_contract_replay_coverage(
            symbol="rb",
            contract="RB2701",
            frequency=BarFrequency.H1,
            trading_day=DAY,
            cutoff=END,
            after=None,
            bars=bars,
        )
    assert raised.value.code == "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"
    assert raised.value.reason == reason
    assert raised.value.context["contract"] == "RB2701"
    assert raised.value.context["expected_count"] == 3
    assert is_historical_candidate_unavailable(raised.value) is recoverable


def test_replay_cutoff_mismatch_is_not_a_missing_suffix():
    service = object.__new__(MarketDataService)
    service.expected_contract_replay_endpoints = lambda **_kwargs: EXPECTED[:-1]
    with pytest.raises(MarketDataError) as raised:
        service.validate_contract_replay_coverage(
            symbol="rb",
            contract="RB2701",
            frequency=BarFrequency.H1,
            trading_day=DAY,
            cutoff=END,
            after=None,
            bars=(),
        )
    assert raised.value.reason == "REPLAY_CUTOFF_MISMATCH"
    assert not is_historical_candidate_unavailable(raised.value)
    assert not is_historical_candidate_unavailable(
        "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "source,reason",
    [
        ("TRADING_CALENDAR_MISSING", "TRADING_CALENDAR_MISSING"),
        ("TRADING_SESSION_MISSING", "TRADING_SESSION_MISSING"),
        ("HISTORICAL_SESSION_FACT_MISSING", "HISTORICAL_SESSION_FACT_MISSING"),
        ("CONTRACT_IDENTITY_MISMATCH", "METADATA_IDENTITY_INVALID"),
        ("UNRECOGNIZED_DATABASE_FAILURE", None),
    ],
)
def test_replay_authority_preserves_missing_invalid_and_unknown(source, reason):
    class Catalog:
        def contract_fact(self, *_args):
            raise InfrastructureError(source)

    service = object.__new__(MarketDataService)
    service.catalog = Catalog()
    with pytest.raises(MarketDataError) as raised:
        service.expected_contract_replay_endpoints(
            symbol="rb",
            contract="RB2701",
            frequency=BarFrequency.H1,
            trading_day=DAY,
            cutoff=END,
        )
    assert raised.value.reason == reason


@pytest.mark.parametrize("endpoint", ["strategy-detail", "historical-snapshot"])
@pytest.mark.parametrize(
    "error,status,reason",
    [
        (
            InfrastructureError("TRADING_CALENDAR_MISSING"),
            409,
            "TRADING_CALENDAR_MISSING",
        ),
        (
            InfrastructureError("CONTRACT_IDENTITY_MISMATCH"),
            409,
            "METADATA_IDENTITY_INVALID",
        ),
        (InfrastructureError("unknown private text"), 500, None),
        (ValueError("NEWOW_PRIVATE /private/fixture.sql"), 500, None),
        (RuntimeError("untrusted database failure"), 500, None),
        (NewowProductReadError("NEWOW_PRIVATE untrusted"), 500, None),
    ],
)
def test_both_endpoints_sanitize_unknown_errors(
    monkeypatch, endpoint, error, status, reason
):
    class Broken:
        def query(self, *_args):
            raise error

        resolve = query

    monkeypatch.setattr(market_newow, "_build_product_service", lambda *_args: Broken())
    monkeypatch.setattr(
        market_newow, "_build_historical_resolver", lambda *_args: Broken()
    )
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/api/v1/market/newow/{endpoint}",
                params={"product": "rb", "strategy": "trend", "frequency": "1d"},
            )
        assert response.status_code == status
        detail = response.json()["detail"]
        if reason is None:
            assert detail == {"code": "NEWOW_INTERNAL_ERROR"}
        else:
            assert detail["code"] == "NEWOW_DATA_UNAVAILABLE"
            assert detail["diagnostic"]["reason"] == reason
            assert detail["diagnostic"]["context"] == {
                "symbol": "rb",
                "frequency": "1d",
            }
    finally:
        app.dependency_overrides.clear()


def test_nonpositive_original_bar_is_named_without_mutating_source(product_cases):
    from dataclasses import replace
    from decimal import Decimal
    from guiyi_quant.newow.product_contracts import ProductFrequency

    _reader, _query, fake = product_cases.paged_reader(prefix_bars=12, page_size=2000)
    bar = fake.physical[("RB2605", BarFrequency.H1)][0]
    source = replace(
        bar, open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(0)
    )
    with pytest.raises(NewowProductReadError) as raised:
        _product_bar("rb", ProductFrequency.HOURLY, "RB2605", "segment", source, False)
    assert raised.value.code == "NEWOW_SOURCE_NONPOSITIVE_PRICE"
    assert raised.value.context["trading_day"] == source.trading_day.isoformat()
    assert source.close == Decimal(0)


def test_public_context_never_serializes_unvalidated_locations_or_details():
    from app.market_data.newow.public_errors import public_product_error

    error = MarketDataError(
        "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_PREFIX_MISSING"
    )
    error.context = {
        "symbol": "rb",
        "contract": "/private/fixture",
        "frequency": "1d",
        "trading_day": "2026-02-30",
        "expected_count": True,
        "missing_count": 2,
        "first_missing_at": END,
        "path": "/private/fixture",
    }
    status, detail = public_product_error(error)
    assert status == 409
    assert detail["diagnostic"]["context"] == {
        "symbol": "rb",
        "frequency": "1d",
        "missing_count": 2,
        "first_missing_at": "2026-09-07T07:00:00+00:00",
    }


@pytest.mark.parametrize(
    "error,continues",
    [
        (
            MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_PREFIX_MISSING"
            ),
            True,
        ),
        (
            MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                reason="REPLAY_ENDPOINTS_MISSING",
            ),
            True,
        ),
        (InfrastructureError("TRADING_CALENDAR_MISSING"), True),
        (InfrastructureError("HISTORICAL_SESSION_FACT_MISSING"), True),
        (MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"), False),
        (
            MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_ENDPOINTS_EXTRA"
            ),
            False,
        ),
        (
            MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_ORDER_INVALID"
            ),
            False,
        ),
        (
            MarketDataError(
                "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_CUTOFF_MISMATCH"
            ),
            False,
        ),
        (InfrastructureError("CONTRACT_IDENTITY_MISMATCH"), False),
        (InfrastructureError("UNKNOWN_FAILURE"), False),
        (NewowProductReadError("NEWOW_SOURCE_NONPOSITIVE_PRICE"), False),
    ],
)
def test_explicit_historical_search_skips_only_proven_missing_candidates(
    error, continues
):
    from app.market_data.newow.historical_snapshot import (
        NewowHistoricalSnapshotResolver,
    )
    from newow.test_historical_snapshot import Reader, delivered

    older = END - timedelta(days=1)
    calls = []

    class Service:
        def query(self, query):
            calls.append(query.as_of)
            if query.as_of == END:
                raise error
            return delivered(query.as_of, query.section.value)

    resolver = NewowHistoricalSnapshotResolver(
        Reader(((DAY, END), (DAY - timedelta(days=1), older))),
        lambda _cancelled: Service(),
        now=lambda: END,
    )
    if continues:
        assert resolver.resolve("rb", "trend", "1d").as_of == older
        assert calls == [END, older, older]
    else:
        with pytest.raises(type(error)):
            resolver.resolve("rb", "trend", "1d")
        assert calls == [END]
