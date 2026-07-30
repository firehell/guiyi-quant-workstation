# 归一量化：暂停 S6-10 后的渐进式核心收口 Codex 顺序执行手册

> 文档状态：用户决策已确认，作为后续 Codex 串行执行依据
> 决策日期：2026-07-30
> 项目：`firehell/guiyi-quant-workstation`
> 实施方案：方案 B——渐进式核心收口
> 当前业务范围：只保留焦煤 `jm`，不扩展全品种
> 当前策略范围：保持 HTDY 既有精确实时观察语义，不接入苏冰新策略
> 当前 S6-10 决策：暂停旧 S6-10 的后续外部 Gate、部署和真实验收；核心架构收口完成后重新设计并重启 S6-10
> 当前验收时长：后续 Shadow 与新版 S6-10 均只要求一个完整 DCE 交易日
> 事实源要求：Codex 每次执行前必须重新读取当前 GitHub HEAD，不得把本文中的日期、SHA 或阶段描述当作永久事实

---

# 0. 本文用途

本文是后续 Codex 开发的唯一顺序执行手册，用于把当前较复杂的 JM Runtime、数据读取、HTDY、SignalEvent、企微和阶段性 Gate 收口为更适合个人项目长期维护的核心架构。

本文不是让 Codex 在一个会话里完成全部任务。固定规则为：

```text
一个可独立集成的任务
= 一个 Codex 会话
= 一个 task branch/worktree
= 一个 PR 或明确的 develop 集成记录
```

任何任务完成后，Codex 必须停止。只有用户明确给出下一步结论，才允许进入后续任务。

后续单交易日验收的统一定义为：

```text
一个完整 DCE 交易日
= 夜盘 + 三段日盘
+ 23 个权威 confirmed 15m 收线桶
+ EOD passed
+ SignalEvent/notification identity 幂等
+ 正式写入 allowlist 外零写入
```

验收窗口中任何代码、policy、schema、ObservationPlan、ReleaseManifest、Runtime deployment
或配置发生变化，或者任一必需桶、EOD、幂等或零非法写入检查失败，整日窗口立即失败。必须
停止、保留失败 evidence、完成修复及新的 release/promotion 后，从下一个完整 DCE 交易日
重新开始；禁止现场热修后继续累计。单日 Ledger 和失败记录只能 append-only，不得删除、
覆盖或改写。

恢复能力使用“单日自然运行 + 同一 exact release 的独立恢复证据”验证。Runtime 进程重启、
RQData/网络短暂故障和 Mac 重启可在验收日前后按获批矩阵单独执行，不要求全部塞入同一个
交易日；所有恢复证据必须与该单日验收绑定同一 exact release、配置和 DB revision。

`LONG_RUNNING_READY=false` 仅作为兼容字段保留，状态固定为
`deprecated / not_applicable`，任何单交易日 Gate 都不得将其设为 true。只有单日自然运行、
同一 exact release 的独立恢复证据、独立 Review 均通过，且用户最终批准后，才可发布
`JM_RUNTIME_READY`；该状态仍不代表盈利、自动通知或自动交易。

允许使用的用户结论固定为：

```text
允许继续实现
允许集成 develop
要求修正后再集成
允许进入 Shadow
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
允许重启 S6-10
阻塞
```

---

# 1. 当前决策与事实边界

## 1.1 为什么暂停旧 S6-10

当前旧 S6-10 已经出现多轮代码修正、部署前置依赖、C2/Approval D、mapping freeze、daily child、Runtime identity、receipt 和恢复链相互耦合的问题。小范围修改会引起重新生成 packet、重新绑定、重新部署或重新验证，已经偏离个人研究工作站的维护目标。

暂停不是删除历史，也不是宣布旧 S6-10 失败，而是：

```text
停止继续扩大旧控制面
冻结现有代码和失败/通过证据
不再生成新的 S6-10 C2 / Approval D / daily child
不执行新的 S6-10 Runtime 部署和 mapping 真实写入
不继续追发旧事件或旧企微
先完成核心架构收口
然后基于新 Runtime 重新设计简化版 S6-10
```

旧 S6-10 的代码、task contract、失败 evidence、receipt 和 Git 历史必须保留，不能为了精简而直接删除。

## 1.2 当前必须保留的业务语义

以下能力不得在收口过程中削弱：

- RQData 是唯一正式 provider；
- 主连与实际主力合约分离；
- `MainContractMap.rank=1` 是 JM 当前实际主力的正式解析基础；
- historical 与 live 数据分层；
- 1m 是正式基础分钟周期，5m/15m/30m/60m/1d 从可信 1m 聚合；
- 夜盘、午休、交易日归属由 TradingCalendar/TradingSession 处理；
- 普通策略只消费已确认收线 bar；
- HTDY original 仍是精确白名单下的 realtime first-seen、允许重绘、首次冻结、不撤回观察；
- 同一信号必须幂等；
- SignalEvent 与企微发送事实必须分离；
- 数据版本、checksum、coverage 和质量状态必须可追溯；
- 不修改 report 14/15；
- 不做自动交易；
- release 和 Runtime promotion 保持两个独立人工 Gate。

## 1.3 本轮明确不做

- 不扩展其他品种；
- 不筛选或删除全品种历史数据；
- 不接入苏冰正式 Runtime；
- 不建设 Research Memory；
- 不做 AI 训练或 AI 辅助判断；
- 不退出 Redis/RQ；
- 不删除 Profile 数据表；
- 不重排现有 Parquet 物理目录；
- 不修改 HTDY 公式、Golden、Stage 5 结论或 first-seen 语义；
- 不恢复旧 dispatcher、`scripts/ai/*` 或旁路状态源。

---

# 2. 总体执行顺序

必须严格串行执行：

