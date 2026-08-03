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

- `允许集成 develop`: both verdicts approve and no load-bearing finding remains;
- `要求修正后再集成`: approval failed before round 3;
- `阻塞`: approval failed at round 3.

Minor findings alone do not create a repair round. Every repair returns to the frozen round-zero
implementer context and binds the preceding final-decision digest. An approved exact-head decision
may be handed to the existing Codex/GitHub flow, but V06 performs no network, PR, CI polling, merge,
release, Runtime, real-write, notification, or trading action.
