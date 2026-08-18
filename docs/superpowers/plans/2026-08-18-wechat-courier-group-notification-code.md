# WeChat-Courier Group Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot the in-progress D1 notification migration from Tencent iLink four-person DMs to one fixed WeChat group sent through a pinned, locally hardened WeChat-Courier transport while preserving Alert Event-first/no-retry semantics.

**Architecture:** Keep the transport-neutral notification contract already created by old Task 1. Delete/revert all iLink-specific work from the current Task5–6 worktree, then add one private group config, one pinned WeChat-Courier dependency contract, one hardened child adapter that exact-verifies search result/title before a single send, and one `WeChatGroupAlertSender`. No OpenClaw/iLink/context monitor/recipient fan-out remains.

**Tech Stack:** Python 3.13 stdlib + existing FastAPI/SQLAlchemy stack, macOS WeChat.app, AppleScript/System Events, macOS Vision/Swift helpers through pinned `bladydora/WeChat-Courier-macOS@981bd14e238302b2a0e206cb5f28e8e2505bb874`, macOS launchd.

**Spec:** `docs/superpowers/specs/2026-08-18-wechat-courier-group-notification-design.md`

## Global Constraints

- This is the replacement D1 code plan. Stop the old iLink Task5–6 executor before continuing old work.
- Current remote `develop` may not contain the in-progress Task1–6 code; inspect the actual task worktree first and preserve unrelated/user changes.
- Do not use `git reset --hard`, `git clean -fd`, whole-tree checkout, broad restore, or bulk staging to pivot the current worktree.
- D1 code work only: no real WeChat-Courier install, no macOS permission mutation, no GUI automation, no screenshot, no group opening, no canary, no Runtime switch, no `main`/tag/release.
- Preserve `htdy_original_15m`, `subing_entry_signal_v1`, their formulas and Scope, Alert two-table schema, DB revision and `auto_order=false`.
- Preserve Event-first: committed Event is never rolled back because notification failed; no notification retry/replay/backfill/outbox/queue.
- V1 target is exactly one private group alias: `primary_alert_group`.
- Real group title never appears in tracked files, tests, logs, receipts or chat.
- Upstream WeChat-Courier fuzzy `text_matches_target` is not accepted as the final safety boundary. Project code must exact-verify unique search result + title.
- Upstream queue/watcher/retry/MCP/HTTP surfaces are forbidden.
- Tests use fake Courier trees, fixture OCR boxes/text, mocked subprocesses, temp private config and render-only launchd only.

## File Structure

### Preserve from old Task 1 if already present

- `services/quant-api/app/alerts/notification.py`
- `services/quant-api/tests/test_alert_notification.py`
- transport-neutral `AlertRuntime.sender: AlertNotificationSender`

### Create

- `services/quant-api/app/alerts/wechat_group_config.py`
- `services/quant-api/app/alerts/wechat_courier.py`
- `services/quant-api/app/alerts/wechat_courier_adapter.py`
- `services/quant-api/tests/test_alert_wechat_group_config.py`
- `services/quant-api/tests/test_alert_wechat_courier.py`
- `tests/engineering/test_wechat_courier_adapter.py`
- `deploy/wechat-courier/versions.json`
- `deploy/wechat-courier/README.md`
- `scripts/ops/macos/install-wechat-courier.sh`

### Modify

- `services/quant-api/app/alerts/runtime.py`
- `services/quant-api/app/alerts/composition.py`
- `services/quant-api/app/guiyi_cli/main.py`
- `services/quant-api/tests/test_alert_runtime.py`
- `services/quant-api/tests/test_alert_cli.py`
- `deploy/launchd/com.guiyi.quant-alert.plist.template`
- `scripts/ops/macos/install-local-services.sh`
- `scripts/ops/macos/local-services-status.sh`
- `tests/engineering/test_alert_runtime_launchd.py`
- `TESTING.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`

### Delete/revert from the old iLink worktree if present

