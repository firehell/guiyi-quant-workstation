# Development Runtime Documentation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete completed, unreferenced documentation artifacts and make every active repository document describe the same temporary `develop` deployment workflow and final isolated Runtime boundary.

**Architecture:** Treat `AGENTS.md` as the sole execution rule, `STATUS.md` as current live fact, and `PROJECT_SOURCE.md` / `DECISIONS.md` as long-lived boundaries. Remove only completed Superpowers artifacts with no active caller; update active and future-facing documents in small responsibility-based groups, then prove consistency with OpenSpec, task inventory, reference scans, and Markdown diff checks.

**Tech Stack:** Markdown, Git, ripgrep, OpenSpec CLI, repository consistency tooling.

## Global Constraints

- Modify or delete Markdown only. Do not modify code, tests, configuration, Runtime, launchd, RQData, Canonical, PostgreSQL, Redis, notifications, or universe files.
- Current development topology is launchd bound directly to the main `develop` working tree.
- Web changes require build and reload; API and Live changes require reload. No document may imply hot reload or automatic deployment.
- Every Runtime reload remains a one-time controlled external operation requiring a fresh explicit execution intent.
- A natural 17:00 job reads the then-current `develop` tree; dirty-tree evidence is not stable Runtime evidence.
- Development deployment is not Ready, release, Runtime promotion, or final MR-08 acceptance.
- After functional closure, create a new isolated Runtime worktree at an exact commit and collect fresh natural-time evidence.
- Preserve `operational_products.txt=j/jm/ap/ag`, `auto_order=false`, and the Historical Canonical / Redis Live boundary.
- Keep active OpenSpec, OpenSpec archive, DFD-07 rolling documents, Market Research Workspace P0 documents, and `docs/tasks/GY-MARKET-RUNTIME-V1.md`.
- Do not create backup documents, deletion receipts, migration packets, or a second workflow canonical.

---

## File Structure Map

### Delete: completed and unreferenced execution artifacts

```text
docs/superpowers/plans/2026-08-09-audit-finding-matrix.md
docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md
docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md
docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md
docs/superpowers/plans/2026-08-09-market-runtime-v1.md
```

### Modify: execution and workflow canonical

```text
AGENTS.md
DECISIONS.md
docs/DEVELOPMENT.md
docs/PERSONAL_DEVELOPMENT_WORKFLOW.md
docs/tasks/README.md
```

### Modify: product, architecture, and operator navigation

```text
README.md
PROJECT_SOURCE.md
docs/ARCHITECTURE.md
```

### Modify: Runtime verification and still-active plans

```text
TESTING.md
docs/tasks/GY-MARKET-RUNTIME-V1.md
docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md
docs/superpowers/specs/2026-08-10-market-research-workspace-design.md
```

`STATUS.md` is the current verified fact baseline. Read and validate it, but do not rewrite it unless the documentation-only work itself proves a factual contradiction.

---

### Task 1: Remove completed Superpowers artifacts

**Files:**
- Delete: `docs/superpowers/plans/2026-08-09-audit-finding-matrix.md`
- Delete: `docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md`
- Delete: `docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md`
- Delete: `docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md`
- Delete: `docs/superpowers/plans/2026-08-09-market-runtime-v1.md`

**Interfaces:**
- Consumes: current audit behavior documented by `docs/DATA_CENTER.md`, `TESTING.md`, and active OpenSpec.
- Consumes: current Runtime contract documented by `docs/tasks/GY-MARKET-RUNTIME-V1.md` and `STATUS.md`.
- Produces: no completed Superpowers artifact that can be mistaken for active state or authorization.

- [ ] **Step 1: Prove no active document references the five paths or basenames**

Run:

```bash
for obsolete_doc in \
  docs/superpowers/plans/2026-08-09-audit-finding-matrix.md \
  docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md \
  docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md \
  docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md \
  docs/superpowers/plans/2026-08-09-market-runtime-v1.md
do
  rg -n -F "$obsolete_doc" . --glob '*.md' \
    --glob '!docs/superpowers/specs/2026-08-10-document-runtime-topology-cleanup-design.md' \
    --glob '!docs/superpowers/plans/2026-08-10-document-runtime-topology-cleanup.md' || true
done
```

Expected: no active reference output.

- [ ] **Step 2: Delete exactly the five files through Git**

Run:

