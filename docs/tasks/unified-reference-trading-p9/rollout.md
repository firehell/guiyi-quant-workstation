# Unified Reference Trading P9 rollout

## Current checkpoint (2026-09-24)

P8 is integrated into `develop@efc896a1ad0f518383d27542207e95a80a0dd804` with
code, targeted tests, independent review and isolated browser/worker/capacity evidence.
Production is a separate boundary. The active workstation still runs
`v1.10.30@120c5c9490b9909bb64b2e55a5fb5893e57a04c0`; its Reference worker
is absent. A read-only, loopback-enabled `local-services-status.sh` on 2026-09-24
returned `overall=passed`, API/Web 200 and matching supervised service identity.
The initial sandboxed probe returned HTTP `000` because it could not access
loopback, and is not evidence of a service fault.

The production application database is at Alembic `20260919_0047`; the P8
forward `20260923_0048` migration is not applied. The RB historical pilot has
ten published streams, all disabled: Newow's three strategies on D1 and W1,
and SuBing on 15m, 30m, 60m and D1. There are no forward streams. The
persisted-page selector defaults to `legacy`. These are historical records,
not proof of live observation or a switched page.

`develop` now declares 60 formal Newow W1 products while the active v1.10.30
declares 50. The separate v1.10.31 release candidate is still in progress.
Its current `b46fdfd8f8177f530049f920a4aae3853d92ecbd` commit does not
contain the P8 develop commit (`git merge-base --is-ancestor` returned 1), so
it cannot serve as the P9 execution version without a new combined candidate.
Newow 60m is not formally open. Any P9 matrix must bind to one immutable
published code identity and its actual capability and source-data readback;
the RB pilot count is not the remaining-work count.

At the current `develop` capability ceiling, the historical candidate matrix
is 600 stream identities: 60 products × (three Newow strategies × D1/W1 plus
SuBing × four periods). The 10 RB rows are a subset, so at most 590 identities
would be new. This is an enumeration ceiling, not 600 data-ready streams or a
single unbounded apply batch. The forward candidate ceiling is 540 identities
(three Newow strategies × D1/W1 and SuBing × 15m/30m/60m); no stream is
enabled by this arithmetic.

## Execution design

1. **Freeze exact identities and evidence.** Record the immutable code/tag and
   target workstation, active/operational product hashes, formal capability
   matrix, production Alembic head, existing stream/revision/row versions,
   Catalog/Canonical dependency identities, backup/rollback root and current
   health. Keep the release gate and Runtime promotion gate distinct.
2. **Generate a read-only matrix and bounded plan.** Enumerate every formal
   strategy/product/period stream for that code identity. Historical Newow D1
   and W1, and SuBing 15m/30m/60m/D1 are candidates only where authoritative
   completed Canonical/MDS data and quality permit. Exclude closed Newow 60m
   and HTDY repainting-history trades. For each stream record exact first and
   last trading day, physical owner segments, input count/bytes, source digest,
   operation (`build`, `advance` or `rebuild`), and budget. Split plans without
   changing their frozen total scope. A blocked stream remains blocked; no
   shortened window or fabricated zero-trade output is accepted.
3. **Migrate and build in controlled order.** Apply `0048` only after exact
   production DB and rollback checks. Execute each frozen historical plan once,
   with no blind retry on uncertain commit. Read back stream, active revision,
   checkpoint, action/trade/mark counts, source digest and representative
   closed/open/empty page parity against the legacy reader. Candidate failure
   leaves the old published revision and reader intact. No provider download or
   Canonical publication is implicit in this batch.
4. **Cut over the historical reader.** Only after every stream in the page's
   formal scope is READY and parity/coverage checks pass, publish a release
   with `REFERENCE_TRADING_READER_MODE=persisted` as an explicit configuration
   change. Test the actual Market route and API for source identity, pagination,
   snapshot cutoff, empty history, gap and conflict. Rollback selects the
   compatible legacy reader; it never drops reference tables or revisions.
5. **Activate forward recording separately.** Enumerate a bounded formal Live
   scope by strategy/product/period. Every stream needs a sealed FLAT seed,
   exact host/environment, future `recording_start`, activation plan hash,
   budget and recovery policy. Newow D1/W1 uses completed Canonical only;
   SuBing uses completed 15m/30m/60m observations. No missed interval is
   backfilled as first-seen. HTDY stays `MODEL_NOT_APPROVED` until its specific
   first-seen/reversal model is accepted. Installing the worker needs a
   reviewed, exact-root, default-off launcher and activation marker. The
   active v1.10.30 installer only renders the plist; this P9 candidate adds
   a controlled install mode. Alert rule, audience, and 15m
   notification scope stay independent.
6. **Prove natural behavior and recovery.** After enablement, collect actual
   completed-Bar processing, no-signal watermark progress, first new signal,
   close/reversal when it naturally occurs, restart idempotence, delayed and
   missing input handling, and post-market reconciliation. Scenarios not yet
   observed remain pending. Stop writer first for rollback; preserve the DB,
   activation receipts, observations and watermarks. Never downgrade the
   schema to erase forward facts.

## Stop conditions

- Version/capability, source digest, data quality, migration head, exact plan
  hash, reader coverage or rollback compatibility changes before application.
- An unknown commit result, a first-seen gap, a model not accepted, or a
  natural-runtime fault; investigate read-only and do not retry or replay it.
- The v1.10.31 candidate is not released, or its published code differs from
  the matrix. A later combined candidate must contain P8/P9 and the intended
  formal capability. Regenerate plans rather than carrying v1.10.30 counts
  forward.

P9 completion is reported per stream and per gate. A release, migration,
historical build, reader cutover, worker installation and natural evidence are
not interchangeable receipts.
