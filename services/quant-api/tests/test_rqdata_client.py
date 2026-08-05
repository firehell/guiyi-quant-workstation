from datetime import date, datetime

import pandas as pd
import pytest

from app.data_core.product_retirement import ProductRetirementError
from app.services.rqdata_ingest.client import RqDataClient


def test_underlying_symbol_uppercases_for_rqdata() -> None:
    assert RqDataClient.underlying_symbol("rb") == "RB"
    assert RqDataClient.underlying_symbol("TA") == "TA"
    assert RqDataClient.underlying_symbol("pp") == "PP"


def test_retired_products_are_rejected_before_any_rqdata_call() -> None:
    with pytest.raises(ProductRetirementError, match="PRODUCT_RETIRED"):
        RqDataClient.underlying_symbol("jr")
    with pytest.raises(ProductRetirementError, match="PRODUCT_RETIRED"):
        RqDataClient.order_book_id("T2609")

    assert RqDataClient.underlying_symbol("pp") == "PP"
    assert RqDataClient.underlying_symbol("ta") == "TA"


def test_all_future_instruments_excludes_retired_products() -> None:
    client = object.__new__(RqDataClient)

    class FakeRqdatac:
        @staticmethod
        def all_instruments(type: str) -> pd.DataFrame:
            assert type == "Future"
            return pd.DataFrame(
                [
                    {"order_book_id": "RB2609", "underlying_symbol": "RB"},
                    {"order_book_id": "JR2609", "underlying_symbol": "JR"},
                    {"order_book_id": "TA609", "underlying_symbol": "TA"},
                ]
            )

    client.rqdatac = FakeRqdatac()

    assert client.all_future_instruments()["order_book_id"].tolist() == ["RB2609", "TA609"]


def test_clamp_dominant_price_start() -> None:
    assert RqDataClient.clamp_dominant_price_start(date(2005, 1, 1)) == date(2010, 1, 4)
    assert RqDataClient.clamp_dominant_price_start(date(2020, 1, 1)) == date(2020, 1, 1)


def test_roll_yield_returns_empty_when_api_unavailable() -> None:
    class FuturesWithoutRollYield:
        pass

    class ClientWithoutRollYield:
        rqdatac = type("Rq", (), {"futures": FuturesWithoutRollYield()})()

    client = ClientWithoutRollYield()
    assert RqDataClient.roll_yield(client, "rb", date(2024, 1, 1), date(2024, 1, 31)).empty


def test_order_book_id_uppercases_contract() -> None:
    assert RqDataClient.order_book_id("rb2501") == "RB2501"


def test_contract_trading_periods_preserves_contract_and_trading_day() -> None:
    client = object.__new__(RqDataClient)

    class FakeRqData:
        @staticmethod
        def get_trading_periods(
            order_book_ids, *, start_date, end_date, frequency, market
        ):
            assert order_book_ids == ["A88", "IF88"]
            assert start_date == date(2026, 8, 4)
            assert end_date == date(2026, 8, 5)
            assert frequency == "1m"
            assert market == "cn"
            index = pd.MultiIndex.from_tuples(
                [("A88", date(2026, 8, 4)), ("IF88", date(2026, 8, 4))],
                names=["order_book_id", "date"],
            )
            return pd.DataFrame(
                {
                    "trading_hours": [
                        "21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00",
                        "09:31-11:30,13:01-15:00",
                    ]
                },
                index=index,
            )

    client.rqdatac = FakeRqData()

    result = client.contract_trading_periods(
        ("a88", "if88"),
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 5),
    )

    assert result.to_dict("records") == [
        {
            "order_book_id": "A88",
            "date": date(2026, 8, 4),
            "trading_hours": "21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00",
        },
        {
            "order_book_id": "IF88",
            "date": date(2026, 8, 4),
            "trading_hours": "09:31-11:30,13:01-15:00",
        },
    ]


def test_market_data_readiness_normalizes_official_response() -> None:
    client = object.__new__(RqDataClient)

    class FakeRqData:
        @staticmethod
        def is_data_ready(*, categories, expected_date, market):
            assert categories == ["future_minbar", "future_daybar"]
            assert expected_date == date(2026, 7, 20)
            assert market == "cn"
            index = pd.MultiIndex.from_tuples(
                [("cn", "future_minbar"), ("cn", "future_daybar")],
                names=["market", "category"],
            )
            return pd.DataFrame(
                {
                    "latest_date": [date(2026, 7, 20), date(2026, 7, 17)],
                    "update_time": [datetime(2026, 7, 20, 16, 19), datetime(2026, 7, 17, 16, 10)],
                    "expected_date": [date(2026, 7, 20), date(2026, 7, 20)],
                    "ready": [True, False],
                },
                index=index,
            )

    client.rqdatac = FakeRqData()
    result = client.market_data_readiness(
        expected_date=date(2026, 7, 20),
        categories=("future_minbar", "future_daybar"),
    )

    assert result["future_minbar"] == {
        "market": "cn",
        "category": "future_minbar",
        "latest_date": "2026-07-20",
        "update_time": "2026-07-20T16:19:00",
        "expected_date": "2026-07-20",
        "ready": True,
    }
    assert result["future_daybar"]["ready"] is False


def test_market_data_readiness_requires_supported_sdk() -> None:
    client = object.__new__(RqDataClient)
    client.rqdatac = object()

    with pytest.raises(RuntimeError, match="rqdatac_is_data_ready_unavailable"):
        client.market_data_readiness(
            expected_date=date(2026, 7, 20),
            categories=("future_minbar",),
        )


def test_rqdatac_version_is_exposed_for_approval_packets() -> None:
    client = object.__new__(RqDataClient)

    assert client.rqdatac_version() == "3.5.6.1"


def test_price_tick_reads_top_level_tick_size_series() -> None:
    class FakeRqdatac:
        @staticmethod
        def get_tick_size(order_book_id: str) -> pd.Series:
            assert order_book_id == "JM2609"
            return pd.Series({"JM2609": 0.5}, name="tick_size")

    client = object.__new__(RqDataClient)
    client.rqdatac = FakeRqdatac()

    assert client.price_tick("jm2609") == 0.5


def test_contract_multiplier_falls_back_to_future_catalog() -> None:
    class FakeFutures:
        @staticmethod
        def get_contract_multiplier(order_book_id: str) -> None:
            assert order_book_id == "JM2609"
            return None

    class FakeRqdatac:
        futures = FakeFutures()

        @staticmethod
        def all_instruments(type: str) -> pd.DataFrame:
            assert type == "Future"
            return pd.DataFrame([{"order_book_id": "JM2609", "contract_multiplier": 60}])

    client = object.__new__(RqDataClient)
    client.rqdatac = FakeRqdatac()

    assert client.contract_multiplier("jm2609") == 60
