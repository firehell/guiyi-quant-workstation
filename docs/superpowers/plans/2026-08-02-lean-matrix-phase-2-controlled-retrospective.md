# Lean Matrix Phase 2 Controlled Retrospective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a versioned, source-bound Phase 2 retrospective that tests Lean Matrix routing against completed Task 04 and records AI-TEAM-001 as a controlled trial without replaying either task or expanding automation.

**Architecture:** Keep Phase 2 evidence-only. Add one reusable trial-report template to the existing repository skill, one filled retrospective under `docs/superpowers/retrospectives/`, and static policy tests that bind required evidence/status fields and prevent Task 04, Task 05, release, or Runtime status expansion. Do not add a metrics service, database, workflow command, or GitHub automation.

**Tech Stack:** Markdown, Python 3 standard library, pytest, existing repository skill and engineering test suite.

## Global Constraints

- Work only in `/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-002-phase2-controlled-retrospective` on `research/AI-TEAM-002-phase2-controlled-retrospective`.
- Base is `origin/develop@0867e12353e6fbb145c0e14427432e5ba06b9b7e`; Issue is #99.
- Task 04 is an immutable historical sample. Do not rerun it, create packets, query RQData, or write PostgreSQL/Parquet.
- AI-TEAM-001 / PR #98 is a completed controlled-trial sample, not authorization to merge, release, or automate future tasks.
- Do not adopt or modify the active Task 05 worktree or any of its files.
- Evidence precedence is repository canonical and GitHub exact facts. Conversation memory is not evidence.
- Metrics that cannot be proven from canonical or GitHub facts must be `NOT_MEASURABLE`, not estimated.
- No changes to `main`, Runtime, real data, notification, release/tag, worktree cleanup, or GitHub rules.
- No new service, database, background process, control plane, or workflow CLI.

---

### Task 1: Add the controlled-trial report contract

**Files:**
- Create: `.agents/skills/lean-matrix-ai-team/assets/trial-report.md`
- Modify: `.agents/skills/lean-matrix-ai-team/SKILL.md`
- Modify: `tests/engineering/test_lean_matrix_skill_policy.py`

**Interfaces:**
- Consumes: the existing Task Charter, stage-report distinctions, exact-head evidence rules, and human Gate categories.
- Produces: a Markdown template with fixed sections and a three-state metric provenance contract: `MEASURED`, `MANUALLY_RECORDED`, or `NOT_MEASURABLE`.

- [ ] **Step 1: Write failing policy tests**

Add assertions that `assets/trial-report.md` exists and contains exactly these level-two sections:

```text
Identity
Sample classification
Routing prediction
Observed execution
Metrics
Gate preservation
Findings
Decision
```

Require fields for Issue/PR/base/head/merge SHA; source type; predicted and observed roles; specialist count; start/merge timestamps; review-fix rounds; user interruption count; CI; external Gates; and the three provenance states. Require the skill to reference the template and forbid inferred metrics.

- [ ] **Step 2: Run the policy test and observe RED**

Run:

```bash
python3 -m pytest -q tests/engineering/test_lean_matrix_skill_policy.py
```

Expected: failure because `assets/trial-report.md` and its skill reference do not exist.

- [ ] **Step 3: Add the minimal template and skill instruction**

Create the eight-section template. State that `MEASURED` needs a canonical/GitHub source; `MANUALLY_RECORDED` needs an explicitly named human observation and cannot drive a Gate; `NOT_MEASURABLE` is mandatory when neither exists. Add one concise workflow sentence to `SKILL.md`; do not duplicate the retrospective itself into the skill.

- [ ] **Step 4: Run GREEN and skill validation**

Run:

```bash
python3 -m pytest -q tests/engineering/test_lean_matrix_skill_policy.py
python3 /Users/zhangzhao/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/lean-matrix-ai-team
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit the report contract**

```bash
git add .agents/skills/lean-matrix-ai-team/SKILL.md \
  .agents/skills/lean-matrix-ai-team/assets/trial-report.md \
  tests/engineering/test_lean_matrix_skill_policy.py