```text
GY-CORE-00  暂停 S6-10 与事实冻结
    ↓
GY-CORE-01  全仓架构与 scripts 只读盘点
    ↓
GY-CORE-02  ActiveDatasetResolver + MarketDataService 兼容 Facade
    ↓
GY-CORE-03  统一 CLI 与旧入口兼容 Shim
    ↓
GY-CORE-04  ObservationPlanRegistry + StrategyAdapter
    ↓
GY-CORE-05  JM 新 Runtime 只读 Shadow 实现
    ↓
GY-CORE-06  单交易日 Shadow 执行与独立 Review
    ↓
GY-CORE-07  ReleaseManifest、正式切换与 Runtime promotion
    ↓
GY-CORE-08  旧入口归档、删除候选和 canonical 收口
    ↓
GY-S6-10-R2  基于新架构重新设计 S6-10
    ↓
GY-S6-10-R2-RUN  新版 S6-10 单交易日真实验收
```

禁止并行开发以下高冲突路径：

- `GY-CORE-02` 与另一个数据选择重构；
- `GY-CORE-04` 与 HTDY 公式修改；
- `GY-CORE-05/06` 与旧 S6-10 部署；
- `GY-CORE-07` 与其他 Runtime/release 任务；
- `GY-CORE-08` 与尚未完成的正式切换；
- 新版 S6-10 与旧 S6-10 外部 Gate。

---

# 3. 总任务矩阵

| 顺序 | 任务 ID | 任务 | Lane | 执行入口 | 模型 | 推理等级 | 会话 | Plan | 人工 Gate | 当前状态 |
|---:|---|---|---|---|---|---|---|---|---|---|
| 0 | `GY-CORE-00` | 暂停 S6-10 与事实冻结 | Lane 2 | Codex App | **Sol** | **高** | 新会话 | **Plan-then-execute** | 文档/状态 Review | **已完成（PR #65）** |
| 1 | `GY-CORE-01` | 全仓架构与 scripts 只读盘点 | Lane 2 | Codex App | **Sol** | **高** | 新会话 + 独立 Review | **Plan-only** | Plan 批准 / 独立 Review | **已完成（PR #66）** |
| 2 | `GY-CORE-02` | 数据选择与统一 MarketData Facade | Lane 3 | Codex App | **Sol** | **高** | 新 Plan 会话 + 实现会话 + 独立 Review | **Plan-only → 批准后实现** | Plan 批准 / 独立 Review | **已合入 develop（PR #68）；CODE_COMPLETE_EXTERNAL_GATE_PENDING** |
| 3 | `GY-CORE-03` | 统一 CLI 和兼容 Shim | Lane 2 | Codex App | **Terra** | **中** | 新会话 | **Plan-then-execute** | 正常 Review | **已合入 develop（PR #69）；CODE_COMPLETE_EXTERNAL_GATE_PENDING** |
| 4 | `GY-CORE-04` | ObservationPlan 与 StrategyAdapter | Lane 2 | Codex App | **Terra** | **中** | 新会话；HTDY 专项 Review | **Plan-then-execute** | HTDY 边界 Review | **已合入 develop（PR #70）；CODE_COMPLETE_EXTERNAL_GATE_PENDING** |
| 5 | `GY-CORE-05` | JM 新 Runtime 只读 Shadow 实现 | Lane 3 设计 / Lane 2 只读实现 | Codex App | **Sol** | **高** | 新 Plan 会话 + 实现会话 | **Plan-only → 批准后实现** | Plan 批准 / 独立 Review | **下一入口：Plan-only** |
| 6 | `GY-CORE-06` | 单交易日 Shadow 执行和分析 | 受控只读运行 | Codex App + CLI automation | **Terra（日常执行）/ Sol（最终 Review）** | **中 / 高** | 日常执行会话 + 独立 Review | **Plan-then-execute** | 真实 Shadow 运行批准 | 等 05 集成 |
| 7 | `GY-CORE-07` | 正式切换与 Runtime promotion | Lane 3 | Codex App + CLI automation | **Sol** | **高** | 新实现会话 + 独立 Review | **Plan-only** | Plan / release / Runtime / 写入批准 | 等 06 通过 |
| 8 | `GY-CORE-08` | 旧入口归档和 canonical 收口 | Lane 2 | Codex App | **Terra 执行 / Sol Review** | **中 / 高** | 新会话 + 独立 Review | **Plan-then-execute** | 删除范围 Review | 等 07 稳定 |
| 9 | `GY-S6-10-R2` | 新版 S6-10 设计与代码 | Lane 3 | Codex App | **Sol** | **高** | 新 Plan 会话 + 独立 Review | **Plan-only → 批准后实现** | Plan 批准 | 等 08 集成 |
| 10 | `GY-S6-10-R2-RUN` | 新版单交易日真实验收 | Lane 3 | Codex App + CLI automation | **Sol** | **高** | 新执行会话 + 独立 Review | **Plan-then-execute** | 真实运行 / 故障注入 / 最终批准 | 等 R2 代码批准 |

模型升级规则：

```text
Terra 连续两轮仍未解决
或发现跨三个以上模块
或触及数据选择、幂等、恢复、Runtime、contract 变化
→ 停止原会话
→ 新开 Sol 高推理会话重新分析
```

---

# 4. 通用 Codex 工作方式

每个任务都必须执行：

```text
1. 读取 STATUS.md
2. 读取 AGENTS.md
3. 读取 README.md 和 TESTING.md
4. 读取 PROJECT_SOURCE.md
5. 读取 DECISIONS.md
6. 读取本手册
7. 读取任务相关 canonical / Issue / PR / task contract / evidence
8. 核对 Git branch、HEAD、worktree、dirty state 和 Runtime 身份
9. 只执行当前一个任务
10. 运行定向测试和 engineering Gate
11. 自审 diff
12. 输出 PR/集成建议
13. 停止，不自动进入下一任务
```

## 4.1 Worktree 规则

普通任务：

```text
develop
→ task branch/worktree
→ PR/Review
→ develop
→ 确认已集成后清理 task worktree 和 branch
```

高风险发布：

```text
task branch/worktree
→ develop
→ release candidate
→ release PR to main
→ 用户批准
→ main + annotated tag
→ 用户再次批准 Runtime promotion
→ runtime worktree detached at exact tag
```

约束：

- worktree 是目录，branch 才是合并对象；
- 不在 main/develop worktree 直接开发；
- 先运行 `scripts/engineering/worktree_flow.py` dry-run；
- GitHub 私有仓库规则 API 为 403 时，合规 Lane 1/2 task 可自动完成测试、commit、push 和
  draft PR；用户手动转 ready 并 merge；
