# 全分支合并后 `develop` 收敛 Design Spec

日期：2026-09-04  
状态：`DRAFT / AWAITING_OWNER_REVIEW`  
文档类型：仓库集成基线收敛设计权威  
规划基线：`develop@f476835b332b428d645edd09e7531cafa57ebb35`  
设计分支：`docs/develop-convergence-design`  
目标集成分支：`develop`  
任务车道：Lane 2（仓库治理、文档与普通工程修复；不触及生产写入、发布或 Runtime）

> 本文只设计“全分支内容已经进入 `develop` 之后，如何形成唯一、可验证、可继续开发的集成基线”。  
> 它不授权执行清理、关闭 Issue、删除远端 branch、修改 Release PR、合入 `main`、创建 tag、发布 Release、写生产数据、切换 Runtime 或发送通知。实施必须在本文经用户批准后另行形成 Implementation Plan。

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

### 1.2 本任务定义

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

因此，branch 全部成为 `develop` 祖先并不自动构成 `DEVELOP_CONVERGED`。

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
- 把当前 `develop` 直接视为 `v1.9.15` Release candidate。

### 1.4 允许范围

经设计批准后，实施可以在独立 task branch/worktree 内：

- 读取和比较 Git branch、merge-base、commit、tree、Issue、PR 与文档引用；
- 删除已证明无 active consumer 的仓库内临时文件、重复文档和退役引用；
- 更新 `.gitignore`、task docs、Issue/PR 元数据和仅反映当前事实的 `STATUS.md`；
- 修复由批量合并引入的普通代码、类型、构建或测试回归；
- 增加最小的 repository-hygiene 回归检查，防止同类污染重新进入；
- 在所有必要检查通过后合入 `develop`；
- 对已证明为 `develop` 祖先且未被 worktree/PR 使用的普通残留 branch 做安全清理。

---

## 2. 当前只读基线

本节是 2026-09-04 对 `develop@f476835b332b428d645edd09e7531cafa57ebb35` 的初始快照。实施开始、提交 Review 和合入 `develop` 前都必须重新生成，不能把本节当作未来不变事实。

### 2.1 `develop` 身份

```text
develop@f476835b332b428d645edd09e7531cafa57ebb35
latest merge:
Merge branch docs/newow-v3-2-82-github-dossier into develop
```

该 merge 在此前 `develop@8ecfec79bbe28056d6fb4e99d35ed34097cfd5d2` 上新增 GitHub-safe Newow dossier，并删除一批已失效的 `docs/superpowers/*`、旧 Market Home 文档、旧 SuBing 文档和 demo task 文件。该工作属于已经进入基线的事实，本任务不得重复恢复被删除文档。

### 2.2 远端 branch 拓扑

初始远端共有 18 个 branch：

```text
main
develop
codex/release-v1.9.15
以及 15 个普通残留 branch
```

对除 `main`、`develop` 外的 16 个 branch 逐一执行 `develop...branch` 比较，初始结果全部为：

```text
ahead_by = 0
status = behind
```

即所有 branch tip 当前都是 `develop` 的祖先，没有发现仅存在于残留 branch 的未合并 commit。

| Branch | 初始分类 | 初始 behind_by | 收敛处理 |
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

`behind_by` 只说明 branch 与当前 `develop` 的距离，不是质量或删除依据。最终删除还必须通过：

```text
ahead_by = 0
+ 非 diverged
+ 无 open PR 以该 branch 为 head
+ 未被任何本地 worktree checkout
+ 无后续新增 commit
+ branch 不属于 main / develop / active release
```

### 2.3 Release 线隔离

当前唯一 open PR 为 PR #333：

```text
head branch = codex/release-v1.9.15
current head = 2eb33e6d9f8195847b908e399539c5e12f5ff7b6
base = main
```

PR body 仍写：

```text
Exact RC = a9a9ed02c2b172af36795722326dde001e95b7ab
```

而当前 PR head 已是 `2eb33e6d...`。因此旧的 exact-head Review 和测试声明不能自动覆盖当前 head。该差异必须标记为：

```text
RELEASE_METADATA_STALE
RELEASE_REVIEW_STALE
```