git commit -m "feat(workstation): add lean matrix trial report contract"
```

### Task 2: Add the source-bound Phase 2 retrospective

**Files:**
- Create: `docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-2.md`
- Create: `tests/engineering/test_lean_matrix_phase2_evidence.py`

**Interfaces:**
- Consumes: `docs/tasks/GY-DATA-CORE-V2.md`, `STATUS.md`, the merged Lean Matrix design, GitHub PR #86-#95/#98 facts, exact task and merge SHAs, and the trial-report contract.
- Produces: an immutable retrospective with two samples and an evidence/limitation table usable for the Phase 3 go/no-go decision.

- [ ] **Step 1: Write failing evidence-policy tests**

The test must require:

```python
TASK04_PRS = (86, 87, 88, 89, 90, 91, 92, 93, 94, 95)
AI_TEAM_001_PR = 98
TASK04_CLOSEOUT_MERGE = "cc4302b57728133a1471447902563d3abf3604fb"
AI_TEAM_001_HEAD = "a4af1e8e5798802f4e553d1fe9e6460285e24a67"
AI_TEAM_001_MERGE = "0867e12353e6fbb145c0e14427432e5ba06b9b7e"
```

It must also assert that the document:

- labels Task 04 `historical_retrospective` and AI-TEAM-001 `controlled_trial`;
- names `docs/tasks/GY-DATA-CORE-V2.md` and GitHub PR facts as sources;
- records Task 04 as completed without reopening legacy Shadow;
- records PR #98 as four commits with three post-feature remediation commits and exact-head CI success; the review-fix round count remains `NOT_MEASURABLE` unless an explicit canonical/GitHub source proves it;
- uses `NOT_MEASURABLE` for conversation/session/user-interruption metrics that cannot be reconstructed from canonical/GitHub facts;
- states zero Task 05 adoption and zero `main`/Runtime/data/notification authority;
- concludes Phase 3 is eligible only for a new independent task, not the active Task 05 worktree;
- contains no `TBD`, `TODO`, profitability, trading instruction, or Runtime-ready claim.

- [ ] **Step 2: Run the evidence test and observe RED**

```bash
python3 -m pytest -q tests/engineering/test_lean_matrix_phase2_evidence.py
```

Expected: collection or assertion failure because the retrospective does not exist.

- [ ] **Step 3: Write the retrospective from immutable facts**

For Task 04, distinguish the predicted single data/database specialist route from the actual multi-PR Gate-repair sequence. Record that repeated exact-hash invalidation and fail-closed behavior preserved safety but increased cycle count. Treat GitHub review arrays being empty as “GitHub native review not recorded,” not “no independent review”; cite canonical independent-review statements separately.

For AI-TEAM-001, record PR created `2026-08-02T04:34:47Z`, merged `2026-08-02T05:01:10Z`, four commits, 11 changed files, three exact-head CI checks, and three post-feature remediation commits. Mark review-fix rounds, user interruptions, and total agent sessions `NOT_MEASURABLE` because they are absent from canonical/GitHub facts.

End with evidence-based Phase 3 entry conditions: new Issue, new task worktree, one ordinary reversible task, frozen Charter, no Task 05 adoption, measured report fields from task start, exact-head review, and no new authority.

- [ ] **Step 4: Run GREEN and combined policy tests**

```bash
python3 -m pytest -q \
  tests/engineering/test_lean_matrix_phase2_evidence.py \
  tests/engineering/test_lean_matrix_skill_policy.py \
  tests/engineering/test_lean_matrix_team.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit the retrospective**

```bash
git add docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-2.md \
  tests/engineering/test_lean_matrix_phase2_evidence.py
git commit -m "docs(workstation): record lean matrix phase 2 evidence"
```

### Task 3: Align phase status and deliver exact-head evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`
- Verify: all Phase 2 files from Tasks 1-2

**Interfaces:**
- Consumes: approved Phase 2 report and exact-head verification.
- Produces: an accurate design status that says Phase 1 is merged and Phase 2 is implemented on a Draft PR, without claiming Phase 3 completion or Phase 4/5 authorization.

- [ ] **Step 1: Update only the design status line and Phase 2 status note**

State that Phase 1 merged through PR #98 at `develop@0867e123`; Phase 2 evidence is implemented on Issue #99 and remains subject to its Draft PR/merge status. Do not alter the frozen Phase 3-5 contracts.

- [ ] **Step 2: Run final local verification**

```bash
bash scripts/engineering/test.sh all-safe
bash scripts/engineering/check-secrets.sh
python3 /Users/zhangzhao/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/lean-matrix-ai-team
git diff --check
```

Expected: all commands exit 0, with no real-write or Runtime action.

- [ ] **Step 3: Obtain independent exact-head review**

Review against `origin/develop@0867e123`. Require findings by Critical/Important/Minor and explicit `Spec PASS/FAIL` plus `Quality APPROVED/CHANGES_REQUIRED`. Fix findings with bounded TDD rounds; stop after three failed rounds.

- [ ] **Step 4: Commit status alignment if changed**

```bash
git add docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md
git commit -m "docs(workstation): advance lean matrix phase status"
```

- [ ] **Step 5: Use the controlled integration entrypoint**

Dry-run, then apply:

```bash
bash scripts/engineering/task-worktree.sh integrate \
  --lane 2 --issue 99 --test-profile all-safe \
  --commit-message "docs(workstation): complete lean matrix phase 2 retrospective" --json

bash scripts/engineering/task-worktree.sh integrate \
  --lane 2 --issue 99 --test-profile all-safe \
  --commit-message "docs(workstation): complete lean matrix phase 2 retrospective" --apply --json
```

If earlier task commits leave no uncommitted files, push the branch and create the Draft PR through the repository-approved Git/GitHub flow instead of manufacturing an empty commit.

- [ ] **Step 6: Verify PR exact head and report the stage**

Require Draft PR base `develop`, exact head equal to the local clean branch, all checks green, and a PR evidence comment. Report measured results, limitations, Phase 3 entry decision, and confirm `main`, Runtime, real data, notifications, and Task 05 were untouched.
