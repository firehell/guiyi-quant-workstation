# 模拟交易 API

模拟交易统一使用 `paper-trading` 命令。CLI 会把不同模板的模拟交易配置合并成同一组查询和维护命令。

产品统一使用 `product_id_or_name` 定位。

## `insert paper-trading`

创建或写入模拟交易配置。创建新模拟交易时通过 `template` 选择配置模板；写入既有产品配置时传 `product_id_or_name`。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `template` | string | 创建新模拟交易时必填 | `equity_long`、`conventional` |
| `name` | string | `template=equity_long/conventional` 时必填 | 产品名称 |
| `benchmark` | string/object | `template=equity_long/conventional` 时必填 | 基准 |
| `start_date` | string/date | `template=equity_long/conventional` 时必填 | 起始日期 |
| `init_amount` | number | `template=equity_long/conventional` 时必填 | 初始资金 |
| `algo` | string | `template=equity_long` 时必填 | 撮合方式 |
| `stock_min_fee` | number | `template=conventional` 时必填 | 股票最低手续费 |
| `stock_commission_rate` | number | `template=conventional` 时必填 | 股票佣金率 |
| `loan_rate` | number | `template=conventional` 时必填 | 融资利率 |
| `margin_rate` | number | `template=conventional` 时必填 | 保证金比例 |
| `strategy_category` | string | `template=conventional` 时必填 | 策略类型 |
| `product_id_or_name` | string | 写入既有产品配置时必填 | 目标产品 ID/名称 |
| `config` | object | 否 | 额外配置；会与顶层字段合并 |
| `file_paths` | string[] | 否 | 创建时附带上传的本地文件路径 |

返回：`data` 为创建或写入结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | string | 产品 ID |
| `id` | string/null | 模拟交易配置 ID |
| `effect_count` | number/null | 写入影响数量 |
| `ok` | boolean/null | 是否写入成功 |

示例：

```powershell
rqamsc insert paper-trading --payload '{"template":"equity_long","name":"demo","benchmark":"index,000300.XSHG","start_date":"2026-01-01","init_amount":1000000,"algo":"open"}'
rqamsc insert paper-trading --payload '{"template":"conventional","name":"demo","benchmark":"index,000300.XSHG","start_date":"2026-01-01","init_amount":1000000,"stock_min_fee":5,"stock_commission_rate":0.0003,"loan_rate":0.06,"margin_rate":0.5,"strategy_category":"index_enhanced"}'
rqamsc insert paper-trading --payload '{"product_id_or_name":"demo","stock_min_fee":5,"stock_commission_rate":0.0003}'
```

## `get paper-trading-list`

