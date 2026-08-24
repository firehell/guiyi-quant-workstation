# No-Watch Reliability V1 Implementation Plan

> **Goal:** 在不增加自动交易、重型平台或第二套事实链的前提下，让单用户工作站能在白天无人盯盘时，可靠暴露 Alert 与盘后任务的自然运行状态，并提供可检查的 Market 首页健康入口。

## Scope and Gates

- 只修改普通源码、测试与 canonical 文档。
- 不执行 Runtime switch、真实 PushPlus、真实 RQData/Canonical/DB 写入、migration、main merge、tag 或 release。
- Alert 运行观察只写现有 Redis，盘后运行观察只写既有状态文件；不新增 PostgreSQL 表、队列、retry 或独立监控进程。
- 所有通知与 Web 状态都是研究/运维观察，不是交易指令；`auto_order=false` 不变。
- Stage 2 四系统全周期观察实现暂停到本计划合入 `develop`；无需等待自然事件即可恢复 Stage 2 工程实施，但自然证据仍保持独立 pending。

## Task 1: Repair engineering and canonical documentation facts

**Files:**

- Modify: `tests/engineering/test_canonical_consistency.py`
- Modify: `STATUS.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `docs/RQALPHA_RESEARCH_BACKTEST.md` when its current wording requires correction
- Include: this implementation plan

**Behavior:**

1. Add a failing engineering test proving that tracked Markdown files are allowed only directly under `docs/superpowers/specs/` and `docs/superpowers/plans/`.
2. Keep `docs/tasks/` empty and reject any other tracked file below `docs/superpowers/`, including nested files under the two allowed directories.
3. Correct `STATUS.md` so the pending natural after-market fact targets the current v1.8 Runtime rather than v1.7, remove the stale Diagnostic controller next step, and make No-Watch Reliability V1 the current minimum next step.
4. Clarify that RQAlpha workbench code is included in v1.8, while the local sidecar remains unloaded and outside Runtime and its real smoke remains pending.
5. Record that the four-system design and implementation plan are approved and persisted, while implementation is paused behind this reliability layer.

**Verification:**

```bash
uv run --offline --project services/quant-api pytest -q tests/engineering/test_canonical_consistency.py
git diff --check
```

## Task 2: Add persistent Alert Redis runtime observation

**Files:**

- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/app/alerts/pushplus.py` and/or composition only as required by the existing transport seam
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_service.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`

**Behavior:**

1. Persist schema-version-1 JSON at Redis key `alert:runtime-status` without TTL:
   `last_processed_bar_at`, `last_processing_success_at`, `last_processing_failure_at`,
   `processing_error_type`, `last_event_at`, `last_transport_attempt_at`,
   `last_provider_accepted_at`, `last_notification_failure_at`,
   `notification_error_type`, and `consecutive_notification_failures`.
2. Missing state means `unobserved`, never success.
3. A processing failure after a success is degraded. A notification failure after a provider acceptance is degraded. The next provider acceptance clears notification failure state and the consecutive counter.
4. Missing taxonomy is a notification-preparation failure and must not fabricate a transport attempt.
5. Do not persist or expose provider references.
6. A Redis runtime-status write failure is fail-closed: the supervised Alert process exits/restarts rather than continuing with log-only observability loss.
7. Make `AlertNotificationSender.send` return the existing/new minimal `ProviderAcceptance` value needed to record provider acceptance.
8. Preserve the `AlertEvent` model, DB schema and historical timing/meaning of `notification_attempted_at` exactly; the Redis status is the transport-observation layer.
9. Expand `/api/runtime/health.components.alert` with `processing_state=unobserved|ok|failed`, `notification_state=unobserved|provider_accepted|failed`, the relevant timestamps/counter/error types, and an `ok` value that remains structurally healthy when unobserved but exposes that lack of natural verification.

**Verification:**

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_runtime_health.py
```

## Task 3: Make after-market state crash-visible and notify only natural failures

**Files:**

- Modify: `services/quant-api/app/market_data/after_market.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Modify: existing composition/config seam only as needed to reuse PushPlus owner transport
- Modify: `services/quant-api/tests/data_foundation/test_after_market.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`

**Behavior:**

1. Upgrade the after-market status file to schema version 2 while reading version 1 compatibly.
2. Add `current_run={scheduled_date,started_at,products}` and write it immediately at natural-run start. Every write uses a same-directory temporary file followed by atomic replacement. Clear `current_run` only when the run is finalized.
3. Add `last_run.failure_notification={attempted_at,state,error_type}`, with state `provider_accepted|failed`.
4. Resolve the latest expected trading day through the repository `TradingCalendar` for the exchanges represented by `operational_products.txt`: before 18:20 use only prior trading days; at/after 18:20 today may be expected. The cross-exchange result must be unique; unavailable or non-unique is fail-closed.
5. Classify no status before the first expected run as pending; classify an expected run missing after 18:20, or a last success older than the expected day, as degraded/missed. Classify a `current_run` at most two hours old as running/pending and older than two hours as degraded/stuck.
6. Replace the legacy failure-notifier seam with PushPlus owner-only for a natural after-market execution failure. Send at most one request, no retry, no Topic, AlertEvent, DB, replay or fallback.
7. Use a fixed sanitized message containing trading day, public error code, attempts and `系统运维提醒，非交易指令`.
8. Provider acceptance is not delivery. Notification failure updates `last_run.failure_notification=failed` but does not alter or retry the primary after-market result.
9. Missed/stuck health states never send because there is no independent monitor process.

**Verification:**

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/test_runtime_health.py
```