- 不自动 merge、deploy、tag；
- release 批准与 Runtime promotion 批准必须分开；
- 任何真实写入均不得继承旧 S6-10 授权。

## 4.2 每个任务完成后 Codex 必须输出

```text
修改摘要
变更文件
测试命令与结果
数据/Runtime/通知写入情况
PR 或 develop 集成结果
worktree/branch 清理状态
风险与未完成项
推荐用户结论
```

---

# 5. `GY-CORE-00`：暂停 S6-10 与事实冻结

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新开会话**
- Plan：**Plan-then-execute**
- 工作区：**新 docs task worktree**
- 人工 Gate：**文档和状态 Review**

### 目标

把用户已经确认的暂停决策写入 GitHub 事实源，并冻结旧 S6-10 当前状态，防止 Codex 或后续任务继续生成新 C2、Approval D、daily child、mapping write、部署或真实事件。

### 允许修改

- `STATUS.md`
- `DECISIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/tasks/JM-LIVE-STABILITY-S6-10.md`
- `docs/tasks/README.md`
- `docs/tasks/V1-FINAL-ACCEPTANCE-S6-11.md`
- 新增一个核心收口总任务契约，例如：
  `docs/tasks/GY-CORE-CONVERGENCE.md`

### 必须表达

```text
S6-10_PAUSED_BY_OWNER_FOR_CORE_CONVERGENCE
LONG_RUNNING_READY=false
旧 C2 / Approval D / daily child 不再继续执行
不生成 fresh S6-10 authorization
不执行 S6-10 mapping/deployment/notification
旧证据保留且不可改写
恢复入口为 GY-S6-10-R2，而不是继续旧合同
新版验收只需一个完整 DCE 交易日
覆盖夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、幂等和零非法写入
单日失败整日重启；Ledger append-only
LONG_RUNNING_READY=false 是 deprecated/not_applicable 兼容字段
JM_RUNTIME_READY 只在独立恢复证据、独立 Review 和用户最终批准后发布
```

### 禁止

- 修改产品代码；
- 修改 migration；
- 写 PostgreSQL、Parquet 或 Runtime 配置；
- 启动、重启或停止生产 Runtime；
- 生成新的 packet/receipt；
- 发送企微；
- 删除旧 S6-10 evidence；
- 宣布 V1/S6-10 Ready。

### 验收

- `STATUS.md`、`DECISIONS.md`、task contract 三者一致；
- 架构、Signal 与 S6-11 active canonical 已同步单交易日和 Ready 语义；
- 原失败证据和旧历史状态未改写；
- 明确下一步唯一入口为 `GY-CORE-01`；
- 文档扫描没有同时出现“继续旧 S6-10”和“暂停”两个 active 结论；
- `git diff --check`、docs test、secret scan 通过。

### 可复制 Codex Prompt

```text
请先阅读 STATUS.md、AGENTS.md、README.md、TESTING.md、PROJECT_SOURCE.md、
DECISIONS.md、docs/tasks/JM-LIVE-STABILITY-S6-10.md、docs/tasks/README.md，
以及《归一量化：暂停 S6-10 后的渐进式核心收口 Codex 顺序执行手册》。

本任务为 GY-CORE-00，Lane 2，Sol 高推理，Plan-then-execute。

用户已决定暂停旧 S6-10，先完成渐进式核心架构收口，再重新设计并启动 S6-10。

目标：
只更新项目事实源和任务契约，冻结旧 S6-10 当前状态。

必须写清：
- S6-10_PAUSED_BY_OWNER_FOR_CORE_CONVERGENCE；
- LONG_RUNNING_READY=false；
- 不再生成 fresh C2、Approval D、daily child；
- 不执行新的 mapping/deployment/Runtime/notification；
- 已有失败/通过 evidence、receipt、Git 历史保持不变；
- 下一唯一执行入口为 GY-CORE-01；
- 后续以 GY-S6-10-R2 重启，而不是继续旧合同。
- 新版只验收一个完整 DCE 交易日，覆盖夜盘、三段日盘、23 个 confirmed 15m 桶、EOD、
  幂等和零非法写入；
- 单日失败整日重启，Ledger append-only；
- 恢复由同一 exact release 独立 evidence 验证；
- LONG_RUNNING_READY=false 固定为 deprecated/not_applicable；
- JM_RUNTIME_READY 仅在独立 Review 与用户最终批准后发布。

允许修改：
STATUS.md、DECISIONS.md、docs/ARCHITECTURE.md、docs/SIGNAL_EVENTS.md、
docs/tasks/JM-LIVE-STABILITY-S6-10.md、docs/tasks/V1-FINAL-ACCEPTANCE-S6-11.md、
docs/tasks/README.md，并可新增 docs/tasks/GY-CORE-CONVERGENCE.md。

禁止修改产品代码、migration、DB、Parquet、.env、Runtime、企微、main/tag。
不得生成 packet/receipt，不得宣布任何 Ready。

完成后运行 docs/engineering 验证，并输出变更摘要、测试、风险和推荐用户结论。
```

### 用户通过结论

```text
允许集成 develop
```

---

# 6. `GY-CORE-01`：全仓架构与 scripts 只读盘点

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新开会话 + 新开独立 Review 会话**
- Plan：**Plan-only**
- 工作区：**新 task worktree**
- 人工 Gate：**Plan 批准 / 独立 Review**

### 目标

获得真实调用图和删除边界，为后续收口提供唯一事实基础。

### 必须输出

1. 历史数据同步调用链；
2. EOD 自动增量调用链；
3. live ingest / aggregation 调用链；
4. 主力映射调用链；
5. HTDY evaluator/writer 调用链；
6. SignalEvent 与企微调用链；
7. Web/API 数据消费调用链；
8. Runtime install/start/restart/deploy/recovery 调用链；
9. `scripts/` 全量分类：
   `KEEP / MERGE / MOVE / ARCHIVE / DELETE_CANDIDATE / UNKNOWN`；
