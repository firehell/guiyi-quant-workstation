# Weixin iLink Notification Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the develop-branch WeCom Alert transport with a notification-only Tencent iLink direct-DM implementation using a pinned OpenClaw/Tencent adapter, a private recipient registry, and a non-AI context monitor while preserving Alert Event-first/no-retry semantics.

**Architecture:** OpenClaw is control-plane tooling only: pinned CLI/plugin install, inspect, and QR login. Runtime never starts OpenClaw Gateway. One Node adapter is the only private Tencent-plugin seam and exposes `probe/register/monitor/send`; Python owns notification contracts, recipient policy, process boundaries, startup readiness, CLI, and sanitized logging. `com.guiyi.quant-weixin-context` is a guiyi exact-commit service that long-polls `getUpdates` solely to refresh approved-recipient context tokens.

**Tech Stack:** Python 3.13 stdlib + existing FastAPI/SQLAlchemy stack, Node 24.15.0 ESM + built-in `node:test`, macOS launchd, OpenClaw 2026.8.1, `@tencent-weixin/openclaw-weixin` 2.4.6.

**Spec:** `docs/superpowers/specs/2026-08-18-weixin-ilink-direct-notification-design.md`

## Global Constraints

- Lane 2 code work only: **Sol, high reasoning, Plan-then-execute**.
- Create one task branch/worktree from `develop`; integrate only to `develop` after verification/review. Do not touch `main`, tag, or Runtime worktree.
- Do not install OpenClaw, QR login, create the real recipient registry, send WeChat/WeCom, load launchd, switch Runtime, mutate Rule Scope/DB/Canonical, or touch order paths.
- Preserve `htdy_original_15m`, `subing_entry_signal_v1`, their evaluator formulas and existing Scope semantics, Alert two-table schema, DB revision, and `auto_order=false`.
- Preserve Event-first behavior: notification failures never roll back committed AlertEvent and never trigger notification retry/replay/backfill/outbox/queue.
- Private Tencent coupling is allowed only in `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs` and is exact-version/exact-module-shape fail-closed.
- Tests use only temp paths, fake plugin trees, mocked subprocesses, fixture DBs, and render-only launchd. No iLink network access.
- Real account/target/token/context/challenge values never appear in tracked files or guiyi logs.

## File Structure

### Create

- `services/quant-api/app/alerts/notification.py`
- `services/quant-api/app/alerts/recipient_registry.py`
- `services/quant-api/app/alerts/weixin.py`
- `services/quant-api/app/alerts/weixin_context.py`
- `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- `deploy/openclaw/versions.json`
- `deploy/openclaw/README.md`
- `deploy/launchd/com.guiyi.quant-weixin-context.plist.template`
- `scripts/ops/macos/install-openclaw-weixin-tools.sh`
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
- `scripts/ops/macos/install-local-services.sh`
- `scripts/ops/macos/run-local-service.sh`
- `scripts/ops/macos/local-services-status.sh`
- `tests/engineering/test_alert_runtime_launchd.py`
- `TESTING.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`

### Delete at Task 7

- `services/quant-api/app/alerts/wecom.py`
- `services/quant-api/tests/test_alert_wecom.py`

---

### Task 1: Extract the transport-neutral notification contract

**Files:** create `notification.py`, create `test_alert_notification.py`, modify `runtime.py`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AlertNotificationMessage:
    rule_code: str
    symbol: str
    product_name: str
    contract: str
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool = False

class AlertNotificationSender(Protocol):
    def send(self, message: AlertNotificationMessage) -> None: ...

ALERT_CANARY_TEXT = "【归一量化】微信通知测试\n\nAlert 通知通道正常"

def format_alert_message(message: AlertNotificationMessage) -> str: ...
```

- [ ] **Step 1: Move formatter/model tests from `test_alert_wecom.py` to a new failing test file**

Keep all current HTDY/SuBing validation and exact expected strings. Add:

```python
def test_canary_text_is_channel_neutral() -> None:
    assert ALERT_CANARY_TEXT == "【归一量化】微信通知测试\n\nAlert 通知通道正常"
```

