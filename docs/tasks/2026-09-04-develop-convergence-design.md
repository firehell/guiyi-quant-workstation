# 全分支合并后 `develop` 收敛 Design Spec

日期：2026-09-04
状态：`DESIGN_APPROVED / READY_FOR_IMPLEMENTATION_PLAN`
文档类型：仓库集成基线收敛设计权威
规划基线：`develop@f476835b332b428d645edd09e7531cafa57ebb35`
设计分支：`docs/develop-convergence-design`
目标集成分支：`develop`
任务车道：Lane 2（仓库治理、文档与普通工程修复；不触及生产写入、发布或 Runtime）

> 本文只定义“全分支内容已经进入 `develop` 之后，如何形成唯一、可验证、可继续开发的集成基线”。
> 它不授权立即执行清理、关闭 Issue、删除远端 branch、修改 Release PR、合入 `main`、创建 tag、发布 Release、写生产数据、切换 Runtime 或发送通知。实施须按配套 Implementation Plan 分阶段执行并保留 fail-closed Gate。

## 0. Owner 决策

2026-09-04，Owner 已批准本文设计，并选择截图方案 A：

```text
NEWOW_SCREENSHOT_POLICY = RETAIN
DISTRIBUTION_STATUS = DISTRIBUTION_APPROVED_BY_OWNER
```

具体含义：

- 保留 `docs/research/newow-v3.2.82/screenshots/**` 中现有 27 张标的/周期截图与 2 张上下文截图；
- 在 Newow dossier 中记录 Owner 已明确批准这些截图继续存在于当前公开 GitHub 仓库；
- 该决定只代表仓库所有者的分发选择，不构成法律意见，也不扩大对第三方内容的权利声明；
- `.playwright-cli/**` 中的完整页面响应、逐 Bar 原始输入和本地浏览器采集产物仍按 fail-closed 路径删除并加入 `.gitignore`；
- 截图保留不意味着原始 HTML、JavaScript、接口响应、股票逐 Bar 数据或 RQData/Canonical 原始事实可以进入仓库。

---

## 1. 规范性边界

### 1.1 事实源优先级

发生冲突时依次服从：

1. `STATUS.md`：当前 release、production Runtime、Scope、自然 evidence 与 pending Gate；
2. `AGENTS.md`：执行授权、安全边界与不可破坏规则；
3. `docs/DEVELOPMENT.md`：日常开发和验证流程；
4. `PROJECT_SOURCE.md`：稳定产品面和明确退役面；
5. `DECISIONS.md`、`docs/ARCHITECTURE.md` 与 accepted OpenSpec：长期决策、active 依赖和正式合同；
6. 本文：本次 `develop` 收敛任务的设计边界；
7. 当前 Issue、PR、源码、测试与 exact-head 验证：实际实现事实。

对话、旧 Issue、旧 task doc、旧分支名称或历史完成声明不得覆盖 active canonical。冲突无法唯一解释时必须保留事实并 fail-closed，不得猜测、静默修正或用最新修改时间冒充权威。

### 1.2 “已合并”与“已收敛”

本任务中的“已合并”只表示：

```text
某 branch tip 对最终 develop 的 ahead_by = 0
```

“已收敛”必须同时满足：

```text
分支内容无遗漏
+ active canonical 唯一
+ 退役面未复活
+ 原始/临时证据已分类
+ Issue / PR 元数据不再陈旧或矛盾
+ 全量适用验证通过
+ exact-head 双轴 Review 通过
+ 残留 branch 安全清理完成或有明确保留理由
```

branch 全部成为 `develop` 祖先，不自动构成 `DEVELOP_CONVERGED`。

### 1.3 明确禁止范围

本任务不得：

- 改写 Git 历史、rebase 已共享历史、force push 或 force-delete 未证明安全的 branch；
- 修改 `main`、合入 Release PR、创建 tag 或发布 GitHub Release；
- 修改 GitHub branch protection、ruleset 或 required checks；
- 执行 RQData、Canonical、production PostgreSQL、Redis、Scope 或仓库外数据写入；
- 启用、切换或 promotion Runtime；
- 发送 PushPlus 或其他真实通知；
- 修改 Newow、HTDY、SuBing、Range Detector 等策略和指标公式；
- 扩展产品功能、模拟账户、订单、仓位或自动交易；
- 以“清理”为名恢复 archive、backup、legacy-copy、rollback-copy、approval packet 或 receipt；
- 把当前 `develop` 直接视为 `v1.9.15` Release candidate；
- 因 Owner 批准保留截图而恢复 `.playwright-cli/**` 或其他原始采集数据。

