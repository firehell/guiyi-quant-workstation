# 焦煤单策略 SimNow 接入只读评估

基线：develop `c89a612fa61e01342b8c70cd421618d7969322e5`。本轮检查策略内核、Newow API/Web、行情读入口、历史/前向参考交易、研究回测与 Walk-forward、运行合同、依赖及账户执行域。不是逐行审计整个仓库，也不是全量回归或正式 Runtime 现场验收。

## 比较范围与口径

用户指定趋势、震荡、双策略、测试1–4，共七类；周期为当前开放的 5m、15m、30m、60m、1d、1w，共42格。主升浪不在本轮指定名单；1m只是输入与聚合周期，不是当前开放的 Newow 策略产品周期。

请求窗口2025-10-11至2026-10-10，固定as_of为2026-10-11 00:00上海时间。使用develop现有服务与MarketDataService，在PostgreSQL REPEATABLE READ / READ ONLY事务读取已有Canonical，不下载、不写Catalog、不开启Runtime。每个周期独立事务，保存输入hash；不是跨六周期的原子数据快照。

只比较ordinary页面普通参考累计值，单位为百分点，零费用/零滑点。没有混入ideal/theoretical，但ordinary仍使用页面参考价、同Bar高低价或末端Close估值，不能当作可执行年收益、账户净收益或资金复利。四测试的表值为各物理段已舍入累计值求和，与基础策略先汇总再舍入可能相差几百分之一百分点；回撤仅为段内口径，不是账户回撤。

JSON中的history_coverage=FULL是既有服务返回，不代表此次另做完整底层缺口审计。source_evidence_sha256若为空，不虚构补值。基础服务包含前序生命周期预热，实验只保留窗口内可评价段，不能按segment_count大小比较质量。

初版JSON的dual_fusion.formula_versions来自趋势请求身份，现已改名request_formula_versions；另外记录从当前源码推导的fusion_code_identity，并明确它不是原始服务回读。native融合revision及缺口区间未捕获，不作已核验断言。实际双策略融合同时绑定趋势、震荡公式及融合模型；代码权威为packages/quant-core/guiyi_quant/newow/fusion_reference.py及product_service.py。数值是现有fusion_comparison.page_performance返回，非自行拼接两组收益。

## 当前版本近一年页面普通结果

42/42格计算成功。实际末根completed为2026-10-09 15:00（上海）。单位为页面普通累计百分点。

| 周期 | 趋势 | 震荡 | 双策略 | 测试1 | 测试2 | 测试3 | 测试4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5m | 407.14 | 258.36 | 499.36 | 259.33 | 8.34 | 156.66 | 162.65 |
| 15m | 256.7 | 145.43 | 306.55 | 147.43 | 24.51 | 97.06 | 106.22 |
| 30m | 184.8 | 142.53 | 238.47 | 143.34 | 39.54 | 87.39 | 82.92 |
| 60m | 139.21 | 60.59 | 161.82 | 64.27 | 27.13 | 29.17 | 23.65 |
| 1d | 46.01 | 56.88 | 60.92 | 52.75 | 24.72 | 21.81 | 31.11 |
| 1w | 3.99 | 41.08 | 41.68 | 48.58 | 14.84 | 27.27 | 24.92 |

页面表现第一：JM × 5m × 双策略，499.36百分点、1609笔参考交易。选择为优先因果验证候选；不据此锁定SimNow自动执行。其页面分段回撤6.87百分点不能当作一手账户风险。

测试1：7%价格止损；测试2：7%止损并锁定入场HHV10目标；测试3：7%止损加前两根MA10上升过滤；测试4：12%止损与触上轨后延迟确认退出。以上均为各自页面公式语义。

## 当前能力与缺口

- 可复用：统一行情入口、实际主力物理合约分段、completed Bar、版本化策略Action、历史和前向参考交易、持久观察及健康/恢复机制。
- 趋势、震荡、双策略属于现有参考交易范围；测试1–4属于只读页面实验，没有正式前向Recording/Runtime执行身份。
- 当前因果研究器ResearchStrategy只有trend、oscillation、main_rise。双策略和四测试未接入该研究器，不能根据页面排序声称七类已有因果/OOS比较。
- 没有账户级StrategyDecision、TargetPosition、RiskDecision、Paper订单成交、不可变账户Ledger、持仓权益重放、CTP/SimNow接入、委托回报状态机及账户重连对账闭环。研究BacktestFill和ReferenceTrade均不是账户成交。
- STATUS记录正式Runtime为v1.15.1/gen12，当前develop晚于v1.15.2；自然盘中连续性仍PENDING。历史页面开放不代表所选流已经实时启用，5/15/30m尤其需要核对单路激活与自然证据。本轮不把STATUS记录冒充当前进程现场读回。

