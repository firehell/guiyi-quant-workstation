from datetime import date

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
