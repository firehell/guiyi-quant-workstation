# WeChat-Courier Group Notification Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this rollout. Every external mutation is a separate human Gate; do not batch approvals across Gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely migrate the production Alert notification transport from the current exact-tag WeCom Runtime to one fixed WeChat group through the pinned local WeChat-Courier transport, while preserving Alert Event-first/no-retry semantics and proving target verification before any production switch.

**Architecture:** Production remains on the current exact-tag WeCom Runtime until the WeChat-Courier dependency, private target, macOS GUI permissions, no-send target verification, real canary, stability matrix, release, continuous notification scope, and exact-tag Runtime identity have each passed their own Gate. The new sender always uses `primary_alert_group`, strict unique search-result verification, exact chat-title verification, a non-blocking GUI lock, and at most one physical text-send primitive per newly committed AlertEvent.

**Tech Stack:** macOS GUI session, official WeChat.app, Python 3.13 project Runtime, dedicated WeChat-Courier venv, Pillow 11.3.0, AppleScript/System Events, macOS Vision/Swift helpers, launchd, Git worktrees, existing FastAPI/Alert Runtime.

**Spec:** `docs/superpowers/specs/2026-08-18-wechat-courier-group-notification-design.md`

**Code baseline reviewed for rollout:** `b007436d4ee52088cc156d413d2950c9e46573e6`

## Global Constraints

- Current production remains the exact-tag `v1.4.2` Runtime at commit `fb96506493763340e082ed85e8112b60d6670d65` until Gate G8 completes.
- Current production Alert transport remains WeCom until Gate G8 completes; do not remove or mutate the production webhook before then.
- Pinned upstream is exactly `bladydora/WeChat-Courier-macOS@981bd14e238302b2a0e206cb5f28e8e2505bb874`.
- V1 has exactly one notification alias: `primary_alert_group`.
- The real group title exists only in `/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json`; it must never be copied into Git, chat, command argv, logs, screenshots retained for evidence, or rollout notes.
- Private config parent mode is `0700`; file mode is `0600`; both must be owned by the current Runtime user.
- No OpenClaw, Tencent iLink, inbound listener, context monitor, queue, retry, replay, backfill, outbox, provider fallback, or auto-order path is allowed.
- `htdy_original_15m`, `subing_entry_signal_v1`, their current production Scope, Alert two-table schema, DB revision, Market eight-table contract, Canonical, and `auto_order=false` must remain unchanged.
- Every real GUI action is a separate external-operation Gate. `alert-target-verify` is no-send but is **not** readonly: it activates WeChat, searches, clicks, screenshots, and OCRs.
- `runtime alert-canary` is a real message send and always requires its own explicit Gate.
- Failure at any Gate stops the rollout. Do not weaken exact matching, choose the first result, switch to fuzzy matching, send by coordinates only, or add retry to obtain a pass.
- Keep the old `v1.4.2` Runtime worktree intact through Gate G9 so rollback remains available by a new explicit Gate. It is not an active fallback; it is rollback material only.

---

## R2 Final Review Closure — Preconditions for G2

R2 is code review only; it authorizes no external action.

- [ ] Confirm `origin/develop` contains `b007436d4ee52088cc156d413d2950c9e46573e6` or a strict descendant that has been re-reviewed.
- [ ] Confirm `STATUS.md` still records production `v1.4.2` + WeCom and current Rule Scope; do not edit it for planned rollout.
- [ ] Confirm the following contracts remain true:

```text
AlertEvent commit -> one notification attempt -> end
verification failure -> physical send count = 0
send path -> physical send count <= 1
GUI lock busy -> immediate failure, no wait queue
alert-target-verify -> message_sent=false
runtime status exception -> readonly=true
runtime live/alert/canary/target-verify exception -> readonly=false
```

- [ ] Confirm active iLink/OpenClaw code references are zero.
- [ ] Confirm the local D1 verification evidence is available in the completed task report. GitHub CI status is not required to exist, but missing CI must not be misreported as independent CI proof.

**R2 PASS condition:** Critical=`0`, Important=`0`. Minor findings that affect rollout safety must be fixed before G2; cosmetic minors may be recorded without blocking.

---

## Gate G2 — Install Exact WeChat-Courier on the Expansion Disk

**Mutation:** local filesystem + network clone/package installation.