## 从研究候选到模拟自动交易的七步

1. **冻结候选并完成焦煤因果验证。** 用本轮页面结果确定优先研究组合；固定公式、参数、方向和窗口，补其执行语义。completed后最早可执行时点、真实物理合约、权威手续费/涨跌停/合约参数、滑点、零量、换月和期末持仓单列；做成本压力、样本外与Walk-forward。选择使用过的一年不再冒充独立OOS。若不足，保持候选，不以页面盈利晋升。
2. **实现一手目标仓位与最小风控。** 仅JM、一个周期、一个版本、LONG，BUILD目标1手、CLEAR目标0手；HOLD不产生新开仓。持仓加未完成开仓及发送中预留合计不超过1手；拒绝多账户、多合约、重复信号和不明确身份。冻结试点资金、保证金预算、日内亏损与停止开仓规则；不擅自把测试策略的价格止损当成账户风险上限。
3. **实现本地Paper与可重放账本。** 保存决策、风控、订单、成交、资金事件，重建持仓和权益；验证手续费、未成交、撤单、重复回报、结果未知和崩溃恢复。研究收益、Paper净收益、SimNow账户收益分栏。先做单账户最小闭环，无需组合优化平台。
4. **验收焦煤单路实时Shadow。** 使用真实自然completed Bar形成意图但不发单，核对顺序、时效、持久游标、重启、断线、Live/Canonical一致性。仅验收选定单路即可，不要求60品种全部完成。短分钟需完成该路运行接入；测试策略需另建正式前向适配。不得将历史补算当成实时信号。
5. **SimNow只读接入和账户对账。** 核实环境、账号、会话、交易日、结算、资金、持仓、委托、成交和合约参数；验证断线重连先读账户。信号行情仍由既有RQData链提供；交易端报价/状态只作执行校验并独立标识。优先用于仿真的正常交易时段环境，不能用开发测试环境的成功代替结算验收。
6. **订单草稿与人工确认的一手闭环。** 对明确的模拟账户生成草稿，经确认完成一次开仓、撤单路径和最终平仓对账；客户端订单身份、CTP订单/成交身份、交易日和本地账本能逐笔对应。覆盖拒单、发送超时、成交回报迟到/重复及重启后恢复，不在未知状态下重发。
7. **晋升到受控SimNow自动执行。** 以上验证通过且owner明确交办启用后，才自动发送该单一路径的新决策。提供持久停止开仓开关和可控撤单/平仓通道；行情过期、数据缺口、未知委托、仓位不符、超风险预算、会话异常和换月时停止新开仓。首版不自动换月、不自动补单、不自动晋升策略、不接真实资金账户。

## 本轮验证

实际执行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/newow/test_oscillation_experiments.py services/quant-api/tests/newow/test_research_backtest.py services/quant-api/tests/newow/test_research_walk_forward.py services/quant-api/tests/newow/test_page_performance.py services/quant-api/tests/reference_trading/test_forward_inputs.py services/quant-api/tests/reference_trading/test_newow_forward.py
```

结果：130 passed in 1.54s。git diff --check通过。已有代码合同的定向验证，不证明JM策略盈利、账户接入或自动交易就绪。

本轮仅新增本地审计脚本/结果/说明；未修改产品代码、生产数据、凭据、运行开关或账户。无需发布或回滚生产。

## 来源

- PROJECT_SOURCE.md：当前无账户/执行能力、阶段边界。
- docs/ARCHITECTURE.md：行情、策略、参考交易、Runtime职责。
- STATUS.md：发布与运行版本、自然验收边界。
- packages/quant-core/guiyi_quant/newow/research_backtest.py：三类ResearchStrategy与strict execution facts。
- packages/quant-core/guiyi_quant/newow/oscillation_experiments.py：测试1–4语义及普通/理论模型。
- packages/quant-core/guiyi_quant/newow/page_performance.py：页面普通累计、末端估值和分段边界。
- services/quant-api/app/reference_trading/forward_inputs.py：真实completed输入捕获。
- SimNow官方产品/环境说明：https://www.simnow.com.cn/product.action（本轮联网核查；实际接入时重新核实环境）。
