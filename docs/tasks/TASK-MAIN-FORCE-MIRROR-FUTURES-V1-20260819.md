# TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819

> 单一执行合同：实现 `main_force_mirror_futures_v1` 的 60m 期货方向性持仓压力观察、双向追价警戒、Web 三 Tab 与只读 Historical Shadow。本文只调度仓库开发；不授权 release、Runtime、真实 Shadow、通知、DB/Canonical 或订单。

## 0. 元信息

| 字段 | 值 |
| --- | --- |
| Task ID | `TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819` |
| GitHub Issue | `#179` |
| Status | `PLAN_READY` |
| Spec | `docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md` |
| Implementation Plan | `docs/superpowers/plans/2026-08-19-main-force-mirror-futures-v1.md` |
| Existing V0 | `main_force_mirror_v0 / designed-v0` — frozen |
| New V1 | `main_force_mirror_futures_v1 / futures-research-v1` |
| Base | 每个 Task 执行时最新 `origin/develop`，必须包含本 Spec/Plan/TASK |
| Product Scope | `60m + contract|actual_dominant` only |
| Capability | `observation_only`; Web yes; backtest/live/alert/notification no |
| External Side Effects | none |
| Owner Gate | 当前仅 Plan/TASK 完成；Task 1 代码实现仍等待用户明确批准；release/Runtime/真实 Shadow/evidence/通知/DB 另行授权 |

## 1. 当前判断

这是一个**混合车道但整体按高风险公式合同调度**的任务：

```text
Lane 3：Python Indicator Kernel 公式、readiness、rounding、caution/latch、Python/Web parity
Lane 2：Web physical-contract plumbing、三 Tab、marker、hover
Lane 1：Historical-only Shadow service / CLI
Lane 3 review：whole-branch final review / canonical closeout
```

V1 是新版本，不允许原地改 V0。任何实现者发现需要改变已批准参数、权重、阈值、readiness、rounding、conflict 或 re-arm 规则时必须停止并输出：

```text
FORMULA_DRIFT_REQUIRES_NEW_VERSION
```

不得以“效果更好”为理由修改 `futures-research-v1`。

## 2. Codex 总调度建议

- 任务车道：Lane 3 主控；内部含 Lane 2 / Lane 1 子任务
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开总控会话；每个 Task fresh 子会话/agent
- Plan：Plan-then-execute；严格执行已批准 Spec/Implementation Plan，不重新 brainstorming
- 工作区：每个 Task 从执行时最新 `develop` 创建新 task branch/worktree
- 人工 Gate：Task 1 首次实现前需要用户明确批准；Lane 3 Task 独立 Review；最终 whole-branch 独立 Review；release/Runtime/真实 Shadow 均不在本合同

### Worktree / Branch / PR 规则

```text
latest origin/develop
→ task branch/worktree
→ task RED/GREEN/verification/self-review
→ task PR or equivalent reviewable integration record → develop
→ read back develop ancestry
→ cleanup merged task worktree/branch
```

- Task 1 未获新的明确实现批准前不得创建实现 worktree 或修改代码；
- Task 1/2/4 必须独立 Review 后才可进 `develop`；
- Task 3/5/6 也必须跑本合同定向测试；可由 Codex 在 review clean 后自动集成 `develop`；
- Task 7 使用新独立 Sol Review 会话；Critical/Important 必须为 0；
- 所有 Task 都从**当时最新 develop** 开始，不能长期堆叠在一个陈旧 task branch；
- 不允许任何 task branch 直接合并 `main`；
- 不创建正式 tag；
- 不修改 Runtime worktree；
- task branch 合入并读回 `develop` 后才清理；未合入/有未提交文件时不强制删除。

## 3. Task Dispatch Matrix

