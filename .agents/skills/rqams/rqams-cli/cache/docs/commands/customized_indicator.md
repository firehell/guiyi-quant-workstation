# 自定义指标 API

本页覆盖产品或产品组上的自定义指标配置，统一使用 `product_like_id_or_name` 定位。

## `get customized-indicator`

获取产品或产品组自定义指标配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |

返回：`data` 为自定义指标配置。

## `insert customized-indicator`

创建产品或产品组自定义指标配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `customized_indicators` | object | 是 | 指标配置对象 |

返回：`data` 为创建结果。

## `update customized-indicator`

更新产品或产品组自定义指标配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `customized_indicators` | object | 是 | 指标配置对象 |

返回：`data` 为更新结果。

## `delete customized-indicator`

删除产品或产品组自定义指标配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |

返回：`data` 为删除结果。
