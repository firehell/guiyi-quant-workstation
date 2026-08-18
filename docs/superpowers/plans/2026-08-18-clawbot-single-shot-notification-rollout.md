# Clawbot Single-Shot Alert Notification Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this rollout. Every real external mutation or message send is a separate human Gate; never batch approvals across Gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move production Alert notifications from the current exact-tag WeCom Runtime to the already-installed OpenClaw Weixin Clawbot, sending every newly committed approved AlertEvent to exactly one owner with at most one physical `sendMessageWeixin()` attempt and no retry/replay/fallback.

**Architecture:** D1 code has already frozen the exact installed OpenClaw/Node/openclaw-weixin compatibility contract and replaced Courier with a single private seam. Rollout then writes the one private owner identity, proves zero-send account/context readiness, performs a single real canary, validates stability, releases an exact tag, separately authorizes ongoing natural Alert notifications, promotes all Guiyi services to that exact tag, and finally waits for the first natural Clawbot Alert before retiring the old WeCom rollback material.

**Tech Stack:** existing macOS Guiyi Runtime, existing OpenClaw Gateway/Clawbot installation, Tencent `openclaw-weixin`, Python/Node single-shot seam, launchd, Git exact-tag worktrees.

**Spec:** `docs/superpowers/specs/2026-08-18-clawbot-single-shot-notification-design.md`

**Code plan:** `docs/superpowers/plans/2026-08-18-clawbot-single-shot-notification-code.md`

## Global Constraints

- Enter this plan only after D1/R1 verdict is `D1 CLAWBOT CODE PASS` with Critical=`0`, Important=`0`.
- Current production stays exact-tag `v1.4.2` / `fb96506493763340e082ed85e8112b60d6670d65` + WeCom until Gate G8 completes.
- The old v1.4.2 Runtime worktree and the old private WeCom credential remain rollback material until G9 natural evidence succeeds; they are not an automatic fallback.
- Guiyi never installs, upgrades, enables/disables, logs in/out, restarts or reconfigures OpenClaw during this rollout. OpenClaw/Clawbot remains externally supervised by its existing setup.
- Guiyi never runs `openclaw message send`; formal sends use only the D1 single-shot seam and Tencent `sendMessageWeixin()` at most once.
- No retry, queue, replay, backfill, outbox, provider failover, WeCom fallback, Courier fallback or synthetic AlertEvent is allowed.
- `htdy_original_15m`, `subing_entry_signal_v1`, current production Scope, Alert schema/Event identity, DB revision, Market eight-table contract, Canonical, Execution Review and `auto_order=false` must remain unchanged unless a separate user Gate explicitly changes them.
- Real account id, target user id, bot token, context token and real message body must never be printed into chat/task reports or committed to Git.
- All real notification targets are derived only from `/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json`; no runtime `--target`/`--account` override exists.
- Any failed Gate stops the rollout. Do not rerun a real canary without a new explicit authorization.

---

## Preconditions From G1 / D1 / R1

Before G2, read back:

```text
origin/develop contains the D1 Clawbot implementation
D1 verification all required checks passed
R1 Critical=0 / Important=0
deploy/clawbot/versions.json matches the actual installed OpenClaw/Node/plugin versions discovered in G1
current production status still reports v1.4.2 + WeCom
```

Also retain the exact local paths discovered in G1 for the rollout shell environment:

```text
GUIYI_OPENCLAW_BIN
GUIYI_OPENCLAW_NODE_BIN
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
GUIYI_OPENCLAW_STATE_DIR
GUIYI_OPENCLAW_CONFIG_PATH
GUIYI_ALERT_CLAWBOT_OWNER_PATH=/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json
```

These paths are local operational facts, not Git content.

---

## Gate G2 — Bootstrap and Freeze the One Owner

**Mutation:** writes one private recipient-scope file.

**Does not authorize:** sending a message, release, Runtime promotion, Scope changes, OpenClaw configuration changes.

