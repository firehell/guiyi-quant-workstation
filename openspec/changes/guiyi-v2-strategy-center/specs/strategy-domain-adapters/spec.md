## ADDED Requirements

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
