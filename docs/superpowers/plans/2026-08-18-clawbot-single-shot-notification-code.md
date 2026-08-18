# Clawbot Single-Shot Alert Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all active WeChat-Courier notification code on `develop` with one Clawbot/OpenClaw-Weixin single-shot sender that preserves Alert Event-first, no-retry, at-most-one physical send semantics, while keeping current production `v1.4.2` + WeCom untouched until rollout.

**Architecture:** Keep `AlertNotificationMessage`, `AlertNotificationSender` and the existing formatters as the stable domain boundary. First perform read-only discovery of the user's already-installed OpenClaw, Node and `openclaw-weixin`; freeze only their exact non-secret compatibility facts. Then use one private `.mjs` seam to read existing Clawbot account/context state and call Tencent `sendMessageWeixin()` at most once. Guiyi never calls `openclaw message send`, never owns OpenClaw login/inbound/Gateway lifecycle, and never creates a notification queue/retry path.

**Tech Stack:** Python 3.13 project runtime, the existing local Node/OpenClaw installation, Tencent `@tencent-weixin/openclaw-weixin`, subprocess/stdin JSON, macOS launchd, pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-08-18-clawbot-single-shot-notification-design.md`

## Global Constraints

- Baseline is `develop` at/after `e8337b80b8fcde9968e67b71a7d80b1068983d83`; if `develop` moves, re-read the delta before implementation.
- Current production remains exact-tag `v1.4.2` / `fb96506493763340e082ed85e8112b60d6670d65` + WeCom until rollout G8. D1 must not send WeCom or Clawbot messages and must not switch Runtime.
- D1 is repository work plus G1 read-only local dependency discovery. No OpenClaw install/update/enable/disable/login/logout/config write, no real owner-config write, no canary, no launchd load/reload, no main/tag/release.
- Preserve `htdy_original_15m`, `subing_entry_signal_v1`, evaluator semantics, current Scope, Alert two-table schema/Event identity, DB revision, Market eight-table contract, Canonical, Execution Review and `auto_order=false`.
- Preserve Event-first: Event commit precedes notification attempt; notification failure never rolls back an Event.
- For every new `AlertEvent × owner`: bridge child count `<=1`; `sendMessageWeixin()` call count `<=1`; missing context means physical send `=0`.
- No notification retry, replay, backfill, outbox, queue, provider fallback, WeCom fallback, Courier fallback, Gateway send, OpenClaw `message send`, Agent/tool send or broadcast.
- V1 recipient is exactly `owner`; no recipient list, fan-out, routing DSL, recipient DB or per-rule recipient routing.
- Real `account_id`, `target_user_id`, bot token, context token, real message body and raw OpenClaw/Tencent logs never enter Git, public CLI output, Guiyi logs or task reports.
- The only file allowed to know Tencent private module paths/exports is `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`.
- D1 tests use fake plugin roots/modules, temp private config and mocked subprocesses. After G1 compatibility discovery, D1 tests must not read the real owner's account/context contents.

---

## File Structure

### Preserve

- `services/quant-api/app/alerts/notification.py`
- `services/quant-api/app/alerts/runtime.py` transport-neutral sender dependency
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
- `tests/engineering/test_secret_scan.py` if required for Clawbot privacy regression coverage
- `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `TESTING.md`, `deploy/README.md`
- `STATUS.md` only to state the truthful `develop / not released` target; existing production v1.4.2/WeCom facts remain.

### Delete after replacement tests are green

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

The old Courier design/code/rollout docs were already deleted. Historical WeCom/Courier facts remain only in Git history and truthful historical/status text.

---

## Gate G1 — Read-Only Discovery of the Existing Clawbot Installation

**Lane:** Lane 2 read-only external inspection.

- [ ] **Step 1: Read repository and production truth**

```bash
git fetch origin develop
git switch develop
git pull --ff-only
git rev-parse HEAD
git status --short
scripts/ops/macos/local-services-status.sh
```

Expected before D1: supervised production is still exact-tag v1.4.2 and reports WeCom. If production truth conflicts with `STATUS.md`, stop.

- [ ] **Step 2: Resolve exact local executables and official read-only OpenClaw surfaces**

```bash
OPENCLAW_BIN="$(command -v openclaw)"
NODE_BIN="$(command -v node)"
[ -n "$OPENCLAW_BIN" ] && [ -x "$OPENCLAW_BIN" ]
[ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]
"$OPENCLAW_BIN" --version
"$NODE_BIN" --version
"$OPENCLAW_BIN" config file
"$OPENCLAW_BIN" plugins inspect openclaw-weixin --runtime --json
```

