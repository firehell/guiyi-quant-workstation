# Strategy Center

## Purpose

Provide a read-only strategy directory and workspace for the six retained strategies. Strategy Center references the domain-owned identity, configuration, runtime and evidence in Newow, HTDY/TQKQ and SuBing Portfolio.

## Requirements

### Requirement: The strategy catalog contains only the six retained strategy identities

The Strategy Center SHALL register the four retained Newow identities, the HTDY 60m domain strategy identity, and the single SuBing 16-product shared Portfolio identity. Newow Dual Fusion SHALL be typed as a composite strategy consuming Trend and Oscillation results, not as a fourth base formula. Retired strategies, Alerts, generic indicators, chart hints, and research-only L.M.S modes MUST NOT appear as active strategy definitions.

#### Scenario: The catalog is loaded

- **WHEN** the Strategy Center loads its static catalog
- **THEN** it exposes newow_trend, newow_oscillation, newow_main_rise, newow_dual_fusion, htdy_60m, and subing_portfolio_16
- **AND** it identifies each strategy's domain and type
- **AND** it does not reactivate or expose retired strategy identities as active definitions

#### Scenario: A retired identity has historical records

- **GIVEN** a retired strategy has historical Runs, Journals, Events, or research files
- **WHEN** the current catalog is queried
- **THEN** the retired identity is absent from the active strategy list
- **AND** its historical records remain available only through their original audit/read paths

### Requirement: Catalog keys do not replace domain identities

Strategy Center strategy_id values SHALL be stable catalog keys only. They MUST NOT replace, rewrite, alias over, or migrate existing ProductIdentity, formula/rule IDs, stream IDs, account IDs, policy versions, Run IDs, Event IDs, or journal identities owned by existing domains.

#### Scenario: A catalog key maps to an existing Newow identity

- **WHEN** the catalog displays newow_trend
- **THEN** it references the existing Newow strategy/product/formula identities
- **AND** it does not rewrite any saved ReferenceTrading stream, revision, action, or trade identity

### Requirement: Strategy definitions are static, typed metadata rather than executable plugins

The catalog SHALL define stable strategy identity, domain ownership, strategy type, formula/policy references, declared input requirements, supported uses, and result ownership. Definitions MUST NOT contain executable user code, dynamic imports, arbitrary Python expressions, or database-loaded strategy implementations.

#### Scenario: A new strategy is registered

- **WHEN** a new strategy is added to the catalog
- **THEN** it is introduced through a reviewed code definition and an explicit domain adapter
- **AND** registration alone does not create a binding, Scope, subscription, deployment, or Runtime

#### Scenario: An unknown strategy identity is requested

- **WHEN** the API requests a strategy_id absent from the static catalog
- **THEN** the request returns a typed not-found result
- **AND** it does not dynamically load or execute a strategy

### Requirement: Formula, profile, policy, binding, deployment, and research identities remain distinct

The Strategy Center SHALL reference Formula Version, Profile Revision, Policy Version, Binding Revision, Deployment Generation, and Research Run as separate identities. Domain-owned sources remain authoritative for their contents and lifecycle. The Strategy Center MUST NOT replace them with one shared version field or a central editable Profile store.

#### Scenario: A Newow profile changes

- **GIVEN** a Newow domain-owned Profile Revision changes
- **WHEN** the Strategy Center reads the strategy definition
- **THEN** it displays the new domain-owned revision and source reference
- **AND** it does not rewrite the Formula Version or existing reference records

#### Scenario: HTDY policy and formula have different versions

- **GIVEN** the HTDY original formula and account policy use different version identities
- **WHEN** the Strategy Center presents HTDY
- **THEN** it displays the formula and policy references independently
- **AND** it does not treat the account policy as the formula version

### Requirement: Capability, binding, authorization, runtime, and evidence are independent dimensions

The Strategy Center SHALL distinguish catalog registration, supported capability, actual binding, Runtime authorization, observed Runtime state, and research/natural evidence. A supported product/frequency matrix MUST NOT imply a configured binding or enabled Runtime. Missing or stale source evidence MUST be represented as UNKNOWN, UNAVAILABLE, or the source-specific status, never inferred as READY.

#### Scenario: A Newow combination is supported but not configured

- **GIVEN** a product/frequency combination appears in the Newow capability contract
- **AND** no active saved binding or Scope exists for that combination
- **WHEN** the Strategy Center lists the combination
- **THEN** it reports supported capability separately from binding and Runtime authorization
- **AND** it does not create or enable the missing binding

