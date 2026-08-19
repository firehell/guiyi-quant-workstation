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
- The old v1.4.2 Runtime worktree and old private WeCom credential remain rollback material until G9 natural evidence succeeds; they are not an automatic fallback.
- Guiyi never installs, upgrades, enables/disables, logs in/out, restarts or reconfigures OpenClaw during this rollout. OpenClaw/Clawbot remains externally supervised.
- Guiyi never runs `openclaw message send`; formal sends use only the D1 single-shot seam and Tencent `sendMessageWeixin()` at most once.
- No retry, queue, replay, backfill, outbox, provider failover, WeCom fallback, Courier fallback or synthetic AlertEvent is allowed.
- `htdy_original_15m`, `subing_entry_signal_v1`, current production Scope, Alert schema/Event identity, DB revision, Market eight-table contract, Canonical, Execution Review and `auto_order=false` remain unchanged unless separately gated.
- Real account id, target user id, bot token, context token and real message body never appear in chat/task reports or Git.
- All real targets come only from `/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json`; no runtime target/account override exists.
- Any failed Gate stops rollout. A real canary is never rerun without a new explicit authorization.

---

## Preconditions From G1 / D1 / R1

Before G2 read back:

```text
origin/develop contains D1 Clawbot implementation
D1 required verification PASS
R1 Critical=0 / Important=0
deploy/clawbot/versions.json matches the G1-installed OpenClaw/Node/plugin versions
current production still reports v1.4.2 + WeCom
```

Retain the exact local G1 paths in the rollout shell only:

```text
GUIYI_OPENCLAW_BIN
GUIYI_OPENCLAW_NODE_BIN
GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
GUIYI_OPENCLAW_STATE_DIR
GUIYI_OPENCLAW_CONFIG_PATH
GUIYI_ALERT_CLAWBOT_OWNER_PATH=/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json
```

---

## Gate G2 — Bootstrap and Freeze the One Owner

**Mutation:** one private recipient-scope file. **Does not authorize:** message send, release, Runtime promotion, Scope change or OpenClaw config change.

### G2.1 Read-only discovery

- [ ] Export only exact G1 path values; never export account/user/token/context values manually.
- [ ] Confirm production truth with `scripts/ops/macos/local-services-status.sh`; expected channel remains WeCom.
- [ ] Run:

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

No id/token/context may appear in stdout/stderr. If context is unavailable, stop; the user may use Clawbot normally to refresh it and then repeat only the read-only discovery. Guiyi must not create a context monitor.

### G2.2 Human Gate

- [ ] Obtain explicit approval to write the unique discovered owner to `/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json`.

### G2.3 Write exactly once

- [ ] Ensure `/Volumes/扩展盘/guiyi-secrets` exists, current-user owned, exact mode `0700`.
- [ ] Run once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime clawbot-owner-bootstrap --confirm-write-owner
```

Required public result:

```text
status=ok
readonly=false
channel=openclaw-weixin
owner_alias=owner
owner_written=true
```

- [ ] Validate metadata only:

```bash
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets'
stat -f '%Lp %u %N' '/Volumes/扩展盘/guiyi-secrets/alert-clawbot-owner.json'
```

Required: parent `0700`, file `0600`, both current uid.

**G2 PASS:** immutable owner file exists; zero messages sent.

---

## Gate G3 — Real Zero-Send Clawbot Preflight

**Mutation:** none in Guiyi. **Message send:** forbidden.

- [ ] Obtain approval for one real read-only preflight.
- [ ] Run once:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
  uv run --offline --project services/quant-api \
  guiyi runtime clawbot-preflight
```

Required result:

```text
status=ok
readonly=true
channel=openclaw-weixin
owner_alias=owner
account_configured=true
context_available=true
would_send=false
```

- [ ] Confirm no new WeChat message appeared and Guiyi logs contain only alias/stable codes.

Dependency/version/account/context failure blocks G4. Never send without context or loosen owner matching.

**G3 PASS:** exact owner/account/context ready, physical send count 0.

---

## Gate G4 — First Real Single Clawbot Canary

**Mutation:** exactly one Clawbot direct message.

- [ ] Run `clawbot-preflight` immediately before canary; failure blocks G4.
- [ ] Obtain explicit authorization for exactly one canary to `owner`.
- [ ] Run once:

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

`provider_accepted=1` is not delivered/read proof.

