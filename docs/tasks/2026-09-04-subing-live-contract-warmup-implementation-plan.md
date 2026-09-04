# SuBing Live Contract Warm-up Repair Implementation Plan

状态：`IMPLEMENTATION_IN_PROGRESS / TASKS_1_TO_4_COMMITTED / TASK_5_DIRTY / TASKS_6_TO_7_PENDING`

日期：2026-09-04

事实基线：计划编写时为 `develop@d1a8bb8e993896616e47e11e6f7cb02f7dd9e8d7`；截至 2026-09-04，实施 branch 落后当前 `develop`，必须先保留其未提交 Task 5 修改并完成收敛，不能把旧基线当作可直接合入的 RC。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 SuBing 首次/换月评估时“最近完整 Canonical 同物理合约前缀 + 当日 completed Live”的拼接边界，并增加一个受控、可审计的 physical-contract warm-up 入口，以便为 `PF2611` 补齐七周期真实 RQData Canonical 后发布 `v1.9.15`，再做自然开盘验收。

**Architecture:** 保持 `MarketDataService` 严格读取合同不变；只在 `MarketReadService` 将 physical replay 第一页改为 latest-page bootstrap，再按 cutoff 和 cursor 裁剪。历史写路径仍集中在 `HistoricalDataManager`，新增 exact-contract maintenance request/plan/result，并把 contract partition 完整性从“精确等于 rank1 映射日”改为“包含全部 rank1 必需 Bar，且所有持久 Bar 都在合约有效生命周期内”。CLI dry-run 只读生成稳定 plan hash；apply 在 maintenance lock 内重算并校验 hash 后才允许访问 RQData 和写 Canonical。

**Tech Stack:** Python 3.13、FastAPI application services、SQLAlchemy/PostgreSQL Catalog、RQData adapter、Canonical Parquet、Redis Live overlay、pytest、Ruff、Mypy、OpenSpec、Vue 3/TypeScript release checks。

**Spec:** `docs/tasks/2026-09-04-subing-live-contract-warmup-design.md`

## Global Constraints

- 实现开始前重新读取 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`、`TESTING.md`、本 Plan 与批准 Design。
- 从执行时最新且干净的 `origin/develop` 创建独立 `codex/subing-live-contract-warmup` worktree；不得在带有用户修改的主工作区直接实现。当前主工作区的 `.playwright-cli/` 是无关未跟踪目录，不得暂存、删除或清理。
- 当前 production release/runtime 仍是 `v1.9.14@ca15456eaff988db4fe61c37657ca37302a7f977`。代码提交、测试通过或合入 `develop` 都不能表述为已发布或已部署。
- 不修改 `MarketDataService` 的严格 Dataset/partition/coverage/physical-read 校验，不增加 consumer fallback，不让 Runtime 访问 RQData。
- Canonical 仍只有唯一 V2；本任务不增加 Alembic migration，不改变 `subing_ths_alert_15m_v1` Rule identity 或 `subing_ths_15m_v3` formula identity。
- PF warm-up 只接受真实 `PF2611` RQData；禁止 synthetic、continuous、上一主力合约、跨合约或 Live-only seed。
- 实现与普通测试不得连接真实 RQData、production PostgreSQL/Redis、修改 Canonical、发送通知、改变 Scope、切换 Runtime、合入 main、创建 tag 或 GitHub Release。
- 真实 RQData/Canonical apply、release、Runtime promotion 各自是独立的一次性 Gate；失败后的重试仍需新的明确授权。
- 保留 2026-09-03 `LIVE_DOMINANT_MISMATCH` 与已有 Event/Runtime 事实；不得回放、补发、改写或用手工 after-market 运行替代自然验收。
- 每个行为改动使用 RED → GREEN → REFACTOR；每个 Task 只暂存本 Task 文件并单独提交。

---

## Task 0: 建立隔离实现工作区与事实快照

**Files:**

- Read: `STATUS.md`
- Read: `AGENTS.md`
- Read: `docs/DEVELOPMENT.md`
- Read: `PROJECT_SOURCE.md`
- Read: `DECISIONS.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `TESTING.md`
- Read: `docs/tasks/2026-09-04-subing-live-contract-warmup-design.md`
- Read: `docs/tasks/2026-09-04-subing-live-contract-warmup-implementation-plan.md`

- [ ] 在主工作区执行只读检查：

