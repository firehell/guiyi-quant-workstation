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
