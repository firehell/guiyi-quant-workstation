## ADDED Requirements

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