### G2.1 Read-only discovery

- [ ] Export only the exact G1 path values in the current shell. Do not export account/user/token/context values.
- [ ] Confirm current production first:

```bash
scripts/ops/macos/local-services-status.sh
```

Expected: production still reports WeCom.

- [ ] Run the owner bootstrap in discovery mode only:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime clawbot-owner-bootstrap
```

Required public result:

```text
status=ready
readonly=true
channel=openclaw-weixin
owner_alias=owner
account_count=1
owner_candidate_count=1
context_available=true
owner_written=false
```

No id/token/context may appear in stdout/stderr.

If context is unavailable, stop. The user may use the Clawbot normally from WeChat to refresh context, then a new read-only discovery may be run. Guiyi must not start a getUpdates monitor or alter OpenClaw.

### G2.2 Human Gate

- [ ] Obtain explicit approval for exactly:

```text
write the unique currently discovered Clawbot owner identity to
/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json
```

This is a notification-recipient scope mutation.

### G2.3 Write owner once

- [ ] Ensure `/Volumes/扩展盘/guiyi-secrets` exists, is current-user owned and exact mode `0700`.
- [ ] Run once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime clawbot-owner-bootstrap --confirm-write-owner
```

Expected public result:

```text
status=ready|ok
readonly=false
owner_alias=owner
owner_written=true
```

- [ ] Validate only metadata, never file contents:

```bash
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets'
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json'
```

Required: parent `0700`, file `0600`, both current uid.

**G2 PASS:** one immutable owner config exists; zero messages sent.

---

## Gate G3 — Real Zero-Send Clawbot Preflight

**Mutation:** none in Guiyi; read-only account/context/provider readiness.

**Message send:** forbidden.

- [ ] Obtain approval for one real preflight read against the existing Clawbot state.
- [ ] Run exactly once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime clawbot-preflight
```

Required public result:

```text
status=ok
readonly=true
channel=openclaw-weixin
owner_alias=owner
account_configured=true
context_available=true
would_send=false
```

- [ ] Confirm there is no new WeChat message caused by this command.
- [ ] Confirm Guiyi logs contain only alias/stable codes and no owner/account/target data.

If dependency version, account identity or context is invalid, stop. Do not weaken the owner match or call send without context.

**G3 PASS:** exact owner/account/context are ready and physical send count is zero.

---

## Gate G4 — First Real Single Clawbot Canary

**Mutation:** exactly one Clawbot direct message to the frozen owner.

- [ ] Run `clawbot-preflight` immediately before the canary. If it fails, G4 is blocked.
- [ ] Obtain explicit approval for exactly one real canary to `owner`.
- [ ] Execute once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime alert-canary
```

Required machine evidence:

```text
attempted=1
provider_accepted=1
failed=0
failed_aliases=[]
```

`provider_accepted=1` is not read/delivery proof.

- [ ] User manually confirms the canary arrived in the intended Clawbot direct chat and only once.
- [ ] Do not repeat the canary merely to collect more evidence. A second canary requires a new explicit Gate.

**G4 PASS:** one machine send accepted + one human receipt confirmation, no duplicate.

---

## Gate G5 — Stability Checks Before Release

No automatic retries. Each real send, if any, requires its own approval.

### G5.1 Normal Clawbot chat refresh

- [ ] User sends a normal message to the Clawbot through WeChat and uses it normally.
- [ ] Run one approved `clawbot-preflight`.
- [ ] Expected: context remains available; zero send.

### G5.2 OpenClaw/Clawbot restart by its existing owner mechanism

Guiyi must not restart OpenClaw itself.

- [ ] User restarts the existing OpenClaw/Clawbot through its normal external supervisor/process management.
- [ ] Confirm normal Clawbot functionality returns.
- [ ] Run `clawbot-preflight`.
- [ ] Expected: persisted/restored account/context passes, zero send.

