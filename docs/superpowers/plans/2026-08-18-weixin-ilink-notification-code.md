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
- `scripts/ops/macos/install-openclaw-weixin-tools.sh` — check/install helper; real install path remains externally gated.
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
- `deploy/launchd/com.guiyi.quant-alert.plist.template`
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
- `AlertNotificationMessage` dataclass with current fields.
- `AlertNotificationSender(Protocol)` with `send(message) -> None`.
- `ALERT_CANARY_TEXT`.
- `format_alert_message(message) -> str` with unchanged HTDY/SuBing validation/wording.

- [ ] **Step 1: Copy formatter/model tests out of `test_alert_wecom.py` and import `app.alerts.notification`**

Keep current exact HTDY/SuBing expected strings. Add:

```python
from datetime import UTC, datetime

from app.alerts.notification import ALERT_CANARY_TEXT, AlertNotificationMessage, format_alert_message


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

Expected: FAIL because module is absent.

- [ ] **Step 3: Create `notification.py` by moving existing logic**

```python
from typing import Protocol


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...
```

Move current timezone/validation/formatter code without changing conditions or strings.

- [ ] **Step 4: Change `runtime.py` to depend on Protocol**

```python
from app.alerts.notification import AlertNotificationMessage, AlertNotificationSender
```

Constructor field:

```python
sender: AlertNotificationSender,
```

Do not change Event creation/send ordering.

- [ ] **Step 5: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add services/quant-api/app/alerts/notification.py \
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
- `RecipientRegistryError(RuntimeError)`.
- `load_recipient_registry(path: Path) -> RecipientRegistrySnapshot`.
- `write_recipient_registry(path: Path, snapshot: RecipientRegistrySnapshot) -> None`.
- `add_recipient(snapshot, recipient) -> RecipientRegistrySnapshot`.

- [ ] **Step 1: Write registry validation tests**

Cover missing path, directory/symlink/non-regular, mode != `0600`, malformed JSON, version != 1, channel mismatch, blank account, duplicate alias/target, non-boolean enabled, target not ending `@im.wechat`, empty/all-disabled, and maximum **16 enabled recipients**.

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

- [ ] **Step 2: Run tests and verify import failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: FAIL because module is absent.

- [ ] **Step 3: Implement immutable load/validation**

Use `lstat`, reject symlink, require regular `0600`, strict schema, stripped alias/target, runtime snapshot contains only enabled recipients.

- [ ] **Step 4: Add atomic-write test and implementation**

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

Require existing `0700` parent; same-dir `0600` temp; flush, `fsync`, `os.replace`.

- [ ] **Step 5: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add services/quant-api/app/alerts/recipient_registry.py services/quant-api/tests/test_alert_recipient_registry.py
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
- `OpenClawWeixinDependency(root, cli_executable, node_executable, plugin_root, openclaw_version, plugin_version)`.
- `resolve_openclaw_weixin_dependency(root: Path, *, run_process=...) -> OpenClawWeixinDependency`.
- `OpenClawWeixinAdapterRunner(dependency, *, run_process=...)`.
- `probe(snapshot) -> None`.
- Node exports `runProbe/runRegister/runMonitor/runSend` and CLI action in `process.argv[2]`.

- [ ] **Step 1: Create exact version file**

```json
{
  "schema_version": 1,
  "openclaw": "2026.8.1",
  "openclaw_weixin": "2.4.6",
  "node": "24.15.0"
}
```

- [ ] **Step 2: Write Python dependency-probe tests**

Exact inspect argv:

```python
[
    str(root / "runtime/bin/openclaw"),
    "plugins",
    "inspect",
    "openclaw-weixin",
    "--json",
]
```

Reject wrong versions/status, missing/escaping install path, missing Node, malformed JSON.

- [ ] **Step 3: Implement dependency discovery**

Require fixed:

```text
<root>/runtime/bin/openclaw
<root>/runtime/tools/node/bin/node
```

Realpath containment only; no PATH/glob/shell/`latest`.

- [ ] **Step 4: Write Node probe tests with fake managed plugin tree**

Exact fake files:

```text
dist/src/auth/accounts.js
dist/src/api/api.js
dist/src/storage/sync-buf.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

