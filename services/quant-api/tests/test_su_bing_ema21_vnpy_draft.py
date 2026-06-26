from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_ema21"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def test_su_bing_ema21_vnpy_strategy_module_imports() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import SuBingEma21VnpyStrategy

    assert SuBingEma21VnpyStrategy.__name__ == "SuBingEma21VnpyStrategy"
    assert "signal_reason" in SuBingEma21VnpyStrategy.variables
    assert "trade_note" in SuBingEma21VnpyStrategy.variables


def test_default_params_json_can_be_parsed_and_validated() -> None:
    from guiyi_quant.strategies.su_bing_ema21.config_schema import validate_params

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    params = validate_params(raw_params)

    assert params.ema_period == 21
    assert params.macd_fast == 12
    assert params.macd_slow == 26
    assert params.atr_period == 14
    assert params.allow_long is True
    assert params.allow_short is True


def test_default_params_match_required_template() -> None:
    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        raw_params = json.load(file)

    assert raw_params == {
        "ema_period": 21,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "volume_window": 20,
        "volume_multiplier": 1.2,
        "atr_period": 14,
        "stop_atr_multiple": 2.0,
        "take_profit_r_multiple": 2.5,
        "max_ema_deviation_atr": 1.5,
        "allow_long": True,
        "allow_short": True,
    }


def test_strategy_directory_avoids_broker_and_secret_keywords() -> None:
    forbidden = [
        "CTP",
        "TqApi",
        "TqAuth",
        "TqAccount",
        "send_order",
        "insert_order",
        "password",
        "api_key",
        "实盘",
        "自动下单",
    ]

    for path in STRATEGY_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".md"}:
            content = path.read_text(encoding="utf-8")
            assert not any(keyword in content for keyword in forbidden), path
