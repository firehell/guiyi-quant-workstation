from app.services.futures_contract_utils import (
    display_product_name,
    extract_product_name_from_contract_symbol,
    is_continuous_contract,
    is_synthetic_futures_contract,
    normalize_product_name,
    resolve_instrument_display_name,
    should_update_instrument_name,
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


def test_extract_product_name_from_contract_symbol() -> None:
    assert extract_product_name_from_contract_symbol("螺纹钢0909", "rb") == "螺纹钢"
    assert extract_product_name_from_contract_symbol("rb2610", "rb") == "rb"
    assert extract_product_name_from_contract_symbol("瓶片3月2503", "pr") == "瓶片"
    assert extract_product_name_from_contract_symbol("白银1209", "ag") == "白银"


def test_should_update_instrument_name_avoids_downgrade() -> None:
    assert should_update_instrument_name("螺纹钢", "rb", "rb") is True
    assert should_update_instrument_name("rb", "螺纹钢", "rb") is False
    assert should_update_instrument_name("rb", None, "rb") is True


def test_resolve_instrument_display_name_uses_manual_override() -> None:
    assert resolve_instrument_display_name("ao", "ao2601") == "氧化铝"
    assert resolve_instrument_display_name("rb", "rb2610", existing_name="螺纹钢") == "螺纹钢"


def test_display_product_name_uses_manual_override() -> None:
    assert display_product_name("ao", "ao") == "氧化铝"
    assert display_product_name("ec", "ec") == "集运指数(欧线)"
