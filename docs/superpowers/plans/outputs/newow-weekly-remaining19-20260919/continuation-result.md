# Newow W1 remaining 19 continuation result

Date: 2026-09-19

## Scope and boundaries

- Continued from `5ba5a7cc36bd` on `codex/newow-w1-remaining19-sol-continuation`.
- Fixed cutoff: `2026-09-18T07:00:00.000001+00:00`.
- All data diagnosis, readiness, matrix, and browser work was read-only.
- Provider requests: `0`; Canonical/Catalog/production writes: `0`.
- No main merge, tag, release, Runtime promotion, or production acknowledgement was performed.

## R1: immutable W1 quality policy

`newow_weekly_input_quality_v2` is isolated end-to-end for the remaining-19 W1 candidate scope. Product/source/input/calculation/cache/snapshot/inflight/reference identities carry the policy namespace. The v1 identity payload remains unchanged, D1 rejects the W1-only policy, and the formal-41 scope remains unchanged.

Review additionally verified and fixed the ReferenceTrade stream boundary: v1 and v2 now have distinct futures-adaptation versions and stream IDs. The legacy HTTP payload omits the policy field instead of serializing it as `null`. The 60-product after-market audit partitions formal-41 v1 and remaining-19 v2 requests before readiness composition, so it never mixes two policies in one call.

Candidate capability schema v9 admits the complete 60-product W1 preview scope while the frontend continues to accept the older v4/v8 contracts. Only the remaining-19 W1 path selects v2.

## R2: 20-contract conflict diagnosis

The stored W1 conflicts were reproduced for all 20 contracts: `b=7`, `bz=3`, `cj=8`, `eb=1`, `eg=1`.

- All seven fields, session boundaries, physical-contract ownership, and weekly endpoints were compared.
- `open`, `high`, `low`, `close`, `volume`, and `open_interest` are numerically equal.
- Only `turnover` differs; no conflict is precision-only.
- Current authoritative D1 revisions and stored W1 partition identities are recorded separately.
- The repository contains no original provider response that proves which historical fact is authoritative.

Therefore all 20 contracts are classified `SOURCE_VERIFICATION_REQUIRED`; no automatic overwrite is justified. The reviewed diagnostic is fail-closed unless exactly 20 contracts reproduce on one stable Catalog revision with that classification. Evidence: `weekly-conflict-diagnosis-reviewed.json` (`status=diagnosed`, provider requests `0`, writes `0`).

## R3: frozen prepare manifests

The actual read-only audit produced J first, then PG and SI. Native recovery `prepare` created only local manifests:

| Batch | Units | Provider requests | Expected bars | Lock | SHA-256 |
|---|---:|---:|---:|---|---|
| J | 5 | 80 | 915 | yes | `80e2fa2ff048b3c033c44f27143ce1c6cf93617caeeefc736c3eb4eb7bbe3e4d` |
| PG-001 | 20 | 431 | 4,835 | yes | `95fabe9806f7e19268def7451043e29d06039d428f527d35ef165f52c9cd0c4d` |
| PG-002 | 5 | 107 | 1,190 | yes | `f7059620e1b98cb733625e46bf3687a47fb7640ee52aae6aeefb8ab59c431277` |
| SI-001 | 20 | 346 | 3,968 | yes | `1163e7c910b472c52dd248695f691f715ca4aa865b5c819b59130b61e7b80626` |
| SI-002 | 5 | 92 | 1,070 | yes | `4bcb5825be15c1c244cca3145198633eee9eb98f13070de335b10deb5766b2f3` |

All five manifests bind code commit `b02e37b4f8b11aad53c986f4c50b0efeb340376d`, execution-code SHA-256 `e22897fb878cbd86b9c13e60c75de42ec4b0a9831a428e3076e1175235092313`, configuration SHA-256 `c9df3ef2a1a9f4b856b0fdc7a0839eaf9040fcad0eb56b6adc573b819c4ab746`, and Canonical-root SHA-256 `1094b8d30a5f54593c407af265e2f3fc9bdb1655f9a9db84aeba15b74289e5ab`. PG totals 25 units / 538 requests; SI totals 25 units / 438 requests. These manifests and `external-gate-packet-reviewed.md` are proposals, not download/apply receipts.

## R4: fixed 19 x 3 matrix and browser acceptance

The final consumer-only API matrix completed all `19 products x 3 strategies = 57` cases and 399 section statuses. Catalog revision remained stable. It consumed all 399 work items and completed successfully, but the 900-second deadline was reached during finalization, so the artifact truthfully retains `budget_exhausted=true`; this is not represented as unused budget.

- 48 cases: `DATA_UNAVAILABLE / REPLAY_ENDPOINTS_MISSING`.
- 9 cases: `INTEGRITY_ERROR / DATA_INTEGRITY_INVALID` (`b`, `cj`, and `eg`, three strategies each).
- 0 cases are `READY` on existing inputs.
- Every case uses `newow_weekly_input_quality_v2`.

The final reviewed browser run used one independent context per case and a `finally` close for every context. It completed `57/57 PAGE_PASS`, with `interrupted=0`, `untested=0`, and `fatal=null`. Its preview identity, page banner, and input matrix all bind tested code SHA `34fd7dee12c0560d0dbf10421a5bbaebcd327e8d` and Catalog revision `e8450448b08f833ee7f4990856dc9f9937c35aa3fad040c89e172526e3ffa64c`. All 57 pages returned HTTP `409` with API code `NEWOW_DATA_UNAVAILABLE`, used `newow_weekly_input_quality_v2`, derived the blocked state from the weekly-snapshot response, omitted an explicit `as_of` under default-complete-week mode, matched the matrix reason, and displayed the terminal unavailable state. Reason totals were 48 `REPLAY_ENDPOINTS_MISSING` and 9 `DATA_INTEGRITY_INVALID`.

Earlier evidence is retained rather than overwritten:

- `browser-existing-input`: deliberately interrupted after the original runner proved it watched the wrong endpoint; terminal states include completed/interrupted/untested.
- `browser-existing-input-rerun`: browser launch denied by the filesystem sandbox; 57 cases remain untested.
- `browser-existing-input-final`: earlier successful run retained as historical evidence; it did not persist enough exact-code/API assertions for final acceptance.
- `remaining19-matrix-existing-input-reviewed`: 300-second incomplete run retained with 40 `UNSTARTED` cases.
- `remaining19-matrix-existing-input-reviewed-complete`: complete 57/57 run that exactly consumed the 399-work ceiling.
- `remaining19-matrix-existing-input-reviewed-final`: final current-code 57/57 matrix with explicit 400-work allowance; the deadline flag remained exhausted during finalization and is retained.
- `browser-existing-input-reviewed`: reviewed 57/57 run against the earlier matrix, retained as historical evidence.
- `browser-existing-input-reviewed-final`: final 57/57 run with exact matching tested-code SHA, matrix SHA, preview identity, status/code/reason, policy, and Catalog-revision evidence.

## External gates still pending

Two operations remain separate and require owner authorization:

1. Source verification for the 20 B/BZ/CJ/EB/EG contracts. This may query the real provider, but must not overwrite Canonical merely because current D1 differs from stored W1.
2. Execution of the frozen J/PG/SI batches. Authorization must explicitly include provider download and, separately, Canonical publication plus Catalog mutation for these exact manifests. Prepare alone grants neither.

After either approved mutation, the fixed API and browser matrices must be rerun against the new exact Catalog revision. Until then, existing-input terminal states are the accepted result, not a data-repair completion claim.
