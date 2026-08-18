# Weixin iLink Notification Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans only for the currently approved Gate. Do not batch or auto-advance across Gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely move the Mac mini Alert notification transport from the currently running v1.4.2 WeCom Runtime to the approved four-recipient Tencent iLink direct-DM design after structural and long-idle canary evidence passes.

**Architecture:** The released guiyi code owns a notification-only `com.guiyi.quant-weixin-context` process and single-shot sender. OpenClaw remains installed only as pinned CLI/Node/plugin control-plane tooling; no OpenClaw Gateway runs. Every real install/login/recipient mutation/canary/release/continuous-authorization/Runtime-promotion operation is a separate Lane 3 Gate.

**Tech Stack:** macOS launchd, guiyi exact-tag Runtime worktree, OpenClaw 2026.8.1 + Node 24.15.0, `@tencent-weixin/openclaw-weixin` 2.4.6, Tencent iLink.

**Spec:** `docs/superpowers/specs/2026-08-18-weixin-ilink-direct-notification-design.md`

**Code Plan:** `docs/superpowers/plans/2026-08-18-weixin-ilink-notification-code.md`

## Global Constraints

- This plan begins only after the Lane 2 code plan is verified and integrated to `develop` with conclusion `允许集成 develop`.
- **Every D2-D9 mutation needs a fresh, scope-specific user instruction immediately before that Gate.** A pass/fail does not authorize retry or the next Gate.
- Default Lane 3 dispatch: **Sol, high reasoning, new session, Plan-only before mutation, independent review where appropriate**.
- No Gate authorizes orders; `auto_order=false` remains invariant.
- No Gate authorizes Scope mutation unless that Gate explicitly says so. This rollout does not change existing Rule scopes.
- No Gateway, Agent, LLM inbound, slash command, notification retry/replay/backfill/outbox/queue, or WeCom fallback may be introduced during rollout.
- Production v1.4.2 WeCom Alert Runtime remains untouched until D9.
- Real recipient ids/tokens/context tokens are never copied into Git, chat, screenshots, receipts, or logs. Human-facing evidence uses aliases and aggregate counts only.

---

### Gate D2: Install pinned OpenClaw/Node/plugin tools on the expansion disk

**Lane:** Lane 3 — filesystem/tooling/config mutation outside the repository.

**Human Gate required:** User must explicitly authorize installation of the exact OpenClaw/Node/Tencent-plugin tools under `/Volumes/扩展盘/openclaw`, with no login, message send, launchd Gateway, or guiyi Runtime switch.

- [ ] **Step 1: Before mutation, read current code/config identity**

Read only:

```bash
cat deploy/openclaw/versions.json
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
```

Expected exact contract from the approved code plan:

```text
OpenClaw 2026.8.1
Node 24.15.0
openclaw-weixin 2.4.6
```

If `versions.json` differs, stop and review compatibility before installing. Do not silently substitute `latest`.

- [ ] **Step 2: Obtain the D2 execution authorization**

The authorization must identify:

```text
operation: install pinned OpenClaw/Node/openclaw-weixin tooling
target: local Mac mini, /Volumes/扩展盘/openclaw
boundary: no QR login, no send, no launchd Gateway, no guiyi Runtime switch
```

Without it, stop.

- [ ] **Step 3: Create only the approved external directories**

```bash
mkdir -p \
  /Volumes/扩展盘/openclaw/runtime \
  /Volumes/扩展盘/openclaw/state \
  /Volumes/扩展盘/openclaw/cache/npm \
  /Volumes/扩展盘/openclaw/tmp
chmod 700 /Volumes/扩展盘/openclaw /Volumes/扩展盘/openclaw/state
```

- [ ] **Step 4: Install exact OpenClaw + Node via the official rootless installer**

Run through the repository-reviewed helper from the approved code tag/branch, not an ad-hoc installer command. The helper must resolve to the equivalent exact install contract:

```text
prefix=/Volumes/扩展盘/openclaw/runtime
openclaw=2026.8.1
node=24.15.0
onboard=false
```

It must not start Gateway or onboarding.

- [ ] **Step 5: Install and enable the exact Tencent plugin using the pinned OpenClaw CLI**

Run with these environment roots:

```bash
export OPENCLAW_PREFIX=/Volumes/扩展盘/openclaw/runtime
export OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state
export OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json
export OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json
export npm_config_cache=/Volumes/扩展盘/openclaw/cache/npm
export TMPDIR=/Volumes/扩展盘/openclaw/tmp
```

Then the exact plugin operation is:

```bash
/Volumes/扩展盘/openclaw/runtime/bin/openclaw \
  plugins install npm:@tencent-weixin/openclaw-weixin@2.4.6 --pin

/Volumes/扩展盘/openclaw/runtime/bin/openclaw \
  config set plugins.entries.openclaw-weixin.enabled true
```

