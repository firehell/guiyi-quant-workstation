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
- `scripts/ops/macos/install-openclaw-weixin-tools.sh` — render/check/install helper whose default is dry/read-only and whose real install mode remains externally gated.
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
- Consumed later by `WeixinAlertSender`, `AlertRuntime`, and `alert-canary`.

- [ ] **Step 1: Copy the formatter/model tests out of `test_alert_wecom.py` and make them import `app.alerts.notification`**

Keep the existing exact HTDY/SuBing expected strings. Add this Protocol-shape smoke test:

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

- [ ] **Step 2: Run the focused test and verify import failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py
```

Expected: FAIL because `app.alerts.notification` does not exist.

- [ ] **Step 3: Create `notification.py` by moving, not rewriting, the existing dataclass/formatter logic**

Required public shape:

```python
from typing import Protocol


class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...
```

Move the current `_SHANGHAI`, validation, `_format_htdy_message`, and `_format_subing_message` without altering their conditions or output, and define the exact generic canary constant above.

- [ ] **Step 4: Change `runtime.py` to depend on `AlertNotificationSender`**

Replace the concrete import/type:

```python
from app.alerts.notification import AlertNotificationMessage, AlertNotificationSender
```

and constructor parameter:

```python
sender: AlertNotificationSender,
```

Do not change the Event creation/send ordering or exception boundary.

- [ ] **Step 5: Run notification + existing runtime tests**

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
- Produces: `NotificationRecipient(alias: str, target: str)` frozen dataclass.
- Produces: `RecipientRegistrySnapshot(version: int, channel: str, account_id: str, recipients: tuple[NotificationRecipient, ...])`.
- Produces: `RecipientRegistryError(RuntimeError)` with stable codes only.
- Produces: `load_recipient_registry(path: Path) -> RecipientRegistrySnapshot`.
- Produces: `write_recipient_registry(path: Path, snapshot: RecipientRegistrySnapshot) -> None`.
- Produces: `add_recipient(snapshot, recipient) -> RecipientRegistrySnapshot`.

- [ ] **Step 1: Write registry validation tests**

Include parameterized tests for missing path, directory/symlink/non-regular path, mode != `0600`, malformed JSON, version != 1, channel != `openclaw-weixin`, blank account, duplicate alias, duplicate target, non-boolean enabled, target not ending `@im.wechat`, empty/all-disabled, and a fixed safe maximum of **16 enabled recipients**.

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

- [ ] **Step 2: Run the focused tests and verify import failure**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement immutable load/validation**

Use `Path.lstat()` and `stat.S_ISREG`, reject symlinks, require `stat.S_IMODE(mode) == 0o600`, parse exact schema, normalize aliases with `strip()` but preserve opaque target text after `strip()`, and return only enabled recipients in the runtime snapshot.

- [ ] **Step 4: Add atomic write tests**

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

`write_recipient_registry` must require an existing `0700` parent, write a same-directory temporary file as `0600`, `fsync`, and `os.replace` it. It must not create arbitrary parent directories.

- [ ] **Step 5: Run tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipient_registry.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add \
  services/quant-api/app/alerts/recipient_registry.py \
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
- Produces: `OpenClawWeixinDependency(root, cli_executable, node_executable, plugin_root, openclaw_version, plugin_version)` frozen dataclass.
- Produces: `resolve_openclaw_weixin_dependency(root: Path, *, run_process=...) -> OpenClawWeixinDependency`.
- Produces: `OpenClawWeixinAdapterRunner(dependency, *, run_process=...)`.
- Produces: `probe(snapshot) -> None`.
- Node adapter exports `runProbe`, `runRegister`, `runMonitor`, `runSend` for Node tests and also supports CLI action in `process.argv[2]`.

- [ ] **Step 1: Add exact dependency identity**

Create `deploy/openclaw/versions.json` exactly:

```json
{
  "schema_version": 1,
  "openclaw": "2026.8.1",
  "openclaw_weixin": "2.4.6",
  "node": "24.15.0"
}
```

- [ ] **Step 2: Write Python dependency-probe tests**

Mock fixed argv and return JSON matching `openclaw plugins inspect openclaw-weixin --json`. Assert the command is exactly:

```python
[
    str(root / "runtime/bin/openclaw"),
    "plugins",
    "inspect",
    "openclaw-weixin",
    "--json",
]
```

Reject wrong OpenClaw/plugin version, disabled/error status, missing install path, path escaping `root`, missing node executable, and malformed JSON using only `WEIXIN_ADAPTER_INCOMPATIBLE`/`WEIXIN_ADAPTER_UNAVAILABLE`.

- [ ] **Step 3: Implement dependency discovery**

Read `deploy/openclaw/versions.json`, validate fixed executables:

```text
<root>/runtime/bin/openclaw
<root>/runtime/tools/node/bin/node
```

Use `realpath()` containment checks for plugin root. Never use PATH, glob, shell strings, `latest`, or runtime package search.

- [ ] **Step 4: Write Node probe tests with a fake managed plugin project**

The fake tree must include exact ESM modules under:

```text
dist/src/auth/accounts.js
dist/src/api/api.js
dist/src/storage/sync-buf.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