本收敛任务只允许纠正元数据，使 PR 明确写出当前 head、旧证据适用的旧 SHA 和重新 Review 的必要性；不得借此授权 release、main merge、tag、Runtime promotion 或生产数据 apply。`codex/release-v1.9.15` 在 PR #333 最终处理前不得删除。

### 2.4 GitHub 治理现状

初始只读结果：

```text
develop protected = false
required status checks = none
```

本任务不得修改 GitHub rules。由于缺少技术性 branch protection，实施必须通过流程性约束降低风险：

- 从 exact `develop` SHA 创建独立 task branch/worktree；
- 实施期间不在 `develop` 直接清理；
- 每次关键阶段重新检查 `develop` 是否前移；
- 若前移，先同步并重新生成差异、branch 和验证清单；
- 只在 exact-head Review 通过后集成。

### 2.5 已识别的 P1 内容冲突

仓库根目录仍跟踪 `.playwright-cli/`。其中 `browser-page-000001-SH.json` 等文件包含：

- 第三方页面 URL 与服务地址；
- 页面标题和版本；
- 股票/指数逐 Bar OHLCV 输入；
- 浏览器采集时间和完整结构化响应。

与此同时，`docs/research/newow-v3.2.82/README.md` 明确声明 GitHub-safe dossier **不分发**：

```text
牛哇完整 HTML / JavaScript / 原始接口响应
股票 / 指数逐 Bar 原始输入
RQData / Canonical 原始行情与成本事实
```

因此当前仓库内容与 dossier 的分发边界互相矛盾。该问题必须优先处理，不能等同于普通无用文件清理。

初始设计结论：

```text
.playwright-cli/** = DISTRIBUTION_UNSAFE_CANDIDATE
```

实施时必须先确认无测试、脚本或文档 consumer，再删除全部 tracked capture，并在 `.gitignore` 中加入 `.playwright-cli/`。不得把这些原始响应平移到另一个仓库目录继续分发。需要保留的研究结论只能使用已进入 `docs/research/newow-v3.2.82/` 的安全派生结果、来源登记、hash manifest 和经 owner 确认可分发的截图。

### 2.6 截图分发 Gate

Newow dossier 当前包含 27 张标的/周期截图和 2 张上下文截图。其 README 已明确提示：公开仓库分发前需要 owner 确认第三方截图的公开分发权限。

本任务不作法律判断。实施必须输出一个明确状态：

```text
DISTRIBUTION_APPROVED_BY_OWNER
或
DISTRIBUTION_REVIEW_PENDING
```

在 owner 未确认前，不能声明整个仓库已经完成公开分发合规收敛。若 owner 选择 fail-closed 路径，则从 public repo 删除第三方截图，只保留文件清单、hash、派生结果和不含第三方页面表达的自有材料。

### 2.7 文档事实源残留

`docs/DEVELOPMENT.md` 已规定：

```text
不把 docs/superpowers/ 当当前设计源
```

当前仍保留：

```text
docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md
docs/superpowers/plans/2026-09-04-newow-futures-validation.md
docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md
```

这些文件初始分类为：

```text
NON_CANONICAL_REVIEW_REQUIRED
```

默认处理是：若其有效结论已经被 `docs/tasks/*`、`docs/research/newow-v3.2.82/*`、代码或测试覆盖，则删除；若存在唯一且仍有效的合同内容，先迁移到正确 active canonical，再删除原文件。不得通过加一个“legacy/archive”目录继续保存。

### 2.8 Issue 事实残留

当前 open Issue 至少包括：

- #286：旧 `subing_watch_15m_v1`、SMA21 与保留旧策略的设计，已与 active SuBing v3 和整体退役决策冲突；
- #307：仍写 `formula_version=subing_ths_15m_v2`，并引用当前已删除的旧 Spec/Plan 路径；
- #259：旧的七层 Newow proprietary/clean-room 研究路线，与当前“公开可验证策略和指标为主、私有选股 `UNKNOWN / OUT_OF_SCOPE`”的新范围不再一致。

初始处理原则：

```text
#286 -> superseded / not_planned 候选
#259 -> superseded / not_planned 候选
#307 -> 保持 open，但更新为 v3、当前 canonical、真实 pending Gate
```