- [ ] **Step 6: Read back identity and prove no Gateway service was created**

```bash
/Volumes/扩展盘/openclaw/runtime/bin/openclaw --version
/Volumes/扩展盘/openclaw/runtime/bin/openclaw plugins inspect openclaw-weixin --json
ls -l /Volumes/扩展盘/openclaw/runtime/tools/node/bin/node
launchctl print "gui/$UID/ai.openclaw.gateway" >/dev/null 2>&1 && exit 1 || true
launchctl print "gui/$UID/com.guiyi.quant-openclaw" >/dev/null 2>&1 && exit 1 || true
```

Expected: exact versions/paths, no OpenClaw Gateway launchd label.

**D2 conclusion:** `允许继续实现` only in the sense of continuing rollout to the next separately authorized Gate; do not auto-run D3.

---

### Gate D3A: QR login the single Weixin bot account

**Lane:** Lane 3 — credential/auth mutation.

**Human Gate required:** Fresh authorization for one QR-login attempt on the local Mac mini using the pinned plugin; no recipient registration, no canary, no Runtime switch.

- [ ] **Step 1: Confirm no OpenClaw Gateway is running**

Use launchctl/process read-only checks. Any active Gateway blocks this design until removed/reviewed.

- [ ] **Step 2: Obtain D3A authorization**

Scope:

```text
operation: one QR login attempt
target: pinned openclaw-weixin account state under /Volumes/扩展盘/openclaw/state
boundary: save bot credential only; no recipient registration/send/Runtime switch
```

- [ ] **Step 3: Run the official login command with expansion-disk environment**

```bash
OPENCLAW_PREFIX=/Volumes/扩展盘/openclaw/runtime \
OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state \
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json \
OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json \
TMPDIR=/Volumes/扩展盘/openclaw/tmp \
/Volumes/扩展盘/openclaw/runtime/bin/openclaw \
  channels login --channel openclaw-weixin
```

The user scans and confirms in WeChat. Do not copy QR/token/account ids into chat or Git.

- [ ] **Step 4: Read back only sanitized account readiness**

Use the repository probe/read-only tooling. Required result:

```text
exactly_one_indexed_account=true
account_configured=true
token_present=true
```

Do not print the account id/token.

**D3A conclusion:** stop. QR success does not authorize registration.

---

### Gate D3B: Register the four approved recipients by exact one-time challenge

**Lane:** Lane 3 — recipient notification-scope mutation.

**Human Gate required:** Fresh authorization to build one recipient registry containing aliases `owner`, `member_2`, `member_3`, `member_4` for the currently logged-in single bot account. This Gate does not authorize sending Alert/canary messages.

- [ ] **Step 1: Confirm context monitor is not running**

```bash
launchctl print "gui/$UID/com.guiyi.quant-weixin-context" >/dev/null 2>&1 && exit 1 || true
```

This is a hard exclusion: registration and monitor may not concurrently consume `getUpdates`.

- [ ] **Step 2: Obtain D3B authorization for the exact four aliases**

If the user authorizes fewer/different aliases, stop and revise the scope. Do not infer recipients from prior messages.

- [ ] **Step 3: Register `owner`**

Run from the verified `develop` code checkout/worktree:

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json \
  uv run --project services/quant-api guiyi runtime weixin-register --alias owner
```

The command shows a one-time challenge. Only the intended owner sends that exact challenge to the Bot. User-facing completion must show only alias/status.

- [ ] **Step 4: Repeat sequentially for `member_2`, `member_3`, `member_4`**

Use the same command with each exact alias. Do not overlap registrations. If any one attempt fails/times out, the D3B attempt is consumed; stop and obtain new authorization before retrying the failed registration.

- [ ] **Step 5: Read back the private registry without displaying targets**

Use a repository command/test helper that outputs only:

```text
registry_valid=true
account_consistent=true
enabled_recipient_count=4
aliases=owner,member_2,member_3,member_4
unique_targets=4
mode=0600
```

If any field differs, `阻塞`.

**D3B conclusion:** stop. Four registered recipients do not authorize a canary.

---

### Gate D3C: Activate the development WeixinContextMonitor only

**Lane:** Lane 3 — local Runtime/launchd mutation.

**Human Gate required:** Fresh authorization to load only `com.guiyi.quant-weixin-context` from the identified `develop` checkout for context maintenance. No Alert Runtime switch and no message send.

- [ ] **Step 1: Verify code/tests were already accepted and current checkout is clean**

Read branch/status/commit. The commit must be from the reviewed D1 lineage.

- [ ] **Step 2: Obtain D3C authorization**

Scope exactly:

```text
operation: load/reload com.guiyi.quant-weixin-context only
target: local Mac mini development checkout
boundary: no com.guiyi.quant-alert switch, no canary/send
```

- [ ] **Step 3: Load the context monitor through the repository installer**

```bash
GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1 \
  scripts/ops/macos/install-local-services.sh --confirm-weixin-context
