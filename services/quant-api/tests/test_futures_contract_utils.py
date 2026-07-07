from app.services.futures_contract_utils import (
    is_continuous_contract,
    is_synthetic_futures_contract,
    normalize_product_name,
)


def test_is_synthetic_futures_contract_detects_main_and_rqdata_codes() -> None:
    assert is_synthetic_futures_contract("jm.MAIN") is True
    assert is_synthetic_futures_contract("IF88") is True
    assert is_synthetic_futures_contract("IF99") is True
    assert is_synthetic_futures_contract("A8888") is True
    assert is_synthetic_futures_contract("RB9999") is True
    assert is_synthetic_futures_contract("JM2609") is False
    assert is_synthetic_futures_contract("RB2510") is False


def test_is_continuous_contract_alias() -> None:
    assert is_continuous_contract("jm.MAIN") is True
    assert is_continuous_contract("JM2609") is False


def test_normalize_product_name_strips_continuous_suffixes() -> None:
    assert normalize_product_name("豆一指数连续", "a") == "豆一"
    assert normalize_product_name("焦煤主力连续", "jm") == "焦煤"
    assert normalize_product_name(None, "jm") == "JM"