**Does not authorize:** WeChat launch, TCC changes, screenshots, target verification, canary, Runtime switch, release, Scope mutation.

### G2.1 Read-only preflight

- [ ] Read current production state first:

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation
scripts/ops/macos/local-services-status.sh
```

Expected production facts before rollout:

```text
alert.notification_channel=wecom
alert_runtime_enabled=true
production Runtime identity still v1.4.2 / fb965064...
```

- [ ] Confirm target install root is absent or already valid:

```bash
export GUIYI_WECHAT_COURIER_ROOT='/Volumes/扩展盘/wechat-courier'
scripts/ops/macos/install-wechat-courier.sh --check
```

Allowed pre-install output:

```text
status=not_installed
```

If output is `invalid`, stop and inspect the exact root. Do not delete or overwrite an unknown directory.

### G2.2 Human Gate

- [ ] Obtain explicit approval for exactly:

```text
install pinned WeChat-Courier commit 981bd14e238302b2a0e206cb5f28e8e2505bb874
under /Volumes/扩展盘/wechat-courier
and install only the pinned Pillow dependency into its dedicated venv
```

### G2.3 Install

- [ ] Execute once:

```bash
export GUIYI_WECHAT_COURIER_ROOT='/Volumes/扩展盘/wechat-courier'
scripts/ops/macos/install-wechat-courier.sh --confirm-install
```

- [ ] Read back exact identity:

```bash
scripts/ops/macos/install-wechat-courier.sh --check
/usr/bin/git -C "$GUIYI_WECHAT_COURIER_ROOT/source" rev-parse HEAD
/usr/bin/git -C "$GUIYI_WECHAT_COURIER_ROOT/source" status --porcelain
"$GUIYI_WECHAT_COURIER_ROOT/venv/bin/python" - <<'PY'
from PIL import __version__
print(__version__)
PY
stat -f '%Sp %u %N' \
  "$GUIYI_WECHAT_COURIER_ROOT" \
  "$GUIYI_WECHAT_COURIER_ROOT/runtime" \
  "$GUIYI_WECHAT_COURIER_ROOT/tmp" \
  "$GUIYI_WECHAT_COURIER_ROOT/cache/clang"
```

Required evidence:

```text
commit = 981bd14e238302b2a0e206cb5f28e8e2505bb874
source clean
Pillow = 11.3.0
root/runtime/tmp/cache/clang private and current-user owned
```

Do not run upstream watcher, queue, MCP server, `send_wechat.py`, or any example command.

**G2 PASS:** exact clean dependency ready; no WeChat UI action occurred.

---

## Gate G3A — Create the One Private Group Target

**Mutation:** private local config only.

**Does not authorize:** opening/searching WeChat, screenshot/OCR, send, launchd reload, Runtime switch.

- [ ] Ensure the private directory exists with exact ownership/mode:

```bash
umask 077
mkdir -p '/Volumes/扩展盘/guiyi-secrets'
chmod 700 '/Volumes/扩展盘/guiyi-secrets'
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets'
```

- [ ] Obtain explicit approval to set/replace the single notification target.

- [ ] Write the group title from a hidden TTY prompt so the real title is never present in shell history or chat:

```bash
python3 - <<'PY'
from __future__ import annotations
import getpass
import json
import os
from pathlib import Path

parent = Path('/Volumes/扩展盘/guiyi-secrets')
path = parent / 'alert-wechat-group.json'
tmp = parent / '.alert-wechat-group.json.tmp'
target = getpass.getpass('Exact WeChat group title (hidden): ')
if not target or target.strip() != target or '\n' in target or '\r' in target:
    raise SystemExit('invalid target input')
