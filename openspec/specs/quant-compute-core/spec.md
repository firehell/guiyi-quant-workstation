# Quant Compute Core

## Purpose

This specification defines the shared calculation registry, formula and result identities, deterministic inputs, incremental state and publication boundaries for Quant Core consumers.

## Requirements

### Requirement: QC01 Quant Core is a pure independently versioned compute package

`guiyi-quant-core` SHALL remain a pure Python package that accepts validated immutable BarSeries/array inputs and returns typed calculation results. It MUST NOT import RQData, VeighNa runtime, FastAPI, Vue, PostgreSQL, Redis, account stores or order transports. Market identity, physical contract, segment, frequency, source revision, Bar end and availability time MUST be carried through input/result contracts.

#### Scenario: A compute function is called with a validated series

- **GIVEN** a completed BarSeries with one physical owner segment and explicit source revision
- **WHEN** a registered indicator or feature is calculated
- **THEN** it returns values and status bound to the same product, contract, segment, frequency and input revision
- **AND** it performs no network, database, cache or account side effect.

#### Scenario: Input identity crosses a segment boundary

- **GIVEN** input Bars contain more than one physical contract or calculation segment
- **WHEN** a single-segment kernel is invoked
- **THEN** it rejects the mixed input or the caller splits it into separate owner segments
- **AND** no recursive state or rolling window silently crosses the boundary.

### Requirement: QC02 Generic indicator whitelist uses TA-Lib as the sole implementation

The generic indicator registry SHALL expose only EMA10/EMA21/EMA60, MACD 12/26/9, ATR14, STDDEV20, BOLL20/2, HHV, LLV, OBV and Volume Ratio. EMA, MACD, ATR, STDDEV, BOLL, HHV, LLV and OBV MUST call TA-Lib directly with the registered parameters. Volume Ratio MAY use a small NumPy implementation. The generic registry MUST NOT expose SMA, WMA, RSI, KDJ, CCI, OI-derived indicators or other unapproved indicators. The registry MUST NOT maintain a parallel legacy implementation of the same generic indicator.

Volume Ratio SHALL default to current completed volume divided by the average volume of the preceding five completed Bars; the current Bar MUST NOT be included in its own reference average. HHV/LLV generic rolling outputs include the current input Bar; any prior-only breakout reference MUST explicitly shift/exclude the current Bar.

#### Scenario: A generic indicator is requested

- **GIVEN** a valid float64 NumPy input array and a registered generic indicator
- **WHEN** the indicator is calculated
- **THEN** the registered TA-Lib function and parameters are used directly
- **AND** the output is returned without strategy-specific formula rewriting or display rounding.

#### Scenario: An unapproved generic indicator is requested

- **WHEN** a consumer requests SMA, WMA, RSI or an OI-derived generic indicator
- **THEN** the generic registry rejects the request as unsupported
- **AND** an internal legacy formula remains available only through its own strategy-specific contract when that contract requires it.

#### Scenario: Volume Ratio has no valid reference window

- **GIVEN** fewer than N preceding completed Bars, a zero reference average or invalid volume
- **WHEN** Volume Ratio is calculated
- **THEN** the result is WARMING/UNKNOWN/INVALID as appropriate
- **AND** it MUST NOT substitute zero, one or an incomplete current-inclusive average.

### Requirement: QC03 Generic indicators have explicit parameters, readiness and numeric status

Each registered indicator SHALL declare input fields, parameters, supported frequencies, lookback/warm-up, output schema and formula version. TA-Lib leading NaN values MUST be mapped to explicit WARMING/INVALID states and MUST NOT be filled with zero or carried forward as valid output. Analytical float64 outputs MUST NOT replace Decimal market/ledger facts.

#### Scenario: A series is shorter than the indicator warm-up

- **WHEN** the registered lookback is not available
- **THEN** the output marks the unavailable prefix as WARMING and exposes no fabricated numeric value.

#### Scenario: TA-Lib returns non-finite output

- **WHEN** a result point is NaN or infinite
- **THEN** that point is invalid/unavailable with a diagnostic
- **AND** subsequent points are processed only according to the indicator's defined input-validity policy.

### Requirement: QC04 Trend features remain a small owned feature set

