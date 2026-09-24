# Unified Reference Trading P9 rollout

## 2026-09-25 production checkpoint

The W1 quality-gap correction is integrated at `develop@f3cf595738d2a2fdd20a69e4ec21e23e3a905dbf`.
It labels Newow calculation segments before historical replay and retains the
source gap while omitting a reducer boundary before the owner's first eligible
completed W1 Bar. The targeted regression suite passed 361 tests with 45 skipped;
Ruff and diff checks passed, and independent review found no confirmed issue.
Production-bound, read-only planning at code `45afe2e2a342434ec59cb63440aa49158755845c`
returned `SOURCE_READY=9/9` for PL/PX/RS W1, using each product's authoritative
start and the frozen 2026-09-23 cutoff. The [exact audit](../../../outputs/reference-p9-source-inventory-20260925/w1-45afe2e2-readonly.json)
has file SHA-256 `1070422ef973adecd4910ac50d228456cabca887ccfc182d21e2e4249f0610dd`.
This is source planning evidence, not a historical build or production reader
switch. The 600-stream matrix must be regenerated for the final code identity.
The remaining four Newow D1 product blockers (EB, PB, PD and PG) were
classified read-only as physical D1 replay-prefix gaps. Their exact 43 monthly
direct targets are all already within the frozen wave-1 candidate target set;
the four dry-run plans made zero provider requests. See the
[source diagnosis](../../../outputs/reference-p9-source-inventory-20260925/newow-d1-prefix-a7621201-readonly.json)
and [four exact dry-run plans](../../../outputs/reference-p9-source-inventory-20260925/newow-d1-warmup-a7621201-readonly.json).
The [read-only 0048 preflight](../../../outputs/reference-p9-source-inventory-20260925/schema-0048-preflight-16e28836-readonly.json)
(SHA-256 `80797a87ee5a6e727c525b8c787456485586aaf658c8d6683da326c09c118e51`)
confirmed production schema `0047`, ten READY historical streams all disabled,
zero enabled forward streams, and no `0048` columns. It counted ten revisions,
485 batches, 2,861 actions, 1,514 trades and 38,700 marks. The existing
`0047` batch-kind check is intact. Migration, backup and post-migration readback
remain pending. A fresh preflight is required immediately before migration.
The [full W1 read-only audit](../../../outputs/reference-p9-source-inventory-20260925/w1-full-f3cf5957-readonly.json)
at fix commit `f3cf595738d2a2fdd20a69e4ec21e23e3a905dbf` returned
`SOURCE_READY=180 / BLOCKED=0` for 60 products and all three formal Newow
strategies, using each product's authoritative start and the fixed
2026-09-23 cutoff. Its file SHA-256 is
`a52b99335b0399196578f973b4b1419459e42c5d69eeda5b17841d052545ee8b`.
All rows still carry `execution_gate=UNVERIFIED`; no historical stream was built.
The [read-only D1 scope comparison](../../../outputs/reference-p9-source-inventory-20260925/subing-d1-scope-overlap-readonly.json)
found zero product/physical-contract/month overlap between the 460 current
zero-price investigation keys and either the wave-1 43 direct D1 targets or
the 156 targets of the already applied quality batch. The investigation keys
are not validated publication targets; source classification and a separate
exact data plan remain necessary.
The [date-level read-only D1 inventory](../../../outputs/reference-p9-source-inventory-20260925/subing-d1-zero-dates-f3cf5957-readonly.json)
records the exact 3,113 distinct physical zero-close Bar endpoints across 11
products, including 79 within owner intervals and 460 product/contract/month
investigation keys. Its SHA-256 is
`323ada53dff3521389571fadf8bce2c3ff44bbdda10e946d7e05abac7cacc4f8`.
This inventory is not provider source classification or a publication plan.
The [source-only candidate](../../../outputs/reference-p9-d1-source-20260925/candidate.json)
at task commit `94e513fbdf84ec5b1e15cf70c97e4e89e6506105` binds that
date-level inventory to 460 unique product/contract/month requests, 3,113
target dates and 2,166 same-month response context dates. Its plan SHA-256 is
`337024d346e6c9e8d903f84010027d699f6f33e0ebcef50dd2f18278bd113f0b`.
It uses one concurrent request, zero retries and source capture only; there
is no Canonical or Catalog write. The [official read-only preflight](../../../outputs/reference-p9-d1-source-20260925/preflight-94e513fb.json)
passed with zero provider requests and zero writes; file SHA-256 is
`176eae04a49c54fc81414170e03e593d75f1a9f1217ca577f86f806d2497761a`.
The source verifier suite passed 35 tests, Ruff and diff checks passed, and
independent review found no Confirmed Issue. Execution requires an exact
provider-query authorization; source classification and any quality publication
remain separate steps.

The installed workstation remains `v1.10.33@943c23b61a18156e0d068726ace843aacb6d4e43`.
Production application schema is still `20260919_0047`; the persisted reader and
Reference worker remain disabled. The previously missing 2026-09-24 rank-1
metadata for all 60 operational products was repaired once from the frozen
9/24 source capture (`b15453c3c4bc07c4ba031876b1e5ebd7354937168708d471bcc3bab8b97f2ae8`).
The reviewed one-time code was `b21341d252111f6c37e7ea84fb896828d9ee9ceb`;
the production plan was `e5e6b12210617e9a573270a874aa436b55e4462613232076ae3d48ea9d92dc16`.
It inserted exactly 60 rows without provider or Canonical writes, and the
independent read-only replan returned `equal=60, insert=0`.

