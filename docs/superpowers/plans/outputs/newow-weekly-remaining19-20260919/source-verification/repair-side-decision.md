# Remaining-19 W1 turnover conflict repair-side decision

Status: `SOURCE_VERIFIED_NO_APPLY`

This packet classifies every conflict week after the authorized read-only
`futures.get_exchange_daily` run. It is **not** an apply permit. Canonical
writes, Catalog writes, retries, native weekly substitution, other products,
and J/PG/SI apply remain forbidden.

Machine-readable twin: `repair-side-decision.json`
(SHA-256 `7d6d35a749e5641fe1c473675fd159b9e3f9d82b82a76d82ad7fb26bc91218c8`).

## Frozen identity

| Item | Value |
|---|---|
| Attempt | `conflict-src-20260920-001` (gitignored local responses) |
| Plan SHA-256 | `fdaf3c8a629f977810b71a01af82b743c9a74f0380eaf75e210590f13642e54f` |
| Catalog revision | `fa01809910bfda3d93de9fe6e213cc46ee4c5463e81db7c5bf49fe56d4b1a8a7` |
| Code SHA | `3958b66d65e4aab45adc7c09db9d7e7450d7e387` |
| As-of | `2026-09-18T07:00:00.000001+00:00` |
| Method | `futures.get_exchange_daily` |
| Requests / responses | 21 / 21 |
| Stop reason | none |
| Canonical writes | 0 |
| Catalog writes | 0 |
| Retry | false |
| Apply authorized | **false** |

Licensed source rows stay in the local attempt directory. The repository keeps
only hashes and sanitized turnover aggregates.

## Classification outcome

20 contracts, 21 conflict weeks, all have a terminal state.

| Class | Weeks | Suggested `repair_target` | Auto-write? |
|---|---|---|---|
| `PROVIDER_MATCHES_D1_NOT_W1` | 0 | `W1_PARTITION` | no — none observed |
| `PROVIDER_MATCHES_NEITHER_D1_STALE` | 2 | `D1_THEN_W1` | **no** — still needs a later write packet |
| `PROVIDER_MATCHES_NEITHER` | 19 | `NONE` | no |

Current provider daily is a **third turnover** on 19 weeks. Stored D1 aggregate
therefore cannot overwrite stored W1: that would publish a value that matches
neither the stored weekly bar nor the live exchange-daily source.

The two judged weeks match stored W1, not stored D1. Overwriting those weekly
bars with the current Catalog D1 aggregate would replace the source-matching
weekly turnover with a stale daily sum.

## Judged weeks (still not authorized to write)

### B2607 `2026-W16`

- `repair_target`: `D1_THEN_W1`
- Evidence: provider aggregate `13705003200` equals stored W1; stored D1
  aggregate is `13705003250`
- D1 preimage: `2026-04` `part.d514af4751df66114e2c1b378ffc0933dc2dd2ac82eb98ab1e55d2d1b4983e9a.parquet` (21 rows)
- W1 preimage: `2026-04` `part.636cf3f17d74ee5db12fccbde67331b25989476122edf95754002aba3d2033ff.parquet` (5 rows)
- Required later write, if separately authorized: refresh the April D1
  partition from the verified exchange-daily rows, then reaggregate affected
  W1 from that new D1. Do not hand-edit turnover. Do not write W1 from the
  current Catalog D1 aggregate.

### B2609 `2026-W33`

- `repair_target`: `D1_THEN_W1`
- Evidence: provider aggregate `21031689100` equals stored W1; stored D1
  aggregate is `21031689130`
- D1 preimage: `2026-08` `part.1967462587e1c3598078adcc3e253b500842958ae55ee12eaeeda75b4184aa2c.parquet` (21 rows)
- W1 preimage: `2026-08` `part.parquet` (2 rows)
- Same write rule as B2607, scoped to August partitions only.

`B2609` also has `2026-W26`, which is `INCONCLUSIVE`. The contract is therefore
`MIXED` and cannot be repaired as a single identity.

## Inconclusive contracts

The remaining 18 contracts, plus `B2609` `2026-W26`, stay `repair_target=NONE`.
Current provider weekly turnover matches neither stored W1 nor stored D1
aggregate. Unlocking them would require a new owner decision to accept the
**current** provider snapshot as a historical revision of **both** D1 and W1.
This packet does not make that decision.

`CJ2601` `2025-W27` is the only cross-month week
(`2025-06-30`..`2025-07-04`). Its provider aggregate also carries a float
residue (`65062594899.999998`). That is recorded, not rounded away.

## BZ / EB

Turnover verification is not replay-gap repair.

| Contract | Week | Turnover class | Replay-gap remaining |
|---|---|---|---|
| BZ2606 | 2026-W17 | `INCONCLUSIVE` | yes |
| BZ2608 | 2026-W26 | `INCONCLUSIVE` | yes |
| BZ2609 | 2026-W30 | `INCONCLUSIVE` | yes |
| EB2405 | 2024-W12 | `INCONCLUSIVE` | yes |

Even a later authorized turnover repair would not by itself make BZ or EB
READY.

## Per-week sanitized turnover

Values are weekly sums. Source OHLCV rows are not committed.

| Contract | Week | Stored W1 | D1 aggregate | Provider aggregate | Target |
|---|---|---|---|---|---|
| B2501 | 2024-W43 | 14200597950 | 14200598010 | 14200598000 | NONE |
| B2505 | 2024-W51 | 16142790030 | 16142789970 | 16142790000 | NONE |
| B2511 | 2025-W34 | 15793187840 | 15793187910 | 15793187900 | NONE |
| B2601 | 2025-W44 | 22422453810 | 22422453820 | 22422453800 | NONE |
| B2605 | 2025-W52 | 14695292850 | 14695292810 | 14695292800 | NONE |
| B2607 | 2026-W16 | 13705003200 | 13705003250 | 13705003200 | D1_THEN_W1 |
| B2609 | 2026-W26 | 23264411820 | 23264411840 | 23264411900 | NONE |
| B2609 | 2026-W33 | 21031689100 | 21031689130 | 21031689100 | D1_THEN_W1 |
| BZ2606 | 2026-W17 | 19694346120 | 19694346070 | 19694346100 | NONE |
| BZ2608 | 2026-W26 | 10568534850 | 10568534870 | 10568534800 | NONE |
| BZ2609 | 2026-W30 | 33382436970 | 33382436930 | 33382436900 | NONE |
| CJ2309 | 2023-W16 | 7381671475 | 7381512325 | 7380890300 | NONE |
| CJ2401 | 2023-W32 | 12534924100 | 12534694000 | 12534110600 | NONE |
| CJ2409 | 2024-W15 | 7857102350 | 7856991925 | 7856251600 | NONE |
| CJ2501 | 2024-W30 | 6894761700 | 6894830250 | 6895294000 | NONE |
| CJ2505 | 2024-W49 | 12918978925 | 12918762225 | 12917900900 | NONE |
| CJ2509 | 2025-W16 | 11324631100 | 11324549625 | 11325375800 | NONE |
| CJ2601 | 2025-W27 | 65062792425 | 65064640675 | 65062594899.999998 | NONE |
| CJ2605 | 2025-W50 | 28770722700 | 28770457675 | 28769900300 | NONE |
| EB2405 | 2024-W12 | 83026074305 | 83026074325 | 83026074300 | NONE |
| EG2601 | 2025-W34 | 39028187780 | 39028187860 | 39028187800 | NONE |

## Next write still needs independent authorization

A later apply packet, if owner authorizes one, must name exact partitions, the
verified attempt hashes above, `canonical_writes` / Catalog mutation scope, and
the fail-closed rule that current Catalog D1 aggregate must not overwrite W1.
This file does not grant that authorization.
