# Weixin iLink Notification Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the develop-branch WeCom Alert transport with a notification-only Tencent iLink direct-DM implementation that uses a private pinned OpenClaw/Tencent adapter, a four-recipient local registry, and a non-AI context monitor while preserving Alert Event-first/no-retry semantics.

**Architecture:** OpenClaw is control-plane tooling only: pinned CLI/plugin install, inspect, and QR login. Runtime code never starts OpenClaw Gateway. A single Node adapter is the only private Tencent-plugin seam and exposes `probe/register/monitor/send`; Python owns Alert contracts, registry policy, subprocess boundaries, and sanitized CLI/runtime behavior. `com.guiyi.quant-weixin-context` is a guiyi exact-commit service that long-polls `getUpdates` only to refresh approved-recipient context tokens.

**Tech Stack:** Python 3.13 stdlib + existing FastAPI/SQLAlchemy codebase, Node 24.x ESM with built-in `node:test`, macOS launchd, OpenClaw 2026.8.1, `@tencent-weixin/openclaw-weixin` 2.4.6.

**Spec:** `docs/superpowers/specs/2026-08-18-weixin-ilink-direct-notification-design.md`

## Global Constraints

- This is **Lane 2 code work only**. Use **Sol, high reasoning, Plan-then-execute** because the change crosses Alert Runtime, CLI, Node private integration, launchd, and canonical contracts.
- Work in one new task branch/worktree created from `develop`; do not modify `main` or any Runtime worktree.
- Do not install OpenClaw, run QR login, create the real recipient registry, send any WeChat/WeCom message, reload launchd, switch Runtime, mutate Scope/DB/Canonical, create tag/release, or touch orders.
- Preserve `htdy_original_15m`, `subing_entry_signal_v1`, existing Rule Scope semantics, evaluator formulas, Alert two-table schema, production DB revision, and `auto_order=false`.
- Preserve Event-first semantics: committed Event is never rolled back or retried because notification failed.
- No notification queue, outbox, retry, replay, backfill, provider failover, recipient/delivery DB table, or OpenClaw Gateway.
- Private Tencent-plugin coupling is allowed only in `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs` and is exact-version/exact-module-shape fail-closed.
- Tests must use temp files, fake plugin trees, mocked subprocesses, fixture DBs, and render-only launchd. No test may access production/runtime credentials or network iLink.
- Real target/account/token/context values must never appear in tracked files or guiyi logs/tests.

---

## File Structure

### Create

- `services/quant-api/app/alerts/notification.py` — transport-neutral Alert notification model, Protocol, formatter, canary text.
- `services/quant-api/app/alerts/recipient_registry.py` — private registry load/validate/atomic-write/snapshot helpers.
- `services/quant-api/app/alerts/weixin.py` — OpenClaw dependency probe, adapter runner, registration orchestration, sender and sanitized result types.
- `services/quant-api/app/alerts/weixin_context.py` — Python foreground context-monitor wrapper and status validation.
- `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs` — only private Tencent/OpenClaw integration seam; `probe/register/monitor/send`.
- `deploy/openclaw/versions.json` — exact dependency identity.
- `deploy/openclaw/README.md` — control-plane/runtime paths and explicit no-Gateway boundary.
- `deploy/launchd/com.guiyi.quant-weixin-context.plist.template` — guiyi-owned context-monitor service.
- `scripts/ops/macos/install-openclaw-weixin-tools.sh` — check/install helper whose default path is read-only and whose real install mode remains externally gated.
- `services/quant-api/tests/test_alert_notification.py`
- `services/quant-api/tests/test_alert_recipient_registry.py`
- `services/quant-api/tests/test_alert_weixin.py`
- `services/quant-api/tests/test_alert_weixin_context.py`
- `tests/engineering/openclaw_weixin_adapter.test.mjs`
- `tests/engineering/test_weixin_context_launchd.py`

### Modify