With both the production DB and Canonical root bound, a read-only audit of the
published code's RB pilot window (2023-01-01 through 2026-09-23) returned
`SOURCE_READY=10/10`. A broader six-product audit returned 37/60 ready. AO
was initially queried before its authoritative 2023-06-19 listing start;
re-auditing from that start returned 7/10 ready. Raising the source budget
above measured estimates for A, AG, AL, AP and AU returned 37/50 ready and
13 SuBing minute streams blocked by `SUBING_REFERENCE_DATA_UNAVAILABLE`.
The subsequent product-by-product audit used each authoritative listing start
and covered all 600 formal historical candidate streams: 387 were
`SOURCE_READY` and 213 blocked. The final reasons were 175
`SUBING_REFERENCE_DATA_UNAVAILABLE`, 23 `P9_SOURCE_BLOCKED` and 15
`REFERENCE_BOUNDARY_CONTEXT_MISSING`. Only BZ and RB were 10/10 ready.
The one initial SC budget miss was re-audited above its measured bound and
classified as `SUBING_REFERENCE_DATA_UNAVAILABLE`; the original and follow-up
source hashes are retained in the [stream-level matrix](../../../outputs/reference-p9-source-inventory-20260925/matrix.json)
(SHA-256 `1759cd9dcfd6865ba3be193eced1f884bb64fa0ad74a931c956322daeabdccea`).
Representative expanded errors were `CONTRACT_REPLAY_COVERAGE_UNAVAILABLE`
for EB Newow D1 and a non-positive reference price for CJ SuBing D1.

The 175 `SUBING_REFERENCE_DATA_UNAVAILABLE` streams were rechecked with the
published planner: 171 first failed at a physical minute partition, four at
a D1 replay prefix. These first blockers span 58 products and 64 physical
contracts. All 175 bounded `contract-warmup` dry-runs returned `planned` with
zero actual provider requests. The [candidate wave-1 scope](../../../outputs/reference-p9-warmup-wave1-20260925/candidate-plan.json)
(SHA-256 `de734c196c2e02426a41618a5840bdfcbfaab39e74be5fac13a01b7f403c5505`)
deduplicates their targets to 526 direct and 1,485 derived monthly partitions,
with 3,233,580 missing direct bars. It is read-only and does not prove that
repairing these first blockers will make every stream ready. Overlapping
plans must be recalculated after each write and held within the frozen target
set. The bounded campaign code is integrated at
`develop@3555b060438e99ca8c2ab4b69e2e84da54613bfb`. Independent review
found and verified fixes for CLI progress plus pretty JSON parsing and explicit
RQData configuration binding. Its nine targeted tests and Ruff passed. An
actual production-bound read-only CLI check matched its frozen plan hash; the
complete 175/175 read-only preflight then passed with [receipt](../../../outputs/reference-p9-warmup-wave1-20260925/preflight-3555b060.json)
(file SHA-256 `9e996c42e6776dc630488be8857c7a188feda12a0b143b6090df665c1ef9b2a5`).
The receipt binds code, candidate, DB endpoint, Canonical root and project.env
identities, with a ceiling of 526 provider requests and 3,600 seconds. No data
apply or provider request has been made for this wave.

One exact blocker is physical A2305 15m: the read-only warm-up plan
`09b3b98deb8d815007cfde908ea0fd2d9ed70d0478fdf564541d7d4b3d08c2c7`
requires one direct 1m target and nine derived targets. This source audit
does not authorize a data batch. The 0048 migration, additional historical
builds, reader cutover,
forward activation, release of this closeout code, and natural acceptance
remain separate pending Gates.

## Current checkpoint (2026-09-24)

P8 is integrated into `develop@efc896a1ad0f518383d27542207e95a80a0dd804` with
code, targeted tests, independent review and isolated browser/worker/capacity evidence.
P9's default-off worker installation, identity inventory and bounded read-only
source audit are integrated into `develop@7a80b8564a540ef318fd3c7f1ca647615019f742`.
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

A real RB-only source audit at code `e01d60f33faf9fdf2152ff07a92ea0ae4e8fe0ed`
used `since=2023-01-01`, `through=2026-09-23`, and
`as_of=2026-09-23T08:00:00Z`: 10/10 streams were `SOURCE_READY`, with 117,890
input bars and 41,407,559 input bytes, zero DB data writes and released
per-stream maintenance locks. D1 and SuBing minute inputs ended at Sep 23
07:00Z; W1 ended at Sep 18 07:00Z. The report is retained at
`/private/var/folders/5f/3h8_rqbd2nnf_yz0rg3zhhym0000gn/T/guiyi-p9-rb-source-audit-84654792-9317-4701-8027-6485886ef655.json`.
An earlier `as_of=2026-09-24T08:00:00Z` read retained 4 ready and six
`MAIN_CONTRACT_MAP_MISSING` Newow streams because its reader included the
unfinished Sep 24 day. Neither audit saves an executable historical plan,
proves the other 590 formal historical candidates, or enables a stream.

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