Forbidden in G1: `plugins install/update/enable/disable`, `config set/patch/unset`, `channels login/logout/add/remove`, `message send` or any OpenClaw writer.

- [ ] **Step 3: Parse only non-secret compatibility facts**

Require exactly one loaded `openclaw-weixin` plugin with one exact version and one exact install path. Resolve its install path with `realpath`. Record only in local task evidence:

```text
exact OpenClaw version
exact Node version
exact openclaw-weixin version
resolved plugin root
```

Do not copy raw plugin/account diagnostics into the report.

- [ ] **Step 4: Resolve exact config/state paths without guessing**

Use the current official `openclaw config file` surface for the config path. Require stdout to contain exactly one
non-empty path line. Accept an absolute path, or one leading `~/` path expanded only against exact `HOME` from the
currently loaded `ai.openclaw.gateway` official service-env; then resolve with `realpath` and require an existing
readable regular file that is not a symlink. The service-env itself must be the unique path read from the loaded job,
current-uid owned, `0600`, regular and not a symlink; source it only in a child shell and never print its values.
Empty/multiline/other-relative/missing/non-regular/unreadable output or command failure is a hard stop; do not use a
default path, candidate scan or custom wrapper. For state dir:

1. if `OPENCLAW_STATE_DIR` is explicitly set, require an absolute existing directory and use its realpath;
2. otherwise accept the config file's parent only if the expected Tencent state subtree for this installed plugin exists there and can be structurally verified without printing account contents;
3. otherwise stop with `G1 BLOCKED: OPENCLAW_STATE_DIR_NOT_DETERMINISTIC` and ask the user for the exact state directory.

Do not assume `~/.openclaw` simply because it is an upstream default.

- [ ] **Step 5: Verify exact compiled private module shape**

For the installed version, require these observed compiled module files; if the real installed version differs, stop and revise the spec/plan rather than guessing:

```text
dist/src/auth/accounts.js
dist/src/messaging/inbound.js
dist/src/messaging/send.js
```

A read-only Node import probe must confirm exact exports:

```text
accounts.js:
  listIndexedWeixinAccountIds
  loadWeixinAccount
  DEFAULT_BASE_URL

inbound.js:
  restoreContextTokens
  getContextToken

send.js:
  sendMessageWeixin
```

Because current OpenClaw `channels status --channel` cannot address dynamic `openclaw-weixin`, use these exact frozen
modules for a zero-send readiness probe after export validation: require exactly one indexed account, configured token
and `userId` ending `@im.wechat`, restore persisted context, and require non-empty context for that same account/user.
Only sanitized counts/booleans may leave the probe. `sendMessageWeixin()` call count must remain zero.

No glob/fallback path and no `src/*.ts` import is allowed.

- [ ] **Step 6: Create isolated task branch/worktree**

Use `superpowers:using-git-worktrees`, for example branch `task/clawbot-single-shot-notification`, based on the just-read `develop`.

**G1 PASS:** exact versions, plugin root, config/state paths, loaded/probe status and private export shape are known; evidence contains no account/user/token/context values.

---

### Task 1 — Freeze Compatibility Facts and Owner Schema

**Files:** `deploy/clawbot/*`, `clawbot_owner.py`, `test_alert_clawbot_owner.py`.

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

- [ ] **Step 1: Write `deploy/clawbot/versions.json` from the exact G1 readbacks**

The tracked file must contain exactly these keys:

```text
schema_version = 1
openclaw_version = exact G1 OpenClaw version string
openclaw_weixin_version = exact G1 plugin version string
node_version = exact G1 Node version string
plugin_modules.accounts = dist/src/auth/accounts.js
plugin_modules.inbound = dist/src/messaging/inbound.js
plugin_modules.send = dist/src/messaging/send.js
```

No local absolute path or private id belongs in Git.

- [ ] **Step 2: Write owner-loader RED tests**

Cover missing/symlink/non-regular, parent mode `0700`, file mode `0600`, parent/file current uid, exact schema keys, fixed version/channel/alias, control/blank ids, and `target_user_id` ending in `@im.wechat`. Use only synthetic values such as `fixture-owner@im.wechat`.

- [ ] **Step 3: Implement strict immutable owner loading**

Use `lstat()`, exact mode/uid checks, no symlink. Collapse errors to `CLAWBOT_OWNER_INVALID`; never interpolate private values or paths.

- [ ] **Step 4: Implement atomic owner writer for rollout G2 only**

Require existing private parent `0700/current uid`; validate ids; write same-directory temp file; chmod `0600`; fsync; `os.replace`; re-load as postcondition. D1 tests use temp paths only.

