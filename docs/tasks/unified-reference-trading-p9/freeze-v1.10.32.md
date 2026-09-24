# P8/P9 combined release candidate: v1.10.32

This is a code and scope freeze for read-only P9 planning. It is not a release,
Runtime promotion, database migration, historical build, reader cutover, or
forward activation approval. The exact candidate commit is the immutable HEAD
of `codex/reference-p9-combined-rc`; the generated P9 manifest records it.

## Inputs and formal capability

- Published baseline: annotated `v1.10.31` peeled commit
  `bf5dbbfbae905111498a0a2b10ede30e73d03c50`.
- P8/P9 engineering input: `develop@3f5144a2b7acb5fa061a5db9c395153a5a90829b`.
- The merge has no textual conflict. Application and Web version are `1.10.32`.
- Formal Newow capability is `newow_product_capabilities_v22`: all 60 active
  products have D1/W1; 60m remains closed. The formal D1-v2 quality subset has
  10 products and W1-v2 has 19. Their 87 historical and 87 forward Newow
  stream identities bind the formal v2 input policy and futures adaptation;
  V1 streams retain their existing identities. SuBing reference history is 15m/30m/60m/D1;
  forward candidates are 15m/30m/60m. HTDY forward remains
  `MODEL_NOT_APPROVED`. Alert recipients and the 15m notification scope are
  outside this candidate.
- Both `active_products.txt` and `operational_products.txt` are 60-product
  inputs with file SHA-256
  `d2f7e8387fa9dd92b8720ed703de3a7bbc1ef79d0d75340b246783bab079fd1d`.
  The exact manifest must still verify equality and enumerate stream IDs.

The nominal historical matrix is 600 formal stream identities (360 Newow
D1/W1 and 240 SuBing); the forward matrix is 540 (360 Newow D1/W1 and 180
SuBing intraday). These are capability ceilings, not data-ready or enabled
counts. Newow 60m's 180 historical and 180 forward identities are closed.

## Data identity and execution boundary

Generate `reference_trading_p9_manifest.py` from the **clean exact candidate**
with a new output path and read-only production DB identity check. Record its
code SHA, capability version, universe hashes, DB name/schema, existing stream
rows and unmatched IDs. Before any historical work, independently freeze each
stream's Canonical/Catalog/MainContractMap/quality identity, completed-bar
window, physical owner segments, source digest and work budget. The prior RB
10/10 source audit was on `e01d60f33` with `through=2026-09-23` and is not an
audit of this candidate or of the other 590 streams. A source-readiness audit
does not save the full executable plan. No provider request, Canonical publish
or DB data write is included here.

The active workstation readback before this freeze showed Runtime
`v1.10.30@120c5c9490b9909bb64b2e55a5fb5893e57a04c0`, with Reference
worker disabled and immediate Runtime health `failed`. The clean detached
`v1.10.31@bf5dbbfbae905111498a0a2b10ede30e73d03c50` root exists but is
not the supervised root. Recheck these identities and health immediately
before any later operation; do not infer production DB or Canonical state from
the checkout.

## Recovery scope

- Before `0048` or activation, abandon this candidate without production
  rollback. Preserve the current supervised `v1.10.30` root and the published
  detached `v1.10.31` root; neither is removed or switched by this freeze.
- After `0048` and historical writes, stop any Reference writer before code
  rollback. Preserve the additive schema, stream rows, revisions, receipts and
  watermarks. A compatible previous code root with `legacy` reader is a
  candidate only after a real compatibility/preflight check; do not downgrade
  the database or delete reference history as a rollback shortcut.
- Reader cutover and forward activation require separate exact configuration,
  stream coverage, seed, start-time, worker and Runtime gates. Unknown commit
  results, first-seen gaps or source identity drift stop the affected mutation
  pending read-only investigation; no blind replay or retry.

The next P9 operation is bounded, read-only source/DB inventory tied to the
exact candidate SHA. Release and Runtime promotion remain separate decisions.