| Task | Lane | 模型 | 推理 | Session | Branch 建议 | Review | 完成码 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Contracts/readiness/rounding | Lane 3 | Sol | 高 | 新 | `research/mfm-futures-v1-contracts` | 独立 | `MFM_FUTURES_V1_CONTRACTS_READY` |
| 2 Python kernel/caution/latch | Lane 3 | Sol | 高 | 新 | `research/mfm-futures-v1-kernel` | 独立 | `MFM_FUTURES_V1_KERNEL_READY` |
| 3 Web physical contract | Lane 2 | Terra | 中 | 新 | `feat/mfm-futures-v1-physical-contract` | task review | `MFM_FUTURES_V1_IDENTITY_READY` |
| 4 Web mirror/parity | Lane 3 | Sol | 高 | 新 | `feat/mfm-futures-v1-web-mirror` | 独立 | `MFM_FUTURES_V1_PARITY_READY` |
| 5 Web pane/marker/hover | Lane 2 | Terra | 中 | 新 | `feat/mfm-futures-v1-web-pane` | task review | `MFM_FUTURES_V1_WEB_READY` |
| 6 Shadow service/CLI | Lane 1 | Sol | 高 | 新 | `research/mfm-futures-v1-shadow` | task review | `MFM_FUTURES_V1_SHADOW_CODE_READY` |
| 7 Regression/final review | Lane 3 review | Sol | 高 | 新独立 Review | `docs/mfm-futures-v1-closeout` 或 read-only review worktree | whole-branch | `MFM_FUTURES_V1_DEVELOP_VERIFIED` |

Terra 两轮无法解决、根因涉及 formula/physical identity/parity、或范围跨三个以上模块时，停止当前 Terra 会话并用 Sol 新会话重新分析；不得在已混乱上下文中继续猜。

## 4. 绝对禁止范围

任何 Task 均不得：

- 修改 `main_force_mirror_v0` 数学、version、golden 或 capability；
- 把 70 写成资金流百分比、反转概率或主力账户事实；
- 引入会员席位、Level-2、逐笔或第二 provider；
- 新增/修改 DatasetKey、八表 Market Catalog、Canonical schema 或 Parquet 分区模型；
- 新增 DB/migration/Redis lifecycle state/worker/queue/outbox；
- 新增 Alert Rule、Scope、Alert evaluator、Clawbot、真实微信；
- 修改 Execution Review；
- 恢复通用 backtest API/Web/worker；
- 调 provider、执行正式 Canonical/DB 写入；
- 执行真实 `jm/ag/cu/m/sc` representative Shadow；
- 保存正式 research evidence；
- release `main` / tag；
- reload/promote Runtime；
- 创建订单、连接账户或自动改变仓位。

## 5. 全局公式硬合同

Codex 不得重新解释以下规则：

```text
period                 = 60m only
series                 = contract | actual_dominant
state first ready      = block index 20 / 21st bar
caution/ready first    = block index 30 / 31st bar
OI                     = required input
caution threshold      = 70 / 100 evidence score
round                  = half_away_from_zero_binary64 / 6 digits
long conflict behavior = no event / no latch consume / no re-arm
short conflict behavior= same
re-arm interruption    = streak reset to 0
warmup/unavailable     = pause latch/re-arm counters
input/OI/id/time invalid= block reset
timestamp offender     = invalid; cannot seed new block
contract switch        = valid new contract bar may seed new block index 0
TURNOVER direction=0   = signed score 0
caution marker         = dynamic series marker; no fixed ±92 point
```

Exact parameters、reason precedence、公式与权重只看 Spec；聊天解释不是第二事实源。

## 6. Task 1 执行合同 — Exact Contracts / Readiness / Rounding

### 目标

先建立不对外注册的 V1 Python domain contract：exact parameters、result shape、valid/block/readiness、timestamp/OI reset 与统一 rounding。

