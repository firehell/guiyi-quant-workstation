# TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819

> 主力照妖镜·期货 V1 的单一 executable contract。Issue 是远程生命周期入口，Spec 是业务/数学设计权威，Implementation Plan 是逐步执行权威；本文件固定任务边界、调度、Gate、停止码和 Codex 主 Prompt。

## 0. Metadata

| Field | Value |
| --- | --- |
| Task ID | `TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819` |
| GitHub Issue | `#179` |
| Spec | `docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md` |
| Implementation Plan | `docs/superpowers/plans/2026-08-19-main-force-mirror-futures-v1.md` |
| Existing V0 | `main_force_mirror_v0@designed-v0` |
| New V1 | `main_force_mirror_futures_v1@futures-research-v1` |
| Planning baseline | `develop@7e58cfd07a1d274b4e206603496b0d79d302528b` (hardened Plan commit); execution still uses the then-latest `origin/develop` |
| Execution base | execution-time latest clean `origin/develop` containing Spec-fix commit `a5180f97c5ac6675a6d73e6a48bc837efac8be06` |
| Status | `PLAN_READY / AWAITING_IMPLEMENTATION_APPROVAL` |
| Owner | `firehell` |
| External side effects | none authorized |
| Release/Runtime | not authorized |

## 1. Current Judgment

The approved design is ready for implementation planning and task dispatch.

The current V0 remains a published historical-reproduction observation. V1 is a new futures-only observation based on:

```text
OHLCV
+ open interest
+ exact physical contract
→ five futures position-pressure states
→ long/short chase caution scores
→ episode latch/re-arm
→ Web observation
→ read-only Historical Shadow
```

V1 does not identify a participant account, member seat, net-long owner, net-short owner, or measured capital flow. Its threshold `70` is an evidence score, not a percentage or reversal probability.

This TASK does not authorize implementation merely by existing. Each implementation Task starts only after the user explicitly approves that Task or the full implementation sequence.

## 2. Approved Review Resolutions

The implementation must preserve all nine frozen resolutions:

1. Direction conflict emits no directional event, consumes neither latch, performs no re-arm, and pauses counters.
2. `state_ready` begins at block index 20; `caution_ready/ready` begins at block index 30; `warmup_bars=30`, `lookback_bars=31`.
3. OI is required. Missing/null/non-finite/negative OI invalidates the whole bar and resets the block; the OI reason is a diagnostic specialization.
4. A bad/non-increasing timestamp invalidates the offending bar; it cannot seed a new block; later bars must exceed the historical maximum parseable timestamp.
5. A false re-arm streak condition resets directly to zero; unavailable/warm-up pauses.
6. TURNOVER with exact zero direction has signed score zero.
7. The exact parameter is `liquidation_dominated_oi_threshold`.
8. Caution uses dynamic series markers, never fixed `+92/-92` numeric points.
9. Python and Web use `half_away_from_zero_binary64`; state/threshold decisions use raw values.

Changing any item requires a new Spec/version, not a “small implementation fix”.

## 3. Exact Scope

### Included

- Python V1 Indicator Kernel;
- exact Registry and FormalPolicy;
- V0 regression protection;
- per-bar physical-contract identity in Web read models;
- TypeScript Web mirror;
- one shared frozen Python/Web golden fixture;
- bottom-pane tabs `MACD / 主力照妖镜 / 原型V0`;
- dynamic bilateral caution markers and V1 hover facts;
- read-only Historical Shadow service and CLI;
- repository-native tests, build, documentation, independent review, develop-only closeout.

### Excluded

- any V0 formula/version/golden/capability change;
- frequencies other than 60m;
- continuous-series interpretation;
- member positions, L2, tick aggressor, second provider;
- measured fund-flow percentage or participant identity;
- formal backtest engine/API/Web/worker;
- Alert Rule/Scope/evaluator or notification;
- Execution Review automatic entry;
- DB/migration/Catalog/Canonical/Parquet/Redis mutation;
- background worker/queue/outbox;
- account, position, risk, order, or auto-order path;
- real representative-matrix Shadow run;
- formal evidence persistence;
- `main`, release/tag, Runtime reload/promotion.

## Codex 调度建议

- 任务车道：Lane 3 主控；内部按 Task 使用 Lane 3 / Lane 2 / Lane 1
- 执行入口：Codex App
- 推荐模型：Sol；Task 4 与 Task 6 可使用 Terra
- 推理强度：高；纯 Web plumbing 为中
- 会话：每个独立 Task 新开会话；Task 8 新开独立 Review 会话
- Plan：Lane 3 Task 为 Plan-only → 人工批准 → 执行；Lane 1/2 为 Plan-then-execute
- 工作区：每个 Task 从执行时最新 `origin/develop` 创建新 task branch/worktree
- 人工 Gate：Lane 3 Task Plan 批准 + 独立 Review；最终 whole-branch Review；release/Runtime/真实 Shadow 均未授权