- `services/quant-api/app/alerts/recipient_registry.py`
- `services/quant-api/app/alerts/weixin.py`
- `services/quant-api/app/alerts/weixin_context.py`
- `services/quant-api/app/alerts/openclaw_weixin_adapter.mjs`
- `services/quant-api/tests/test_alert_recipient_registry.py`
- `services/quant-api/tests/test_alert_weixin.py`
- `services/quant-api/tests/test_alert_weixin_context.py`
- `tests/engineering/openclaw_weixin_adapter.test.mjs`
- `tests/engineering/test_weixin_context_launchd.py`
- `deploy/openclaw/**`
- `deploy/launchd/com.guiyi.quant-weixin-context.plist.template`
- `scripts/ops/macos/install-openclaw-weixin-tools.sh`
- old CLI branches `weixin-register` and `weixin-context`
- old environment wiring `GUIYI_OPENCLAW_ROOT`, `GUIYI_ALERT_RECIPIENTS_PATH`

### Delete when new sender is ready

- `services/quant-api/app/alerts/wecom.py`
- `services/quant-api/tests/test_alert_wecom.py`

---

### Task 0: Stop old Task5–6 and perform a surgical transition audit

**Files:** current in-progress task worktree only.

**Interfaces:**
- Consumes: old iLink Task1–6 partial state.
- Produces: clean transport-neutral base with no committed/uncommitted iLink-specific implementation, while preserving Task1 notification abstractions.

- [ ] **Step 1: Record current identity and dirty scope before changing anything**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
git diff --name-status
git diff --cached --name-status
git log -8 --oneline
```

Save only non-sensitive path/status evidence in the task report; do not copy secrets or real group/account ids.

- [ ] **Step 2: Classify every old Task1–6 changed path**

Use three buckets:

```text
KEEP
- notification.py and its tests
- generic AlertNotificationSender typing
- transport-neutral formatter/canary constants

REMOVE_ILINK
- recipient registry
- OpenClaw/iLink adapter
- weixin sender/context monitor
- registration/context CLI
- OpenClaw deploy/tooling/launchd wiring

UNRELATED
- anything not created/modified by this notification task
```

Any path whose ownership is unclear is `UNRELATED` until manually inspected.

- [ ] **Step 3: Remove only iLink-specific committed or uncommitted hunks**

For newly created iLink-only files, delete those exact files. For mixed files such as `main.py`, `composition.py`, launchd templates or installers, edit only the old iLink hunks and preserve unrelated changes/index state.

Forbidden:

```bash
git reset --hard
git clean -fd
git restore .
git checkout -- .
```

- [ ] **Step 4: Verify the transition base**

Run:

```bash
git grep -n -E 'openclaw_weixin|WeixinContext|weixin-register|weixin-context|GUIYI_OPENCLAW_ROOT|GUIYI_ALERT_RECIPIENTS_PATH' -- \
  services deploy scripts tests || true

git status --short
```

Expected: no active old iLink implementation reference in this task's code scope; unrelated changes remain intact.

- [ ] **Step 5: Run transport-neutral tests**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py
```

If `test_alert_notification.py` does not exist because old Task1 never landed in this worktree, implement old Task1 exactly from Git history/new spec before proceeding.

- [ ] **Step 6: Commit only the transition cleanup if the worktree uses task commits**

```bash
git add <only reviewed notification-task paths>
git commit -m "refactor(alert): pivot notification transport to group sender"
```

Do not stage unrelated paths.

---

### Task 1: Add the single private group target contract

**Files:**
- Create: `services/quant-api/app/alerts/wechat_group_config.py`
- Create: `services/quant-api/tests/test_alert_wechat_group_config.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WeChatGroupTarget:
    version: int
    channel: str
    group_alias: str
    target_chat: str

class WeChatGroupConfigError(RuntimeError): ...

def load_wechat_group_target(path: Path) -> WeChatGroupTarget: ...
```

Constants:

```python
WECHAT_GROUP_CONFIG_VERSION = 1
WECHAT_GROUP_CHANNEL = "wechat-courier"
PRIMARY_ALERT_GROUP_ALIAS = "primary_alert_group"
```

- [ ] **Step 1: Write failing config validation tests**

Cover all cases explicitly:

```python
missing file
symlink
non-regular file
a parent whose mode != 0700
file mode != 0600
malformed JSON
extra/missing top-level keys
version != 1
channel != "wechat-courier"
group_alias != "primary_alert_group"
blank target_chat
target_chat containing newline/control characters
```

Representative test:

```python
def test_load_private_group_target(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "alert-wechat-group.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "channel": "wechat-courier",
            "group_alias": "primary_alert_group",
            "target_chat": "fixture-group-title",
        }),
        encoding="utf-8",
    )
    path.chmod(0o600)
    result = load_wechat_group_target(path)
    assert result.group_alias == "primary_alert_group"
    assert result.target_chat == "fixture-group-title"
```

- [ ] **Step 2: Run the red test**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_group_config.py
```

Expected: import failure.

- [ ] **Step 3: Implement strict loader**

Use `Path.lstat()`. Reject symlink and non-regular file. Require exact `0600`, exact parent `0700`, exact schema keys and exact fixed channel/alias. Do not log `target_chat`.

- [ ] **Step 4: Add privacy tests**

Force every validation error and assert `str(exc)` never contains the fixture target value.

- [ ] **Step 5: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_group_config.py

git add services/quant-api/app/alerts/wechat_group_config.py \
  services/quant-api/tests/test_alert_wechat_group_config.py
git commit -m "feat(alert): add private WeChat group target"
```

---

### Task 2: Pin WeChat-Courier and build the hardened no-send adapter contract

**Files:**
- Create: `deploy/wechat-courier/versions.json`
- Create: `services/quant-api/app/alerts/wechat_courier.py`
- Create: `services/quant-api/app/alerts/wechat_courier_adapter.py`
- Create: `services/quant-api/tests/test_alert_wechat_courier.py`
- Create: `tests/engineering/test_wechat_courier_adapter.py`

**Interfaces:**

Pinned identity:

```json
{
  "schema_version": 1,
  "repository": "bladydora/WeChat-Courier-macOS",
  "commit": "981bd14e238302b2a0e206cb5f28e8e2505bb874"
}
```

Python domain interfaces:

```python
@dataclass(frozen=True, slots=True)
class WeChatCourierDependency:
    root: Path
    source_root: Path
    python_executable: Path
    upstream_commit: str

class WeChatCourierError(RuntimeError): ...

def resolve_wechat_courier_dependency(root: Path, *, run_process=...) -> WeChatCourierDependency: ...

class WeChatCourierRunner:
    def verify_target(self, target: WeChatGroupTarget) -> None: ...
```

Child adapter input for D1 tests:

```json
{
  "action": "verify",
  "target_chat": "fixture-group-title",
  "upstream_root": "/fixture/source"
}
```

Child public output:

```json
{"status":"verified"}
```

- [ ] **Step 1: Write dependency resolver red tests**

Require exact paths:

```text
<root>/source/.git
<root>/source/wechat_courier.py
<root>/venv/bin/python
<root>/runtime
<root>/tmp
<root>/cache/clang
```

Resolver must run fixed argv only:

```python
["/usr/bin/git", "-C", str(source_root), "rev-parse", "HEAD"]
["/usr/bin/git", "-C", str(source_root), "status", "--porcelain"]
```

Reject wrong commit, dirty upstream checkout, missing files or root escaping its configured path.

- [ ] **Step 2: Write exact target normalization tests**

In `wechat_courier_adapter.py` expose pure helpers for engineering tests:

```python
def normalize_chat_name(value: str) -> str: ...
def title_matches_exact_target(ocr_line: str, target: str) -> bool: ...
def select_unique_search_box(box_texts: Sequence[str], target: str) -> int: ...
```

Test:

```text
"归一量化" == "归一量化"
"归一 量化" normalized == exact target
"归一量化测试" != "归一量化"
"测试归一量化" != "归一量化"
0 exact -> error
2 exact -> error
"归一量化（4）" title accepted for target "归一量化"
"归一量化测试（4）" rejected
```

- [ ] **Step 3: Write a fake pinned upstream module**

Fixture exports only the exact reviewed functions the adapter may use:

```python
activate_wechat
make_search_results_screenshot
ocr_boxes
search_result_row_click_point
click_point
make_safety_screenshot
make_title_screenshot
ocr_image
paste_and_send_text
```

The fake records every call and never touches GUI.

- [ ] **Step 4: Implement exact private seam loading**

Use `importlib.util.spec_from_file_location()` on exactly:

```text
<upstream_root>/wechat_courier.py
```

Require all nine callable exports above. Missing/extra upstream behavior is not guessed. Wrong shape -> `WECHAT_COURIER_DEPENDENCY_INVALID`.

Do not call upstream `find_search_result_click_point()` or `text_matches_target()`.

- [ ] **Step 5: Implement `verify` without any send primitive**

Exact sequence:

```text
activate_wechat
→ open search UI using project-reviewed helper logic based on upstream primitives
→ OCR search-result crop
→ require exactly one exact normalized result
→ click that row
→ OCR safety crop and reject known search-page markers
→ OCR title crop
→ require exact target or exact target + (N)/(（N）)
→ delete all screenshots
→ return {"status":"verified"}
```

If implementing search UI requires calling upstream `open_chat()`, monkey-patch/replace its result selector inside this one adapter so the upstream fuzzy selector cannot run. Engineering tests must prove fuzzy `text_matches_target()` is never called.

- [ ] **Step 6: Silence upstream output**

Wrap upstream calls with `contextlib.redirect_stdout(io.StringIO())` and `redirect_stderr(io.StringIO())`. On failure emit only a stable JSON error code; never include OCR text, target title or raw exception.

- [ ] **Step 7: Add exact child environment in the parent runner**

Parent uses fixed argv:

```python
[
    str(dependency.python_executable),
    str(PROJECT_ROOT / "services/quant-api/app/alerts/wechat_courier_adapter.py"),
]
```

Pass target/upstream root through stdin JSON only. Child env contains:

```python
{
    "PATH": f"{root}/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "TMPDIR": f"{root}/tmp",
    "CLANG_MODULE_CACHE_PATH": f"{root}/cache/clang",
    "PYTHONUNBUFFERED": "1",
}
```

Do not pass target in argv or logs.

- [ ] **Step 8: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_wechat_courier.py \
  tests/engineering/test_wechat_courier_adapter.py

git add deploy/wechat-courier/versions.json \
  services/quant-api/app/alerts/wechat_courier.py \
  services/quant-api/app/alerts/wechat_courier_adapter.py \
  services/quant-api/tests/test_alert_wechat_courier.py \
  tests/engineering/test_wechat_courier_adapter.py
git commit -m "feat(alert): add hardened WeChat Courier adapter"
```

---

### Task 3: Add one-group single-shot sender, GUI lock and structured canary

**Files:**
- Modify: `services/quant-api/app/alerts/wechat_courier.py`
- Modify: `services/quant-api/app/alerts/wechat_courier_adapter.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify/Test: `services/quant-api/tests/test_alert_wechat_courier.py`
- Modify/Test: `services/quant-api/tests/test_alert_cli.py`
- Modify/Test: `tests/engineering/test_wechat_courier_adapter.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WeChatGroupSendSummary:
    attempted: int
    automation_completed: int
    failed: int
    failed_aliases: tuple[str, ...]

class WeChatGroupAlertSender:
    def __init__(
        self,
        *,
        target: WeChatGroupTarget,
        runner: WeChatCourierRunner,
    ) -> None: ...

    def send(self, message: AlertNotificationMessage) -> None: ...
    def send_canary(self) -> WeChatGroupSendSummary: ...
```

- [ ] **Step 1: Write GUI lock tests**

Lock path:

```text
<GUIYI_WECHAT_COURIER_ROOT>/runtime/guiyi-wechat-courier.lock
```

