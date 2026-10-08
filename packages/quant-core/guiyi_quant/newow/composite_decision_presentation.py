"""Daily/weekly view copy over CDV2 facts, never a second decision kernel."""

from .composite_explanation import (
    CompositeStatusState,
    calculate_first_action_principle,
)

PRESENTATION_VERSION = "guiyi_cdv2_daily_weekly_presentation_v1"

# Public CDV2 DECISION meanings, phrased for futures page-reference observation.
_ADVICE = {
    "bullish-bullish": "趋势与震荡共振向上，观察建仓或加仓信号，参考强度以综合结果为准。",
    "bullish-bearish": "趋势看多但震荡已清仓，短线回踩，保留参考底仓并等待回补信号。",
    "bullish-neutral": "趋势基调向上，震荡暂无明确方向，观察趋势建仓信号。",
    "bearish-bullish": "大级别趋势向下，震荡持有属于下跌中的反弹。按第一行动原则观察减仓离场，趋势转多前不维持底仓、不逆势加仓。",
    "bearish-bearish": "趋势与震荡共振向下，观察清仓或空仓，等待趋势反转。",
    "bearish-neutral": "趋势基调向下，震荡暂无明确方向，跟随趋势空仓观察。",
    "cautious-bullish": "周线看多而日线回调，震荡仍持有，谨慎观察并控制参考强度。",
    "cautious-bearish": "日线回调叠加震荡清仓，短线转弱，观察减仓信号。",
    "cautious-neutral": "日线回调、短线偏弱，谨慎观察，等待节奏明确。",
    "warning-bullish": "周线看空、日线反弹且震荡持有，属于反弹背离，观察逢高减仓。",
    "warning-bearish": "反弹背离叠加震荡清仓，观察反弹末段的减仓离场信号。",
    "warning-neutral": "周线看空、日线反弹，仍按反弹背离处理，减仓观望。",
    "neutral-bullish": "趋势信号不足而震荡先建仓，属于左侧信号；小仓试探的参考强度以本卡为准，等待趋势日线确认。",
    "neutral-bearish": "趋势信号不足而震荡先清仓，观察逢高减仓，等待趋势信号明确。",
    "neutral-neutral": "日周信号不足，等待趋势与震荡状态明确。",
    "MM1": "震荡已转空而趋势日线仍在黄带，属于旧趋势动摇、新趋势未立的错配期。观察保留底仓、逢高分批减仓；不追高、不加仓，趋势日线转蓝后按趋势信号处理。",
    "MM2": "震荡已建仓而趋势日线仍在蓝带，属于左侧信号。小仓试探并等待趋势翻黄确认；震荡规则本身没有止损出口，不能把参考强度当作风险预算。",
    "MM3": "趋势于 {age}下穿 MA10 转蓝，震荡仍持有。趋势定基调，震荡反弹只作减仓观察，不因此推迟减仓；周线亦在蓝带时按第一行动原则空仓观察。",
    "MM4": "趋势于 {age}上穿 MA10 转黄，震荡尚未回补。趋势定基调，观察分批回补窗口，等待震荡日线重新建仓再确认节奏。",
}


