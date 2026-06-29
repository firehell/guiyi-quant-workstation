# SKILL_ALIGNMENT_TEMPLATE

本模板只填当前代码规则，不编造苏冰 Skill 规则。`su_bing_skill_rule` 留给后续人工或 ChatGPT 对齐。

| rule_category | current_code_rule | su_bing_skill_rule | match_status | impact_on_report_10 | suggested_action | priority |
|---|---|---|---|---|---|---|
| 趋势方向 | close > EMA21 偏多，close < EMA21 偏空；未使用更高周期趋势。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| EMA21 位置 | 多头要求 daily close > EMA21；空头要求 daily close < EMA21。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| EMA21 斜率 | 当前入场不要求 EMA21 斜率；只在导出中记录 `ema21_slope`。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 突破 / 回踩 / 收回 EMA21 | 当前代码不识别突破、回踩或收回形态，只检查收盘价与 EMA21 位置。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| MACD 零轴附近 | 要求 `abs(DIF) <= 25 and abs(DEA) <= 25`。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| MACD 金叉 / 死叉 | 多头要求金叉；空头要求死叉。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 成交量确认 | 要求 `current_volume > previous_volume`。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 禁止追高 / 杀跌 | 当前代码没有独立追高/杀跌过滤。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 震荡区过滤 | 当前代码没有独立震荡区过滤。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 入场触发 | 日线收盘确认信号，下一根日线 open 成交，1 tick 不利滑点。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 持仓逻辑 | 最多 1 手；无 pyramiding；无同日反手；持仓直到 EMA21 失效。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 离场逻辑 | 多单 close < EMA21 后下一日 open 平；空单 close > EMA21 后下一日 open 平。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 止损逻辑 | v0.2.0-daily 禁用固定止损。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 浮盈保护 | 当前代码没有浮盈保护。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 多空对称性 | 多空在 EMA21 位置、MACD 交叉、成交量确认上基本对称。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 换月 / 主连处理 | 回测研究符号为 `jm.MAIN`，成交合约由主力映射补充；未做强制换月平仓。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
| 信号强弱评分 | 当前代码没有信号强弱评分。 | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |
