# Remaining-19 W1 turnover conflict source-verification packet

Status: `PLANNED / SOURCE_QUERY_AUTHORIZED / CANONICAL_WRITES_NOT_AUTHORIZED`

This packet freezes the exact `futures.get_exchange_daily` windows for the 20
B/BZ/CJ/EB/EG conflict contracts. Owner authorized read-only provider queries
for these windows. It does not authorize Canonical publication, Catalog commit,
retry, native weekly requests, other products, or J/PG/SI apply.

## Frozen identity

| Item | Value |
|---|---|
| Diagnosis | `all-conflict-weeks.json` |
| Diagnosis SHA-256 | `0ec069562b75d4698bfd356db732a70da348a91e52ce502d358027ef2620e9c3` |
| Plan | `source-verification-plan.json` |
| Plan SHA-256 | `fdaf3c8a629f977810b71a01af82b743c9a74f0380eaf75e210590f13642e54f` |
| Catalog revision | `fa01809910bfda3d93de9fe6e213cc46ee4c5463e81db7c5bf49fe56d4b1a8a7` |
| Catalog stable | yes |
| As-of | `2026-09-18T07:00:00.000001+00:00` |
| Method | `futures.get_exchange_daily` |
| Requests | 21 |
| Expected source rows | 105 |
| Reusable saved daily responses | 0 |
| Canonical writes | 0 |
| Retry | false |

The 5-product Catalog revision is unchanged from the earlier first-week
diagnosis. The 19-product matrix revision `e8450448...` hashes a larger product
set and is not a drift of these 20 contracts.

## Scope

20 contracts, 21 conflict weeks. Only `B2609` has two weeks (`2026-W26` and
`2026-W33`); they are not adjacent and remain two requests. `CJ2601` `2025-W27`
is the only cross-month week and stays one request covering
`2025-06-30`..`2025-07-04` with both June and July D1 partition identities.

Every week still conflicts on `turnover` only. Existing PF/RS source-response
files do not cover these contracts; session-period records are not daily
evidence.

## Authorization boundary

Authorized now:

1. provider `futures.get_exchange_daily` for exactly the 21 frozen requests.

Not authorized:

1. Canonical publication or Catalog mutation
2. native weekly / `get_price` substitution
3. merging windows, extra months, or other products
4. retry after extra dates, missing dates, duplicates, or unknown outcome
5. J/PG/SI batch apply

A later write packet must name exact partitions after this comparison. Current
D1 aggregate values must not overwrite stored W1.

Query completed in attempt `conflict-src-20260920-001` with 21/21 responses and
zero writes. Repair-side classification is in `repair-side-decision.md` /
`repair-side-decision.json`. That decision packet is still not an apply permit.
