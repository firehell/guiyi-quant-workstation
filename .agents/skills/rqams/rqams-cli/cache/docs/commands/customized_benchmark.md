# 自定义基准 API

本页覆盖自定义基准。

## `get customized-benchmark-list`

获取自定义基准列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `fields` | string[]/string | 否 | CLI 返回字段 |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data[]` 为自定义基准列表。支持 `format:"ndjson"`。

## `get customized-benchmark`

获取自定义基准详情。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_benchmark_id` | string | 是 | 自定义基准 ID |

返回：`data` 为自定义基准详情。

## `insert customized-benchmark`

创建自定义基准。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_benchmark` | object | 是 | 自定义基准对象，字段见[自定义基准字段](#自定义基准字段) |
| `raw` | boolean | 否 | 为 `true` 时只返回创建接口原始结果 |

返回：默认返回创建后的基准详情；`metadata.insert_response` 保留创建接口结果。

示例：

```powershell
rqamsc insert customized-benchmark --payload '{"customized_benchmark":{"name":"demo benchmark","type":"fixed_rates","rates":0.03}}'
```

## `update customized-benchmark`

更新自定义基准。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_benchmark_id` | string | 是 | 自定义基准 ID |
| `customized_benchmark` | object | 是 | 更新后的自定义基准对象 |
| `raw` | boolean | 否 | 为 `true` 时只返回更新接口原始结果 |

返回：默认返回 `data.update` 和 `data.benchmark`。

## `delete customized-benchmark`

删除自定义基准。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_benchmark_id` | string | 是 | 自定义基准 ID |

返回：`data.effect_count` 表示删除数量。

## 自定义基准字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 自定义基准 ID |
| `name` | string | 自定义基准名称 |
| `type` | string | 基准类型，例如 `composite`、`fixed_rates` |
| `weights[]` | array | 复合基准成分权重 |
| `weights[].start_date` | string/date | 权重开始生效日期 |
| `weights[].weights[]` | array | 当期成分权重列表 |
| `weights[].weights[].order_book_id` | string | 成分资产代码 |
| `weights[].weights[].weight` | number | 成分权重 |
| `rates` | number | 固定收益率 |
| `remarks` | string/null | 备注 |
| `user_id` | string/int | 创建者用户 ID |
| `workspace_id` | string | 所属 workspace ID |