任何关闭或改写都必须保留链接到当前替代事实源，不能把未完成的自然 Gate 写成完成。

---

## 3. 设计目标

本任务最终形成一个可作为后续开发起点的 `develop`：

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

目标不是让仓库看起来“整洁”，而是让后续任何人或 Codex 都能唯一回答：

1. 当前 release 和 Runtime 是什么；
2. 当前 `develop` 包含什么、尚未发布什么；
3. 哪些策略、指标、API、Web 和 Runtime 是 active；
4. 哪些文件是 canonical、task contract、research evidence 或 local artifact；
5. 哪些 Issue/PR 仍然有效；
6. 哪些 branch 可以安全删除；
7. 哪些验证真实运行过；
8. 哪些外部 Gate 仍未授权或未完成。

---

## 4. 方案比较

### 4.1 方案 A：直接在 `develop` 大批量删除和修复

优点：步骤少。  
缺点：当前 `develop` 无 branch protection，批量合并后尚未形成可靠基线；直接删除会把“审计”和“修改”混在一起，难以判断删除依据，也容易影响 PR #333 或其他本地 worktree。

结论：不采用。

### 4.2 方案 B：从 Release candidate 重新建干净分支，再挑选 `develop` 内容

优点：表面上历史较短。  
缺点：会重新制造选择性 cherry-pick、遗漏与双重事实源；无法证明全部已合并 branch 的内容被正确保留；还会混淆 `v1.9.15` 与后续 Newow 工作。

结论：不采用。

### 4.3 方案 C：在当前 `develop` 上做前向、证据驱动的分阶段收敛

流程：

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

优点：保留完整历史，不重复合并、不重写历史；每一步都有删除依据和回归证据；Release 线可独立保护。  
缺点：比一次性清理多一个 inventory 和 Review 周期。

结论：采用方案 C。

---

## 5. 收敛模型

### 5.1 四类仓库对象

每个被审计对象必须被唯一分类：

| 类别 | 含义 | 允许位置 | 处理原则 |
|---|---|---|---|
| `ACTIVE_AUTHORITY` | 当前产品、数据、架构或命令权威 | 根 canonical、`docs/ARCHITECTURE.md`、OpenSpec、`TESTING.md` | 必须唯一且与代码一致 |
| `ACTIVE_TASK_CONTRACT` | 尚在执行或仍约束实现的任务文档 | `docs/tasks/` | 明确状态、基线、替代关系 |
| `RESEARCH_EVIDENCE` | 可验证但不直接定义产品或 Runtime 的研究证据 | `docs/research/`、受控 fixture | 明确来源、hash、分发边界和结论边界 |
| `LOCAL_OR_OBSOLETE` | 本地采集、临时输出、重复文档、已退役引用 | 不允许长期跟踪 | 关闭 consumer 后删除并按需 ignore |

一个文件不能同时作为 active canonical 和 research evidence；一个 Issue 不能同时表达旧 v2 与当前 v3；一个 branch 不能同时是 cleanup candidate 和 active release branch。

### 5.2 文档职责映射

收敛后固定：

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
| `docs/research/` | 有边界的研究报告与 evidence |
| Git history | 已完成过程和被删除旧文档的恢复来源 |

`docs/superpowers/` 不再作为当前设计源；若收敛后目录为空，允许删除空目录，不新建 README 作为“旧文档索引”。

### 5.3 代码收敛边界

本任务不对所有历史 commit 做逐行重审，也不重新评价策略收益。代码审计只覆盖批量合并最容易引入的四类风险：

1. **退役面复活**：旧 Strategy、API、CLI、Web、Runtime、Scope、Event、cache 或兼容 reader 再次成为 active；
2. **双重 authority**：同一指标、主力解析、市场读取、公式、路由或配置出现两套 active 实现；
3. **合并回归**：测试、类型、构建、路由、依赖或版本身份不一致；
4. **证据越权**：page-parity、retrospective、repainting、fixture 或研究收益被接入正式 Alert/Runtime/交易语义。

以下兼容/遗留代码不能仅凭名字删除，必须先验证是否仍是已批准延期的一部分。例如 Market Detail Slice E 尚未完成时，`LegacyMarketChart.vue` 可能仍是受控 fallback；这类对象应标记为 `DEFERRED_ACTIVE_SEAM`，而不是误判为重复代码。