- [ ] **Step 2: Run red test**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_notification.py
```

Expected: import failure for `app.alerts.notification`.

- [ ] **Step 3: Move current dataclass/formatter code without semantic changes**

Do not alter timezone checks, Rule/frequency/result validation, or message text.

- [ ] **Step 4: Re-type `AlertRuntime.sender` to `AlertNotificationSender`**

Import notification types from `app.alerts.notification`; leave Event/send ordering unchanged.

- [ ] **Step 5: Verify**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_runtime.py
```

- [ ] **Step 6: Commit**

```bash
git add services/quant-api/app/alerts/notification.py services/quant-api/app/alerts/runtime.py \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_runtime.py
git commit -m "refactor(alert): extract notification contract"
```

---

### Task 2: Add immutable registry document + enabled Runtime projection

**Files:** create `recipient_registry.py`, create `test_alert_recipient_registry.py`.

**Interfaces:** storage and Runtime views must not be conflated:

```python
@dataclass(frozen=True, slots=True)
class NotificationRecipient:
    alias: str
    target: str
    enabled: bool

@dataclass(frozen=True, slots=True)
class RecipientRegistryDocument:
    version: int
    channel: str
    account_id: str
    recipients: tuple[NotificationRecipient, ...]

    @property
    def enabled_recipients(self) -> tuple[NotificationRecipient, ...]: ...

class RecipientRegistryError(RuntimeError): ...

def load_recipient_registry(path: Path) -> RecipientRegistryDocument: ...
def write_recipient_registry(path: Path, document: RecipientRegistryDocument) -> None: ...
def add_recipient(document: RecipientRegistryDocument, recipient: NotificationRecipient) -> RecipientRegistryDocument: ...
```

This preserves disabled records on read-modify-write while Runtime uses only `document.enabled_recipients`.

- [ ] **Step 1: Write failing validation tests**

Cover: missing, directory/symlink/non-regular, mode != `0600`, malformed JSON, version !=1, channel mismatch, blank account, blank/duplicate alias, duplicate target, non-boolean enabled, target not ending `@im.wechat`, empty/all-disabled, and more than **16 total recipient records**.

Representative:

```python
def test_disabled_recipient_survives_round_trip(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        recipients=[
            {"alias": "owner", "target": "u1@im.wechat", "enabled": True},
            {"alias": "paused", "target": "u2@im.wechat", "enabled": False},
        ],
    )
    document = load_recipient_registry(path)
    write_recipient_registry(path, document)
    reloaded = load_recipient_registry(path)
    assert [item.alias for item in reloaded.recipients] == ["owner", "paused"]
    assert [item.alias for item in reloaded.enabled_recipients] == ["owner"]
```

- [ ] **Step 2: Run red test**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_recipient_registry.py
```

- [ ] **Step 3: Implement strict load and projection**

Use `Path.lstat()`, reject symlink, require regular `0600`, strict schema and unique alias/target across all records.

- [ ] **Step 4: Implement atomic write and tests**

Require existing parent directory mode exactly `0700`; same-directory temp file mode `0600`; `json.dump`, flush, `os.fsync`, `os.replace`. Never create arbitrary parent directories.

- [ ] **Step 5: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_recipient_registry.py

git add services/quant-api/app/alerts/recipient_registry.py services/quant-api/tests/test_alert_recipient_registry.py
git commit -m "feat(alert): add private recipient registry"
```

---

### Task 3: Freeze dependency discovery and implement adapter `probe`

**Files:** create `versions.json`, `weixin.py`, adapter `.mjs`, Python/Node tests.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OpenClawWeixinDependency:
    root: Path
    cli_executable: Path
    node_executable: Path
    plugin_root: Path
    openclaw_version: str
    plugin_version: str

def resolve_openclaw_weixin_dependency(root: Path, *, run_process=...) -> OpenClawWeixinDependency: ...

class OpenClawWeixinAdapterRunner:
    def probe(self, document: RecipientRegistryDocument) -> None: ...