```

- [ ] **Step 4: Read back process identity/status**

```bash
scripts/ops/macos/local-services-status.sh
```

Required privacy-safe evidence:

```text
weixin_context loaded/running
weixin_context root/commit == current approved develop checkout
weixin_context status=ok
recipient_count=4
last_poll_at fresh
```

No target/account/body/token output.

**D3C conclusion:** stop. Monitor activation does not authorize canary or Alert Runtime switch.

---

### Gate D4: Read-only structural preflight

**Lane:** Lane 2/read-only.

No mutation authorization is needed, but do not turn this into a send.

- [ ] **Step 1: Run project status and adapter probe**

Use the released/reviewed read-only commands. Required facts:

```text
OpenClaw exact version = 2026.8.1
plugin exact version = 2.4.6
plugin private seam compatible
exactly one configured account
recipient registry valid
recipient_count=4
context monitor fresh/ok
context_token present=4/4
```

- [ ] **Step 2: Record conclusion only as structural readiness**

Allowed conclusion:

```text
STRUCTURALLY_READY=true
```

Forbidden conclusion:

```text
delivered=true
production-ready=true
```

If any structural item fails: `阻塞`.

---

### Gate D5: First real four-person canary

**Lane:** Lane 3 — real notification.

**Human Gate required:** Fresh authorization for exactly one `alert-canary` fan-out to the current four-recipient private registry. No Event/Scope/Runtime mutation.

- [ ] **Step 1: Obtain D5 real-notification authorization**

The user must identify the local Mac mini, current four-recipient registry, fixed canary purpose, and one-attempt boundary.

- [ ] **Step 2: Run exactly one canary**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json \
  uv run --project services/quant-api guiyi runtime alert-canary
```

Do not rerun on partial failure without new authorization.

- [ ] **Step 3: Check system evidence**

Required:

```text
attempted=4
provider_accepted=4
failed=0
```

This is not proof of human delivery.

- [ ] **Step 4: Obtain human receipt confirmation from all four recipients**

Required: four people independently confirm receipt. Record only `4/4 confirmed`, not screenshots/content/ids.

**D5 PASS:** provider accepted 4/4 + human confirmed 4/4. Otherwise `阻塞` until a separately authorized diagnostic/fix cycle.

---

### Gate D6: Silent-window proactive-delivery canary

**Lane:** Lane 3 — real notification.

**Human Gate required:** New one-attempt notification authorization after the silent window.

- [ ] **Step 1: After D5, do not ask any of the four recipients to message the Bot**

Maintain at least **24 hours** with no recipient-originated messages. This is an engineering verification interval, not a Tencent SLA claim.

- [ ] **Step 2: Verify context monitor stayed healthy during the interval**

Read-only status must show fresh polling even though no context refresh was needed.

- [ ] **Step 3: Obtain D6 authorization and run one canary**

Use the same `guiyi runtime alert-canary` command and current frozen four-recipient registry.

- [ ] **Step 4: Require both 4/4 system acceptance and 4/4 human receipt**

If either layer is less than 4/4, final conclusion is **阻塞**: do not release/promote iLink as the sole production channel.

**D6 PASS:** allows release preparation only; it does not authorize release.

---

### Gate D7: Release the verified code to main/tag

**Lane:** Lane 3 — release/main/tag.

**Human Gate required:** Fresh explicit release authorization after re-reading current `STATUS.md`, `AGENTS.md`, the design spec, both plans, D5/D6 evidence, and the actual release candidate commit.

- [ ] **Step 1: Prepare release candidate without mutating main/tag**

Verify the candidate contains the D1 code plan, D5/D6 PASS evidence references if repository policy records them, no real credentials, and no production STATUS claim that Runtime has already switched.

- [ ] **Step 2: Determine the exact next version at release time**

Use the repository's current release/version state at this Gate. The exact semver/tag must be part of the user's D7 authorization; do not pre-authorize or guess it in this plan.

- [ ] **Step 3: Obtain the D7 release authorization**

The user's instruction must name the exact release candidate and exact tag/version. It authorizes only release PR/main merge/annotated tag as defined by current repository release flow; it does not authorize D8 or D9.

- [ ] **Step 4: Execute release and read back**

Verify main, annotated tag peeled commit, release candidate ancestry, and develop synchronization according to the active repository release procedure.