```bash
git rm -- \
  docs/superpowers/plans/2026-08-09-audit-finding-matrix.md \
  docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md \
  docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md \
  docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md \
  docs/superpowers/plans/2026-08-09-market-runtime-v1.md
```

Expected: only the five named tracked Markdown files are staged as deleted.

- [ ] **Step 3: Verify the deletion diff**

Run:

```bash
git diff --cached --name-status
git diff --cached --check
```

Expected: five `D` entries and no whitespace errors.

- [ ] **Step 4: Commit the artifact deletion**

Run:

```bash
git commit -m "docs: remove completed implementation artifacts"
```

Expected: one documentation-only commit containing the five deletions.

---

### Task 2: Make governance and workflow documents authoritative

**Files:**
- Modify: `AGENTS.md` sections `Personal Development Workflow`, `Controlled External Operations`, and Runtime boundary.
- Modify: `DECISIONS.md` decision table.
- Modify: `docs/DEVELOPMENT.md` sections `Daily Flow`, `Local Verification`, and `Controlled External Operations`.
- Modify: `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md` after section 3.
- Modify: `docs/tasks/README.md` active-contract index.

**Interfaces:**
- Consumes: current deployment fact from `STATUS.md`.
- Produces: one execution rule: edit/test in `develop`; deploy only after explicit one-time intent; final Runtime remains isolated.

- [ ] **Step 1: Update `AGENTS.md` with the temporary development topology**

Add one concise paragraph after the ordinary `develop` workflow stating all of the following:

```text
Current development phase: local launchd may bind directly to the main develop checkout for rapid observation.
Source edits do not hot reload: Web requires build/reload; API and Live require reload.
Each reload is a Runtime switch and consumes a fresh explicit one-time execution intent.
The 17:00 job reads the current develop tree, so dirty or moving-tree evidence is development evidence only.
After functional closure, recreate an exact-commit isolated Runtime worktree for final natural-time acceptance.
```

Keep the existing four-product continuing authorization and `auto_order=false` unchanged.

- [ ] **Step 2: Add the long-lived topology decision to `DECISIONS.md`**

Update the document date to `2026-08-10` and add one table row:

```text
Topic: Development deployment topology
Decision: During functional development, local launchd may temporarily run the main develop checkout; final acceptance uses a new isolated exact-commit Runtime worktree.
Boundary: No hot reload; each reload needs one-time intent; develop evidence is not promotion or final Runtime evidence.
```

- [ ] **Step 3: Update `docs/DEVELOPMENT.md`**

Update the document date to `2026-08-10`. Add a `Development Runtime deployment` subsection containing this exact sequence:

```text
clean develop + intended commit
-> affected tests / Ruff / Mypy / Web build
-> fresh explicit deployment request
-> render and lint launchd plists
-> reload only requested surfaces
-> read back project root and health
```

State that `--render-only` is ordinary validation, while `--confirm-load` and `--confirm-market-runtime` are controlled external operations. Replace any wording that can be read as “Runtime is currently disabled” with “templates default closed; current local state is routed through STATUS.md.”

- [ ] **Step 4: Update `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md`**

Add section `4. Development Runtime deployment` before the existing repository-deletion section and renumber later headings. The section must state:

- deployment is a controlled external operation even though the source path is in the repository;
- a dirty working tree, failed required check, missing build, or root mismatch stops reload;
- no automatic retry after a failed reload;
- after reload, verify installed `GUIYI_PROJECT_ROOT`, API/Web reachability, bounded Live state, and scheduled-job idle state;
- do not manually run after-market to replace a natural event.

- [ ] **Step 5: Update `docs/tasks/README.md`**

Add `GY-MARKET-RUNTIME-V1.md` under active contracts with this meaning:

```text
Implementation exists and local bounded Runtime is enabled, but MR-08 natural-time acceptance is still partial.
```

Do not move it to historical facts until the independent Runtime acceptance is actually complete.

- [ ] **Step 6: Validate and commit governance documents**

Run:

```bash
rg -n 'hot reload|自动生效|develop|Runtime worktree|one-time|一次' \
  AGENTS.md DECISIONS.md docs/DEVELOPMENT.md \
  docs/PERSONAL_DEVELOPMENT_WORKFLOW.md docs/tasks/README.md
git diff --check
git status --short
```

Expected: the five files consistently express the temporary/final topology and no unrelated file is modified.

Commit:

```bash
git add -- AGENTS.md DECISIONS.md docs/DEVELOPMENT.md \
  docs/PERSONAL_DEVELOPMENT_WORKFLOW.md docs/tasks/README.md
git commit -m "docs: define develop runtime workflow"
```

---

### Task 3: Align product and architecture navigation

**Files:**
- Modify: `README.md` local-start and safety sections.
- Modify: `PROJECT_SOURCE.md` engineering/external-operation section and DFD progress wording.
- Modify: `docs/ARCHITECTURE.md` system-positioning and runtime-boundary sections.

**Interfaces:**
- Consumes: governance wording established by Task 2.
- Produces: concise operator navigation without creating a second deployment authority.

- [ ] **Step 1: Update `README.md`**

Keep `./scripts/dev/dev-up.sh` as the process-local startup path. Add a separate `Development launchd deployment` note that says:

- current local deployment root is recorded only in `STATUS.md`;
- modifying `develop` is not deployment;
- Web requires `npm --prefix apps/quant-web run build` before reload;
- reload commands are executed only after a fresh explicit request;
- final stable Runtime is created separately after functional closure.

Do not publish `--confirm-*` commands as an always-authorized copy/paste shortcut.

- [ ] **Step 2: Update `PROJECT_SOURCE.md`**

Keep temporary paths and hashes out of this long-lived document. Add these stable rules:

```text
Current deployment root is owned by STATUS.md.
Development may temporarily deploy from develop for rapid local observation.
Final Runtime acceptance requires a new isolated exact-commit worktree and fresh natural evidence.
```

Replace the stale statement that DFD-02 through DFD-06 are still converging with:

```text
DFD-01 through DFD-06 are repository-complete; DFD-07 production Canonical closure remains partial and is reported by STATUS.md.
```

- [ ] **Step 3: Update `docs/ARCHITECTURE.md`**

Update the date to `2026-08-10`. In system positioning, distinguish:

- repository code/templates default closed;
- this local workstation has bounded `j/jm/ap/ag` Runtime enabled;
- the temporary deployment root is `develop`, routed through `STATUS.md`;
- Live remains Redis-only and never enters Canonical/DB;
- the final Runtime topology remains an isolated exact-commit worktree.

- [ ] **Step 4: Validate and commit product/architecture documents**

Run:

```bash
rg -n '尚未启用|默认关闭|develop|Runtime worktree|DFD-0[1-7]' \
  README.md PROJECT_SOURCE.md docs/ARCHITECTURE.md
git diff --check
```

Expected: no active statement says the local Runtime is currently unenabled; template default-closed wording remains explicit.

Commit:

```bash
git add -- README.md PROJECT_SOURCE.md docs/ARCHITECTURE.md
git commit -m "docs: align runtime architecture and navigation"
```

---

### Task 4: Update verification, Runtime contract, and future P0 premises

**Files:**
- Modify: `TESTING.md` Runtime section.
- Modify: `docs/tasks/GY-MARKET-RUNTIME-V1.md` header/current-facts/acceptance sections.
- Modify: `docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md` Runtime constraint and review correction.
- Modify: `docs/superpowers/specs/2026-08-10-market-research-workspace-design.md` current boundary.

**Interfaces:**
- Consumes: current status `develop` deployment with MR-08 still partial.
- Produces: executable validation commands and still-active plans with correct premises.

- [ ] **Step 1: Update `TESTING.md`**

Update the date to `2026-08-10`. Keep the existing no-side-effect Runtime commands. Add three clearly separated levels:

1. `render/test`: existing pytest, render-only, plist lint; no external authorization.
2. `development reload`: only after a fresh explicit request; build/test first, reload selected surfaces, then read back root and health.
3. `final Runtime acceptance`: isolated exact commit plus natural BREAK/recovery, natural 17:00 completion, and non-trading-day evidence.

State that manual `guiyi data after-market` never substitutes for level 3 natural evidence.

- [ ] **Step 2: Update `docs/tasks/GY-MARKET-RUNTIME-V1.md`**

Set:

```text
Disposition: partial_canary_development_runtime
Current topology: launchd temporarily runs the main develop checkout; old detached worktree is removed.
```

Retain the original frozen architecture and implementation scope. Add a current-status subsection that distinguishes:

- repository implementation complete;
- immediate code acceptance complete at the current documented baseline;
- natural-time MR-08 gates incomplete;
- current develop observations cannot close the later independent Runtime gate;
- final worktree creation, release, main, tag, and promotion remain separate decisions.