Add fake `node_modules/openclaw` export for `plugin-sdk/config-runtime`. Adapter resolves it via `createRequire(path.join(pluginRoot, "package.json"))`.

Probe must require exact account enabled/configured/token, restore all contexts, never call send/getUpdates, and return only `{status:"ready",recipient_count:N}`.

- [ ] **Step 5: Implement adapter module loading**

Before plugin imports:

```javascript
process.env.OPENCLAW_LOG_LEVEL = "FATAL";
```

Use exact file URLs and OpenClaw `loadConfig()` peer surface.

- [ ] **Step 6: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_weixin.py
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add deploy/openclaw/versions.json services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs services/quant-api/tests/test_alert_weixin.py \
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
- `generate_registration_challenge() -> str`, at least 80 bits entropy.
- `RegistrationMatch(alias: str, target: str)` internal only.
- `register_recipient(alias: str, *, prompt_stream: TextIO, timeout_seconds: float = 180.0) -> RecipientRegistrySnapshot`.
- CLI `guiyi runtime weixin-register --alias <alias>`.
- `main(..., prompt_stream: TextIO | None = None)`: production default opens `/dev/tty`; no TTY -> `WEIXIN_REGISTRATION_TTY_REQUIRED` before polling.

- [ ] **Step 1: Extend CLI tests**

Runtime commands:

```python
{"status", "live", "alert", "alert-canary", "weixin-context", "weixin-register"}
```

Use injected `prompt_stream=io.StringIO()`. Challenge only appears there; stdout is one final JSON; stderr empty on success; target absent from every stream. Failure must leave stderr as one parseable JSON error with no challenge/target.

- [ ] **Step 2: Write Node registration tests**

Sequence: wrong unknown; approved refresh; exact new challenge. Assert cursor persistence, approved refresh, unknown drop, exact target context persistence, no send/Agent/pairing/reply. Cover timeout, two matches, missing context, invalid sender.

- [ ] **Step 3: Implement exact challenge matching**

```javascript
const text = msg.item_list?.find((item) => item?.type === 1)?.text_item?.text;
if (text === challenge && msg.from_user_id?.endsWith("@im.wechat") && msg.context_token) {
  // candidate
}
```

Never reply. Advance plugin sync cursor.

- [ ] **Step 4: Implement Python registration orchestration**

Validate alias; refuse if context monitor runs; first registry needs exactly one indexed account; existing registry fixes account; challenge only to prompt stream; adapter target capture never logged; atomic registry write.