and a fake `node_modules/openclaw` package exposing `plugin-sdk/config-runtime` so the adapter can use `createRequire(<plugin_root>/package.json)` to resolve OpenClaw peer imports.

Test that `runProbe()`:

- resolves the exact account only;
- requires account enabled/configured/token;
- restores tokens and requires all supplied approved targets to have context;
- never invokes `sendMessageWeixin` or `getUpdates`;
- returns `{status:"ready", recipient_count:N}` without target/account/token fields.

- [ ] **Step 5: Implement adapter dependency loading**

At the top of the adapter, before dynamic imports:

```javascript
process.env.OPENCLAW_LOG_LEVEL = "FATAL";
```

Use `pathToFileURL` for exact Tencent module files and `createRequire(path.join(pluginRoot, "package.json"))` to resolve `openclaw/plugin-sdk/config-runtime`; call `loadConfig()` and `resolveWeixinAccount(config, accountId)`.

- [ ] **Step 6: Run Python and Node tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin.py

node --test tests/engineering/openclaw_weixin_adapter.test.mjs
```

Expected: both PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  deploy/openclaw/versions.json \
  services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/tests/test_alert_weixin.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add pinned iLink adapter probe"
```

---

### Task 4: Implement challenge registration without OpenClaw Agent/pairing

