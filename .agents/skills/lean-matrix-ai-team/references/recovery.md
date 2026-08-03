# Recovery protocol

The ignored evidence root is noncanonical and recoverable:

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
```

The only review ledger is:

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/review-ledger.json
```

The AI delivery lead writes the complete ledger after each final decision, only after every referenced
artifact is present at its fixed derived path. There is no record command and no alternate ledger path.
The strict schema is:

```json
{
  "schema_version": 1,
  "intake_digest": "sha256:...",
  "rounds": [
    {
      "round": 0,
      "implementer_brief": {
        "path": "<repo-relative-path>",
        "digest": "sha256:..."
      },
      "implementer_handoff": {
        "path": "<repo-relative-path>",
        "digest": "sha256:..."
      },
      "reviewer_brief": {
        "path": "<repo-relative-path>",
        "digest": "sha256:..."
      },
      "review_package": {
        "path": "<repo-relative-path>",
        "digest": "sha256:..."
      },
      "final_decision": {
        "path": "<repo-relative-path>",
        "digest": "sha256:..."
      },
      "specialist_evidence": [
        {
          "brief": {
            "path": "<repo-relative-path>",
            "digest": "sha256:..."
          },
          "handoff": {
            "path": "<repo-relative-path>",
            "digest": "sha256:..."
          }
        }
      ]
    }
  ]
}
```

Each artifact reference has exactly `path` and `digest`. `rounds` is contiguous from 0 through at most
3. Specialist evidence is an ordered list of exact `brief`/`handoff` artifact references. The loader
rejects extra fields such as `conversation_memory`.

The executable read-only contract is `lean_matrix.ledgers.recover_review_ledger`. A caller first loads
the trusted approved plan, intake, and fixed round-zero implementer identity, then calls:

```python
decisions = recover_review_ledger(repo_root, intake, ledger_path, round_zero_brief=round_zero_brief)
```

`ledger_path` must equal the fixed path above. The returned tuple is the fully revalidated decision
chain; an exception is a blocked recovery, never permission to infer success.

Recovery never uses a caller-supplied recovery path and never selects evidence by modification time.
It loads only regular, non-symlink, size-bounded JSON at fixed derived paths and validates exact byte
digests before trusting a contract. Missing, gapped, forked, stale, duplicated, out-of-workspace, or
internally inconsistent evidence fails closed.

The unfinished stage is reconstructed from Git/PR facts and digest-bound local receipts, never from
conversation memory. Recovery revalidates the trusted intake and round-zero identity, then every
brief, handoff, test receipt, package, final decision, predecessor digest, and specialist binding. It
recomputes Git facts and artifact bindings, full changed paths, diff digests, base/head ancestry, and
requires the latest recovered package to equal current local HEAD.

Receipt or Git drift blocks recovery. Restoring the exact trusted bytes and exact Git state permits a
fresh read-only validation; missing evidence never implies success. Recovery cannot reset a round,
replace the original implementer, reuse a reviewer context for implementation, add a fourth round,
or authorize Owner Gate, merge, release, Runtime, data/DB, notification, or trading work.

## V07 merge-result and cleanup recovery

V07 does not resume from a remembered action or a previous allow decision. Its recovery state is one of the
freshly observed stages `pre_merge`, `merge_readback`, or `cleanup`; every `GitHubGateFactsV1` observation is
digest-bound and valid for exactly five minutes.

If an expected-head merge request times out, disconnects, or returns an uncertain result, Connector/Codex must
not retry. It re-reads the exact PR and `develop`, emits fresh `merge_readback` facts, and runs the pure
evaluator. Recovery advances only when the exact task head is the merged PR head, a merge SHA exists, and
`develop` contains that task head. Otherwise `MERGE_RESULT_UNCONFIRMED` blocks without inferring either success
or safe retry. A still-unmerged PR whose current `develop` no longer equals the frozen base is strict base
drift and requires fresh intake, exact-head Review, and CI.

After confirmed readback, Connector/Codex writes the external digest-bound merge receipt described in
[execution.md](execution.md). Receipt identity or digest drift blocks cleanup. Worktree/branch removal remains a
separate cleanup transition: re-read a fresh `cleanup` facts object and require confirmed exact-head merge, a
clean task worktree, and both local and remote-tracking `develop` ancestry. An interrupted cleanup is observed
again; it is never completed from conversation memory or merely from the prior merge decision.
