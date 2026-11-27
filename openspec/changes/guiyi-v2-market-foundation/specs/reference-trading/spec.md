## MODIFIED Requirements

### Requirement: Only Newow remains in the active reference calculation scope

The active reference worker SHALL schedule, ingest new deliveries and automatically refresh
reference trades only for Newow strategies. HTDY and SuBing reference streams SHALL remain
outside that scope even when an old database activation is still enabled. Existing identities,
trades, captures, inbox receipts and recovery evidence SHALL remain unchanged; unfinished retired
strategy deliveries SHALL be reported separately from active calculation backlog.

Official historical planning/execution composition and HTDY snapshot build commands SHALL reject
new HTDY/SuBing reference work. HTDY HTTP replay endpoints SHALL return explicit retirement
instead of recalculating trades. Legacy codecs, deterministic verification engines and saved
read-only assets remain available for historical evidence validation.

HTDY and SuBing chart workspaces SHALL NOT mount reference trade/performance panels or load
historical reference replay. They SHALL retain actual AlertEvent markers and audit records;
HTDY SHALL retain the independent TqKq simulation records. This retirement SHALL NOT change
indicator formulas, Alert scope/evaluation, transport configuration, development models or
account execution. The older HTDY/SuBing requirements below define retained historical identities
and evidence, and do not authorize active reference calculation or chart presentation.

After approved Market Foundation cutover, the Newow Market reference worker SHALL consume
verified Market archive receipts only. It SHALL deduplicate by trading day, committed input revision
and series, preserve the previous successful reference revision on failure, and expose the saved as-of
and calculation status. Tick, completed Live, page reads and publication from an independent
research domain SHALL NOT trigger Newow Market reference calculation. Prior forward captures,
references and messages remain available by their original identities. The two independent
simulated account paths and existing Alert continue under their own inputs and permissions.

#### Scenario: Legacy reference activations remain in storage

- **GIVEN** enabled HTDY/SuBing streams and their unfinished original deliveries
- **WHEN** the reference worker reads its scope or accepts a new completed observation
- **THEN** only Newow routes are scheduled and receive new reference deliveries
- **AND** old HTDY/SuBing deliveries are preserved without completion or replay

#### Scenario: Isolated Market rolls forward while a Newow archive receipt is being consumed
- **GIVEN** one verified after-close receipt and newly completed intraday bars for another trading day
- **WHEN** the receipt is read after a consumer restart and the Web chart is refreshed
- **THEN** only the saved Market reference projections may be read and one logical reference publication occurs for that receipt
- **AND** there is no Newow Tick, completed Bar or page-triggered calculation and no reference-derived account or notification effect