#### Scenario: A Runtime source is unavailable

- **GIVEN** a domain status source cannot be read or its heartbeat is stale
- **WHEN** the Strategy Center builds the runtime projection
- **THEN** it reports the source as unavailable or stale with its diagnostic
- **AND** it does not reuse a prior READY label as current proof

### Requirement: Strategy Center adapters preserve domain ownership

The Strategy Center SHALL use one read adapter per retained domain: Newow, HTDY/TQKQ, and SuBing Portfolio. Adapters MUST consume existing typed services, read APIs, or read-only repositories. They MUST NOT execute strategy formulas, mutate domain state, create Runs, advance cursors, change Scope, submit/cancel orders, write Alerts, or alter account ledgers.

#### Scenario: A strategy detail page is opened

- **WHEN** the Strategy Center reads a domain strategy
- **THEN** it obtains the result and status from that domain's existing owner
- **AND** it does not call a strategy kernel to regenerate the result during the read

#### Scenario: A domain adapter is unavailable

- **WHEN** one domain adapter fails or times out
- **THEN** other domain catalog entries remain readable
- **AND** the unavailable domain is marked with a source-specific diagnostic rather than a fabricated result

### Requirement: Newow remains the owner of its four strategy identities and reference results

Newow SHALL remain the authority for Trend, Oscillation, Main Rise, and Dual Fusion formulas, profiles, state, capability, and ReferenceTrading results. During one admitted input evaluation, the Trend and Oscillation base outputs MUST each be produced once and passed to the Fusion rule; Fusion maintains its own identity/state without invoking the base kernels a second time. Newow Action, Hint, and ReferenceTrade semantics MUST remain distinct.

#### Scenario: Dual Fusion is displayed

- **WHEN** the Strategy Center reads a Dual Fusion result
- **THEN** it presents the Fusion result and references its Trend and Oscillation inputs
- **AND** it does not present Fusion as a new base formula or a separate account

#### Scenario: A Newow Hint is displayed

- **WHEN** the Strategy Center reads a Newow Hint
- **THEN** it preserves quantity_effect=none and its hint identity
- **AND** it does not convert the Hint into an Action, Alert, Order, Fill, or Position

### Requirement: HTDY remains the owner of its original formula and independent account policy

HTDY SHALL retain the original 60m formula, its repainting/observation-only classification, 1m execution eligibility input, fixed-one-lot policy, account risk policy, TQKQ Controller, Journal, native readback, and recovery contracts. Strategy catalog registration MUST NOT grant backtest, formal Live, order, or auto-order capability that is not independently authorized by the existing contracts.

#### Scenario: HTDY is listed while its account Runtime is unavailable

- **WHEN** the Strategy Center loads the HTDY catalog entry but cannot verify the TQKQ Runtime
- **THEN** it may display the retained formula and policy identities
- **AND** it reports account Runtime as unavailable or blocked without implying executable status

#### Scenario: HTDY repainting history is requested

- **WHEN** the Strategy Center displays HTDY historical repainting observations
- **THEN** it labels them as retrospective observation
- **AND** it does not classify them as causal backtest or formal trading signals

### Requirement: SuBing remains one shared 16-product Portfolio

SuBing SHALL remain a single Portfolio strategy with one shared capital/risk state and its existing PortfolioJournal authority. Each continuous execution lifecycle SHALL have one portfolio-level Run; its 16 products MUST NOT be converted into independent strategy accounts, independent capital ledgers, or independent product Runs. Continuous observation and historical replay SHALL remain distinct views of the same Portfolio identity.

#### Scenario: The SuBing portfolio is displayed

- **WHEN** the Strategy Center reads SuBing
- **THEN** it presents one shared Portfolio and its product members
- **AND** it references the existing Run and Journal rather than creating 16 strategy Runs

#### Scenario: A SuBing product has incomplete input

- **WHEN** one product is blocked by missing completed input or execution facts
- **THEN** its product-level diagnostic is preserved
- **AND** the Strategy Center does not silently reset the Portfolio or fabricate an empty position

### Requirement: Alert and research domains remain outside the active strategy catalog

HTDY Alert, SuBing Alert, generic indicators, Newow Hint, Range Detector, and L.M.S research modes SHALL remain separate domains or outputs. Their events, indicators, and research records MUST NOT be converted into strategy definitions or trading results.

#### Scenario: An AlertEvent is shown beside a strategy

