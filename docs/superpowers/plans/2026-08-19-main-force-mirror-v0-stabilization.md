# Main Force Mirror V0 Post-Merge Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对已经由 PR #171 合入 `develop` 的 `main_force_mirror_v0` 完成仓库原生稳定化验收：冻结现有 designed-v0 数学口径与“小心”公式，补足必要边界回归，执行完整 Python/Web/E2E/build 验证，并仅在全部 Gate 通过后记录准确的 develop-only 状态。

**Architecture:** 本计划不重新实现主力照妖镜，也不重新设计六色柱。Python Indicator Kernel 继续是唯一业务口径权威，Web `mainForceMirror.ts` 继续只是浏览器观察镜像；最底部副图继续由 `MACD / 主力照妖镜` Tab 复用同一 pane。稳定化任务先做 merge-baseline 与 contract characterization，再补足精确边界测试和 Web 交互验收；任何生产代码修复都必须由先失败的回归测试驱动，且只能修复与当前 canonical 不一致的实现 bug。若修复需要改变 designed-v0 数学语义，必须停止并升级为新的公式设计任务。

**Tech Stack:** Python 3.13、NumPy、Indicator Kernel、Vue 3、TypeScript、Lightweight Charts 5.2、Node test、Playwright、pytest、Ruff、Mypy、Vite。

**Spec:** `docs/INDICATOR_KERNEL.md`（`主力照妖镜 observation V0` 为本计划唯一公式与业务语义依据）

## Global Constraints

- 执行基线必须从当时最新 `develop` 创建；其 ancestry 必须包含 PR #171 merge commit `ee35631a0ac750dbff43295be0fc130d78a042a1`。若最新 `develop` 与本 Plan 或 `docs/INDICATOR_KERNEL.md` 冲突，先停止并重新评估，不按旧计划猜测。
- 当前 V0 数学口径冻结为：`CLV`、20 周期相对成交量、`EMA(raw_flow, 5)`、20 周期区间位置和当前六状态分类规则；稳定化任务不得调整窗口、阈值、权重、符号、颜色语义或状态命名以“优化效果”。
- “小心”必须精确保持为用户提供的通达信逻辑：`rising_edge(BARSLAST(HIGH = HHV(HIGH, 5)) < 10)`，显示 level 固定为 `50`。不得把它改为资金流阈值、超买阈值、峰值未来确认、成交量过滤或六色柱派生条件。
- `main_force_mirror_v0` 继续是 `observation_only`；`web=true`，`backtest=false`，`live=false`，`alert=false`。FormalPolicy 只允许 `Web_manual_observation`，并明确阻断 `formal_backtest/live/alert/notification`。
- 六色柱继续被定义为 OHLCV 设计代理；不得生成或暴露 `outflow_ratio`、主力净流出百分比、账户身份、Level-2 结论或“70% 已流出”的计算事实。
- 最底部副图默认仍为 MACD；Tab 切换不得新增行情请求、改变 `selectedOverlay`、EMA 偏好、行情 identity、主图 pane、成交量 pane 或 Alert marker 语义。
- 不新增 API、数据库表、Catalog、Canonical 字段、Redis 状态、worker、queue、Alert Rule、Scope、通知、Execution Review 自动入口或订单路径。
- 本计划不授权 `main`、release、tag、Runtime switch/promotion、开发态 Runtime reload、真实通知、Scope mutation、生产 DB/Canonical 写入或任何订单操作。
- 任一发现若需要对 designed-v0 数学口径作新的业务选择，稳定化任务必须输出 `FORMULA_DRIFT_REQUIRES_NEW_TASK` 并停止；不得在本任务中顺手改公式。
- 任一生产代码修复遵守 TDD：先新增能稳定复现问题的失败测试并观察 RED，再做最小修复；已有行为的 characterization 测试可以直接 PASS，但其通过不授权生产代码改动。
- `STATUS.md` 只能在所有仓库原生验证、独立 Review 均通过后更新；只能记录 `develop` 已验证实现，不得宣称 release、production Runtime、Alert、盈利或策略有效。
- 文档/测试/代码中不得读取、记录或提交凭据。tracked 内容变化后运行 `python3 scripts/engineering/secret_scan.py --json`。