payload = {
    'version': 1,
    'channel': 'wechat-courier',
    'group_alias': 'primary_alert_group',
    'target_chat': target,
}
tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
os.chmod(tmp, 0o600)
os.replace(tmp, path)
os.chmod(path, 0o600)
print('private_group_config_written=true')
PY
```

- [ ] Validate only metadata, never print file contents:

```bash
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json'
```

Expected:

```text
parent=0700 current uid
file=0600 current uid
```

- [ ] Freeze the real group name for V1. If the group is renamed later, the existing Runtime must not hot-reload it; changing the private file requires a new target Gate and Runtime reload.

**G3A PASS:** exactly one private target exists; title remains undisclosed outside the file.

---

## Gate G3B — Prepare macOS GUI Prerequisites and Permissions

**Mutation:** user-controlled macOS privacy permissions and GUI session state.

**Does not authorize:** sending any message.

Upstream exact commit requires: official desktop WeChat logged in, Python 3, Xcode Command Line Tools / Swift, Accessibility, Automation, and Screen Recording for the automation execution context.

- [ ] User manually starts official WeChat.app and confirms it is logged in.
- [ ] Verify toolchain without opening/searching a chat:

```bash
xcode-select -p
/usr/bin/swift --version
'/Volumes/扩展盘/wechat-courier/venv/bin/python' -c 'import PIL; print(PIL.__version__)'
```

- [ ] User manually grants only the macOS permissions required for the current logged-in GUI session. Do **not** edit the TCC database, run privilege-bypass scripts, or use a broad permission reset.
- [ ] Record only boolean evidence:

```text
wechat_logged_in=true
accessibility_prepared=true
screen_recording_prepared=true
automation_prepared=true
swift_available=true
```

Do not record screenshots, contact names, group names, or permission-database dumps.

**G3B PASS:** prerequisites prepared; no target verification and no send yet.

---

## Gate G3C — Interactive No-Send P0 Target Verification

**Mutation:** WeChat GUI, temporary local screenshots/OCR.

**Message send:** forbidden.

- [ ] Obtain explicit approval for one `alert-target-verify` execution.
- [ ] Export only private paths, not the title:

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation
export GUIYI_WECHAT_COURIER_ROOT='/Volumes/扩展盘/wechat-courier'
export GUIYI_ALERT_WECHAT_GROUP_PATH='/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json'
```

- [ ] User manually opens a **non-target** WeChat chat first. This proves the adapter must navigate and verify instead of relying on current-chat state.
- [ ] Execute exactly once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime alert-target-verify
```

Required stdout shape:

```json
{
  "schema_version": 1,
  "command": "runtime.alert-target-verify",
  "status": "ok",
  "readonly": false,
  "group_alias": "primary_alert_group",
  "target_verified": true,
  "message_sent": false
}
```

- [ ] Manually confirm no new message appeared in the target group.
- [ ] Verify Courier temp directory has no retained screenshots:

```bash
find "$GUIYI_WECHAT_COURIER_ROOT/tmp" -maxdepth 1 -type f -print
```

Expected: no retained OCR screenshot files. If files exist, stop; identify exact files and investigate before any canary.

- [ ] If target verification returns `WECHAT_GROUP_TARGET_UNVERIFIED`, `WECHAT_COURIER_BUSY`, or dependency errors, stop. Do not run the command repeatedly until it passes; first diagnose the exact cause.

**G3C PASS:** exact target can be opened and verified with zero message sends.

---

## Gate G4 — First Real Group Canary

**Mutation:** exactly one real WeChat group message.

- [ ] Re-run no-send target verification immediately before canary. If it fails, G4 is blocked.
- [ ] Obtain explicit approval for exactly one canary to `primary_alert_group`.
- [ ] Execute once:

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation
export GUIYI_WECHAT_COURIER_ROOT='/Volumes/扩展盘/wechat-courier'
export GUIYI_ALERT_WECHAT_GROUP_PATH='/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json'
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime alert-canary
```

Expected machine evidence:

```text
attempted=1
automation_completed=1
failed=0
```

`automation_completed=1` is not delivery proof.

- [ ] User manually confirms the canary exists in the intended group and was not sent to any other chat.
- [ ] Verify no retained screenshots remain.
- [ ] Record only alias-level evidence; never record the real group title or screenshot.

**G4 PASS:** machine automation completed and human group receipt both pass.

---

## Gate G5 — Stability Matrix Before Release

Every row is an independent experiment. No automatic retry between rows.

### G5.1 Different chat currently open

- [ ] User opens an unrelated chat.
- [ ] Run one approved `alert-target-verify`.
- [ ] Expected: target verified, `message_sent=false`.

### G5.2 Target not relied on as recent/current chat

- [ ] User navigates away from target and leaves WeChat in a normal non-target state.
- [ ] Run one approved `alert-target-verify`.
- [ ] Expected: successful exact search/title verification, no send.

### G5.3 Near-name ambiguity contract

