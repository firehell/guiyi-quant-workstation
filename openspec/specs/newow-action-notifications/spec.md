# Newow 动作观察通知

## Purpose

独立 Delivery consumer 将已提交的 Newow forward observation 动作推送到 owner 指定的既有
PushPlus Topic。Reference Trading 继续只保存参考事实，不调用 provider，不创建账户或订单。

## Requirements

### Requirement: Explicit scope and activation boundary

The notification policy SHALL default to off. Explicit activation SHALL persist its enabled time,
operational product set and configured Topic fingerprint. Its scope SHALL be exactly
`newow_trend/newow_oscillation/newow_dual_fusion/newow_main_rise` × `1w/1d/60m`.
Configured Topic-code drift SHALL fail closed. Repeated activation SHALL NOT reset the boundary or replay history.
The owner identifies this existing Topic as the four-person audience. Sending credentials do not grant
membership-query access; member count SHALL NOT be represented as independently verified, and the
consumer SHALL NOT modify Topic membership or substitute direct recipients.

#### Scenario: Old completed bar recorded after activation
- **WHEN** a bar end is at or before the activation boundary
- **THEN** its action SHALL NOT be sent even if observed or processed later

### Requirement: Committed actions only

The consumer SHALL read only committed active forward calculation batches from enabled streams.
Only BUILD, REDUCE and CLEAR action facts with stable identity and physical contract SHALL be eligible.
HOLD/FLAT states, hints, seed/history/reconciliation facts and price previews SHALL NOT produce sends.
The consumer SHALL preserve strategy formula, completed-bar identity and observed time.

#### Scenario: A completed bar contains only holding state or a hint
- **WHEN** no eligible action exists
- **THEN** the consumer SHALL perform no provider call

### Requirement: One-shot delivery

Before the external call a durable claim SHALL commit, uniquely binding stream and stable signal identity
independent of revision. Concurrent consumers and restart SHALL NOT send the same signal twice.
Provider acceptance SHALL be distinct from recipient delivery. Failure or unknown provider outcome
SHALL NOT trigger automatic retry, fallback, replay or historical backfill.

#### Scenario: Process stops after claim commit
- **WHEN** no final provider result was persisted
- **THEN** the result remains unknown and SHALL NOT be retried

### Requirement: Delivery isolation and message semantics

Provider latency SHALL NOT block the reference observation scheduler. Messages SHALL include strategy,
product, period, physical contract, action, reference price and completed bar time, and SHALL identify
the result as research observation, not an account trade. PushPlus SHALL use the existing configured
Topic through the shared secure transport; no extra recipients or test broadcasts are authorized.

#### Scenario: Provider request fails
- **WHEN** the external request raises an exception
- **THEN** durable failure/unknown classification is recorded without exposing credentials
- **AND** reference observation scheduling continues
