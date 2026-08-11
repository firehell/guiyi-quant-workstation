## Purpose

Defines the slim Web observation surface: Market workbench only, for browsing the active 69-product historical quotes with agreed indicators.

## ADDED Requirements

### Requirement: Web navigation is Market-only
The Web application SHALL expose only the Market workbench in primary navigation and SHALL redirect the site root to the Market list.

#### Scenario: Root opens Market
- **WHEN** a user navigates to `/`
- **THEN** the application redirects to `/market`

#### Scenario: Non-Market module routes are gone
- **WHEN** a user navigates to a former module path such as `/dashboard`, `/signal`, `/strategy`, `/review`, `/data`, or `/runtime`
- **THEN** the application does not render that module and treats the path as not found (or equivalent absent route)

### Requirement: Market list shows active-universe dominants
The Market list page SHALL present dominant-contract coverage for the active product universe so the user can open historical charts.

#### Scenario: Open chart from list
- **WHEN** a user chooses to view a product chart from the Market list
- **THEN** the application navigates to the Market chart route for that product context

### Requirement: Chart retains agreed indicators only as overlays
The Market chart page SHALL support historical bars with EMA10, EMA21, EMA60, 火天大有 (HTDY), and MACD overlays, and MUST NOT present strategy-signal layers, signal markers, or right-rail panels for signal, review, or runtime.

#### Scenario: Indicators available without signal UI
- **WHEN** a user opens a Market chart for a product
- **THEN** the chart can display EMA10/21/60, HTDY, and MACD
- **AND** the page does not show signal-layer controls, StrategySignal markers, or signal/review/runtime right-rail tabs

#### Scenario: Experimental research panel removed
- **WHEN** a user opens a Market chart
- **THEN** the FuturesResearch experimental panel is not present