- `services/quant-api/app/alerts/runtime.py`
- `services/quant-api/app/alerts/composition.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/tests/test_alert_runtime.py`
- `services/quant-api/tests/test_alert_cli.py`
- `tests/engineering/test_alert_runtime_launchd.py`
- `scripts/ops/macos/install-local-services.sh`
- `scripts/ops/macos/run-local-service.sh`
- `scripts/ops/macos/local-services-status.sh`
- `TESTING.md`
- `AGENTS.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`

### Delete in the final code task

- `services/quant-api/app/alerts/wecom.py`
- `services/quant-api/tests/test_alert_wecom.py`

---

### Task 1: Extract the transport-neutral Alert notification contract

**Files:**
- Create: `services/quant-api/app/alerts/notification.py`
- Create: `services/quant-api/tests/test_alert_notification.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Test source to migrate from: `services/quant-api/tests/test_alert_wecom.py`

**Interfaces:**
- Produces: `AlertNotificationMessage` dataclass with the current fields.
- Produces: `AlertNotificationSender(Protocol)` with `send(message) -> None`.
- Produces: `ALERT_CANARY_TEXT`.
- Produces: `format_alert_message(message) -> str` with unchanged HTDY/SuBing validation and wording.

- [ ] **Step 1: Copy formatter/model tests out of `test_alert_wecom.py` and import `app.alerts.notification`**

Keep the existing exact HTDY/SuBing expected strings. Add:

```python
from datetime import UTC, datetime

from app.alerts.notification import (
    ALERT_CANARY_TEXT,
    AlertNotificationMessage,
    format_alert_message,
)


def test_canary_text_is_channel_neutral() -> None:
    assert ALERT_CANARY_TEXT == "【归一量化】微信通知测试\n\nAlert 通知通道正常"


def test_subing_formatter_keeps_current_wording() -> None:
    message = AlertNotificationMessage(
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        product_name="焦煤",
        contract="JM2609",
        frequency="15m",
        bar_end=datetime(2026, 8, 18, 6, 15, tzinfo=UTC),
        result_codes=("buy",),
        lower_tf_confirmation=True,
    )
    assert format_alert_message(message) == "【苏冰】焦煤 · JM2609\n\n15m 买入信号 · 14:15\n5m 同向确认"
```

- [ ] **Step 2: Run focused test and verify import failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py
```

Expected: FAIL because `app.alerts.notification` does not exist.

- [ ] **Step 3: Create `notification.py` by moving, not rewriting, existing formatter logic**

Required Protocol:

```python
from typing import Protocol


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...
```

Move current timezone/validation/HTDY/SuBing formatter code without changing conditions or strings.

- [ ] **Step 4: Change `runtime.py` to depend on the Protocol**

```python
from app.alerts.notification import AlertNotificationMessage, AlertNotificationSender
```

Constructor:

```python
sender: AlertNotificationSender,
```

Do not change Event creation/send ordering or the post-commit exception boundary.

- [ ] **Step 5: Run notification + runtime tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add \
  services/quant-api/app/alerts/notification.py \
  services/quant-api/app/alerts/runtime.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
git commit -m "refactor(alert): extract notification contract"
```

---

### Task 2: Add the fail-closed private recipient registry

**Files:**
- Create: `services/quant-api/app/alerts/recipient_registry.py`
- Create: `services/quant-api/tests/test_alert_recipient_registry.py`

**Interfaces:**
- `NotificationRecipient(alias: str, target: str)` frozen dataclass.
- `RecipientRegistrySnapshot(version: int, channel: str, account_id: str, recipients: tuple[NotificationRecipient, ...])`.
- `RecipientRegistryError(RuntimeError)` with stable codes only.
- `load_recipient_registry(path: Path) -> RecipientRegistrySnapshot`.
- `write_recipient_registry(path: Path, snapshot: RecipientRegistrySnapshot) -> None`.
- `add_recipient(snapshot, recipient) -> RecipientRegistrySnapshot`.

- [ ] **Step 1: Write registry validation tests**

Cover missing path, directory/symlink/non-regular path, mode != `0600`, malformed JSON, version != 1, channel mismatch, blank account, duplicate alias/target, non-boolean enabled, target not ending `@im.wechat`, empty/all-disabled, and a fixed safe maximum of **16 enabled recipients**.

Representative test:

```python
def test_load_registry_rejects_duplicate_target(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        recipients=[
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "member_2", "target": "u1@im.wechat", "enabled": True},
        ],
    )
    with pytest.raises(RecipientRegistryError, match="^WEIXIN_RECIPIENT_REGISTRY_INVALID$"):
        load_recipient_registry(path)