**Files:**
- Modify: `services/quant-api/app/alerts/weixin.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_weixin.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- Produces: `generate_registration_challenge() -> str` using `secrets` and at least 80 bits of entropy.
- Produces: `RegistrationMatch(alias: str, target: str)` internal dataclass; `target` is never logged/printed.
- Produces: `register_recipient(alias, *, stderr, timeout_seconds=180.0) -> RecipientRegistrySnapshot`.
- CLI: `guiyi runtime weixin-register --alias <alias>`.

- [ ] **Step 1: Extend parser/CLI tests**

Update the runtime command set to:

```python
{"status", "live", "alert", "alert-canary", "weixin-context", "weixin-register"}
```

Add a test that injected registration prints the challenge only to the supplied interactive `stderr`, returns final sanitized JSON on stdout, and never exposes target:

```python
assert "u2@im.wechat" not in stdout.getvalue()
assert "u2@im.wechat" not in stderr.getvalue()
```

- [ ] **Step 2: Write Node `register` tests**

Fake `getUpdates` must return, in order:

1. unknown sender with wrong text;
2. already-approved sender with a new context token;
3. new sender with the exact challenge and non-empty context token.

Assert:

- sync cursor is saved for every returned response;
- approved sender token refresh occurs;
- wrong unknown sender is not persisted;
- exact-match target is persisted with `setContextToken` and returned once to captured parent stdout;
- no `sendMessageWeixin`, Agent, pairing, or reply function is imported/called.

Also cover timeout, two exact matches in one response (`WEIXIN_REGISTRATION_AMBIGUOUS`), missing context, and non-`@im.wechat` sender.

- [ ] **Step 3: Implement `register` action**

Use exact text matching only:

```javascript
const text = msg.item_list?.find((item) => item?.type === 1)?.text_item?.text;
if (text === challenge && msg.from_user_id?.endsWith("@im.wechat") && msg.context_token) {
  // candidate
}
```

Never send a reply. Use the persisted `get_updates_buf` file through plugin helpers.

- [ ] **Step 4: Implement Python registration orchestration**

Rules:

- reject blank/unsafe alias with `WEIXIN_RECIPIENT_ALIAS_INVALID`;
- before polling, fail if `com.guiyi.quant-weixin-context` is currently loaded/running (inject the check in tests; no implicit stop);
- if registry is absent, private adapter must find exactly one indexed account; Python writes the first snapshot only after exact challenge match;
- if registry exists, use its exact account and reject duplicate alias/target;
- challenge is written once to the provided interactive stream and is never logged;
- captured target is used only to build `NotificationRecipient` then discarded.

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
git add \
  services/quant-api/app/alerts/weixin.py \
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
- Create: `tests/engineering/test_weixin_context_launchd.py`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- Produces: `WeixinContextStatus` parser with `schema_version/status/recipient_count/last_poll_at/last_context_refresh_at/last_error_code` only.
- Produces: `WeixinContextMonitor.run_forever() -> None`.
- Produces: `build_weixin_context_monitor_from_env() -> WeixinContextMonitor`.
- CLI: `guiyi runtime weixin-context` foreground loop.
- launchd label: `com.guiyi.quant-weixin-context`.

- [ ] **Step 1: Write Node monitor tests**

Fake `getUpdates` sequence must prove:

- cursor resumes from persisted value;
- new cursor is saved before message handling;
- approved target + context refreshes token;
- unknown sender is dropped without body/target logging and without token persistence;
- `sendMessageWeixin` is never called;
- SIGTERM ends the loop and calls `notifyStop` best-effort;
- network errors back off and retry only `getUpdates`;
- stale token marks status degraded and rereads the same account credential instead of QR/login.

- [ ] **Step 2: Implement privacy-safe atomic status file**

Adapter `monitor` receives `status_path` in stdin bootstrap. Write same-directory temp JSON at mode `0600`, `fsync`, `rename`. Never include ids or message content. Use `status="ok"` only after a successful poll response; use stable `last_error_code` on degraded polls.

- [ ] **Step 3: Write Python wrapper tests**

Test that `WeixinContextMonitor` loads an immutable registry snapshot, resolves dependency once, invokes fixed Node argv:

```python
[
    str(dependency.node_executable),
    str(PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"),
    "monitor",
]
```

passes targets only through stdin, and collapses child exit/error to `WEIXIN_CONTEXT_MONITOR_FAILED` without echoing child stderr.

- [ ] **Step 4: Implement `weixin_context.py` and CLI branch**

`runtime weixin-context` must be a foreground process, like `runtime alert`; it must not daemonize. Its final payload after natural exit is:

```json
{
  "schema_version": 1,
  "command": "runtime.weixin-context",
  "status": "ok",
  "foreground": true
}
```

- [ ] **Step 5: Add launchd template and render-only mode**

`com.guiyi.quant-weixin-context.plist.template` must use the existing `run-local-service.sh` path and carry the same `GUIYI_PROJECT_ROOT` / `GUIYI_RUNTIME_COMMIT` identity as Alert. Extend `run-local-service.sh` with a `weixin-context)` branch invoking `uv run ... guiyi runtime weixin-context`.

Extend `install-local-services.sh` with a distinct `--confirm-weixin-context` mode. `--render-only` renders it but never loads it. `--confirm-alert-runtime` will later load context before Alert, but do not add real readiness waiting until Task 7.

- [ ] **Step 6: Run focused tests**

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

Expected: PASS; no launchctl mutation under render-only.

- [ ] **Step 7: Commit Task 5**

```bash
git add \
  services/quant-api/app/alerts/weixin_context.py \
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

### Task 6: Implement single-shot four-recipient sending and generic canary

