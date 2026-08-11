## Purpose

Defines bounded MarketDataService probe diagnostics for M2 so unreadable and main-contract findings expose stable reason codes without creating a second correctness engine.

## ADDED Requirements

### Requirement: Unreadable findings carry bounded reason codes
When M2 reports a market-data unreadable finding, the finding MUST include a bounded `reason_code` derived from existing MarketDataService, CanonicalHistoricalReader, or session-aligned probe error outcomes. Allowed reason codes MUST include at least: `calendar_missing`, `session_missing`, `probe_window_unavailable`, `dataset_missing`, `coverage_missing`, `catalog_gap`, `manifest_invalid`, `reader_empty`, and `reader_error`. M2 MUST NOT invent a separate database correctness model to guess reasons.

#### Scenario: Calendar absence surfaces as calendar_missing
- **WHEN** a session-aligned probe fails because required TradingCalendar rows for the actual exchange are missing
- **THEN** the M2 finding is unreadable with `reason_code=calendar_missing`

#### Scenario: Empty successful read surfaces as reader_empty
- **WHEN** the reader path completes without throwing but returns no bars for a required probe window that should be covered
- **THEN** the M2 finding is unreadable with `reason_code=reader_empty`

### Requirement: MainContractMap findings distinguish dataset absence
M2 MUST return a main-contract-map invalid finding only when the mapping itself is missing, ambiguous, or violates rank/rule/provider constraints. When the mapping is valid but the expected actual-dominant dataset or window is absent, M2 MUST return a distinct mapped-contract-dataset-missing finding.

#### Scenario: Valid map without dataset is dataset missing
- **WHEN** MainContractMap rank1 points to contract X for a required window and no matching actual-dominant Catalog dataset/window exists
- **THEN** M2 emits mapped-contract-dataset-missing rather than classifying the mapping itself as invalid

#### Scenario: Ambiguous map remains invalid
- **WHEN** MainContractMap coverage for a required day is missing or ambiguous under rank1 rules
- **THEN** M2 emits main-contract-map-invalid
