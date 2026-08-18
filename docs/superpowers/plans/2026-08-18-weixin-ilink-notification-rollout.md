# Weixin iLink Notification Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans only for the currently approved Gate. Do not batch or auto-advance across Gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely move the Mac mini Alert notification transport from the currently running v1.4.2 WeCom Runtime to the approved four-recipient Tencent iLink direct-DM design after structural and long-idle canary evidence passes.

**Architecture:** Released guiyi code owns the notification-only `com.guiyi.quant-weixin-context` process and single-shot sender. OpenClaw is pinned CLI/Node/plugin control-plane tooling only; no Gateway runs. Install/login/recipient mutation/canary/release/continuous-authorization/Runtime-promotion are separate Lane 3 Gates.

**Tech Stack:** macOS launchd, guiyi exact-tag Runtime worktree, OpenClaw 2026.8.1 + Node 24.15.0, `@tencent-weixin/openclaw-weixin` 2.4.6, Tencent iLink.

**Spec:** `docs/superpowers/specs/2026-08-18-weixin-ilink-direct-notification-design.md`

**Code Plan:** `docs/superpowers/plans/2026-08-18-weixin-ilink-notification-code.md`

## Global Constraints

- Start only after D1 code is verified/integrated with conclusion `允许集成 develop`.
- **Every D2-D9 mutation requires a fresh scope-specific user instruction immediately before that Gate.** Pass/fail does not authorize retry or the next Gate.
- Lane 3 default: **Sol, high reasoning, new session, Plan-only before mutation, independent review where appropriate**.
- No Gate changes existing Rule scopes unless explicitly stated; this rollout does not change them.
- No Gateway, Agent, LLM inbound, slash command, notification retry/replay/backfill/outbox/queue, WeCom fallback, or order path.
- Production v1.4.2 WeCom Runtime remains untouched until D9.
- Real recipient/account/token/context values are never copied into Git/chat/screenshots/receipts/logs; human evidence uses aliases/counts.

---

### Gate D2: Install pinned OpenClaw/Node/plugin tools

**Lane:** Lane 3 — external filesystem/tool/config mutation.

**Human Gate:** exact install under `/Volumes/扩展盘/openclaw`; no login/send/Gateway/Runtime switch.

- [ ] **Step 1: Read current pinned identity**

```bash
cat deploy/openclaw/versions.json
scripts/ops/macos/install-openclaw-weixin-tools.sh --check
```

Expected contract:

```text
OpenClaw 2026.8.1
Node 24.15.0
openclaw-weixin 2.4.6
```

If repository identity differs, stop for compatibility review.

- [ ] **Step 2: Obtain D2 authorization**

It must identify operation, local Mac mini, `/Volumes/扩展盘/openclaw`, and no login/send/Gateway/guiyi Runtime switch.

- [ ] **Step 3: Run the repository-reviewed install entry**

```bash
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
  scripts/ops/macos/install-openclaw-weixin-tools.sh --confirm-install
```

The helper is required to install exactly OpenClaw 2026.8.1, Node 24.15.0 and plugin 2.4.6, enable the plugin, and do nothing else.

- [ ] **Step 4: Read back identity and absence of Gateway**

```bash
OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state \
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json \
OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json \
  /Volumes/扩展盘/openclaw/runtime/bin/openclaw --version

OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state \
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json \
OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json \
  /Volumes/扩展盘/openclaw/runtime/bin/openclaw plugins inspect openclaw-weixin --json

ls -l /Volumes/扩展盘/openclaw/runtime/tools/node/bin/node
launchctl print "gui/$UID/ai.openclaw.gateway" >/dev/null 2>&1 && exit 1 || true
launchctl print "gui/$UID/com.guiyi.quant-openclaw" >/dev/null 2>&1 && exit 1 || true
```

Expected: exact versions and no Gateway label.

**Stop.** D2 does not authorize D3.

---

### Gate D3A: QR login the single Bot account

**Lane:** Lane 3 — credential/auth mutation.

**Human Gate:** one QR-login attempt only; no recipient mutation/send/Runtime switch.

- [ ] **Step 1: Read-only confirm no Gateway**

Any running OpenClaw Gateway blocks the design until reviewed/stopped under its own Gate.

- [ ] **Step 2: Obtain D3A authorization**

Scope: save one bot credential under `/Volumes/扩展盘/openclaw/state`; no other mutation.

- [ ] **Step 3: Run official plugin login**

```bash
OPENCLAW_PREFIX=/Volumes/扩展盘/openclaw/runtime \
OPENCLAW_STATE_DIR=/Volumes/扩展盘/openclaw/state \
OPENCLAW_CONFIG_PATH=/Volumes/扩展盘/openclaw/state/openclaw.json \
OPENCLAW_CONFIG=/Volumes/扩展盘/openclaw/state/openclaw.json \
TMPDIR=/Volumes/扩展盘/openclaw/tmp \
  /Volumes/扩展盘/openclaw/runtime/bin/openclaw channels login --channel openclaw-weixin
```