```bash
git status --short --branch
git worktree list --porcelain
git fetch origin develop
git rev-parse origin/develop
git log -5 --oneline --decorate origin/develop
```

预期：只允许已知无关 `.playwright-cli/`；若出现其它 dirty path、现有同名 branch/worktree 或基线变化，先解析所有权与冲突。

- [ ] 从当时的 exact `origin/develop` 创建隔离工作区：

```bash
git worktree add -b codex/subing-live-contract-warmup \
  /private/tmp/guiyi-subing-live-contract-warmup origin/develop
```

- [ ] 在新 worktree 记录基线，不修改文件：

```bash
git status --short --branch
git rev-parse HEAD
git merge-base HEAD origin/develop
```

预期：worktree clean，`HEAD == merge-base == execution-time origin/develop`。

- [ ] 若依赖环境缺失，只运行锁定安装；不得修改 lockfile：

```bash
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

- [ ] 本 Task 不产生 commit。

---

## Task 1: 用 production-shaped RED 固定 Canonical + Live replay 边界

**Files:**

- Modify: `services/quant-api/tests/test_market_read_service.py`
- Modify: `services/quant-api/app/market_data/market_read_service.py`

**Contract:**

```text
first physical page: before=None
next pages: before=previous_page.next_before
accepted canonical/live bars: after < bar_end <= cutoff
missing physical history: MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE
```

- [ ] 在 `test_market_read_service.py` 增加真实 `MarketDataService + MarketCatalog + CanonicalMonthlyStore` fixture，建立：
  - `RB2610 + 15m` Canonical coverage 截止最近完整交易日；
  - decision cutoff 位于下一交易日的 completed Live 15m；
  - Live observation contract 精确为 `RB2610`；
  - 旧 `before=cutoff+1us` 查询必须复现 `DATASET_OR_PARTITION_MISSING`。
- [ ] 写失败测试 `test_current_contract_replay_bootstraps_latest_canonical_before_live_cutoff`：调用公开 `current_contract_replay_window()`，预期返回历史前缀加 Live cutoff，旧实现应红灯。
- [ ] 写失败测试冻结第一页请求与裁剪：
  - 第一页 `before is None`；
  - Canonical 中 `bar_end > cutoff` 的 future tail 不进入 replay；
  - `after` 非空时仅返回严格大于 cursor 的 Bar；
  - 多页时第二页严格使用较小 `next_before`；
  - cursor stalled 仍返回 `MARKET_READ_PAGINATION_STALLED`。
- [ ] 写失败测试冻结错误映射：底层 `MarketDataError("DATASET_OR_PARTITION_MISSING")` 必须变成 `MarketReadWindowError("MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE")`；未知 `RuntimeError` 不得被吞掉。
- [ ] 运行 RED：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py \
  -k 'current_contract_replay'
```

预期：新增 latest bootstrap、future-tail 与稳定错误测试失败；既有同合约、冲突、分页、cursor 测试保持通过。

- [ ] 在 `market_read_service.py` 显式导入 `MarketDataError`，把 `_current_contract_history()` 的初始游标改为：

```python
before: datetime | None = None
```

- [ ] 每页 `history_page()` 仅捕获 `MarketDataError`，转换为：

```python
raise MarketReadWindowError(
    "MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE"
) from exc
```

- [ ] 保持分页 guard 对 `before=None` 安全：第一页拿到 `next_before` 后才比较；后续要求 `next_before < before`。过滤始终执行：

```python
if bar.bar_end > cutoff:
    continue
if after is not None and bar.bar_end <= after:
    continue
```

- [ ] 不改变 Live provenance、重复 timestamp 值一致、conflict、cutoff 必须存在等既有 fail-closed 分支。
- [ ] 运行 GREEN：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_read_service.py
```

预期：全部通过。

- [ ] 静态检查并提交：

```bash
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/market_read_service.py \
  services/quant-api/tests/test_market_read_service.py
git diff --check
git add services/quant-api/app/market_data/market_read_service.py \
  services/quant-api/tests/test_market_read_service.py
git commit -m "fix(market): join canonical prefix with live cutoff"
```

---

## Task 2: 固定 SuBing evaluator 与 per-rule Runtime 失败/恢复语义

**Files:**

- Modify: `services/quant-api/tests/test_alert_evaluator.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify only if RED proves necessary: `services/quant-api/app/alerts/evaluators.py`
- Modify only if RED proves necessary: `services/quant-api/app/alerts/runtime.py`