Use `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. A second holder must fail immediately with `WECHAT_COURIER_BUSY`; no sleep/wait/retry.

- [ ] **Step 2: Write child `send` red tests**

Input:

```json
{"action":"send","target_chat":"fixture-group-title","text":"fixture-alert","upstream_root":"/fixture/source"}
```

Prove:

```text
verification failure -> paste_and_send_text calls = 0
verification success -> paste_and_send_text calls = 1
paste_and_send_text failure -> calls = 1, no retry
near-match/ambiguous search -> calls = 0
```

- [ ] **Step 3: Implement `send` as verify-then-single-send**

The exact sequence is the Task 2 verification sequence followed by exactly one:

```python
upstream.paste_and_send_text(text)
```

No other outbound primitive is permitted.

- [ ] **Step 4: Add parent process timeout semantics**

One Alert -> one child process. Timeout/crash/malformed JSON/nonzero exit collapses to one of:

```text
WECHAT_COURIER_BUSY
WECHAT_GROUP_TARGET_UNVERIFIED
WECHAT_COURIER_DEPENDENCY_INVALID
WECHAT_COURIER_SEND_FAILED
```

Never rerun the child automatically.

- [ ] **Step 5: Implement sender formatting exactly once**

```python
text = format_alert_message(message)
runner.send_text(target, text)
```

Do not log `text` or `target.target_chat`.

- [ ] **Step 6: Rewrite `runtime alert-canary` output contract**

Success stdout:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"ok","attempted":1,"automation_completed":1,"failed":0,"failed_aliases":[]}
```

Failure stdout:

```json
{"schema_version":1,"command":"runtime.alert-canary","status":"failed","attempted":1,"automation_completed":0,"failed":1,"failed_aliases":["primary_alert_group"]}
```

Failure returns exit code 1. Never use `provider_accepted`, `delivered` or `read`.

- [ ] **Step 7: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_wechat_courier.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_wechat_courier_adapter.py

git add services/quant-api/app/alerts/wechat_courier.py \
  services/quant-api/app/alerts/wechat_courier_adapter.py \
  services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests/test_alert_wechat_courier.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_wechat_courier_adapter.py
git commit -m "feat(alert): add single-shot WeChat group sender"
```

---

### Task 4: Rewire Alert Runtime and retire active WeCom on develop

**Files:**
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `deploy/launchd/com.guiyi.quant-alert.plist.template`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`
- Delete: `services/quant-api/app/alerts/wecom.py`
- Delete: `services/quant-api/tests/test_alert_wecom.py`

**Interfaces:**

```python
def build_wechat_group_sender_from_env() -> WeChatGroupAlertSender: ...
def build_alert_runtime() -> AlertRuntime: ...
```

Required env:

```text
GUIYI_WECHAT_COURIER_ROOT
GUIYI_ALERT_WECHAT_GROUP_PATH
```

- [ ] **Step 1: Add failing composition tests**

Cover:

```text
missing Courier root -> ALERT_NOTIFICATION_TRANSPORT_NOT_READY
missing private group config -> same stable failure
wrong Courier commit -> same stable failure
invalid private config -> same stable failure
valid structural dependency/config -> sender builds without touching WeChat
```

Construction/preflight must never run adapter `verify` or `send`; no GUI automation at startup.

- [ ] **Step 2: Rewire Runtime to the generic sender Protocol**

If old Task1 has already changed:

```python
sender: AlertNotificationSender
```

keep it. Otherwise make this exact change now. Do not alter Event creation/order.

- [ ] **Step 3: Rewire composition in fixed order**

```text
activation marker
→ operational products/taxonomy
→ private group target
→ pinned Courier dependency structural validation
→ Redis source/heartbeat
→ AlertRuntime(sender=WeChatGroupAlertSender)
```

No OCR/open/send during composition.

- [ ] **Step 4: Inject identical private paths into Alert launchd**

`com.guiyi.quant-alert.plist.template` gains placeholders/environment:

```text
GUIYI_WECHAT_COURIER_ROOT
GUIYI_ALERT_WECHAT_GROUP_PATH
```

`install-local-services.sh --render-only` requires explicit values only when rendering an enabled/confirmed Alert Runtime path; ordinary inactive render behavior remains compatible with repository rules.

- [ ] **Step 5: Preserve Event-first failure isolation tests**

Required assertions:

```text
new Event -> sender called once
duplicate Event -> sender not called
DB failure -> sender not called
sender failure -> Event committed
sender failure -> next completed Bar still processes
multiple messages in one Bar -> sender calls sequentially
```

- [ ] **Step 6: Delete active WeCom implementation/tests**

Delete `wecom.py`, `test_alert_wecom.py`, WeCom composition factory and active `WECOM_WEBHOOK_URL` wiring only after Tasks 1–3 pass.

Do not change current production `STATUS.md`; current exact-tag Runtime still runs WeCom until later promotion.

- [ ] **Step 7: Verify and commit**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_wechat_group_config.py \
  services/quant-api/tests/test_alert_wechat_courier.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_cli.py \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_wechat_courier_adapter.py

git add -A services/quant-api/app/alerts services/quant-api/app/guiyi_cli/main.py \
  services/quant-api/tests deploy/launchd/com.guiyi.quant-alert.plist.template \
  scripts/ops/macos/install-local-services.sh tests/engineering
git commit -m "feat(alert): switch develop notifications to WeChat group"
```

---

### Task 5: Add expansion-disk Courier tooling, status and full D1 verification

**Files:**
- Create: `deploy/wechat-courier/README.md`
- Create: `scripts/ops/macos/install-wechat-courier.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `TESTING.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`
- Test: existing engineering shell/status tests plus new adapter tests.

**Interfaces:**

```text
install-wechat-courier.sh --check
install-wechat-courier.sh --confirm-install
```

D1 only tests these with fixtures/fake commands. Real `--confirm-install` belongs to a later user Gate.

- [ ] **Step 1: Implement read-only `--check` tests first**

With missing root, output privacy-safe:

```text
status=not_installed
```

and exit 0.

Fixture-installed root verifies:

```text
source commit = 981bd14e238302b2a0e206cb5f28e8e2505bb874
source clean
venv python exists
wechat_courier.py exists
runtime/tmp/cache roots exist
```

No group title appears.

- [ ] **Step 2: Implement gated `--confirm-install` code path without running it**

Require `GUIYI_WECHAT_COURIER_ROOT` absolute and under `/Volumes/`.

Exact intended operations for later Gate:

```bash
mkdir -p "$ROOT/source" "$ROOT/runtime" "$ROOT/tmp" "$ROOT/cache/clang"
/usr/bin/git clone https://github.com/bladydora/WeChat-Courier-macOS.git "$ROOT/source"   # only when source absent
/usr/bin/git -C "$ROOT/source" fetch origin 981bd14e238302b2a0e206cb5f28e8e2505bb874
/usr/bin/git -C "$ROOT/source" checkout --detach 981bd14e238302b2a0e206cb5f28e8e2505bb874
/usr/bin/python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install --disable-pip-version-check Pillow==11.3.0
```

If source already exists, require its origin to resolve exactly to the reviewed GitHub repo before fetch/checkout. Never run `main`, pull latest, start watcher/queue/MCP, grant TCC, open WeChat or send.

Tests replace git/python/pip with fake executables and assert exact argv.

- [ ] **Step 3: Extend local status output**

Add external dependency namespace without exposing group title:

```text
external.wechat_courier.commit=981bd14e238302b2a0e206cb5f28e8e2505bb874
external.wechat_courier.status=ready|not_installed|invalid
alert.notification_channel=wechat-courier   # only based on current code/config surface, not delivery proof
alert.notification_group_alias=primary_alert_group
```

Do not call GUI/OCR in status.

- [ ] **Step 4: Update current canonicals without falsifying production**

`AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md` should state:

```text
develop target architecture = one-group WeChat-Courier
no OpenClaw/iLink/context monitor
strict exact target verification
no notification retry/queue
current production exact-tag Runtime remains WeCom until future promotion recorded in STATUS.md
```

Do not modify `STATUS.md` to claim the migration is active.

- [ ] **Step 5: Update TESTING.md**

Document D1-safe tests and explicitly state that none of these authorize:

```text
real Courier install
TCC/Screen Recording/Accessibility changes
opening/searching a real group
OCR capture of real WeChat
real canary
Runtime switch/release
```