### 1.4 允许范围

实施可在独立 task branch/worktree 内：

- 读取和比较 Git branch、merge-base、commit、tree、Issue、PR 与文档引用；
- 删除已证明无 active consumer 的仓库内临时文件、重复文档和退役引用；
- 更新 `.gitignore`、task docs、Issue/PR 元数据和只反映当前事实的 `STATUS.md`；
- 更新 Newow dossier 的截图分发状态说明；
- 修复由批量合并引入的普通代码、类型、构建或测试回归；
- 增加最小 repository-hygiene 回归检查，防止同类污染重新进入；
- 在必要检查和 exact-head Review 通过后集成 `develop`；
- 对已证明为 `develop` 祖先且未被 worktree/PR 使用的普通残留 branch 做安全清理。

涉及策略公式、成交时序、数据合同、生产 migration、Runtime 或真实通知的任何问题，必须从本任务拆出并按 Lane 3 处理。

---

## 2. 初始只读基线

本节记录 2026-09-04 的初始快照。实施开始、提交 Review 和集成 `develop` 前均须重新读取，不能把本节当作未来不变事实。

### 2.1 `develop` 身份

```text
develop@f476835b332b428d645edd09e7531cafa57ebb35
latest merge:
Merge branch docs/newow-v3-2-82-github-dossier into develop
```

该 merge 在此前 `develop@8ecfec79bbe28056d6fb4e99d35ed34097cfd5d2` 上新增 GitHub-safe Newow dossier，并删除一批已失效的 `docs/superpowers/*`、旧 Market Home 文档、旧 SuBing 文档和 demo task 文件。实施不得重复恢复这些已删除文档。

### 2.2 远端 branch 拓扑

初始远端共有 18 个 branch：

```text
main
develop
codex/release-v1.9.15
以及 15 个普通残留 branch
```

除 `main`、`develop` 外的 16 个 branch 对初始 `develop` 均为：

```text
ahead_by = 0
status = behind
```

即初始 readback 没有发现只存在于残留 branch 的独有 commit。

| Branch | 初始分类 | 初始 behind_by | 设计处理 |
|---|---|---:|---|
| `codex/release-v1.9.15` | Release 保留 | 124 | 保留，受 PR #333 管理 |
| `codex/full-history-residual-repair-004b-closure` | 普通清理候选 | 2703 | 重新核验后删除候选 |
| `codex/newow-page-v2-coverage-discovery` | 普通清理候选 | 135 | 重新核验后删除候选 |
| `docs/candidate-validation-v1-plan` | 普通清理候选 | 1436 | 重新核验后删除候选 |
| `docs/market-detail-v1-remaining-plan` | 普通清理候选 | 227 | 重新核验后删除候选 |
| `docs/market-home-niuwah-implementation-plan` | 普通清理候选 | 446 | 重新核验后删除候选 |
| `docs/n-structure-v1-plan` | 普通清理候选 | 1407 | 重新核验后删除候选 |
| `docs/newow-layered-strategy-reconstruction-spec` | 普通清理候选 | 619 | 重新核验后删除候选 |
| `docs/newow-slice-b-cup-engine-spec` | 普通清理候选 | 436 | 重新核验后删除候选 |
| `docs/newow-slice-b-plan-alignment` | 普通清理候选 | 427 | 重新核验后删除候选 |
| `docs/subing-ths-alert-15m-v1-implementation-plan` | 普通清理候选 | 400 | 重新核验后删除候选 |
| `docs/subing-ths-alert-15m-v1-plan` | 普通清理候选 | 403 | 重新核验后删除候选 |
| `feature/jm-historical-catchup-foundation-s6-02` | 普通清理候选 | 2620 | 重新核验后删除候选 |
| `feature/newow-trend-page-parity` | 普通清理候选 | 171 | 重新核验后删除候选 |
| `task/demo-20260715-003-github-native-v3-final-e2e` | 普通清理候选 | 2760 | 重新核验后删除候选 |
| `task/demo-wb-v3-001` | 普通清理候选 | 2717 | 重新核验后删除候选 |

