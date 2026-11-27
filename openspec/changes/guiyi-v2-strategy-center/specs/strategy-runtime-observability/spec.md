## ADDED Requirements

### Requirement: Runtime status is a read-only projection of domain-owned facts

The Strategy Center SHALL project the original domain status, source timestamp, deployment generation, Run identity, watermark, heartbeat, and diagnostics when those facts are available. The projection MUST preserve the raw domain status and MUST NOT infer current health from code presence, HTTP success alone, an old STATUS entry, or a previously cached READY value.

#### Scenario: A domain heartbeat is stale

- **GIVEN** a domain provides a heartbeat older than its freshness contract
- **WHEN** the Strategy Center builds its status view
- **THEN** it reports stale/unavailable with the original heartbeat timestamp
- **AND** it does not report the domain as currently running

#### Scenario: A domain reports a blocking status

- **GIVEN** a domain reports a specific blocked reason
- **WHEN** the Strategy Center maps it to a common display status
- **THEN** it preserves the original reason code and source status
- **AND** it does not hide the reason behind a generic READY/FAILED label

### Requirement: Strategy Center queries do not execute strategy or research computation

Read APIs and Web page reads SHALL be projection-only. They MUST NOT invoke historical replay, compute missing indicators, build ReferenceTrading revisions, create Portfolio Runs, advance Runtime watermarks, or trigger Research Runs. Missing results remain explicitly missing or unavailable.

#### Scenario: A user refreshes the strategy directory

- **WHEN** the Web client requests the strategy catalog or status
- **THEN** the API reads the catalog and existing domain projections
- **AND** it does not start a strategy task or historical computation

#### Scenario: A result is missing

- **WHEN** the requested domain has no published result
- **THEN** the response reports the missing state and its source
- **AND** it does not calculate a replacement result during the GET request

### Requirement: Strategy computation and account state preserve domain-specific ordering

The Strategy Center MUST NOT introduce a global strategy worker pool or central state manager. Existing Compute Runtime Batch/Canonical/Live queues and each domain's ordering, locks, checkpoint, and commit rules remain authoritative. Independent calculations MAY be parallelized only where their inputs and state partitions are independent and the owning domain contract permits it.

#### Scenario: Newow Fusion consumes base results

- **WHEN** Trend and Oscillation results are available for the same valid input identity
- **THEN** Fusion consumes those results once under its own state and version identity
- **AND** the system does not recompute both base kernels for Fusion

#### Scenario: HTDY calculations overlap across products

- **WHEN** independent product signal calculations are prepared concurrently
- **THEN** account-level risk arbitration, command journal commits, order updates, and recovery remain serialized by the existing TQKQ account owner

#### Scenario: SuBing receives same-time product events

- **WHEN** completed observations for multiple SuBing products share a decision timestamp
- **THEN** the existing Portfolio contract determines event ordering, exit priority, fixed product order, and shared-capital allocation
- **AND** no parallel account transactions can race for the same portfolio capital

### Requirement: Shared features use the existing Compute Registry identity

When multiple consumers request the same registered generic feature, reuse SHALL be governed by the existing Compute Registry and complete FeatureIdentity, including physical contract, segment, frequency, source revision, formula version, parameters, and as-of identity. Strategy Center MUST NOT create a second indicator cache or assume that similarly named features are interchangeable.

#### Scenario: Two Newow strategies request the same EMA

- **WHEN** both requests resolve to the same complete FeatureIdentity
- **THEN** the existing Compute Runtime may reuse the registered feature result
- **AND** each strategy retains its own state and result identity

#### Scenario: A feature identity differs by source revision

- **WHEN** two feature requests use different source revisions or physical segments
- **THEN** they are not treated as the same cached feature
- **AND** no cross-revision or cross-segment reuse occurs

### Requirement: Strategy Center aggregation is bounded and supports partial domain failure

The Strategy Center SHALL use bounded read fan-out, per-domain deadlines, and explicit unavailable results. A slow or failed domain MUST NOT hold an unbounded request or make unrelated catalog entries unavailable. The aggregation MUST NOT add a new message broker or persistent queue.

#### Scenario: One domain read exceeds its deadline

- **WHEN** the SuBing adapter exceeds its read budget
- **THEN** the response returns its timeout/unavailable state
- **AND** Newow and HTDY results remain independently readable