## Task 4: Add a compact Market homepage runtime status strip

**Files:**

- Modify: `apps/quant-web/src/api/runtime.ts` or the current API module
- Add/Modify: a focused Market runtime-status component
- Modify: `apps/quant-web/src/pages/market/index.vue`
- Add/Modify: focused unit tests and Market Playwright coverage

**Behavior:**

1. Define the full runtime-health DTO and render a compact status strip on the existing Market homepage; do not add a route or page.
2. Show overall, Live, Alert and after-market state plus useful timestamps. Distinguish `服务商已接受` from delivery, `未获自然验证`, failure, running, missed and stuck.
3. On mount fetch Formal, Runtime, Radar and Trend. The single manual refresh fetches all four. Visibility returning to visible refreshes only Formal and Runtime, not Radar/Trend.
4. Add generation guards so stale requests cannot overwrite newer results.
5. Runtime refresh failure preserves the last successful payload and marks it stale; the first failure is unavailable. Formal may retain its current fail-closed behavior.

**Verification:**

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
```

## Task 5: Add opt-in data audit progress without changing stdout JSON

**Files:**

- Modify: `services/quant-api/app/guiyi_cli/data_parser.py`
- Modify: `services/quant-api/app/guiyi_cli/data_commands.py`
- Modify: `services/quant-api/app/market_data/manager.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`
- Modify: focused HistoricalDataManager tests as needed
- Modify: `TESTING.md`
- Modify: `docs/DATA_CENTER.md`

**Behavior:**

1. Add optional `guiyi data audit --progress`; without it, stdout JSON and all existing behavior are byte-for-byte compatible.
2. Give `HistoricalDataManager.audit` an optional observer seam that emits one `started` and one `completed` event per product.
3. With `--progress`, write stderr NDJSON records with literal shape: `schema_version=1`, `event=data.audit.progress`, `state=started|completed`, `completed`, `total`, `symbol`, and `finding_count` (`null` on started).
4. Do not add a quick mode and do not make provider requests.
5. If progress output itself fails, disable later progress emissions and let the audit continue to its normal result.

**Verification:**

```bash
uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation
```

## Task 6: Close canonical documentation and integrate into develop

**Files:**

- Modify: `AGENTS.md`
- Modify: `DECISIONS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `docs/DATA_CENTER.md`
- Modify: `STATUS.md`
- Modify: `TESTING.md` when validation commands changed

**Behavior:**

1. Record the Alert Redis observation contract, after-market schema/threshold contract, owner-only one-shot operational failure notification, Market homepage health strip and opt-in audit progress.
2. Keep the operational after-market failure notification separate from Alert Rules: owner only, natural execution failure only, at most once and no retry.
3. Record only `CODE_COMPLETE / TEST_COMPLETE` on `develop`; explicitly preserve release, Runtime switch, real notification, natural-event acceptance and real data writes as separate pending Gates.
4. Run independent final Standards and plan-compliance review. Fix all Critical/Important findings and re-run affected checks.
5. Merge the reviewed task branch into local `develop`, push `develop`, and read back the remote SHA. Do not modify `main`, create release/tag, switch Runtime or send a real notification.
6. After the `develop` integration is confirmed, mark Stage 2 engineering implementation as resumable; do not start Stage 2 in this task.

**Final verification:**

```bash
uv run --offline --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/data_foundation/test_after_market.py \
  services/quant-api/tests/data_foundation/test_cli.py

uv run --offline --project services/quant-api pytest -q \
  -m "not isolated_postgresql" services/quant-api/tests

uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api:packages/quant-core \
uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/backtest \
  services/quant-api/app/market_data \
  services/quant-api/app/research \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/alerts \
  services/quant-api/app/execution_review \
  services/quant-api/app/runtime_entry.py \
  services/quant-api/app/services/runtime_health.py \
  services/quant-api/app/api/market.py \
  services/quant-api/app/api/market_live.py \
  services/quant-api/app/api/alerts.py \
  services/quant-api/app/api/execution_review.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web exec playwright test -c playwright.config.mjs
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```