- [ ] **Step 5: Focused tests + commit**

Run owner tests and `git diff --check`, then commit only Task 1 files.

---

### Task 2 — Implement the Single Tencent Private Seam

**Files:** `openclaw_weixin_single_shot.mjs`, `openclaw_weixin_single_shot.test.mjs`.

The single seam supports exactly three actions:

```text
discover_owner  # read-only bootstrap helper, zero send
probe           # owner/account/context readiness, zero send
send            # at most one text send attempt
```

`discover_owner` is the necessary clarification of the approved owner-bootstrap section; it remains inside the same one private seam and is not a second transport.

- [ ] **Step 1: Create fake compiled plugin modules for `node --test`**

The fake account module exports `listIndexedWeixinAccountIds`, `loadWeixinAccount`, `DEFAULT_BASE_URL`; inbound exports `restoreContextTokens`, `getContextToken`; send exports `sendMessageWeixin`. All calls are recorded; no network/OpenClaw real state.

- [ ] **Step 2: RED tests for manifest/path/export safety**

Require absolute plugin root, exact manifest schema, plugin `package.json` version equal to frozen manifest, every relative module realpath under plugin root, and every required export callable/value of the expected type. Any mismatch => `CLAWBOT_DEPENDENCY_INVALID`, zero send.

- [ ] **Step 3: RED tests for `discover_owner`**

Require exactly one indexed account; `loadWeixinAccount()` returns token + `userId`; `userId` ends `@im.wechat`; `restoreContextTokens(account)` then `getContextToken(account,userId)` returns non-empty. Zero/multiple accounts, missing token/user/context or malformed data fail closed.

The child may return `account_id`/`target_user_id` only to its trusted parent over captured stdout JSON; public CLI must never echo them. Child stderr must never intentionally print them.

- [ ] **Step 4: RED tests for `probe`**

Load exact owner account, require token, require `account.userId == target_user_id`, restore context, require non-empty context; `sendMessageWeixin` calls = 0. Missing context => `CLAWBOT_CONTEXT_UNAVAILABLE`.

- [ ] **Step 5: RED tests for `send`**

Same checks as probe, then exactly one call:

```javascript
await sendMessageWeixin({
  to: targetUserId,
  text,
  opts: {
    baseUrl: account.baseUrl?.trim() || DEFAULT_BASE_URL,
    token: account.token,
    contextToken,
  },
});
```

Success => one call. Throw => one call + `CLAWBOT_SEND_FAILED`. Missing context => zero calls.

- [ ] **Step 6: Implement minimal ESM seam**

Read one stdin JSON object; get plugin root and versions-manifest path only from explicit child env; use `pathToFileURL()` for exact dynamic imports. Never import channel/Gateway/Agent/message-tool modules. Never invoke hooks or public OpenClaw send APIs.

Set/expect child logging to the quietest available mode; regardless of upstream logger behavior, the Python parent captures and discards raw stdout/stderr and never forwards raw vendor output.

- [ ] **Step 7: Run node tests + commit**

```bash
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
```

---

### Task 3 — Python Dependency/Runner/Sender + Controlled CLI

**Files:** `clawbot.py`, `test_alert_clawbot.py`, `guiyi_cli/main.py`, `test_alert_cli.py`.

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
class ClawbotOwnerCandidate:
    account_id: str
    target_user_id: str

@dataclass(frozen=True, slots=True)
class ClawbotSendSummary:
    attempted: int
    provider_accepted: int
    failed: int
    failed_aliases: tuple[str, ...]

class ClawbotError(RuntimeError): ...

class ClawbotRunner:
    def discover_owner(self) -> ClawbotOwnerCandidate: ...
    def probe(self, owner: ClawbotOwner) -> None: ...
    def send_text(self, owner: ClawbotOwner, text: str) -> None: ...

class ClawbotAlertSender:
    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> ClawbotSendSummary: ...