def describe_daily_weekly_cdv2(cd, trend, oscillation):
    """Reuse the existing first-action priority; omitted hourly never confirms it.

    The caller supplies owner-validated raw D1/W1 states. This function only
    returns display copy and does not mutate scores, actions, or exposure.
    """
    age = cd["mismatch_age"]
    age_text = "最新一根" if age == 0 else f"{age} 根日K前" if age > 0 else "计龄未知时"
    advice = _ADVICE.get(cd["action_code"], _ADVICE["neutral-neutral"]).format(age=age_text)
    if cd["insufficient_overlay"]:
        advice = "参与计算的日周信号明确性不足，当前结论为等待信号；不据此推断建仓或持仓。"
    if cd["volatility_level"] == "high":
        advice += "近期日线波动率偏高，注意控制参考强度、等待回踩确认。"

    w, d = trend.get("week"), trend.get("day")
    ow, od = oscillation.get("week"), oscillation.get("day")
    bearish_present = w in ("sell", "wait") or d in ("sell", "wait")
    complete = all(s in ("buy", "hold", "sell", "wait") for s in (w, d, ow, od))
    if not complete and not bearish_present:
        first = {
            "rule_token": "daily_weekly_inputs_missing",
            "level": "unknown",
            "title": "日周依据不足 · 等待状态明确",
            "detail": "部分日周策略状态不可用，不能确认第一行动原则；缺失60分钟不当作已确认信号。",
            "source_formula_version": None,
        }
    else:
        def osc_state(s):
            return (
                CompositeStatusState.HOLDING
                if s in ("buy", "hold")
                else CompositeStatusState.CLEARED
                if s in ("sell", "wait")
                else CompositeStatusState.IDLE
            )

        rule = calculate_first_action_principle(
            w, d, osc_state(ow), osc_state(od), CompositeStatusState.IDLE
        )
        title = rule.page_title.replace("持股", "持有")
        detail = rule.page_detail.replace("持股", "持有")
        # No stock-index authority, fixed stock allocation, or account claims.
        detail = detail.split("同步确认大盘")[0].rstrip()
        detail = detail.replace("大盘建仓期可顺势操作，仓位按建议执行。", "参考强度以本卡综合结果为准。")
        detail = detail.replace("60min/日线反弹", "日线反弹")
        exposure = cd["reference_exposure_range"] or "0%"
        detail = detail.replace("若参与建议仓位 ≤30%", f"若参与，建议仓位参考强度 {exposure}")
        first = {
            "rule_token": rule.rule_token,
            "level": rule.level,
            "title": title,
            "detail": detail,
            "source_formula_version": rule.page_formula_version,
        }
    return {
        "version": PRESENTATION_VERSION,
        "scope": "daily_weekly",
        "advice": advice,
        "first_action": first,
    }


def describe_hourly_cdv2(cd, trend, oscillation):
    """Present all three admitted periods without changing the decision kernel."""
    view = describe_daily_weekly_cdv2(cd, trend, oscillation)
    view.update(version="guiyi_cdv2_daily_weekly_hourly_presentation_v1", scope="daily_weekly_hourly")
    def osc_state(s):
        return (CompositeStatusState.HOLDING if s in ("buy", "hold") else
                CompositeStatusState.CLEARED if s in ("sell", "wait") else CompositeStatusState.IDLE)
    rule = calculate_first_action_principle(
        trend.get("week"), trend.get("day"), osc_state(oscillation.get("week")),
        osc_state(oscillation.get("day")), osc_state(oscillation.get("m60")))
    complete = all(axis.get(p) in ("buy", "hold", "sell", "wait")
                   for axis in (trend, oscillation) for p in ("week", "day", "m60"))
    if not complete and rule.level == "ok":
        view["first_action"] = {"rule_token": "daily_weekly_hourly_inputs_missing", "level": "unknown",
            "title": "日周小时依据不足 · 等待状态明确",
            "detail": "部分周期状态不可用，不把缺失视为确认信号。", "source_formula_version": None}
    else:
        detail = rule.page_detail.replace("持股", "持有").split("同步确认大盘")[0].rstrip()
        detail = detail.replace("大盘建仓期可顺势操作，仓位按建议执行。", "参考强度以本卡综合结果为准。")
        detail = detail.replace("若参与建议仓位 ≤30%", f"若参与，建议仓位参考强度 {cd['reference_exposure_range'] or '0%'}")
        view["first_action"] = {"rule_token": rule.rule_token, "level": rule.level,
            "title": rule.page_title.replace("持股", "持有"), "detail": detail,
            "source_formula_version": rule.page_formula_version}
    view["advice"] = view["advice"].replace("参与计算的日周信号", "参与计算的日周小时信号").replace("日周信号不足", "日周小时信号不足")
    return view