Real production must not create or rename groups solely to manufacture a risky ambiguity. Use this evidence rule:

- [ ] Engineering tests for exact/near/same-name ambiguity are still green.
- [ ] If a pre-existing near-name group/contact is naturally available, run one approved no-send verify and confirm the exact target remains uniquely selected.
- [ ] If no real near-name candidate exists, record `real_near_name_case=not_available` and retain the deterministic engineering-test evidence. Do not create a temporary production chat just for this test.

### G5.4 WeChat restart / cold app state

- [ ] User manually quits and reopens official WeChat, logs in if required, and opens a non-target chat.
- [ ] Run one approved `alert-target-verify`.
- [ ] If this no-send P0 passes, obtain a separate approval for one canary and run it once.
- [ ] Human confirms canary reached only the target group.

### G5.5 GUI lock / concurrency

No real second send is required. Use the D1 engineering evidence plus one read-only process check:

- [ ] Confirm no second Courier automation process is already active before canary/P0.
- [ ] Retain the existing engineering test proving lock contention yields `WECHAT_COURIER_BUSY` and starts no child.

### G5.6 Privacy residue

- [ ] After each P0/canary, verify `$GUIYI_WECHAT_COURIER_ROOT/tmp` contains no retained screenshots.
- [ ] Confirm application logs contain only stable error codes/alias and do not contain OCR/raw target text.

**G5 PASS:** all required rows pass; no fuzzy fallback or message retry was introduced.

---

## Gate G6 — Release the Verified Candidate

**Mutation:** GitHub main + annotated tag only.

**Does not authorize:** Runtime promotion or continuous group sends.

- [ ] Read back current `origin/main`, `origin/develop`, current latest release tag, and repository version files.
- [ ] Resolve the next release version according to the repository's existing release policy. The exact version is a required human Gate input; if not explicitly approved, stop.
- [ ] Re-run the full D1/Courier verification on the release candidate, including secret scan, Alert/Courier pytest, engineering tests, Ruff, Mypy, shell syntax, render-only/plutil, Web regression suite required by current release policy, and `git diff --check`.
- [ ] Confirm no real WeChat action occurs during release verification.
- [ ] Create the release PR from the verified candidate to `main` using the repository's standard release flow.
- [ ] Obtain explicit approval to merge the exact release candidate.
- [ ] Merge, create the annotated tag on the exact merged commit, and read back:

```text
origin/main commit
annotated tag peeled commit
release candidate ancestry
```

All must identify the same approved code.

- [ ] Synchronize `main -> develop` according to the repository's existing ancestry rule before any new feature work.

**G6 PASS:** release/tag identity proven. Production services still remain on `v1.4.2` WeCom.

---

## Gate G6B — Stage Exact-Tag Runtime and Prove Launchd/Aqua No-Send Compatibility

This gate closes the gap between Terminal P0 and the real launchd GUI execution context. It must occur **after** G6 produces an exact tag and **before** continuous notification authorization.

**Mutation:** create exact-tag Runtime worktree + temporary one-shot LaunchAgent. No message send.

- [ ] Create the new exact-tag Runtime worktree on the expansion disk using the repository's standard Runtime-worktree procedure. Do not load any production service yet.
- [ ] Install/build the release Runtime dependencies exactly as required by the existing release process.
- [ ] Keep the old `v1.4.2` Runtime worktree untouched.
- [ ] Run the exact-tag `alert-target-verify` once interactively from the GUI session using the same Courier root/private config. It must pass before launchd-context testing.
- [ ] Create a **temporary one-shot** user LaunchAgent label `com.guiyi.quant-wechat-courier-p0` that runs the exact-tag CLI command `runtime alert-target-verify` in the logged-in Aqua session. The temporary helper must:

```text
RunAtLoad=true
KeepAlive=false
use the exact-tag Runtime Python
source the existing private Runtime env without printing it
restore the approved GUIYI_WECHAT_COURIER_ROOT / GUIYI_ALERT_WECHAT_GROUP_PATH after sourcing
write only sanitized CLI stdout/stderr to dedicated temporary files
never call runtime alert or alert-canary
```

- [ ] Obtain explicit approval before bootstrapping this temporary LaunchAgent.
- [ ] Bootstrap once, wait for exit, and read the sanitized JSON result.
- [ ] Required result:

```text
target_verified=true
message_sent=false
```

- [ ] Human confirms zero new group messages.
- [ ] Boot out the temporary label if still present and delete only the exact temporary plist/wrapper/output files created by this Gate.
- [ ] Verify no `com.guiyi.quant-wechat-courier-p0` job remains loaded.

If launchd/Aqua context cannot access Accessibility/Screen Recording/Automation, **block production promotion**. Do not treat a Terminal-only P0 as sufficient evidence for unattended Alert Runtime.

**G6B PASS:** exact-tag code works in a production-equivalent user LaunchAgent context with zero sends.

---

## Gate G7 — Continuous WeChat Group Notification Authorization

This Gate is authorization only. It does not itself load the new Runtime.

- [ ] Read the current production Rule Scope from the server/database using existing read surfaces. Do not mutate Scope.
- [ ] Confirm the only code-defined Alert rules remain:

```text
htdy_original_15m
subing_entry_signal_v1
```

- [ ] Confirm the approved notification alias is exactly:

```text
primary_alert_group
```

Do not print or record the real target title.

- [ ] Present the exact authorization scope to the user in alias form:

```text
htdy_original_15m × current explicit scope_products × primary_alert_group
subing_entry_signal_v1 × current explicit scope_products × primary_alert_group
```

- [ ] Obtain explicit approval for **continuous natural Alert sends only**.

The approval does not authorize:

```text
new rules
new/changed Scope
another group
manual/synthetic AlertEvent creation
replay/backfill
canary
order execution
```

If current Scope differs from the previously recorded production Scope unexpectedly, stop and investigate before asking for authorization.

**G7 PASS:** exact continuous notification scope approved.

---

## Gate G8 — Exact-Tag Runtime Promotion

**Mutation:** production launchd Runtime identity.

**No canary is implicit in this Gate.**

### G8.1 Pre-promotion readback

- [ ] Confirm G2–G7 all PASS.
- [ ] Confirm exact release tag/commit and exact Runtime worktree identity.
- [ ] Confirm old `v1.4.2` Runtime remains available for explicit rollback.
- [ ] Confirm Courier exact commit is still clean and pinned.
- [ ] Confirm private config metadata is still `0700/0600`, current-user owned.
- [ ] Confirm production DB revision and Rule Scope are unchanged.
- [ ] Run `alert-target-verify` once more from the exact-tag candidate under the approved GUI context. This is a new explicit no-send Gate action.

### G8.2 Render exact-tag launchd configuration

From the exact-tag Runtime root:

```bash
export GUIYI_WECHAT_COURIER_ROOT='/Volumes/扩展盘/wechat-courier'
export GUIYI_ALERT_WECHAT_GROUP_PATH='/Volumes/扩展盘/guiyi-secrets/alert-wechat-group.json'
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-api.plist
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

- [ ] Read back both rendered plists and prove API/Alert Courier root/config path are identical.
- [ ] Do not print the private file contents.

### G8.3 Promote in dependency order

The new `--confirm-alert-runtime` contract requires the already-installed API plist to carry identical Courier paths. Therefore use this order and stop between stages for health/readback:

1. **Base services:** explicit Gate → `--confirm-load` with the approved Courier paths.
2. **Market Runtime:** explicit Gate → `--confirm-market-runtime` if required by the current exact-tag promotion procedure.
3. **Alert Runtime:** only after G7 authorization and base path readback → explicit Gate → `--confirm-alert-runtime`.

Do not combine these approvals into one blanket authorization.

### G8.4 Read back production identity

- [ ] Run:

```bash
scripts/ops/macos/local-services-status.sh
```

Required final facts:

```text
supervised_runtime_root = new exact-tag Runtime
runtime checkout clean + detached
all required loaded_commit values = exact tag commit
alert.notification_channel=wechat-courier
alert.notification_group_alias=primary_alert_group
external.wechat_courier.commit=981bd14e238302b2a0e206cb5f28e8e2505bb874
external.wechat_courier.status=ready
health.runtime status=ok readonly=true
```

- [ ] Read `/api/runtime/health` and confirm Alert is enabled/healthy and transport structurally configured.
- [ ] Confirm DB revision, Alert Rule code, Scope, Market Runtime universe, and `auto_order=false` remain unchanged.
- [ ] Confirm no canary or synthetic Event was produced by promotion.

### G8.5 Production truth update

Only after all readbacks pass:

- [ ] Update `STATUS.md` to record the actual release/tag/Runtime promotion, the new `wechat-courier` production transport, exact Courier commit, and the fact that WeCom is no longer active.
- [ ] Do not include the real group title.
- [ ] Commit the truth update through the normal post-promotion documentation process.

**G8 PASS:** production exact-tag Runtime uses WeChat-Courier and health/readback is clean.

---

## Gate G8R — Explicit Rollback Path if Promotion Fails

Rollback is never automatic.

If G8 fails after any service switch:

- [ ] Stop and preserve evidence.
- [ ] Obtain explicit rollback approval.
- [ ] Re-point services to the still-preserved exact `v1.4.2` Runtime using the existing production promotion procedure.
- [ ] Restore the old WeCom Runtime identity only; do not copy old code into the new tag.
- [ ] Read back all five service roots/commits, health, Alert channel=`wecom`, DB revision and Scope.
- [ ] Do not send a rollback canary unless separately approved.

Keep the new Courier install/private config for diagnosis unless the user separately authorizes their removal.

---

## Gate G9 — First Natural Production Alert Evidence

G9 proves the real unattended path; it must not manufacture evidence.

- [ ] Wait for the next naturally created `htdy_original_15m` or `subing_entry_signal_v1` AlertEvent inside the already-approved Rule Scope.
- [ ] Do not create synthetic Event, replay Pub/Sub, backfill, retry, or manually trigger an old bar.
- [ ] When a natural Event appears, verify:

```text
AlertEvent persisted once
notification_attempted_at populated according to existing Event-first semantics
application log contains no private target/OCR/message text
human confirms exactly one corresponding group notification
```

- [ ] If no natural Event occurs, keep G9=`pending`; do not change release/promotion facts.
- [ ] If natural Event exists but group notification fails, record the failure and decide separately whether to rollback. Do not resend the old AlertEvent.

### G9.1 Deferred old-Runtime cleanup

Only after at least one natural WeChat-Courier Alert is confirmed, or after the user explicitly accepts operating without that evidence:

- [ ] Obtain a separate cleanup approval.
- [ ] Prove no launchd plist/root/loaded process references the old `v1.4.2` Runtime.
- [ ] Remove only the exact old Runtime worktree using the repository's normal worktree cleanup process.

**G9 PASS:** first natural unattended notification evidence confirmed; old Runtime may then be cleaned up by separate Gate.

---

## Optional Reliability Gate — Controlled Mac Reboot

For year-long unattended operation, a controlled reboot test is recommended after G6B and before G7, but it is operationally disruptive and therefore never implicit.

- [ ] Obtain explicit reboot approval.
- [ ] Before reboot, confirm production remains old WeCom or otherwise record the current Gate state.
- [ ] Reboot the Mac normally; do not alter launchd/TCC databases.
- [ ] After login, user manually confirms WeChat is logged in/available.
- [ ] Read back Courier install identity and permissions state.
- [ ] Run one approved no-send `alert-target-verify` from the intended GUI execution context.
- [ ] If desired, obtain a separate canary approval and run exactly one canary.

Failure blocks unattended-year confidence but does not authorize weakening safety checks.

---

## Rollout Completion Criteria

The migration is complete only when all required evidence is true:

```text
R2 Critical=0 Important=0
G2 pinned Courier exact/clean
G3A private target valid
G3B macOS prerequisites prepared
G3C interactive no-send P0 PASS
G4 one real canary + human receipt PASS
G5 stability matrix PASS
G6 release/tag identity PASS
G6B exact-tag launchd-context no-send P0 PASS
G7 continuous natural-notification scope explicitly approved
G8 exact-tag production promotion + health/readback PASS
STATUS.md records actual Courier production truth without real group title
G9 first natural evidence PASS or remains explicitly pending without fabricated evidence
```

At no point may the rollout claim `delivered`, `read`, or `exactly once`. The strongest machine claim remains `automation_completed=1`; human observation supplies receipt evidence for canary/natural Alert.

---

## Execution Handoff

Execute this plan only with `superpowers:executing-plans` and explicit checkpoints. The immediate next executable step after this plan is **Gate G2 read-only preflight**, followed by a stop for user approval before `--confirm-install`.