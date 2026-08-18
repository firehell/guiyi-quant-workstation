# Clawbot Single-Shot Alert Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all active WeChat-Courier notification code on `develop` with one Clawbot/OpenClaw-Weixin single-shot sender that preserves Alert Event-first, no-retry, at-most-one physical send semantics, while keeping current production `v1.4.2` + WeCom untouched until rollout.

**Architecture:** Keep `AlertNotificationMessage`, `AlertNotificationSender` and the existing formatters as the stable domain boundary. Discover the user's already-installed OpenClaw/Node/openclaw-weixin exact versions first, freeze only those version/module-shape facts in Git, then use one private `.mjs` seam to read the existing Clawbot account/context state and call Tencent `sendMessageWeixin()` at most once. Guiyi never calls `openclaw message send`, never owns OpenClaw login/inbound/Gateway lifecycle, and never creates a notification queue/retry path.

**Tech Stack:** Python 3.13 project runtime, Node.js from the user's existing OpenClaw installation, OpenClaw CLI, Tencent `@tencent-weixin/openclaw-weixin`, subprocess/stdin JSON, macOS launchd, pytest, node:test.

**Spec:** `docs/superpowers/specs/2026-08-18-clawbot-single-shot-notification-design.md`

## Global Constraints

- Code baseline is `develop` at/after `e8337b80b8fcde9968e67b71a7d80b1068983d83`; if `develop` moves, re-read the delta before implementation.
- Current production stays exact-tag `v1.4.2` / `fb96506493763340e082ed85e8112b60d6670d65` and keeps WeCom until rollout Gate G8. D1 must not send WeCom or Clawbot messages and must not switch Runtime.
- D1 is repository work plus G1 read-only local dependency discovery only. No OpenClaw install/update/enable/disable/login/logout/config write, no owner config write, no canary, no launchd load/reload, no release/main/tag.
- Preserve `htdy_original_15m`, `subing_entry_signal_v1`, their evaluator semantics and current Scope, Alert two-table schema/Event identity, DB revision, Market eight-table contract, Canonical, Execution Review, and `auto_order=false`.
- Preserve Event-first: Event commit happens before notification attempt; notification failure never rolls back an Event.
- For every new `AlertEvent × owner`: bridge child process count `<= 1`; `sendMessageWeixin()` call count `<= 1`; context missing means physical send `= 0`.
- No notification retry, replay, backfill, outbox, queue, provider fallback, WeCom fallback, Courier fallback, Gateway send, OpenClaw `message send`, Agent/tool send, or broadcast.
- V1 recipient is exactly one alias: `owner`; no recipient list, fan-out, routing DSL, recipient DB or per-rule recipient routing.
- Real `account_id`, `target_user_id`, bot token, context token, real message body and OpenClaw raw logs must never enter Git, public CLI output, Guiyi logs or task reports.
- The only file allowed to know Tencent private module paths/exports is `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`.
- Tests use fake plugin roots, fake account/context modules, temp private config and mocked subprocesses. D1 must never touch the real owner's private account/context values after G1 discovery has finished.

---

## File Structure Locked by This Plan

### Preserve

- `services/quant-api/app/alerts/notification.py`
- `services/quant-api/app/alerts/runtime.py` transport-neutral `AlertNotificationSender` dependency
- `services/quant-api/tests/test_alert_notification.py`

### Create

- `deploy/clawbot/versions.json`
- `deploy/clawbot/README.md`
- `services/quant-api/app/alerts/clawbot_owner.py`
- `services/quant-api/app/alerts/clawbot.py`
- `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`
- `services/quant-api/tests/test_alert_clawbot_owner.py`
- `services/quant-api/tests/test_alert_clawbot.py`
- `tests/engineering/openclaw_weixin_single_shot.test.mjs`

### Modify

