# Unified Reference Trading P2 剩余实现与交接计划

> 执行方式：新的 Terra Medium 任务使用 executing-plans 连续完成剩余 P2，包含独立 Review、修复与验证后 develop 集成。本文件优先说明剩余范围，不重做已通过的工作。

**Goal:** 在现有逐 Bar 改造上补齐完整策略 checkpoint、输入顺序/幂等/失败原子性，以及苏冰/Newow实际参考投影到公共 reducer 的唯一计算路径。

**Spec:** [P2完整计划](2026-09-19-unified-reference-trading-p2-plan.md)、[总设计](../specs/2026-09-19-unified-reference-trading-design.md)、`openspec/specs/reference-trading/spec.md`。

## 1. 精确交接事实

2026-09-19核对：

- P0/P1已集成点 `e69f026dee887f4f12a2ccf6adaaa4f9c76de4aa`。
- P2部分成果分支 `codex/unified-reference-trading-p2`，本地与远端记录的HEAD为 `1974cfe68a184dfdbec92c63f1a3f8023b822430`。
- 该分支包含 `bb75a5a80`（typed completed bars / 公共checkpoint）及 `1974cfe68`（共用逐Bar replay）。
- 原任务worktree `/Users/zhangzhao/.codex/worktrees/bd0f/guiyi-quant-workstation` 已核对干净；原任务不再运行。
- 原任务报告最后定向回归299 passed，仍明确PARTIAL、未合入develop。新任务须自己复验，不把交接报告当新提交测试证据。
- 主树当前 `a23475c3d08debabc416f1300c8b58e0984c7ab4`，develop领先origin/develop 4提交，另有周线计划与outputs未跟踪，均不是本任务可清理内容。

新任务必须独立worktree，从上述P2提交建立新的 `codex/` 分支；不要检出占用中的原分支，不在原worktree继续写。
创建工具若先从项目默认分支初始化，在干净新树内再建立正确基线。已有分支结果与最新develop的冲突须保留双方语义后解决。
禁止reset/clean、force push，禁止为本任务顺带推送不属于本任务的主树提交。

## 2. 已有资产与真正缺口

| 已有资产 | 保留并复验 | 剩余 |
|---|---|---|
| 公共typed completed input、return policy、codec | 原分支contracts/reducer/checkpoint与测试 | 不能据此宣称完整strategy checkpoint或严格验证已完成 |
| Newow seed_replay_state/replay_step | 三策略共用step、预热marker释放修复 | state目前可变、输入顺序交给caller；补适配层验证、失败原子性及恢复 |
| 苏冰逐Bar state | 四周期原projection复用step、Decimal上下文修复 | 完整指标/配对状态恢复，所有动作实际进入公共reducer |
| 现有projector/统计 | 保留对外接口、ID、Hint、指标、收益和诊断 | Newow/苏冰旧配对不能与公共状态机并存为两套active实现 |

## 3. R0：接收基线和验证清单

- [x] 新树检查AGENTS、HEAD/dirty、最新develop和并发任务；复制本文件到同相对路径并提交，原主树文件保留。
- [x] 确认上述两提交已包含，检查现有P2原计划与主树未跟踪版本一致再决定是否复制，不能覆盖任务已有更改。
- [x] 跑原P2计划测试入口，固定旧基线fixture oracle，输出差异清单；不重录golden掩盖行为变化。
- [x] 逐项核对实际source ID、Decimal政策、计龄、缺价/换月与原公共reducer衔接问题，已修项只补缺失验证，不重复改造。

出口：新工作从已验证部分成果起步，未触碰其他任务文件。

## 4. R1：真正可恢复、严格的策略状态

实现位置：现有 `reference_trading/adapters.py` / `checkpoint.py` 及必要策略专用适配文件；复用原指标step。

### 状态和输入合同

- 泛型/具体typed adapter替代object占位；包含immutable或copy-on-write策略状态、reference state、stream identity、owner/calculation segment、有效输入水位、最近输入完整fingerprint、预热/配对资格。
- Subing保存MACD/EMA及previous差值、计数、owner资格、当前entry关联；Newow保存实际策略state、pairing、escape/hint关联、initial-clear资格与声明的有界滚动窗口。
- 独立保存指标预热位置与owner内正式进度；多个owner的预热时间重叠不倒退正式水位，也不在owner外生成交易。
- fingerprint覆盖所有影响结果的输入字段：OHLC/Close、物理身份、Bar instant、交易日、周期、owner/quality边界、lifecycle证据身份；不能只hash信号或最新Close。

### 增量与异常规则

- 完全相同末输入重放不重复指标step或输出；相同身份不同内容冲突；更旧有效输入拒绝，不自动回退修订。
- 校验完成后才发布新state；内部step如果可变，工作副本只复制有界计算状态，任一中途错误不能修改原checkpoint。
- 同Bar有序动作的未sealed/已sealed规则沿canonical；不得为了避开watermark检验把正式Bar拆出无法证明的时序。
- 新合约/新计算段只通过显式权威边界转换；不通过Bar自带字符串变化偷偷跨合约持仓。

### JSON恢复