涉及 worktree 的固定流转：

```text
execution-time latest origin/develop
→ one Task branch/worktree
→ RED/GREEN + scoped verification
→ required Review
→ integrate develop
→ read back develop ancestry
→ remove only the merged Task worktree/branch
```

- 从哪个 branch 创建：每次从最新 `origin/develop`
- 完成后集成到哪个 branch：`develop`
- 是否允许自动 task → `develop`：Lane 1/2 在测试与 Review clean 后允许；Lane 3 需 Task Plan/Review Gate
- 是否需要 PR：推荐；至少保留等价可审查 integration record
- 何时清理：确认提交已进入 `develop` 且 worktree clean 后
- 是否触及 `main`、tag 或 Runtime：不允许

## 4. Codex Dispatch Matrix

| Task | Lane | Entry | Model | Reasoning | Session | Plan | Workspace | Human Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Python contract/readiness/rounding | Lane 3 | Codex App | Sol | 高 | new | Plan-only → approved execution | new task worktree | Task Plan approval + independent review |
| 2 Python math/five states | Lane 3 | Codex App | Sol | 高 | new | Plan-only → approved execution | new task worktree | Task Plan approval + formula review |
| 3 Caution/latch/Registry/Policy/V0 guard | Lane 3 | Codex App | Sol | 高 | new | Plan-only → approved execution | new task worktree | Task Plan approval + independent review |
| 4 Web physical identity | Lane 2 | Codex App | Terra | 中 | new | Plan-then-execute | new task worktree | scoped tests/review |
| 5 Web mirror/golden parity | Lane 3 | Codex App | Sol | 高 | new | Plan-only → approved execution | new task worktree | parity review |
| 6 Web pane/marker/hover | Lane 2 | Codex App | Terra | 中 | new | Plan-then-execute | new task worktree | unit/E2E/build review |
| 7 Historical Shadow/CLI | Lane 1 | Codex App | Sol | 高 | new | Plan-then-execute | new task worktree | leakage/segment review |
| 8 Full verification/closeout | Lane 3 Review | Codex App | Sol | 高 | new independent Review | Review-only | closeout worktree | Critical=0 / Important=0 |

Default integration:

```text
latest develop
→ one Task branch/worktree
→ TDD + scoped tests
→ required review
→ integrate develop
→ read back ancestry
→ clean merged Task worktree/branch
```

Ordinary successful Task integration to `develop` does not authorize `main`, tag, Runtime, data writes, or notifications.

## 5. Task Sequence and Deliverables

### Task 1 — Python contract/readiness/rounding

Deliver:
- new Python module;
- exact constants/parameters/reasons;
- whole-bar OI validation;
- timestamp maximum handling;
- calculation-block reset;
- ATR/volume/range/OI readiness;
- `state_ready`, `caution_ready`, `ready`;
- shared half-away rounding;
- Task 1 tests.

Allowed conclusion:

```text
PYTHON_CONTRACT_READY
```

### Task 2 — Python math/five states

Deliver:
- price impulse;
- CLV/direction;
- relative volume/participation;
- OI impulse;
- long/short opening pressure;
- strength;
- LONG_BUILD, SHORT_BUILD, SHORT_COVER, LONG_LIQUIDATION, TURNOVER;
- signed-score and prefix-invariance tests.

Allowed conclusion:

```text
PYTHON_BASE_KERNEL_READY
```

### Task 3 — Caution/latch/policy

Deliver:
- eight reason conditions;
- 69/70 candidate boundary;
- conflict fail-closed;
- long/short latch and four re-arm paths;
- Registry 60m-only support;
- Web-only FormalPolicy;
- package exports;
- V0 unchanged regression;
- independent formula review.

Allowed conclusion:

```text
PYTHON_V1_POLICY_READY
```

### Task 4 — Web physical identity

Deliver:
- `BarData.physicalContract`;
- contract and actual-dominant Historical mapping;
- segment conflict fail-closed;
- snapshot/bar overlay identity;
- no `live_contract` guessing;
- prepend/replace/live preservation;
- Web unit/Market runtime regression.

Allowed conclusion:

```text
WEB_PHYSICAL_IDENTITY_READY
```

### Task 5 — Web mirror/golden

Deliver:
- one shared root golden fixture;
- TypeScript mirror;
- identical rounding and operation order;
- exact point-by-point Python/Web comparison;
- conflict/re-arm/OI gap/timestamp/segment/readiness/tie cases;
- independent parity review.

Allowed conclusion:

```text
PYTHON_WEB_PARITY_READY
```

### Task 6 — Web pane/markers/hover

