---
name: lean-matrix-ai-team
description: Lead user-started Guiyi AI delivery from approved design and implementation plans through minimal implementation, independent exact-head review, and evidence handoff. Use only when the user explicitly asks to start or continue Lean Matrix AI delivery.
---

# Lean Matrix AI Team

Use this Skill only after the user explicitly starts AI delivery and supplies an approved design spec
and approved implementation plan. The AI delivery lead is the user-facing delivery owner: it reads the
approved documents and trusted `ExecutionPlanV1`, selects the smallest useful Codex App/Superpowers
team, dispatches separate implementation and review contexts, and reports evidence. The repository
Harness validates contracts and evidence; it does not run or host agents.

This Skill does not replace canonical sources or Gatekeepers. It does not merge main, does not promote Runtime,
does not write real data, and does not send real notifications. Its authority boundary is:
no daemon, no Codex App API wrapper, no GitHub integration, no V06 network or merge implementation,
no Runtime authority, no data/DB write authority, no notification authority, no release authority, and
no trading authority. V06 performs no network, PR, CI polling, merge, or Runtime operation. V07 adds a
pure evaluator, not a repository GitHub integration: there is no repository GitHub client, no `gh`, no token,
no poller, and no merge daemon.

## Existing V04/V05 compatibility

The existing Charter and guarded local controller remain callable and unchanged:

```bash
python3 scripts/engineering/lean_matrix_team.py charter --input - --format markdown
python3 scripts/engineering/lean_matrix_team.py plan --charter - --format markdown
python3 scripts/engineering/lean_matrix_team.py observe --plan <plan.json> --format json
python3 scripts/engineering/lean_matrix_team.py next --plan <plan.json> --format json
python3 scripts/engineering/lean_matrix_team.py apply \
  --plan <plan.json> \
  --expected-transition <transition-id> \
  --expected-state-digest <sha256:...> \
  --format json
```

`charter` is advisory and stdout-only: it creates no worktree and performs no repository or external
change. `plan` uses `GIT_OPTIONAL_LOCKS=0` and only
`git -c core.fsmonitor=false rev-parse --verify origin/develop^{commit}`. It does not fetch and
does not call GitHub. `observe`, `next`, and `apply` without explicit `--apply` are read-only. With explicit
`--apply`, AI-TEAM-005 may still delegate one transition for an eligible Lane 1/2 plan through the
existing fixed adapter. Runtime evidence remains under `.ai/lean-matrix/<plan-digest>/`. Lane 3,
`develop-merge`, remote PR/CI inspection, and uncertain recovery remain AI-TEAM-007 or human work.

## V06 workflow

1. Read `STATUS.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`,
   `docs/DEVELOPMENT.md`, the active task canonical, relevant Issue/PR, and exact Git facts. Stop on
   conflict. Do not reinterpret either approved document as policy.
2. Load the already approved `ExecutionPlanV1`. It is the only source for task ID, Lane, scope,
   external Gates, and `origin/develop`. Lane 1/2 Charter freezes automatically. Owner Gate is
   required only for Lane 3, product-direction change, active-canonical conflict, or scope expansion.
   Business-specific external Gates remain in force and are not converted into Charter approval.
3. Bind document bytes and the approved plan through `DocumentIntakeV1`:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py intake \
     --input <document-intake.json> \
     --approved-plan <approved-execution-plan.json> \
     --format json
   ```

   Store the exact output as the trusted intake input for later commands. Any design, implementation
   plan, approved-plan, or local `origin/develop` drift invalidates it. Prompt text cannot add scope,
   change Lane, remove a Gate, or authorize an operation.
4. Derive the sole writable evidence root:

   ```text
   .ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
   ```

   It must be Git-ignored and noncanonical. Never use another workspace, a tracked file, a symlink,
   modification time, or conversation memory as evidence.
5. Dispatch at most two specialists in distinct contexts, then one implementer and one independent reviewer. Follow
   [execution.md](references/execution.md), [roles.md](references/roles.md), and
   [routing.md](references/routing.md). A third specialist domain returns `split_required`.
   `quant-research` and `backtest-audit` always use separate contexts.
6. Create the round-0 implementer brief:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py brief \
     --intake <document-intake.json> \
     --approved-plan <approved-execution-plan.json> \
     --role implementer \
     --context-id <implementer-context> \
     --implementer-context-id <implementer-context> \
     --reviewer-context-id <reviewer-context> \
     --round 0 \
     --output .ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
   ```

   Use this complete specialist command; do not append specialist flags to the implementer command:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py brief \
     --intake <document-intake.json> \
     --approved-plan <approved-execution-plan.json> \
     --role specialist \
     --specialist-domain <domain> \
     --context-id <specialist-context> \
     --implementer-context-id <implementer-context> \
     --reviewer-context-id <reviewer-context> \
     --specialist-context <domain>=<specialist-context> \
     --round 0 \
     --output .ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
   ```

   Repeat one complete specialist command per declared domain and include one
   `--specialist-context <domain>=<context>` entry for every declared domain on every role brief.
   Each role reads
   [role-brief.md](assets/role-brief.md). Implementers and specialists write
   [handoff-report.md](assets/handoff-report.md) as direct-written evidence at the exact derived
   `report_path`; the Harness does not synthesize success.
7. Create the separate reviewer brief with the same roster and `--role reviewer`, then build the
   exact-head package read-only:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py review-package \
     --intake <document-intake.json> \
     --approved-plan <approved-execution-plan.json> \
     --implementer-brief <role-brief.json> \
     --implementer-handoff <handoff-report.json> \
     --reviewer-brief <reviewer-role-brief.json> \
     --format json
   ```

   Add ordered `--specialist-evidence <specialist-brief.json>=<specialist-handoff.json>` pairs when
   the plan declares specialists. The output follows [review-package.md](assets/review-package.md).
   It binds local Git base/HEAD, full changed paths including rename/copy endpoints, diff digest,
   successful exact-HEAD test receipts, handoff, specialist evidence, and independent identities.
