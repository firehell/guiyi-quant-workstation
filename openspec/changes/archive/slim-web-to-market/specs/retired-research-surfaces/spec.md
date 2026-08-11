## Purpose

Records retirement of strategy, signal, dashboard, and review executable surfaces from Web and API while leaving DB tables and strategy source packages intact for later rebuild.

## ADDED Requirements

### Requirement: Retired HTTP and WebSocket surfaces are unavailable
The API process SHALL NOT serve dashboard summary, strategy registry, signals (including scan/ack/events), reviews, or `/ws/signals` endpoints as active application routes.

#### Scenario: Signal HTTP is unavailable
- **WHEN** a client calls a former `/api/signals` route
- **THEN** the request is not handled by an active signals router (not found or equivalent unmounted)

#### Scenario: Strategy registry is unavailable
- **WHEN** a client calls the former strategies registry route
- **THEN** the request is not handled by an active strategies router

#### Scenario: Signal WebSocket is unavailable
- **WHEN** a client attempts to connect to `/ws/signals`
- **THEN** the connection is not served by an active signal WebSocket router

### Requirement: Signal and notification workers are not runnable entrypoints
The application SHALL NOT expose RQ worker entrypoints that enqueue or execute signal scan or live notification delivery as part of the slimmed runtime.

#### Scenario: Worker queues omit signal and notification jobs
- **WHEN** the slimmed worker configuration is inspected
- **THEN** signal-scan and notification-delivery job entrypoints are not registered as active queues/tasks

### Requirement: Data and runtime ops surfaces remain
The system SHALL retain Market canonical read APIs, data-center HTTP APIs used for ops, runtime health HTTP, and CLI `data` / `runtime status` commands.

#### Scenario: Runtime status CLI still works
- **WHEN** an operator runs the runtime status CLI
- **THEN** the command can still produce a health status without depending on the removed Web runtime page

#### Scenario: Market bars API remains
- **WHEN** a client requests canonical market bars or indicators through the Market API
- **THEN** the request continues to be served

### Requirement: Persistence and strategy source code are retained
This retirement MUST NOT drop signal/review-related database tables in this change and MUST NOT delete quant-core strategy research source packages.

#### Scenario: No DB drop in this change
- **WHEN** this change is applied
- **THEN** it does not include an Alembic migration that drops signal or review tables

#### Scenario: Strategy packages remain in repo
- **WHEN** the repository is inspected after this change
- **THEN** quant-core strategy research packages remain present even though Web/API entrypoints are removed
