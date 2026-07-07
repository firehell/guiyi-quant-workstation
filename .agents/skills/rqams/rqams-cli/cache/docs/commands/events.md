# 事件 API

事件按产品管理，分为托管事件和份额事件。托管事件描述申购款到账、赎回款出账、产品费用实付、分红和科目调整；份额事件描述产品份额的申购或赎回变化。

产品统一使用 `product_id_or_name` 定位。该字段可以传产品 ID 或产品名称，CLI 会解析后请求产品接口。

## `get custodian-event-list`

获取产品托管事件列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `custodian_event_type` | string[]/string | 否 | 托管事件类型过滤 |
| `adjust_target` | string | 否 | 科目调整目标过滤 |
| `fields` | string[]/string | 否 | CLI 返回字段列表，例如 `id`、`date`、`custodian_event_type`、`amount` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.custodian_events[]` 为托管事件列表，`data.total` 为服务端匹配数量。支持 `format:"ndjson"`。

示例：

```powershell
rqamsc get custodian-event-list --payload '{"product_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31"}'
rqamsc get custodian-event-list --payload '{"product_id_or_name":"demo","custodian_event_type":["redemption_paid","product_dividend_paid"],"fields":["id","date","custodian_event_type","amount"],"limit":20,"format":"ndjson"}'
```

## `insert custodian-event`

批量插入托管事件。

如果该操作用于修正对账差异，执行前必须先和用户核对产品、日期、`effective_date`、事件类型、金额、调整科目和预期影响，确认后再写入。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `custodian_events` | object[]/object | 是 | 托管事件对象，字段见[托管事件字段](#托管事件字段) |

返回：`data` 为服务端插入结果；成功插入时包含 `effect_count`。

示例：

```powershell
rqamsc insert custodian-event --payload '{"product_id_or_name":"demo","custodian_events":[{"date":"2026-01-31","custodian_event_type":"product_dividend_paid","amount":1000,"effective_date":"2026-01-31"}]}'
```

## `update custodian-event`

更新单个托管事件。服务端按完整托管事件对象替换，因此需要传完整事件字段；`event_id` 可以放在 payload 顶层，也可以作为 `custodian_event.id` 传入。

用于修正对账差异时，执行前必须先展示原事件和拟更新后的完整事件，让用户确认后再提交。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `event_id` | string | 是 | 托管事件 ID |
| `custodian_event` | object | 是 | 完整托管事件对象，字段见[托管事件字段](#托管事件字段) |

返回：`data` 为服务端更新结果，包含 `effect_count`。

示例：

```powershell
rqamsc update custodian-event --payload '{"product_id_or_name":"demo","event_id":"...","custodian_event":{"date":"2026-01-31","custodian_event_type":"product_dividend_paid","amount":1000,"effective_date":"2026-01-31"}}'
```

## `delete custodian-event`

按事件 ID 批量删除托管事件。

删除托管事件会影响现金、应收应付、份额和收益计算。用于修正对账差异时，执行前必须先让用户确认 `event_ids` 和删除原因。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `event_ids` | string[]/string | 是 | 托管事件 ID 列表 |

返回：`data` 为服务端删除结果，包含 `effect_count`。

示例：

```powershell
rqamsc delete custodian-event --payload '{"product_id_or_name":"demo","event_ids":["..."]}'
```

## 托管事件字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 否 | 托管事件 ID；列表返回中存在，更新时可用它代替顶层 `event_id` |
| `date` | string/date | 是 | 出入账或事件发生日期 |
| `custodian_event_type` | string | 是 | 托管事件类型，见[托管事件类型](#托管事件类型) |
| `amount` | number | 是 | 发生金额 |
| `sr_open_date` | string/date/null | 否 | 申赎开放日；`subscription_fund_received`、`redemption_paid` 会使用 |
| `unit_net_value` | number/null | 否 | 申赎单位净值；申购款到账和赎回款出账事件需要 |
| `effective_date` | string/date/null | 否 | 权益生效日期；仅 `product_dividend_paid` 和 `redemption_paid` 支持 |
| `product_cost_type` | string | 否 | 产品费用类型；`product_cost_paid` 需要 |
| `adjust_target` | string | 否 | 科目调整目标；`subject_adjusted` 需要 |
| `adjust_operation` | string | 否 | 科目调整方向；`subject_adjusted` 需要，取值为 `increase`、`decrease`、`adjust_to` |
| `remarks` | string/null | 否 | 备注 |

## 托管事件类型

| 取值 | 说明 |
| --- | --- |
| `subscription_fund_received` | 申购款入账 |
| `redemption_paid` | 赎回款出账 |
| `product_cost_paid` | 产品费用实付 |
| `product_dividend_paid` | 产品分红 |
| `subject_adjusted` | 科目调整 |

## `get unit-event-list`

获取产品份额事件列表和按日期汇总的份额变化。默认情况下，CLI 会从 `data.daily_units[]` 中过滤服务端标记为 `source:"auto"` 的自动份额明细；如需保留自动明细，传 `include_auto_units:true`。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `include_auto_units` | boolean | 否 | 是否保留 `source:"auto"` 的 `daily_units[]` 明细；默认 `false` |
| `fields` | string[]/string | 否 | CLI 返回的 `daily_units[]` 字段列表 |
| `limit` | integer | 否 | CLI 返回的 `daily_units[]` 条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.daily_units[]` 为份额事件明细，`data.unit_changes[]` 为服务端按日期汇总的份额变化。支持 `format:"ndjson"`，此时逐行输出 `daily_units[]`。

