# SDD ledger — plan: /private/tmp/guiyi-aftermkt-recovery-20260911/2026-09-12-post-d-consolidated-plan.md

Plan SHA256: `e0ff45a0c2e308cd60efa3e01ae2044a0eca6f240a26c991f724b51241b3187b`

## Preflight interface scan

| Pair | Shared interface/state | Dependency ruling | Cost if wrong |
|---|---|---|---|
| A → B | `RuntimeDataBinding`, stopped terminal status, E/F CAS | A must establish one pinned stopped-terminal authority before E/F; B remains a later separately approved real operation. | E/F could run against stale or reappeared writer state. |
| A → C | compatible proof, deployment status authority, installer/preflight, recovery root | A must make Python the common authority used by CLI and deployment checks; shell must not duplicate terminal JSON validation. | Release/preflight could accept a different identity contract than recovery. |
| A → D | new-writer status ownership and natural-run evidence | A must define ownership and failure recovery without loading or switching Runtime. | Natural-run receipts could be written by the wrong root/version. |
| B → C | Session/market readback gates | C may only consume fresh B evidence; no promotion inference from code green. | Runtime could be promoted over incomplete market facts. |
| B → D | data state for natural increment/page checks | D must use post-B current state, not the historical D cutoff. | Acceptance could validate stale data. |
| C → D | exact tag/root/five-service identity | D must bind natural evidence to the exact promoted identity. | Runtime acceptance could be attributed to the wrong build. |
| A → A | closeout, recovery proof, E/F, deployment checks | Implement A as one shared contract; keep ordinary five-loaded-service closeout strict. | Entry points can drift and bypass fail-closed checks. |
| B → B | E then F real operations | Serial only; each exact range/hash requires its own current intent. | Range expansion or replay could mutate unapproved facts. |
| C → C | release then Runtime switch | Separate exact approvals; no implied promotion from release. | Publication and production switch Gates could be conflated. |
| D → D | Live, consumer, after-market, increment, page | Preserve distinct natural evidence and identity receipts. | A partial signal could be reported as full Runtime acceptance. |

## Controller rulings

1. The currently authorized implementation scope is work package A only. B/C/D mutations are not authorized by the consolidated plan approval.
2. A is one serial implementation task because all affected entry points share the same stopped-terminal identity contract.
3. The stopped path is legal only for an exact valid schema-v5 terminal state, an explicitly absent after-market label, an unchanged installed plist/root/commit and exact remaining service identities. Permission/error is not absence. Reappearance or any pinned-state drift fails closed.
4. The ordinary closeout path continues to require all five services loaded; the stopped state never makes promotion pass and never removes the four existing promotion predicates.
5. Frontend test/build evidence may be reused only if frontend source/config/lock remain unchanged from `24ab72601ea8a7da4c92bd4379c885060485c8f8`.
6. The plan uses A/B/C/D headings rather than `Task N`; the controller therefore created a manual Task 1 brief. Omission risk is mitigated by linking the exact plan/spec and reviewing the report and diff against both.

## Task status

- Task 1 / package A: implementation complete at `b31e4888b820c0d51afd1123f4990b0c144d3e1e`
- Independent review: approved after two fix rounds; no open Critical/Important findings
- Controller verification: passed (`438 passed`; Mypy 159; Ruff; OpenSpec 9; repository/canonical 21 passed, 1 deselected; secret, bash syntax and diff checks passed)
- Frontend evidence: reused only because frontend source/config/lock diff is empty from `24ab72601ea8a7da4c92bd4379c885060485c8f8` (existing evidence: 543 passed, 1 skipped; build exit 0)
- Push/develop integration: pending final remote/develop drift check
- External Gates: packages B/C/D, release, Runtime switch and natural acceptance remain unapproved and pending