```

Exact version file:

```json
{"schema_version":1,"openclaw":"2026.8.1","openclaw_weixin":"2.4.6","node":"24.15.0"}
```

- [ ] **Step 1: Write Python discovery tests**

Assert fixed inspect argv:

```python
[
    str(root / "runtime/bin/openclaw"),
    "plugins", "inspect", "openclaw-weixin", "--json",
]
```

Reject wrong versions/status, malformed JSON, absent/escaping install path, absent fixed Node.

- [ ] **Step 2: Implement discovery**

Require:

```text
<root>/runtime/bin/openclaw
<root>/runtime/tools/node/bin/node
```

Read only `deploy/openclaw/versions.json`; use realpath containment; no PATH/glob/shell/latest.

All child commands use an explicit sanitized environment derived from `dependency.root`:

```python
{
    "OPENCLAW_PREFIX": str(root / "runtime"),
    "OPENCLAW_STATE_DIR": str(root / "state"),
    "OPENCLAW_CONFIG_PATH": str(root / "state/openclaw.json"),
    "OPENCLAW_CONFIG": str(root / "state/openclaw.json"),
    "TMPDIR": str(root / "tmp"),
    "OPENCLAW_LOG_LEVEL": "FATAL",
}
```

Do not inherit a conflicting `OPENCLAW_*` value from the parent environment.

- [ ] **Step 3: Build a fake managed plugin tree in Node tests**

Exact modules:

```text
dist/src/auth/accounts.js
dist/src/api/api.js
dist/src/storage/sync-buf.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

Fake `node_modules/openclaw` must export `plugin-sdk/config-runtime`.

- [ ] **Step 4: Resolve the OpenClaw ESM peer surface safely**

In adapter code:

```javascript
const requireFromPlugin = createRequire(path.join(pluginRoot, "package.json"));
const configRuntimePath = requireFromPlugin.resolve("openclaw/plugin-sdk/config-runtime");
const { loadConfig } = await import(pathToFileURL(configRuntimePath).href);
```

Do not call `require()` on the ESM module.

- [ ] **Step 5: Implement `probe`**

Before dynamic imports set `process.env.OPENCLAW_LOG_LEVEL = "FATAL"`. Require exact account enabled/configured/token, call `restoreContextTokens(accountId)`, require context for every `enabled_recipients` target, never call `getUpdates`/`sendMessageWeixin`, return only:

```json
{"status":"ready","recipient_count":4}
```

- [ ] **Step 6: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q services/quant-api/tests/test_alert_weixin.py
node --test tests/engineering/openclaw_weixin_adapter.test.mjs

git add deploy/openclaw/versions.json services/quant-api/app/alerts/weixin.py \
  services/quant-api/app/alerts/openclaw_weixin_adapter.mjs services/quant-api/tests/test_alert_weixin.py \
  tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add pinned iLink adapter probe"
```

---

### Task 4: Implement exact-challenge recipient registration

**Files:** modify `weixin.py`, adapter, CLI, Python/Node tests.

**Interfaces:**

```python
def generate_registration_challenge() -> str: ...  # >= 80 bits entropy

def register_recipient(
    alias: str,
    *,
    prompt_stream: TextIO,
    timeout_seconds: float = 180.0,
) -> RecipientRegistryDocument: ...
```

`main(..., prompt_stream: TextIO | None = None)` gains an injectable interactive stream. Production default opens `/dev/tty`; unavailable TTY fails before polling with `WEIXIN_REGISTRATION_TTY_REQUIRED`.

- [ ] **Step 1: Extend parser/CLI red tests**

Runtime commands become:

```python
{"status", "live", "alert", "alert-canary", "weixin-context", "weixin-register"}
```

Challenge appears only in `prompt_stream`; success stdout is one JSON document; stderr empty; target absent from all public streams. Failure stderr remains one parseable JSON error and contains neither challenge nor target.

- [ ] **Step 2: Write Node registration tests**

Fake `getUpdates` returns wrong unknown sender, approved sender with new context, then exact-challenge new sender. Assert cursor saved, approved context refreshed, wrong unknown ignored, matching context persisted, no outbound/Agent/pairing/reply call. Cover timeout, >1 exact match in one response (`WEIXIN_REGISTRATION_AMBIGUOUS`), missing context, invalid sender id.

- [ ] **Step 3: Implement exact candidate matching**

```javascript
const text = msg.item_list?.find((item) => item?.type === 1)?.text_item?.text;
const isCandidate =
  text === challenge &&
  msg.from_user_id?.endsWith("@im.wechat") &&
  Boolean(msg.context_token);
```

Never reply. Persist each returned sync cursor before processing its messages.

- [ ] **Step 4: Implement Python orchestration**

Reject invalid alias; fail if context monitor is running; first registration requires exactly one indexed configured account; later registration fixes account from document; reject duplicate alias/target; write challenge only to TTY/prompt stream; capture matched target internally, atomically update full `RecipientRegistryDocument`, discard target from public output.

- [ ] **Step 5: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_weixin.py services/quant-api/tests/test_alert_cli.py
node --test tests/engineering/openclaw_weixin_adapter.test.mjs

git add services/quant-api/app/alerts/weixin.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add challenge recipient registration"
```