If context does not survive, the user may send the Clawbot a normal message to refresh it, then run a new preflight. Do not add Guiyi retry/context-monitor logic.

### G5.3 Version drift rejection

- [ ] Read current `openclaw --version`, Node version and plugin inspect version again.
- [ ] Require exact match to `deploy/clawbot/versions.json`.
- [ ] If any version changed since G1/D1, stop and perform a new compatibility review/code change; do not silently accept drift.

### G5.4 Single-shot engineering evidence

- [ ] Re-run the D1 node/Python tests proving context missing=0 send, success=1 send, failure=1 attempt, timeout/crash no respawn and no public `openclaw message send` path.

### G5.5 Optional second canary only if justified

A second real canary is not required solely because G5 occurred. If restart/context behavior creates uncertainty that zero-send preflight cannot resolve, obtain a new explicit one-message approval and run one canary; otherwise record `second_canary=not_required`.

**G5 PASS:** normal chat/restart/version-drift/single-shot contracts are stable.

---

## Gate G6 — Release Exact Clawbot Code

**Mutation:** Git release only.

**Does not authorize:** ongoing notification, Runtime promotion, Scope changes, another canary.

- [ ] Re-read `origin/develop`, D1/R1/G2-G5 evidence and run release-candidate verification from a clean task/release worktree.
- [ ] Open the normal release PR from `develop` to `main` according to repository workflow.
- [ ] Independent release review must confirm notification transport only; no evaluator/Scope/DB/Canonical/order change.
- [ ] Merge only after review/verification passes.
- [ ] Create an annotated semver tag determined at release time; do not pre-bake a version number in this rollout plan.
- [ ] Read back `main`, annotated tag and peeled commit identity.

**G6 PASS:** exact release tag exists; production Runtime is still v1.4.2 + WeCom.

---

## Gate G7 — Continuous Natural Alert Notification Authorization

This is the authorization that permits future natural AlertEvents to send to the frozen owner. It is independent of release and Runtime promotion.

- [ ] Read the production Alert Rule registry and current exact Scope at Gate time. Do not assume Scope is still `jm` if it has changed through a separately approved workflow.
- [ ] Read owner config metadata and confirm `owner_alias=owner`; do not print ids.
- [ ] Obtain explicit bounded authorization for exactly:

```text
htdy_original_15m × its current approved production scope × owner × clawbot-openclaw-weixin
subing_entry_signal_v1 × its current approved production scope × owner × clawbot-openclaw-weixin
```

Authorization includes only newly created natural AlertEvents after G8 promotion.

It does **not** authorize:

```text
new Rule
new product Scope
new recipient/owner
owner replacement
manual/synthetic Event
replay/backfill
canary retry
release
Runtime promotion
DB/Canonical/order changes
```

Any later owner file replacement is a new recipient-scope Gate and requires Runtime restart/re-read.

**G7 PASS:** bounded continuous notification authorization exists.

---

## Gate G8 — Exact-Tag Runtime Promotion to Clawbot

**Mutation:** Guiyi production Runtime only. OpenClaw remains externally owned and untouched.

### G8.1 Preflight

- [ ] Require G6 exact tag and G7 continuous authorization.
- [ ] Require current `clawbot-preflight` PASS immediately before promotion.
- [ ] Require exact dependency versions still match the released manifest.
- [ ] Require owner config valid, `0600`, current uid.
- [ ] Require current DB revision, Rule registry/Scope and `auto_order=false` match pre-promotion evidence.
- [ ] Create/verify a clean detached exact-tag Runtime worktree using the project's existing Runtime promotion procedure. Preserve the old `v1.4.2` worktree for rollback material.

### G8.2 Render the new exact paths

Export the exact local G1/G5 dependency paths and owner config path. Run render-only first:

```bash
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-api.plist
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

Read the rendered plist values and confirm API/Alert receive exactly the same six Clawbot paths. Never print owner-file contents.

### G8.3 Promote services within one bounded Gate

Use the existing service promotion sequence from the exact-tag Runtime. The bounded Gate may temporarily have mixed roots while services are being switched; do not treat that transient state as final evidence.

Required final state:

```text
API/Web/Live/after-market/Alert all point at the same new exact tag/commit
Market activation preserved
Alert activation preserved
new Alert source identity = clawbot-openclaw-weixin
OpenClaw external dependency ready
owner config ready
DB revision unchanged
Rule Scope unchanged
execution-review roll state unchanged
auto_order=false
```

No canary is implied by promotion. Do not send a test message during G8.

### G8.4 Read-back

Run:

```bash
scripts/ops/macos/local-services-status.sh
```

Require sanitized final evidence:

```text
alert.notification_channel=clawbot-openclaw-weixin
alert.notification_owner_alias=owner
external.openclaw.status=ready
external.openclaw_weixin.status=ready
external.clawbot_owner_config=ready
health.runtime status=ok readonly=true
all supervised roots/commits identical to exact release tag
```

Also verify `/api/runtime/health`, DB revision, Rule Scope and Runtime version.

Only after all G8 read-back succeeds may `STATUS.md` current-runtime facts be updated from WeCom to Clawbot. Historical WeCom sections remain historical truth.

**G8 PASS:** production exact-tag Runtime uses Clawbot as the only active notification transport.

---

## Gate G9 — First Natural Alert Evidence and Final WeCom Retirement

G9 must use a natural completed-Bar Alert. No synthetic Event, replay, backfill or manual notification injection.

### G9.1 Wait for natural evidence

- [ ] Wait for the next naturally created Event in an already-authorized Rule/Scope.
- [ ] Verify Event exists in DB before its notification attempt evidence, consistent with Event-first semantics.
- [ ] Verify Guiyi logged only stable alias/error facts.
- [ ] User manually confirms the corresponding Clawbot message arrived once.

If no natural Event occurs, leave G9 `pending`. Do not fabricate evidence; G8 production promotion remains a separate completed fact if it passed.

### G9.2 Failure handling

If the first natural Event notification fails:

```text
Event remains committed
no retry/replay/backfill
old Event is not resent
future new Events continue under the same continuous authorization if Runtime remains healthy
```

A transport defect may justify a new code/release/promotion cycle. Do not re-enable automatic WeCom fallback.

### G9.3 Final WeCom cleanup Gate

Only after at least one natural Clawbot Alert is confirmed, obtain a separate explicit cleanup approval to:

```text
remove the obsolete v1.4.2 rollback Runtime worktree after all formal references are zero
remove the stale private WECOM_WEBHOOK_URL/WeCom credential from the production runtime environment/secrets store
verify no active launchd plist/process references the old Runtime
verify current source/config contains no active WeCom transport
```

Do not rewrite historical Git/STATUS evidence that WeCom was used previously.

**G9 PASS:** natural Clawbot notification evidence exists and obsolete WeCom operational rollback material/credential is explicitly retired.

---

## Rollback Contract

Before G8 completes, rollback is unnecessary because production is still v1.4.2 + WeCom.

After G8 and before G9 final cleanup, the old exact-tag v1.4.2 worktree may be used only by a new explicit rollback Gate. There is no automatic provider fallback. A rollback must rebind the full supervised Runtime consistently, not only the Alert service, and must re-read DB/Scope/runtime identity afterward.

After G9 cleanup, any future rollback to WeCom requires a new design/release; the old webhook secret and active implementation are intentionally retired.

---

## Final Production Contract

After G9:

```text
completed Bar
→ approved Rule evaluation
→ new AlertEvent commit
→ frozen owner snapshot
→ exact context lookup
→ sendMessageWeixin at most once
→ end
```

And the active system contains no:

```text
WeCom transport
WeChat-Courier transport
OpenClaw public message-send path
notification queue/retry/replay/backfill/outbox
recipient fan-out
automatic trading/order path
```