The initial Trend Feature Kernel SHALL organize the existing trend direction, EMA21 slope, OLS slope and ATR-normalized slope capabilities. It MUST reuse registered generic indicator outputs and MUST NOT add unvalidated acceleration, persistence, stability or machine-learning factors by default. ABU may inform future research but its source code and GPL implementation MUST NOT be copied into Quant Core.

#### Scenario: Multiple consumers request the same trend feature

- **GIVEN** identical input identity, formula version and parameters
- **WHEN** multiple strategies or chart layers request the trend feature
- **THEN** the shared result may be reused
- **AND** consumers retain independent decision/position/account state.

### Requirement: QC05 Public Price Action Kernel is bounded and causal

The public pattern registry SHALL initially include Swing Pivot, Support/Resistance, Breakout/Breakdown and Retest/Pullback only. Every pattern that requires right-side confirmation MUST distinguish occurrence/pivot time, confirmation time and actual availability time. Retrospective visual backfill MUST NOT be exposed as a prospective signal or formal backtest fact.

#### Scenario: A Swing Pivot requires right-side Bars

- **GIVEN** a candidate pivot at Bar t that requires N right-side completed Bars
- **WHEN** those N Bars have not completed
- **THEN** the pivot remains tentative and unavailable to formal consumers
- **AND** after confirmation its available time is no earlier than the confirming Bar.

#### Scenario: A retrospective shape is displayed

- **GIVEN** a shape whose historical location is determined only after later Bars arrive
- **WHEN** it is returned to a chart
- **THEN** its retrospective/repainting status and confirmation time are explicit
- **AND** it remains ineligible for actions, alerts, backtests or live decisions unless a separate causal contract is approved.

### Requirement: QC06 Strategy-specific kernels retain their formula authority

Newow, HTDY and SuBing specialized kernels SHALL retain their existing formula identities, state machines, parameters, causal/repainting policies and consumer permissions. Reuse of TA-Lib generic indicators MUST NOT silently rewrite internal strategy-specific EMA/SMA/WMA/MACD/ATR calculations. Newow auxiliary outputs SHALL remain display/observation facts according to their existing contracts; the Zhaoyao mirror SHALL remain retrospective-only.

#### Scenario: A generic indicator implementation changes

- **GIVEN** a Newow/HTDY/SuBing kernel internally uses a similarly named mathematical operation
- **WHEN** the generic indicator registry migrates to TA-Lib
- **THEN** the strategy-specific kernel retains its own formula and version
- **AND** no strategy result or golden fixture changes as a side effect.

### Requirement: QC07 Batch, incremental and live computation have separate runtime policies

Quant Core SHALL support batch calculation and pure state-step calculation. The application Compute Runtime SHALL schedule Batch, post-Canonical Incremental and explicitly scoped Live consumers separately. Newow reference calculation SHALL be triggered only by successful post-close Canonical publication. Live calculation SHALL be limited to explicitly enabled consumers and required product/frequency/feature dependencies.

#### Scenario: A Newow chart receives an intraday Tick

- **WHEN** market quote or completed intraday observation advances
- **THEN** Newow reference computation is not triggered by that event
- **AND** the chart may update only the permitted market display facts.

#### Scenario: A scoped simulation consumer receives a completed Bar

- **GIVEN** the consumer has an explicit subscription to a registered feature and matching physical owner segment
- **WHEN** a new completed Bar is committed
- **THEN** only that consumer's required incremental dependencies are advanced once
- **AND** a duplicate input does not advance the same state twice.

### Requirement: QC08 Compute dependency identity and result schema are explicit

A compute result/cache identity SHALL include source revision, product, physical contract, segment, frequency, feature ID, formula version, parameter hash and as-of/availability boundary. Result and state schema versions MUST be separate from package version. Historical revision or owner change MUST invalidate affected dependent results and state.

#### Scenario: A historical Bar is revised

- **GIVEN** a source revision changes an input Bar used by a feature
- **WHEN** the Compute Runtime resolves dependencies
- **THEN** affected results are invalidated/recomputed from the earliest affected dependency boundary
- **AND** unaffected series remain reusable.

#### Scenario: An incremental state schema is incompatible

- **WHEN** a worker loads a checkpoint with an unsupported state schema version
- **THEN** it rejects that checkpoint and rebuilds from a verified input prefix
- **AND** it does not reinterpret the old bytes as a new state.