---

### Task 5: Add notification-only context monitor + launchd contract

**Files:** create `weixin_context.py`, test, context plist; modify adapter, CLI, installer, run-local-service, launchd tests.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WeixinContextStatus:
    schema_version: int
    status: str
    recipient_count: int
    last_poll_at: datetime | None
    last_context_refresh_at: datetime | None
    last_error_code: str | None

class WeixinContextMonitor:
    def run_forever(self) -> None: ...
```

CLI: `guiyi runtime weixin-context`. Label: `com.guiyi.quant-weixin-context`.

- [ ] **Step 1: Write Node monitor red tests**

Prove sync cursor resume, save-before-handle, approved-target context refresh, unknown sender drop, zero outbound calls, graceful SIGTERM with best-effort `notifyStop`, and only `getUpdates` retry behavior.

Fix retry policy exactly:

```text
normal long poll timeout: 35s
transport exception backoff: 2s, 5s, 15s, then 30s capped
nonzero non-stale API response: 30s before same-cursor retry
stale token ret/errcode -14: status degraded; reread same account credential every 60s;
  resume only when token value changes; never QR login automatically
successful poll: reset transport backoff and write status=ok
```

`notifyStart` runs best-effort once before polling; `notifyStop` best-effort on graceful exit. Neither sends user-visible content.

- [ ] **Step 2: Implement privacy-safe status writes**

`status_path` arrives in stdin bootstrap. Same-dir temp `0600`, flush/fsync/rename. Only the six fields above; no ids/body/tokens/provider raw response.

- [ ] **Step 3: Write Python Popen/signal tests**

Exact child argv:

```python
[
    str(dependency.node_executable),
    str(PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs"),
    "monitor",
]
```

Write one bootstrap JSON to stdin then close it. Never forward child stdout/stderr. Parent SIGTERM/KeyboardInterrupt path must `terminate()`, bounded wait, `kill()` only if needed, then restore previous handlers.

- [ ] **Step 4: Implement Python wrapper with `subprocess.Popen`**

Unexpected child exit collapses to `WEIXIN_CONTEXT_MONITOR_FAILED` without raw stderr.

- [ ] **Step 5: Add CLI foreground branch**

Natural exit payload:

```json
{"schema_version":1,"command":"runtime.weixin-context","status":"ok","foreground":true}
```

- [ ] **Step 6: Add launchd/render contract**

Context plist receives:

```text
GUIYI_PROJECT_ROOT
GUIYI_RUNTIME_COMMIT
GUIYI_OPENCLAW_ROOT
GUIYI_ALERT_RECIPIENTS_PATH
```

Add `__OPENCLAW_ROOT__`, `__ALERT_RECIPIENTS_PATH__` placeholders. `install-local-services.sh` renders them; `--confirm-weixin-context` requires absolute non-empty values. Add `weixin-context)` to `run-local-service.sh`. `--render-only` never loads a service.

- [ ] **Step 7: Verify and commit**

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

git add services/quant-api/app/alerts/weixin_context.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin_context.py \
  deploy/launchd/com.guiyi.quant-weixin-context.plist.template scripts/ops/macos/install-local-services.sh \
  scripts/ops/macos/run-local-service.sh tests/engineering/test_weixin_context_launchd.py \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add notification-only context monitor"
```

---

### Task 6: Implement single-shot fan-out + structured canary

**Files:** modify `weixin.py`, adapter, CLI, Python/Node tests.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WeixinSendSummary:
    attempted: int
    provider_accepted: int
    failed: int
    failed_aliases: tuple[str, ...]

class WeixinAlertSender:
    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> WeixinSendSummary: ...