- [ ] 在 evaluator 测试增加：
  - physical history 缺失稳定映射为 `ALERT_EVALUATION_FAILED`；
  - 修复后的 Canonical + Live replay 能从同一 `RB2610` 前缀推进到 cutoff；
  - 主力从旧合约切到新合约时 cursor 丢弃旧 state，从新 physical contract 前缀重建；
  - `after` cursor、completed-only、prefix invariance 和无 replay/backfill Event 保持成立。
- [ ] 在 Runtime 测试增加序列：
  1. 一个 relevant `15m` SuBing trigger 失败；
  2. 随后到达 unrelated `1m` trigger；
  3. `rule_status.subing_ths_alert_15m_v1.error_type` 与 `last_failure_at` 不得被该 1m trigger 清掉或冒充成功；
  4. 下一次 relevant `15m` 成功后才允许更新 `last_evaluated_bar_at` 并清空该 Rule error。
- [ ] 运行 RED/GREEN：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  -k 'subing or rule_status or current_contract'
```

- [ ] 若现有实现已满足新增 Runtime test，不修改 production Runtime；若红灯，最小修复只能在 `_record_rule_result()` 的 relevant-rule 更新边界内，不增加 HTTP 字段、全局 success 推断或通知行为。
- [ ] 运行完整 SuBing 定向合同：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py
```

预期：全部通过；没有生成真实 Event 或 transport call。

- [ ] 提交：

```bash
git add services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/app/alerts/evaluators.py \
  services/quant-api/app/alerts/runtime.py
git commit -m "test(alert): preserve subing rule evaluation evidence"
```

暂存前先用 `git status --short` 排除未修改的 optional production files；没有变化的文件不得传给 `git add`。

---

## Task 3: 将 physical contract 生命周期设为 Catalog 权威

**Files:**

- Modify: `services/quant-api/app/market_data/catalog.py`
- Modify: `services/quant-api/app/market_data/coverage_source.py`
- Modify: `services/quant-api/app/market_data/historical_data_manager.py`
- Modify: `services/quant-api/tests/data_foundation/test_catalog_and_service.py`
- Modify: `services/quant-api/tests/data_foundation/test_historical_data_manager.py`
- Modify: `services/quant-api/tests/data_foundation/test_infrastructure.py`

**New value object:**

```python
@dataclass(frozen=True, slots=True)
class ContractFact:
    symbol: str
    contract: str
    exchange: str
    provider: str
    listed_date: date
    expired_date: date
```

**New Catalog seam:**

```python
MarketCatalog.contract_fact(symbol: str, contract: str) -> ContractFact
```

错误码固定：

```text
CONTRACT_NOT_FOUND
CONTRACT_SYMBOL_MISMATCH
CONTRACT_PROVIDER_UNSUPPORTED
CONTRACT_METADATA_MISSING
CONTRACT_ACTIVE_WINDOW_MISSING
```

- [ ] 先写 Catalog RED：精确 identity 正常返回；大小写规范化后必须唯一；symbol 不匹配、provider 非 `rqdata`、缺 listed/expired、`listed_date >= expired_date` 分别 fail-closed。
- [ ] 在 `DatabaseCoverageSource` 增加公开只读方法：

```python
def contract_trading_days(
    self,
    fact: ContractFact,
    start: date,
    end: date,
) -> tuple[date, ...]: ...

def contract_expected_bar_ends(
    self,
    key: DatasetKey,
    fact: ContractFact,
    year: int,
    month: int,
    through: date,
) -> tuple[datetime, ...]: ...
```

- [ ] `contract_trading_days()` 取 `TradingCalendar is_trading_day=true` 与 `[listed_date, expired_date)` 的交集，并要求 Calendar/Session 历史事实完整；日内频率另外受 `RQDATA_INTRADAY_HISTORY_START` 限制。不得依据 `MainContractMap` 缩小。
- [ ] 扩展 `valid_boundary()`：continuous 维持当前 session 校验；contract 还必须证明 Dataset contract 与 `ContractFact` identity 一致，`listed_date <= bar.trading_day < expired_date`，并落在该交易日/频率的正式 expected boundary。
- [ ] 在 manager 中增加唯一 helper，对 contract partition 应用：