```

- [ ] **Step 2: Run focused tests and verify import failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: FAIL because module is absent.

- [ ] **Step 3: Implement immutable load/validation**

Use `Path.lstat()` + `stat.S_ISREG`, reject symlinks, require `0600`, parse exact schema, strip aliases/targets, and return only enabled recipients in the runtime snapshot.

- [ ] **Step 4: Add atomic-write tests and implementation**

```python
def test_write_registry_is_atomic_and_owner_only(tmp_path: Path) -> None:
    parent = tmp_path / "secrets"
    parent.mkdir(mode=0o700)
    path = parent / "alert-weixin-recipients.json"
    snapshot = RecipientRegistrySnapshot(
        version=1,
        channel="openclaw-weixin",
        account_id="bot-im-bot",
        recipients=(NotificationRecipient("owner", "u1@im.wechat"),),
    )
    write_recipient_registry(path, snapshot)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_recipient_registry(path) == snapshot
```

Implementation must require an existing `0700` parent, create a same-directory `0600` temp file, flush+`fsync`, then `os.replace`.

- [ ] **Step 5: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add services/quant-api/app/alerts/recipient_registry.py \
  services/quant-api/tests/test_alert_recipient_registry.py
git commit -m "feat(alert): add private recipient registry"
```

---

### Task 3: Freeze OpenClaw dependency discovery and adapter probe

**Files:**
- Create: `deploy/openclaw/versions.json`
- Create: `services/quant-api/app/alerts/weixin.py`
- Create: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Create: `services/quant-api/tests/test_alert_weixin.py`
- Create: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- `OpenClawWeixinDependency(root, cli_executable, node_executable, plugin_root, openclaw_version, plugin_version)` frozen dataclass.
- `resolve_openclaw_weixin_dependency(root: Path, *, run_process=...) -> OpenClawWeixinDependency`.
- `OpenClawWeixinAdapterRunner(dependency, *, run_process=...)`.
- `probe(snapshot) -> None`.
- Node adapter exports `runProbe`, `runRegister`, `runMonitor`, `runSend` for tests and supports `process.argv[2]` action.

- [ ] **Step 1: Add exact dependency identity**

Create:

```json
{
  "schema_version": 1,
  "openclaw": "2026.8.1",
  "openclaw_weixin": "2.4.6",
  "node": "24.15.0"
}
```

- [ ] **Step 2: Write Python dependency-probe tests**

Mock fixed argv and return JSON matching `plugins inspect`. Exact argv:

```python
[
    str(root / "runtime/bin/openclaw"),
    "plugins",
    "inspect",
    "openclaw-weixin",
    "--json",
]
```

Reject wrong OpenClaw/plugin version, disabled/error state, missing/escaping install path, missing Node executable, and malformed JSON with stable errors only.

- [ ] **Step 3: Implement dependency discovery**

Read `deploy/openclaw/versions.json`; require:

```text
<root>/runtime/bin/openclaw
<root>/runtime/tools/node/bin/node
```

Use realpath containment for plugin root. Never use PATH, glob, shell strings, `latest`, or runtime package search.

- [ ] **Step 4: Write Node probe tests with fake managed plugin project**

Fake exact files:

