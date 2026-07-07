# 交易流水 API

交易流水按产品管理。产品统一使用 `product_id_or_name` 定位。产品申购、赎回、产品分红和产品费用属于托管事件概念，维护方式见 [事件 API](events.md)。

## `get trade-list`

查询产品交易流水。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `sources` | string[]/string | 否 | 来源过滤，见[流水来源](#流水来源) |
| `order_book_id` | string | 否 | 合约 ID |
| `symbol` | string | 否 | 名称或代码关键字 |
| `asset_transaction_types` | string[]/string | 否 | 资产交易类型过滤 |
| `account_names` | string[]/string | 否 | 账户名过滤 |
| `asset_unit_ids` | string[]/string | 否 | 资产单元 ID 过滤 |
| `key_words` | string | 否 | 关键字 |
| `group_by` | string | 否 | 服务端分组字段 |
| `remarks` | string | 否 | 备注过滤 |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.trades[]` 为交易流水，字段见[交易流水字段](#交易流水字段)。支持 `format:"ndjson"`。

示例：

```powershell
rqamsc get trade-list --payload '{"product_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31","limit":20}'
```

## `insert trade`

批量插入交易流水。CLI 会按 openapi 流水提交，导入后服务端返回的 `source` 为 `open_api`。

如果该操作用于修正对账差异，执行前必须先和用户核对产品、日期、交易类型、合约、方向、数量、价格/金额、账户、资产单元和预期影响，确认后再写入。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `trades` | object[] | 是 | 交易流水数组，字段见[交易流水字段](#交易流水字段) |
| `chunk_size` | integer | 否 | 分批提交大小 |

返回：`data` 为批量插入结果；分批提交时返回各批次结果汇总。

示例：

```powershell
rqamsc insert trade --payload '{"product_id_or_name":"demo","trades":[{"transaction_type":"buy","datetime":"2026-01-05 09:31:00","order_book_id":"000001.XSHE","symbol":"平安银行","quantity":100,"price":10.5,"account":"stock","remarks":"manual insert"}]}'
```

## `delete trade`

删除交易流水。可以按 `trade_ids` 删除，也可以按日期区间和来源删除。

删除流水会影响历史持仓、现金和收益计算。用于修正对账差异时，执行前必须先让用户确认删除范围，优先使用 `trade_ids` 精确删除，避免只按日期和来源误删。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `trade_ids` | string[]/string | 否 | 交易流水 ID |
| `start_date` | string/date | 否 | 删除日期区间起点 |
| `end_date` | string/date | 否 | 删除日期区间终点 |
| `sources` | string[]/string | 否 | 来源过滤 |

返回：`data` 为删除结果。

## `insert settlement-trade`

上传交割单文件并触发解析。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `account_name` | string | 是 | 产品账户名 |
| `file_paths` | string[] | 是 | 一个或多个交割单文件路径 |

返回：`data` 为上传任务或解析结果。

示例：

```powershell
rqamsc insert settlement-trade --payload '{"product_id_or_name":"demo","account_name":"stock","file_paths":["D:/tmp/settlement.csv"]}'
```

## 交易流水字段

| 字段 | 类型 | 上传 | 返回 | 说明 |
| --- | --- | --- | --- | --- |
| `_id` | string | 否 | 是 | AMS 交易流水 ID |
| `asset_class` | string | 否 | 是 | 资产类型，见[资产类型](#资产类型) |
| `trading_asset_class` | string | 否 | 否 | 交易属性，用于辅助服务端识别资产 |
| `transaction_type` | string | 是 | 是 | 交易类型，见[交易类型](#交易类型) |
| `account` | string | 否 | 是 | 产品账户名；不传时服务端使用产品第一个账户 |
| `datetime` | string/datetime/date | 是 | 是 | 交易时间 |
| `trading_date` | string/date | 否 | 是 | 交易日期 |
| `order_book_id` | string | 是 | 是 | 合约 ID；现金类资产传 `CNY` |
| `symbol` | string | 是 | 是 | 合约名称 |
| `quantity` | number | 否 | 是 | 交易数量；非现金类交易需要 |
| `price` | number | 否 | 是 | 交易价格；回购类价格表示利率 |
| `settlement_amount` | number | 否 | 是 | 结算金额；资金、利息、分红、债券还本付息类流水需要 |
| `commission` | number | 否 | 是 | 佣金 |
| `tax` | number | 否 | 是 | 税费 |
| `other_fees` | number | 否 | 是 | 其他费用 |
| `exchange_rate` | number | 否 | 是 | 汇率 |
| `remarks` | string | 否 | 是 | 备注 |
| `source` | string | 否 | 是 | 流水来源，见[流水来源](#流水来源) |
| `foreign_id` | string | 否 | 是 | 外部标识 ID；相同 `foreign_id` 的 openapi 流水会覆盖更新 |
| `asset_unit_id` | string | 否 | 是 | 资产单元 ID |

## 交易类型

| 取值 | 说明 | 金额字段 |
| --- | --- | --- |
| `buy` | 买入 | `quantity` + `price` |
| `sell` | 卖出 | `quantity` + `price` |
| `buy_open` | 多头开仓 | `quantity` + `price` |
| `sell_close` | 多头平仓 | `quantity` + `price` |
| `sell_open` | 空头开仓 | `quantity` + `price` |
| `buy_close` | 空头平仓 | `quantity` + `price` |
| `cash_in` | 入金 | `settlement_amount` |
| `cash_out` | 出金 | `settlement_amount` |
| `dividend_payment` | 红利入账 | `settlement_amount` |
| `dividend_tax_payment` | 红利税支付 | `settlement_amount` |
| `interest_income` | 利息收入 | `settlement_amount` |
| `interest_payment` | 利息支出 | `settlement_amount` |
| `coupon_payment` | 债券付息 | `settlement_amount` |
| `principal_payment` | 债券偿付本金 | `settlement_amount` |
| `reverse_repo` | 逆回购 | `quantity` + `price` |
| `reverse_repo_repurchase` | 逆回购购回 | `quantity` + `price` |
| `repo` | 正回购 | `quantity` + `price` |
| `repo_repurchase` | 正回购购回 | `quantity` + `price` |

## 流水来源

| 取值 | 说明 |
| --- | --- |
| `manual` | 手工录入 |
| `settlement_upload` | 日终结算流水文件导入 |
| `intraday_upload` | 日内流水文件导入 |
| `open_api` | API 或 CLI 导入 |
| `paper_trading` | 模拟交易生成 |
| `auto_balance` | 自动权益生成 |
| `netting_derived_shadow` | 估值表覆盖头寸后倒推生成 |
| `client_upload` | 客户端上传 |

## 资产类型

| 取值 | 说明 |
| --- | --- |
| `stock` | 股票 |
| `convertible_bond` | 可转债 |
| `bond` | 债券 |
| `repo` | 正回购 |
| `reverse_repo` | 逆回购 |
| `open_end_fund` | 开放式基金 |
| `etf_fund` | ETF 基金 |
| `lof_fund` | LOF 基金 |
| `money_market_fund` | 货币基金 |
| `commodity_futures` | 商品期货 |
| `stock_index_futures` | 股指期货 |
| `stock_index_option` | 股指期权 |
| `otc_option` | 场外期权 |
| `total_return_swap` | 收益互换 |
| `current_deposit` | 活期存款 |
| `asset_unit` | 资产单元 |
| `other_asset` | 其他资产 |
| `cash_debt` | 现金类负债 |
