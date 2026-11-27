## ADDED Requirements

### Requirement: CI01 Chart Engine is an independently versioned presentation package

`@guiyi/quant-chart` SHALL provide reusable chart hosting, panes, layer lifecycle, renderer registry, indicator catalog and chart profiles on top of the existing Lightweight Charts dependency. It MUST NOT fetch market data, access databases, calculate strategy decisions, create orders or own account facts. It consumes typed, identity-bound data/results from the application layer.

#### Scenario: A chart profile is mounted

- **GIVEN** a validated chart identity and a profile definition
- **WHEN** the Chart Engine mounts
- **THEN** it creates only the required chart/pane/layer resources
- **AND** all data is supplied by the application layer.

### Requirement: CI02 Compute Registry and Display Catalog are separate authorities

Quant Core Compute Registry SHALL own formula identity, inputs, parameters, dependencies, warm-up, permissions and output schema. Quant Chart Display Catalog SHALL own renderer, pane, style, display configuration and profile defaults. Both SHALL use a stable indicator ID. A display item with source type quant_feature MUST resolve to a compatible compute definition; business_fact MUST name its source authority; display_transform MUST be presentation-only.

#### Scenario: A display definition references a missing compute feature

- **WHEN** the Chart Catalog is validated against the Compute Registry manifest
- **THEN** build/test validation fails with the unresolved indicator ID
- **AND** the UI does not silently render an empty or guessed layer.

#### Scenario: A business marker is registered

- **GIVEN** a strategy action, AlertEvent, order/fill or Paper event
- **WHEN** it is added to a chart
- **THEN** it is registered as a business_fact layer with an explicit source owner
- **AND** the chart does not recalculate or reinterpret that fact as a technical indicator.

### Requirement: CI03 Main, volume and auxiliary panes share a stable chart timeline

The Chart Engine SHALL distinguish Main Price Pane, Volume Track and Auxiliary Pane. Price and same-Bar volume SHALL share the existing main chart/time axis. Auxiliary panes SHALL share the same logical time axis, viewport and crosshair while retaining independent value scales. The engine SHALL support a bounded number of auxiliary panes; the initial UI limit is three. Existing Newow profile SHALL continue to show one selected auxiliary pane by default.

#### Scenario: A user adds a second auxiliary indicator

- **GIVEN** a chart profile with one ready auxiliary pane
- **WHEN** the user adds a compatible indicator to a new auxiliary pane
- **THEN** both panes align to the same Bar times, viewport and cursor
- **AND** the main chart and volume track remain unchanged.

#### Scenario: Newow switches its selected auxiliary

- **GIVEN** the existing Newow profile with one selected auxiliary component
- **WHEN** the user selects another Newow auxiliary component
- **THEN** the existing pane is replaced under the same chart identity
- **AND** the previous layer is disposed without creating a second default pane.

### Requirement: CI04 Renderer Registry provides reusable and specialized rendering

The Chart Engine SHALL provide Line, Histogram, Band, Marker, PriceLevel/Zone and Primitive renderer types. A display item MAY compose multiple renderer types. Specialized Primitive MUST be used only when generic renderers cannot represent the required geometry. Each layer SHALL own and release its Series, Primitive, subscriptions, observers and listeners.

#### Scenario: A layer is removed

- **WHEN** a layer is removed or its chart identity is invalidated
- **THEN** all resources owned by that layer are detached/disposed
- **AND** other layers and the shared chart instance remain intact.

#### Scenario: A stale request completes after profile switch

- **GIVEN** a chart profile or market identity has advanced to a newer generation
- **WHEN** an old indicator request completes
- **THEN** it cannot mutate the new chart, pane, series or layer state.

### Requirement: CI05 Existing custom main-chart and auxiliary indicators are preserved

The catalog SHALL retain the existing Newow main-chart overlays, including trend band/channel, oscillation channel, Donchian/dynamic range, main-rise D1-D6 process markers, cup-handle, breakout/wick facts, high/low/nine-turn markers, main-force attack line, target/absorb price references and dual-strategy background, together with the four auxiliary components main_force_control, up_down_energy, zhaoyao_mirror and trend_reversal. Existing structure/actions/hints/breakouts/wicks/detail/stop/Donchian/trend/oscillation/comparison-background controls SHALL remain independently addressable. Existing HTDY observation overlay, Range Detector, SuBing and Free indicators, strategy action/Hint markers, and custom volume display policies SHALL retain their source identities and permissions. Newow profile defaults and existing product-specific visibility behavior MUST remain unchanged except for the separately specified Newow MACD TA-Lib delta.