- [ ] **Step 5: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin.py services/quant-api/tests/test_alert_cli.py
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add services/quant-api/app/alerts/weixin.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add challenge recipient registration"
```

---

### Task 5: Add notification-only context monitor and launchd contract

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
- `WeixinContextStatus` parser with only schema/status/count/timestamps/error-code.
- `WeixinContextMonitor.run_forever() -> None`.
- `build_weixin_context_monitor_from_env() -> WeixinContextMonitor`.
- CLI `guiyi runtime weixin-context`.
- launchd `com.guiyi.quant-weixin-context`.

- [ ] **Step 1: Write Node monitor tests**

Prove cursor resume/save-before-handle, approved refresh, unknown drop, zero send calls, SIGTERM graceful exit + best-effort notifyStop, getUpdates-only backoff, stale-token degraded + same-account credential reread.

- [ ] **Step 2: Implement privacy-safe status file**

`status_path` via stdin bootstrap. Same-dir `0600` temp, fsync, rename. `status="ok"` only after successful poll. No ids/body/token/raw provider response.

- [ ] **Step 3: Write Python wrapper tests using `Popen`**

Exact argv:

```python
[
    str(dependency.node_executable),
    str(PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"),
    "monitor",
]
```

Write one bootstrap JSON to child stdin then close. Never forward raw child output. On parent termination: `terminate()`, bounded wait, `kill()` only if needed; restore previous signal handlers.

- [ ] **Step 4: Implement `weixin_context.py`**

Use `subprocess.Popen`, not `run`. Collapse unexpected child exit to `WEIXIN_CONTEXT_MONITOR_FAILED`.

- [ ] **Step 5: Add CLI foreground branch**

Natural-exit payload:

```json
{"schema_version":1,"command":"runtime.weixin-context","status":"ok","foreground":true}
```

- [ ] **Step 6: Add launchd template and render contract**

`com.guiyi.quant-weixin-context.plist.template` must carry:

```text
GUIYI_PROJECT_ROOT
GUIYI_RUNTIME_COMMIT
GUIYI_OPENCLAW_ROOT
GUIYI_ALERT_RECIPIENTS_PATH
```

Add template placeholders `__OPENCLAW_ROOT__` and `__ALERT_RECIPIENTS_PATH__`. `install-local-services.sh` renders them from environment variables. `--confirm-weixin-context` must require both variables to be absolute and non-empty; render-only may use explicit fixture values supplied by tests. Add `weixin-context)` to `run-local-service.sh`.

- [ ] **Step 7: Run tests**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin_context.py services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_weixin_context_launchd.py tests/engineering/test_alert_runtime_launchd.py
GUIYI_OPENCLAW_ROOT=/private/tmp/guiyi-render-openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/private/tmp/guiyi-render-secrets/recipients.json \
  scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-weixin-context.plist
```

Expected: PASS; no launchctl mutation.

- [ ] **Step 8: Commit Task 5**

```bash
git add services/quant-api/app/alerts/weixin_context.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin_context.py \
  deploy/launchd/com.guiyi.quant-weixin-context.plist.template scripts/ops/macos/install-local-services.sh \
  scripts/ops/macos/run-local-service.sh tests/engineering/test_weixin_context_launchd.py \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/openclaw_weixin_adapter.test.mjs
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

- [ ] **Step 1: Write Node fan-out tests**

Four targets; member_3 rejects. Exactly one physical call each, member_4 still attempted, no retry. Missing-context target gets zero physical send.

- [ ] **Step 2: Implement adapter `send`**

Use `Promise.allSettled`; exact account/config/context. Only:

```javascript
await sendMessageWeixin({
  to: recipient.target,
  text,
  opts: { baseUrl: account.baseUrl, token: account.token, contextToken },
});
```

No `sendWeixinOutbound`, hooks, Gateway, queue, Agent.

- [ ] **Step 3: Write Python sender tests**

One formatted text + one child process per Alert; all recipients included; timeout/malformed/nonzero collapse; partial failure isolated; raw stderr never public.

- [ ] **Step 4: Implement sender**

`send()` raises sanitized `WEIXIN_SEND_FAILED` after all attempts if any fail. `send_canary()` returns aggregate summary for ordinary recipient failures; catastrophic adapter failures may raise stable error.

- [ ] **Step 5: Change `alert-canary` JSON contract**

Success:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"ok","attempted":4,"provider_accepted":4,"failed":0,"failed_aliases":[]}
```

Partial failure remains normal stdout command result but `status="failed"`, so `main()` returns 1:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"failed","attempted":4,"provider_accepted":3,"failed":1,"failed_aliases":["member_3"]}
```

Provider accepted is not delivered/read.

- [ ] **Step 6: Run tests**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add services/quant-api/app/alerts/weixin.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add single-shot Weixin sender"
```

---

### Task 7: Rewire Alert composition, startup Gate, and retire active WeCom code