## Task Dispatch Matrix

| Task | Lane | Model | Reasoning | Session | Plan | Workspace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 Baseline + contract characterization | Lane 2 | Sol | 高 | 新会话 | Plan-then-execute | 从最新 `develop` 新 task worktree | focused checks |
| 2 Caution + Python/Web parity hardening | Lane 2（语义漂移即停止升级） | Sol | 高 | 继续同一稳定化会话 | Plan-then-execute | 同 task worktree | Python/Web exact parity |
| 3 Web same-pane interaction acceptance | Lane 2 | Terra | 中 | 继续同一任务或独立 Web 子会话 | Plan-then-execute | 同 task worktree | Playwright + build |
| 4 Repository-native full verification | Lane 2 | Sol | 高 | 继续同一任务 | Direct verification | 同 task worktree | all required commands green |
| 5 Canonical closeout + independent review | Lane 2 review | Sol | 高 | 新独立 Review 会话 | Review-only | task/develop read-only diff | Critical=0 / Important=0 |

Worktree lifecycle:

```text
latest develop (must contain ee35631a...)
→ fix/main-force-mirror-v0-stabilization task branch/worktree
→ Tasks 1–4
→ independent Task 5 review
→ integrate task branch → develop only after all gates pass
→ read back develop ancestry
→ remove merged task worktree/branch
```

No step may touch `main`, a release worktree, an exact-tag Runtime worktree or production service state.

---

## File Structure

### Existing production files under verification

- `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py` — Python business-authoritative designed-v0 computation.
- `packages/quant-core/guiyi_quant/indicators/registry.py` — observation-only registry capability.
- `packages/quant-core/guiyi_quant/indicators/policy.py` — `main_force_mirror_observation_v0` consumer boundary.
- `apps/quant-web/src/utils/mainForceMirror.ts` — Web observation mirror only.
- `apps/quant-web/src/components/kline/KlineChart.vue` — MACD/主力照妖镜 same-pane Tab and rendering.

### Existing tests under verification/hardening

- `services/quant-api/tests/test_main_force_mirror.py`
- `services/quant-api/tests/test_indicator_registry_v1.py`
- `apps/quant-web/tests/mainForceMirror.test.ts`
- `apps/quant-web/e2e/main-force-mirror.spec.mjs`
- `apps/quant-web/e2e/market-runtime.spec.mjs`
- `apps/quant-web/tests/indicators.test.ts`
- `apps/quant-web/tests/kline-view-model.test.ts`

### Canonical/status files

- `docs/INDICATOR_KERNEL.md` — frozen V0 formula/business boundary; only change if tests prove documentation is inconsistent with the already-approved contract, never to invent new formula semantics.
- `TESTING.md` — add a focused Main Force Mirror verification section only if the stabilized command set is not already discoverable from existing sections.
- `STATUS.md` — final closeout only after every verification/review gate passes.

No new runtime module, API module, DB migration, data file or production config is expected.

---

### Task 1: Freeze the Merged Baseline and Characterize Existing Contract

**Files:**
- Read: `STATUS.md`
- Read: `AGENTS.md`
- Read: `docs/DEVELOPMENT.md`
- Read: `PROJECT_SOURCE.md`
- Read: `DECISIONS.md`
- Read: `docs/INDICATOR_KERNEL.md`
- Read: PR #171 / merge commit `ee35631a0ac750dbff43295be0fc130d78a042a1`
- Test: `services/quant-api/tests/test_main_force_mirror.py`
- Test: `apps/quant-web/tests/mainForceMirror.test.ts`

**Interfaces:**
- Consumes: merged `main_force_mirror_v0` and existing golden values.
- Produces: an explicit baseline decision: `BASELINE_READY` or `BASELINE_DRIFT_BLOCKED`.

- [ ] **Step 1: Create isolated task workspace from latest develop**