- `services/quant-api/app/alerts/composition.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/app/services/runtime_health.py`
- `services/quant-api/tests/test_alert_cli.py`
- `services/quant-api/tests/test_alert_runtime.py`
- `services/quant-api/tests/test_runtime_health.py`
- `deploy/launchd/com.guiyi.quant-api.plist.template`
- `deploy/launchd/com.guiyi.quant-alert.plist.template`
- `scripts/ops/macos/install-local-services.sh`
- `scripts/ops/macos/run-local-service.sh`
- `scripts/ops/macos/local-services-status.sh`
- `tests/engineering/test_alert_runtime_launchd.py`
- `tests/engineering/test_market_runtime_launchd.py`
- `tests/engineering/test_secret_scan.py` as needed for Clawbot private-data regression coverage
- `AGENTS.md`
- `PROJECT_SOURCE.md`
- `DECISIONS.md`
- `TESTING.md`
- `deploy/README.md`
- `STATUS.md` only to record a truthful `develop / not released` Clawbot target; current production `v1.4.2 + WeCom` facts must remain unchanged.

### Delete after Clawbot replacement is green

- `services/quant-api/app/alerts/wechat_courier.py`
- `services/quant-api/app/alerts/wechat_courier_adapter.py`
- `services/quant-api/app/alerts/wechat_group_config.py`
- `services/quant-api/tests/test_alert_wechat_courier.py`
- `services/quant-api/tests/test_alert_wechat_group_config.py`
- `tests/engineering/test_wechat_courier_adapter.py`
- `tests/engineering/test_wechat_courier_ops.py`
- `deploy/wechat-courier/README.md`
- `deploy/wechat-courier/versions.json`
- `scripts/ops/macos/install-wechat-courier.sh`

The old Courier design/code/rollout docs were already deleted before this plan. Historical WeCom/Courier evidence remains in Git history/STATUS history only.

---

## Gate G1: Read-Only Discovery of the Existing Clawbot Installation

**Lane:** Lane 2 read-only external inspection.

**Purpose:** establish execution-time facts required to freeze D1 compatibility. This Gate changes no files outside the task branch until the final sanitized `deploy/clawbot/versions.json` commit.

- [ ] **Step 1: Record repository and production truth**

Run:

```bash
git fetch origin develop
git switch develop
git pull --ff-only
git rev-parse HEAD
git status --short
scripts/ops/macos/local-services-status.sh
```

Expected before any Clawbot code work: production remains the supervised exact-tag `v1.4.2` Runtime and reports WeCom. If production/runtime truth is inconsistent with `STATUS.md`, stop before D1.

- [ ] **Step 2: Resolve exact local executables without mutating OpenClaw**

Run:

```bash
OPENCLAW_BIN="$(command -v openclaw)"
NODE_BIN="$(command -v node)"
[ -n "$OPENCLAW_BIN" ] && [ -x "$OPENCLAW_BIN" ]
[ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]
"$OPENCLAW_BIN" --version
"$NODE_BIN" --version
"$OPENCLAW_BIN" config file --json
"$OPENCLAW_BIN" plugins inspect openclaw-weixin --runtime --json
"$OPENCLAW_BIN" channels status --channel openclaw-weixin --probe --json
```

Do not run any OpenClaw writer (`plugins install/update/enable/disable`, `config set/patch/unset`, `channels login/logout/add/remove`, `message send`).

- [ ] **Step 3: Parse only the non-secret compatibility facts**

From `plugins inspect ... --json`, require exactly one `openclaw-weixin` plugin with status `loaded`, an exact version string, and one exact install path. Resolve the install path with `realpath` and require it to be a directory. Record only:

```text
openclaw exact version
node exact version
openclaw-weixin exact version
resolved plugin root path (local task evidence only, never tracked)
```

Do not copy the plugin JSON wholesale into the task report because install/account diagnostics may contain local information.

- [ ] **Step 4: Resolve the active config/state paths without guessing**

Use `openclaw config file --json` for the exact config path. For state dir:

1. if `OPENCLAW_STATE_DIR` is explicitly set, require an absolute existing directory and use its resolved realpath;
2. otherwise, accept the config file's parent only if the expected Tencent state subtree for the installed plugin exists there and can be verified structurally without printing account contents;
3. otherwise stop with `G1 BLOCKED: OPENCLAW_STATE_DIR_NOT_DETERMINISTIC` and ask the user for the exact state directory. Do not assume `~/.openclaw` merely because it is the upstream default.

- [ ] **Step 5: Verify the installed private module shape read-only**

Under the exact plugin root, require the installed compiled modules used by the approved seam. For the currently published package this is expected to be:

```text
dist/src/auth/accounts.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

Run one read-only Node import probe that asserts these exact exports exist:

```text
loadWeixinAccount
restoreContextTokens
getContextToken
sendMessageWeixin
```

If the observed installed version has a different compiled layout, stop and revise the spec/plan before implementation. Do not glob for alternates or fall back to `src/*.ts`.

- [ ] **Step 6: Create an isolated task branch/worktree from the just-read `develop`**

Use `superpowers:using-git-worktrees`. The branch should be notification-specific, for example:

```text
task/clawbot-single-shot-notification
```

No implementation changes belong directly on the user's main develop worktree.

**G1 PASS evidence:** exact OpenClaw/Node/plugin versions, exact plugin root, exact config/state paths, plugin loaded/probe healthy, exact private export shape. Evidence must be sanitized and contain no account/user/token/context values.

---

### Task 1: Freeze the Observed Compatibility Contract and Owner File Schema

**Files:**
- Create: `deploy/clawbot/versions.json`
- Create: `deploy/clawbot/README.md`
- Create: `services/quant-api/app/alerts/clawbot_owner.py`
- Create: `services/quant-api/tests/test_alert_clawbot_owner.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ClawbotOwner:
    version: int
    channel: str
    owner_alias: str
    account_id: str
    target_user_id: str

class ClawbotOwnerError(RuntimeError): ...

def load_clawbot_owner(path: Path) -> ClawbotOwner: ...

def write_clawbot_owner_atomic(path: Path, *, account_id: str, target_user_id: str) -> None: ...
```

Constants:

```python
CLAWBOT_OWNER_VERSION = 1
CLAWBOT_CHANNEL = "openclaw-weixin"
CLAWBOT_OWNER_ALIAS = "owner"
```

- [ ] **Step 1: Write `deploy/clawbot/versions.json` from G1 facts**

The file contains only exact non-secret compatibility facts observed in G1, plus exact private module relative paths verified in G1. Required schema:

```json
{
  "schema_version": 1,
  "openclaw_version": "the exact G1 stdout version string",
  "openclaw_weixin_version": "the exact G1 plugin version string",
  "node_version": "the exact G1 node version string",
  "plugin_modules": {
    "accounts": "dist/src/auth/accounts.js",
    "inbound": "dist/src/messaging/inbound.js",
    "send": "dist/src/messaging/send.js"
  }
}
```

Do not track local absolute install paths, account ids, user ids, tokens or context values.

- [ ] **Step 2: Write owner-loader RED tests**

Cover:

```text
missing file
symlink
non-regular file
parent mode != 0700
file mode != 0600
parent uid != current uid
file uid != current uid
malformed JSON
missing/extra key
version != 1
channel != openclaw-weixin
owner_alias != owner
blank/control-character account_id
blank/control-character target_user_id
target_user_id not ending @im.wechat
```

Use only synthetic values such as `fixture-owner@im.wechat`.

- [ ] **Step 3: Implement strict immutable owner loading**

Use `lstat()`, exact mode and UID checks. Errors collapse to stable `CLAWBOT_OWNER_INVALID` and never interpolate private values or paths.

- [ ] **Step 4: Add an atomic owner writer for later rollout**

`write_clawbot_owner_atomic()` must:

```text
require parent already exists and is 0700/current uid
validate candidate ids before writing
write a temp file in the same parent
chmod temp 0600
fsync temp
os.replace(temp, final)
chmod final 0600
re-load with load_clawbot_owner() as postcondition
```

It must not be executed against the real production path during D1.

- [ ] **Step 5: Verify and commit**

Run the focused owner tests and `git diff --check`, then commit only Task 1 files.

---

### Task 2: Implement the One Tencent Private Seam (`discover_owner`, `probe`, `send`)

**Files:**
- Create: `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`
- Create: `tests/engineering/openclaw_weixin_single_shot.test.mjs`

**Interfaces:**

The seam reads one JSON object from stdin. It receives local dependency paths via explicit environment, not argv.

Allowed actions:

```text
discover_owner  # read-only bootstrap helper, zero send
probe           # owner/account/context readiness, zero send
send            # one text send attempt maximum
```

The added `discover_owner` action is the implementation clarification required by the approved owner-bootstrap section: it stays inside the same single private seam and never creates a second notification path.

- [ ] **Step 1: Build a fake plugin tree for node:test**

The fixture provides the exact three compiled module files named by `versions.json` and records calls to:

```text
loadWeixinAccount
restoreContextTokens
getContextToken
sendMessageWeixin
```

No network or real OpenClaw import is allowed in D1 tests.

- [ ] **Step 2: Write RED tests for dependency/path safety**

Require:

```text
plugin root absolute and existing
manifest schema exact
package.json version == frozen plugin version
all manifest module paths resolve under plugin root
all required exports are functions
no glob/fallback/private source TS imports
```

Missing or mismatched dependency => `CLAWBOT_DEPENDENCY_INVALID`, zero send.

- [ ] **Step 3: Write RED tests for `discover_owner`**

Contract:

```text
exactly one indexed/configured account
loadWeixinAccount(account)
account token present
account.userId exists and ends @im.wechat
restoreContextTokens(account)
getContextToken(account, account.userId) returns non-empty
candidate count exactly one
```

The child may return the private `account_id`/`target_user_id` only in its captured machine payload to the trusted Python parent. The public CLI must never echo those fields. Tests must prove child stderr never contains them.

Multiple accounts, zero accounts, missing user id, missing context, malformed account => fail closed and zero send.

- [ ] **Step 4: Write RED tests for `probe`**

Inputs include the frozen owner ids. Require:

```text
load exact account
configured token exists
account.userId == target_user_id
restore contexts
context exists
sendMessageWeixin calls == 0
```

Missing context => `CLAWBOT_CONTEXT_UNAVAILABLE` and zero send.

- [ ] **Step 5: Write RED tests for `send`**

Require:

```text
same dependency/account/context checks as probe
sendMessageWeixin called exactly once on success
sendMessageWeixin throw => exactly one call, CLAWBOT_SEND_FAILED
context missing => zero calls
no loop/re-spawn/retry path inside child
```

- [ ] **Step 6: Implement minimal ESM seam**

Use `fs`, `path`, `url` and dynamic `import(pathToFileURL(...))`. Resolve every manifest module realpath under the exact plugin root. Do not import `channel.ts/channel.js`, `sendWeixinOutbound`, OpenClaw core message functions, hooks, Gateway or Agent code.

The send call must be exactly the low-level Tencent API:

```javascript
await sendMessageWeixin({
  to: targetUserId,
  text,
  opts: { baseUrl: account.baseUrl || DEFAULT_BASE_URL_IF_EXACTLY_AVAILABLE_FROM_ACCOUNT_MODULE,
          token: account.token,
          contextToken }
})
```

If the frozen installed account module does not expose a safe exact base URL contract, stop and adjust the private seam from the observed installed module; never guess.

- [ ] **Step 7: Sanitize child output**

Normal public machine results for `probe/send` are stable codes only. `discover_owner` sensitive fields are for captured parent consumption only; parent tests must prove they never reach user-visible stdout/stderr/logging.

- [ ] **Step 8: Run node tests and commit**

Run:

```bash
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
```

Expected: all pass with fake modules only.

---

### Task 3: Add Python Clawbot Runner, Sender, Bootstrap and Canary Contracts

**Files:**
- Create: `services/quant-api/app/alerts/clawbot.py`
- Create: `services/quant-api/tests/test_alert_clawbot.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ClawbotDependency:
    openclaw_bin: Path
    node_bin: Path
    plugin_root: Path
    state_dir: Path
    config_path: Path
    owner_path: Path
    versions_path: Path

@dataclass(frozen=True, slots=True)
class ClawbotSendSummary:
    attempted: int
    provider_accepted: int
    failed: int
    failed_aliases: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ClawbotOwnerCandidate:
    account_id: str
    target_user_id: str

class ClawbotError(RuntimeError): ...

class ClawbotRunner:
    def discover_owner(self) -> ClawbotOwnerCandidate: ...
    def probe(self, owner: ClawbotOwner) -> None: ...
    def send_text(self, owner: ClawbotOwner, text: str) -> None: ...

class ClawbotAlertSender:
    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> ClawbotSendSummary: ...
```

- [ ] **Step 1: Write RED dependency/runner tests**

Parent process must use fixed argv only:

```python
[node_bin, PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs"]
```

All action/account/target/text data goes through stdin JSON. Tests inspect argv and assert no `@im.wechat`, account id or message body appears there.

Child environment is rebuilt from an allowlist. At minimum it sets:

```text
OPENCLAW_STATE_DIR=<exact configured state dir>
OPENCLAW_CONFIG=<exact config path>
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT=<exact plugin root>
GUIYI_CLAWBOT_VERSIONS_PATH=<exact manifest>
PATH=<node parent dir>:/usr/bin:/bin:/usr/sbin:/sbin
```

Do not blindly inherit conflicting `OPENCLAW_*`/`CLAWDBOT_*`.

- [ ] **Step 2: Implement one-child-at-most runner semantics**

Each `discover_owner`, `probe` or `send_text` call invokes `subprocess.run()` once with a finite timeout. Timeout, crash, malformed JSON or nonzero exit returns a stable Clawbot error and never creates a second child.

- [ ] **Step 3: Write sender RED tests**

Prove:

```text
format_alert_message called through existing formatter
one sender call -> one runner.send_text
runner failure propagates sanitized Clawbot error
send_canary uses fixed ALERT_CANARY_TEXT
success summary attempted=1/provider_accepted=1/failed=0
failure summary attempted=1/provider_accepted=0/failed=1/failed_aliases=("owner",)
```

- [ ] **Step 4: Add CLI surfaces with no arbitrary send primitive**

Replace Courier-only `alert-target-verify` with:

```text
guiyi runtime clawbot-owner-bootstrap [--confirm-write-owner]
guiyi runtime clawbot-preflight
guiyi runtime alert-canary
```

Contracts:

`clawbot-owner-bootstrap` without confirm:

```json
{
  "schema_version": 1,
  "command": "runtime.clawbot-owner-bootstrap",
  "status": "ready",
  "readonly": true,
  "channel": "openclaw-weixin",
  "owner_alias": "owner",
  "account_count": 1,
  "owner_candidate_count": 1,
  "context_available": true,
  "owner_written": false
}
```

With `--confirm-write-owner`, the command uses the same unique candidate and `write_clawbot_owner_atomic()`, returns `readonly=false`, and still does not expose ids. D1 tests use a temp file only; the real production path is rollout-only.

`clawbot-preflight`:

```json
{
  "schema_version": 1,
  "command": "runtime.clawbot-preflight",
  "status": "ok",
  "readonly": true,
  "channel": "openclaw-weixin",
  "owner_alias": "owner",
  "account_configured": true,
  "context_available": true,
  "would_send": false
}
```

`alert-canary` keeps the generic command but changes its result field from Courier's `automation_completed` to:

```text
attempted
provider_accepted
failed
failed_aliases
```

No CLI may accept `--target`, `--account`, `--message` or free-form text for Clawbot sends.

- [ ] **Step 5: Fix readonly classification tests**

Expected:

```text
runtime status -> true
runtime clawbot-owner-bootstrap (discovery) -> true
runtime clawbot-owner-bootstrap --confirm-write-owner -> false
runtime clawbot-preflight -> true
runtime live/alert/alert-canary -> false
```

- [ ] **Step 6: Verify and commit**

Run focused Python tests and node tests before commit.

---

### Task 4: Rewire Alert Composition and Health Without Changing Alert Semantics

**Files:**
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`

**Interfaces:**

```python
def build_clawbot_sender_from_env(*, live_probe: bool = True) -> ClawbotAlertSender: ...

def clawbot_transport_configured_from_env() -> bool: ...
```

- [ ] **Step 1: Write RED composition tests**

Require all six explicit path inputs:

```text
GUIYI_OPENCLAW_BIN
GUIYI_OPENCLAW_NODE_BIN
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
GUIYI_OPENCLAW_STATE_DIR
GUIYI_OPENCLAW_CONFIG_PATH
GUIYI_ALERT_CLAWBOT_OWNER_PATH
```

Reject missing/relative/nonexistent/incorrect file type, unsupported manifest version, exact version mismatch or plugin inspect mismatch with `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`. Do not expose raw local paths in public errors.

- [ ] **Step 2: Implement two-level preflight**

`live_probe=False` checks only structural/local compatibility for HTTP health and must not call Tencent network APIs or send.

`live_probe=True` additionally loads the immutable owner and runs exactly one `runner.probe(owner)` before returning the sender. This is used by Alert Runtime startup, `clawbot-preflight` and canary construction.

- [ ] **Step 3: Rewire `build_alert_runtime()`**

Replace `build_wechat_group_sender_from_env()` with `build_clawbot_sender_from_env(live_probe=True)`. Keep evaluator, Redis source/heartbeat, operational products, taxonomy and session factories unchanged.

- [ ] **Step 4: Preserve Event-first/no-retry regression tests**

Tests must prove:

```text
DB/Event creation failure -> sender calls 0
new Event commit -> sender call 1
duplicate Event -> sender calls 0
sender failure -> Event remains committed
sender failure -> no second sender call and next Bar can still process
old failed Event is never replayed/backfilled
```

- [ ] **Step 5: Make runtime health structural only**

`build_runtime_health()` should use `clawbot_transport_configured_from_env()` or `build_clawbot_sender_from_env(live_probe=False)` and must not call `send`, bootstrap owner, mutate context or invoke `channels status --probe` on every HTTP request.

- [ ] **Step 6: Verify and commit**

Run Alert runtime/composition/health focused tests.

---

### Task 5: Replace Courier Ops/Launchd Identity With External Clawbot Identity

**Files:**
- Modify: `deploy/launchd/com.guiyi.quant-api.plist.template`
- Modify: `deploy/launchd/com.guiyi.quant-alert.plist.template`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `scripts/ops/macos/run-local-service.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`
- Modify: `tests/engineering/test_market_runtime_launchd.py`

- [ ] **Step 1: Replace launchd Courier vars**

API and Alert plist templates must carry the same six Clawbot path variables. No real account/user/token/context belongs in launchd.

- [ ] **Step 2: Preserve launcher-authority precedence**

Extend the existing `run-local-service.sh` protection so non-empty launchd values for all six Clawbot path variables survive `project.env/.env` sourcing. Do not alter precedence for unrelated secrets.

- [ ] **Step 3: Update render/install fail-closed checks**

`install-local-services.sh --confirm-alert-runtime` must validate the required Clawbot paths and the already-installed API plist's six values before writing the Alert marker or invoking `launchctl`. Any API/Alert mismatch => failure before mutation.

No script may install/update/restart OpenClaw.

- [ ] **Step 4: Replace status channel detection**

`local-services-status.sh` identifies the supervised Runtime source tree:

```text
wecom.py only -> wecom
clawbot.py only, no wecom/courier -> clawbot-openclaw-weixin
ambiguous/none -> unknown
```

For Clawbot Runtime, print only sanitized external dependency facts:

```text
alert.notification_channel=clawbot-openclaw-weixin
alert.notification_owner_alias=owner
external.openclaw.status=ready|invalid|missing
external.openclaw.version=<non-secret exact>
external.openclaw_weixin.status=ready|invalid|missing
external.openclaw_weixin.version=<non-secret exact>
external.clawbot_owner_config=ready|invalid|missing
```

Never print account id, target user id, bot/context token, plugin raw JSON or message text. Never compare OpenClaw/plugin identity to `GUIYI_RUNTIME_COMMIT`.

Legacy v1.4.2 WeCom Runtime must still pass status even when Clawbot variables are absent.

- [ ] **Step 5: Add engineering tests**

Cover legacy WeCom, new Clawbot, ambiguous source identity, missing dependency, mismatched API/Alert paths, launcher precedence and sanitized status output.

- [ ] **Step 6: Verify and commit**

Run engineering tests, shell `bash -n`, render-only launchd and `plutil -lint` only. Do not load services.

---

### Task 6: Delete Courier Active Source, Close Canonicals, and Run Full Verification

**Files:** delete/modify the paths listed in the File Structure section.

- [ ] **Step 1: Delete Courier-only source/tests/tooling**

Delete exactly the Courier files listed above. Remove `alert-target-verify`, Courier env vars, Courier installer/version manifest and Courier status logic. Do not delete unrelated historical evidence.

- [ ] **Step 2: Verify active WeCom source remains zero on `develop`**

In active source/config/tests, the following must not reappear:

```text
WeComWebhookSender
build_wecom_sender_from_env
WECOM_WEBHOOK_URL
qyapi.weixin.qq.com
```

`STATUS.md` historical/current production paragraphs may still truthfully say WeCom until rollout G8.

- [ ] **Step 3: Update canonicals truthfully**

Document:

```text
develop notification target = Clawbot single-shot / not released
production exact-tag = v1.4.2 + WeCom until G8
OpenClaw/Clawbot = external existing infrastructure, not Guiyi-supervised
no public OpenClaw message send/durable queue in Alert path
```

Do not claim owner bootstrap, canary, release or Runtime promotion happened during D1.

- [ ] **Step 4: Run secret/privacy scans**

Run the repository secret scan and explicit diffs/grep. Test fixtures may contain obvious synthetic `fixture-owner@im.wechat`; no real opaque ids may appear.

- [ ] **Step 5: Run full D1 verification**

At minimum:

```bash
python3 scripts/engineering/secret_scan.py --json

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_clawbot_owner.py \
  services/quant-api/tests/test_alert_clawbot.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py

node --test tests/engineering/openclaw_weixin_single_shot.test.mjs

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_market_runtime_launchd.py \
  tests/engineering/test_secret_scan.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check services/quant-api/app services/quant-api/tests

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api mypy services/quant-api/app

bash -n scripts/ops/macos/install-local-services.sh
bash -n scripts/ops/macos/run-local-service.sh
bash -n scripts/ops/macos/local-services-status.sh

scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-api.plist
plutil -lint .run/launchd/com.guiyi.quant-alert.plist

git diff --check
```

Also run the project's normal broader Alert/backend regression set if the task branch changed shared CLI/ops files beyond the focused scope.

- [ ] **Step 6: Run forbidden-path checks**

Active production files must not contain calls to:

```text
openclaw message send
sendDurableMessageBatchCore
Gateway send
wechat_courier
GUIYI_WECHAT_COURIER_ROOT
GUIYI_ALERT_WECHAT_GROUP_PATH
alert-target-verify
```

The tests may contain literal forbidden strings only to assert rejection; scope grep accordingly rather than deleting the tests.

- [ ] **Step 7: Independent Review**

Open a fresh review session and inspect, at minimum:

1. `sendMessageWeixin` physical call count can never exceed one per sender invocation;
2. missing context is zero-send;
3. child timeout/crash/malformed output cannot re-spawn;
4. no OpenClaw public `message send`/durable queue path slipped in;
5. `discover_owner` cannot leak ids to CLI/logs;
6. owner config cannot hot reload into a running sender;
7. Alert Event is committed before notification and survives failure;
8. evaluator/Scope/DB/Canonical/order paths are unchanged;
9. API/Alert launchd path identities match and launcher values win;
10. status reports supervised Runtime truth and keeps legacy v1.4.2 WeCom truthful;
11. no real OpenClaw mutation/send/runtime switch happened during D1.

**R1 PASS:** Critical=`0`, Important=`0`; all required verification passes.

- [ ] **Step 8: Integrate task branch to `develop` only after R1 PASS**

Fast-forward/merge according to repository workflow, re-read `origin/develop`, then clean the task worktree/merged task branch. Do not touch `main`, tag or production Runtime.

---

## D1 Completion Gate

D1 is complete only when all of these are true:

```text
G1 exact installed dependency facts captured and frozen
Clawbot single-shot source is the only active develop notification transport
WeChat-Courier active source/tests/tooling = 0
active WeCom sender source/config = 0 on develop
production v1.4.2 + WeCom unchanged
clawbot-owner-bootstrap code exists but real owner file not written
clawbot-preflight code exists but no real external call executed by D1 tests
alert-canary code exists but no real message sent
Event-first/no-retry/at-most-one verified
secret/privacy tests pass
Critical=0 / Important=0 independent review
```

Final D1 verdict:

```text
D1 CLAWBOT CODE PASS，允许进入 rollout G2 owner bootstrap
```

or

```text
D1 CLAWBOT CODE BLOCKED，禁止进入真实 owner/canary
```