```text
dist/src/auth/accounts.js
dist/src/api/api.js
dist/src/storage/sync-buf.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

Also create fake `node_modules/openclaw` exports for `plugin-sdk/config-runtime`. Adapter uses `createRequire(path.join(pluginRoot, "package.json"))` to resolve this peer surface.

Assert `runProbe()` resolves exact account, requires enabled/configured/token, restores tokens, requires every approved target context, never calls send/getUpdates, and returns only `{status:"ready",recipient_count:N}`.

- [ ] **Step 5: Implement adapter dependency loading**

Before dynamic imports:

```javascript
process.env.OPENCLAW_LOG_LEVEL = "FATAL";
```

Use exact `pathToFileURL` imports for Tencent modules and `createRequire` for OpenClaw `loadConfig()`.

- [ ] **Step 6: Run Python + Node tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin.py

node --test tests/engineering/openclaw_weixin_adapter.test.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add deploy/openclaw/versions.json \
  services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/tests/test_alert_weixin.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add pinned iLink adapter probe"
```

---

### Task 4: Implement challenge registration without Agent/pairing

**Files:**
- Modify: `services/quant-api/app/alerts/weixin.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_weixin.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- `generate_registration_challenge() -> str` using `secrets` with at least 80 bits entropy.
- `RegistrationMatch(alias: str, target: str)` internal dataclass; target never logged/displayed.
- `register_recipient(alias: str, *, prompt_stream: TextIO, timeout_seconds: float = 180.0) -> RecipientRegistrySnapshot`.
- CLI: `guiyi runtime weixin-register --alias <alias>`.
- `main(..., prompt_stream: TextIO | None = None)` gains an injectable interactive stream. Production default opens `/dev/tty`; if no TTY is available, fail with `WEIXIN_REGISTRATION_TTY_REQUIRED` before polling.

- [ ] **Step 1: Extend parser/CLI tests**

Runtime command set becomes:

```python
{"status", "live", "alert", "alert-canary", "weixin-context", "weixin-register"}
```

Use `prompt_stream=io.StringIO()` in registration tests. Assert challenge appears only there; final stdout is one JSON document; stderr remains empty on success; target never appears in any stream.

Add timeout/failure test asserting stderr remains one parseable JSON error document and does not contain the challenge or target.

- [ ] **Step 2: Write Node `register` tests**

Fake `getUpdates` sequence:

1. unknown sender/wrong text;
2. already-approved sender/new context;
3. new sender/exact challenge/non-empty context.

Assert cursor saved, approved context refreshed, wrong unknown sender not persisted, exact target persisted via `setContextToken` and returned only to captured parent stdout, and no send/Agent/pairing/reply call.

Cover timeout, two exact matches in one response (`WEIXIN_REGISTRATION_AMBIGUOUS`), missing context, non-`@im.wechat` sender.

- [ ] **Step 3: Implement `register` action**

Exact text only:

```javascript
const text = msg.item_list?.find((item) => item?.type === 1)?.text_item?.text;
if (text === challenge && msg.from_user_id?.endsWith("@im.wechat") && msg.context_token) {
  // exact candidate
}
```

Never send a reply. Advance the persisted `get_updates_buf` through plugin helpers.

- [ ] **Step 4: Implement Python registration orchestration**

Rules:

- validate alias;
- fail if context monitor is currently running; never stop it implicitly;
- first registry creation requires exactly one indexed logged-in account;
- existing registry fixes account identity and rejects duplicate alias/target;
- generate challenge and write it only to `prompt_stream`, flush immediately, never log it;
- capture target from adapter stdout internally, write registry atomically, discard target from public outputs.

- [ ] **Step 5: Run focused tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add challenge recipient registration"
```

---

### Task 5: Add the notification-only context monitor and launchd contract