- [ ] User manually confirms exactly one canary arrived in the intended Clawbot direct chat.
- [ ] No repeat canary without a new explicit authorization.

**G4 PASS:** one machine acceptance + one human receipt, no duplicate.

---

## Gate G5 — Stability Before Release

No automatic retries; any real send needs a distinct approval.

### G5.1 Normal Clawbot context refresh

- [ ] User talks to Clawbot normally through WeChat.
- [ ] Run one approved `clawbot-preflight`; require zero-send PASS.

### G5.2 External OpenClaw/Clawbot restart

Guiyi must not restart OpenClaw.

- [ ] User restarts the existing OpenClaw/Clawbot through its normal external mechanism.
- [ ] Confirm normal Clawbot functionality returns.
- [ ] Run `clawbot-preflight`; require persisted/restored account/context PASS.
- [ ] If context is absent, user may send a normal Clawbot message to refresh it, then run a new preflight; do not add Guiyi context/retry logic.

### G5.3 Version-drift rejection

- [ ] Re-read OpenClaw, Node and plugin exact versions and require equality with `deploy/clawbot/versions.json`.
- [ ] Any version drift blocks release until a new compatibility review/code change is made.

### G5.4 Single-shot regression

- [ ] Re-run D1 tests proving context missing=0 send, success=1 send, send failure=1 attempt, child failure no respawn and no public OpenClaw message-send path.

### G5.5 Optional second canary

A second canary is not required just because G5 occurred. Use one only if zero-send evidence cannot resolve a restart/context uncertainty, and only after new explicit one-message authorization.

**G5 PASS:** normal chat/restart/version/single-shot contracts stable.

---

## Gate G6 — Release Exact Clawbot Code

**Mutation:** Git release only. **Does not authorize:** ongoing notifications, Runtime promotion, Scope change or another canary.

**2026-08-19 approved scope revision:** `origin/main..origin/develop` also contains the already-accepted
Market Live stale-feed repair, HTDY chart/UI clarification and their canonical/status updates. The user explicitly
approved releasing the complete accumulated `develop` diff together in G6. Therefore this Gate's independent review
must cover that exact widened scope and confirm that nothing beyond Clawbot + Market Live repair + HTDY UI/canonical
updates is present; the former notification-only review condition no longer applies to this release. Gate ordering,
production `v1.4.2 + WeCom` truth and all G7–G9 authorization boundaries remain unchanged.

- [ ] Re-read `origin/develop`, D1/R1/G2-G5 evidence and run release-candidate verification from a clean worktree.
- [ ] Open normal release PR `develop -> main`; independent review must confirm the exact approved widened scope above.
- [ ] Merge only after verification/review PASS.
- [ ] Create an annotated semver tag chosen at release time; this plan does not preselect the version number.
- [ ] Read back main, tag and peeled commit.

**G6 PASS:** exact release tag exists; production is still v1.4.2 + WeCom.

---

## Gate G7 — Continuous Natural Alert Notification Authorization

- [ ] Read production Rule registry and exact current Scope at Gate time; do not assume `jm` if it changed separately.
- [ ] Confirm owner config metadata `owner_alias=owner` without printing ids.
- [ ] Obtain explicit bounded authorization for:

```text
htdy_original_15m × current approved production scope × owner × clawbot-openclaw-weixin
subing_entry_signal_v1 × current approved production scope × owner × clawbot-openclaw-weixin
```

Authorization covers only newly created natural AlertEvents after G8. It does not authorize new Rules/Scopes/owner replacement, synthetic Event, replay/backfill, canary retry, release, Runtime promotion, DB/Canonical/order changes.

Any later owner replacement is a new recipient-scope Gate and requires Runtime restart.

**G7 PASS:** bounded continuous authorization exists.

---

## Gate G8 — Exact-Tag Runtime Promotion

**Mutation:** Guiyi production Runtime only; OpenClaw remains externally owned and untouched.

### G8.1 Preflight

- [ ] Require G6 tag + G7 continuous authorization.
- [ ] Require fresh `clawbot-preflight` PASS.
- [ ] Require dependency versions equal released manifest and owner config valid `0600/current uid`.
- [ ] Require DB revision, Rule registry/Scope, execution-review roll state and `auto_order=false` unchanged.
- [ ] Create/verify clean detached exact-tag Runtime worktree through the existing promotion procedure; preserve old v1.4.2 worktree as rollback material.

### G8.2 Render exact paths

Export exact G1/G5 local dependency paths and owner path, then:

```bash
scripts/ops/macos/install-local-services.sh --render-only
plutil -lint .run/launchd/com.guiyi.quant-api.plist
plutil -lint .run/launchd/com.guiyi.quant-alert.plist
```

Confirm API/Alert plists carry identical six Clawbot paths; never print owner-file contents.

### G8.3 Promote the full supervised Runtime in one bounded Gate

Use the existing service promotion sequence from the exact-tag Runtime. Temporary mixed roots during the bounded switch are not final evidence.

Required final state:

```text
API/Web/Live/after-market/Alert all same new exact tag/commit
Market activation preserved
Alert activation preserved
notification source = clawbot-openclaw-weixin
OpenClaw external dependency ready
owner config ready
DB revision unchanged
Rule Scope unchanged
execution-review roll unchanged
auto_order=false
```

No canary is implied by promotion.

### G8.4 Final read-back

```bash
scripts/ops/macos/local-services-status.sh
```

Require:

```text
alert.notification_channel=clawbot-openclaw-weixin
alert.notification_owner_alias=owner
external.openclaw.status=ready
external.openclaw_weixin.status=ready
external.clawbot_owner_config=ready
health.runtime status=ok readonly=true
all supervised roots/commits equal exact release tag
```

Also verify `/api/runtime/health`, DB revision, Rule Scope and Runtime version. Only after successful read-back may current `STATUS.md` production facts change from WeCom to Clawbot; historical WeCom text stays.

**G8 PASS:** production exact-tag Runtime uses Clawbot as its only active notification transport.

---

## Gate G9 — First Natural Alert Evidence and Final WeCom Retirement

No synthetic Event, replay, backfill or manual Alert injection.

**Execution closeout (2026-08-19):** production observation truth remained
`post_g8_natural_event_count=0`; no natural notification-attempt or receipt evidence exists. The owner
explicitly chose not to wait for G9.1, accepted that evidence gap, and separately authorized G9.3 cleanup.
After fail-closed zero-reference checks, the obsolete `v1.4.2` worktree and private WeCom credential were
removed. The rollout records G9 as `COMPLETED_WITH_NATURAL_EVIDENCE_WAIVER`, not as a fabricated natural
Alert PASS. Historical criteria below remain unchanged as the approved baseline.

### G9.1 Natural evidence

- [ ] Wait for the next natural Event in an already-authorized Rule/Scope.
- [ ] Verify Event exists before notification-attempt evidence, preserving Event-first.
- [ ] Verify Guiyi logs contain only alias/stable facts.
- [ ] User confirms the matching Clawbot message arrived exactly once.

If no natural Event occurs, leave G9 pending; do not fabricate evidence. G8 remains a separate completed fact if it passed.

### G9.2 Natural-send failure contract

If notification fails: Event remains committed, no retry/replay/backfill, old Event is never resent. A defect may require a new code/release/promotion cycle; never restore automatic WeCom fallback.

### G9.3 Explicit final WeCom cleanup Gate

After at least one natural Clawbot Alert is confirmed, obtain separate cleanup approval to:

```text
remove obsolete v1.4.2 rollback Runtime worktree after formal references are zero
remove stale private WECOM_WEBHOOK_URL/WeCom credential from production env/secrets
verify no launchd plist/process references old Runtime
verify current source/config contains no active WeCom transport
```

Do not rewrite historical Git/STATUS evidence.

**Approved-baseline G9 PASS criterion:** natural Clawbot evidence exists and obsolete WeCom operational
rollback material/credential is retired. The actual closeout used the explicit owner waiver recorded above;
only the cleanup half is evidenced.

---

## Rollback Contract

Before G8, production is still WeCom so no migration rollback is needed. After G8 and before G9 cleanup, old v1.4.2 may be used only under a new explicit rollback Gate; there is no automatic provider fallback. Rollback must rebind the complete supervised Runtime consistently and re-read DB/Scope/runtime identity.

After G9 cleanup, any future WeCom return requires a new design/release; the old webhook secret and active implementation are intentionally retired.

---

## Final Production Contract

```text
completed Bar
→ approved Rule evaluation
→ new AlertEvent commit
→ frozen owner snapshot
→ exact context lookup
→ sendMessageWeixin at most once
→ end
```

Final active system contains no WeCom transport, WeChat-Courier transport, OpenClaw public message-send path, notification queue/retry/replay/backfill/outbox, recipient fan-out or automatic order path.