```bash
git fetch origin develop
git worktree add ../guiyi-main-force-mirror-v0-stabilization -b fix/main-force-mirror-v0-stabilization origin/develop
cd ../guiyi-main-force-mirror-v0-stabilization
```

- [ ] **Step 2: Verify ancestry and clean identity**

```bash
git status --short
git merge-base --is-ancestor ee35631a0ac750dbff43295be0fc130d78a042a1 HEAD
git log -5 --oneline --decorate
```

Expected:

```text
status is clean
merge-base command exits 0
HEAD is latest origin/develop or a direct task branch created from it
```

If ancestry fails, output `BASELINE_DRIFT_BLOCKED` and stop.

- [ ] **Step 3: Read the exact frozen contract before touching tests**

Confirm these exact facts from `docs/INDICATOR_KERNEL.md`:

```text
indicator_code = main_force_mirror_v0
indicator_version = designed-v0
status = observation_only
future_looking = false
“小心” = rising_edge(BARSLAST(HIGH = HHV(HIGH, 5)) < 10)
caution_level = 50
six-state values = entry/wash/pull_up/distribute/exit/lure
no outflow_ratio
```

If current source disagrees with this canonical, do not edit yet. Record the mismatch and continue only far enough to create a failing regression test in Task 2.

- [ ] **Step 4: Run existing focused baseline tests without modification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test -- mainForceMirror.test.ts
```

If the repository Node test runner does not accept a filename after `--`, use the canonical whole-unit command instead:

```bash
pnpm --dir apps/quant-web test
```

Record exact pass/fail counts. A failure is not permission to change the formula.

- [ ] **Step 5: Commit nothing if baseline characterization is already green**

Task 1 is allowed to produce zero diff. Do not create evidence files or status packets merely to prove the command ran.

---

### Task 2: Harden Exact “小心” Boundaries and Python/Web Parity

**Files:**
- Modify if coverage is missing: `services/quant-api/tests/test_main_force_mirror.py`
- Modify if coverage is missing: `apps/quant-web/tests/mainForceMirror.test.ts`
- Modify only after a RED regression proves an implementation bug: `packages/quant-core/guiyi_quant/indicators/main_force_mirror.py`
- Modify only after a RED regression proves an implementation bug: `apps/quant-web/src/utils/mainForceMirror.ts`

**Interfaces:**
- Consumes: frozen contract from Task 1.
- Produces: explicit edge-case coverage for repeated HHV ties, quiet-window boundary, no duplicate caution, warm-up nullability and identical Python/Web golden outputs.

- [ ] **Step 1: Add characterization for repeated equal 5-bar highs**

Python expected behavior:

```python
def test_caution_does_not_repeat_while_hhv5_event_keeps_state_active() -> None:
    compute, _ = _mirror_api()
    highs = [1, 2, 3, 4, 5, 5, 5, 4, 3, 2, 1, 0]
    result = compute(
        [f"tie-{index}" for index in range(len(highs))],
        [value - 1.0 for value in highs],
        highs,
        [value - 2.0 for value in highs],
        [value - 0.5 for value in highs],
        [1_000] * len(highs),
    )
    assert [index for index, flag in enumerate(result.caution) if bool(flag)] == [4]
```

Add the equivalent TypeScript assertion using `calculateMainForceMirror()`.

This is characterization of an already-required behavior. It may PASS immediately; if so, do not modify production code.

- [ ] **Step 2: Add explicit quiet-window boundary characterization**

Use a sequence where the last HHV5 event is at index 4, `BARSLAST == 9` still keeps the state active at index 13, `BARSLAST == 10` makes it inactive at index 14, and a new HHV5 event at index 15 creates the next rising edge.

Exact expected caution indexes:

```text
[4, 15]
```

The existing test may already cover this implicitly. If so, strengthen test names/comments rather than duplicate the same input.

- [ ] **Step 3: Preserve warm-up unavailability**

Confirm before 20-bar six-state readiness:

```text
score/value = unavailable (NaN/null)
state = None/null
ready = false
```

Do not replace missing output with zero.

- [ ] **Step 4: Verify shared deterministic golden values in both runtimes**

The current frozen last eight ready tuples must remain:

```text
20  -0.654814  distribute
21   0.697117  exit
22   1.896099  exit
23  -2.603149  lure
24  -0.181907  lure
25  -2.923248  pull_up
26  -0.584624  lure
27  -2.445683  lure
```

And the deterministic caution indexes remain:

```text
[4]
```

If Python and Web disagree, determine which implementation disagrees with `docs/INDICATOR_KERNEL.md`. A pure implementation drift may be fixed after a failing regression test. If choosing the correct value requires changing the designed-v0 contract, stop with `FORMULA_DRIFT_REQUIRES_NEW_TASK`.

- [ ] **Step 5: RED before any production fix**

For any implementation mismatch, first run the new regression and capture the expected failure:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py

pnpm --dir apps/quant-web test
```

