## MODIFIED Requirements

### Requirement: WebSocket reads are bounded and isolated from the event loop
WebSocket SHALL subscribe before reading its initial snapshot. Synchronous Catalog, Parquet and Redis
reads, including Session and client construction and cleanup, MUST run on a worker thread. Each read
MUST own a fresh resource scope; no Session may be shared across worker calls. Admission SHALL be
bounded to four outstanding reads per process, without an unbounded queue. Saturation MUST close the
connection as unavailable; it MUST NOT bypass Live eligibility, snapshot deduplication or state reset.
An accepted detail connection SHALL periodically reacquire one bounded display snapshot, so a connection
opened while Live is unavailable can recover without relying on a later state Pub/Sub event. Internal Bar
Pub/Sub payloads MUST carry physical-contract provenance; the detail socket SHALL reject a payload whose
contract or trading day differs from its current display authority. An authority change SHALL emit reset
before any Bar owned by the replacement segment; the reset's non-null trading day and contract SHALL
establish that replacement authority for following Bar frames.
Periodic refresh output MUST retain the display snapshot source: delayed post-close Bars SHALL remain a
`post_close` snapshot and MUST NOT be emitted as ordinary realtime Bar frames.

In the approved Market Foundation display mode, the same Market read authority SHALL return quote and
activity as optional display-only facts with separate received and observed times. A physical owner,
trading day or source-generation mismatch SHALL invalidate the preview. Previous unarchived Live may
remain visible after the next Session starts, only for independently proved previous-day ownership.
A covered archived endpoint SHALL use the latest verified Canonical value. D1/W1 preview SHALL require
the proved day or week prefix and SHALL NOT enter completed datasets, signals or execution.

#### Scenario: A read is slow or its caller disconnects
- **WHEN** a synchronous read blocks or the awaiting connection is cancelled
- **THEN** the event loop remains responsive and admission remains held until the actual worker finishes
- **AND** all per-read clients close on their owning worker, while all asynchronous Pub/Sub clients close on exit

#### Scenario: Live recovers without another state event
- **GIVEN** a detail connection was accepted while its Live overlay was unavailable
- **WHEN** a later bounded refresh proves Live available under the same authority
- **THEN** the same connection emits the changed state and completed Bars after its existing watermark

#### Scenario: A late writer publishes after an owner change
- **WHEN** the bounded refresh or state event proves a new trading day or physical contract
- **THEN** the socket emits reset before replacement-owner Bars and rejects late old-owner Pub/Sub payloads

#### Scenario: New night begins before previous-day archive readback
- **GIVEN** the previous day's Live tail is still awaiting archive while the new night's physical owner differs
- **WHEN** a consumer reads the Market display snapshot
- **THEN** the previous-day tail remains independently identified, the newly proved owner provides current preview, and completed-only consumers receive no preview
- **AND** verified old-day archival replaces its Live overlap without changing current-day authority