- **WHEN** an AlertEvent is visible in a strategy workspace
- **THEN** it retains its Alert source identity and event semantics
- **AND** it does not become a strategy Action, account fill, or order

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

### Requirement: The strategy workspace presents strategies by their owning domain

The Strategy Workspace SHALL group the four Newow identities, the HTDY 60m domain strategy, and the single SuBing shared Portfolio. Detail views MAY share navigation and metadata layout, but MUST preserve domain-specific result semantics and ownership.

#### Scenario: The strategy directory is opened

- **WHEN** a user opens the Strategy Center
- **THEN** the page groups Newow, HTDY, and SuBing separately
- **AND** it shows the six retained strategy identities without retired strategies or unrelated indicators

#### Scenario: A Newow strategy detail is opened

- **WHEN** the user opens a Newow strategy
- **THEN** the page presents its formula/profile references, capability, product/frequency bindings, Action, Hint, and ReferenceTrading evidence
- **AND** it does not show account, order, fill, position, or account PnL as Newow facts

#### Scenario: An HTDY detail is opened

- **WHEN** the user opens HTDY
- **THEN** the page presents the original formula classification, 60m signal/1m eligibility distinction, independent policy references, and TQKQ account facts when readable
- **AND** it labels missing or blocked account facts explicitly

#### Scenario: The SuBing detail is opened

- **WHEN** the user opens SuBing
- **THEN** the page presents one 16-product shared Portfolio, shared capital/risk state, Run/Journal references, and product-level diagnostics
- **AND** it does not display 16 independent strategy accounts

### Requirement: Strategy workspace reads are source-labeled and do not mutate configuration

The initial Strategy Workspace SHALL be read-only. It MUST label the source and as-of time for runtime and result data. It MUST NOT expose strategy enable/disable, Scope editing, Profile writes, policy changes, order actions, Alert activation, or promotion controls in this change.

#### Scenario: A user views a profile reference

- **WHEN** the user views a Formula, Profile, or Policy reference
- **THEN** the page displays the owner, version, and source
- **AND** it does not mutate the domain-owned configuration

#### Scenario: A user sees historical research beside current runtime

- **WHEN** historical research evidence and current runtime facts are both displayed
- **THEN** they are labeled with their separate Run, source, and time identities
- **AND** historical success is not presented as current Runtime health

### Requirement: Strategy lifecycle, Runtime status, and research evidence are separate state dimensions

The Strategy Center SHALL present lifecycle, Runtime status, capability, and evidence as separate dimensions. A candidate, supported capability, successful backtest, or historical result MUST NOT imply an approved deployment or current healthy Runtime.

#### Scenario: A candidate has a successful historical result

- **GIVEN** a research candidate has a successful backtest
- **WHEN** its lifecycle and evidence are displayed
- **THEN** it remains a candidate until an explicit human approval is recorded
- **AND** it does not gain a deployment or account permission

#### Scenario: Runtime is blocked while historical evidence exists

- **GIVEN** a strategy has historical results but its current domain Runtime is blocked
- **WHEN** the Strategy Center presents both
- **THEN** the historical evidence remains readable
- **AND** current Runtime status remains blocked

### Requirement: Promotion requires an explicit human decision and domain-specific authorization

The Strategy Center MUST NOT automatically promote a candidate, modify an active formula or policy, enable a Runtime, expand a Scope, or grant account/order permissions based on AI analysis, backtest performance, or a capability registration. Any future promotion flow SHALL require an explicit human decision and the owning domain's separate authorization contract.

#### Scenario: AI recommends a candidate

- **WHEN** an AI research process recommends a candidate version
- **THEN** the candidate and supporting evidence may be displayed
- **AND** no active formula, Profile, policy, deployment, Scope, or account state changes

#### Scenario: A candidate is approved for research Shadow

- **WHEN** an owner explicitly approves a Shadow evaluation
- **THEN** only the separately authorized Shadow domain may create that deployment
- **AND** the Strategy Center records a reference to the approval/evidence without directly enabling Runtime

### Requirement: Retired strategies remain historical audit identities only

Retired strategies SHALL be excluded from the current active catalog and new default configuration choices. Existing Runs, Journals, Events, and research files SHALL remain associated with their original identities and SHALL NOT be rewritten, merged into current strategy identities, or used as implicit defaults.

#### Scenario: A retired SuBing model is queried

- **WHEN** a user opens an old standalone JM or 14-product SuBing record
- **THEN** it is labeled retired/historical with its original identity
- **AND** it is not presented as the current 16-product shared Portfolio
