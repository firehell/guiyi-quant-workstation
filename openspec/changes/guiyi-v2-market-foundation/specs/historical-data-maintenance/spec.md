## MODIFIED Requirements

### Requirement: Daily maintenance is Catalog-bounded
`UpdateRequest` SHALL default to `full`; optional `daily` MUST reject `since` and require existing continuous
1m/D1 Catalog baseline, complete Calendar and gap-free rank1 mapping. It SHALL select current months,
Catalog-identifiable missing months and exact endpoint gaps, including mapped new dominant contracts.
Missing contract W1 MUST refresh same-contract D1 for its exact complete ISO week within valid lifecycle,
including pre-rank1 dates, in the same provider batch; other valid persisted D1 rows MUST be preserved.
When Catalog contains a validated physical-contract D1 `PriceUnavailableFact` or `NonpositiveCloseFact`,
daily MUST exclude that contract's complete ISO week from W1 price targets and companion D1 refreshes.
The exclusion MUST use the same contract and ISO week and MUST NOT excuse ordinary missing D1/W1 prices,
other contracts or other weeks. Existing source-quality merge and weekly parity guards remain fail-closed.
It MUST NOT open other historical Parquet or automatically bootstrap historical metadata or contract lifecycle.
Missing baseline or indeterminate mapping/boundaries MUST fail closed with historical maintenance required.
Daily groups MUST be bounded by product, family and month and reuse the shared validation, provider and atomic
publication path. Complete ISO-week D1/W1 context and natural quota/restart semantics MUST remain unchanged.
Calendar/Session checks MUST use batch queries. Validated source reuse MUST be limited to one group and
invalidate on Catalog pointer change. Optional typed progress MUST carry bounded identities, stage counters
and durations; completed values MUST count successful operations rather than distinct partitions, unknown totals
MUST be absent, and nested phase durations MUST NOT be added as wall-clock time. Publishing counts MUST follow
successful commit, and observer failure MUST stop the attempt.

In the approved Market Foundation archive mode, a complete publication receipt SHALL require
independent committed-pointer readback and the complete scope's endpoint proof. Cache cleanup SHALL be
limited to recreatable content for the proved trading day and SHALL preserve all observation originals,
consumer cursors and later trading days. A partial publication SHALL NOT issue a complete receipt.
A successful retry of the same day and committed data revision SHALL be one logical publication.
An unknown commit SHALL be independently read back before the affected mutation can proceed.
Natural archive and late recovery SHALL report `LIVE_SUBSCRIPTION_SNAPSHOT_MISSING` for an absent
snapshot that has no eligible retained proof. A present snapshot conflicting with the required scope
or rank1 SHALL report `LIVE_DOMINANT_MISMATCH`. Neither condition permits Live cleanup or a receipt.

In formal Tick mode, the existing late-provider schedule SHALL claim at most one check at the
same D+2 window after two safe pre-publication failures. The check MUST bind the current Runtime
owners, the formal Tick source and the exact failed day's subscription or retained cleanup proof.
A subscription that expired between the original runs and D+2 MAY use its retained digest
bound to the same day, formal source and current rank1. A changed subscription or source SHALL block.
An unresolved schedule from a different source SHALL preserve its original claim budget.
Metadata recovery MUST reject conflicting existing facts. The recovery SHALL use the same committed
readback and cleanup evidence as the natural archive and retain its receipt independently of the
original natural status. Unknown or interrupted commit attempts MUST park further archive writes
pending independent readback. Restart after a verified cleanup checkpoint MAY finish the same
claim through a fresh strict readback before the next natural batch advances Canonical pointers.
This continuation MUST NOT call the provider, reapply a historical plan or send a notification.

#### Scenario: Old physical corruption is outside daily scope
- **WHEN** an old partition has complete Catalog edges but damaged Parquet
- **THEN** daily does not open that partition or claim its integrity; full update/audit remains responsible

#### Scenario: Derived partition missing after restart
- **WHEN** a mapped derived month is missing while its 1m source is complete
- **THEN** daily rebuilds that month from validated 1m without a provider request or success-checkpoint dependency

#### Scenario: Physical weekly price is interrupted by a persisted daily quality fact
- **WHEN** a physical D1 Catalog partition contains a validated price-unavailable or nonpositive-close fact and the same contract's W1 price is absent for that ISO week
- **THEN** daily creates neither a W1 price target nor its companion D1 refresh for that week; ordinary gaps in other weeks remain repairable

#### Scenario: A prior day is completed while the next day's night Session is active
- **GIVEN** complete verified scope for the prior day and active cache and originals for the next trading day
- **WHEN** the archive publishes or completes an interrupted cleanup
- **THEN** the receipt identifies the verified prior-day revision and cleanup removes only the prior day's regenerable cache
- **AND** next-day cache, original observations and every consumer cursor retain their identity

#### Scenario: Historical provider data becomes ready at the late check
- **GIVEN** two safe natural failures and a due, unclaimed late check for the same operational scope
- **WHEN** the single check finishes publication, independent readback and day-scoped cleanup
- **THEN** the late status references the retained archive receipt and the original natural failure remains readable
- **AND** an older repaired day does not replace a newer receipt on the latest pointer