Expected for a real bug: at least one new regression fails for the exact mismatched behavior.

- [ ] **Step 6: Apply the smallest contract-preserving fix only if RED exists**

Allowed examples:

```text
off-by-one BARSLAST window
Python/Web rounding mismatch
Web mirror uses wrong sign for an already-frozen state
caution marker duplicates despite frozen rising-edge rule
```

Forbidden in this task:

```text
change HHV5 to another period
change quiet window from 10
add volume/flow threshold to caution
change six-state thresholds because the picture looks better
change CLV/relative-volume formula
promote the indicator to alert/backtest/live
```

- [ ] **Step 7: GREEN parity verification**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test
```

- [ ] **Step 8: Commit only if Task 2 changed tracked files**

```bash
git add \
  services/quant-api/tests/test_main_force_mirror.py \
  apps/quant-web/tests/mainForceMirror.test.ts \
  packages/quant-core/guiyi_quant/indicators/main_force_mirror.py \
  apps/quant-web/src/utils/mainForceMirror.ts

git diff --cached --check
git commit -m "test(indicators): harden main-force mirror v0"
```

Stage only files actually changed; omit untouched production files from `git add`.

---

### Task 3: Verify the Web Same-Pane Tab Contract

**Files:**
- Test: `apps/quant-web/e2e/main-force-mirror.spec.mjs`
- Test: `apps/quant-web/e2e/market-runtime.spec.mjs`
- Modify only if a RED browser test proves a defect: `apps/quant-web/src/components/kline/KlineChart.vue`

**Interfaces:**
- Consumes: `calculateMainForceMirror()` output and the existing three-pane chart.
- Produces: browser proof that MACD is default and main-force mirror is an in-place secondary-pane alternative with no data refetch.

- [ ] **Step 1: Run syntax check on the focused E2E**

```bash
node --check apps/quant-web/e2e/main-force-mirror.spec.mjs
```

Expected: exit `0`.

- [ ] **Step 2: Run focused Playwright behavior**

```bash
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs
```

Required assertions:

```text
MACD tab selected by default
主力照妖镜 tab exists
switch to mirror changes only secondary panel state
switch does not add a /bars/page request
switch back restores MACD selection
mirror view exposes non-measured-fund-flow disclaimer
```

- [ ] **Step 3: Run adjacent Market chart regression**

```bash
pnpm --dir apps/quant-web exec playwright test \
  e2e/market-runtime.spec.mjs
