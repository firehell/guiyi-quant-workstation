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

Candidate capability schema v9 admits the complete 60-product W1 preview scope while the frontend continues to accept the older v4/v8 contracts. Only the remaining-19 W1 path selects v2.

## R2: 20-contract conflict diagnosis

The stored W1 conflicts were reproduced for all 20 contracts: `b=7`, `bz=3`, `cj=8`, `eb=1`, `eg=1`.

- All seven fields, session boundaries, physical-contract ownership, and weekly endpoints were compared.
- `open`, `high`, `low`, `close`, `volume`, and `open_interest` are numerically equal.
- Only `turnover` differs; no conflict is precision-only.
- Current authoritative D1 revisions and stored W1 partition identities are recorded separately.
- The repository contains no original provider response that proves which historical fact is authoritative.

Therefore all 20 contracts are classified `SOURCE_VERIFICATION_REQUIRED`; no automatic overwrite is justified. Evidence: `weekly-conflict-diagnosis.json`.

## R3: frozen prepare manifests

The actual read-only audit produced J first, then PG and SI. Native recovery `prepare` created only local manifests:

| Batch | Units | Provider requests | Expected bars | Lock | SHA-256 |
|---|---:|---:|---:|---|---|
| J | 5 | 80 | 915 | yes | `2c6b54c20b7d3ab615447380f77198b2a968f8705570886e0c37c54140217ba1` |
| PG-001 | 20 | 431 | 4,835 | yes | `9bb1aa1176fa0bac56b4b4eb9dc7ad57e74e4071e52c7fc5458ac3dcf8ac026b` |
| PG-002 | 5 | 107 | 1,190 | yes | `fc7d8b4af4d25f0d55311c6d6c165b043ac45a71586beac66043ba3cc5d79c0f` |
| SI-001 | 20 | 346 | 3,968 | yes | `62b42e9e04fef21c3a352c2d184e9b590aa5d9fa4faf3b634eb3ed43676ee869` |
| SI-002 | 5 | 92 | 1,070 | yes | `be1cec3624658f2e327afb4988924d25a10774a97d86a5df1e694d1d9bd645ea` |

PG totals 25 units / 538 requests; SI totals 25 units / 438 requests. These manifests are proposals, not download/apply receipts.

## R4: fixed 19 x 3 matrix and browser acceptance

The consumer-only API matrix completed all `19 products x 3 strategies = 57` cases and 399 section statuses without exhausting its budget. Catalog revision remained stable.

- 48 cases: `DATA_UNAVAILABLE / REPLAY_ENDPOINTS_MISSING`.
- 9 cases: `INTEGRITY_ERROR / DATA_INTEGRITY_INVALID` (`b`, `cj`, and `eg`, three strategies each).
- 0 cases are `READY` on existing inputs.
- Every case uses `newow_weekly_input_quality_v2`.

The final browser run used one independent context per case and a `finally` close for every context. It completed `57/57 PAGE_PASS`, with `interrupted=0`, `untested=0`, and `fatal=null`. All 57 pages derived the blocked state from the weekly-snapshot response, omitted an explicit `as_of` under default-complete-week mode, matched the API matrix reason, and displayed the terminal unavailable state.

Earlier evidence is retained rather than overwritten:

- `browser-existing-input`: deliberately interrupted after the original runner proved it watched the wrong endpoint; terminal states include completed/interrupted/untested.
- `browser-existing-input-rerun`: browser launch denied by the filesystem sandbox; 57 cases remain untested.
- `browser-existing-input-final`: successful exact-HEAD run.

## External gates still pending

Two operations remain separate and require owner authorization:

1. Source verification for the 20 B/BZ/CJ/EB/EG contracts. This may query the real provider, but must not overwrite Canonical merely because current D1 differs from stored W1.
2. Execution of the frozen J/PG/SI batches. Authorization must explicitly include provider download and, separately, Canonical publication plus Catalog mutation for these exact manifests. Prepare alone grants neither.

After either approved mutation, the fixed API and browser matrices must be rerun against the new exact Catalog revision. Until then, existing-input terminal states are the accepted result, not a data-repair completion claim.