示例：

```powershell
rqamsc get unit-event-list --payload '{"product_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31"}'
rqamsc get unit-event-list --payload '{"product_id_or_name":"demo","include_auto_units":true,"fields":["id","date","subscription_units","redemption_units","source"],"limit":20,"format":"ndjson"}'
```

## `insert unit-event`

批量插入手工份额事件。每个事件必须且只能提供 `subscription_units` 或 `redemption_units` 其中一个。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `unit_events` | object[]/object | 是 | 份额事件对象，字段见[份额事件字段](#份额事件字段) |

返回：`data` 为服务端插入结果；成功插入时包含 `effect_count`，行解析失败时包含 `err_msg`。

示例：

```powershell
rqamsc insert unit-event --payload '{"product_id_or_name":"demo","unit_events":[{"date":"2026-01-31","subscription_units":1000}]}'
```

## `update unit-event`

更新单个手工份额事件。`event_id` 可以放在 payload 顶层，也可以作为 `unit_event.id` 传入。服务端要求更新体同时包含 `subscription_units` 和 `redemption_units`，其中一个可以为 `null`。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `event_id` | string | 是 | 份额事件 ID |
| `unit_event` | object | 是 | 份额事件字段，至少包含 `subscription_units` 和 `redemption_units` |

返回：`data` 为服务端更新结果，包含 `effect_count`。

示例：

```powershell
rqamsc update unit-event --payload '{"product_id_or_name":"demo","event_id":"...","unit_event":{"subscription_units":1000,"redemption_units":null}}'
```

## `delete unit-event`

按事件 ID 批量删除手工份额事件。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `event_ids` | string[]/string | 是 | 份额事件 ID 列表 |

返回：`data` 为服务端删除结果，包含 `effect_count`。

示例：

```powershell
rqamsc delete unit-event --payload '{"product_id_or_name":"demo","event_ids":["..."]}'
```

## 份额事件字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 否 | 份额事件 ID；列表返回中存在，更新时可用它代替顶层 `event_id` |
| `date` | string/date | 是 | 份额事件日期 |
| `subscription_units` | number/null | 否 | 申购份额；插入时与 `redemption_units` 二选一 |
| `redemption_units` | number/null | 否 | 赎回份额；插入时与 `subscription_units` 二选一 |
| `source` | string | 否 | 事件来源；列表返回为 `manual` 或 `auto` |

## 份额变化汇总字段

`unit_changes[]` 由服务端按日期聚合生成：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | string | 产品 ID |
| `date` | string/date | 汇总日期 |
| `subscription_units` | number | 当日申购份额合计 |
| `redemption_units` | number | 当日赎回份额合计 |
| `units` | number/null | 当日计算后的产品总份额，取决于服务端估值结果是否存在 |
