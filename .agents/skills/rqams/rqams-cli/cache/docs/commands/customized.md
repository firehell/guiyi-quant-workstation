# 自定义合约 API

本页只覆盖自定义合约。自定义基准和自定义指标已拆到独立页面：

- [自定义基准](customized_benchmark.md)
- [自定义指标](customized_indicator.md)

## `get customized-instrument-list`

获取自定义合约列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `fields` | string[]/string | 否 | CLI 返回字段 |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.customized_instruments[]` 为自定义合约列表。支持 `format:"ndjson"`。

## `get customized-instrument-price`

获取自定义合约价格。CLI 默认返回 `fair_values[]`；传 `raw:true` 时保留服务端完整响应。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_ins_id` | string | 是 | 自定义合约 ID |
| `raw` | boolean | 否 | 是否保留完整响应 |
| `limit` | integer | 否 | CLI 返回条数上限 |

返回：默认返回价格数组；`raw:true` 时返回合约详情对象。

<a id="fair_value"></a>

### `fair_value 单条记录`

单条记录至少包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | date/string | 公允价值日期 |
| `value` | number | 公允价值 |
| `customized_ins_id` | string/ObjectId | 手工编辑回传时通常会带上；文件上传生成的记录通常只有 `date` 和 `value` |

文件上传解析出的价格记录只保留 `date` 和 `value` 两列；如果通过前端手工编辑后再整体回传，服务端会把 `customized_ins_id` 一并写入每条记录。

## `insert customized-instrument`

创建自定义合约。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_instrument` | object | 是 | 自定义合约对象，字段见[自定义合约字段](#自定义合约字段) |

返回：`data` 为创建结果。

示例：

```powershell
rqamsc insert customized-instrument --payload '{"customized_instrument":{"asset_class":"otc_option","order_book_id":"OTC_DEMO","symbol":"demo option"}}'
```

## `insert customized-instrument-price`

上传自定义合约公允价值文件。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_ins_id` | string | 是 | 自定义合约 ID |
| `file_paths` | string[] | 是 | 本地文件路径，或包含文件的目录 |

返回：`data` 为按文件路径聚合的上传结果。

## `delete customized-instrument`

删除自定义合约。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `customized_ins_ids` | string[]/string | 是 | 自定义合约 ID 列表 |

返回：`data` 为删除结果。

## 自定义合约字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 自定义合约 ID |
| `asset_class` | string | 资产类型 |
| `order_book_id` | string | 合约代码 |
| `symbol` | string | 合约名称 |
| `product_id` | string/null | 归属产品 ID |
| `workspace_id` | string | 所属 workspace ID |
| `user_id` | string/int | 创建者用户 ID |
| `create_time` | string/datetime | 创建时间 |
| `fair_values[]` | array<object> | 公允价值记录数组，见上面的 [fair_value 单条记录](#fair_value) |

## 相关页面

- [自定义基准](customized_benchmark.md)
- [自定义指标](customized_indicator.md)