User scans/approves. Do not copy QR/token/account ids into chat/Git.

- [ ] **Step 4: Read back sanitized readiness only**

Required:

```text
exactly_one_indexed_account=true
account_configured=true
token_present=true
```

**Stop.** Login does not authorize recipient registration.

---

### Gate D3B: Register the approved four recipients by challenge

**Lane:** Lane 3 — recipient notification-scope mutation.

**Human Gate:** one bounded registration batch for aliases `owner`, `member_2`, `member_3`, `member_4`; no canary/Alert Runtime.

- [ ] **Step 1: Confirm no context monitor is consuming getUpdates**

```bash
launchctl print "gui/$UID/com.guiyi.quant-weixin-context" >/dev/null 2>&1 && exit 1 || true
```

- [ ] **Step 2: Obtain D3B authorization**

If approved aliases differ, stop and revise scope.

- [ ] **Step 3: Create the approved private registry directory**

```bash
mkdir -p /Volumes/扩展盘/guiyi-secrets
chmod 700 /Volumes/扩展盘/guiyi-secrets
```

Do not create the registry manually; `weixin-register` writes it only after exact challenge match.

- [ ] **Step 4: Register `owner`**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json \
  uv run --project services/quant-api guiyi runtime weixin-register --alias owner
```

The command shows a one-time challenge through its interactive TTY stream. Only the intended user sends that exact challenge to the Bot. Public completion shows alias/status only.

- [ ] **Step 5: Register `member_2`, `member_3`, `member_4` sequentially**

Use the same command with each exact alias. Never overlap registration consumers. If one attempt fails/times out, stop; retry requires a new authorization.

- [ ] **Step 6: Read back registry without ids**

Required:

```text
registry_valid=true
account_consistent=true
enabled_recipient_count=4
aliases=owner,member_2,member_3,member_4
unique_targets=4
mode=0600
```

Any mismatch -> `阻塞`.

**Stop.** Registry completion does not authorize canary.

---

### Gate D3C: Activate development WeixinContextMonitor only

**Lane:** Lane 3 — local launchd Runtime mutation.

**Human Gate:** load only `com.guiyi.quant-weixin-context` from identified `develop` checkout; no Alert switch/send.

- [ ] **Step 1: Verify reviewed D1 lineage and clean checkout**

Read branch/status/commit; no dirty unrelated work.

- [ ] **Step 2: Obtain D3C authorization**

Scope: local Mac mini, context label only, identified develop commit; no Alert/canary.

- [ ] **Step 3: Load context monitor with exact private paths**

```bash
GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1 \
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json \
  scripts/ops/macos/install-local-services.sh --confirm-weixin-context
```

- [ ] **Step 4: Read back identity/status**

```bash
scripts/ops/macos/local-services-status.sh
```

Required: context running, exact reviewed root/commit, status ok, recipient_count=4, fresh poll. No PII.

**Stop.** Context activation does not authorize canary/Alert switch.

---

### Gate D4: Read-only structural preflight

**Lane:** Lane 2/read-only.

- [ ] **Step 1: Run project status and adapter probe**

Required:

```text
OpenClaw=2026.8.1
plugin=2.4.6
private seam compatible
one configured account
registry valid, 4 unique recipients
context monitor fresh/ok
context_token present=4/4
```

- [ ] **Step 2: State only structural conclusion**

Allowed: `STRUCTURALLY_READY=true`. Forbidden: delivered/production-ready. Failure -> `阻塞`.

---

### Gate D5: First real four-person canary

**Lane:** Lane 3 — real notification.

**Human Gate:** exactly one canary fan-out to current 4-person registry; no Event/Scope/Runtime mutation.

- [ ] **Step 1: Obtain D5 authorization**

It must identify local Mac mini, current 4-person registry, fixed canary purpose and one-attempt boundary.

- [ ] **Step 2: Run exactly one canary**

```bash
UV_CACHE_DIR=/private/tmp/guiyi-test-uv-cache \
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw \
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json \
  uv run --project services/quant-api guiyi runtime alert-canary
