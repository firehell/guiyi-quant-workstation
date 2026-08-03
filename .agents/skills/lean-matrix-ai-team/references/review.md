# Independent review protocol

The reviewer has a separate context, inherits no implementation conversation, and remains read-only.
Implementation-side and reviewer context sets are globally disjoint across the complete round chain.
The reviewer receives the trusted reviewer brief, validated direct-written handoffs, test receipts,
and [exact-head package](../assets/review-package.md), never a prose claim of success.

Every package and decision belongs under the fixed evidence root:

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
```

The package path is the reviewer report directory's `review-package.json`; the decision path is the
reviewer brief's exact `final-decision.json`. These are fixed derived paths. The next load validates
package digest, exact HEAD, and implementer/reviewer contexts. In other words, recovery validates package digest, exact HEAD, and implementer/reviewer contexts. It also recomputes Git facts, scope,
diff digest, successful exact-HEAD receipts, handoff digest, and ordered specialist evidence digests.

The reviewer records both Spec `PASS/FAIL` and Quality `APPROVED/CHANGES_REQUIRED`. Findings use
severity `Critical`, `Important`, or `Minor`. `Critical` and `Important` are load-bearing. A caller
cannot request a more permissive decision than the verdicts, findings, and round derive:

The independent `FinalDecisionV1` is the only evidence that satisfies `independent-review`. An
implementer Handoff receipt and a GitHub CI check cannot substitute for that decision, just as the
decision cannot substitute for fresh `exact-head-ci` facts.

- `允许集成 develop`: both verdicts approve and no load-bearing finding remains;
- `要求修正后再集成`: approval failed before round 3;
- `阻塞`: approval failed at round 3.

Minor findings alone do not create a repair round. Every repair returns to the frozen round-zero
implementer context and binds the preceding final-decision digest. An approved exact-head decision
may be handed to the existing Codex/GitHub flow, but V06 performs no network, PR, CI polling, merge,
release, Runtime, real-write, notification, or trading action.

## V07 exact-head handoff

The independent `FinalDecisionV1` is necessary evidence but is not a live GitHub observation. Before every
`pre_merge` evaluation, Connector/Codex re-reads the exact PR head/base, current `develop`, CI checks, review
identity/findings, blocking threads, changed paths, and mergeability into `GitHubGateFactsV1`. The reviewed
head/base in `GitHubReviewEvidenceV1` must equal the PR head and frozen expected base. Strict base drift or
head drift invalidates the prior package; fresh intake, exact-head review, and CI are required.

The ready transition never inherits merge authority. If `DevelopGateDecisionV1` returns
`READY_TRANSITION_REQUIRED`, Connector/Codex may mark only that exact PR ready, then must re-read and
re-evaluate before an expected head SHA merge request. The external flow binds the resulting decision and
facts digests into its digest-bound merge receipt after confirmed `merge_readback`. Review approval does not
authorize a separate cleanup transition, main/release/tag, Runtime, real data/DB, strategy/backtest semantics,
notifications, live, deletion, candidate promotion, or GitHub rules.