获取模拟交易配置列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `fields` | string[]/string | 否 | CLI 返回字段 |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data[]` 为合并后的模拟交易配置。支持 `format:"ndjson"`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string/null | 模拟交易配置 ID |
| `product_id` | string | 产品 ID |
| `name` | string/null | 产品或模拟交易名称 |
| `status` | string/null | 模拟交易状态 |
| `strategy_model` | string | 配置模板或策略模型 |
| `benchmark` | string/object/null | 基准 |
| `start_date` | string/date/null | 起始日期 |
| `init_amount` | number/null | 初始资金 |
| `algo` | string/null | 撮合方式 |
| `stock_min_fee` | number/null | 股票最低手续费 |
| `stock_commission_rate` | number/null | 股票佣金率 |
| `loan_rate` | number/null | 融资利率 |
| `margin_rate` | number/null | 保证金比例 |
| `strategy_category` | string/null | 策略类型 |
| `futures_float_rate` | number/null | 期货按比例浮动滑点 |
| `futures_float_amount` | number/null | 期货固定金额滑点 |
| `slippage_rate` | number/null | 按比例滑点 |
| `slippage_ticks` | number/null | 按 tick 滑点 |

## `get paper-trading`

获取单个产品的模拟交易配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |

返回：`data` 为配置对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string/null | 模拟交易配置 ID |
| `product_id` | string | 产品 ID |
| `name` | string/null | 产品或模拟交易名称 |
| `status` | string/null | 模拟交易状态 |
| `strategy_model` | string | 配置模板或策略模型 |
| `benchmark` | string/object/null | 基准 |
| `start_date` | string/date/null | 起始日期 |
| `init_amount` | number/null | 初始资金 |
| `algo` | string/null | 撮合方式 |
| `stock_min_fee` | number/null | 股票最低手续费 |
| `stock_commission_rate` | number/null | 股票佣金率 |
| `loan_rate` | number/null | 融资利率 |
| `margin_rate` | number/null | 保证金比例 |
| `strategy_category` | string/null | 策略类型 |
| `futures_float_rate` | number/null | 期货按比例浮动滑点 |
| `futures_float_amount` | number/null | 期货固定金额滑点 |
| `slippage_rate` | number/null | 按比例滑点 |
| `slippage_ticks` | number/null | 按 tick 滑点 |

## `update paper-trading`

更新模拟交易配置。CLI 会读取现有配置，把 `update_fields` 合并后提交。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `update_fields` | object | 是 | 要更新的配置字段 |

返回：`data` 为更新结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | string/null | 产品 ID |
| `effect_count` | number/null | 更新影响数量 |
| `ok` | boolean/null | 是否更新成功 |

## `delete paper-trading`

删除模拟交易配置。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |

返回：`data` 为删除结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string/null | 删除任务 ID |
| `deleted` | number/null | 删除数量 |
| `effect_count` | number/null | 删除影响数量 |
| `ok` | boolean/null | 是否提交成功 |

## `recompute paper-trading`

提交模拟交易重算。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `date` | string/date | 否 | 指定重算日期 |

返回：`data` 为重算任务或结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string/null | 重算任务 ID |
| `status` | string/null | 任务状态 |
| `effect_count` | number/null | 重算影响数量 |
| `ok` | boolean/null | 是否提交成功 |

## `get paper-trading-signal-list`

获取模拟交易信号列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `fields` | string[]/string | 否 | 信号字段 |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data` 为信号列表；若服务端返回包装对象，列表位于 `data.signals[]`。支持 `format:"ndjson"`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data[]` | array | 信号列表 |
| `signals[]` | array | 信号列表 |
| `signals[].id` | string | 信号 ID |
| `signals[].date` | string/date/null | 信号日期 |
| `signals[].filename` | string/null | 信号文件名 |
| `signals[].fs_id` | string/null | 文件 ID |
| `signals[].status` | string/null | 信号状态 |
| `signals[].type` | string/null | 信号类型 |
| `signals[].orders[]` | array/null | 目标订单 |
| `signals[].matching_results[]` | array/null | 撮合结果 |

## `get paper-trading-signal`

获取单条模拟交易信号详情。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `signal_id` | string | 是 | 信号 ID |
| `fields` | string[]/string | 否 | 信号字段 |

返回：`data` 为信号详情。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 信号 ID |
| `date` | string/date/null | 信号日期 |
| `filename` | string/null | 信号文件名 |
| `fs_id` | string/null | 文件 ID |
| `status` | string/null | 信号状态 |
| `type` | string/null | 信号类型 |
| `orders[]` | array/null | 目标订单 |
| `orders[].order_book_id` | string/null | 合约 ID |
| `orders[].symbol` | string/null | 合约名称 |
| `orders[].side` | string/null | 买卖方向 |
| `orders[].quantity` | number/null | 委托数量 |
| `orders[].target_weight` | number/null | 目标权重 |
| `matching_results[]` | array/null | 撮合结果 |
| `matching_results[].order_book_id` | string/null | 合约 ID |
| `matching_results[].quantity` | number/null | 成交或目标数量 |
| `matching_results[].price` | number/null | 撮合价格 |

## `insert paper-trading-signal`

上传模拟交易信号文件。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `file_paths` | string[] | 是 | 本地信号文件路径，或包含信号文件的目录 |

返回：`data` 为上传任务或处理结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string/null | 上传处理任务 ID |
| `uploaded` | number/null | 上传文件或记录数量 |
| `effect_count` | number/null | 上传影响数量 |
| `ok` | boolean/null | 是否提交成功 |

## `delete paper-trading-signal`

删除模拟交易信号。支持按 `signal_ids` 删除；未传 `signal_ids` 时按日期区间删除。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `signal_ids` | string[] | 否 | 信号 ID 列表 |
| `start_date` | string/date | 否 | 删除起始日期 |
| `end_date` | string/date | 否 | 删除结束日期 |

返回：`data` 为删除任务或结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string/null | 删除任务 ID |
| `effect_count` | number/null | 删除影响数量 |
| `ok` | boolean/null | 是否提交成功 |

## 信号字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 信号 ID |
| `date` | string/date | 信号日期 |
| `status` | string | 信号状态 |
| `type` | string | 信号类型 |
| `orders[]` | array | 目标订单 |
| `matching_results[]` | array | 撮合结果 |