```

- [ ] **Step 1: Write Node fan-out red tests**

Four enabled recipients; member_3 rejects. Assert each eligible recipient gets at most one physical call and member_4 still runs. Missing context -> zero call for that recipient.

- [ ] **Step 2: Implement only direct plugin send**

Use `Promise.allSettled` and call only:

```javascript
await sendMessageWeixin({
  to: recipient.target,
  text,
  opts: { baseUrl: account.baseUrl, token: account.token, contextToken },
});
```

No `sendWeixinOutbound`, hooks, Gateway, queue, Agent, retry.

- [ ] **Step 3: Write Python sender tests**

One formatting pass + one child process per Alert; payload contains `document.enabled_recipients`; timeout/malformed/nonzero child output collapses; raw stderr never public; partial failure preserves all attempts.

- [ ] **Step 4: Implement sender semantics**

`send()` waits for full fan-out, then raises sanitized `WeixinSendError("WEIXIN_SEND_FAILED")` if `failed>0`; Runtime catches after Event commit. `send_canary()` returns summary for ordinary partial failure.

- [ ] **Step 5: Change canary CLI output contract**

Success:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"ok","attempted":4,"provider_accepted":4,"failed":0,"failed_aliases":[]}
```

Partial result goes to stdout with `status="failed"`, making `main()` return 1:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"failed","attempted":4,"provider_accepted":3,"failed":1,"failed_aliases":["member_3"]}
```

Never call this delivered/read evidence.

- [ ] **Step 6: Verify and commit**

```bash
node --test tests/engineering/openclaw_weixin_adapter.test.mjs
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py

git add services/quant-api/app/alerts/weixin.py services/quant-api/app/alerts/openclaw_weixin_adapter.mjs \
  services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_weixin.py \
  services/quant-api/tests/test_alert_cli.py tests/engineering/openclaw_weixin_adapter.test.mjs
git commit -m "feat(alert): add single-shot Weixin sender"
```

---

### Task 7: Rewire Alert startup + retire active WeCom

**Files:** modify composition/runtime/CLI/tests/Alert plist/installer; delete WeCom files.

**Interfaces:**

```python
def build_weixin_sender_from_env() -> WeixinAlertSender: ...
def build_alert_runtime() -> AlertRuntime: ...
```

- [ ] **Step 1: Add failing composition/CLI tests**

Replace missing-webhook cases with fail-closed missing registry/root/context-status cases. Canary must not create DB session or AlertRuntime.

- [ ] **Step 2: Add exact 90-second context freshness check**

Require schema1, `status="ok"`, `recipient_count == len(document.enabled_recipients)`, aware `last_poll_at`, age <=90s; all failure collapses to `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`.

- [ ] **Step 3: Rewire composition in fixed order**

```text
activation marker
→ operational products/taxonomy
→ registry document
→ monitor status
→ pinned dependency
→ adapter probe enabled recipients
→ Redis source/heartbeat
→ AlertRuntime(sender=WeixinAlertSender)
```

No Event/Scope/send in preflight.

- [ ] **Step 4: Inject identical private paths into Alert plist**

`com.guiyi.quant-alert.plist.template` must also receive `GUIYI_OPENCLAW_ROOT` and `GUIYI_ALERT_RECIPIENTS_PATH` from the same render placeholders as ContextMonitor.

- [ ] **Step 5: Make `--confirm-alert-runtime` load ContextMonitor before Alert**

Require both paths; load/reload context; wait <=90s for fresh privacy-safe status; only then load Alert; write alert marker only after both succeed. Failure leaves marker disabled.

- [ ] **Step 6: Delete WeCom active implementation/tests**

Delete the two files and active imports/config/canary factory.

- [ ] **Step 7: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py services/quant-api/tests/test_alert_recipient_registry.py \
  services/quant-api/tests/test_alert_weixin.py services/quant-api/tests/test_alert_weixin_context.py \
  services/quant-api/tests/test_alert_runtime.py services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_weixin_context_launchd.py

git add -A services/quant-api/app/alerts services/quant-api/app/guiyi_cli/main.py services/quant-api/tests \
  deploy/launchd/com.guiyi.quant-alert.plist.template scripts/ops/macos/install-local-services.sh \
  tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_weixin_context_launchd.py
git commit -m "feat(alert): switch develop transport to iLink"
```

---

### Task 8: Add OpenClaw tooling/status, update canonicals, run full verification

**Files:** create `deploy/openclaw/README.md`, create install helper, modify local status + active canonicals/testing.

**Interfaces:**

```text
install-openclaw-weixin-tools.sh --check          # read-only
install-openclaw-weixin-tools.sh --confirm-install # D2-only external mutation entry
```

- [ ] **Step 1: Write tooling/status engineering tests**

