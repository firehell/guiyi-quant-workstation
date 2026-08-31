# P5 — Active Canonical、OpenSpec、完整验证与 RC Packet 计划

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 3 trusted contract / release readiness。

## Goal

把 P1–P4 已实现并通过 Review 的事实写入职责正确的 active canonical、OpenSpec 和测试导航，运行完整验证并生成 release-candidate evidence packet。P5 不发布 `main`、不创建 tag/Release、不执行 production migration、不切 Runtime、不发送通知。

## Workspace

```text
base: P4 合入后的最新 origin/develop
branch: docs/subing-watch-canonical-release-candidate
worktree: 新 task worktree
integration: develop
PR: Draft PR required
review: independent Sol/high exact-head whole-program Review
human Gate: 允许集成 develop；随后最多允许进入 release candidate
```

## File Map

```text
AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
docs/INDICATOR_KERNEL.md
TESTING.md
openspec/specs/alert-runtime-reliability/spec.md
openspec/specs/subing-watch-alert/spec.md
tests/engineering/test_canonical_consistency.py
```

`STATUS.md` 不在 P5 修改范围。P0 只修正既有 release 事实；新 release、migration、Runtime、canary 和自然 delivery 只有真实发生后才能更新 `STATUS.md`。

## Task 1 — Add failing canonical drift guards

Extend `tests/engineering/test_canonical_consistency.py` before editing docs. Guards must require:

```text
subing_watch_15m_v1 appears in Registry, policy, OpenSpec, PROJECT_SOURCE, DECISIONS and ARCHITECTURE
Watch MA21 is documented as SMA21
Watch scope authority is product
HTDY scope authority remains product_frequency
Watch status key/schema/TTL match implementation
migration code revision is 20260901_0043
subing_strategy_v1 remains Historical/Current/Web research capable
stable production model has two Rules, not three
no retry/queue/outbox/order capability appears
Web is not formula authority
```

The guard must distinguish code capability from deployment fact: migration file existence cannot make `STATUS.md` claim production head `20260901_0043`.

Run RED:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  tests/engineering/test_canonical_consistency.py
```

Expected: failure until canonical/OpenSpec are synchronized.

## Task 2 — Update canonical by document responsibility

### `PROJECT_SOURCE.md`

Record stable product surface only:

- “苏冰盯盘” is the formal owner Alert observation after production cutover;
- formula identity is completed `actual_dominant + 15m`, MACD CROSS + SMA21;
- context labels are advisory and non-gating;
- Session-aware finalized boundary distinguishes normal silence from incomplete Runtime;
- `subing_strategy_v1` remains read-only Historical/Current/Web research capability;
- HTDY remains independent;
- `auto_order=false`.

Do not include release history or current Runtime claims.

### `DECISIONS.md`

Add long-term decisions:

```text
Alert business completion authority = finalized Session-aware boundary, not heartbeat
SuBing Watch = immutable observation-only formula identity and product Scope
V1 context labels = non-gating
Rule kind and scope authority = orthogonal
Rule replacement = forward-only, exactly two stable Rules, no archive/dual lineage
Watch status = short-lived operational proof, not business history
```

### `docs/ARCHITECTURE.md`

Update dependency graph:

```text
Market Runtime completed 15m
  -> SuBing Watch incremental evaluator
  -> Watch boundary ledger
  -> alert:watch-runtime-status
  -> Runtime health / Market status card

Watch Candidate
  -> AlertEvent
  -> owner one-shot PushPlus

MarketDataService
  -> Watch Historical/Current projection
  -> Market chart review
```

Preserve `MarketDataService` as only Historical reader and preserve HTDY/Watch separation.

### `AGENTS.md`

Update execution rules without claiming deployment:

- exact pre/post single-lineage startup contract;
- Watch shadow has no Event/send;
- Watch active requires post-migration lineage;
- boundary status is not Event history;
- provider accepted is not delivery;
- migration execution, Runtime promotion and real send remain separate external Gates;
- old Strategy research remains, but post-migration no longer owns owner Alert.

### `docs/INDICATOR_KERNEL.md`

Pin:

```text
SMA21 rolling policy
MACD 12/26/9 + sma_window + histogram_scale=2
exact CROSS equality boundary
completed-only
physical segment reset
invalid input fail-closed
context-only non-suppression
60m strict-before
batch/incremental/prefix/future-tail/restore parity
```

### `TESTING.md`

Add focused commands for P1–P4. Clearly label:

```text
ordinary unit tests: no external mutation
isolated PostgreSQL migration: disposable DB only
Shadow Runtime: external Runtime Gate
production migration: separate production DB Gate
owner canary/real message: separate send Gate
```

## Task 3 — Add strict OpenSpec

### `openspec/specs/alert-runtime-reliability/spec.md`

Normative requirements and Given/When/Then scenarios:

- Session-authoritative expected set;
- zero-trigger outage detection;
- restart first full boundary;
- product outcomes;
- shared arrival grace;
- freeze/late arrivals;
- counter invariants;
- normal silence;
- bounded TTL status;
- missing/stale/invalid health behavior;
- no PostgreSQL boundary table;
- Shadow no Event/send.

### `openspec/specs/subing-watch-alert/spec.md`

Normative requirements and scenarios:

- exact formula/policy identity;
- SMA21 versus EMA21;
- exact CROSS and warm-up;
- physical segment reset;
- context-only fields;
- Historical/Current/restore/Live one-step parity;
- Rule kind/scope authority;
- pre/post single lineage;
- observation Event fields and immutability;
- owner message and forbidden language;
- Event-first/one-shot;
- forward migration and no downgrade;
- Web server-truth projection and formal bar_end.

OpenSpec must be concise normative truth, not a copy of the long design/plan.

## Task 4 — Focused and full backend verification

Focused:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api --no-sync pytest -q \
  services/quant-api/tests/test_subing_watch_formula.py \
  services/quant-api/tests/research/test_subing_watch_replay.py \
  services/quant-api/tests/data_foundation/test_subing_watch_current_service.py \
  services/quant-api/tests/research/test_subing_watch_report.py \
  services/quant-api/tests/research/test_subing_watch_research_service.py \
  services/quant-api/tests/research/test_subing_watch_cli.py \
  services/quant-api/tests/test_watch_expectation.py \
  services/quant-api/tests/test_watch_boundary.py \
  services/quant-api/tests/test_watch_status.py \
  services/quant-api/tests/test_subing_watch_runtime.py \
  services/quant-api/tests/test_alert_registry.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_market_research_overlays_api.py
```