```

This protects pagination, Live seam, series switching and period switching from KlineChart regressions.

- [ ] **Step 4: Validate pane-header attachment after resize**

The implementation must continue deriving Tab top position from actual pane heights rather than hard-coded 6:2:2 percentages. If the existing E2E can observe the header position reliably, add one stable assertion that the header remains within the third pane after viewport resize. Do not add pixel-perfect screenshot assertions or browser-dependent exact coordinates.

- [ ] **Step 5: RED before any Vue fix**

If the browser test fails because of KlineChart behavior, preserve the failing Playwright assertion first. Then make the smallest fix in `KlineChart.vue`; do not refactor unrelated chart code.

- [ ] **Step 6: Build after any Web change**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

- [ ] **Step 7: Commit only if Task 3 changed tracked files**

```bash
git add apps/quant-web/e2e/main-force-mirror.spec.mjs apps/quant-web/src/components/kline/KlineChart.vue
git diff --cached --check
git commit -m "fix(web): stabilize main-force mirror pane switch"
```

Omit `KlineChart.vue` if it was not changed.

---

### Task 4: Run Repository-Native Full Verification

**Files:**
- No expected source changes.
- Read: `TESTING.md`

**Interfaces:**
- Consumes: stabilized task branch.
- Produces: exact verification record in the execution summary, not a new evidence artifact in the repository.

- [ ] **Step 1: Ensure dependencies are already synchronized or synchronize once**

Only if this checkout has not installed the lockfile-defined dependencies:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

Dependency installation is not permission for any Runtime or provider operation.

- [ ] **Step 2: Run focused Indicator Kernel suite**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_htdy_strict_kernel.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_main_force_mirror.py
```

- [ ] **Step 3: Run complete backend baseline**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests
```

If isolated PostgreSQL-only tests require `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`, use only a database whose name contains `test` or `isolated` and whose OID differs from Runtime. Never point the suite at production.

- [ ] **Step 4: Run Python static checks**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data services/quant-api/app/guiyi_cli services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py services/quant-api/app/api/execution_review.py
```

- [ ] **Step 5: Run Web unit, focused E2E and production build**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/market-runtime.spec.mjs \
  e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build
```

- [ ] **Step 6: Run repository hygiene**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

Expected secret scan: zero findings. Expected diff check: exit `0`. `git status --short` may contain only this task's intentional changes.

- [ ] **Step 7: Fail closed on any required failure**

Do not write `STATUS.md` and do not claim completion while any required command is red. Fix only defects inside the current frozen contract; formula choices trigger `FORMULA_DRIFT_REQUIRES_NEW_TASK`.

---

### Task 5: Canonical Closeout and Independent Review

**Files:**
- Modify after all verification passes: `STATUS.md`
- Modify only if command discoverability is missing: `TESTING.md`
- Review: all task diff against latest `develop`

**Interfaces:**
- Consumes: all green Task 4 evidence and final branch diff.
- Produces: accurate develop-only status and review result `Critical=0 / Important=0`.

- [ ] **Step 1: Add a bounded STATUS record only after all gates are green**

Add a concise current-state statement with these exact semantics:

```text
- develop 已包含并完成仓库原生验证的 `main_force_mirror_v0`（主力照妖镜 observation V0）：
  Python Indicator Kernel 为唯一口径，Web 在现有最底部副图通过 `MACD / 主力照妖镜` Tab 二选一，
  默认 MACD；“小心”保持 `rising_edge(BARSLAST(HIGH=HHV(HIGH,5))<10)`。
  六色柱仅为 OHLCV 设计代理，不是实测资金流；该指标仍为 observation_only，未进入 Alert、
  backtest、live、notification 或 Runtime。本条只记录 develop 实现与验证，不表示 release 或 Runtime promotion。
```

Do not include invented test counts; copy exact counts from the actual Task 4 output if counts are recorded.

- [ ] **Step 2: Add TESTING focused section only if needed**

If `TESTING.md` lacks an obvious exact entry for Main Force Mirror, add:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test e2e/main-force-mirror.spec.mjs
pnpm --dir apps/quant-web build
```

Do not duplicate the full repository baseline commands already present.

- [ ] **Step 3: Commit closeout docs**

```bash
git add STATUS.md TESTING.md
git diff --cached --check
git commit -m "docs(status): record main-force mirror v0 stabilization"
```

Stage `TESTING.md` only if it was actually modified.

- [ ] **Step 4: Open fresh independent Review**

Reviewer context must include only:

```text
Base: latest develop at task creation
Head: fix/main-force-mirror-v0-stabilization
Canonical: docs/INDICATOR_KERNEL.md
Issue: #172
Plan: docs/superpowers/plans/2026-08-19-main-force-mirror-v0-stabilization.md
```

Review focus:

