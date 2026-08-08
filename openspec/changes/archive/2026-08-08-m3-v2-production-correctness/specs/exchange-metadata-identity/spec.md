## Purpose

Defines exchange-specific TradingCalendar and TradingSession identity so readers and writers share one fail-closed metadata track without CNFE or hardcoded exchange fallbacks.

## ADDED Requirements

### Requirement: Calendar writer materializes actual exchanges
Calendar upsert MUST write `exchange_code` values equal to the actual `Instrument.exchange_code` values of selected active products. The writer MUST NOT hardcode `CNFE` as the calendar identity. When RQData supplies a generic trading-day set, the system MUST materialize that truth onto each required actual exchange.

#### Scenario: Writer does not persist CNFE as active identity
- **WHEN** metadata bootstrap upserts trading calendar rows for selected products
- **THEN** persisted calendar rows use actual exchange codes such as DCE, SHFE, CZCE, INE, GFEX, or CFFEX and do not introduce new CNFE identity rows as the active write target

### Requirement: Session writer resolves exchange from instruments
Session upsert MUST resolve missing or unreliable provider exchange codes from `Instrument.exchange_code`. The writer MUST NOT default unresolved sessions to `CNFE`. Night-session flags MUST follow evidence-backed rules; the writer MUST NOT unconditionally set `has_night_session=false` for new calendar rows when night-session products are in scope.

#### Scenario: Session rows follow instrument exchange
- **WHEN** provider session rows lack a reliable exchange code for a selected product
- **THEN** the upserted session rows use that product's instrument exchange code

### Requirement: Readers fail closed on actual exchange only
At the final Gate, TradingSessionClock and product session construction MUST query Calendar and Session only by the actual exchange code. The system MUST NOT use CNFE calendar fallback, CNFE session fallback, or CZCE hardcoded missing-session templates. Missing required metadata MUST fail closed.

#### Scenario: Missing actual-exchange session fails closed
- **WHEN** a product requires sessions for exchange E and no usable session templates exist for E
- **THEN** session construction fails closed instead of inventing CNFE or hardcoded CZCE sessions

### Requirement: Fallback removal follows metadata completeness
Reader fallbacks MAY remain only until production actual-exchange Calendar and Session coverage is verified complete. If coverage is incomplete, the system MUST materialize and verify actual-exchange metadata before removing reader fallbacks. The system MUST NOT remove fallbacks in a way that breaks current production reads while actual-exchange rows are still incomplete.

#### Scenario: Incomplete metadata keeps migration ordered
- **WHEN** read-only inventory shows incomplete actual-exchange calendar or session coverage
- **THEN** writer materialization and a metadata normalization gate complete and verify coverage before reader fallbacks are removed