#### Scenario: A Newow auxiliary component is selected

- **WHEN** the user selects one of the four existing Newow auxiliary components
- **THEN** its existing typed result and formula identity are rendered in the auxiliary pane
- **AND** no other auxiliary formula or strategy action is implicitly activated.

#### Scenario: A repainting auxiliary is displayed

- **GIVEN** the Zhaoyao mirror result
- **WHEN** it is rendered
- **THEN** the chart marks it as retrospective/repainting and does not expose it as a formal strategy signal.

### Requirement: CI06 Volume display policies remain presentation-only and independent

The Chart Catalog SHALL preserve the generic volume scoring/color policy, the SuBing 2x/3x tier display and the Newow-specific volume presentation as distinct display policies. They MUST use the same underlying volume Bar facts and MUST NOT modify OHLCV, create strategy signals, alter Alert rules or affect account/ledger facts. The SuBing tier policy SHALL retain same physical contract and same calculation segment requirements.

#### Scenario: A volume display policy is toggled

- **WHEN** the user changes volume color/tier display settings
- **THEN** only the volume renderer/display transform changes
- **AND** no market data, strategy feature, order or account state is recalculated or modified.

#### Scenario: A volume tier crosses a segment boundary

- **GIVEN** adjacent Bars have different physical contracts or calculation segments
- **WHEN** the SuBing volume tier display is calculated
- **THEN** no 2x/3x comparison is emitted across that boundary.

### Requirement: CI07 Chart Profiles preserve product-specific defaults

Free, Newow Trend/Oscillation/MainRise/Dual, HTDY, SuBing and Backtest SHALL have explicit profile definitions. A profile controls default indicator selection, pane placement, display style and allowed layer categories; it MUST NOT grant new calculation, alert, strategy or trading permissions. Existing defaults and user preferences SHALL be migrated without changing product identity.

#### Scenario: A user switches from Newow Trend to Newow Oscillation

- **WHEN** the strategy profile changes under the same supported chart identity
- **THEN** only incompatible Newow strategy layers are replaced
- **AND** shared market candles, volume and compatible user-selected indicators remain.

#### Scenario: A user switches to HTDY or SuBing

- **WHEN** the product view changes
- **THEN** the destination profile uses its own permitted overlays and volume policy
- **AND** Newow-only layers and retrospective facts are not carried into the destination view.

### Requirement: CI08 Indicator lifecycle distinguishes hide, remove, retire and delete

The Chart UI SHALL support Add, Hide, Remove-from-chart, Configure, Restore-default and diagnostic inspection. Hide SHALL retain the user's selection; Remove SHALL remove only the current chart/profile selection and release its rendering resources; neither action deletes the compute implementation. Retire SHALL prevent new selection while preserving historical identities. Source deletion SHALL require zero active consumers, strategy dependencies, profile references and historical obligations.

#### Scenario: A user hides an indicator used by a strategy

- **GIVEN** an indicator is hidden from the current chart but remains a strategy dependency
- **WHEN** the chart updates
- **THEN** the layer is not rendered
- **AND** the strategy dependency remains available to its authorized consumer.

#### Scenario: A user changes only line color

- **WHEN** a style-only preference changes
- **THEN** the renderer updates without recalculating indicator values.

### Requirement: CI09 Chart diagnostics and visual regression are available

Each layer SHALL expose indicator ID, package/formula version, source identity, frequency, pane, renderer, status, warm-up, data cutoff, cache state and last error/time. Tests SHALL separately cover compute results and chart rendering. Existing custom Newow auxiliary, main overlays and volume displays SHALL have stable visual fixtures.

#### Scenario: A layer is blank

- **WHEN** a user inspects its diagnostics
- **THEN** the system distinguishes missing input, warming, invalid source, compute error, catalog mismatch and renderer failure
- **AND** it does not display an empty chart as a successful no-signal result.
