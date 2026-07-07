# 对账命令

对账命令按产品管理，用于查询对账状态、查询差异、标记人工对账状态，以及在明确确认后触发或撤销自动对账。

批量对账命令使用 `product_ids_or_names`。单产品对账命令使用 `product_id_or_name`。

## `get reconciliation-list`

获取多个产品在日期区间内的对账状态。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_ids_or_names` | string[] | 是 | 产品 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data[]` 为产品维度结果。支持 `format:"ndjson"`。

常见返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | string | 产品 ID |
| `product_name` / `name` | string | 产品名称 |
| `reconciliation_list[]` | array | 按日期的对账状态 |

示例：

```powershell
rqamsc get reconciliation-list --payload '{"product_ids_or_names":["demo"],"start_date":"2026-01-01","end_date":"2026-01-31"}'
```

## `get reconciliation-diff`

获取单个产品某日的对账差异。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `date` | string/date | 是 | 对账日期 |
| `fields` | string[]/string | 是 | 差异分组，可选 `positions`、`prices`、`payable`、`receivable`、`cash`、`net_asset` |

返回：`data` 为按 `fields` 分组的差异结果。

示例：

```powershell
rqamsc get reconciliation-diff --payload '{"product_id_or_name":"demo","date":"2026-01-31","fields":["positions","prices","payable","receivable","cash","net_asset"]}'
```

## `update reconciliation`

统一对账写入入口。`action` 决定写入人工状态、触发自动对账或撤销自动对账。默认使用 `mark`。`auto` 和 `undo_auto` 都应在用户明确确认后使用。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `date` | string/date | 是 | 对账日期 |
| `action` | string | 否 | `mark`、`auto`、`undo_auto`；默认 `mark` |
| `done` | boolean | 否 | `action:"mark"` 时写入人工对账状态 |
| `description` | string | 否 | 人工对账备注 |

Action:

| action | 行为 |
| --- | --- |
| `mark` | 写入人工对账状态 `done` 和 `description` |
| `auto` | 使用估值表覆盖当日流水/头寸相关结果，并可能生成由估值表倒推的流水 |
| `undo_auto` | 撤销自动对账生成的覆盖或倒推结果 |

返回：`data` 为写入或重算结果；`meta.resolved_action` 为实际执行的 action。

示例：

```powershell
rqamsc update reconciliation --payload '{"product_id_or_name":"demo","date":"2026-01-31","action":"mark","done":true,"description":"checked"}'
```

谨慎操作示例，仅在确认估值表应作为当日主数据时使用：

```powershell
rqamsc update reconciliation --payload '{"product_id_or_name":"demo","date":"2026-01-31","action":"auto"}'
rqamsc update reconciliation --payload '{"product_id_or_name":"demo","date":"2026-01-31","action":"undo_auto"}'
```