**Files:**
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `deploy/launchd/com.guiyi.quant-alert.plist.template`
- Delete: `services/quant-api/app/alerts/wecom.py`
- Delete: `services/quant-api/tests/test_alert_wecom.py`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`

**Interfaces:**
- `build_weixin_sender_from_env() -> WeixinAlertSender`.
- `build_alert_runtime()` requires activation marker + fresh context status + probe.
- canary default factory becomes `build_weixin_sender_from_env`.

- [ ] **Step 1: Add failing composition/CLI tests**

Replace webhook missing cases with recipient/OpenClaw/context status failures. Canary must never construct DB session or AlertRuntime.

- [ ] **Step 2: Add fixed context freshness validation**

**90 seconds**, schema 1, `status=ok`, expected count, aware timestamp; failure -> `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`.

- [ ] **Step 3: Rewire composition**

```text
activation marker
→ operational products/taxonomy
→ recipient registry
→ monitor status
→ pinned dependency
→ adapter probe 4/4
→ Redis source/heartbeat
→ AlertRuntime(WeixinAlertSender)
```

No Event/Scope/send in preflight.

- [ ] **Step 4: Inject the same private paths into Alert launchd**

Add `__OPENCLAW_ROOT__` and `__ALERT_RECIPIENTS_PATH__` to `com.guiyi.quant-alert.plist.template` so Alert and ContextMonitor receive the same values. `--confirm-alert-runtime` must reject missing/non-absolute render values.

- [ ] **Step 5: Make `--confirm-alert-runtime` load context first**

Load context, wait <=90s for fresh/ok status, then load Alert; write alert marker only after both succeed. Failure leaves Alert marker disabled and reports failure.

- [ ] **Step 6: Delete WeCom implementation/tests and close active imports**

After Task 8 canonical edits, no active hits:

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true
```

- [ ] **Step 7: Run regression tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_recipient_registry.py \
  services/quant-api/tests/test_alert_weixin.py services/quant-api/tests/test_alert_weixin_context.py \
  services/quant-api/tests/test_alert_runtime.py services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_weixin_context_launchd.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 7**

```bash
git add -A services/quant-api/app/alerts services/quant-api/app/guiyi_cli/main.py services/quant-api/tests \
  deploy/launchd/com.guiyi.quant-alert.plist.template scripts/ops/macos/install-local-services.sh \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_weixin_context_launchd.py
git commit -m "feat(alert): switch develop transport to iLink"
```

---

### Task 8: Add OpenClaw tooling/status, update canonicals, and verify D1

