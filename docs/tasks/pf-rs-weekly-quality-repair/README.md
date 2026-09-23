# PF2611 / RS2609 W1 quality conflict: exact candidate

Read-only prepare on 2026-09-23 produced [`prepare.json`](../../../outputs/pf-rs-weekly-quality/prepare.json), SHA-256 `91eb72014ecefd5e3f99c61139845fd14164138359b235bb7af2f943ac97d63e`. It pins the current Catalog revision `efab2decec3eaa201562dea9493721aaff8a52fc5ca4285adfc0e7a5602f6a80`, Canonical root identity, D1 quality hashes, source identities, old W1 byte hashes, candidate W1 hashes, and exact row lists. Provider requests and D1 writes are both zero. The older 2026-09-18 ten-product audit is diagnosis only; current pointers and D1 facts were reread for this packet.

The September 14 [source verification](../newow-weekly-data-recovery/execution-readiness-20260913.md) found authoritative exchange-daily nonpositive prices for PF2611 and RS2609. Current D1 Catalog still records `NONPOSITIVE_CLOSE` at one or more endpoints in each of the 15 weeks. Every expected D1 endpoint is explained by a price Bar or a quality fact under `weekly-d1-quality-v2`; no W1 price may cover those weeks. RQData W1 alone cannot supersede this D1 evidence. If a later D1 source revision becomes authoritative, this packet must be abandoned and both D1 quality and W1 handled in a new plan.

| Contract | W1 month | Delete conflicted weeks | Retain normal weeks | Catalog action |
| --- | --- | ---: | ---: | --- |
| PF2611 | 2025-11 | 2 | 0 | Remove month pointer |
| PF2611 | 2025-12 | 4 | 1 | Publish immutable candidate |
| PF2611 | 2026-01 | 2 | 2 | Publish immutable candidate |
| PF2611 | 2026-02 | 3 | 0 | Remove month pointer |
| RS2609 | 2025-11 | 1 | 0 | Remove month pointer |
| RS2609 | 2026-08 | 1 | 3 | Publish immutable candidate |
| RS2609 | 2026-09 | 2 | 0 | Remove month pointer |

The 15 deleted trading days and all seven old/new URI and byte identities are in the packet. The six retained rows are byte-equivalent as Canonical values; no D1, other W1 month, other contract, Scope, notification, or Runtime input is in this batch. Old W1 Parquet files remain physically intact. Four empty months have no legal W1 price row and therefore no active W1 month pointer after commit. This is not `NO_TRADE`: all-zero source prices with `NONPOSITIVE_CLOSE` remain quality interruptions, and mixed weeks cannot drop their bad-price days to create a normal W1.

## Validation and execution boundary

`prepare` uses a read-only Catalog transaction. An in-memory store overlay at the fixed cutoff returned PF2611 **3 normal W1 + 11 quality interruptions**; RS2609 still fails later full-prefix replay at `REPLAY_ENDPOINTS_MISSING` from separate missing W1 work. Each of the four RS target weeks has its own complete D1 interruption proof in the packet. Existing MDS, Newow and ReferenceTrade tests verify that quality weeks interrupt calculations, never yield a price Bar, and require normal subsequent warm-up. This candidate does not establish either product as READY.

Before a separately authorized production apply, verify exact code, root, Catalog revision, D1/W1 preimages and packet hash. The script takes the global maintenance lock, recomputes the entire packet under lock, writes three immutable candidate files, and changes seven pointers in one Catalog transaction. It verifies candidates inside the transaction and separately reads active pointers after commit. A repeat against all candidate pointers is reported as `already_applied`; mixed/unknown state is rejected. A commit exception is `COMMIT_OUTCOME_UNKNOWN`: stop and run `inspect` in an independent read-only session. No automatic retry follows.

The exact old metadata and immutable old files provide a recovery path. The `restore` command requires the same packet hash and an explicit flag, takes the same lock, accepts only an all-candidate state, verifies D1 and old W1 hashes, then restores all seven old pointers in one transaction. An isolated SQLite exercise verified apply, candidate readback, restore, old readback, and unchanged unrelated data; a forced second publish failure left both old pointers intact. Production restore requires its own authorization and readback decision. It returns to the old conflict state, so it is an incident recovery action, not a data-quality solution.

No production Canonical/Catalog write, provider download, main/tag publication, Runtime promotion, or formal PF/RS weekly opening has occurred. PF/RS also retain separate missing-W1 and old no-trade-aggregation findings, and the 84 D1/W1 amount differences remain outside this batch. The next Gate is owner authorization of this exact seven-pointer batch and, separately, its recovery scope after final preflight. A changed pointer, source hash, code hash, or Catalog revision requires a new read-only packet.
