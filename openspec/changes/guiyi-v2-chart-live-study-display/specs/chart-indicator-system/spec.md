## ADDED Requirements

### Requirement: Generic study anchors are independent of Web pagination

The Web adapter SHALL evaluate each whitelisted TA-Lib study in a deterministic block based on the Market trading-day month, including the next trading-day assignment of a night session. Each block SHALL process all expected input through the target, seeded with exactly 256 preceding valid Bars or all contiguous preceding Bars back to a proven owner, explicit quality or verified coverage boundary if earlier. A page edge, ambiguous gap or read-budget limit MUST NOT act as a seed. This policy deliberately re-seeds at month boundaries and does not promise equality to a single calculation over unlimited history. The block policy, exact first input and source identity SHALL identify the calculation anchor. The policy applies only to generic Web display and preserves the Core formula, lookback and parameter contract. Reads and retained calculation state SHALL be bounded. If required endpoint, owner or quality evidence is missing, the affected result SHALL be unavailable. A verified segment with too few inputs for the registered lookback SHALL report WARMING.

#### Scenario: Pagination extends the current chart

- **WHEN** two visible windows contain the same Bar with the same calculation anchor, physical owner, source input and feature parameters
- **THEN** the result for that Bar is identical across both windows
- **AND** the Web adapter slices the aligned result to the requested Bars.

#### Scenario: A source quality boundary interrupts the prefix

- **WHEN** the prefix reaches an explicit invalid or unusable input
- **THEN** no seed crosses that input
- **AND** the next proven segment observes the full registered lookback.

### Requirement: Generic chart demand may consume typed transient market display bars

The adapter SHALL admit only Free, HTDY and SuBing chart profiles and only visible registered studies EMA10, EMA21, EMA60, BOLL and TA-Lib MACD under their existing default parameter contracts. Same-name THS MACD is an independent observation display. During full market closure the generic studies SHALL be driven by the latest verified Canonical data. When the Market display reader proves the same physical owner, frequency, Calendar and Session continuity, completed Live Bars MAY extend a display-only computed prefix beyond Canonical coverage. A current Market activity snapshot MAY be evaluated against a fork of the completed prefix. The interface SHALL identify Canonical, completed Live and active preview inputs separately and bind projected values to the corresponding immutable Bar facts or exact preview observation, including generation, trading day, owner and observed/received timestamps. Daily and weekly previews SHALL use Market-provided D1/W1 activity, without aggregating intraday Bars or quotes in the adapter. Retained price-only tails are ineligible without completed continuity evidence. A completed or preview Bar in a new trading-day month selects its own block seed. A transient result SHALL have Web display permission only. Canonical publication SHALL take precedence over overlapping observations. A same-endpoint revision shall invalidate the affected seed and every dependent result, including later completed and active results computed from that seed. Live unavailability SHALL preserve verified Canonical results and remove unsupported transient points.

#### Scenario: Multiple ticks replace the active Bar

- **WHEN** the Market display provides two observations for the same unfinished endpoint
- **THEN** each preview starts from the same completed prefix
- **AND** neither preview commits that endpoint to the completed state.

#### Scenario: Live input is interrupted by a disconnect, owner change or missing expected endpoint

- **WHEN** Live or preview input cannot be bound to the exact current Market identity and Session
- **THEN** the display rejects the unsupported transient points
- **AND** a new owner starts a separate warm-up using only its own verified segment.

#### Scenario: A newer Canonical publication overlaps a completed Live tail

- **WHEN** the visible Market revision contains new or revised Canonical endpoints
- **THEN** Canonical owns those endpoints and the Web calculation replaces affected values from the new verified prefix
- **AND** a result racing the publication cannot attach to a different chart revision.

#### Scenario: A product-specific or business fact layer is displayed

- **WHEN** a chart shows a published Newow layer, retrospective component, HTDY observation, Alert, Paper event or simulation fill
- **THEN** the layer retains its existing authority and consumer permissions
- **AND** generic Live or preview demand cannot trigger any corresponding calculation or publication workflow.

### Requirement: Transient generic study delivery preserves chart resources

The Web adapter SHALL coalesce active updates, bound pending reads, discard obsolete responses on identity or selection changes and release requests with no remaining display consumer. Only affected generic study layers SHALL update on transient study delivery. Style changes SHALL use existing rendering options without issuing calculation requests. Diagnostics SHALL identify warming, unavailable or invalid input, compute failures and renderer failures.

#### Scenario: Study demand is removed or replaced during a request

- **WHEN** a user switches workspaces or removes the last visible generic study
- **THEN** the Web adapter releases old demand and an in-flight response cannot change the current chart
- **AND** the existing chart and unrelated layer resources are preserved when their identity is unchanged.