最终删除必须同时满足：

```text
ahead_by = 0
+ 非 diverged
+ 无 open PR 以该 branch 为 head
+ 未被任何本地 worktree checkout
+ 远端 tip 在审计后未前移
+ branch 不属于 main / develop / active release / 当前任务
```

`behind_by` 只描述距离，不是质量或删除依据。

### 2.3 Release 线隔离

初始 open Release PR 为 PR #333：

```text
head branch = codex/release-v1.9.15
current head = 2eb33e6d9f8195847b908e399539c5e12f5ff7b6
base = main
```

PR body 仍把旧 SHA 写为 Exact RC：

```text
Exact RC = a9a9ed02c2b172af36795722326dde001e95b7ab
```

因此初始状态为：

```text
RELEASE_METADATA_STALE
RELEASE_REVIEW_STALE
```

收敛任务只允许纠正元数据，使 PR 明确区分当前 head、旧证据适用的旧 SHA 和重新 Review 的必要性。不得把最新全量 `develop` 塞入该 RC，也不得授权 release、main merge、tag、Runtime promotion 或生产数据 apply。`codex/release-v1.9.15` 在 PR #333 最终处理前不得删除。

### 2.4 GitHub 治理现状

初始 readback：

```text
develop protected = false
required status checks = none
```

本任务不修改 GitHub rules。实施通过流程约束降低风险：

- 从 exact `develop` SHA 创建独立 task branch/worktree；
- 不在 `develop` 上直接清理；
- 每个关键阶段重新检查 `develop` 是否前移；
- 前移时先同步并重建 inventory、差异和验证清单；
- 只在 exact-head Review 通过后集成。

### 2.5 `.playwright-cli/**` 分发冲突

当前 `.playwright-cli/**` 跟踪了第三方页面 URL、页面版本、股票/指数逐 Bar OHLCV、完整结构化响应和浏览器采集时间。Newow GitHub-safe dossier 同时明确“不分发原始响应和逐 Bar 输入”，两者冲突。

固定结论：

```text
.playwright-cli/** = DISTRIBUTION_UNSAFE_CANDIDATE
```

实施须先确认无 active consumer，再：

```text
删除全部 tracked .playwright-cli/**
+ .gitignore 加入 .playwright-cli/
+ 确认仓库中无同类替代副本
```

需要保留的结论只使用 `docs/research/newow-v3.2.82/` 的安全派生结果、来源登记、hash manifest 与 Owner 已批准保留的截图。

### 2.6 截图分发状态

Owner 已选择方案 A，状态固定为：

```text
DISTRIBUTION_APPROVED_BY_OWNER
```

实施须保留现有 Newow screenshot 路径，并在 dossier README 中将“待 Owner 确认”更新为“Owner 已于 2026-09-04 明确批准继续分发”。不得把这一状态解释成法律审查通过，也不得扩展到原始页面响应或行情原文。

### 2.7 非 canonical 文档残留

`docs/DEVELOPMENT.md` 已规定不把 `docs/superpowers/` 当当前设计源。初始仍保留：

```text
docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md
docs/superpowers/plans/2026-09-04-newow-futures-validation.md
docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md
```

初始分类：

```text
NON_CANONICAL_REVIEW_REQUIRED
```

若有效结论已被 `docs/tasks/*`、`docs/research/newow-v3.2.82/*`、代码或测试覆盖，则删除；若存在唯一且仍有效的合同内容，先迁移到正确 active canonical，再删除原文件。不得迁入 `legacy`、`archive` 或备份目录。

### 2.8 Issue 事实残留

初始需要收敛的 open Issue 至少包括：

- #286：旧 `subing_watch_15m_v1`、SMA21 与保留旧策略的设计，已与 active SuBing v3 和整体退役决策冲突；
- #307：仍写 `formula_version=subing_ths_15m_v2`，并引用当前已删除的旧 Spec/Plan 路径；
- #259：旧七层 Newow proprietary/clean-room 研究路线，与当前“公开可验证策略和指标为主、私有选股 `UNKNOWN / OUT_OF_SCOPE`”的新范围不一致。