`--check` with absent tools emits `status=not_installed` and exits 0. Fixture-installed state verifies versions/paths. It never npm-installs, logs in, launches Gateway, calls launchctl, or sends.

Status output may include:

```text
external.openclaw.version=2026.8.1
external.openclaw_weixin.version=2.4.6
weixin_context.loaded=...
weixin_context.status=...
```

No account/target fields.

- [ ] **Step 2: Implement `--check`**

Read `versions.json`; inspect only fixed root from `GUIYI_OPENCLAW_ROOT`; absent tools are not an error before D2.

- [ ] **Step 3: Implement externally gated `--confirm-install` entry**

Require absolute `GUIYI_OPENCLAW_ROOT` beginning `/Volumes/`. Exact operations:

```text
create runtime/state/cache/npm/tmp under root; state/root private dirs 0700
fetch official OpenClaw install-cli.sh to a temporary file
run: install-cli.sh --prefix <root>/runtime --version 2026.8.1 --node-version 24.15.0 --no-onboard
set exact OPENCLAW_PREFIX/STATE_DIR/CONFIG_PATH/CONFIG/npm_config_cache/TMPDIR
run: <root>/runtime/bin/openclaw plugins install npm:@tencent-weixin/openclaw-weixin@2.4.6 --pin
run: <root>/runtime/bin/openclaw config set plugins.entries.openclaw-weixin.enabled true
```

Never run Gateway, channels login, message send, launchctl, guiyi Runtime switch, or onboarding. This code path is tested with fake commands only in D1 and invoked for real only under D2.

- [ ] **Step 4: Extend `local-services-status.sh`**

Keep external dependency version identity separate from guiyi commit identity. If Alert marker enabled, ContextMonitor becomes required and must be fresh. Never introduce an OpenClaw Gateway label.

- [ ] **Step 5: Update `TESTING.md`**

Replace WeCom test entry with notification/registry/weixin/context tests and add Node adapter tests, install helper `--check`, launchd render-only. State explicitly that real install/login/registration/canary/context-load/Alert-load/release/promotion are not test permissions.

- [ ] **Step 6: Update `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md` without falsifying production**

Record develop's approved notification-only iLink architecture and no-Gateway/no-retry rules. Preserve that `STATUS.md` is authoritative for current v1.4.2 production WeCom Runtime until D8/D9. Existing WeCom continuous authorization does not authorize iLink.

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

Expected: all exit 0; secret scan 0 findings; no external mutation.

- [ ] **Step 8: Review active references/scope**

```bash
git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services scripts deploy TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true

git diff --stat develop...HEAD
git diff develop...HEAD -- \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli services/quant-api/tests \
  deploy/openclaw deploy/launchd scripts/ops/macos TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md
```

Verify no evaluator formula, Scope, migration, DB schema, Canonical, order path, `main`, tag, or Runtime worktree change.

- [ ] **Step 9: Commit**

```bash
git add deploy/openclaw scripts/ops/macos/install-openclaw-weixin-tools.sh \
  scripts/ops/macos/local-services-status.sh TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md tests/engineering
git commit -m "docs(alert): define iLink notification operations"
```

---

## D1 Completion Gate

Fresh evidence must support all items:

```text
PASS no real external operation executed
PASS no OpenClaw Gateway in runtime design
PASS inbound cannot enter Agent/LLM/slash/tool pipeline
PASS registration exact-challenge and monitor-exclusive
PASS registry read-modify-write preserves disabled records
PASS registration preserves CLI JSON via dedicated TTY/prompt stream
PASS all Node children receive exact expansion-disk OpenClaw state/config environment
PASS context monitor retry policy can never create outbound messages
PASS context-monitor parent forwards termination to child
PASS Alert and ContextMonitor receive identical private paths
PASS alert-canary reports aggregate provider acceptance and exits nonzero on partial failure
PASS each AlertEvent×recipient has at most one physical send attempt
PASS committed Event survives notification failure
PASS no notification retry/replay/backfill/outbox/queue
PASS no DB migration/schema/Scope/evaluator/order change
PASS active WeCom code retired on develop
PASS production v1.4.2 WeCom Runtime not mutated/falsified in STATUS.md
```

If all pass: **允许集成 develop**. D2-D9 remain blocked behind `2026-08-18-weixin-ilink-notification-rollout.md` and fresh user Gates.