```text
1. No formula drift from designed-v0.
2. Exact HHV5/BARSLAST10 rising-edge semantics.
3. Python/Web golden parity.
4. MACD remains default and same-pane switching has no bar refetch.
5. Registry/Policy remain observation-only and fail closed for formal consumers.
6. No Alert/DB/Canonical/Runtime/notification/order scope expansion.
7. STATUS wording does not claim release or Runtime promotion.
```

- [ ] **Step 5: Resolve all Critical/Important findings**

Any fix follows the same TDD rule and reruns affected plus full required checks. Minor findings may be accepted only if they do not change correctness, semantics, safety or maintainability of this bounded feature.

- [ ] **Step 6: Re-run final completion checks**

```bash
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

- [ ] **Step 7: Integrate to develop only**

After all required verification and Review are green:

```text
fix/main-force-mirror-v0-stabilization
→ develop
```

Read back that the integration commit contains task HEAD ancestry before removing the task worktree/branch. Do not touch `main`, tag or Runtime.

---

## Acceptance Criteria

All of the following must be true:

1. Execution baseline ancestry contains merge commit `ee35631a0ac750dbff43295be0fc130d78a042a1`.
2. Python and Web preserve the exact same frozen deterministic golden score/state outputs.
3. “小心” fires only on the rising edge of `BARSLAST(HIGH = HHV(HIGH, 5)) < 10`; repeated equal HHV5 events do not repeatedly fire while state remains active.
4. `BARSLAST == 9` remains active and `BARSLAST == 10` is inactive, allowing the next HHV5 event to create a fresh caution signal.
5. Warm-up state does not fabricate zero score/state.
6. `main_force_mirror_v0` remains `observation_only`, causal, Web-capable only; backtest/live/alert/notification stay blocked.
7. No `outflow_ratio` or claim of measured 70% main-force outflow exists in runtime data models, metadata, API, Web or docs.
8. Web defaults to MACD; switching to/from 主力照妖镜 reuses the same secondary pane and does not refetch bars.
9. Existing market pagination/Live seam/overlay/EMA/HTDY behavior remains green under adjacent regression tests.
10. Focused Indicator Kernel tests, complete backend tests, Ruff, Mypy, Web unit, focused Playwright, Web production build, secret scan and diff check all pass in the repository-native environment.
11. Independent Review closes with `Critical=0 / Important=0`.
12. `STATUS.md` records develop-only validation without claiming release, Runtime promotion, Alert activation, strategy validity or profitability.
13. No DB/Canonical/Redis/provider/Runtime/Scope/notification/order mutation occurs.

## Stop Conditions

Immediately stop and report the exact code when any condition holds:

```text
BASELINE_DRIFT_BLOCKED
FORMULA_DRIFT_REQUIRES_NEW_TASK
PRODUCTION_IDENTITY_MISMATCH
TEST_DATABASE_NOT_ISOLATED
REQUIRED_VERIFICATION_FAILED
REVIEW_CRITICAL_OR_IMPORTANT_OPEN
```

Do not convert any stop condition into a workaround by weakening a test, changing canonical language or widening scope.

## Self-Review

- Spec coverage: every Main Force Mirror V0 requirement in `docs/INDICATOR_KERNEL.md` maps to Tasks 1–5 and Acceptance Criteria 2–8.
- Scope coverage: no task introduces API/DB/Runtime/Alert/notification/order work.
- Formula protection: all new edge coverage is characterization; any semantic choice is explicitly fail-closed to a new task.
- Type/interface consistency: Python `compute_main_force_mirror` and Web `calculateMainForceMirror` remain the only computation entry points named in this Plan.
- Placeholder scan: no `TBD`, `TODO`, deferred implementation or unspecified “appropriate tests” remain.
- Completion discipline: STATUS closeout is sequenced after, not before, full native verification and independent review.

## Execution Handoff

This Plan is implemented by the executable contract:

`docs/tasks/TASK-MAIN-FORCE-MIRROR-V0-STABILIZATION-20260819.md`

Recommended execution mode: `superpowers:subagent-driven-development`, using one bounded task worktree and fresh reviewer context at Task 5.