### 允许修改

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
services/quant-api/tests/test_main_force_mirror_futures.py
```

### 禁止

Task 1 不修改 Registry/Policy/Web，不让半完成 indicator 成为 consumer-visible。

### 测试实现注意

`ready/state_ready/caution_ready` 最终为 NumPy bool arrays；测试不得写：

```python
assert result.state_ready[19] is False
```

因为 `np.bool_ is False` 不是值比较。必须写：

```python
assert not bool(result.state_ready[19])
assert bool(result.state_ready[20])
assert not bool(result.caution_ready[29])
assert bool(result.caution_ready[30])
```

这条执行合同覆盖 Plan 中示例断言的 Python identity 语法歧义，不改变 readiness 业务语义。

### 验收

- exact parameter key-set 等于 Spec；
- 参数名只有 `liquidation_dominated_oi_threshold`；
- positive/negative half-tie；
- `-0 → 0`；
- OI missing/null/nonfinite/negative invalid；
- timestamp duplicate/regression/offender/new seed；
- state index20 / caution index30；
- contract A→B reset；
- pytest + Ruff + diff check GREEN；
- Independent Task Review Critical=0 / Important=0。

### 完成流转

在用户明确批准 Task 1 implementation 后执行；Review clean 后合入 `develop`；读回 ancestry 后清理分支/worktree。

## 7. Task 2 执行合同 — Python Kernel / Caution / Latch

### 目标

完成 Python authoritative exact math、five-state、signed score、双向 evidence score、conflict、Episode latch/re-arm，并在完成后登记 Registry/Policy。

### 允许修改

```text
packages/quant-core/guiyi_quant/indicators/main_force_mirror_futures.py
packages/quant-core/guiyi_quant/indicators/__init__.py
packages/quant-core/guiyi_quant/indicators/registry.py
packages/quant-core/guiyi_quant/indicators/policy.py
services/quant-api/tests/test_main_force_mirror_futures.py
services/quant-api/tests/test_indicator_registry_v1.py
services/quant-api/tests/test_main_force_mirror.py   # regression assertions only
```

### 验收

- ATR14 Wilder seed；volume20；OI abs-delta EMA20 SMA seed；range20；
- five states + deadband exact thresholds；
- TURNOVER cap/zero；
- all 8 reason weights；
- 69/70 boundary；
- conflict/latch exact semantics；
- four re-arm paths + counter reset/pause；
- prefix invariance；
- V0 regression unchanged；
- Registry `("60m",)` only；
- FormalPolicy only `Web_manual_observation` allowed；
- test/Ruff/diff GREEN；Review clean。

## 8. Task 3 执行合同 — Web Physical Contract Identity

### 目标

给每根 Web Bar 建立可验证 physical contract identity，使 actual-dominant 换月成为真实 calculation reset，而不是价格/OI 假信号。

### 允许修改

```text
apps/quant-web/src/types/market.ts
apps/quant-web/src/composables/useMarketSeries.ts
apps/quant-web/tests/marketSeries.test.ts
```

### 实现细节

可增加 Web-only：

```ts
physicalContract?: string
physicalContractReason?:
  | 'MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING'
  | 'MFM_FUTURES_V1_SEGMENT_CONFLICT'
