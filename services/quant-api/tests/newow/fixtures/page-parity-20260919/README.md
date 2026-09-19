# Newow page-parity witnesses — 2026-09-19

These are small, source-derived witnesses for the implementation tasks in
`docs/superpowers/plans/2026-09-19-newow-algorithm-display-parity-plan.md`.
They are not market data and do not assert production availability.

Each JSON's `input_sha256` is the SHA-256 of its `input`, encoded as canonical
JSON (UTF-8, sorted keys, compact separators).  `expected` was transcribed from
the named public function's documented/static rule; it must never be generated
by the Python implementation it tests.

## Source registry

| Source | SHA-256 | Used by |
| --- | --- | --- |
| `stock_detail.html?v=3.3.46` | `4c44ae93ab5d66c361a787f94954ca170daa7e31ecb5e04a19400f51912fdf0f` | chart markers, statistics, recommendation |
| `strategy-calc.js?v=3.3.46` | `bb9e630aa322464a535ccf4951a9c4728bff40e101bdb2a35dddc5d602536fbd` | target/absorb selector and price progress |
| `composite-decision-v2.js?v=3.3.46` | `68c634c05bddc7191de884a37ae5c8877dfd8416a43e53d93c66838ea8585fbb` | CDV2 |
| `trend-reversal-core.js?v=3.3.46` | `85a72b64ca9b9a84ee04338cfffeb28b67dfae923699498a80eb71a22faf6f80` | WR20/MA120 |

The raw public bytes were intentionally not committed.  The frozen hash and
function name make any later replay auditable against
`docs/research/newow-v3.2.82/evidence/latest-audit-20260918.json`.

## Proven versus blocked mappings

`target`, `absorb`, current-period HHV/LLV, the price guard, progress direction,
same-bar chart semantics, WR20/MA120, CDV2 arithmetic, standard/ideal statistics,
and `scoreCombos` are public-function inputs.  The API adapter mapping from a
futures `ProductReader` snapshot to `target_daily`, `target_weekly`,
`cost_daily`, `cost_weekly`, `cross_weekly_buy`, and an exact same-physical
previous close is **EVIDENCE_REQUIRED** until Task 4 adds typed source facts.
No fixture permits guessing those roles by name or treating unavailable data as
parity pass.