```

- [ ] **Step 1: RED tests for dependency resolution**

All six local paths are explicit env inputs:

```text
GUIYI_OPENCLAW_BIN
GUIYI_OPENCLAW_NODE_BIN
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
GUIYI_OPENCLAW_STATE_DIR
GUIYI_OPENCLAW_CONFIG_PATH
GUIYI_ALERT_CLAWBOT_OWNER_PATH
```

Reject missing/relative/nonexistent/wrong type. Exact live validation compares `openclaw --version`, `node --version`, and `openclaw plugins inspect openclaw-weixin --runtime --json` to the frozen manifest and exact resolved plugin root. Any mismatch => `ALERT_NOTIFICATION_TRANSPORT_NOT_READY`.

- [ ] **Step 2: RED tests for one-child-at-most runner**

Fixed argv only:

```python
[node_bin, PROJECT_ROOT / "services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs"]
```

Action/account/target/text are stdin JSON. Child env is an allowlist and includes:

```text
OPENCLAW_STATE_DIR=<exact state dir>
OPENCLAW_CONFIG=<exact config path>
OPENCLAW_LOG_LEVEL=FATAL
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT=<exact plugin root>
GUIYI_CLAWBOT_VERSIONS_PATH=<exact versions manifest>
PATH=<node parent>:/usr/bin:/bin:/usr/sbin:/sbin
```

Do not blindly inherit conflicting `OPENCLAW_*`/`CLAWDBOT_*`. Each runner method calls `subprocess.run()` exactly once with finite timeout. Timeout/crash/nonzero/malformed output never creates a second child. Raw child stdout/stderr is never included in the raised public error.

- [ ] **Step 3: RED sender tests**

`send()` uses existing `format_alert_message()` once and runner once. `send_canary()` uses fixed `ALERT_CANARY_TEXT` and returns:

```text
success: attempted=1, provider_accepted=1, failed=0, failed_aliases=()
failure: attempted=1, provider_accepted=0, failed=1, failed_aliases=("owner",)
```

- [ ] **Step 4: Add controlled CLI only**

Replace Courier `alert-target-verify` with:

```text
guiyi runtime clawbot-owner-bootstrap [--confirm-write-owner]
guiyi runtime clawbot-preflight
guiyi runtime alert-canary
```

No `--target`, `--account`, `--message`, arbitrary send or free-form text option exists.

Discovery bootstrap public output contains only channel/alias/count/context booleans and `owner_written=false`; `readonly=true`. `--confirm-write-owner` writes the unique candidate through `write_clawbot_owner_atomic()`, returns deterministic `status=ok`, `readonly=false`, `owner_written=true`, and still exposes no ids.

`clawbot-preflight` calls `probe`, returns `readonly=true`, `would_send=false` and zero send.

`alert-canary` returns `attempted/provider_accepted/failed/failed_aliases`; it is not readonly.

- [ ] **Step 5: Readonly classification tests**

```text
runtime status -> true
clawbot-owner-bootstrap discovery -> true
clawbot-owner-bootstrap --confirm-write-owner -> false
clawbot-preflight -> true
runtime live/alert/alert-canary -> false
```

- [ ] **Step 6: Focused tests + commit**

---

### Task 4 — Rewire Alert Composition and Structural Health

**Files:** `composition.py`, `runtime_health.py`, `test_alert_runtime.py`, `test_runtime_health.py`.

**Interfaces:**

```python
def build_clawbot_dependency_from_env(*, verify_versions: bool) -> ClawbotDependency: ...
def build_clawbot_runner_from_env(*, verify_versions: bool = True) -> ClawbotRunner: ...
def build_clawbot_sender_from_env(*, live_probe: bool = True) -> ClawbotAlertSender: ...
def clawbot_transport_configured_from_env() -> bool: ...
```

- [ ] **Step 1: RED composition tests**

`verify_versions=True` runs only local/read-only version/plugin-inspect checks plus private seam probe. `live_probe=True` loads immutable owner and calls runner `probe(owner)` once. No send.

- [ ] **Step 2: Rewire `build_alert_runtime()`**

Replace Courier builder with `build_clawbot_sender_from_env(live_probe=True)`. Do not change evaluators, Redis source/heartbeat, operational products, taxonomy or session factories.

- [ ] **Step 3: Preserve Event-first/no-retry tests**

Prove DB/Event failure => 0 sends; new committed Event => 1 sender call; duplicate Event => 0; sender failure leaves Event committed; no second sender call; next Bar can continue; old failed Event is never replayed.

- [ ] **Step 4: Structural HTTP health only**

`clawbot_transport_configured_from_env()` validates local path/file/manifest/owner structure without network send, owner discovery or Tencent API calls. `/api/runtime/health` remains readonly and must not run a real canary/probe on every HTTP request.

- [ ] **Step 5: Focused tests + commit**

---

### Task 5 — Replace Courier Ops/Launchd With External Clawbot Identity

**Files:** both API/Alert plist templates, `install-local-services.sh`, `run-local-service.sh`, `local-services-status.sh`, engineering launchd tests.

- [ ] **Step 1: Replace Courier env in API + Alert plist templates**

Both receive exactly the same six Clawbot path variables. No account/user/token/context value belongs in plist.

- [ ] **Step 2: Preserve launcher authority**

Extend existing `run-local-service.sh` logic so non-empty launchd values for all six Clawbot path variables win over `project.env/.env`. Do not alter unrelated env precedence.

- [ ] **Step 3: Fail closed before Alert promotion mutation**

`install-local-services.sh --confirm-alert-runtime` validates required Clawbot paths and the already-installed API plist's six values before writing Alert marker or invoking `launchctl`. API/Alert mismatch fails before mutation. No script may install/update/restart OpenClaw.

- [ ] **Step 4: Replace supervised notification-channel status logic**

```text
wecom.py only -> wecom
clawbot.py only and no wecom/courier -> clawbot-openclaw-weixin
ambiguous/none -> unknown
```

For Clawbot Runtime print only sanitized external facts:

```text
alert.notification_channel=clawbot-openclaw-weixin
alert.notification_owner_alias=owner
external.openclaw.status=ready|invalid|missing
external.openclaw.version=<non-secret exact version>
external.openclaw_weixin.status=ready|invalid|missing
external.openclaw_weixin.version=<non-secret exact version>
external.clawbot_owner_config=ready|invalid|missing
```

Never print ids/tokens/raw plugin JSON/message. Never compare OpenClaw/plugin identity with `GUIYI_RUNTIME_COMMIT`.

Legacy v1.4.2 WeCom Runtime must still report/passes without Clawbot vars.

- [ ] **Step 5: Engineering tests + shell/render/plutil verification + commit**

No real `launchctl` load/reload in D1.

---

### Task 6 — Delete Courier, Close Canonicals, Full Verification, Independent Review

- [ ] **Step 1: Delete all Courier source/tests/tooling listed in File Structure**

Remove Courier env vars, `alert-target-verify`, installer/version/status logic. Do not rewrite historical evidence.

- [ ] **Step 2: Verify active WeCom source remains zero on `develop`**

Active source/config/tests must not reintroduce:

```text
WeComWebhookSender
build_wecom_sender_from_env
WECOM_WEBHOOK_URL
qyapi.weixin.qq.com
```

Historical/current-production text in `STATUS.md` may still say WeCom until G8.

- [ ] **Step 3: Update canonicals truthfully**

Record `develop = Clawbot single-shot / not released`, `production = v1.4.2 + WeCom until G8`, and `OpenClaw = external existing infrastructure not Guiyi-supervised`. Do not claim bootstrap/canary/release/promotion occurred.

- [ ] **Step 4: Run full verification**

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

Run the broader normal Alert/backend regressions if shared CLI/ops edits require them.

- [ ] **Step 5: Forbidden-path review**

Production source must not call/contain active paths for:

```text
openclaw message send
Gateway send
sendDurableMessageBatchCore
wechat_courier
GUIYI_WECHAT_COURIER_ROOT
GUIYI_ALERT_WECHAT_GROUP_PATH
alert-target-verify
```

Tests may contain literal forbidden strings only to assert they are rejected; scope grep accordingly.

- [ ] **Step 6: Independent Review in a fresh session**

Review at minimum:

1. `sendMessageWeixin` cannot exceed one call per sender invocation;
2. missing context is zero-send;
3. timeout/crash/malformed child output cannot respawn;
4. no public OpenClaw/durable queue path exists;
5. `discover_owner` private ids cannot leak to CLI/logs;
6. owner config is immutable for a running sender;
7. Event-first and failure isolation remain intact;
8. evaluator/Scope/DB/Canonical/order diffs are zero;
9. API/Alert launchd paths match and launcher values win;
10. status reads supervised Runtime truth and legacy v1.4.2 WeCom remains truthful;
11. D1 performed no real owner write/send/OpenClaw mutation/Runtime switch.

**R1 PASS:** Critical=`0`, Important=`0`, required verification PASS.

- [ ] **Step 7: Integrate task branch into `develop` only after R1 PASS**

Use repository workflow, read back `origin/develop`, then clean the task worktree/merged task branch. Do not touch main/tag/production.

---

## D1 Completion Gate

D1 completes only when:

```text
G1 exact installed dependency facts are frozen
Clawbot single-shot is the only active develop notification transport
Courier active source/tests/tooling = 0
active WeCom sender source/config = 0 on develop
production v1.4.2 + WeCom unchanged
bootstrap/preflight/canary code exists but no real owner write/send occurred
Event-first/no-retry/at-most-one verified
privacy/secret checks pass
R1 Critical=0 / Important=0
```

Final verdict: `D1 CLAWBOT CODE PASS，允许进入 rollout G2 owner bootstrap` or `D1 CLAWBOT CODE BLOCKED，禁止进入真实 owner/canary`.
