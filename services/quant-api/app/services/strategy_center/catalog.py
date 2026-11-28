"""Stable directory keys. Formulas, policies and runtime belong to the domains."""

from dataclasses import dataclass
from types import MappingProxyType

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class Strategy:
    strategy_id: str
    domain: str
    name: str
    kind: str
    owner_key: str
    description: str
    dependencies: tuple[str, ...] = ()
    lifecycle: str = "ACTIVE"


CATALOG = MappingProxyType({
    item.strategy_id: item
    for item in (
        Strategy("newow_trend", "newow", "趋势", "BASE", "trend", "趋势参考动作与参考交易"),
        Strategy("newow_oscillation", "newow", "震荡", "BASE", "oscillation", "震荡参考动作与参考交易"),
        Strategy("newow_main_rise", "newow", "主升浪", "BASE", "main_rise", "主升浪参考动作与参考交易"),
        Strategy("newow_dual_fusion", "newow", "双策略融合", "COMPOSITE", "dual_fusion",
                 "组合趋势与震荡的领域结果", ("newow_trend", "newow_oscillation")),
        Strategy("htdy_60m", "htdy", "火天大有 60m", "DOMAIN_STRATEGY", "htdy",
                 "60m 原始观察与快期模拟账户"),
        Strategy("subing_portfolio_16", "subing", "苏冰共享 Paper 组合", "PORTFOLIO", "portfolio",
                 "16 品种共享一个组合资金与账本"),
    )
})
DOMAINS = tuple(dict.fromkeys(strategy.domain for strategy in CATALOG.values()))