```text
required_mapped_ends is subset of persisted_ends
persisted_ends is subset of lifecycle_valid_ends
```

- [ ] RED 覆盖普通 update：
  - 合法非 rank1 warm-up Bar 保留；
  - rank1 mapped Bar 缺失仍规划补齐；
  - 非 session、挂牌前、到期日及以后 extra 触发整分区修复；
  - continuous 仍要求 exact equality；
  - fixed-through 仍保留同月中更晚的合法 Bar。
- [ ] RED 覆盖 refresh：contract force refresh 的 target 是 `mapped expected ∪ existing valid warm-up timestamps`，会从 provider 重拉两者，不把 warm-up 静默删除。
- [ ] RED 覆盖 audit：
  - 合法 superset 通过；
  - mapped subset 缺失返回 `EXPECTED_PARTITION_MISSING`；
  - lifecycle/session 非法 extra 返回 `CONTRACT_PARTITION_OUTSIDE_LIFECYCLE`；
  - 不自动改文件或 Catalog。
- [ ] 实现时只重构 `_iter_targets()` 与 `audit()` 共用的 contract partition classification；禁止复制两套合法性判断。
- [ ] 运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
```

预期：全部通过；现有 `test_weekly_owner_refresh_keeps_contract_daily_to_rank1_mapped_days` 需要改名并改断言为“保留合法 warm-up”，不能删除其风险覆盖。

- [ ] Ruff/Mypy 后提交：

```bash
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/market_data/catalog.py \
  services/quant-api/app/market_data/coverage_source.py \
  services/quant-api/app/market_data/historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data
git diff --check
git add services/quant-api/app/market_data/catalog.py \
  services/quant-api/app/market_data/coverage_source.py \
  services/quant-api/app/market_data/historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
git commit -m "fix(data): preserve valid contract warmup history"
```

---

## Task 4: 实现 hash-locked exact contract warm-up 编排

**Files:**

- Modify: `services/quant-api/app/market_data/historical_data_manager.py`
- Modify: `services/quant-api/tests/data_foundation/test_historical_data_manager.py`

**New contracts:**

```python
@dataclass(frozen=True, slots=True)
class ContractWarmupRequest:
    symbol: str
    contract: str
    through: date
    expected_plan_sha256: str | None = None
    apply: bool = False

@dataclass(frozen=True, slots=True)
class ContractWarmupPlan:
    symbol: str
    contract: str
    provider: str
    listed_date: date
    expired_date: date
    through: date
    target_windows: tuple[Mapping[str, object], ...]
    direct_target_count: int
    derived_target_count: int
    expected_bar_count: int
    provider_request_count: int
    plan_sha256: str

@dataclass(frozen=True, slots=True)
class ContractWarmupResult:
    status: str
    readonly: bool
    plan: ContractWarmupPlan
    applied: int
    blocked: int
    failed: int
    provider_requests: int
    failures: tuple[Mapping[str, object], ...] = ()