**Files:**
- Modify: `services/quant-api/app/alerts/weixin.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- Modify: `services/quant-api/tests/test_alert_weixin.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `tests/engineering/openclaw_weixin_adapter.test.mjs`

**Interfaces:**
- Produces: `WeixinRecipientSendResult(alias: str, status: str)`.
- Produces: `WeixinSendSummary(attempted: int, provider_accepted: int, failed: int, failed_aliases: tuple[str, ...])`.
- Produces: `WeixinAlertSender.send(message) -> None` and `send_canary() -> WeixinSendSummary`.
- `send()` raises one sanitized `WeixinSendError` only after the adapter has attempted every eligible recipient.

- [ ] **Step 1: Write Node send fan-out tests**

With four fake targets, configure fake `sendMessageWeixin` so member_3 rejects. Assert physical calls are exactly one per recipient and in one process invocation; member_4 is still attempted. Assert no second call for member_3.

Add context-missing test: target with no token produces `context_missing` and zero physical send for that target.

- [ ] **Step 2: Implement adapter `send`**

Use `Promise.allSettled` over recipients. Before each call, require exact account configured/token and restored exact context token. Call only:

```javascript
await sendMessageWeixin({
  to: recipient.target,
  text,
  opts: {
    baseUrl: account.baseUrl,
    token: account.token,
    contextToken,
  },
});
```

Do not call plugin `sendWeixinOutbound`, hooks, Gateway, queue, or Agent surfaces.

- [ ] **Step 3: Write Python sender tests**

Inject a subprocess result containing sanitized adapter JSON and verify:

```python
sender.send(message)
```

formats once and passes one payload containing all recipients. Add tests for child timeout, malformed JSON, nonzero exit, 3/4 success, and raw stderr containing fake secrets; public exception/log must not contain them.

- [ ] **Step 4: Implement `WeixinAlertSender` and canary**

`send_canary()` must use `ALERT_CANARY_TEXT` and the same frozen registry/dependency/adapter path as `send()`. There is no per-target override API.

- [ ] **Step 5: Run focused tests**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add \
  services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
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
- Produces: `build_weixin_sender_from_env() -> WeixinAlertSender`.
- `build_alert_runtime()` requires activation marker + fresh context monitor + adapter probe before constructing Runtime.
- `alert-canary` default factory becomes `build_weixin_sender_from_env`.

- [ ] **Step 1: Add failing composition/CLI tests**

Replace the old missing-webhook assertion with fail-closed cases for missing recipient path/OpenClaw root/context status. Add test that canary never constructs AlertRuntime or DB session and uses only the shared Weixin sender.

- [ ] **Step 2: Add context-status freshness validator**

Use a fixed **90-second freshness window**. At construction time require status schema 1, `status="ok"`, approved recipient count, timezone-aware `last_poll_at`, and age <= 90 seconds. Collapse failures to `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`.

- [ ] **Step 3: Rewire composition**

`build_alert_runtime()` order:

```text
activation marker
→ load operational products/taxonomy
→ load recipient registry
→ validate monitor status
→ resolve pinned OpenClaw/plugin dependency
→ adapter probe 4/4 context
→ construct Redis source/heartbeat
→ construct AlertRuntime(sender=WeixinAlertSender(...))
```

No transport preflight may create AlertEvent, Scope mutation, or send a message.

- [ ] **Step 4: Make `--confirm-alert-runtime` load context before Alert**

In `install-local-services.sh`, `--confirm-alert-runtime` loads `com.guiyi.quant-weixin-context`, waits up to 90 seconds for the privacy-safe context status to become fresh/ok, then loads `com.guiyi.quant-alert`, and writes the alert marker only after both load steps succeed. Failure must leave Alert not loaded/marker not enabled.

Engineering tests use fake launchctl and a fake status file; no real service is started.

- [ ] **Step 5: Delete WeCom implementation/tests and close active imports**

After deletion, run:

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true
```

Expected after Task 8 canonical edits: no active references. Historical release/spec evidence outside these active paths may still mention WeCom.

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
git add -A \
  services/quant-api/app/alerts \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_alert_*.py \
  scripts/ops/macos/install-local-services.sh \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_weixin_context_launchd.py
git commit -m "feat(alert): switch develop transport to iLink"
```