- 在现有ReferenceState codec之外增加完整adapter state envelope，记录schema、策略/周期/版本、stream hash、输入进度与必要状态。
- 严格字段白名单及嵌套结构校验；JSON重复key、额外/缺失字段、字符串假数组、bool假整数、非有限float/Decimal、无时区、错误enum/版本均拒绝。
- decoder接受expected stream/schema/公式身份并交叉核对；核对OPEN entry/计龄/mark/水位/owner一致性，不能仅凭外层schema正确就信任内部状态。
- float指标保持原数值语义，Decimal用string；不使用pickle、动态import、eval或任意类反序列化。
- 校验和用于发现损坏而非宣称防恶意伪造；不增加无需求的签名/密钥基础设施。
- round-trip后能在预热、OPEN、反手、质量段切换后继续，重启不回放无界前缀。

出口：增加 `test_adapter_input_order.py`、扩展 `test_checkpoint_parity.py`，覆盖乱序、幂等、无信号、identity漂移、异常不污染原状态及严格负向输入。

## 5. R2：苏冰实际接公共 reducer

- [x] 保留现有Subing kernel step与state，适配它的信号为稳定、显式关联的OPEN/CLOSE动作；同一反手signal允许两个不同action身份。
- [x] reducer成为开/平/中断/估值状态的唯一计算入口；旧projection仅累积delta并转换旧字段/ID/summary，不再独立配对交易。
- [x] SAME_DIRECTION旧信号仍可展示，但不能再次OPEN；无信号Bar仍推进状态和持有计龄。
- [x] 保留苏冰`(exit-entry)/entry`政策、四周期formula identity和D1质量v2，保持既有信号/交易ID。
- [x] 验证entry/close/反手Bar计龄、最后OPEN mark、中断null、期初归属、指标readiness与固定窗口统计。

出口：四周期旧oracle逐值一致；测试spy证明旧public projector实际经过公共reducer，而非只保留一个未使用的适配入口。

## 6. R3：牛哇三策略实际接公共 reducer

- [x] 复用已抽取replay_step，保留chart/replay的底层依赖方向，避免chart依赖reference应用层。
- [x] 将BUILD/CLEAR映射到公共动作，价型保持趋势慢线B/震荡Low-High/主升浪MA45；保留Newow `exit/entry-1`政策。
- [x] 生命周期证据约束INITIAL_CLEAR_NO_ENTRY；HINT关联和未分配Hint仍输出，但不影响交易数量。
- [x] 正确组织owner/warmup/quality边界的Bar级fold，保持同Bar动作与边界顺序以及换月中断。
- [x] 原ReferenceTradeProjector.project改为同一适配/reducer的全量组合与旧DTO转换，删除重复配对状态机。
- [x] 保留summary统计算法与公开trade/signal ID；不把新内部ID泄漏到旧页面。

出口：三策略×现有允许周期的fixture parity；chart相关回归不变；未开放周期不自动开放。

## 7. R4：统一的完成证据

新增或扩展 `test_strategy_parity.py`、`test_adapter_incremental.py` 和checkpoint/输入顺序测试。

| 验证 | 必须证明 |
|---|---|
| 全量/逐Bar/多种切批 | 动作、交易状态/ID、价格、收益、计龄、Hint、诊断与统计一致 |
| 恢复 | 每个关键Bar JSON恢复后的尾部结果等于不中断计算，禁止只测P1 ReferenceState |
| 无信号重放 | 不二次推进kernel/计龄；同identity换输入必须拒绝 |
| 窗口 | 更改显示since/through不改变底层预热与合法entry配对 |
| 历史修订 | 从修订前checkpoint重算到最新与全量相同；P2不实现自动侦测/调度 |
| 复杂度 | step计数随新增Bar增加；checkpoint不包含全历史输出，已闭合历史marker不无限积累 |
| 冻结oracle | 来自固定基线与既有fixture，不能用新实现自己生成expected再比较自己 |
| reducer接入 | 两个旧public projector均实际调用公共迁移，删除另一个active开平配对循环 |
| 失败原子性 | 有效前缀后接非法Bar/动作，抛错后调用者原state深层对象也不变 |

原报告299 passed只证明当时部分代码；最终运行完整原P2定向组，并按改动扩到reader/product service/API。
独立Review必须审查上述完成出口、JSON跨字段校验、时序、数值政策、并发develop兼容；修复后复验。

## 8. R5：集成与收尾

- [x] 新分支commit/push，保护原分支历史；不force，不改原任务worktree。
- [x] 当前主树领先origin且存在他人文件，集成时核对提交归属与最新develop；不能顺带push不属于本任务且授权不明的提交。
- [x] 可安全集成时按仓库流程集成并对合并结果复验；确有共享状态冲突则保持已完成候选，明确集成剩余事项，不自行覆盖。
- [x] 处理主树同名未跟踪计划时先逐字比较，内容一致可按既有任务文档流程纳入；不删除/覆盖周线计划或outputs。
- [x] 更新P2实际完成状态；不宣称P3持久化、后台worker、API迁移、生产启用或HTDY模型完成。

完成证据：候选分支和本地develop合并结果均通过545项联合回归、Ruff、OpenSpec 10/10、secret scan与
diff check；独立Review关闭全部Critical/Important后给出允许集成develop。develop因原有4个非本任务
提交尚未推送，仅完成本地集成；本任务没有顺带push develop。

P2完整出口是R1–R4和独立审查通过，不能在仅补checkpoint/推送分支后主动结束为“剩余以后再做”。
本轮只允许普通开发、测试、Review及条件满足的develop集成；不含生产RQData/Canonical/DB/Redis/通知、main/tag/release/Runtime。
