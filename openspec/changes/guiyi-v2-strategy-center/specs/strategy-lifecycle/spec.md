## ADDED Requirements

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