---

### Task 8: Add OpenClaw tooling docs/status, update canonicals, and run full verification

**Files:**
- Create: `deploy/openclaw/README.md`
- Create: `scripts/ops/macos/install-openclaw-weixin-tools.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `TESTING.md`
- Modify: `AGENTS.md`
- Modify: `PROJECT_SOURCE.md`
- Modify: `DECISIONS.md`
- Do not modify `STATUS.md` to claim production transport changed.

**Interfaces:**
- `install-openclaw-weixin-tools.sh --check` is read-only.
- Any future real install mode requires an explicit flag such as `--confirm-install` and remains Lane 3; D1 tests use only `--check`/fixture paths.
- `local-services-status.sh` reports guiyi context-monitor identity plus external OpenClaw/plugin dependency versions without exposing install secrets/recipient IDs.

- [ ] **Step 1: Write engineering tests for tooling/status**

`--check` must verify expected paths/version contract from fixture data and must not run npm install, QR login, launchctl, or send commands. `local-services-status.sh` fixture output must include:

```text
external.openclaw.version=2026.8.1
external.openclaw_weixin.version=2.4.6
weixin_context.loaded=...
weixin_context.status=...
```

with no target/account fields.

- [ ] **Step 2: Implement tool-check and status sections**

Keep OpenClaw external dependency identity separate from guiyi Git commit identity. Do not add any OpenClaw Gateway service label.

- [ ] **Step 3: Update `TESTING.md` Alert V2 section**

Replace `test_alert_wecom.py` with the new notification/registry/weixin/context tests and add:

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
scripts/ops/macos/install-local-services.sh --render-only
```

Explicitly state that `weixin-register`, QR login, real canary, `--confirm-weixin-context`, `--confirm-alert-runtime`, OpenClaw install, release, and Runtime promotion are not test permissions.

- [ ] **Step 4: Update active canonicals without falsifying production state**

`AGENTS.md`, `PROJECT_SOURCE.md`, and `DECISIONS.md` must record:

- develop architecture is notification-only iLink with no Gateway/AI inbound;
- no-retry/no-queue Event semantics remain;
- the old WeCom continuous authorization remains a **production Runtime fact until D8/D9** and does not authorize iLink;
- iLink real canary/continuous authorization/Runtime promotion are separate Lane 3 Gates;
- `STATUS.md` remains the sole source for the still-running v1.4.2 WeCom Runtime.

Do not say iLink is production active or continuously authorized.

- [ ] **Step 5: Run the full project-native verification relevant to this change**

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

Expected: all commands exit 0; secret scan reports 0 findings; no command sends a real message or mutates Runtime.

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

Verify no evaluator formula, Rule Scope, migration, DB schema, Canonical, order path, main/tag, or Runtime file was modified.

- [ ] **Step 7: Commit Task 8**

```bash
git add \
  deploy/openclaw \
  scripts/ops/macos/install-openclaw-weixin-tools.sh \
  scripts/ops/macos/local-services-status.sh \
  TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md \
  tests/engineering
git commit -m "docs(alert): define iLink notification operations"
```

---

## D1 Completion Gate

Before this branch may integrate to `develop`, the reviewer must be able to state all of the following from fresh evidence:

```text
PASS: no real external operation was executed
PASS: no OpenClaw Gateway exists in the runtime design
PASS: inbound adapter cannot enter Agent/LLM/slash/tool pipeline
PASS: recipient registration is exact-challenge and monitor-exclusive
PASS: every AlertEvent×recipient has at most one physical send attempt
PASS: Event remains committed on notification failure
PASS: no notification retry/replay/backfill/outbox/queue
PASS: no DB migration/schema/Scope/evaluator/order change
PASS: active WeCom code is retired on develop
PASS: production v1.4.2 WeCom state was not modified or falsely rewritten in STATUS.md
```

If all pass, the code task conclusion is **允许集成 develop**. D2-D9 remain blocked behind the separate rollout plan and their own explicit user Gates.