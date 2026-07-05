from datetime import date

import pandas as pd

from app.services.rqdata_ingest.client import RqDataClient


def test_underlying_symbol_uppercases_for_rqdata() -> None:
    assert RqDataClient.underlying_symbol("rb") == "RB"
    assert RqDataClient.underlying_symbol("TA") == "TA"
    assert RqDataClient.underlying_symbol("pp") == "PP"


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
