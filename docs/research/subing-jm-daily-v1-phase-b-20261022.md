# JM日线阶段B：独立离线模型与工程验收

状态：离线模型实现、定向测试和本地工程回放完成；不构成盈利、OOS、持续Paper或Runtime证据。规则以[冻结设计](subing-jm-daily-v1-design-20261022.md)为准，输入范围与缺口沿用[阶段A](subing-jm-daily-v1-phase-a-20261022.md)。

## 实现与边界

- `packages/quant-core/guiyi_quant/subing_jm_daily.py`：纯内存Event→DailyModel；复用共享MACD/EMA内核、ExecutionFacts及FeeSchedule，独立实现用户的一手双向政策，没有加减仓、动态周期或新执行基础设施。
- `services/quant-api/app/market_data/subing_jm_daily.py`：只经MDS读取D1/15m/1m，逐一核验489日的物理owner、Session、完整端点、日线前缀、来源指纹及执行快照；无跨周期替代、修复或provider入口。
- `scripts/research/subing_jm_daily.py`：一次离线工程回放、只读事务加载后关闭数据库，再计算账户、重放与输出。仅在阶段A结果目录新建JSON，已有文件不覆盖。

Event为已完成的1m、1d或15m观察。成交发生在严格晚于意图时刻的物理合约1m开始时刻，记录时刻另为该Bar完成时刻。日线先更新EMA保护线，15m作保护检查；同一时刻先处理1m成交与费用、再日线、再15m，通过清仓原因优先级合并为一个意图。日亏与保证金保护不变成新的指标过滤。

资金固定初始100000元；数量为－1/0/1。开仓前与成交前均按当时权益2%检查预计止损损失、开平费用及方向性滑点；一手不满足就拒绝。多单保护EMA21－12、空单EMA21＋12，每日只收紧；不以盘中触价替代15m收盘确认。日亏包含费用及浮亏，达到日初权益5%后清仓停开；跨交易日仍有仓/未决时不解除停机。日线旧交叉挂起到下一完成日线失效，反向清仓后不保留自动反手意图。

换主力即中断当前账户，空仓也不自动继续新合约；持仓时保留旧合约/最后有效标价和清仓意图。只有后续旧合约可执行输入能产生退出Fill。没有期末强制平仓、零成本换月或新合约估值旧仓。未知checkpoint状态、冲突身份、不合理限价和异常账户重放均拒绝。

金额与价格用Decimal且运算上下文固定。checkpoint绑定政策版本与内容hash，恢复时从Fill重放现金、费用、方向和持仓；恢复后的后续事件与连续处理逐值比较。这里的重放是研究模型，不是新建数据库Ledger或Broker对账。

## 冻结身份和真实输入

数值实现提交：`52852de19fbd31d4ca5465cda305b79cda923a20`。模型与政策沿用阶段A独立身份，原公式、原参考交易、旧Paper profile及active配置均未修改。

最终本地证据：`output/subing-jm-daily-v1-20261022/phase-b-005.json`，SHA256：`a293c3c6455766344d7ec0762f629a2b92e119fb29bb1dc02361ecce59d6ef45`。独立复算结果：同目录`phase-b-verification.json`。早期001～004保留，不覆盖或抹去准备失败；开发.env不满足私有读取合同，之后使用既有0600 project.env。

- 请求窗口：2024-10-14～2026-10-19，489个已验证交易日、7个owner、178777个完成事件。
- 输入hash：`3f97123a6160c23e52a1e6ad9a3cd719cb0c8729689d0433f549b82bf1abb626`；执行facts内容hash：`62f33cdbd73855a8a73f77db87a60a26231aaba54e3738231c4caa3529eb99a9`。
- 完整逐段来源分区、代码SHA、阶段A与费用快照原文件SHA均在005.metadata；输入文件前后不变，来源在各段及全加载结束后核对。
- 确认时刻等于Bar完成时刻是明确的历史模型假设；完成Bar的成交量/限价决定模型能否按其open加减1 tick成交，不代表逐tick委托簿或实际数据到达证据。
- RQData调用0、Canonical/Catalog/生产数据库写入0、Paper/Runtime配置修改0。SQLite/构造测试只用于工程验证。