**Files:**
- Create: `services/quant-api/app/alerts/weixin_context.py`
- Create: `services/quant-api/tests/test_alert_weixin_context.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Create: `deploy/launchd/com.guiyi.quant-weixin-context.plist.template`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `scripts/ops/macos/run-local-service.sh`
- Create: `tests/engineering/test_weixin_context_launchd.py`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- `WeixinContextStatus` parser with only `schema_version/status/recipient_count/last_poll_at/last_context_refresh_at/last_error_code`.
- `WeixinContextMonitor.run_forever() -> None`.
- `build_weixin_context_monitor_from_env() -> WeixinContextMonitor`.
- CLI `guiyi runtime weixin-context`.
- launchd `com.guiyi.quant-weixin-context`.

- [ ] **Step 1: Write Node monitor tests**

Prove cursor resume/save-before-handle, approved-target refresh, unknown drop, zero send calls, SIGTERM graceful exit with best-effort `notifyStop`, getUpdates-only network backoff, and stale-token degraded behavior with same-account credential reread.

- [ ] **Step 2: Implement privacy-safe status file**

Adapter receives `status_path` through stdin bootstrap. Write same-directory `0600` temp JSON, flush+fsync+rename. Never include ids/body/token/provider raw text. `status="ok"` only after successful poll.

- [ ] **Step 3: Write Python wrapper tests using `Popen` abstraction**

The wrapper must spawn exact argv:

```python
[
    str(dependency.node_executable),
    str(PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"),
    "monitor",
]
```

It writes one bootstrap JSON document to child stdin, closes stdin, waits for the child, and never forwards raw child stdout/stderr.

Test injected signal handling: on parent SIGTERM/KeyboardInterrupt path, call child `terminate()`, wait with a bounded timeout, then `kill()` only if the child fails to exit. This is process cleanup, not notification retry.

- [ ] **Step 4: Implement `weixin_context.py` with `subprocess.Popen`**

Do not use `subprocess.run()` for the long-lived child. Install temporary signal handlers around the child lifetime and restore previous handlers on exit. Collapse unexpected child failure to `WEIXIN_CONTEXT_MONITOR_FAILED` without raw stderr.

- [ ] **Step 5: Add CLI branch**

`runtime weixin-context` stays foreground. Final natural-exit payload:

```json
{
  "schema_version": 1,
  "command": "runtime.weixin-context",
  "status": "ok",
  "foreground": true
}
```

- [ ] **Step 6: Add launchd template/render modes**

Template carries same `GUIYI_PROJECT_ROOT`/`GUIYI_RUNTIME_COMMIT` as Alert. Add `weixin-context)` to `run-local-service.sh`. Add `--confirm-weixin-context` to installer; render-only never loads it.

- [ ] **Step 7: Run focused tests**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin_context.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_weixin_context_launchd.py \
  tests/engineering/test_alert_runtime_launchd.py
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-weixin-context.plist
```

Expected: PASS; render-only performs no launchctl mutation.

- [ ] **Step 8: Commit Task 5**

```bash
git add services/quant-api/app/alerts/weixin_context.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_alert_weixin_context.py \
  deploy/launchd/com.guiyi.quant-weixin-context.plist.template \
  scripts/ops/macos/install-local-services.sh \
  scripts/ops/macos/run-local-service.sh \
  tests/engineering/test_weixin_context_launchd.py \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add notification-only context monitor"
```

---

### Task 6: Implement single-shot fan-out and structured canary result

