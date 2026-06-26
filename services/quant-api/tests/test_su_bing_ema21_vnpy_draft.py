from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_ema21"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass
class SimpleBar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _make_bar(close: float, volume: float = 100.0, spread: float = 1.0) -> SimpleBar:
    return SimpleBar(
        open=close - spread * 0.25,
        high=close + spread,
        low=close - spread,
        close=close,
        volume=volume,
    )


def _feed_strategy(strategy: object, bars: list[SimpleBar]) -> tuple[str, str]:
    for bar in bars:
        strategy.on_bar(bar)
    return strategy.last_signal, strategy.signal_reason


def test_su_bing_ema21_vnpy_strategy_module_imports() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import SuBingEma21VnpyStrategy

    assert SuBingEma21VnpyStrategy.__name__ == "SuBingEma21VnpyStrategy"
    assert "signal_reason" in SuBingEma21VnpyStrategy.variables
    assert "trade_note" in SuBingEma21VnpyStrategy.variables
    assert "volume_ratio" in SuBingEma21VnpyStrategy.variables
    assert "ema_distance_atr" in SuBingEma21VnpyStrategy.variables


def test_strategy_class_alias_and_canonical_path() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import STRATEGY_CLASS_PATH, SuBingEma21Strategy, SuBingEma21VnpyStrategy
    from guiyi_quant.strategies.su_bing_ema21.vnpy_strategy import SuBingEma21Strategy as ModuleAlias

    assert SuBingEma21Strategy is SuBingEma21VnpyStrategy
    assert ModuleAlias is SuBingEma21VnpyStrategy
    assert STRATEGY_CLASS_PATH.endswith("SuBingEma21VnpyStrategy")


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


def test_volume_average_excludes_current_bar() -> None:
    from guiyi_quant.strategies.su_bing_ema21.config_schema import validate_params
    from guiyi_quant.strategies.su_bing_ema21.vnpy_strategy import SuBingEma21VnpyStrategy, _volume_average_prior

    params = validate_params({"volume_window": 3})
    bars = [_make_bar(100 + index, volume=100.0) for index in range(4)]
    bars[-1] = _make_bar(104.0, volume=999.0)

    indicators = SuBingEma21VnpyStrategy._calculate_indicators(bars, params)

    assert _volume_average_prior([100.0, 100.0, 100.0, 999.0], params.volume_window) == 100.0
    assert indicators.volume_average == 100.0


def test_golden_cross_decision_includes_features() -> None:
    from unittest.mock import patch

    from guiyi_quant.strategies.su_bing_ema21.config_schema import validate_params
    from guiyi_quant.strategies.su_bing_ema21.vnpy_strategy import IndicatorSnapshot, SuBingEma21VnpyStrategy

    params = validate_params({"volume_multiplier": 1.0, "max_ema_deviation_atr": 5.0})
    bars = [_make_bar(100.0, volume=150.0), _make_bar(101.0, volume=150.0)]
    previous = IndicatorSnapshot(ema=100.0, dif=-0.5, dea=0.0, atr=2.0, volume_average=100.0)
    current = IndicatorSnapshot(ema=100.5, dif=0.5, dea=0.0, atr=2.0, volume_average=100.0)

    def fake_calculate_indicators(history: list[SimpleBar], _params: object) -> IndicatorSnapshot:
        return previous if len(history) == 1 else current

    with patch.object(SuBingEma21VnpyStrategy, "_calculate_indicators", staticmethod(fake_calculate_indicators)):
        decision = SuBingEma21VnpyStrategy._decide_signal(bars, current, params)

    assert decision.direction == "long"
    assert decision.reason == "ema21_bullish_macd_golden_cross"
    assert decision.features is not None
    assert decision.features.dif == 0.5
    assert decision.features.volume_ratio == 1.5
    assert decision.features.ema_distance_atr == 0.25


def test_on_bar_decisions_are_causal() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import SuBingEma21VnpyStrategy

    bars = [_make_bar(100 + index * 0.2, volume=100 + index) for index in range(40)]
    full_strategy = SuBingEma21VnpyStrategy(None, "full", "rb2405.SHFE", {})
    prefix_strategy = SuBingEma21VnpyStrategy(None, "prefix", "rb2405.SHFE", {})

    full_decisions: list[tuple[str, str, float, float]] = []
    for bar in bars:
        full_strategy.on_bar(bar)
        full_decisions.append(
            (
                full_strategy.last_signal,
                full_strategy.signal_reason,
                full_strategy.volume_ratio,
                full_strategy.ema_distance_atr,
            )
        )

    for bar in bars[:-1]:
        prefix_strategy.on_bar(bar)

    assert (
        prefix_strategy.last_signal,
        prefix_strategy.signal_reason,
        prefix_strategy.volume_ratio,
        prefix_strategy.ema_distance_atr,
    ) == full_decisions[-2]


def test_future_bar_does_not_change_prior_decision() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import SuBingEma21VnpyStrategy

    bars = [_make_bar(100 + index * 0.2, volume=100 + index) for index in range(40)]
    incremental = SuBingEma21VnpyStrategy(None, "incremental", "rb2405.SHFE", {})

    for bar in bars[:-1]:
        incremental.on_bar(bar)
    prior_state = (
        incremental.last_signal,
        incremental.signal_reason,
        incremental.ema_value,
        incremental.dif_value,
        incremental.dea_value,
    )

    replay = SuBingEma21VnpyStrategy(None, "replay", "rb2405.SHFE", {})
    for bar in bars[:-1]:
        replay.on_bar(bar)

    assert (
        replay.last_signal,
        replay.signal_reason,
        replay.ema_value,
        replay.dif_value,
        replay.dea_value,
    ) == prior_state


def test_strategy_class_alias_loads_via_strategy_loader() -> None:
    from app.vnpy_integration.strategy_loader import load_strategy_class
    from guiyi_quant.strategies.su_bing_ema21 import STRATEGY_CLASS_PATH, SuBingEma21Strategy, SuBingEma21VnpyStrategy

    canonical = load_strategy_class(STRATEGY_CLASS_PATH)
    legacy_alias = load_strategy_class("guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21Strategy")

    assert canonical is SuBingEma21VnpyStrategy
    assert legacy_alias is SuBingEma21Strategy
    assert legacy_alias is canonical


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