```

不得修改 Canonical DTO/HTTP schema 来保存该字段。

### 验收

contract、actual_dominant exact one/zero/multiple segment、prepend page、snapshot、subsequent bar、no-identity bar 均有测试；不得从 `live_contract` 猜普通 bar identity；Node test + diff GREEN。

## 9. Task 4 执行合同 — Web Mirror / Shared Golden

### 目标

实现 `mainForceMirrorFutures.ts`，与 Python authority 共用一份 deterministic golden，逐点锁定 9 项用户 Review 边界。

### 允许修改/新增

```text
apps/quant-web/src/utils/mainForceMirrorFutures.ts
apps/quant-web/tests/mainForceMirrorFutures.test.ts
tests/fixtures/main_force_mirror_futures_v1_golden.json
services/quant-api/tests/test_main_force_mirror_futures.py
```

### 验收

单 fixture 同时覆盖 2 contracts、5 states、long/short warning、conflict、re-arm、missing OI、timestamp regression、half-ties、state/caution readiness；Python 与 Web 所有 public fields deep-equal；prefix invariance；Review clean。

不得创建 Python fixture + Web fixture 两份人工副本。

## 10. Task 5 执行合同 — Three Tabs / Dynamic Marker / Hover

### 目标

现有 pane 2 改为：

```text
MACD | 主力照妖镜 | 原型V0
```

其中 `主力照妖镜`=Futures V1，`原型V0`=已发布 V0；默认仍 MACD。

### 允许修改

```text
apps/quant-web/src/components/kline/KlineChart.vue
apps/quant-web/src/components/kline/KlineHoverLegend.vue
apps/quant-web/src/utils/klineViewModel.ts
apps/quant-web/src/types/market.ts
apps/quant-web/src/pages/market/chart.vue
apps/quant-web/src/styles/chartTheme.ts
apps/quant-web/src/styles/tokens.css
apps/quant-web/tests/kline-view-model.test.ts
apps/quant-web/e2e/main-force-mirror-futures.spec.mjs
apps/quant-web/e2e/main-force-mirror.spec.mjs
apps/quant-web/e2e/market-runtime.spec.mjs  # 仅已有 harness 所需回归
```

### 验收

- V1 only enabled for 60m contract/actual_dominant；
- 15m/continuous disabled；
- Tab switch no refetch；
- pane count unchanged；
- three series/marker families clear each other；
- long marker above/arrowDown、short below/arrowUp；
- no `±92` value；
- strength 100 不改变 marker scale；
- Hover 有 physical contract/state/readiness/OI/score/reason；
- 70 disclaimer visible；
- V0 original formula UI still available；
- Web unit、target Playwright、production build GREEN。

## 11. Task 6 执行合同 — Historical Shadow Code / CLI

### 目标

建立只读 `guiyi research main-force-mirror-futures`，复用 MarketDataService + Python kernel，计算 segment-local warnings 与 1/3/5/10 outcome summaries。

### 允许修改/新增

```text
services/quant-api/app/market_data/main_force_mirror_futures_research_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py
services/quant-api/tests/test_research_cli.py
```

### 验收

- request rejects unsupported series/frequency；
- contract requires contract；
- actual_dominant uses existing resolver/segments；
- no direct Parquet/provider/Redis；
- conflict not event；
- outcomes do not cross segment；
- stdout readonly JSON；
- no evidence file/DB/Canonical write；
- no promotion/recommendation field；
- tests/Ruff/diff GREEN。

真实代表矩阵 `jm/ag/cu/m/sc` 不在本 Task 执行。

## 12. Task 7 执行合同 — Full Regression / Independent Review / Closeout

### 目标

执行仓库原生完整验证、独立 whole-branch Review，只有 clean 后更新 canonical docs 和 `STATUS.md` develop-only 状态。

### 允许修改

```text
docs/INDICATOR_KERNEL.md
TESTING.md
STATUS.md  # only after all verification + review pass
```

Review finding 的代码修复可修改 Task 1–6 已触及文件，但必须先补 regression test。

### Required verification

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror_futures.py \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/data_foundation/test_main_force_mirror_futures_research_service.py \
  services/quant-api/tests/test_research_cli.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror-futures.spec.mjs \
  e2e/main-force-mirror.spec.mjs \
  e2e/market-runtime.spec.mjs
pnpm --dir apps/quant-web build

python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

执行时如果最新 `TESTING.md` 要求更多受影响测试，以最新文件为准，只能增加不能删减。

### Review Gate

新独立 Sol Review：

```text
Critical = 0
Important = 0
```

重点逐条审：

1. conflict 不消耗 latch；
2. state 21 / caution 31；
3. OI 缺失整根 invalid；
4. timestamp offender 不 seed；
5. streak interruption reset=0；
6. TURNOVER zero；
7. parameter rename；
8. dynamic marker no ±92；
9. half-away Python/Web parity；
10. V0 invariance；
11. physical segment reset；
12. no Alert/DB/Runtime/order path。

### STATUS 允许写入的唯一结论

```text
main_force_mirror_futures_v1
DEVELOP CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE
observation_only
```

并明确：未 release、未 Runtime promotion、未真实 representative Shadow、未正式 evidence、未 Alert/notification。

## 13. 全局失败码 / 停止条件

Codex 遇到以下情况不得自行降级：

```text
FORMULA_DRIFT_REQUIRES_NEW_VERSION
MFM_FUTURES_V1_FREQUENCY_UNSUPPORTED
MFM_FUTURES_V1_SERIES_UNSUPPORTED
MFM_FUTURES_V1_SEGMENT_CONFLICT
MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING
MFM_FUTURES_V1_TIMESTAMP_INVALID
MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE
MFM_FUTURES_V1_INPUT_INVALID
MFM_FUTURES_V1_WARMUP
MFM_FUTURES_V1_CAUTION_WARMUP
MFM_FUTURES_V1_ATR_INVALID
MFM_FUTURES_V1_VOLUME_BASELINE_INVALID
MFM_FUTURES_V1_RANGE_INVALID
MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT
```

这些是业务结果/诊断；真正停止整个实现的条件是：active canonical 与 Spec 冲突、需要新公式选择、测试无法在不改变业务合同的前提下修复、或会触发本合同禁止的真实外部副作用。

## 14. 每个 Codex 会话的最小执行 Prompt

```text
请先阅读最新：
- STATUS.md
- AGENTS.md
- docs/DEVELOPMENT.md
- PROJECT_SOURCE.md
- DECISIONS.md
- docs/superpowers/specs/2026-08-19-main-force-mirror-futures-v1-design.md
- docs/superpowers/plans/2026-08-19-main-force-mirror-futures-v1.md
- docs/tasks/TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819.md

