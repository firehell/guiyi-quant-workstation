# JM日线阶段C：本地成本压力与失败路径研究

结论：已按冻结规则完成本地基准、双倍手续费、双倍滑点研究。主连续账户在首次换月时中断，整窗收益仍为null。7个独立owner只有3笔不同的完整交易，证据不足以判断稳定盈利或晋升策略。规则不变，Paper、Runtime、SimNow和真实订单未启用。

范围沿用[冻结设计](subing-jm-daily-v1-design-20261022.md)、[阶段A输入审计](subing-jm-daily-v1-phase-a-20261022.md)和[阶段B工程验收](subing-jm-daily-v1-phase-b-20261022.md)。只使用本地已验证489个交易日（2024-10-14～2026-10-19）、7个物理owner、178777个完成事件；未补数据、缩窗、搜索参数或新增指标过滤。430日执行事实不足和11个换月旧合约退出输入缺口保持。

## 成本场景与实现

| 场景 | 开平费用 | 每边方向性滑点 | 其他规则 |
| --- | --- | --- | --- |
| baseline | 原执行快照 | 1 tick | 冻结规则 |
| double_commission | 各合约每日开、平今、平昨费用均×2 | 1 tick | 同基准 |
| double_slippage | 原执行快照 | 2 ticks | 同基准 |

tick为0.5价格点，乘数为60；这些合约事实来自冻结快照。1或2 tick滑点为模型假设，不是实际成交证据。手续费压力通过不可变费用副本实现，不改原快照。更高费用和滑点同时进入信号前风险检查、成交前风险检查、实际模拟Fill及账户核算，不是事后从同一收益中简单扣钱。基准核心输出与阶段B逐值相等。

实现复用原DailyModel、MDS适配器和费用内核；只提取共享入场风险解释函数，并加入独立成本场景身份和诊断记录。保护线、EMA/MACD公式、手数、2%/5%限制、换月和反向政策不变。成本身份为`subing_jm_d1_cost_{scenario}_v1`；checkpoint拒绝跨成本政策恢复。没有新的执行基础设施或数据库账本。

## 连续账户：明确中断

三个场景均处理17344个事件，于2024-12-17 21:01北京时间（交易日2024-12-18）观察JM2501→JM2505而进入`ROLLOVER_INTERRUPTED`。最后现金100000元、持仓0、Fill数0。整窗权益/净收益为null，不把空仓无亏损记作整个研究窗收益，也不在新owner自动恢复。

主账户在挂起意图或中途checkpoint条件之前即中断，故此次恢复验证明确为`terminal_checkpoint_only`；不冒充中途继续处理验收。下述全部21个独立owner/场景组合为`in_stream`恢复一致。

## 独立owner结果

每个owner、每种成本场景均独立从100000元开始。以下是各自的净收益率，不合成连续收益、年化或组合净值。三个成本场景重复同3个历史机会，不构成9个独立样本。

| owner | 每场景完整回合 | 基准净收益率 | 双倍手续费 | 双倍滑点 |
| --- | ---: | ---: | ---: | ---: |
| JM2501 | 0 | 0% | 0% | 0% |
| JM2505 | 1 | −0.882999% | −0.895998% | −0.942999% |
| JM2509 | 0 | 0% | 0% | 0% |
| JM2601 | 0 | 0% | 0% | 0% |
| JM2605 | 1 | +0.676293% | +0.662586% | +0.616293% |
| JM2609 | 1 | −1.335306% | −1.350612% | −1.395306% |
| JM2701 | 0 | 0% | 0% | 0% |

0%仅表示相应独立段未成交且空仓结束，不证明策略有防御能力。所有独立段期末持仓为0。

| 有成交owner | 基准最大回撤 | 双倍手续费最大回撤 | 双倍滑点最大回撤 | 基准/双倍费用/双倍滑点总手续费（元） |
| --- | ---: | ---: | ---: | --- |
| JM2505 | 0.882999% | 0.895998% | 0.942999% | 12.999 / 25.998 / 12.999 |
| JM2605 | 4.148043% | 4.154808% | 4.177802% | 13.707 / 27.414 / 13.707 |
| JM2609 | 1.335306% | 1.350612% | 1.395306% | 15.306 / 30.612 / 15.306 |

其他4个owner三场景回撤和费用均为0。回撤取完成1分钟标价权益相对历史峰值的最大降幅，包含浮动盈亏及费用；不是仅在15分钟导出曲线上取点。表内回撤四舍五入到6位小数，JSON保留完整Decimal值。JM2605最终盈利仍经历约4.15%峰值回撤；它与“相对交易日日初权益亏损5%”是不同指标。

## 三笔基准交易与描述性归因

时间均为北京时间；夜盘自然日期和所属交易日分开，持有时间按实际时间差计算。

| 合约/方向 | 入场时刻与价 | 退出时刻与价 | 持有时间 | 毛/净损益（元） | 退出原因 |
| --- | --- | --- | --- | --- | --- |
| JM2505 多1手 | 2025-03-13 21:00，1090.5 | 2025-03-13 22:16，1076.0 | 76分钟 | −870 / −882.999 | 15分钟保护触发后成交 |
| JM2605 空1手 | 2026-02-09 21:00，1148.0 | 2026-03-06 21:00，1136.5 | 25个自然日 | +690 / +676.293 | 日线EMA退出后成交 |
| JM2609 多1手 | 2026-07-09 21:00，1286.5 | 2026-07-09 21:16，1264.5 | 16分钟 | −1320 / −1335.306 | 15分钟保护触发后成交 |