10. launchd、Makefile、CI、shell、Python import、canonical 和测试引用；
11. `GY-CORE-02～08` 的精确文件范围、依赖和冲突矩阵。

### 判定标准

| 分类 | 含义 |
|---|---|
| KEEP | 当前正式运行唯一依赖，业务名称稳定 |
| MERGE | 与其他入口重复，应合入统一 CLI |
| MOVE | 内含可复用业务逻辑，应迁入/保留 services |
| ARCHIVE | 只服务阶段性验收，退出 active 入口 |
| DELETE_CANDIDATE | 已替代且无引用，Review 后可删 |
| UNKNOWN | 无法确认，必须保留并阻塞删除 |

### 禁止

- 修改产品代码；
- 删除或移动脚本；
- 修改 Runtime；
- 写 DB/Parquet；
- 恢复旧 S6-10；
- 提前设计多品种、苏冰、AI。

### 可复制 Codex Prompt

```text
请先阅读项目 canonical、GY-CORE-00 已集成结论、
《归一量化：暂停 S6-10 后的渐进式核心收口 Codex 顺序执行手册》，
以及所有与 JM data/runtime/signal/notification 相关的 task、PR 和 evidence。

本任务为 GY-CORE-01，Lane 2，Sol 高推理，Plan-only。

目标：
只读盘点当前仓库的真实业务调用链和 scripts 全量依赖，
形成后续渐进式核心收口的精确实施 Plan。

必须输出：
1. historical sync、EOD、live ingest、aggregation、dominant mapping、HTDY、
   SignalEvent、WeCom、Web/API、deployment/recovery 的真实调用图；
2. scripts 全量 KEEP/MERGE/MOVE/ARCHIVE/DELETE_CANDIDATE/UNKNOWN 分类；
3. launchd、Makefile、CI、shell、Python import、测试和 canonical 引用；
4. Profile、Redis/RQ、packet/receipt/rebind 的真实依赖边界；
5. GY-CORE-02～08 的精确文件清单、测试矩阵、冲突矩阵和回滚计划；
6. 所有 UNKNOWN 和阻塞项。

禁止任何产品代码、数据、Runtime、通知或 Git 发布写入。
禁止继续旧 S6-10。

只提交审计文档和 Plan，不执行实现。
```

### 用户通过结论

```text
允许继续实现
```

若存在重要 UNKNOWN：

```text
阻塞
```

---

# 7. `GY-CORE-02`：ActiveDatasetResolver 与 MarketDataService Facade

## Codex 调度建议

- 任务车道：Lane 3（active 数据选择）
- 执行入口：Codex App
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新 Plan 会话 + 新实现会话 + 新开独立 Review 会话**
- Plan：**Plan-only → 用户批准后实现**
- 工作区：**新 task worktree**
- 人工 Gate：**Plan 批准 / 独立 Review**

### 目标

在不改变现有数据选择结果的前提下，为 Web、指标、回测、策略和后续 Shadow Runtime 提供统一 Python 领域服务。

### 新增边界

```text
ActiveDatasetResolver
MarketDataService
DatasetDescriptor
BarsResult
```

第一阶段实现必须是兼容 Facade：

```text
新 Facade
→ 调用现有 Profile/MarketDataFile/reader
→ 返回统一 Descriptor/Result
```

不得立即删除 Profile 或重写 Parquet 读取算法。

### 首批范围

仅覆盖 JM：

- `jm.MAIN` continuous historical；
- 当前实际主力 actual historical；
- live 1m/15m 只读；
- strict/browser；
- historical/live；
- 先迁移一个只读 caller。

### 必须证明等价

- profile/file ID；
- contract role；
- actual contract；
- period；
- quality status；
- data version；
- checksum；
- coverage；
- bar key、row count 和 OHLCV；
- warning/failed 处理；
- lineage token 或兼容 identity。

### 禁止

- migration；
- DB/Parquet 写入；
- 修改 report 14/15；
- 修改策略公式；
- 部署 Runtime；
- 静默选择最新文件；
- 静默降级 provider。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-01 最终 inventory、当前 canonical 和本顺序执行手册。

本任务为 GY-CORE-02，Lane 3，Sol 高推理。第一阶段只输出 Plan，用户批准后再在独立实现
会话执行。

目标：
在不改变现有数据选择和 lineage 语义的前提下，实现：
- ActiveDatasetResolver
- MarketDataService
- DatasetDescriptor / BarsResult

要求：
- 仅 JM；
- 第一阶段只做兼容 Facade；
- 复用现有 Profile、MarketDataFile、quality、version、checksum 和 reader；
- 先迁移一个只读 caller；
- 新旧结果逐字段、逐 bar 对照；
- 无唯一合法资产时 fail-closed；
- 不删除 Profile，不重排 Parquet。

禁止 migration、DB/Parquet 写入、Runtime 部署、策略修改、report 14/15 修改。

完成后输出新旧等价矩阵、测试、PR/集成建议和风险。
```

### 用户通过结论

Plan 后：

```text
允许继续实现
```

实现和独立 Review 后：

```text
允许集成 develop
```

---

# 8. `GY-CORE-03`：统一 CLI 与旧入口兼容 Shim

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：**Terra**
- 推理强度：**中**
- 会话：**新开会话**
- Plan：**Plan-then-execute**
- 工作区：**新 task worktree**
- 人工 Gate：**正常 Review**

### 目标

将用户和 Codex 的正式入口收口为少量稳定命令，业务算法继续位于 `app/services/`。

目标 CLI：

```bash
guiyi data sync
guiyi data eod
guiyi data verify
guiyi runtime plan
guiyi runtime once
guiyi runtime status
guiyi notify preview
guiyi backup create
guiyi backup restore-check
guiyi dev preflight
guiyi dev test
```

### 本任务首轮只实现

- CLI 主骨架；
- `data verify`；
- `runtime status`；
- 一个 `dry-run` 样板；
- 1～2 个旧脚本转为兼容 Shim；
- 参数、退出码和 JSON 输出兼容测试。

不得一次迁移全部脚本。

### 原则

```text
CLI = 参数解析和调用编排
Service = 业务算法
```

### 禁止

- CLI 重新实现 ingest、aggregation、strategy 或 notification；
- 真实数据写入；
- Runtime 切换；
- 新增 S7/Stage 编号命令；
- 删除旧入口。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-01 inventory、GY-CORE-02 Facade 及本顺序执行手册。

本任务为 GY-CORE-03，Lane 2，Terra 中推理，Plan-then-execute。

目标：
建立统一 guiyi CLI 骨架，并选择 1～2 个只读/dry-run 能力作为样板。
旧脚本只转调同一 service，不删除。

首轮实现：
- guiyi data verify
- guiyi runtime status
- 一个 dry-run 样板
- 旧入口兼容 Shim
- 参数、退出码、JSON 输出测试

禁止在 CLI 中实现领域算法，禁止真实数据/Runtime/通知写入，
禁止一次迁移所有 scripts。

完成后输出新旧入口等价证据、测试和后续 MERGE 清单。
```

