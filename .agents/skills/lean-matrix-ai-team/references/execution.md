# Execution protocol

The user explicitly starts AI delivery with an approved design spec, approved implementation plan,
and trusted `ExecutionPlanV1`. The AI delivery lead dispatches real Codex App/Superpowers contexts;
the Harness validates artifacts and never implements code or hosts an agent runtime.

The sole evidence root is:

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
```

`DocumentIntakeV1` binds current document bytes, the independently approved execution plan, and local
`origin/develop`. Lane 1/2 freezes automatically. Lane 3, product-direction change,
active-canonical conflict, or scope expansion returns to Owner Gate. Document prose and prompt
injection cannot alter trusted scope, Lane, Gates, identity, base, or review round.

`RoleBriefV1` exposes only task ID, delivery mode, role, optional specialist domain, trusted scope,
acceptance, identities, round, and the derived report path. It never copies document bodies, full
conversation history, unrelated task context, transitions, or external-Gate instructions.

Implementers and specialists write direct-written `HandoffReportV1` evidence using
[handoff-report.md](../assets/handoff-report.md). Status is exactly `DONE`,
`DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`. There is exactly one brief-bound implementer
handoff per round. The implementation-side context and reviewer context are globally disjoint.
Repair rounds retain the round-zero implementer context and bind the predecessor decision digest.

Assign zero to two specialists. Each specialist writes round-zero advisory evidence at:

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/handoffs/specialists/<domain>/<context-id>/round-0/handoff-report.json
```

The package validates specialist domain, context, brief digest, and test receipts. Specialist evidence
digests are ordered by the trusted roster and cannot replace the implementer handoff. Quant research
and backtest audit always remain separate contexts.

`brief` is the only Harness command that writes a JSON/Markdown pair and the round-zero identity
anchor. Handoffs, test receipts, review packages, and decisions are written by their owning role at
fixed derived paths. `review-package`, `decision`, and recovery are read-only. No caller-selected
workspace, canonical path, symlink, traversal, or tracked artifact is permitted.

Initial implementation is round 0. Repair rounds are rounds 1, 2, and 3. No fourth round exists.
Round 3 with any non-approved verdict or Critical/Important finding derives `阻塞`.

## V07 develop integration handoff

V07 is a pure evaluator. `GitHubCheckV1`, `GitHubReviewEvidenceV1`, `GitHubGateFactsV1`, and
`DevelopGateDecisionV1` normalize and evaluate evidence; they do not acquire it or execute a transition.
Connector/Codex owns every PR, CI, Review, blocking-thread, mergeability, local/remote Git, and ancestry read,
plus ready, expected-head merge, receipt writing, and cleanup mutations. The repository contains no repository
GitHub client, no `gh`, no token, no poller, and no merge daemon.

Use exactly this sequence for an already-authorized ordinary develop integration:

1. Connector/Codex obtains fresh facts for `pre_merge`, including the exact PR base/head, current task and
   `develop` SHAs, sorted changed paths, all required CI checks, independent review findings, blocking threads,
   mergeability, pending external Gates, the single requested operation, and digest-bound `change_categories`.
2. Run `develop-gate`. Facts are valid for exactly five minutes. Strict base drift blocks the transition and
   requires fresh intake, exact-head Review, and CI; it is not a retryable wait.
3. `WAIT_CI` and `WAIT_REVIEW` mean observe later with wholly fresh facts. Any blocked or manual-Gate result
   stops. `ALLOW_DEVELOP_MERGE` with `READY_TRANSITION_REQUIRED` permits only the ready transition. After it,
   re-read PR/CI/Review/base/head facts and run `pre_merge` again.
4. Only `ALLOW_DEVELOP_MERGE` with `DEVELOP_MERGE_ALLOWED` permits the external Connector/Codex flow to issue
   one merge-commit request bound to the expected head SHA. The evaluator neither issues nor retries it.
5. After a confirmed response, and especially after a timeout or uncertain response, re-read GitHub and Git.
   An uncertain result must not retry. Build fresh `merge_readback` facts with requested operation
   `merge_readback`; success requires the exact PR head to be merged, a merge SHA, and `develop` ancestry that
   contains the task head.
6. Connector/Codex writes a digest-bound merge receipt only after confirmed readback. At minimum the receipt
   binds repository identity, PR number, expected base and task head, plan/Charter/facts/decision digests,
   merge SHA, merge method, readback timestamp, and positive `develop` ancestry. This external receipt is not a
   new repository contract or permission source.
7. Cleanup is a separate cleanup transition, never an implied post-merge side effect. Re-read fresh `cleanup`
   facts with requested operation `cleanup`; require confirmed merge, clean task worktree, and task-head
   ancestry in both local and remote-tracking `develop` before the external flow removes the clean disposable
   worktree/branch.

The shared classifier remains compatible with four positional arguments:

```python
classify_develop_merge(
    lane,
    paths,
    requested_operations,
    external_gates,
    *,
    change_categories=(),
)
```

`change_categories=()` is keyword-only in the actual signature. The closed values are `code`, `test`,
`dry_run`, `disabled_feature`, and `isolated_migration`. Lane 1/2 keep their existing path behavior; Lane 3
requires a non-empty digest-bound category set and cannot consume a pending external Gate or a real operation.