Deliver:
- tabs `MACD / 主力照妖镜 / 原型V0`;
- MACD default;
- V1 support/disabled logic;
- V1 histogram;
- dynamic long/short markers;
- no fixed caution numeric point;
- V1 hover and reason display;
- V0 still accessible;
- no-refetch E2E and production build.

Allowed conclusion:

```text
WEB_OBSERVATION_READY
```

### Task 7 — Historical Shadow/CLI

Deliver:
- MarketDataService-only service;
- 60m contract/actual-dominant validation;
- directional events;
- conflict diagnostic only;
- 1/3/5/10 same-segment outcomes;
- readonly stdout CLI;
- no persistence/promotion;
- leakage/identity review.

Allowed conclusion:

```text
READONLY_SHADOW_CODE_READY
```

This conclusion does not mean a real Shadow matrix was executed.

### Task 8 — full closeout

Deliver:
- full backend/engineering/Ruff/Mypy/Web/E2E/build/safety checks;
- updated Indicator Kernel and Testing canonical docs;
- independent final Review;
- develop-only STATUS entry after all gates;
- readback and cleanup.

Allowed conclusion:

```text
DEVELOP_IMPLEMENTATION_VERIFIED
```

## 6. Stable Stop Codes

Stop instead of guessing when any condition applies:

```text
FORMULA_DRIFT_REQUIRES_NEW_VERSION
```

A fix requires changing a frozen parameter, formula, threshold, evidence weight, readiness index, conflict/latch/re-arm, rounding, or supported identity.

```text
PHYSICAL_IDENTITY_CONTRACT_UNRESOLVED
```

The Web/Shadow path cannot bind each required bar to exactly one physical contract without guessing or changing the Market data contract.

Resolved amendment (2026-08-20): the implementation added `ContractTradingDayQuery` /
`MarketDataService.query_contract_trading_days` as the authoritative physical-contract trading-day seam. The seam requires complete Calendar rows, resolves TradingSession bounds, and clamps to the Catalog `[listed_date, expired_date)` window. Because the exact contract is now frozen in `docs/DATA_CENTER.md` and consumers no longer guess boundaries, this stop condition is resolved rather than bypassed.

```text
PYTHON_WEB_PARITY_BLOCKED
```

The same shared fixture does not produce exact identical public output after verifying operation order and rounding.

```text
V0_REGRESSION_DETECTED
```

V0 output, metadata, Registry, policy, or Web behavior changes.

```text
SHADOW_DATA_IDENTITY_BLOCKED
```

The read-only research service would need direct Parquet/provider/Redis access, copied rank1 resolution, or cross-segment outcomes.

```text
FULL_VERIFICATION_FAILED
```

Any required Task 8 command fails or cannot be run in the required isolated environment.

```text
CANONICAL_CONFLICT
```

`STATUS.md`, `AGENTS.md`, `docs/DEVELOPMENT.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `docs/INDICATOR_KERNEL.md`, the Spec, or later accepted ADR contradicts this Task.

A stop code is a blocking result, not permission to weaken validation.

## 7. Acceptance Gates

### Formula/Kernel

- V0 exact regression remains green.
- V1 parameters/hash/support/capabilities match Spec.
- OI and timestamp invalidation match exact block semantics.
- readiness indices are exact.
- all five states and boundaries pass.
- all eight bilateral reasons pass.
- 69 does not trigger; 70 triggers.
- conflict does not consume latches.
- all four re-arm paths and reset/pause rules pass.
- binary64 half-away parity passes.

### Web

- every V1-ready bar has exact `physicalContract`;
- contract/actual-dominant mapping is deterministic;
- unsupported identity is disabled, not silently substituted;
- tabs are exact and local;
- marker direction/text/score is exact;
- no fixed ±92 caution data exists;
- hover distinguishes missing, warm-up, caution warm-up, conflict, ready;
- switching tabs does not fetch bars or alter the main chart; persistent Alert markers remain intact across their legal 5m/15m MACD/V0 pane switch, while 60m-only Futures V1 dynamic markers are verified independently because the two support sets do not overlap;
- no responsive overflow;
- production build passes.

### Shadow

- only `MarketDataService`;
- no future leakage into event creation;
- outcomes stay inside one physical segment;
- conflict is diagnostic, not event;
- CLI is readonly stdout JSON;
- no promotion/recommendation/profitability field;
- no real matrix run under this contract.

### Final

- full repository-native checks pass;
- secret scan has zero findings;
- diff check passes;
- independent Review has Critical=0 / Important=0;
- STATUS says develop-only and no more.

## 8. Worktree and Integration Rules

For each implementation Task:

1. fetch `origin`;
2. create from current latest `origin/develop`;
3. verify Spec-fix commit `a5180f97...` is an ancestor;
4. read current canonical docs and exact Task section;
5. modify only listed Task files;
6. run RED before implementation;
7. run GREEN and scoped regression;
8. perform self-review;
9. obtain required independent review;
10. integrate only to `develop`;
11. read back the integrated commit;
12. remove only that merged Task worktree/branch.

Do not:
- reuse a stale Task branch after `develop` changes;
- force-update refs;
- mix two independent Tasks in one branch;
- clean another Task’s worktree;
- touch `main`, tag, release, Runtime, production data, or notification.

## 9. Copyable Codex Master Prompt

```text
请先读取并遵守：