---

## 6. 分阶段实施设计

### Slice 0：冻结与完整 inventory

输入：实施开始时最新 clean `develop`。  
输出：一份 exact-head inventory，至少包含：

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
```

规则：

- 该 Slice 只读，不删除、不关闭、不改文档；
- inventory 必须使用最终要实施的 exact baseline 重新生成；
- 若发现任何普通 branch `ahead_by > 0` 或 `diverged`，立即停止 branch 清理并单独审查；
- 本地必须读取 `git worktree list --porcelain`，GitHub 远端比较不能替代 worktree 检查。

### Slice 1：P1 分发安全与临时产物收敛

优先处理：

```text
.playwright-cli/**
第三方原始页面/接口响应
逐 Bar 股票/指数原始输入
可能包含本地路径、内部地址、cookie、token 或 provider 原文的产物
```

固定顺序：

```text
consumer/reference scan
→ secret/distribution scan
→ 与 docs/research safe dossier 对照
→ 删除 tracked local/raw capture
→ 更新 .gitignore
→ 运行受影响测试
→ 确认 git tree 中无同类替代副本
```

删除只影响 Git 当前树，不重写历史。若历史中曾出现敏感凭据，需另开 Git 历史安全事件；本任务不得自行 history rewrite。

### Slice 2：canonical、task docs、Issue 与 PR 收敛

#### 2.1 Canonical

- `STATUS.md` 只更新可读回的当前 SHA、Release/Runtime 与 stale Review 状态；
- `PROJECT_SOURCE.md`、`DECISIONS.md` 和 `docs/ARCHITECTURE.md` 默认不改；只有确认当前代码已改变稳定产品面或 active 依赖时才提出独立变更；
- `TESTING.md` 只在实际命令已变化时更新；
- OpenSpec 只修复与代码现状的明确冲突，不趁机新增产品语义。

#### 2.2 Task docs

对 `docs/tasks/*` 逐个标记：

```text
ACTIVE
IMPLEMENTED / EVIDENCE_PENDING
SUPERSEDED
HISTORICAL_REFERENCE_ONLY
```

规则：

- 一个当前任务只有一份设计权威和一份实施计划；
- 被替代文档必须删除或在 active 文档中明确替代后删除；
- 不能保留两份都自称“当前权威”的 Spec；
- 完成过程从 Git history 追溯，不复制 archive。

#### 2.3 `docs/superpowers/*`

按第 2.7 节执行迁移或删除。目标状态：无 active reference 指向该目录。

#### 2.4 Issue

- #286：在确认无剩余独立 Gate 只属于该旧身份后，关闭为 `not_planned`/superseded；
- #259：以当前 Newow scope 和 `docs/research/newow-v3.2.82/` 为替代依据，关闭为 superseded，不声称原七层计划全部完成；
- #307：更新为 `subing_ths_15m_v3`、当前 canonical 和真实 pending Gate，保持 open 直到自然闭环满足；
- 其他 Issue 必须按同一规则处理，不以更新时间判断有效性。

#### 2.5 PR #333

- 保留 branch 与 open PR；
- PR body 必须区分旧 reviewed SHA 与 current head；
- 清除“当前 exact head 已通过 Review”之类不再成立的表述；
- 不重跑 release 或变更 base，除非另有 release 任务授权。

### Slice 3：退役面、双重 authority 与合并回归

至少执行以下静态和测试审计：

```text
旧 subing_strategy_v1 / Daily Watch / retired factor surface
旧 Backtest / Execution Review active API、CLI、Web、Runtime 或表消费者
Attention / Trend Focus / Main Force Mirror / N Structure 等已退役 active surface
Historical consumer 绕过 MarketDataService
actual_dominant 自判主力或跨频 fallback
Web 复制 Newow / HTDY / SuBing 正式公式
repainting primitive 进入 formal signal / backtest / Alert / Runtime
page-parity 收益被当成 causal 或账户收益
重复 route、重复 identity authority、重复 version source
```

处理原则：

- 只修复有直接证据的合并回归；
- 不实施新功能、不调策略参数、不扩大产品面；
- 删除源码前同步删除 active reference 和专用测试；
- 保留长期 causality、strict-before、prefix invariance、future-leak、golden parity、fail-closed 测试；
- 若发现需要改变策略公式、成交时序或可信口径，立即升级为独立 Lane 3 任务，本收敛任务停止处理该项。

### Slice 4：全量适用验证

验证以执行时 `TESTING.md` 为准，至少包括：

```text
Backend pytest（排除 isolated_postgresql / manual_acceptance）
Ruff
Mypy
Web unit
Web build
Playwright E2E
Alert rule ownership check
engineering canonical consistency
OpenSpec strict validation
secret scan
git diff --check
```

另加 repository-hygiene 验证：

- `.playwright-cli/` 不得被跟踪；
- 禁止的 raw capture 路径不得重新进入；
- 删除文档不存在 inbound reference；
- 当前 task/canonical 链接全部有效；
- 版本身份在 API、Web、lockfile/测试中一致；
- 当前 `develop` 相对任务 baseline 的变更只属于本任务允许范围。

不在文档中预设通过数量。只有真实命令输出才能写入最终验收记录。

### Slice 5：普通残留 branch 安全清理

仅在 Slice 0–4 通过后执行。

保留：

```text
main
develop
codex/release-v1.9.15
当前未合并 task/review branch
```

普通 branch 删除前逐个执行：

```text
git merge-base --is-ancestor <branch> <final-develop>
git log <final-develop>..<branch> --oneline  # 必须为空
git worktree list --porcelain                # 不得被 checkout
GitHub open PR head scan                      # 不得被使用
远端 tip 再读回                               # 不得在审计后前移
```

任何条件不满足时跳过该 branch，并在最终结果列出，不得 force。

远端删除完成后再次列出 branch；本地 branch/worktree 只在确认不再需要后清理。Release branch 的清理只由 release 流程决定。

### Slice 6：exact-head 双轴 Review 与集成

对最终 task head 分别进行：

1. **Standards Review**：工程边界、安全、删除依据、测试、Git 流转、无外部操作；
2. **Spec Review**：本文范围、分类、验收、canonical/Issue/PR 一致性、无范围漂移。

Review 必须引用同一个 exact 40 字符 SHA。若任一路出现 P1/P2，修复后重新运行受影响验证并在新 exact head 复核。

只有以下条件全部满足，才允许集成 `develop`：

```text
P1 = 0
P2 = 0
必要测试全部通过
分发风险有明确 owner 状态
PR #333 未被误改为已授权 release
普通残留 branch 已清理或逐项记录保留理由
```

---

## 7. 数据流与产物

本任务不创建业务数据流。仓库治理流为：

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

设计批准后才允许创建：

```text
docs/tasks/2026-09-04-develop-convergence-implementation-plan.md
```

实施完成后的结果应主要存在于 Git diff、commit、PR、Review 与真实测试输出中。若需要仓库内收敛总结，只允许一份简短 task result 文档，不复制完整日志、原始网页响应或 branch backup。

---

## 8. 错误处理与 fail-closed 规则

| 情况 | 固定处理 |
|---|---|
| `develop` 在实施期间前移 | 同步最新 `develop`，重建 inventory 和受影响验证 |
| branch `ahead_by > 0` 或 diverged | 禁止删除，单独审查未合并 commit |
| branch 被 worktree 或 PR 使用 | 禁止删除 |
| raw capture 有 active consumer | 先迁移 consumer 到安全 fixture/派生 evidence，再删除 |
| 发现凭据 | 停止普通收敛，报告安全事件；不自行 history rewrite |
| 截图分发权限未确认 | 标记 `DISTRIBUTION_REVIEW_PENDING`，不得宣称公开分发收敛完成 |
| canonical 与代码冲突 | 按事实源优先级定位；涉及策略/数据/Runtime 时停止并拆为独立高风险任务 |
| 必要测试失败 | 只报告失败，不进入 branch cleanup 或完成声明 |
| PR #333 head 再次变化 | 旧 Review 再次失效，更新 current head 并重新走 release Review |
| 删除后出现断链 | 恢复当前任务 commit 或补正引用；不创建 archive 副本 |

---

## 9. 验收标准

### 9.1 Git 与 branch

- [ ] 最终基线与 task exact head 均记录 40 字符 SHA；
- [ ] 所有普通残留 branch 在删除前再次证明 `ahead_by=0`；
- [ ] 无 branch 因本地 worktree、open PR 或新增 commit 被误删；
- [ ] `main`、`develop`、active release branch 未被改写；
- [ ] 无 force push、history rewrite 或 GitHub rules 变更。

### 9.2 内容与分发

- [ ] `.playwright-cli/` 不再被跟踪，并已加入 `.gitignore`；
- [ ] 仓库中不存在被 safe dossier 明确排除的第三方完整响应或逐 Bar 原始输入副本；
- [ ] Newow screenshot 分发具有 owner 明确状态；
- [ ] secret scan 为 0 findings，或存在阻塞性安全事件并停止完成声明；
- [ ] 删除文件无 active consumer 或 inbound reference。

### 9.3 Canonical 与文档

- [ ] `STATUS.md`、PR #333 current head 和 Review 状态一致；
- [ ] `PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md` 未被无关清理改写；
- [ ] `docs/tasks/` 中不存在两份同时声称当前权威的 Spec/Plan；
- [ ] `docs/superpowers/` 不再被作为 active source；
- [ ] 所有链接和引用指向存在且职责正确的文件。

### 9.4 Issue 与 PR

- [ ] #286 不再以旧 SMA21/watch 身份充当当前任务；
- [ ] #259 不再要求当前已退出范围的旧完整复原路线；
- [ ] #307 与 `subing_ths_15m_v3` 和真实 pending Gate 一致；
- [ ] PR #333 不再把旧 SHA 的 Review 冒充 current-head Review；
- [ ] 未关闭任何仍承担独立外部 Gate 的 Issue。

### 9.5 代码与测试

- [ ] 未恢复退役 active surface；
- [ ] 未新增第二套 MarketDataService、主力解析、公式或路由 authority；
- [ ] page-parity、repainting、causal-research、Alert 和账户语义仍严格隔离；
- [ ] `TESTING.md` 规定的全部适用检查真实通过；
- [ ] Standards Review 与 Spec Review 在同一 exact head 上均为 P1=0、P2=0。

### 9.6 完成状态

只有上述标准全部满足，才允许写：

```text
DEVELOP_CONVERGED
```

该状态只表示新的开发集成基线成立，不表示：

```text
RELEASED
RUNTIME_READY
NEWOW_PRODUCT_COMPLETE
NEWOW_CAUSAL_RESEARCH_COMPLETE
PAPER_ACCOUNT_READY
```

---

## 10. 推荐任务拆分

本文批准后，Implementation Plan 应严格按以下顺序拆分，避免一个超大 diff 同时做审计、删除、修复和 branch 清理：

```text
Task A：exact baseline inventory 与 blocker 分类
Task B：.playwright-cli / raw capture / distribution P1 收敛
Task C：canonical、task docs、Issue 与 PR 元数据收敛
Task D：退役面、双重 authority、构建与测试回归修复
Task E：全量验证和 repository-hygiene guard
Task F：普通残留 branch/worktree 安全清理
Task G：exact-head 双轴 Review 与 develop 集成
```

A–E 在同一总体任务下可以分 commit，但不得在 A 完成前执行 B–F。F 只处理已证明安全的普通 branch。G 不自动触发 release、main、tag 或 Runtime。

---

## 11. 人工审查重点

用户审查本文时应重点确认：

1. 是否接受把 `.playwright-cli/**` 作为公开仓库不应保留的原始采集产物；
2. Newow 第三方截图是继续保留并明确批准分发，还是 fail-closed 删除后只保留 hash/派生 evidence；
3. 是否接受 #286、#259 作为 superseded/not-planned 候选；
4. 是否同意 #307 保持 open，只修正为当前 v3 与真实 Gate；
5. 是否同意 PR #333 只做 stale metadata 修正，不把当前 `develop` 重新塞入 `v1.9.15`；
6. 是否同意在本任务中清理全部已证明为 `develop` 祖先的普通残留 branch；
7. 是否接受最终结论仅为 `DEVELOP_CONVERGED`，不携带任何发布或 Runtime 授权。