### 用户通过结论

```text
允许集成 develop
```

---

# 9. `GY-CORE-04`：ObservationPlanRegistry 与 StrategyAdapter

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：**Terra**
- 推理强度：**中**
- 会话：**新开会话；完成后独立 HTDY Review**
- Plan：**Plan-then-execute**
- 工作区：**新 task worktree**
- 人工 Gate：**HTDY 边界 Review**

### 目标

把 JM、周期、策略、触发政策和通知开关从 scheduler、环境变量和 task-specific Gate 中抽离为版本化配置。

### 第一阶段配置

建议：

```text
config/observation_plans.yaml
```

active plan 只能是：

```text
product=jm
contract_selector=dominant_rank1
period=15m
strategy=htdy_original_realtime_first_seen/v1.0
trigger_policy=realtime_first_seen
purpose=observation_only
notification.enabled=false
```

苏冰可有 disabled 占位，但不得实现或运行。

### 新增边界

```text
ObservationPlan
ObservationPlanRegistry
StrategyAdapter
StrategyContext
SignalCandidate
HtDyStrategyAdapter
```

HTDY adapter 只能包装现有 evaluator/writer，严禁修改：

- original indicator；
- partial；
- repainting；
- first-seen；
- no-retraction；
- observation key；
- `signal_changed` 禁止；
- Stage 5 rejection。

### 禁止

- DB migration；
- Web 配置编辑；
- 写真实 SignalEvent；
- 发企微；
- 扩展非 JM/非 15m；
- 修改 HTDY 公式或 policy。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-01～03 已集成结果、HTDY canonical/Golden/strategy policy，
以及本顺序执行手册。

本任务为 GY-CORE-04，Lane 2，Terra 中推理，Plan-then-execute。

目标：
实现文件型 ObservationPlanRegistry 与通用 StrategyAdapter contract，
只包装现有 JM HTDY realtime first-seen 链路。

必须限制：
- product=jm
- dominant rank1 actual contract
- period=15m
- htdy_original_realtime_first_seen/v1.0
- realtime_first_seen
- observation_only
- notification.enabled=false

苏冰仅可 disabled 占位，不实现。

严禁修改 HTDY 公式、Golden、partial、repainting、first-seen、no-retraction、
observation key、Stage 5 rejection 或 signal_changed 禁止规则。

只运行测试/Shadow，不写正式表或企微。
完成后输出配置 hash、contract tests 和独立 HTDY Review 所需证据。
```

### 用户通过结论

```text
允许集成 develop
```

---

# 10. `GY-CORE-05`：JM 新 Runtime 只读 Shadow 实现

## Codex 调度建议

- 任务车道：Lane 3 设计；实现保持只读
- 执行入口：Codex App
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新 Plan 会话；批准后新实现会话；独立 Review 会话**
- Plan：**Plan-only → 用户批准后实现**
- 工作区：**新 task worktree**
- 人工 Gate：**Plan 批准 / 独立 Review**

### 目标

实现新的 JM Runtime Orchestrator，但 Shadow 阶段不拥有任何正式写权限。

### Shadow 数据流

```text
读取现有 historical/live 数据
→ ActiveDatasetResolver / MarketDataService
→ ObservationPlanRegistry
→ BarBoundaryTracker
→ HtDyStrategyAdapter
→ 生成 Shadow candidate
→ 写 JSONL/版本化报告
```

### 必须保证

```text
legacy Runtime = 唯一正式写入者
new Shadow Runtime = read-only
```

Shadow 禁止写：

- `live_minute_bars`；
- `live_aggregated_bars`；
- checkpoint；
- `strategy_signals`；
- `signal_events`；
- `signal_notifications`；
- canonical Parquet；
- 企微；
- Runtime 配置。

### 必须输出字段

```text
observed_at
trading_day
actual_contract
source_max_bar
source_revision_hash
bucket_start
bucket_end
bucket_status
snapshot_hash
legacy_candidate
shadow_candidate
legacy_observation_key
shadow_observation_key
blocked_reasons
match_status
```

### 禁止

- 第二个 RQData 写入进程；
- 双 Runtime 写入；
- 新 task-specific packet 链；
- 修改旧 S6-10；
- 自动部署。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-01～04 已集成结果、当前 Runtime/HTDY 实现、
旧 S6-10 暂停决策和本顺序执行手册。

本任务为 GY-CORE-05，Sol 高推理。
第一阶段只输出 Plan，用户批准后再在独立实现会话开发。

目标：
实现 JM 新 Runtime 的 read-only Shadow Orchestrator。

要求：
- legacy Runtime 仍是唯一正式写入者；
- Shadow 只读取现有 historical/live 数据；
- 使用 ActiveDatasetResolver、MarketDataService、ObservationPlanRegistry、StrategyAdapter；
- 生成逐轮 JSONL/版本化对照报告；
- 不构造第二个真实写入 ingest；
- 不写任何正式表、Parquet、checkpoint、企微或 Runtime 配置；
- 不引入新的 task-specific approval packet 链；
- 支持重启后继续只读对照。

Plan 必须包含进程边界、资源冲突防护、输出 schema、测试矩阵、
启动/停止方式、一个完整 DCE 交易日执行方案和回滚方式。
```