1. STATUS.md
2. AGENTS.md
3. docs/DEVELOPMENT.md
4. PROJECT_SOURCE.md
5. DECISIONS.md
6. docs/INDICATOR_KERNEL.md
7. docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md
8. docs/superpowers/plans/2026-08-19-main-force-mirror-futures-v1.md
9. docs/tasks/TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819.md
10. GitHub Issue #179

你正在执行主力照妖镜·期货 V1 的一个明确 Task，不是自由重构。

先确认：
- 当前基线是 execution-time 最新、clean 的 origin/develop；
- `a5180f97c5ac6675a6d73e6a48bc837efac8be06` 是当前基线祖先；
- 当前 Task 的 Lane、模型、Plan 模式、允许文件和禁止范围；
- main、tag、release、Runtime、真实通知、真实 Shadow、DB/Canonical 写入均未获授权。

必须使用 Superpowers：
- 实现会话使用 subagent-driven-development（推荐）或 executing-plans；
- 每个行为先写失败测试并实际观察 RED；
- 最小实现后观察 GREEN；
- 完成 Task 后进行自审和要求的独立 Review；
- 声明完成前运行该 Task 的完整验证命令。

数学和业务权威只看已批准 Spec：
- V0 零修改；
- V1 仅 60m + contract|actual_dominant；
- OI 必需，缺失整根 invalid；
- state_ready 第21根、完整 ready 第31根；
- conflict 不消耗 latch；
- re-arm 中断清零、unavailable 暂停；
- TURNOVER direction=0 输出0；
- 参数名 liquidation_dominated_oi_threshold；
- marker 动态附着，不使用固定 ±92；
- half_away_from_zero_binary64；
- 70 是证据评分，不是资金比例或概率。

不得：
- 调整公式、参数、阈值、权重、reason、readiness 或支持周期；
- 读取/输出凭据；
- 直读 Parquet、调用 RQData、复制主力 resolver；
- 新增 Alert/通知/订单/DB/Catalog/Canonical/Redis/worker/queue；
- 发布 main/tag 或切换 Runtime；
- 运行真实代表矩阵 Shadow；
- 用部分测试冒充完整通过。

如发现必须改变设计，输出：
FORMULA_DRIFT_REQUIRES_NEW_VERSION

如无法确定物理合约，输出：
PHYSICAL_IDENTITY_CONTRACT_UNRESOLVED

如 Python/Web 不一致，输出：
PYTHON_WEB_PARITY_BLOCKED

如 V0 变化，输出：
V0_REGRESSION_DETECTED

如 Shadow 身份/泄漏边界失败，输出：
SHADOW_DATA_IDENTITY_BLOCKED

如验证失败，输出：
FULL_VERIFICATION_FAILED

当前只执行用户明确批准的 Task N。
按 Plan 中 Task N 的步骤逐项完成，不提前执行后续 Task。

完成后输出：
- baseline branch/commit
- 修改文件
- RED 证据
- GREEN 与回归结果
- Review 结论
- 公式/身份/能力边界核对
- commit/PR/集成结果
- develop ancestry readback
- worktree/branch 清理结果
- 风险、停止码和未完成项

不得把 develop 实现写成 release、Runtime-ready、策略有效、可盈利或可交易。
```

## 10. Required Codex Completion Report

Every Task report contains:

```text
Task ID
Task number and Lane
base develop commit
task branch/worktree
changed paths
RED command and observed failure
GREEN/scoped commands and result
review findings and resolution
V0 guard result
forbidden-path scan result
commit SHA
develop integration/readback
cleanup result
remaining risks
final decision
```

Allowed final decisions:

```text
允许继续实现
允许集成 develop
要求修正后再集成
阻塞
```

No other phrase grants release, tag, Runtime, real Shadow, evidence persistence, Alert, notification, data write, or order permission.

## 11. Current Handoff

Current document state:

```text
Spec: approved and review gaps resolved
Plan: ready
TASK: ready
Issue #179: lifecycle entry
Implementation: not started by this documentation action
Release/Runtime/real Shadow: not authorized
```

Next legitimate action is an explicit user approval to start Task 1 or the full Task 1–8 implementation sequence. Lane 3 Tasks still retain their Plan/review Gates even when the overall sequence is approved.