**Files:**
- Modify: `services/quant-api/app/alerts/weixin.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_weixin.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- `WeixinRecipientSendResult(alias: str, status: str)`.
- `WeixinSendSummary(attempted: int, provider_accepted: int, failed: int, failed_aliases: tuple[str, ...])`.
- `WeixinAlertSender.send(message) -> None`.
- `WeixinAlertSender.send_canary() -> WeixinSendSummary`.

- [ ] **Step 1: Write Node send fan-out tests**

Four fake targets; member_3 rejects. Assert exactly one physical call per recipient, member_4 still attempted, no second call for member_3. Context-missing target gets zero physical call.

- [ ] **Step 2: Implement adapter `send`**

Use `Promise.allSettled`. Before each send require same account configured/token + exact context. Call only:

```javascript
await sendMessageWeixin({
  to: recipient.target,
  text,
  opts: { baseUrl: account.baseUrl, token: account.token, contextToken },
});
```

Do not call `sendWeixinOutbound`, hooks, Gateway, queue, or Agent surfaces.

- [ ] **Step 3: Write Python sender tests**

Verify one formatted text + one child process per Alert, all recipients included, child timeout/malformed JSON/nonzero exit collapse, partial failure is isolated, raw stderr secrets never appear publicly.

- [ ] **Step 4: Implement `WeixinAlertSender`**

`send(message)` must complete the adapter fan-out and raise one sanitized `WeixinSendError("WEIXIN_SEND_FAILED")` if summary.failed > 0; Runtime catches it after Event commit. Do not retry.

`send_canary()` uses `ALERT_CANARY_TEXT` and returns the full sanitized summary instead of raising for ordinary recipient failures; catastrophic adapter failure may raise a stable transport error.

- [ ] **Step 5: Change `runtime alert-canary` to emit structured result and nonzero on partial failure**

Success payload must be:

```json
{
  "schema_version": 1,
  "command": "runtime.alert-canary",
  "status": "ok",
  "attempted": 4,
  "provider_accepted": 4,
  "failed": 0,
  "failed_aliases": []
}
```

Partial failure payload must still be written to stdout as a normal command result, but use `status="failed"` so `main()` returns exit code 1:

```json
{
  "schema_version": 1,
  "command": "runtime.alert-canary",
  "status": "failed",
  "attempted": 4,
  "provider_accepted": 3,
  "failed": 1,
  "failed_aliases": ["member_3"]
}
```

Do not treat provider accepted as delivered/read.

- [ ] **Step 6: Run focused tests**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add single-shot Weixin sender"
```

---

### Task 7: Rewire Alert composition, gate startup, and retire active WeCom code

**Files:**
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Delete: `services/quant-api/app/alerts/wecom.py`
- Delete: `services/quant-api/tests/test_alert_wecom.py`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`

**Interfaces:**
- `build_weixin_sender_from_env() -> WeixinAlertSender`.
- `build_alert_runtime()` requires activation marker + fresh context status + adapter probe before Runtime construction.
- default canary factory becomes `build_weixin_sender_from_env`.

- [ ] **Step 1: Add failing composition/CLI tests**

Replace missing-webhook assertions with missing recipient/OpenClaw/context status fail-closed tests. Canary must never construct DB session or AlertRuntime.

- [ ] **Step 2: Add context-status freshness validator**

Fixed **90-second** window. Require schema 1, `status="ok"`, expected recipient count, aware `last_poll_at`, age <=90s. Collapse failure to `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`.

- [ ] **Step 3: Rewire composition**

Order:

```text
activation marker
→ operational products/taxonomy
→ recipient registry
→ monitor status
→ pinned OpenClaw/plugin dependency
→ adapter probe 4/4 context
→ Redis source/heartbeat
→ AlertRuntime(sender=WeixinAlertSender)
```

No preflight may create Event, mutate Scope, or send.

- [ ] **Step 4: Make `--confirm-alert-runtime` load context first**

Load `com.guiyi.quant-weixin-context`, wait up to 90s for fresh/ok privacy-safe status, then load `com.guiyi.quant-alert`; write alert marker only after both succeed. Failure leaves Alert marker disabled and must not report success.

- [ ] **Step 5: Delete WeCom implementation/tests and close active imports**

After Task 8 canonical edits, this search must have no active hits:

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true
```

Historical evidence outside active paths may retain old facts.

- [ ] **Step 6: Run Alert regression tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_recipient_registry.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_weixin_context.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_weixin_context_launchd.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```bash
git add -A services/quant-api/app/alerts \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests \
  scripts/ops/macos/install-local-services.sh \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_weixin_context_launchd.py
git commit -m "feat(alert): switch develop transport to iLink"
```

---

### Task 8: Add tooling/status, update canonicals, and run full verification