**Files:**
- Create: `deploy/openclaw/README.md`
- Create: `scripts/ops/macos/install-openclaw-weixin-tools.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `TESTING.md`
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Do not claim production transport changed in `STATUS.md`.

**Interfaces:**
- `install-openclaw-weixin-tools.sh --check`: read-only; exits 0 with `status=not_installed` when tools are absent.
- `install-openclaw-weixin-tools.sh --confirm-install`: D2-only real install entry; never called during D1 verification.
- `local-services-status.sh`: privacy-safe guiyi context identity + external dependency versions.

- [ ] **Step 1: Write engineering tests for tooling/status**

Fixture `--check` never npm/login/launchctl/send. Status fixture emits:

```text
external.openclaw.version=2026.8.1
external.openclaw_weixin.version=2.4.6
weixin_context.loaded=...
weixin_context.status=...
```

No account/target.

- [ ] **Step 2: Implement exact `--check` behavior**

Read `deploy/openclaw/versions.json`. If `$GUIYI_OPENCLAW_ROOT/runtime/bin/openclaw` is absent, print a structured `status=not_installed` and exit 0. If present, read only version/plugin inspect and return `installed|mismatch`; never modify files/config.

- [ ] **Step 3: Implement exact externally gated `--confirm-install` behavior**

Require `GUIYI_OPENCLAW_ROOT` to be an absolute `/Volumes/...` path and require exact versions from `versions.json`. The helper must:

1. create `runtime/state/cache/npm/tmp` under that root with state root mode 0700;
2. download the official OpenClaw CLI installer to a temporary file;
3. run it with `--prefix <root>/runtime --version 2026.8.1 --node-version 24.15.0 --no-onboard`;
4. set `OPENCLAW_PREFIX/STATE_DIR/CONFIG_PATH/CONFIG/npm_config_cache/TMPDIR` to the approved root;
5. run `openclaw plugins install npm:@tencent-weixin/openclaw-weixin@2.4.6 --pin`;
6. run `openclaw config set plugins.entries.openclaw-weixin.enabled true`;
7. never run `gateway`, `channels login`, `message send`, launchctl, guiyi Runtime switch, or onboarding.

The script itself does not decide authorization; callers may invoke `--confirm-install` only after D2 explicit intent.

- [ ] **Step 4: Implement `local-services-status.sh` additions**

Keep OpenClaw dependency version identity separate from guiyi commit identity. If Alert marker is enabled, context monitor is required; report fresh privacy-safe status. No Gateway label.

- [ ] **Step 5: Update `TESTING.md`**

Add new Python/Node tests and read-only commands. Explicitly state QR login, registration, real canary, `--confirm-install`, `--confirm-weixin-context`, `--confirm-alert-runtime`, release and promotion are not test permissions.

- [ ] **Step 6: Update active canonicals without falsifying production**

Record notification-only develop architecture/no Gateway, unchanged no-retry semantics, current production v1.4.2 WeCom until rollout D8/D9, no inheritance of WeCom authorization to iLink, and separate Lane 3 Gates. `STATUS.md` remains production fact source.

- [ ] **Step 7: Run full relevant verification**

```bash
python3 scripts/engineering/secret_scan.py --json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_registry.py services/quant-api/tests/test_alert_current_trading_day.py \
  services/quant-api/tests/test_alert_models.py services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_evaluator.py services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_recipient_registry.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_weixin_context.py services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py services/quant-api/tests/alembic/test_alert_v2_migration.py \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_weixin_context_launchd.py

node --test tests/engineering/openclaw_weixin_adapter.test.mjs

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli services/quant-api/app/services/runtime_health.py

find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
GUIYI_OPENCLAW_ROOT=/private/tmp/guiyi-render-openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/private/tmp/guiyi-render-secrets/recipients.json \
  scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
plutil -lint .run/launchd/com.guiyi.quant-weixin-context.plist
git diff --check
git status --short
```

Expected: exit 0; secret scan 0 findings; no external mutation.

- [ ] **Step 8: Search active references and review scope**

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true

git diff --stat develop...HEAD
git diff develop...HEAD -- \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli services/quant-api/tests \
  deploy/openclaw deploy/launchd scripts/ops/macos TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md
```

No evaluator formula, Scope, migration, DB schema, Canonical, order, main/tag or Runtime worktree change.

- [ ] **Step 9: Commit Task 8**

```bash
git add deploy/openclaw scripts/ops/macos/install-openclaw-weixin-tools.sh \
  scripts/ops/macos/local-services-status.sh TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md tests/engineering
git commit -m "docs(alert): define iLink notification operations"
```

---

## D1 Completion Gate

Fresh evidence must support:

```text
PASS no real external operation executed
PASS no OpenClaw Gateway in runtime design
PASS inbound cannot enter Agent/LLM/slash/tool pipeline
PASS registration exact-challenge and monitor-exclusive
PASS registration preserves CLI JSON via separate TTY/prompt stream
PASS context-monitor parent forwards termination to Node child
PASS Alert and ContextMonitor receive the same explicit private paths
PASS alert-canary reports aggregate acceptance and exits nonzero on partial failure
PASS each AlertEvent×recipient has at most one physical send attempt
PASS Event remains committed on notification failure
PASS no notification retry/replay/backfill/outbox/queue
PASS no DB migration/schema/Scope/evaluator/order change
PASS active WeCom code retired on develop
PASS production v1.4.2 WeCom state not modified/falsified in STATUS.md
```

If all pass: **允许集成 develop**. D2-D9 remain blocked behind the separate rollout plan and fresh user Gates.