```

No rerun on partial failure without new authorization.

- [ ] **Step 3: Require system 4/4 provider acceptance**

```text
attempted=4
provider_accepted=4
failed=0
```

- [ ] **Step 4: Require human 4/4 receipt confirmation**

Record only aggregate confirmation, no screenshots/content/ids.

D5 PASS requires both layers 4/4; otherwise `阻塞`.

---

### Gate D6: Silent-window proactive canary

**Lane:** Lane 3 — real notification.

**Human Gate:** a new one-attempt canary authorization after the interval.

- [ ] **Step 1: Keep all four recipients silent for at least 24 hours after D5**

No recipient-originated Bot messages. This is an engineering interval, not Tencent SLA.

- [ ] **Step 2: Read-only verify monitor stayed healthy**

Fresh polling must continue without context refresh.

- [ ] **Step 3: Obtain D6 authorization and run one canary**

Use the same command/current registry.

- [ ] **Step 4: Require 4/4 provider acceptance and 4/4 human receipt**

Any deficit -> **阻塞**; do not make iLink sole production channel.

D6 PASS authorizes only release preparation.

---

### Gate D7: Release verified code to main/tag

**Lane:** Lane 3 — release/main/tag.

**Human Gate:** fresh release authorization after current `STATUS.md`, canonicals, design, plans, D5/D6 evidence and exact candidate review.

- [ ] **Step 1: Prepare candidate without main/tag mutation**

Candidate includes D1 code and verified evidence references; no credentials; no false STATUS claim that Runtime already switched.

- [ ] **Step 2: Determine exact next semver at Gate time**

Use then-current release state. The exact tag/version must be named in D7 user authorization; this plan does not guess it.

- [ ] **Step 3: Obtain D7 authorization and execute current repository release flow**

Authorization covers only release PR/main merge/annotated tag for the exact candidate/version, not D8/D9.

- [ ] **Step 4: Read back main/tag/ancestry/develop synchronization**

Success conclusion: `允许发布 main/tag`. Stop before D8.

---

### Gate D8: Grant bounded continuous iLink notification authorization

**Lane:** Lane 3 — ongoing real notification scope authorization.

- [ ] **Step 1: Read current exact Rule scopes and private registry summary**

Required:

```text
htdy_original_15m current scope_products
subing_entry_signal_v1 current scope_products
aliases=owner,member_2,member_3,member_4
unique_targets=4
channel=openclaw-weixin
```

No target ids displayed.

- [ ] **Step 2: Obtain explicit continuous authorization**

Exact boundary:

```text
htdy_original_15m × current explicit scope_products × openclaw-weixin × current approved 4-person registry
+
subing_entry_signal_v1 × current explicit scope_products × openclaw-weixin × current approved 4-person registry
```

It does not cover new Rule, changed Scope, changed recipients, canary retry, release, promotion, DB/Canonical or orders.

- [ ] **Step 3: Record authorization using current canonical/status process**

Do not mutate Scope/registry. It becomes operational only after D9 exact-tag promotion.

**Stop.** D8 does not switch Runtime.

---

### Gate D9: Promote the approved exact release Runtime

**Lane:** Lane 3 — Runtime promotion.

**Human Gate:** exact D7 tag + local Mac mini; D8 must already exist; no canary implied.

- [ ] **Step 1: Read-only preflight**

Verify exact tag/peeled commit, clean detached candidate, OpenClaw/plugin versions, registry 4 unique recipients, healthy context, unchanged Rule scopes/DB revision, `auto_order=false`.

- [ ] **Step 2: Obtain D9 authorization**

Scope: promote required guiyi services to exact approved tag, including context + Alert; no canary/DB/Canonical/Scope/tag mutation/replay.

- [ ] **Step 3: Create/switch exact-tag Runtime via current repository procedure**

There may be only one `getUpdates` consumer. Rebind context label from development checkout to exact tag before Alert start.

- [ ] **Step 4: Load exact-tag context monitor with same private paths**

The promotion/install command must receive:

```text
GUIYI_OPENCLAW_ROOT=/Volumes/扩展盘/openclaw
GUIYI_ALERT_RECIPIENTS_PATH=/Volumes/扩展盘/guiyi-secrets/alert-weixin-recipients.json
```

Wait for exact-root/commit and fresh/ok context status.

- [ ] **Step 5: Load Alert Runtime without canary**

Startup probe requires 4/4 contexts before Pub/Sub consumption. No historical Event replay.

- [ ] **Step 6: Read back complete identity/boundary**

Required: API/Web/Live/after-market/Alert/Context exact roots/commit, context fresh count4, Alert running, Rule scopes and DB revision unchanged, Gateway absent, `auto_order=false`.

- [ ] **Step 7: Update `STATUS.md` only after successful promotion**

Now record iLink as active and WeCom as retired from active Runtime; D5/D6 remain canary evidence, not SLA.

- [ ] **Step 8: Clean obsolete Runtime worktree only after references are zero**

Do not delete OpenClaw state or recipient registry.

Success conclusion: `允许 Runtime promotion`.

---

## Post-Promotion Contract

```text
natural completed Bar
→ approved Rule evaluation
→ new AlertEvent commit
→ frozen approved 4-person Runtime snapshot
→ each recipient at most one sendMessage attempt
```

Recipient/session failure is never replayed. An approved recipient may later message the Bot; `WeixinContextMonitor` may refresh only that recipient's context for future Alerts and never replies.

Any recipient add/remove/replace requires a new recipient-scope Gate, monitor restart, renewed evidence as required, and updated continuous authorization before production activation.