**Files:**
- Create: `deploy/openclaw/README.md`
- Create: `scripts/ops/macos/install-openclaw-weixin-tools.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `TESTING.md`
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Do not change `STATUS.md` to claim production transport changed.

**Interfaces:**
- `install-openclaw-weixin-tools.sh --check` is read-only and exits 0 with a structured `not_installed` status when the external tools are absent; it never installs in D1.
- A future real `--confirm-install` path may perform D2 only after external authorization.
- `local-services-status.sh` reports guiyi context identity + external version identity without PII/secrets.

- [ ] **Step 1: Write engineering tests for tooling/status**

Fixture `--check` verifies version/path contracts but never npm/login/launchctl/send. Local status fixture includes:

```text
external.openclaw.version=2026.8.1
external.openclaw_weixin.version=2.4.6
weixin_context.loaded=...
weixin_context.status=...
```

No target/account fields.

- [ ] **Step 2: Implement tooling/status**

Keep external OpenClaw dependency identity separate from guiyi commit identity. Do not add any OpenClaw Gateway service label.

- [ ] **Step 3: Update `TESTING.md` Alert V2 section**

Add new Python/Node tests and read-only commands:

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
scripts/ops/macos/install-local-services.sh --render-only
```

Explicitly say registration, QR login, real canary, `--confirm-weixin-context`, `--confirm-alert-runtime`, OpenClaw install, release and promotion are not test permissions.

- [ ] **Step 4: Update active canonicals without falsifying production state**

`AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md` must record:

- develop architecture is notification-only iLink, no Gateway/AI inbound;
- no-retry/no-queue Event semantics remain;
- current production Runtime remains v1.4.2 WeCom until rollout D8/D9;
- existing WeCom continuous authorization does not authorize iLink;
- iLink canary/continuous authorization/promotion are separate Lane 3 Gates;
- `STATUS.md` remains source of current production fact.

Do not say iLink is production active or continuously authorized.

- [ ] **Step 5: Run full relevant project-native verification**

```bash
python3 scripts/engineering/secret_scan.py --json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_recipient_registry.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_weixin_context.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_weixin_context_launchd.py

node --test tests/engineering/openclaw_weixin_adapter.test.mjs

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy \
  --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli \
  services/quant-api/app/services/runtime_health.py

find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
plutil -lint .run/launchd/com.guiyi.quant-weixin-context.plist

git diff --check
git status --short
```

Expected: all exit 0; secret scan 0 findings; no command sends or mutates Runtime.

- [ ] **Step 6: Search active references and review scope**

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true

git diff --stat develop...HEAD
git diff develop...HEAD -- \
  services/quant-api/app/alerts \
  services/quant-api/app/guiyi_cli \
  services/quant-api/tests \
  deploy/openclaw deploy/launchd \
  scripts/ops/macos \
  TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md
```

Verify no evaluator formula, Rule Scope, migration, DB schema, Canonical, order path, main/tag or Runtime worktree was modified.

- [ ] **Step 7: Commit Task 8**

```bash
git add deploy/openclaw \
  scripts/ops/macos/install-openclaw-weixin-tools.sh \
  scripts/ops/macos/local-services-status.sh \
  TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md \
  tests/engineering
git commit -m "docs(alert): define iLink notification operations"
```

---

## D1 Completion Gate

Fresh evidence must support all statements:

```text
PASS: no real external operation executed
PASS: no OpenClaw Gateway in runtime design
PASS: inbound cannot enter Agent/LLM/slash/tool pipeline
PASS: registration uses exact challenge and is monitor-exclusive
PASS: registration preserves CLI JSON contract via separate interactive prompt stream
PASS: context-monitor parent forwards termination to Node child
PASS: alert-canary reports aggregate acceptance and exits nonzero on partial failure
PASS: every AlertEvent×recipient has at most one physical send attempt
PASS: Event remains committed on notification failure
PASS: no notification retry/replay/backfill/outbox/queue
PASS: no DB migration/schema/Scope/evaluator/order change
PASS: active WeCom code retired on develop
PASS: production v1.4.2 WeCom state not modified or falsely rewritten in STATUS.md
```

If all pass: **允许集成 develop**. D2-D9 remain blocked behind the separate rollout plan and fresh user Gates.