## 连续账户与独立owner诊断

主连续账户处理17344个事件，于2024-12-17 21:01北京时间（所属交易日2024-12-18）观察JM2501→JM2505后中断。首段一笔入场被2%风险预算拒绝，无成交，最后现金100000元、持仓0；整个请求窗收益为null，不把“未亏钱”作为完整收益。中断后的输入没有继续驱动此账户。

为核验已验证窗口中真实多空/费用路径，另对7个owner各从独立100000元空仓开始作工程诊断，不拼接、累计或复利成一个账户：

| 独立物理owner | Fill数 | 完整回合 | 方向 | 期末仓位 |
| --- | ---: | ---: | --- | ---: |
| JM2501 | 0 | 0 | 无成交 | 0 |
| JM2505 | 2 | 1 | 多 | 0 |
| JM2509 | 0 | 0 | 无成交 | 0 |
| JM2601 | 0 | 0 | 无成交 | 0 |
| JM2605 | 2 | 1 | 空 | 0 |
| JM2609 | 2 | 1 | 多 | 0 |
| JM2701 | 0 | 0 | 无成交 | 0 |

每个独立owner在首个挂起意图或处理中途导出checkpoint后恢复，继续同一后续事件序列，最终结果与未中断处理逐值相等。005与004的数值摘要、逐笔Fill及独立诊断也逐字一致；最终005额外绑定已提交的数值代码。

独立复算6笔Fill：全部一手、严格后续时刻、方向性1 tick、价格对齐tick、非零量及限价范围通过；直接从原费用快照按合约/交易日/开仓平今平昨重算每笔费用，并核对每段现金、总费用及完整回合净损益。这里只证明工程路径，3个回合不足以证明策略有效。

## 实际验证

定向命令（在数值实现工作区，使用既有Python环境；不写工作区缓存）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest -p no:cacheprovider services/quant-api/tests/research/test_subing_jm_daily_model.py services/quant-api/tests/research/test_subing_jm_daily_inputs.py services/quant-api/tests/research/test_subing_jm_daily_preflight.py services/quant-api/tests/test_runtime_shared_tools.py services/quant-api/tests/data_foundation/test_closeout_binding.py -q
```

214 passed；Ruff通过、任务文件secret scan零发现。覆盖多空费用镜像、严格时序、EMA等价边界、只收紧、2%权益变化与跳空拒绝、保证金不足、5%边界、平今平昨、日切停机恢复、零量/限价未成交、旧仓和空仓换月中断、重复身份、现金重放、未知checkpoint、UTC顺序、Decimal上下文及共享私有配置兼容。

必要兼容修复：严格private_settings读取器未识别正式配置中已存在的`GUIYI_NEWOW_FUTURES_RESULTS_ROOT`。只把该纯结果目录字段加入既有忽略集合，不扩展依赖设置、不执行其值，也不允许通过它展开DATABASE_URL；原权限/owner/链接检查保持。169项共享工具及closeout测试通过；未修改任何实际配置或凭据。

独立Review确认并修复了初版空仓跨owner仍继续运行的问题。代码Review与独立214项回归通过；005最终代码/输入SHA与result_hash、6笔费用和3回合毛净PnL也独立复核通过，无剩余Confirmed Issue，允许集成develop。

集成时develop另有四统一日线研究提交858627112；在隔离任务工作区合并后，连同其23项相关测试共237 passed。四份数值依赖SHA与005仍完全相同，未重复伪造新的数值验收。主工作区其他任务的未提交Reference改动不在本次提交或清理范围内。

## 验收与下一步

阶段B允许集成develop，不发布、不切运行副本、不启用持续Paper。430日执行事实缺失与11个换月退出输入缺口保持；本轮未补数据、未做阶段C成本压力或阶段D独立验证。唯一最小下一步是按冻结规则开展阶段C成本压力及失败原因研究，继续把中断账户和独立owner诊断分开。
