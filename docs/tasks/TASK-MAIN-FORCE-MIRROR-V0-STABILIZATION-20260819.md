# TASK-MAIN-FORCE-MIRROR-V0-STABILIZATION-20260819

> 单次执行合同：用于对已合入 `develop` 的 `main_force_mirror_v0` 做稳定化、仓库原生验证、必要的 contract-preserving 修复与 develop-only 收口。本文不恢复历史 TASK 模板、dispatcher、自动发布或旧 AI 工作流。

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | `TASK-MAIN-FORCE-MIRROR-V0-STABILIZATION-20260819` |
| GitHub Issue | `#172` |
| Superpowers Plan | `docs/superpowers/plans/2026-08-19-main-force-mirror-v0-stabilization.md` |
| Formula Canonical | `docs/INDICATOR_KERNEL.md` → `主力照妖镜 observation V0` |
| Required Baseline Ancestor | `ee35631a0ac750dbff43295be0fc130d78a042a1` (PR #171 merge) |
| Suggested Branch | `fix/main-force-mirror-v0-stabilization` |
| Base | execution-time latest `origin/develop` containing the required ancestor |
| Status | `REQUIREMENT_READY` |
| Work Level | `L2` |
| Risk | ordinary repository engineering; formula drift is explicitly out of scope and fail-closed |
| External Side Effects | none |

## 1. 当前事实

PR #171 已经合入 `develop`。当前 V0 已存在以下 active implementation：

```text
Python authority:
packages/quant-core/guiyi_quant/indicators/main_force_mirror.py

Registry / policy:
packages/quant-core/guiyi_quant/indicators/registry.py
packages/quant-core/guiyi_quant/indicators/policy.py

Web observation mirror:
apps/quant-web/src/utils/mainForceMirror.ts

Web rendering:
apps/quant-web/src/components/kline/KlineChart.vue

Tests:
services/quant-api/tests/test_main_force_mirror.py
apps/quant-web/tests/mainForceMirror.test.ts
apps/quant-web/e2e/main-force-mirror.spec.mjs
```

本任务不是重新开发主力照妖镜。它解决的是：PR #171 合并前由于执行环境限制，尚未在完整仓库依赖环境中完成全量 pytest、Ruff/Mypy、Web unit、Playwright 实跑与 production build 的事实缺口。

## 2. 目标

1. 从执行时最新 `develop` 建立干净 task worktree，并证明其 ancestry 包含 PR #171 merge commit。
2. 按 `docs/INDICATOR_KERNEL.md` 冻结 designed-v0 数学口径，禁止稳定化任务调整公式参数或语义。
3. 明确验证“小心”的 `HHV5 + BARSLAST<10 + rising edge` 边界，包括重复等高和第 9/10 根边界。
4. 验证 Python Kernel 与 Web mirror deterministic golden 输出完全一致。
5. 实跑 Web same-pane Tab：默认 MACD、可切主力照妖镜、切换不 refetch bars、切回 MACD 正常。
6. 执行 `TESTING.md` 规定的仓库原生测试、静态检查、Playwright、Web build、secret scan 和 diff check。
7. 只有全部通过后，才允许在 `STATUS.md` 记录 develop-only 的稳定化事实。
8. 完成一次独立 Review；Critical/Important 必须为 0 后才能进入 `develop`。

## 3. 不做事项

严格禁止：

- 不重新定义六色柱算法；
- 不调整 `volume_window=20`、`flow_ema_period=5`、`range_window=20`、现有分类阈值、符号和状态映射；
- 不把“小心”改成资金流、70%、超买、MACD、六色柱或未来峰值条件；
- 不生成 `outflow_ratio` 或声称实测主力资金流出比例；
- 不新增 Alert Rule、Scope、notification、Runtime consumer、Signal 或 Strategy；
- 不新增 API、数据库、migration、Catalog、Canonical、Redis、worker、queue；
- 不恢复 backtest 子系统；
- 不修改 `.env` 或读取/输出凭据；
- 不执行 RQData、正式 Canonical/DB 写入；
- 不执行真实微信通知；
- 不执行开发态或 production Runtime reload/switch；
- 不修改 `main`、release、tag 或 Runtime worktree；
- 不创建订单，`auto_order=false` 不变。

如果任何失败的修复需要新的公式选择，输出：

```text
FORMULA_DRIFT_REQUIRES_NEW_TASK
```

然后停止。不得用“看起来更像网站”作为稳定化修复理由。

## 4. 冻结口径

### 4.1 六色柱 designed-v0

以 `docs/INDICATOR_KERNEL.md` 为唯一依据：

```text
CLV = (2 * close - high - low) / (high - low)
relative_volume = volume / SMA(volume, 20), clipped to [0, 3]
raw_flow = CLV * relative_volume
flow = EMA(raw_flow, 5)
range_position = (close - LLV(low, 20)) / (HHV(high, 20) - LLV(low, 20))
```

输出状态精确为：

```text
entry / wash / pull_up / distribute / exit / lure
进场  / 洗盘 / 拉高    / 出货       / 退场 / 诱多
```

这些是观察标签，不是账户级资金事实。

### 4.2 “小心” exact contract

原始公式：

```text
VAR38 := BARSLAST(HIGH = HHV(HIGH, 5)) < 10;
VAR58 := IF(VAR38=1,2,0);
顶 := IF(VAR58=2,2,0);
顶A := IF(顶>REF(顶,1),50,0);
DRAWTEXT(顶A=50,45,'小 心');
```

冻结等价表达：

```text
short_high_event = HIGH == HHV(HIGH, 5)
recent_short_high = BARSLAST(short_high_event) < 10
caution = rising_edge(recent_short_high)
caution_level = 50
```

必须满足：

- 第一次有效 5-bar HHV 事件可触发 rising edge；
- 状态持续期间即使重复等高或继续新高，也不重复触发；
- 距最后一次事件 9 根仍 active；
- 距最后一次事件 10 根时 inactive；
- inactive 后下一次 HHV5 事件产生新的 `小心`；
- 不使用未来 Bar。

## 5. Codex 调度建议

- 任务车道：Lane 2
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开会话
- Plan：Plan-then-execute
- 工作区：新 task worktree
- 人工 Gate：独立 Review

Worktree 规则：

- 从执行时最新 `origin/develop` 创建 `fix/main-force-mirror-v0-stabilization`；
- 创建后必须证明 `ee35631a0ac750dbff43295be0fc130d78a042a1` 是 HEAD ancestor；
- 完成后只集成到 `develop`；
- 本任务允许在全部验证、独立 Review、scope 检查均通过后 task → `develop`；
- 推荐 PR，但仓库 `AGENTS.md` 不要求 PR 作为普通开发授权条件；
- 确认提交进入 `develop` 并读回 ancestry 后，清理本 task worktree 和已合并 branch；
- 不得触及 `main`、tag、release worktree 或 Runtime worktree。

## 6. 必读顺序

执行前按顺序阅读：

1. `STATUS.md`
2. `AGENTS.md`
3. `docs/DEVELOPMENT.md`
4. `PROJECT_SOURCE.md`
5. `DECISIONS.md`
6. `docs/INDICATOR_KERNEL.md`
7. `TESTING.md`
8. `docs/superpowers/plans/2026-08-19-main-force-mirror-v0-stabilization.md`
9. Issue #172
10. PR #171 diff/review（只用于理解 merged implementation；公式事实仍以 `docs/INDICATOR_KERNEL.md` 为准）

若 active canonical 与本 TASK 冲突，以 active canonical 为准并 fail-closed，不自行调和。

## 7. 允许修改

仅在对应测试/验证需要时：

```text
services/quant-api/tests/test_main_force_mirror.py
apps/quant-web/tests/mainForceMirror.test.ts
apps/quant-web/e2e/main-force-mirror.spec.mjs
packages/quant-core/guiyi_quant/indicators/main_force_mirror.py
apps/quant-web/src/utils/mainForceMirror.ts
apps/quant-web/src/components/kline/KlineChart.vue
packages/quant-core/guiyi_quant/indicators/registry.py
packages/quant-core/guiyi_quant/indicators/policy.py
TESTING.md
STATUS.md
```

约束：

- 生产实现文件只有在先出现与 frozen canonical 不一致的 RED regression 时才能改；
- `registry.py` / `policy.py` 只能修 observation-only capability 漂移，不得扩权；
- `TESTING.md` 只补 focused verification command 的可发现性，不复制整个测试手册；
- `STATUS.md` 只能在最终 Gate 全绿后修改。

## 8. 禁止修改路径

```text
main/release/tag refs
.env*
data/** Canonical / research result / universe facts
migrations/**
services/quant-api/app/alerts/**
services/quant-api/app/execution_review/**
services/quant-api/app/api/** (本任务不需要 API)
deploy/**
scripts/ops/**
Runtime worktree
OpenClaw / openclaw-weixin external installation/config
```

如果实际修复需要越出允许范围，停止并报告 `SCOPE_EXPANSION_REQUIRES_NEW_TASK`。

## 9. 执行步骤

严格逐 Task 执行 Superpowers Plan，不跳步：

```text
Task 1  baseline + characterization
Task 2  caution boundary + Python/Web parity
Task 3  Web same-pane interaction
Task 4  repository-native full verification
Task 5  STATUS closeout + independent review + develop integration
```

### 9.1 Preflight

```bash
git fetch origin develop
git worktree add ../guiyi-main-force-mirror-v0-stabilization \
  -b fix/main-force-mirror-v0-stabilization origin/develop
cd ../guiyi-main-force-mirror-v0-stabilization

git status --short
git merge-base --is-ancestor ee35631a0ac750dbff43295be0fc130d78a042a1 HEAD
git log -5 --oneline --decorate
```

成功结果：

```text
BASELINE_READY
```

失败：

```text
BASELINE_DRIFT_BLOCKED
```

### 9.2 Focused Indicator verification

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_main_force_mirror.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test
```

补足 Plan 规定的等高 HHV5、BARSLAST 9/10 边界时，属于 characterization；如果现有代码已经满足，测试直接通过是允许的，不得为了制造 RED 修改生产代码。

### 9.3 Web E2E

```bash
node --check apps/quant-web/e2e/main-force-mirror.spec.mjs
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/market-runtime.spec.mjs
```

必要行为：

```text
MACD default
MACD / 主力照妖镜 tabs visible
switch to mirror without /bars/page refetch
switch back to MACD
non-measured-fund-flow disclaimer visible
pane header remains attached after resize without pixel-perfect assumptions
```

### 9.4 Full native verification

按 `TESTING.md` 执行：

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
uv run --offline --project services/quant-api pytest -q services/quant-api/tests

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

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web exec playwright test \
  e2e/main-force-mirror.spec.mjs \
  e2e/market-runtime.spec.mjs \
  e2e/market-research.spec.mjs
pnpm --dir apps/quant-web build

python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
```

任何要求 isolated PostgreSQL 的测试只允许 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL` 指向测试/隔离库，且其物理 identity 必须不同于 Runtime DB。缺少安全隔离时跳过不得伪装为通过，应报告：

```text
TEST_DATABASE_NOT_ISOLATED
```

## 10. TDD 修复规则

如果发现实现 defect：

1. 先写能稳定复现 defect 的 regression test；
2. 运行并确认该 test 因 defect 失败；
3. 做最小 production fix；
4. 运行 affected focused tests；
5. 再运行本 TASK 全部 required verification；
6. 不修改 test expectation 去迎合现有错误实现。

允许修复：

```text
off-by-one BARSLAST
Python/Web rounding parity
已经冻结的 score/state sign 实现不一致
same-pane switch stale series
pane header resize attachment bug
registry/policy capability 实现漂移
```

不允许修复：

```text
重新选参数
调整阈值以拟合截图
把 70% 变为计算字段
把 caution 接 Alert
新增持仓量/OI/资金流公式
```

## 11. Review Gate

实现与验证后必须新开独立 Review 会话，模型 `Sol / 高推理`。

Reviewer 只读取：

```text
latest develop baseline
current task head
docs/INDICATOR_KERNEL.md
本 TASK
本 Plan
Issue #172
```

重点：

1. designed-v0 无数学漂移；
2. caution 精确符合 HHV5/BARSLAST10 rising edge；
3. Python/Web golden 一致；
4. MACD default 和 same-pane/no-refetch 保持；
5. observation-only capability 未扩张；
6. 无 Alert/DB/Canonical/Runtime/notification/order 扩张；
7. STATUS 只写 develop verified，不写 release/Runtime。

通过条件：

```text
Critical = 0
Important = 0
```

否则：

```text
REVIEW_CRITICAL_OR_IMPORTANT_OPEN
```

## 12. STATUS 收口合同

仅在全部 tests/build/review 通过后允许修改 `STATUS.md`，语义必须等价于：

```text
- develop 已包含并完成仓库原生验证的 `main_force_mirror_v0`（主力照妖镜 observation V0）：
  Python Indicator Kernel 为唯一口径，Web 在现有最底部副图通过 `MACD / 主力照妖镜` Tab 二选一，
  默认 MACD；“小心”保持 `rising_edge(BARSLAST(HIGH=HHV(HIGH,5))<10)`。
  六色柱仅为 OHLCV 设计代理，不是实测资金流；该指标仍为 observation_only，未进入 Alert、
  backtest、live、notification 或 Runtime。本条只记录 develop 实现与验证，不表示 release 或 Runtime promotion。
```

可以附实际测试数量，但只能从本次真实命令输出复制。

## 13. 验收标准

- [ ] baseline ancestry 包含 `ee35631a...`；
- [ ] focused Python mirror tests PASS；
- [ ] Indicator Registry/Policy tests PASS；
- [ ] Web mirror unit tests PASS；
- [ ] repeated equal HHV5 不重复 `小心`；
- [ ] BARSLAST 9/10 边界精确；
- [ ] Python/Web frozen golden 一致；
- [ ] warm-up 不补零；
- [ ] focused Playwright 实跑 PASS；
- [ ] market-runtime adjacent E2E PASS；
- [ ] complete backend pytest PASS，或仅因明确安全 guard 缺 isolated DB 而准确阻塞，不能伪装 PASS；
- [ ] Ruff PASS；
- [ ] Mypy PASS；
- [ ] Web unit PASS；
- [ ] Web build PASS；
- [ ] secret scan 0 findings；
- [ ] `git diff --check` PASS；
- [ ] independent Review `Critical=0 / Important=0`；
- [ ] no formula drift；
- [ ] no `outflow_ratio`；
- [ ] no Alert/DB/Canonical/Runtime/notification/order changes；
- [ ] STATUS 如有更新，仅声明 develop-only verified state；
- [ ] task branch 集入 develop 后读回 ancestry；
- [ ] task worktree/branch 在确认已合并后安全清理。

## 14. 终止码

```text
BASELINE_DRIFT_BLOCKED
FORMULA_DRIFT_REQUIRES_NEW_TASK
SCOPE_EXPANSION_REQUIRES_NEW_TASK
TEST_DATABASE_NOT_ISOLATED
REQUIRED_VERIFICATION_FAILED
REVIEW_CRITICAL_OR_IMPORTANT_OPEN
```

任一终止码出现时不得集成 `develop`。

## 15. 完成输出格式

Codex 完成后必须输出：

```text
Task ID:
Baseline commit:
Final task head:
Changed files:
Formula changed: yes/no
Caution contract changed: yes/no
Focused Python tests:
Full backend tests:
Ruff:
Mypy:
Web unit:
Playwright:
Web build:
Secret scan:
Diff check:
Independent Review: Critical=N / Important=N / Minor=N
STATUS updated: yes/no
Integration result:
Develop readback:
Worktree/branch cleanup:
External side effects performed: none
Stop code: none | <exact code>
Residual risks:
```

不得用“应该通过”“看起来正常”替代命令结果。

## 16. 可直接复制的 Codex Prompt

```text
请先阅读：

1. STATUS.md
2. AGENTS.md
3. docs/DEVELOPMENT.md
4. PROJECT_SOURCE.md
5. DECISIONS.md
6. docs/INDICATOR_KERNEL.md
7. TESTING.md
8. docs/superpowers/plans/2026-08-19-main-force-mirror-v0-stabilization.md
9. docs/tasks/TASK-MAIN-FORCE-MIRROR-V0-STABILIZATION-20260819.md
10. GitHub Issue #172 与已合并 PR #171

本任务为 Lane 2，Codex App，Sol，高推理，新会话，Plan-then-execute。

目标：
对 PR #171 已合入 develop 的 `main_force_mirror_v0` 做 post-merge stabilization 与仓库原生验收。
这不是重新设计指标。严格冻结 `docs/INDICATOR_KERNEL.md` 的 designed-v0 数学口径和“小心”公式。

工作区：
从执行时最新 `origin/develop` 创建独立 `fix/main-force-mirror-v0-stabilization` task branch/worktree。
必须先证明 merge commit `ee35631a0ac750dbff43295be0fc130d78a042a1` 是 task HEAD ancestor。
不得修改 main/runtime worktree。

核心合同：
- Python Indicator Kernel 是唯一公式权威；Web 只是 observation mirror。
- `小心 = rising_edge(BARSLAST(HIGH = HHV(HIGH, 5)) < 10)`，level=50。
- 六色柱是 OHLCV designed proxy，不是实测资金流；不得产生 `outflow_ratio` 或“70%已流出”的事实字段。
- `main_force_mirror_v0` 保持 observation_only；不得进入 backtest/live/alert/notification。
- MACD 仍是最底部副图默认 Tab；主力照妖镜与 MACD 复用同一 pane；切换不得 refetch bars。

执行：
严格按 Superpowers Plan Task 1→5 执行。
先 characterization/测试，再处理任何 production fix。
如果现有行为已符合合同，characterization test 可以直接 PASS，不得为了制造 RED 修改代码。
如果发现实现 bug，必须先新增失败 regression test，再最小修复并全量复验。
如果修复需要调整 designed-v0 参数、阈值、算法、状态语义或 caution 规则，立即停止并输出 `FORMULA_DRIFT_REQUIRES_NEW_TASK`。
如果需要越出 TASK 允许路径，输出 `SCOPE_EXPANSION_REQUIRES_NEW_TASK`。

重点验证：
1. repeated equal HHV5 不重复触发 caution；
2. BARSLAST=9 active、BARSLAST=10 inactive，下一 HHV5 可产生新 rising edge；
3. Python/Web deterministic golden 完全一致；
4. warm-up 不补零；
5. MACD default / tab switch / no bar refetch / switch-back；
6. full pytest、Ruff、Mypy、Web unit、Playwright、Web build、secret scan、diff check。

数据库测试只允许显式 isolated/test DB；绝不使用 production Runtime DB。
不得运行 RQData、Canonical/DB mutation、Runtime reload/switch、Scope mutation、真实微信、release/tag 或订单操作。

所有 required verification 通过后才允许更新 STATUS.md，且只能记录 develop 已验证实现，不得声明 release 或 Runtime promotion。
随后新开独立 Sol/high Review；只有 Critical=0、Important=0 才允许 task → develop。
确认 task head 已进入 develop 并读回 ancestry 后清理临时 worktree/branch。

完成后按 TASK 第15节精确格式输出结果。
```