Full backend excluding explicit external/manual markers:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

Engineering:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
```

Mypy and Ruff:

```bash
PYTHONPATH=services/quant-api:packages/quant-core MYPYPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant

uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests \
  packages/quant-core/guiyi_quant tests/engineering
```

## Task 5 — Isolated migration verification

Only against a dedicated, empty/disposable PostgreSQL database:

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/isolated_db' \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  -m isolated_postgresql \
  services/quant-api/tests/alembic/test_subing_watch_alert_migration.py
```

No production URL may be used. Failure blocks RC.

## Task 6 — Full Web verification

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web test:e2e
pnpm --dir apps/quant-web build
```

Must cover:

- status card four states;
- Candidate deep link;
- SMA21 vs EMA21;
- Watch/Strategy marker distinction;
- formal bar_end/opening-time coordinate;
- no hidden write;
- alert pre/post lineage UI;
- desktop and narrow viewport.

## Task 7 — Contract, safety and diff verification

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
git status --short
git diff --stat origin/develop...HEAD
```

Required:

```text
no secret finding
no placeholder or conflict marker
no unrelated file
no STATUS deployment claim
no external mutation log committed
```

## Task 8 — Commit canonical synchronization

```bash
git add \
  AGENTS.md \
  PROJECT_SOURCE.md \
  DECISIONS.md \
  docs/ARCHITECTURE.md \
  docs/INDICATOR_KERNEL.md \
  TESTING.md \
  openspec/specs/alert-runtime-reliability/spec.md \
  openspec/specs/subing-watch-alert/spec.md \
  tests/engineering/test_canonical_consistency.py
git commit -m "docs: activate SuBing Watch contracts"
```

Open Draft PR to `develop`. Do not update `STATUS.md` with release/migration/Runtime/evidence.

## Task 9 — Independent exact-head whole-program Review

Open a new Sol/high Review session. Pin exact P5 head plus the merged P1–P4 commits. Review matrix:

```text
Spec hard requirement -> implementation -> test -> canonical/OpenSpec
formula and context truth
Historical/Current/restore/Live parity
Session expected-set authority
zero-trigger outage
boundary freeze/normal silence
bounded status and health
single-lineage behavior
Event-first/one-shot
migration atomicity/no downgrade
HTDY non-regression
Web server truth
no over-engineered platform
no external operation performed
```

Findings format:

```text
Critical
Important
Minor
```

Critical/Important must be zero. Any fix changes head SHA and requires a new exact-head Review.

## Task 10 — RC evidence packet

The PR body, not a new repository receipt file, records:

```text
exact head SHA
P0–P5 integration commits
changed files
policy SHA-256
golden fixture SHA-256
focused/full backend counts
isolated migration result
Mypy/Ruff result
Web unit/E2E/build result
OpenSpec/security/diff result
independent Review result
known pending natural evidence
rollback constraints
all unexecuted external Gates
```

Allowed conclusion after P5 integration:

```text
允许进入 release candidate
```

Forbidden conclusions:

```text
RELEASED
MIGRATED
RUNTIME_READY
NATURAL_EVIDENCE_COMPLETE
允许发布 main/tag
允许 Runtime promotion
```

## Review Checklist

- canonical responsibilities are not mixed;
- code capability is not presented as production state;
- `subing_strategy_v1` research remains active;
- Watch becomes the future formal owner Alert after cutover;
- stable Rule count remains two;
- boundary proof is operational TTL state, not business history;
- every exact constant matches code;
- OpenSpec has positive and negative scenarios;
- all required commands were actually run and outputs captured;
- no secret/private path/provider reference;
- no main/tag/Release/DB/Redis/Runtime/send action.

P5 stops at release-candidate Gate. Release, Shadow Runtime, production migration, Active Runtime, owner canary and natural delivery each require later separate approval.