```

- [ ] 写 plan RED：目标 family 精确为 `(contract, pf, PF2611, frequency)` 七项；每个自然月 target 明确给出 expected/missing 起止、数量；不出现 continuous、其它品种或其它合约。
- [ ] 稳定 hash 使用唯一 canonical JSON：

```python
json.dumps(
    plan_identity,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

`plan_identity` 只含 schema version、command、symbol、contract、provider、listed/expired、requested/effective window 和排序后的 target facts；不得包含绝对路径、当前时间、对象 repr 或秘密。

- [ ] 写 dry-run RED：`apply=False` 时 provider call count、session writes、Catalog writes、Parquet files 均为零；返回 `status=planned`、`readonly=true` 和相同事实下可重复的 SHA-256。
- [ ] 写 apply RED：
  - 缺 `expected_plan_sha256` → `CONTRACT_WARMUP_PLAN_HASH_REQUIRED`；
  - 非 64 位小写 hex → `CONTRACT_WARMUP_PLAN_HASH_INVALID`；
  - maintenance lock unavailable → `status=blocked / maintenance_locked`，零 provider/写入；
  - 取得 lock 后先重算；hash 或 identity/calendar/session/partition 变化 → `CONTRACT_WARMUP_PLAN_CHANGED`，零 provider/写入；
  - `through` 晚于 `latest_complete_day((symbol,))` → `CONTRACT_WARMUP_THROUGH_INCOMPLETE`；
  - effective window 空 → `CONTRACT_ACTIVE_WINDOW_MISSING`。
- [ ] 写数据路径 RED：
  - 基础 provider 只取 `1m/1d`；`1w` 只由完整同源日行情在 adapter 边界聚合；
  - `5m/15m/30m/60m` 只从同 contract、同月、已校验 1m 聚合；
  - D1/W1 不因 rank1 map 缩短；
  - existing valid bars 与 fetched missing 合并后再经 `store.publish()`；
  - strict readback 与 Catalog coverage/row_count 一致；
  - provider quota 结束为 `partial`，不自动重试；
  - 某 family/month 失败记录稳定 reason code，已成功的独立月分区保持可读，下次 dry-run 只规划剩余缺口。
- [ ] 复用 `_Target`、`_execute_apply()`、`_publish_fetched()`、`_publish_derived()`、`_commit_partition()`；为避免 contract W1 走 rank1-only daily companion，给 apply core 增加显式 `weekly_daily_companions: bool`：普通 update/refresh 为 `True`，warm-up 为 `False`，因为 exact lifecycle D1 已作为同一计划中的同源日线 context。
- [ ] `HistoricalDataManager.contract_warmup()` 顺序固定：

```text
validate request and exact ContractFact
→ compute read-only plan
→ if dry-run return
→ validate supplied hash syntax
→ acquire maintenance lease
→ recompute complete plan under lease
→ exact hash compare
→ run before_apply callback
→ fetch/publish direct
→ derive/publish intraday
→ return readback counts
→ release lease
```

`before_apply` 只能用于既有 Market Home projection invalidation；hash compare 通过前不得发生 provider 调用或任何 mutation。若 callback 本身失败，零 provider/Canonical mutation。

- [ ] 运行定向测试：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  -k 'contract_warmup or warmup or contract_partition or refresh'
```

- [ ] 运行完整 Historical manager 测试并提交：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
git diff --check
git add services/quant-api/app/market_data/historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py
git commit -m "feat(data): add hash-locked contract warmup"
```

---

## Task 5: 暴露安全的 `guiyi data contract-warmup` CLI

**Files:**

- Modify: `services/quant-api/app/guiyi_cli/data_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/data_commands.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`
- Modify: `services/quant-api/tests/test_market_home_projection_invalidation.py`

**Command:**

```bash
guiyi data contract-warmup \
  --symbol pf \
  --contract PF2611 \
  --through 2026-09-03 \
  [--expected-plan-sha256 SHA256] \
  [--apply]
```

- [ ] parser RED：注册唯一新 command；`--symbol/--contract/--through` 必填；dry-run 禁止携带 `--expected-plan-sha256`；apply 必须携带 hash；不允许缩写。
- [ ] request RED：symbol 走 active/non-retired authority；contract 仅做 trim/uppercase，最终 identity 由 Catalog 校验；日期使用 `_required_day()`；apply 标志显式进入 request。
- [ ] output RED 固定 schema：

```json
{
  "schema_version": 1,
  "command": "data.contract-warmup",
  "status": "planned",
  "readonly": true,
  "symbol": "pf",
  "contract": "PF2611",
  "provider": "rqdata",
  "listed_date": "2025-11-17",
  "expired_date": "2026-11-13",
  "through": "2026-09-03",
  "direct_target_count": 0,
  "derived_target_count": 0,
  "expected_bar_count": 0,
  "provider_request_count": 0,
  "plan_sha256": "<64 lowercase hex>",
  "applied": 0,
  "blocked": 0,
  "failed": 0,
  "targets": [],
  "failures": []
}
```

测试用数值由 fixture 精确断言，不把示例的零值复制进 production 结果。

- [ ] 证明 dry-run 退出码为 0、stderr 空、`readonly=true`，manager/provider/mutation spy 只观察一次 plan 调用。
- [ ] 证明 apply 进入 `_execution_is_readonly=False`，并像 update/refresh 一样在 manager apply 前失效 Market Home projection；失败时 JSON 只输出公开错误码，不含路径、SQL、stack trace、凭据或 provider 原文。
- [ ] 运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py \
  -k 'contract_warmup or parser_exposes or projection'
```

- [ ] CLI smoke 只能使用测试/fake composition；不得运行真实 `--apply`。可对 temporary SQLite/Canonical 执行 dry-run fixture，但不得 source production env。
- [ ] Ruff/Mypy 后提交：

```bash
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app/guiyi_cli/data_parser.py \
  services/quant-api/app/guiyi_cli/data_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/guiyi_cli services/quant-api/app/market_data
git diff --check
git add services/quant-api/app/guiyi_cli/data_parser.py \
  services/quant-api/app/guiyi_cli/data_commands.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
git commit -m "feat(cli): expose exact contract warmup plan"
```

---

## Task 6: 同步 active canonical、OpenSpec 与运维命令

**Files:**

- Modify: `openspec/specs/subing-ths-alert/spec.md`
- Modify: `openspec/specs/canonical-market-storage/spec.md`
- Modify: `openspec/specs/historical-data-maintenance/spec.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/DATA_CENTER.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `TESTING.md`
- Modify: `STATUS.md`
- Modify only when release process requires displayed package version: `services/quant-api/pyproject.toml`
- Modify only when release process requires displayed package version: `apps/quant-web/package.json`

- [ ] `subing-ths-alert` 写明：首次/换月 evaluator 只接受同 physical contract 的 Canonical lifecycle prefix + 当日 completed Live；第一页 latest bootstrap 不能放宽 MarketDataService；history 缺失 fail-closed。
- [ ] `canonical-market-storage` 写明 contract partition 的双重包含不变量，并明确 continuous exact equality 不变。
- [ ] `historical-data-maintenance` 写明 contract-warmup 的 identity/lifecycle、dry-run 零 provider/零 mutation、plan hash、maintenance lock、direct/derived lineage、partial/no-auto-retry 与独立外部 Gate。
- [ ] `PROJECT_SOURCE.md` 只更新稳定产品/数据边界；不写 release 完成态。
- [ ] `docs/DATA_CENTER.md` 与 `docs/ARCHITECTURE.md` 只增加唯一维护入口与读取依赖，不复制完整执行记录。
- [ ] `TESTING.md` 增加定向测试命令和明确警告：命令示例不授权真实 RQData/Canonical apply。
- [ ] `STATUS.md` 在代码尚未 release 时只记录 `v1.9.15` RC 工作及 pending Gate；保留 `v1.9.14` production Runtime、G9 enabled Scope、0/自然 Event 等当前真实 readback，不提前写 `RELEASED` 或 `RUNTIME_READY`。
- [ ] 不修改 `DECISIONS.md`：批准 Design 已确认这不是新 formula/data version 决策；若实现中出现与该结论冲突的新长期决策，立即停止并回到设计评审。
- [ ] 若版本字段仍按仓库历史保持 `1.9.12` 且 release identity 只由 Git tag 决定，不顺手改包版本；先以 release tooling/canonical 事实为准。
- [ ] 验证：

```bash
openspec validate --specs --strict --no-interactive
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

预期：OpenSpec strict、engineering consistency、secret scan 全通过；secret scan 输出不得包含秘密内容。

- [ ] 提交：

```bash
git add openspec/specs/subing-ths-alert/spec.md \
  openspec/specs/canonical-market-storage/spec.md \
  openspec/specs/historical-data-maintenance/spec.md \
  PROJECT_SOURCE.md docs/DATA_CENTER.md docs/ARCHITECTURE.md TESTING.md STATUS.md
git commit -m "docs: define physical contract warmup boundary"
```

只有实际发生版本文件变更时才将其加入本 commit。

---

## Task 7: 全量验证、独立 Review 与合入 `develop`

**Files:**

- Review: all changes from Task 0 execution baseline to branch HEAD
- Modify: only files required to fix verified findings

- [ ] 定向 backend：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/test_market_home_projection_invalidation.py
```

- [ ] 完整非 isolated backend：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

- [ ] 静态与 canonical：

```bash
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] Web release contract（即使 Web 源码未改也运行）：

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

- [ ] 只有本 release 风险/既有 release checklist 要求浏览器 smoke 时才运行：

```bash
pnpm --dir apps/quant-web test:e2e
```

若不运行，RC handoff 必须明确标记 `not run`，不能写“全量 Web 验证通过”。

- [ ] 对 exact branch HEAD 做两轴独立 Review：
  - Standards：AGENTS/canonical/security/maintainability；
  - Spec：批准 Design 与本 Plan 的行为/测试/Gate 覆盖。

由于协作代理只有在用户明确选择后才能启动，执行会话不得未经授权自动创建 subagent；若用户选择 inline execution，则由当前会话完成实现并在 Review Gate 停止，请用户授权独立 reviewer。

- [ ] 对每个 finding 先复现、再最小修复、重跑受影响测试；阻断 finding 未清零不得形成 RC。
- [ ] fresh verify 后记录：exact HEAD、测试命令/计数、reviewer identity/结论、dirty state、未运行检查和全部外部 pending Gates。
- [ ] 按仓库普通开发流程将任务分支合入 `develop` 并 push；这一步不是 release：

```bash
git status --short
git log --oneline --decorate origin/develop..HEAD
git push -u origin codex/subing-live-contract-warmup
```

创建 PR、CI/Review 全绿后合入 `develop`，随后读回：

```bash
git fetch origin develop
git rev-parse origin/develop
git status --short --branch
```

- [ ] 仅在任务 worktree clean 且 merge 已证实时移除 `/private/tmp/guiyi-subing-live-contract-warmup`；绝不删除主工作区。

**Task 7 completion state:** `CODE_COMPLETE / TEST_COMPLETE / RELEASE_GATE_PENDING`。

---

## Task 8: `v1.9.15` Release Gate（实现会话必须停在授权前）

此 Task 是外部受控操作，不由前面任何批准自动授权。

- [ ] 从最新 `develop` 准备 release PR，确认 exact RC SHA、`v1.9.14..RC` diff、release identity、CI 与 clean state。
- [ ] 向用户提交唯一 release approval packet，至少包含：

```text
target=main
exact_rc=<40-char sha>
version=v1.9.15
tag=annotated v1.9.15
github_release=yes
rollback_boundary=before main merge/tag/release
```

- [ ] 只有收到引用 exact RC 的新明确授权，才允许将 release PR 合入 main、创建 annotated `v1.9.15` tag 并发布 GitHub Release。
- [ ] 发布后只读核验：

```text
main HEAD
tag object type=tag
tag peeled commit == main HEAD
GitHub Release tag/target/published state
```

- [ ] 任何失败不自动重试；报告已完成 mutation 与剩余恢复边界。

**Task 8 completion state:** `RELEASED`，但仍不是 PF data repaired 或 Runtime promoted。

---

## Task 9: exact-tag PF2611 read-only plan 与独立真实 apply Gate

**Exact target:**

```text
release=v1.9.15@<released-sha>
symbol=pf
contract=PF2611
listed_date=2025-11-17
through=2026-09-03
frequencies=1m,5m,15m,30m,60m,1d,1w
```

- [ ] 从 clean detached exact `v1.9.15` root 使用现有安全配置执行只读：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api guiyi data contract-warmup \
  --symbol pf \
  --contract PF2611 \
  --through 2026-09-03
```

- [ ] 确认 `readonly=true`、provider request 实际调用为零，报告 exact target windows、预计 Bar 数、direct/derived target 数、预计 provider request 数、`plan_sha256`、现有 Canonical/Catalog baseline、Runtime 状态与失败恢复边界。
- [ ] 请求一条新的、引用 exact tag 和 exact plan hash 的真实执行授权。批准文本应包含：

```text
授权 exact v1.9.15@<sha> 对 pf/PF2611 through=2026-09-03
执行 contract-warmup --apply --expected-plan-sha256 <sha256>；失败不自动重试。
```

- [ ] 只有收到该授权后才执行一次 apply。hash 漂移、maintenance lock、provider/validation/publish 任一失败都立即停止，不自动重新生成 hash 后继续。
- [ ] apply 后只读验证：
  - PF2611 七周期 Dataset/partition/coverage/row_count 与物理 Parquet 可读；
  - 15m 从真实 1m lineage 聚合且 warm-up 足够；
  - D1/W1/1m hash 与目标一致；
  - 非目标 Dataset、MainContractMap、Rule、Scope、Event、Redis Live、notification count 无变化；
  - 2026-09-03 after-market failure 事实未改写。

**Task 9 completion state:** `PF_DATA_READY`，仍不是 Runtime promoted。

---

## Task 10: 五项 exact-tag Runtime promotion Gate

- [ ] 在 Runtime 仍运行旧版本时先做只读 preflight：五项 service label、root、PID、health、current trading phase、live subscription snapshot、Alert per-rule status、rollback root。
- [ ] 请求 exact tag/root/五项服务/rollback 范围明确的新 Runtime promotion 授权。
- [ ] 获得授权后一次切换 API/Web/Live/Alert/After-market 到 clean detached `v1.9.15@<sha>`；不得在 promotion 中改变 Scope、Rule、Redis 内容、凭据或发送消息。
- [ ] 完成 identity/health/data readback：

```text
all five launchd roots == exact detached v1.9.15 root
API/Web HTTP 200
Live/Alert running when scheduled
After-market loaded with schedule semantics
production DB revision unchanged
SuBing enabled Scope remains exact 60 × 15m
PF live contract and PF2611 Canonical history are both readable
```

- [ ] 失败时按已批准 rollback boundary 恢复旧 root；任何超出已批准的一次重试需新授权。

**Task 10 completion state:** `RUNTIME_READY`，但自然开盘 acceptance 尚未完成。

---

## Task 11: 自然开盘只读验证与 G11/G12

- [ ] 在自然交易时段观察，不注入 synthetic、不手工发 Event、不 replay/backfill、不执行 alert canary。
- [ ] 对 60 个 operational products 区分并报告：market phase、subscription contract、completed 15m 可用、SuBing per-rule last evaluated、processing error、Event increment、provider acceptance。
- [ ] PF 专项要求：Live owner 是当日 rank1；若为 `PF2611`，replay 的全部历史前缀和 Live cutoff 必须同为 PF2611；不得跨合约。
- [ ] 一个 unrelated 1m heartbeat/processing success 不能替代 SuBing 15m per-rule readback。
- [ ] 若自然 completed 15m 没有 Candidate，结论只能是“评估链路通过、等待自然信号”，不能声明 G11。
- [ ] 只有自然 Candidate 形成 immutable `AlertEvent` 且 one-shot transport 获得 provider acceptance 才完成 G11；provider accepted 仍不等于微信送达。
- [ ] G12 只有用户实际确认微信收到后完成。

---

## Final Acceptance Matrix

| Gate | Required evidence | Does not prove |
|---|---|---|
| Code | Task tests + full verification + clean diff | release/runtime/data repaired |
| RC | exact `develop` SHA + review/CI | main/tag/GitHub Release |
| Release | main + annotated tag + GitHub Release exact identity | PF apply/runtime |
| PF plan | read-only targets + plan hash | RQData fetched/Canonical written |
| PF apply | seven-frequency physical readback + unchanged non-target facts | Runtime uses it |
| Runtime | five exact-tag roots + health/data identity | natural SuBing Event |
| Open validation | natural completed 15m per-rule success | Candidate/notification |
| G11 | natural Event + provider acceptance | WeChat delivery |
| G12 | user confirms actual WeChat receipt | trading authorization |

## Rollback and Recovery Boundaries

- Code before merge：普通 Git commit/revert；不得使用 destructive reset。
- Release before tag/publication：停止在 RC；release mutation 后按 release procedure 单独处理，不 force-update public tag。
- PF plan：纯只读，无 rollback。
- PF apply：每个成功月分区是独立有效事实；失败保留成功分区并报告 partial，后续只读重规划；不得用旧错误数据覆盖，也不得自动重试。
- Runtime promotion：仅按批准的旧 exact root 回滚；数据修复不因 Runtime rollback 而反向删除。
- Event/notification：不可变、不回放、不补发；任何自然失败保留为证据。

## Definition of Done

- [ ] Production-shaped replay regression 通过，第一页确认为 `before=None`，strict `MarketDataService` 未放宽。
- [ ] Contract Dataset 双重包含不变量在 update/refresh/audit/store boundary 均有测试。
- [ ] `contract-warmup` dry-run 零 provider/零 mutation，apply hash-locked、持 maintenance lease、只触达 exact family。
- [ ] PF2611 七周期真实数据只有在独立授权后写入并完成只读 readback。
- [ ] `v1.9.15` release、PF apply、Runtime promotion 均分别取得 exact 授权并有证据。
- [ ] 自然开盘能在 relevant completed 15m 上推进 SuBing per-rule evaluator；若无自然 Candidate，G11/G12 保持 pending。
- [ ] 没有 formula/data version、migration、Scope、audience、retry、order 或 Web formula 的越界变化。