设计处理：

```text
#286 -> superseded / not_planned
#259 -> superseded / not_planned
#307 -> 保持 open，更新为 v3、当前 canonical 和真实 pending Gate
```

关闭或改写时必须链接当前替代事实源，不能把未完成的自然 Gate写成完成。

---

## 3. 设计目标

最终形成可作为后续开发起点的 `develop`：

```text
单一 Git 历史
→ 单一 active canonical
→ 单一有效源码面
→ 可解释的研究证据面
→ 无本地采集污染
→ 无未声明的退役面复活
→ 全量测试与独立 Review
→ 安全清理普通残留 branch
```

后续开发者或 Codex 必须能够唯一回答：

1. 当前 release 和 Runtime 是什么；
2. 当前 `develop` 包含什么、尚未发布什么；
3. 哪些策略、指标、API、Web 和 Runtime 是 active；
4. 哪些文件是 canonical、task contract、research evidence 或 local artifact；
5. 哪些 Issue/PR 仍有效；
6. 哪些 branch 可安全删除；
7. 哪些验证真实运行过；
8. 哪些外部 Gate 尚未授权或完成。

---

## 4. 方案选择

### 4.1 不采用：直接在 `develop` 批量删除

审计和 mutation 混在一起，无法证明删除依据；当前 `develop` 没有 branch protection，也容易影响 Release 线和本地 worktree。

### 4.2 不采用：从 Release candidate 重新挑选提交

会重新制造 cherry-pick、遗漏与双重事实源，并混淆 `v1.9.15` 与后续 Newow 工作。

### 4.3 采用：当前 `develop` 上前向、证据驱动收敛

```text
冻结 exact baseline
→ 只读 inventory
→ P1 分发与临时产物清理
→ canonical / Issue / PR 收敛
→ 退役面和代码引用审计
→ 全量验证
→ branch 安全清理
→ exact-head 双轴 Review
→ 集成 develop
```

该方案保留完整 Git 历史，不重复合并、不重写历史；每一步都要求删除依据、回归证据和停止条件。

---

## 5. 收敛分类模型

每个对象必须唯一归入：

| 类别 | 含义 | 允许位置 | 处理原则 |
|---|---|---|---|
| `ACTIVE_AUTHORITY` | 当前产品、数据、架构或命令权威 | 根 canonical、`docs/ARCHITECTURE.md`、OpenSpec、`TESTING.md` | 必须唯一且与代码一致 |
| `ACTIVE_TASK_CONTRACT` | 尚在执行或仍约束实现的任务文档 | `docs/tasks/` | 明确状态、基线和替代关系 |
| `RESEARCH_EVIDENCE` | 可验证但不定义产品或 Runtime 的研究证据 | `docs/research/`、受控 fixture | 明确来源、hash、分发和结论边界 |
| `LOCAL_OR_OBSOLETE` | 本地采集、临时输出、重复文档、已退役引用 | 不允许长期跟踪 | 关闭 consumer 后删除并按需 ignore |

一个文件不能同时作为 active canonical 和 research evidence；一个 Issue 不能同时表达旧 v2 与当前 v3；一个 branch 不能同时是 cleanup candidate 和 active release branch。

### 5.1 文档职责

| 文档/目录 | 唯一职责 |
|---|---|
| `STATUS.md` | 当前 release、Runtime、Scope、自然 evidence、pending Gate |
| `PROJECT_SOURCE.md` | 稳定产品面、明确退役面 |
| `AGENTS.md` | 工程授权、安全规则、不可破坏边界 |
| `docs/DEVELOPMENT.md` | 日常开发流程 |
| `DECISIONS.md` | 长期决策和不变量 |
| `docs/ARCHITECTURE.md` | active 依赖图和 consumer 边界 |
| `TESTING.md` | 当前可执行验证命令 |
| `openspec/specs/` | accepted、可验证的正式业务合同 |
| `docs/tasks/` | 当前任务设计和实施合同 |
| `docs/research/` | 有边界的研究报告和 evidence |
| Git history | 已完成过程和被删除旧文档的恢复来源 |

`docs/superpowers/` 不再作为当前设计源；收敛后若目录为空，删除空目录，不新增旧文档索引。

