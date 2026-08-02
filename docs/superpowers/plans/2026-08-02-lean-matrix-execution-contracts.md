# Lean Matrix Execution Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production behavior follows RED-GREEN-REFACTOR.

**Goal:** Preserve the schema-v1 Charter CLI while adding modular, deterministic V1 execution contracts and a read-only Execution Plan bound to local `origin/develop`.

**Architecture:** `lean_matrix_team.py` remains a thin stdin/file and stdout/stderr CLI. Validation, routing, contracts, digesting, planning, rendering, and the single fixed read-only Git adapter live in focused modules under `scripts/engineering/lean_matrix/`; pure planning accepts an explicit SHA and never invokes Git itself.

**Tech Stack:** Python 3.13 standard library, frozen slotted dataclasses, argparse, pytest, Git.

## Global Constraints

- Base: `origin/develop@39d1002d1051e0ccb6ffc7f480bdc236d9930edc`; Issue #107; Lane 2.
- Existing `charter` JSON, Markdown, exit code, and stderr output remain byte-for-byte compatible.
- `plan` resolves only local `origin/develop^{commit}` with fixed argv, `shell=False`, and `GIT_OPTIONAL_LOCKS=0`.
- No third-party dependency, fetch/network, Git write, transition apply, receipt write, business change, or second state source.
- Do not modify `STATUS.md`, `AGENTS.md`, `PROJECT_SOURCE.md`, `DECISIONS.md`, `.github/**`, business code, data, migration, `main`, or Runtime.

---

### Task 1: Characterize and modularize the Charter

- [ ] Add compatibility tests that fail when the CLI logic has not moved behind focused modules.
- [ ] Run the tests and confirm the expected RED failure.
- [ ] Extract errors, Charter validation, routing, and rendering without changing serialized output.
- [ ] Make `lean_matrix_team.py` a thin CLI and return the suite to GREEN.

### Task 2: Add strict frozen V1 contracts and canonical digests

- [ ] Add failing tests for frozen/slotted values, strict keys, path/SHA/status validation, tuple normalization, and deterministic `to_dict()`.
- [ ] Add failing tests proving semantic changes alter the digest while Markdown changes do not.
- [ ] Implement `TaskCharterV1`, `DispatchPlanV1`, `ExecutionPlanV1`, runtime contracts, nested values, and canonical SHA-256 JSON.
- [ ] Run the contract and compatibility suites to GREEN.

### Task 3: Add the read-only Execution Plan CLI

- [ ] Add failing tests for the fixed plan schema and a real temporary Git repository with `refs/remotes/origin/develop`.
- [ ] Add failure tests for missing Git/ref, nonzero exit, multiline output, and non-40-hex output.
- [ ] Implement the pure plan builder, deterministic JSON/Markdown renderers, and the isolated fixed Git adapter.
- [ ] Prove `charter` invokes no subprocess and `plan` invokes no command except the fixed local `git rev-parse`.

### Task 4: Update repository skill policy and verify

- [ ] Add failing policy assertions for the `plan` command, read-only Git exception, and no-transition boundary.
- [ ] Update the Lean Matrix skill minimally and return policy tests to GREEN.
- [ ] Run targeted pytest, strict preflight, engineering, all-safe, secret scan, and diff checks.
- [ ] Commit, push, create a Draft PR to `develop`, and obtain independent exact-head review before any integration decision.