两笔亏损主要对应入场后价格向不利方向运动，费用分别12.999、15.306元，远小于该两笔毛亏损；这是逐笔账目分解，不证明行情机制或因果解释。双倍手续费仅使各笔净损益再减少一份原费用；双倍滑点在本次实际相同成交路径上每个回合再减少60元。三场景成交次数及交易时刻未变，单元边界测试则证明更高成本在其他输入下可以改变准入和成交路径。

本历史只有一笔盈利空单和两笔亏损多单，不能推导空头更有效、总体盈利能力、参数优劣或普遍成本稳健性。

## 风险拒绝：两个分母

每个场景的7个独立段合计观察到28个符合MACD交叉与EMA方向的日线事件，28次信号准入检查，其中24次因`TRADE_RISK_EXCEEDED`拒绝。剩余4次形成候选开仓；4次成交前检查中又拒绝1次，最终3笔开仓。成交前拒绝不混入“24/28”的信号拒绝率，跨成本重复事件不增加样本量。

| owner | 信号检查/拒绝 | 成交前检查/拒绝 |
| --- | --- | --- |
| JM2501 | 1 / 1 | 0 / 0 |
| JM2505 | 5 / 4 | 1 / 0 |
| JM2509 | 2 / 2 | 0 / 0 |
| JM2601 | 6 / 6 | 0 / 0 |
| JM2605 | 5 / 4 | 1 / 0 |
| JM2609 | 7 / 5 | 2 / 1 |
| JM2701 | 2 / 2 | 0 / 0 |

成交前拒绝例：JM2609，2026-04-22 21:01记录检查。基准候选成交价1279.5、保护线1244.5，入场到保护距离35点。预计风险为35×60＋开仓费7.677＋保守退出费7.464＋退出滑点30＝2145.141元，超过当时2000元预算；双倍费用为2160.282元，双倍滑点为2205.141元，均拒绝。EMA外12点不等于入场到保护仅12点，不能为了增加样本静默放松风险预算。

## 身份、复算和验收

冻结数值提交：`f36dd1dd3f1e546cb62639ebb319c2bc8ae98006`。最终本地证据：`output/subing-jm-daily-v1-20261022/phase-c-002.json`，文件SHA256：`6fa7f030d2e78494c99f59bdb7dc47a0d07b1e133d9c7966f1b2f37b3d9572cd`；内容result_hash：`aab8bf93c2bbfcefdb0633562cc2b5a42cf7145a29f214dc4aa4100f24d53a53`。

输入hash：`3f97123a6160c23e52a1e6ad9a3cd719cb0c8729689d0433f549b82bf1abb626`；执行facts hash：`62f33cdbd73855a8a73f77db87a60a26231aaba54e3738231c4caa3529eb99a9`。002绑定四份代码SHA、阶段A/B及执行快照原文件SHA；fresh MDS所选Bar身份与B005完全一致。执行快照采集于2026-10-20，是回溯采集事实，不冒充历史当时已知证据。001为开发期间试跑，保留原状；002绑定已提交数值实现。

实际执行入口（工作目录为任务worktree，使用既有Python环境）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python scripts/research/subing_jm_daily_stress.py --project-env '/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env' --phase-a /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-a-003.json --phase-b /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-b-005.json --facts /Volumes/扩展盘/guiyi-quant-workstation/output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json --output /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-c-002.json
```

输出独占创建，不可直接重用002文件名覆盖。加载使用已有私有配置读取器与只读Catalog事务；provider调用0、行情/Catalog/生产数据库写入0、参数搜索false、auto_order=false。

定向验证命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest -p no:cacheprovider services/quant-api/tests/research/test_subing_jm_daily_stress.py services/quant-api/tests/research/test_subing_jm_daily_model.py services/quant-api/tests/research/test_subing_jm_daily_inputs.py services/quant-api/tests/research/test_subing_jm_daily_preflight.py services/quant-api/tests/test_runtime_shared_tools.py services/quant-api/tests/data_foundation/test_closeout_binding.py -q
```

227 passed，包含13项本轮测试；Ruff通过，secret scan零发现，diff格式检查通过。覆盖基准不变、费用副本不污染、双倍滑点真实影响Fill、成本引起准入变化、Decimal上下文、风险解释、分母区分、跨成本checkpoint拒绝及空仓换月中断。

独立Review通过，无剩余Confirmed Issue。最终002的result/input/code SHA、基准与B005核心输出一致性均经独立复核。另用同目录`verify_phase_c.py`重新经MDS只读加载所选原始1分钟Bar，直接从原始费用快照按合约/交易日/平今平昨重算费用，不调用DailyModel复算账户：21组owner×场景、18笔Fill的严格时序、方向性价格、限价、费用、逐笔毛净PnL、现金及每分钟最大回撤全部一致；验证产物为`phase-c-002-verification.json`。三场景重复同3笔机会，不能把18笔Fill视为18个交易机会。独立段未触发日亏5%停机，本地历史未自然覆盖该行为，仍只具备对应工程边界测试证据。

## 完成边界与最小下一步

阶段C交付成本研究和可解释的历史失败路径；完整连续账户收益仍受换月合同和输入不足阻塞。3个不同交易机会不足以证明策略价值，既不根据少数亏损直接淘汰，也不因一笔盈利晋升。没有OOS、参数稳定性或持续Paper证据。

唯一最小下一步：阶段D先冻结独立验证范围，复核因果时序、prefix及增量一致性，并明确尚未见过的样本来源；本次已经查看的489日不再冒充全新OOS。保持Paper关闭，不以阶段C完成自动进入运行。