### 5.2 代码审计边界

本任务不逐行重审全部历史 commit，也不重新评价策略收益。只审计批量合并易引入的四类风险：

1. **退役面复活**：旧 Strategy、API、CLI、Web、Runtime、Scope、Event、cache 或兼容 reader 再次 active；
2. **双重 authority**：同一指标、主力解析、市场读取、公式、路由或配置出现两套 active 实现；
3. **合并回归**：测试、类型、构建、路由、依赖或版本身份不一致；
4. **证据越权**：page-parity、retrospective、repainting、fixture 或研究收益接入正式 Alert/Runtime/交易语义。

兼容或遗留命名不能单凭名字删除。尚由已批准延期承担的 seam，例如 Market Detail Slice E 完成前的受控 fallback，应分类为 `DEFERRED_ACTIVE_SEAM`。

---

## 6. 分阶段实施设计

### Slice 0：冻结与完整 inventory

输入：实施开始时最新 clean `develop`。
输出：exact-head inventory，至少包含：

```text
baseline SHA
branch / merge-base / ahead_by / behind_by
open Issue / PR / head SHA / base SHA
tracked large files
tracked hidden/tool output directories
active docs and inbound references
retired-surface symbol/path references
version identities
OpenSpec list
测试入口清单
本地 worktree 清单
```

规则：

- 只读，不删除、不关闭、不改业务文档；
- 使用最终实施的 exact baseline 重新生成；
- 任一普通 branch `ahead_by > 0` 或 diverged 时停止 branch 清理并单独审查；
- 本地必须读取 `git worktree list --porcelain`，远端 GitHub 比较不能替代本地检查。

### Slice 1：P1 分发安全与临时产物收敛

固定顺序：

```text
consumer/reference scan
→ secret/distribution scan
→ 与 docs/research safe dossier 对照
→ 删除 tracked .playwright-cli/**
→ .gitignore 加入 .playwright-cli/
→ 保留已批准截图
→ 更新 dossier owner distribution 状态
→ 运行受影响测试
→ 确认 Git tree 无同类替代副本
```

删除只影响当前 Git tree，不重写历史。若发现真实凭据，停止普通收敛并报告安全事件；不得自行 history rewrite。

### Slice 2：canonical、task docs、Issue 与 PR 收敛

#### Canonical

- `STATUS.md` 只更新可读回的当前 Release/Runtime、PR #333 current head 与 stale Review 状态；
- `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md` 默认不改；只有代码事实证明稳定产品面或 active 依赖已经改变时才提出独立变更；
- `TESTING.md` 只增加实际新增、可执行的 repository-hygiene 验证命令；
- OpenSpec 只修明确冲突，不新增产品语义。

#### Task docs

对 `docs/tasks/*` 分类：

```text
ACTIVE
IMPLEMENTED / EVIDENCE_PENDING
SUPERSEDED
HISTORICAL_REFERENCE_ONLY
```

一个当前任务只能有一份设计权威和一份实施计划。被替代文档删除；完成过程从 Git history 追溯，不建立 archive。

#### `docs/superpowers/*`

按第 2.7 节迁移或删除，目标状态为无 active reference 和无 tracked 文件。

#### Issue

- #286：确认无独立 Gate 后关闭为 `not_planned`/superseded；
- #259：以当前 Newow scope 与 dossier 为替代依据关闭为 `not_planned`/superseded，不声称旧七层计划全部完成；
- #307：更新为 `subing_ths_15m_v3`、当前 canonical 和真实 pending Gate，保持 open；
- 其他 Issue 按同一事实规则处理，不以更新时间判断有效性。

#### PR #333

- 保留 branch 与 open PR；
- PR body 区分旧 reviewed SHA 与 current head；
- 清除 current exact head 已经 Review 通过的失实表述；
- 不重跑 release、不改 base、不吸收当前全量 `develop`。

### Slice 3：退役面、双重 authority 与合并回归

静态和测试审计至少覆盖：