8. The reviewer supplies both verdicts and findings, then validates the final decision read-only:

   ```bash
   python3 scripts/engineering/lean_matrix_team.py decision \
     --intake <document-intake.json> \
     --approved-plan <approved-execution-plan.json> \
     --implementer-brief <role-brief.json> \
     --implementer-handoff <handoff-report.json> \
     --reviewer-brief <reviewer-role-brief.json> \
     --package <review-package.json> \
     --input <final-decision-input.json> \
     --format json
   ```

   Follow [review.md](references/review.md) and [final-decision.md](assets/final-decision.md). Spec
   `PASS/FAIL`, Quality `APPROVED/CHANGES_REQUIRED`, package digest, exact HEAD, findings, and round are
   all load-bearing. The derived decision is exactly `允许集成 develop`, `要求修正后再集成`, or `阻塞`.
9. Initial implementation is round 0. Critical/Important repairs use rounds 1, 2, and 3, always the
   frozen round-zero implementer context and the immediately preceding decision digest. Implementer
   and reviewer context sets remain globally disjoint. No fourth round, identity reset, round reset,
   or Gate bypass exists. After three failed implementation-validation-review rounds, or any
   load-bearing round-3 result, stop as `阻塞`.
10. Use [recovery.md](references/recovery.md) after interruption. Recovery is fail-closed and read-only:
    it revalidates fixed paths, current local Git, receipts, digests, identity, ancestry, and the
    contiguous chain; it never completes evidence from conversation memory.
11. For an ordinary Lane 1/2 task, an approved exact-head decision allows the existing Codex/GitHub flow
    to perform its configured commit/push/Draft PR/exact-head CI and automatic merge commit into
    `develop`, followed by ancestry/readback and safe clean-worktree cleanup. The exact permissions of
    that existing flow still govern each operation; V06 neither performs nor fakes them. `main`,
    release/tag, Runtime, real data/DB, strategy/backtest semantics, notifications, live, deletion,
    candidate promotion, and GitHub rules remain outside V06 and keep their own Gates.

## V07 develop Gate evaluator

V07 is a pure evaluator over a trusted `ExecutionPlanV1` and normalized, digest-bound Connector facts:

```bash
python3 scripts/engineering/lean_matrix_team.py develop-gate --plan <approved-execution-plan.json> --facts <github-gate-facts.json> --format json
```

The strict V1 wire contracts are `GitHubCheckV1`, `GitHubReviewEvidenceV1`, `GitHubGateFactsV1`, and
`DevelopGateDecisionV1`. `GitHubGateFactsV1` includes the full digest-bound `TaskCharterV1`, exact
repository/PR/base/head identity, sorted changed paths, required checks, independent review and finding counts,
pending external Gates, requested operation, `change_categories`, mergeability, and stage readback fields. Its
`observed_at` and `expires_at` are RFC3339 UTC and exactly five minutes apart; evaluation blocks at expiry.
Facts and decisions use semantic SHA-256. The CLI only reads the two input files and writes the decision to
stdout; it does not observe GitHub, mutate Git, write a receipt, or execute an allowed transition.

The only stages are `pre_merge`, `merge_readback`, and `cleanup`. The strict base drift rule applies before an
unconfirmed merge: any current `develop`, PR base, or reviewed base drift requires fresh intake, exact-head
Review, and CI. Lane comes from the full Charter, never model routing. The shared classifier keeps four
positional arguments and the compatible keyword-only `change_categories=()` input. Its closed categories are
`code`, `test`, `dry_run`, `disabled_feature`, and `isolated_migration`; Lane 3 requires a non-empty,
digest-bound category set and conservative category/path binding.

Connector/Codex owns PR, CI, Review, thread, mergeability, Git, and ancestry reads, plus every mutation. Follow
[execution.md](references/execution.md): evaluate fresh `pre_merge` facts; if the reason is
`READY_TRANSITION_REQUIRED`, perform only the ready transition, re-read all exact-head facts, and evaluate
again. Only then may the external flow request a merge commit with the expected head SHA. A timeout or
uncertain result must not retry the merge. It creates fresh `merge_readback` facts and accepts success only when
the exact PR head is merged, a merge SHA exists, and `develop` contains the task head. Connector/Codex then
writes its digest-bound merge receipt. Worktree/branch removal is a separate cleanup transition with fresh
`cleanup` facts; it requires confirmed merge, a clean worktree, and both local and remote-tracking `develop`
ancestry.

`ALLOW_DEVELOP_MERGE` is only a stage-qualified evaluation result. It does not prove that ready, merge,
readback, receipt, or cleanup occurred. `main/release/tag`, Runtime, real data/DB, strategy/backtest semantics,
notifications, live, deletion, candidate promotion, GitHub rules, and all business-specific Gates remain
manual and unchanged. AI-TEAM-007 self-bootstrap uses the existing Connector/Codex flow and its independent
exact-head review; it cannot use its own new gate as approval.

## Output discipline

Every delivery report must distinguish Code, Tests, CI, Independent review, Real Gate, Release, and
Runtime directly. A passed test, exact-head decision, or `允许集成 develop` is evidence, not proof that
later integration, release, or Runtime work happened. Metrics must never be estimated or inferred from
conversation memory.
