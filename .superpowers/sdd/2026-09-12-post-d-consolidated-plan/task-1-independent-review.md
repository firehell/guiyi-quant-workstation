# Task 1 independent review — Package A

Reviewer: independent `gpt-5.6-sol / high`

Fixed point: `24ab72601ea8a7da4c92bd4379c885060485c8f8`

Final reviewed head: `b31e4888b820c0d51afd1123f4990b0c144d3e1e`

## Initial review

Verdict: `Needs fixes`.

The reviewer found two Critical and four Important gaps: untrusted `HOME` could hide retained ownership; the terminal SHA was self-derived; first-install could consume candidate status; partial-install recovery was not demonstrably reachable; launchd cleanup errors could be treated as absence; and public E/F coverage did not use a real stopped binding.

## Fix round 1

Five original findings were closed. The partial-install proof remained incomplete because it did not run a real schema-v5/fixed-SHA authority and public preflight after restoration. The reviewer also found two new Important installer recovery gaps and one Minor quoted-label check.

Verdict: `Findings remain open`.

## Fix round 2

The scoped reviewer verified:

- restored loaded services are checked by Python for plist, root, commit, arguments, working directory and environment;
- restored stopped ownership passes a real schema-v5 `RuntimeDataBinding`, independent expected SHA and public promotion preflight with four-service/config/heartbeat rechecks;
- every mutation after preimage capture enters the common recovery path;
- post-commit cleanup uncertainty returns committed with `retry_safe=false` and does not invite an unsafe retry;
- launchd not-found parsing is bound to the requested label and uid.

The reviewer ran nine focused tests. Result: `9 passed`.

New Critical/Important findings: none.

Final verdict: `Approved` — all findings addressed.

No provider/data write, service mutation, release, Runtime switch, notification or package B/C/D action was performed during implementation or review.