```text
旧 subing_strategy_v1 / Daily Watch / retired factor surface
旧 Backtest / Execution Review active API、CLI、Web、Runtime 或表消费者
Attention / Trend Focus / Main Force Mirror / N Structure 等退役 active surface
Historical consumer 绕过 MarketDataService
actual_dominant 自判主力或跨频 fallback
Web 复制 Newow / HTDY / SuBing 正式公式
repainting primitive 进入 formal signal / backtest / Alert / Runtime
page-parity 收益被当成 causal 或账户收益
重复 route、重复 identity authority、重复 version source
```

只修有直接证据的普通合并回归；不实施新功能、不调策略参数。涉及公式、成交时序或可信口径时停止并升级独立 Lane 3 任务。

### Slice 4：全量适用验证

以执行时 `TESTING.md` 为准，至少运行：

```text
Backend pytest（排除 isolated_postgresql / manual_acceptance）
Ruff
Mypy
Web unit
Web build
Playwright E2E
Alert rule ownership check
engineering canonical consistency
repository hygiene
OpenSpec strict validation
secret scan
git diff --check
```

另验证：

- `.playwright-cli/` 不被跟踪；
- 禁止的 raw capture 不再进入；
- `docs/superpowers/` 无 tracked active 文件；
- 删除文档无 inbound reference；
- 当前 task/canonical 链接有效；
- API、Web、lockfile和测试的版本身份一致；
- 当前任务 diff 只包含允许范围。

不预写通过数量；仅真实输出支持完成声明。

### Slice 5：普通残留 branch 安全清理

只在 Slice 0–4 通过后执行。

保留：

```text
main
develop
codex/release-v1.9.15
当前未合并 task/review branch
```

每个删除候选都须重新证明：

```text
git merge-base --is-ancestor <branch> <final-develop>
git log <final-develop>..<branch> --oneline  # 必须为空
git worktree list --porcelain                # 不得被 checkout
GitHub open PR head scan                      # 不得被使用
远端 tip 再读回                               # 不得前移
```

任一条件不满足即跳过并记录；禁止 force。Release branch 只由 release 流程清理。

### Slice 6：exact-head 双轴 Review 与集成

对同一 exact 40 字符 task head 分别执行：

1. **Standards Review**：工程边界、安全、删除依据、测试、Git 流转、无外部操作；
2. **Spec Review**：本文范围、分类、验收、canonical/Issue/PR 一致性、无范围漂移。

出现 P1/P2 后必须修复、重跑受影响验证，并在新 exact head 重做两轴 Review。

只在以下条件全部满足后允许集成 `develop`：

```text
P1 = 0
P2 = 0
必要测试全部通过
DISTRIBUTION_STATUS = DISTRIBUTION_APPROVED_BY_OWNER
PR #333 未被误改为已授权 release
普通残留 branch 已清理或逐项记录保留理由
```

集成 `develop` 不触发 main、tag、Release、Runtime、数据写入或通知。

---

## 7. 数据流与产物

本任务无业务数据流。仓库治理流为：

```text
Git / GitHub readback
→ immutable inventory facts
→ classification
→ scoped forward-only cleanup commits
→ validation results
→ exact-head Review
→ develop integration
```

设计产物：

```text
docs/tasks/2026-09-04-develop-convergence-design.md
```

配套计划：

```text
docs/tasks/2026-09-04-develop-convergence-implementation-plan.md
```

实施事实主要保留在 Git diff、commit、PR、Review 与测试输出中。允许一份简短结果文档记录 exact baseline、最终 head、分支清理、Issue/PR 变更和验证结果；不得复制完整日志、原始网页响应或 branch backup。

---

## 8. Fail-closed 规则

| 情况 | 固定处理 |
|---|---|
| `develop` 实施期间前移 | 同步最新 `develop`，重建 inventory 和受影响验证 |
| branch `ahead_by > 0` 或 diverged | 禁止删除，单独审查未合并 commit |
| branch 被 worktree 或 PR 使用 | 禁止删除 |
| raw capture 有 active consumer | 先迁移 consumer 到安全 fixture/派生 evidence，再删除 |
| 发现凭据 | 停止普通收敛，报告安全事件；不自行 history rewrite |
| screenshot 路径超出已批准范围 | 不保留，重新提交 Owner 决策 |
| canonical 与代码冲突 | 按事实源优先级定位；涉及策略/数据/Runtime 时拆为独立高风险任务 |
| 必要测试失败 | 只报告失败，不进入 branch cleanup 或完成声明 |
| PR #333 head 再次变化 | 旧 Review 再次失效，更新 current head 并重新走 release Review |
| 删除后出现断链 | 恢复当前任务 commit 或补正引用；不创建 archive 副本 |