执行 TASK-MAIN-FORCE-MIRROR-FUTURES-V1-20260819 的 Task <N>。

只有在用户已明确批准当前 Task implementation 时才执行；否则只读 Plan 并停止在 Gate 前。
以本 Task 执行时最新 origin/develop 创建独立 task branch/worktree。
Spec 是公式/行为最高权威；Plan 是实施步骤；TASK 是允许/禁止与流转合同。

必须 TDD：先 RED，确认失败，再最小 GREEN。
不得改变 V0，不得重新选择 V1 参数/阈值/readiness/conflict/re-arm/rounding。
若必须改变公式，停止并输出 FORMULA_DRIFT_REQUIRES_NEW_VERSION。

不得触碰 main/tag/release/Runtime、真实 Shadow、DB/Canonical、Alert/Scope/通知或订单。

完成后：
1. 运行本 Task 定向验证；
2. 自审 scope 与 forbidden paths；
3. 按调度矩阵完成独立 Task Review；
4. review clean 后按仓库流程集成 develop；
5. 读回 develop ancestry；
6. 安全清理已合并临时 worktree/branch；
7. 输出修改摘要、RED/GREEN 证据、测试结果、Review 结果、集成/清理结果、风险和未完成项。
```

将 `<N>` 替换为 1–7 的精确 Task 编号，不得一次 Codex 会话跨多个独立 Task 实现；Task 7 whole-branch Review 除外。

## 15. 用户最终审查重点

用户不需要逐行审核所有机械代码，重点确认：

- 五状态的解释仍是“更偏向”，没有变成主力账户事实；
- 70 仍是 evidence score；
- OI/换月 identity 没有被 fallback；
- conflict/latch/re-arm 与 approved Spec 一致；
- Python/Web golden 没有通过重复两份实现“假一致”；
- V0 可以继续历史复现；
- Web 的“主力照妖镜”已经是 Futures V1，“原型V0”明确区分；
- Shadow 只产生研究统计，没有 promotion；
- `STATUS.md` 没有提前宣布 release/Runtime/策略有效。

## 16. 当前结论

```text
PLAN_READY
WAITING_FOR_TASK1_IMPLEMENTATION_APPROVAL
```

该结论只代表设计、Implementation Plan 和 TASK 执行合同完整；不代表任何代码 Task 已执行，也不构成 Lane 3 Task 1 的实现授权，更不授权 release、Runtime 或真实研究运行。