### 用户通过结论

Plan 后：

```text
允许继续实现
```

代码 Review 后：

```text
允许集成 develop
```

---

# 11. `GY-CORE-06`：单交易日 Shadow 执行与独立 Review

## Codex 调度建议

- 任务车道：受控只读运行
- 执行入口：Codex App + CLI automation
- 日常执行模型：**Terra**
- 日常推理强度：**中**
- 最终 Review 模型：**Sol**
- 最终推理强度：**高**
- 会话：**日常执行会话 + 新开独立 Review 会话**
- Plan：**Plan-then-execute**
- 人工 Gate：**真实 Shadow 运行批准**

### 目标

在不写正式数据的前提下，对比 legacy 和新 Runtime 一个完整 DCE 交易日，覆盖夜盘、
三段日盘、23 个 confirmed 15m 收线桶与 EOD。

### 单日执行

单日执行只做：

- 启动/确认 Shadow read-only；
- 采集 JSONL；
- 运行零写入 verifier；
- 生成单日 summary；
- 记录 Runtime restart、数据缺失或差异；
- 不自动修代码。

单日执行可使用 Terra 中推理，因为命令和核对规则已经冻结。

### 最终 Review

单日结束后，新开 Sol 高推理独立 Review，会审：

- trading day；
- actual contract；
- source 1m identity/revision；
- 夜盘、三段日盘与全部 23 个 confirmed 15m bucket；
- EOD；
- snapshot hash；
- candidate direction；
- observation key；
- blocked reason；
- 零写入；
- 幂等复跑；
- 所有差异的根因。

Runtime、RQData/网络与 Mac 恢复由同一 exact release 的独立恢复 evidence 会审，不要求在
Shadow 单日内全部注入。

### 通过标准

- 一个完整 DCE 交易日；
- 夜盘、三段日盘、23 个 confirmed 15m 桶和 EOD 全部覆盖；
- Shadow 零正式写入；
- legacy/shadow 关键 identity 一致；
- 不存在无法解释的差异；
- 同桶复跑幂等；
- 同一 exact release 的独立恢复证据通过；
- 没有重复信号和通知风险；
- 独立 Review 明确允许进入 release candidate 设计。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-05 Shadow contract、启动命令、verifier、当前 canonical 和本手册。

本任务为 GY-CORE-06，执行一个完整 DCE 交易日的 JM read-only Shadow。
单日执行使用 Terra 中推理；最终分析必须新开 Sol 高推理独立 Review 会话。

硬规则：
- legacy Runtime 是唯一正式写入者；
- Shadow 不写 live/SignalEvent/notification/checkpoint/Parquet/DB；
- 不发送企微；
- 单日只采集版本化 JSONL 和 summary；
- 必须覆盖夜盘、三段日盘、23 个 confirmed 15m 桶和 EOD；
- 同桶复跑必须幂等，正式写入 allowlist 外必须零写入；
- 发现差异先记录，不在运行现场随手修代码；
- 任一失败整日作废，保留 append-only Ledger，不允许热修后继续累计；
- 任何真实写入立即阻塞。

最终输出：
单日矩阵、零写入证明、所有差异、同一 exact release 的独立恢复结果、风险和是否允许进入
GY-CORE-07。
```

### 用户通过结论

```text
允许进入 release candidate
```

存在无法解释差异：

```text
阻塞
```

---

# 12. `GY-CORE-07`：ReleaseManifest、正式切换与 Runtime promotion

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App + CLI automation
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新 Plan 会话 + 新实现会话 + 新独立 Review 会话**
- Plan：**Plan-only**
- 工作区：**新 task worktree；后续 release worktree**
- 人工 Gate：**Plan 批准 / 独立 Review / release 批准 / Runtime promotion 批准 / 真实写入批准**

### 目标

将“每事件/每日审批”收口为“每正式 release 审批”，并把 JM 正式 Runtime 切换到新编排器。

### ReleaseManifest 最小冻结内容

```text
exact release tag
exact commit
database revision
observation config version/hash
allowed plan codes
allowed write targets
notification enable state
runtime root/bundle identity
rollback bundle identity
```

### 切换顺序

```text
代码集成 develop
→ release candidate
→ 独立 Review
→ 用户批准发布 main/tag
→ main + annotated tag
→ 用户单独批准 Runtime promotion
→ 停止 legacy writer
→ 冻结最终 checkpoint
→ runtime worktree detached at exact tag
→ 验证 ReleaseManifest
→ 启动新 Runtime
→ health/smoke
→ 首个真实事件
→ 幂等复跑
→ rollback drill
```

### 绝对禁止

- legacy/new Runtime 同时写；
- 自动 merge main；
- 自动 tag；
- release 批准自动继承 Runtime promotion；
- 修改 HTDY 公式；
- 为新 Runtime继续生成每日 child authorization；
- 未通过 Shadow 即切换；
- 真实企业微信 autosend 默认打开。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-06 最终 Shadow Review、当前 release/worktree canonical、
Runtime/deployment/backup/recovery 代码和本顺序执行手册。

本任务为 GY-CORE-07，Lane 3，Sol 高推理，Plan-only。

目标：
设计并在用户逐级批准后实现 ReleaseManifest 和 JM 新 Runtime 正式切换。

必须分离以下 Gate：
1. Plan 批准；
2. 实现集成 develop；
3. 独立 Review；
4. 允许发布 main/tag；
5. 允许 Runtime promotion；
6. 真实写入/切换批准。

切换必须先停止 legacy writer，再启动新 writer，禁止双写。
Runtime 必须 detached at exact approved tag。
必须保留 rollback bundle、checkpoint 交接、health/smoke、首个事件、幂等复跑和 rollback drill。

ReleaseManifest 只做 release-level 授权，禁止继续每日/每事件 parent-child packet。
企微 autosend 默认 false。

第一阶段只输出完整 Plan、文件范围、测试、命令、回滚和批准点，不执行真实切换。
```

### 用户批准结论顺序

```text
允许继续实现
允许集成 develop
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
```

不得跳级。

---

# 13. `GY-CORE-08`：旧入口归档与 canonical 收口

## Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 执行模型：**Terra**
- 执行推理强度：**中**
- 独立 Review 模型：**Sol**
- Review 推理强度：**高**
- 会话：**新执行会话 + 新独立 Review 会话**
- Plan：**Plan-then-execute**
- 工作区：**新 task worktree**
- 人工 Gate：**删除/归档范围 Review**

### 开始条件

- 新 Runtime 已正式切换；
- 至少完成一个受控稳定观察窗口；
- rollback bundle 可用；
- legacy 不再是正式 writer；
- GY-CORE-01 分类重新核对。

### 处理顺序

```text
DELETE_CANDIDATE
→ 全引用扫描
→ 删除或归档
→ MERGE 类入口改为 Shim
→ 保留一个兼容窗口
→ 再删除 Shim
```

### 必须保留

- 历史 report/receipt；
- 原失败 evidence；
- report 14/15；
- 数据资产和 checksum；
- Git 历史；
- legacy rollback bundle，至少保留到新版 S6-10 通过；
- HTDY 原语义和 Golden。

### 目标状态

- active scripts 不再新增 `S6-*`、`Stage*`、task ID 正式入口；
- 一个业务能力只有一个用户入口；
- 领域算法位于 services，不塞进 CLI；
- canonical 只描述当前业务架构；
- 历史阶段叙事进入 archive/Git/evidence；
- CI、launchd、Makefile、shell、Python import、文档无悬空引用。

### 可复制 Codex Prompt

```text
请阅读 GY-CORE-01 inventory、GY-CORE-07 切换/rollback evidence、
当前 canonical 和本顺序执行手册。

本任务为 GY-CORE-08，Lane 2。
实现使用 Terra 中推理；完成后必须新开 Sol 高推理独立 Review。

目标：
根据已验证 inventory 精确归档/删除旧入口，统一 canonical，
但保留所有历史 evidence、report 14/15、数据资产、Git 历史和 legacy rollback bundle。

必须逐项检查：
launchd、Makefile、CI、shell、Python import、tests、AGENTS.md、README.md、
TESTING.md、STATUS.md、DECISIONS.md 和业务 canonical。

禁止凭文件名猜测删除；UNKNOWN 一律保留。
禁止触及 Runtime、DB、Parquet、企微、main/tag。
禁止提前删除 rollback bundle；至少保留到新版 S6-10 通过。

完成后输出 KEEP/MERGE/MOVE/ARCHIVE/DELETE 最终矩阵、引用扫描、测试和风险。
```

### 用户通过结论

```text
允许集成 develop
```

---

# 14. `GY-S6-10-R2`：基于新架构重新设计 S6-10

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新 Plan 会话 + 新独立 Review 会话**
- Plan：**Plan-only → 用户批准后实现**
- 工作区：**新 task worktree**
- 人工 Gate：**Plan 批准 / 独立 Review**

### 目标

不继续旧 schema-v6/v7、C2、Approval D、daily child 控制链；基于新 ReleaseManifest、
ObservationPlan、统一 Runtime 和 checkpoint/dedupe 重新设计简化版单交易日 Runtime 验收。

### 新 S6-10 只验证

1. 一个完整 DCE 交易日，包含夜盘、三段日盘和 23 个 confirmed 15m 桶；
2. live 1m 持续更新；
3. 15m 边界和 HTDY first-seen 正确；
4. 同一 event 不重复；
5. notification identity 不重复；
6. EOD 自动追平；
7. 同一 exact release 的一次 Runtime 进程重启恢复证据；
8. 同一 exact release 的一次 RQData/网络短暂故障恢复证据；
9. 同一 exact release 的一次 Mac 重启恢复证据；
10. autosend=false 时绝不发送；
11. ReleaseManifest/config/DB revision 无漂移；
12. 单日生成 append-only 简洁 Ledger，任何失败整日重启且失败记录不改写。

第 7～9 项可在单日自然运行前后按获批矩阵独立执行，不要求全部塞入同一交易日；必须绑定
相同 exact release、ObservationPlan、ReleaseManifest 和 DB revision。

### 不再要求

- 每日 parent/child packet；
- 每日人工授权；
- 每个事件单独批准；
- 23 close allowlist 任务专用控制面；
- 绑定大量旧 S6 receipt 才能运行；
- API/Web/Redis/notification worker 全部放入一个不可拆分故障矩阵。

基础安全改由：

- exact release/tag；
- ReleaseManifest；
- DB unique constraints；
- checkpoint；
- advisory/Redis singleton（当前先保留既有实现）；
- table allowlist；
- idempotency；
- secret filtering；
- bounded retry；
-人工故障注入批准。

### 可复制 Codex Prompt

```text
请阅读新架构最终 canonical、GY-CORE-07/08 evidence、旧 S6-10 task/失败证据，
以及本顺序执行手册。

本任务为 GY-S6-10-R2，Lane 3，Sol 高推理，Plan-only。

目标：
基于新 ReleaseManifest、ObservationPlan、统一 JM Runtime、checkpoint 和幂等机制，
重新设计简化版单交易日 Runtime 验收。

禁止继续旧 C2、Approval D、daily child、每事件授权和 23-close task-specific 控制面。
旧 evidence 保留，不改写。

新版只验证：
- 一个完整 DCE 交易日，覆盖夜盘、三段日盘、23 个 confirmed 15m 桶和 EOD；
- live/EOD 连续性；
- 15m/HTDY first-seen；
- 信号与通知幂等；
- 同一 exact release 的 Runtime/RQData/Mac 独立恢复证据；
- autosend=false；
- release/config/DB 无漂移；
- 单日 append-only Ledger；
- 任一失败整日重启，不允许热修后继续累计。

第一阶段只输出设计、任务合同、测试、故障注入矩阵、运行命令、停止条件和回滚。
用户批准前不得实现或运行。
```

### 用户通过结论

```text
允许继续实现
```

代码和独立 Review 通过后：

```text
允许重启 S6-10
```

---

# 15. `GY-S6-10-R2-RUN`：新版单交易日真实验收

## Codex 调度建议