Do not rewrite historical 4/60 facts as global completion.

- [ ] **Step 3: Correct the P0 implementation plan premise**

In `docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md`, replace:

```text
Market Runtime V1 的历史分页、Redis Live Overlay、REST/WS seam 已实现但尚未启用。
```

with:

```text
Market Runtime V1 paging, Redis Live Overlay, REST/WS seam, and bounded local enablement already exist.
P0 must reuse these surfaces and must not change the Runtime scope, deployment root, operational universe, or authorization state.
```

Update review correction 1 from “do not restore Live” to “reuse the currently enabled seam without owning Runtime deployment.”

- [ ] **Step 4: Correct the P0 design premise**

In `docs/superpowers/specs/2026-08-10-market-research-workspace-design.md`, replace the statement that the design does not restore intraday Live/WebSocket with:

```text
Historical Canonical and Live observation remain separate. The design reuses the existing enabled REST/WebSocket seam but does not modify Live collection, Runtime deployment, operational products, or promotion.
```

- [ ] **Step 5: Validate and commit Runtime/P0 documents**

Run:

```bash
rg -n '尚未启用|未启用|develop|partial_canary|natural|自然|Runtime promotion' \
  TESTING.md docs/tasks/GY-MARKET-RUNTIME-V1.md \
  docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md \
  docs/superpowers/specs/2026-08-10-market-research-workspace-design.md
git diff --check
```

Expected: current Runtime premises are accurate, while P0 remains prohibited from changing Runtime behavior.

Commit:

```bash
git add -- TESTING.md docs/tasks/GY-MARKET-RUNTIME-V1.md \
  docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md \
  docs/superpowers/specs/2026-08-10-market-research-workspace-design.md
git commit -m "docs: refresh runtime acceptance premises"
```

---

### Task 5: Run repository documentation acceptance

**Files:**
- Validate: all modified/deleted Markdown.
- Modify: only a document with a proven contradiction from the checks below.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: one clean, internally consistent documentation state.

- [ ] **Step 1: Validate active OpenSpec**

Run:

```bash
openspec validate converge-canonical-data-foundation --strict --no-interactive
openspec status --change converge-canonical-data-foundation --json
```

Expected: validation succeeds; status output remains evidence only and grants no mutation.

- [ ] **Step 2: Validate task inventory**

Run:

```bash
python3 scripts/engineering/repository_consistency.py --task-inventory
```

Expected: task inventory succeeds and recognizes `GY-MARKET-RUNTIME-V1.md` as current/retained rather than a deleted historical artifact.

- [ ] **Step 3: Scan forbidden stale current-state wording**

Run:

```bash
rg -n -i --glob '*.md' \
  'guiyi-quant-workstation-runtime|Runtime detached checkout current|current Runtime.*not enabled|Market Runtime V1.*not enabled|after-market-scheduler' \
  AGENTS.md STATUS.md PROJECT_SOURCE.md DECISIONS.md README.md TESTING.md docs || true
```

Expected: only explicitly historical/removed-state descriptions, formal OpenSpec archive, or inactive source names remain; no active document treats them as current topology.

- [ ] **Step 4: Prove deleted artifacts are absent**

Run:

```bash
for obsolete_doc in \
  docs/superpowers/plans/2026-08-09-audit-finding-matrix.md \
  docs/superpowers/specs/2026-08-09-audit-finding-matrix-design.md \
  docs/superpowers/plans/2026-08-09-scoped-data-audit-and-canary-preflight.md \
  docs/superpowers/specs/2026-08-09-scoped-data-audit-design.md \
  docs/superpowers/plans/2026-08-09-market-runtime-v1.md
do
  test ! -e "$obsolete_doc"
done
```

Expected: all five checks succeed.

- [ ] **Step 5: Run final Markdown and Git checks**

Run:

```bash
git diff --check
git status --short --branch
git log -6 --oneline --decorate
```

Expected: no unstaged change, no whitespace failure, and only the planned documentation commits after the design/plan commits.

- [ ] **Step 6: Report bounded completion**

Report:

```text
Documentation cleanup: complete.
Runtime/live/data/database mutations: none.
MR-08 and Canonical document closure: still partial until their independent natural/data gates pass.
Current local deployment: develop development runtime, not final isolated Runtime.
```