**D7 conclusion:** `允许发布 main/tag` only after successful readback. Stop before D8.

---

### Gate D8: Grant the new bounded continuous iLink notification authorization

**Lane:** Lane 3 — real ongoing notification scope authorization.

This Gate is an explicit user authorization, not a code/config write by itself.

- [ ] **Step 1: Read current Rule scopes and private registry summary**

Read-only evidence must identify:

```text
htdy_original_15m scope_products = current exact DB scope
subing_entry_signal_v1 scope_products = current exact DB scope
recipient aliases = owner,member_2,member_3,member_4
unique recipient targets = 4
channel = openclaw-weixin
```

Do not expose target ids.

- [ ] **Step 2: Obtain explicit continuous authorization**

The authorization must cover exactly:

```text
htdy_original_15m × its current explicit scope_products × openclaw-weixin × current approved 4-person registry
+
subing_entry_signal_v1 × its current explicit scope_products × openclaw-weixin × current approved 4-person registry
```

It does not cover new Rule, changed Scope, changed recipient registry, canary retry, release, Runtime promotion, DB/Canonical, or orders.

- [ ] **Step 3: Record the authorization boundary in the rollout record/status process required by current canon**

Do not mutate Rule Scope or recipient registry. The authorization becomes effective only when D9 promotes the exact approved release Runtime.

**D8 conclusion:** stop. Continuous authorization alone does not switch Runtime.

---

### Gate D9: Promote the approved exact release Runtime

**Lane:** Lane 3 — Runtime promotion.

**Human Gate required:** Fresh explicit Runtime promotion authorization naming the exact D7 tag and local Mac mini. D8 must already exist. D9 itself does not authorize a canary.

- [ ] **Step 1: Preflight exact release and external dependency identity**

Read-only verify:

```text
release tag/peeled commit exact
runtime checkout candidate clean/detached
OpenClaw 2026.8.1
plugin 2.4.6
recipient registry 4 unique approved aliases/targets
context monitor currently healthy
Rule scopes unchanged
DB revision unchanged
no order path / auto_order=false
```

- [ ] **Step 2: Obtain D9 Runtime promotion authorization**

Scope:

```text
operation: promote all required guiyi services to the exact approved tag, including com.guiyi.quant-weixin-context and Alert
target: local Mac mini Runtime
boundary: no canary, no DB/Canonical/Scope mutation, no tag/release mutation, no replay/backfill
```

- [ ] **Step 3: Create/switch the exact-tag Runtime worktree using the repository release procedure**

The context-monitor label must be rebound from any development checkout to the exact tag before Alert is started. There may be only one active `getUpdates` consumer for the bot account.

- [ ] **Step 4: Load context monitor first and wait for fresh/ok status**

Only after exact-tag `com.guiyi.quant-weixin-context` reports the exact Runtime root/commit and fresh `last_poll_at` may the script load `com.guiyi.quant-alert`.

- [ ] **Step 5: Load Alert Runtime without sending a canary**

Startup probe must verify 4/4 context tokens before Pub/Sub consumption. No historic Event is replayed.

- [ ] **Step 6: Read back the complete Runtime identity and boundary**

Required:

```text
API/Web/Live/after-market/Alert/WeixinContext roots point to exact approved Runtime
loaded commits equal peeled tag commit
context monitor status=ok/fresh recipient_count=4
Alert Runtime running
Rule scopes unchanged
DB revision unchanged
OpenClaw Gateway absent
auto_order=false
```

Do not send a test message as part of this readback.

- [ ] **Step 7: Update `STATUS.md` only after successful promotion**

Now, and only now, record that active Alert notification transport is iLink direct DM and WeCom has exited active Runtime. Preserve D5/D6 evidence wording as canary evidence, not as delivery SLA.

- [ ] **Step 8: Clean obsolete Runtime worktree only after active references are zero**

Follow current repository Runtime cleanup procedure. Do not delete external OpenClaw state/recipient registry.

**D9 conclusion:** after exact identity/readback passes, `允许 Runtime promotion`.

---

## Post-Promotion Operating Contract

After D9, normal bounded continuous behavior is only:

```text
natural completed Bar
→ approved Rule evaluation
→ new AlertEvent commit
→ current 4-person immutable Runtime snapshot
→ each recipient at most one sendMessage attempt
```

A recipient/session failure is logged by alias/stable code only and is never replayed. If a recipient later messages the Bot, `WeixinContextMonitor` may refresh that approved recipient's context for future natural Alerts; it never replies.

Any recipient add/remove/replace requires a new recipient-scope Gate, context-monitor restart, new D5/D6-style evidence as judged necessary, and updated continuous authorization before it becomes production active.