- 任务车道：Lane 3
- 执行入口：Codex App + CLI automation
- 推荐模型：**Sol**
- 推理强度：**高**
- 会话：**新执行会话 + 新独立 Review 会话**
- Plan：**Plan-then-execute**
- 工作区：**runtime exact tag + 独立 evidence 目录**
- 人工 Gate：**真实运行批准 / 故障注入批准 / 最终结论批准**

### 执行原则

- Runtime 必须是 exact approved tag；
- 不在运行窗口改代码、policy、schema 或配置；
- 必须修改时，停止窗口、保留失败 evidence、修复、重新 release/promotion，然后从下一个
  完整 DCE 交易日重新开始；禁止热修后继续累计；
- 单日 Ledger 只追加，不改写失败记录；
- 故障注入按批准矩阵执行；
- Runtime/RQData/网络/Mac 恢复可在单日自然运行前后独立执行，但必须绑定同一 exact release；
- 企微 autosend 是否启用按新版合同单独决定，默认 false；
- `LONG_RUNNING_READY=false` 作为 `deprecated / not_applicable` 兼容字段保留，单日 Gate
  永不将其设为 true；
- 不自动发布 `JM_RUNTIME_READY`。

### 最终 Review

独立 Sol 高推理会话必须核对：

- 单日夜盘、三段日盘、23 个 confirmed 15m 桶和 EOD 完整性；
- Runtime/tag/config/DB identity；
- live 和 EOD 连续性；
- 信号/通知幂等；
- 故障恢复；
- 禁止写入计数；
- 所有失败是否如实保留；
- 是否存在过度宣称。

### 可复制 Codex Prompt

```text
请读取 GY-S6-10-R2 已批准合同、exact release/tag、ReleaseManifest、
Runtime health、每日 Ledger、故障注入矩阵和本手册。

本任务为 GY-S6-10-R2-RUN，Lane 3，Sol 高推理。

执行一个完整 DCE 交易日 Runtime 验收。
运行窗口内禁止修改代码、policy、schema、ObservationPlan 或 ReleaseManifest。
发现必须修改的问题时立即停止并标记整日窗口失败，不允许现场热修后继续累计。

单日追加 Ledger，覆盖夜盘、三段日盘、23 个 confirmed 15m 桶、live、HTDY、SignalEvent、
notification identity、EOD、
Runtime/tag/config/DB identity、错误和恢复。
故障注入必须使用已批准矩阵。

完成后新开独立 Review，会审所有 evidence，并只提出是否允许发布
JM_RUNTIME_READY 的建议，不自动更新状态。`LONG_RUNNING_READY` 不适用于该 Gate。
```

### 最终用户结论

通过全部 Gate 后才可：

```text
允许发布 JM_RUNTIME_READY
```

否则：

```text
阻塞
```

---

# 16. 阶段性验收与停止条件

## 16.1 GY-CORE-00～04

必须满足：

- 不触及正式 Runtime；
- 不写 DB/Parquet；
- 不继续旧 S6-10；
- 数据选择和 HTDY 语义不变；
- 各任务已集成 develop 并清理 task worktree。

## 16.2 GY-CORE-05～06

必须满足：

- Shadow 完全只读；
- legacy 是唯一正式 writer；
- 单日关键 identity 一致；
- 所有差异可解释；
- 独立 Review 通过。

## 16.3 GY-CORE-07

必须满足：

- release 和 Runtime promotion 分别批准；
- legacy writer 先停止；
- 新 Runtime exact tag；
- rollback 可执行；
- 无双写；
- 首个事件幂等。

## 16.4 GY-CORE-08

必须满足：

- 无悬空引用；
- 历史 evidence 未删除；
- rollback bundle 仍保留；
- active 入口显著收口；
- canonical 与新架构一致。

## 16.5 GY-S6-10-R2

必须满足：

- 不再依赖旧 task-specific 控制面；
- 单日真实运行与同一 exact release 的独立恢复证据通过；
- 失败证据未改写；
- 用户最终批准 Ready 状态。

任一任务发现以下情况立即阻塞：

- current canonical 与本手册冲突且无法明确解析；
- develop/main/runtime 身份不清；
- 双 Runtime 写入风险；
- 旧 S6-10 授权仍 active；
- 数据选择结果漂移；
- HTDY first-seen 语义漂移；
- report 14/15 或历史 evidence 可能被修改；
- 需要 production migration 但无独立 Lane 3 Plan；
- 无法证明删除候选无引用。

---

# 17. 最终目标架构

```text
RQDataAdapter
    ├── HistoricalSyncService
    ├── EodSyncService
    ├── LivePollService
    └── MainContractResolver
               ↓
BarStore / LiveBarStore
               ↓
ActiveDatasetResolver
               ↓
MarketDataService
               ↓
ObservationPlanRegistry
               ↓
JM Runtime Orchestrator
               ↓
BarBoundaryTracker
               ↓
StrategyAdapter
               ↓
SignalEvent + Notification Outbox
               ↓
FastAPI / Vue Web / WeCom

ReleaseManifest
    → exact release
    → exact config
    → exact DB revision
    → allowed write targets
    → Runtime promotion
```

长期正式入口目标：

```text
PostgreSQL
FastAPI
JM Runtime Scheduler
JM EOD Scheduler
Vue Web
少量 guiyi CLI
```

本轮完成后才进入后续业务主线：

```text
JM 新版 S6-10
→ V1 最终封板
→ Web 真实自测修复
→ 品种池和多品种
→ 苏冰策略冻结
→ Research Memory
→ AI 辅助判断 Shadow
```

---

# 18. 当前执行入口

下一任务只允许执行：

```text
GY-CORE-05：JM 新 Runtime 只读 Shadow 的设计 Plan
```

配置：

```text
Codex App
Sol
高推理
新 Plan 会话
Plan-only
先复核 GY-CORE-01～04 已集成结果和当前 Runtime 身份
不修改代码、Runtime、DB、Parquet、mapping、SignalEvent 或企微
```

`GY-CORE-05` 的 Shadow 实现仍须独立 Plan 批准，并显式处理 `STATUS.md` 中未关闭的
live source-mode schema/upsert/aggregation P0；Plan 批准前不得进入实现或真实运行。
