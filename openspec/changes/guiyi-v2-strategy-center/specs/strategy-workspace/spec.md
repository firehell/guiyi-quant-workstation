## ADDED Requirements

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
