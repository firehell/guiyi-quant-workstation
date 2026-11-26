## MODIFIED Requirements

### Requirement: MACD auxiliary display preserves the generic kernel contract

`section=auxiliary&component=macd` SHALL remain a read-only display branch of the existing route, with the same product identity, snapshot proof, resource budgets and physical-owner lifecycle. It MUST use the registered TA-Lib MACD implementation with fast=12, slow=26 and signal=9, and expose the TA-Lib DIF, DEA and histogram outputs directly. The display calculation MUST NOT apply the legacy `sma_window` custom kernel or an additional histogram ×2 multiplier. The formula identity SHALL be `talib_macd_12_26_9_v1`; the display adapter identity SHALL be `guiyi_newow_macd_display_v2`. TA-Lib package version and parameter identity MUST be included in the calculation manifest/cache identity. The client SHALL retain `parameters_hash` as 16 lowercase hexadecimal characters, distinct from the 64-character source/snapshot SHA-256 fields. The display adapter version and parameters hash MUST participate in the MACD section cache key.

Each physical owner segment SHALL calculate from the existing completed, as-of-bounded lifecycle replay prefix before projecting observation-eligible points into the display window. Warm-up-only Bars MAY seed that same physical segment but MUST NOT be displayed. The adapter MUST NOT fetch provider data, borrow another contract's state, change strategy formula versions, Action or ReferenceTrade identities, or turn missing/warming values into zero.

The MACD-only envelope SHALL retain `display_adapter_version`, `parameters` and `parameters_hash`; each segment's `data.dif/dea/histogram` SHALL contain aligned points with `bar_end`, `value`, `ready`, `valid` and `reason`. Readiness SHALL follow finite TA-Lib output and the registered warm-up policy; non-finite values MUST remain unavailable. The branch SHALL set `repainting=false`, `formal_signal_eligible=false`, `page_parity=false`, and `allowed_uses=["research_display"]`. Existing auxiliary branch shapes SHALL remain compatible; the top-level envelope SHALL use `newow_product_detail_v2`. MACD MUST NOT feed actions, reference returns or Alert. The client SHALL reject malformed, non-finite, misaligned or contradictory points.

#### Scenario: Display windows share a physical MACD prefix

- **GIVEN** two compatible snapshots differ only in their requested display windows
- **WHEN** each window displays the same physical Bar
- **THEN** DIF, DEA and histogram values and point states SHALL be equal for that Bar
- **AND** a later physical owner segment SHALL restart its own MACD calculation prefix.

#### Scenario: MACD output follows TA-Lib directly

- **GIVEN** a valid completed same-owner Bar prefix and the registered TA-Lib 12/26/9 definition
- **WHEN** the auxiliary MACD section is calculated
- **THEN** its DIF, DEA and histogram are the direct TA-Lib outputs with no additional histogram scaling
- **AND** the section remains research-display-only and does not affect strategy actions, reference returns or Alert.