---

## 9. 验收标准

### 9.1 Git 与 branch

- [ ] 最终 baseline 与 task head 均记录 40 字符 SHA；
- [ ] 所有普通残留 branch 删除前再次证明 `ahead_by=0`；
- [ ] 无 branch 因 worktree、open PR 或新增 commit 被误删；
- [ ] `main`、`develop`、active release branch 未被改写；
- [ ] 无 force push、history rewrite 或 GitHub rules 变更。

### 9.2 内容与分发

- [ ] `.playwright-cli/` 不再被跟踪并加入 `.gitignore`；
- [ ] 仓库无 safe dossier 明确排除的第三方完整响应或逐 Bar 原始输入副本；
- [ ] Newow screenshot 原路径保留；
- [ ] dossier 明确记录 `DISTRIBUTION_APPROVED_BY_OWNER`；
- [ ] secret scan 为 0 findings，或存在阻塞性安全事件并停止完成声明；
- [ ] 删除文件无 active consumer 或 inbound reference。

### 9.3 Canonical 与文档

- [ ] `STATUS.md`、PR #333 current head 和 Review 状态一致；
- [ ] `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md` 未被无关清理改写；
- [ ] `docs/tasks/` 无两份同时声称当前权威的 Spec/Plan；
- [ ] `docs/superpowers/` 无 tracked active source；
- [ ] 所有链接和引用指向存在且职责正确的文件。

### 9.4 Issue 与 PR

- [ ] #286 不再以旧 SMA21/watch 身份充当当前任务；
- [ ] #259 不再要求已退出范围的旧完整复原路线；
- [ ] #307 与 `subing_ths_15m_v3` 和真实 pending Gate 一致；
- [ ] PR #333 不再把旧 SHA Review 冒充 current-head Review；
- [ ] 未关闭任何仍承担独立外部 Gate 的 Issue。

### 9.5 代码与测试

- [ ] 未恢复退役 active surface；
- [ ] 未新增第二套 MarketDataService、主力解析、公式或路由 authority；
- [ ] page-parity、repainting、causal-research、Alert 和账户语义严格隔离；
- [ ] `TESTING.md` 的全部适用检查真实通过；
- [ ] Standards Review 与 Spec Review 在同一 exact head 上均为 P1=0、P2=0。

### 9.6 完成状态

仅上述标准全部满足时允许写：

```text
DEVELOP_CONVERGED
```

该状态不表示：

```text
RELEASED
RUNTIME_READY
NEWOW_PRODUCT_COMPLETE
NEWOW_CAUSAL_RESEARCH_COMPLETE
PAPER_ACCOUNT_READY
```

---

## 10. 推荐任务拆分

配套 Implementation Plan 严格按以下顺序：

```text
Task A：exact baseline inventory 与 blocker 分类
Task B：.playwright-cli / raw capture / distribution P1 收敛
Task C：canonical、task docs、Issue 与 PR 元数据收敛
Task D：退役面、双重 authority、构建与测试回归审计
Task E：全量验证和 repository-hygiene guard
Task F：普通残留 branch/worktree 安全清理
Task G：exact-head 双轴 Review 与 develop 集成
```

A 完成前不得执行 B–F；F 只处理证明安全的普通 branch；G 不触发 release、main、tag 或 Runtime。

---

## 11. Owner 审查结论

Owner 已于 2026-09-04 确认：

1. `.playwright-cli/**` 按公开仓库不应保留的原始采集产物处理；
2. Newow screenshot 选择方案 A，保留并记录 `DISTRIBUTION_APPROVED_BY_OWNER`；
3. #286、#259 可按 superseded/not-planned 路径处理；
4. #307 保持 open，只修正为当前 v3 与真实 Gate；
5. PR #333 只修 stale metadata，不吸收当前全量 `develop`；
6. 已证明为 `develop` 祖先且无 worktree/PR/新 commit 的普通残留 branch 可清理；
7. 最终结论仅为 `DEVELOP_CONVERGED`，不携带发布、Runtime、数据写入或通知授权。