- [ ] **Step 6: Run the full D1 verification**

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
  services/quant-api/tests/test_alert_wechat_group_config.py \
  services/quant-api/tests/test_alert_wechat_courier.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/alembic/test_alert_v2_migration.py \
  tests/engineering/test_alert_runtime_launchd.py \
  tests/engineering/test_wechat_courier_adapter.py

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant tests/engineering

UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache MYPYPATH=services/quant-api \
  uv run --offline --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli services/quant-api/app/services/runtime_health.py

find scripts/ops -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
GUIYI_WECHAT_COURIER_ROOT=/private/tmp/guiyi-fixture-courier \
  scripts/ops/macos/install-wechat-courier.sh --check
GUIYI_WECHAT_COURIER_ROOT=/private/tmp/guiyi-render-courier \
GUIYI_ALERT_WECHAT_GROUP_PATH=/private/tmp/guiyi-render-secrets/alert-wechat-group.json \
  scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
git diff --check
git status --short
```

Expected: all applicable checks exit 0; secret scan 0 findings; no real external mutation.

- [ ] **Step 7: Prove old active routes are gone**

```bash
git grep -n -E 'openclaw_weixin|openclaw-weixin|GUIYI_OPENCLAW_ROOT|GUIYI_ALERT_RECIPIENTS_PATH|weixin-register|weixin-context|WeixinContextMonitor' -- \
  services deploy scripts tests TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true

git grep -n -E 'WeComWebhookSender|build_wecom_sender_from_env|WECOM_WEBHOOK_URL|qyapi\.weixin\.qq\.com' -- \
  services deploy scripts TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md || true
```

Expected: zero active code/current-canonical references. Historical `STATUS.md` evidence is allowed and must remain truthful.

- [ ] **Step 8: Review scope diff**

```bash
git diff --stat develop...HEAD
git diff develop...HEAD -- \
  services/quant-api/app/alerts services/quant-api/app/guiyi_cli services/quant-api/tests \
  deploy/wechat-courier deploy/launchd scripts/ops/macos tests/engineering \
  TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md
```

Verify no evaluator formula, Rule Scope, migration, DB schema, Canonical, order path, `main`, tag, production Runtime worktree or real private group config was changed.

- [ ] **Step 9: Commit**

```bash
git add deploy/wechat-courier scripts/ops/macos/install-wechat-courier.sh \
  scripts/ops/macos/local-services-status.sh TESTING.md AGENTS.md PROJECT_SOURCE.md DECISIONS.md \
  tests/engineering
git commit -m "docs(alert): define WeChat Courier group operations"
```

---

## D1 Completion Gate

Fresh evidence must support every item:

```text
PASS old Task5–6 iLink implementation stopped and surgically removed
PASS transport-neutral notification contract preserved
PASS no OpenClaw/iLink/context monitor/recipient fan-out remains active
PASS private target is one group alias only
PASS target config is 0700 parent / 0600 file and never logged
PASS WeChat-Courier exact commit is pinned and clean
PASS upstream fuzzy target match is not the final safety boundary
PASS search-result exact match is unique or send aborts
PASS title exact match/member-count suffix is verified or send aborts
PASS same-prefix/near-name/same-name ambiguity sends zero messages
PASS OCR screenshots are deleted by default and raw OCR never reaches guiyi logs
PASS GUI lock is non-blocking and creates no queue
PASS each new AlertEvent has at most one physical send primitive
PASS OCR verification retry cannot become message-send retry
PASS committed Event survives notification failure
PASS canary reports automation_completed, never delivered/provider_accepted
PASS no DB migration/schema/Scope/evaluator/order change
PASS active WeCom code retired on develop only after Courier sender is ready
PASS production exact-tag WeCom Runtime not mutated or falsified in STATUS.md
PASS no real WeChat/Courier/TCC/external operation executed during D1
```

If all pass: **允许集成 develop**.

After D1 PASS, stop. Do not reuse the deleted iLink rollout plan. Write a fresh WeChat-Courier rollout plan covering exact install, macOS permissions, no-send P0 target verification, one group canary, stability matrix, release, continuous authorization and exact-tag Runtime promotion.
