# 头寸 API

头寸表示产品或产品组在某个日期或实时截面的组合状态，包含份额、净值、资产、盈亏、风险敞口和持仓明细等信息。

产品和产品组统一使用 `product_like_id_or_name` 定位。该字段可以传产品 ID、产品名称、产品组 ID 或产品组名称，CLI 会解析后请求对应的产品或产品组接口。

## `get balance`

获取产品或产品组的单日头寸。CLI 会以平铺持仓方式请求服务端；有持仓时 `positions[]` 为持仓明细数组。

如果只需要少量摘要字段，可以传 `fields`。CLI 会把 `fields` 透传给服务端，并在返回时只保留这些顶层字段；当 `fields` 不包含 `positions` 时，服务端不会返回完整持仓明细。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `date` | string/date | 否 | 头寸日期；不传或传未来日期时，服务端返回实时头寸 |
| `fields` | string[]/string | 否 | 返回的顶层字段列表，例如 `total_equity`、`unit_net_value`、`daily_pnl` |

返回：`data` 为头寸对象，字段见[单日/实时头寸字段](#单日实时头寸字段)和[持仓字段](#持仓字段)。

示例：

```powershell
rqamsc get balance --payload '{"product_like_id_or_name":"demo","date":"2026-01-31"}'
rqamsc get balance --payload '{"product_like_id_or_name":"demo","date":"2026-01-31","fields":["total_equity","unit_net_value","daily_pnl"]}'
```

## `get balance-series`

获取产品或产品组的头寸序列。服务端默认返回头寸序列的核心顶层字段和默认持仓字段；CLI 的 `fields` 会映射为服务端 `position_fields`，用于追加或筛选持仓字段。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `fields` | string[]/string | 否 | 持仓字段列表，例如 `avg_price`、`fair_value`、`acc_pnl` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data` 或 `data.items[]` 为头寸序列记录。支持 `format:"ndjson"`。

示例：

```powershell
rqamsc get balance-series --payload '{"product_like_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31","fields":["avg_price","fair_value"],"format":"ndjson"}'
```

## `get asset-snapshot`

获取产品或产品组的实时头寸摘要。CLI 默认平铺持仓；如果需要分类树结构，可传 `flatten_positions:false` 并指定 `classifier`。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `fields` | string[]/string | 否 | 额外顶层字段，例如 `risk_exposure`、`net_risk_exposure`、`excess_returns` |
| `flatten_positions` | boolean | 否 | 是否平铺持仓；默认 `true` |
| `classifier` | string | 否 | 非平铺时的分类方式，例如 `asset_class`、`trading_asset_class` |

返回：`data` 为实时头寸对象，字段见[单日/实时头寸字段](#单日实时头寸字段)和[持仓字段](#持仓字段)。

示例：

```powershell
rqamsc get asset-snapshot --payload '{"product_like_id_or_name":"demo","fields":["risk_exposure","net_risk_exposure","excess_returns"]}'
```

## `recompute balance`

提交产品或产品组头寸重算任务。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 否 | 从该日期开始重算；不传时由服务端按产品或产品组起始日处理 |

返回：`data` 为重算提交结果。

示例：

```powershell
rqamsc recompute balance --payload '{"product_like_ids_or_names":["demo"],"start_date":"2026-01-01"}'
```

## 单日/实时头寸字段

以下字段来自 `rqams-server2` 的 `Balance` 结构和头寸服务返回逻辑。实际返回会受接口、日期、产品类型、实时/历史头寸、`fields` 和服务端可计算状态影响。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | string | 产品 ID；产品组头寸可能不返回 |
| `date` | string/date | 头寸日期 |
| `name` | string | 产品或产品组名称 |
| `market_value` | number | 持仓市值，不含应收应付 |
| `total_assets` | number | 总资产 |
| `total_liabilities` | number | 总负债 |
| `total_equity` | number | 净资产 |
| `daily_pnl` | number | 当日盈亏 |
| `daily_returns` | number/null | 当日盈亏率 |
| `units` | number/null | 份额 |
| `unit_net_value` | number/null | 单位净值 |
| `acc_unit_net_value` | number/null | 累计净值 |
| `adjusted_net_value` | number/null | 复权净值 |
| `acc_unit_dividend` | number/null | 累计单位份额分红 |
| `year_init_unit_net_value` | number/null | 年初单位净值 |
| `year_init_acc_net_value` | number/null | 年初累计净值 |
| `year_init_adjusted_net_value` | number/null | 年初复权净值 |
| `returns_this_year` | number/null | 今年以来收益率 |
| `pnl_this_year` | number/null | 今年以来盈亏 |
| `returns_from_establish` | number/null | 成立以来收益率 |
| `daily_pnl_on_close` | number/null | 按昨日收盘价计算的当日盈亏 |
| `daily_returns_on_close` | number/null | 按昨日收盘价计算的当日盈亏率 |
| `daily_equity_long_returns` | number/null | 权益类多头当日收益 |
| `daily_equity_short_returns` | number/null | 权益类空头当日收益 |
| `net_cash_in` | number | 当日净投入 |
| `equity_net_exposure` | number | 权益类净敞口 |
| `cn_stock_market_value` | number | A 股持仓市值 |
| `cn_sh_stock_market_value` | number | 沪市持仓市值 |
| `cn_sz_stock_market_value` | number | 深市持仓市值 |
| `hk_stock_market_value` | number | 港股持仓市值 |
| `cash` | number | 现金 |
| `total_risk_market_value` | number | 风险资产总市值 |
| `net_risk_market_value` | number | 风险资产净市值 |
| `risk_exposure` | number/null | 风险总敞口，服务端按需计算 |
| `net_risk_exposure` | number/null | 风险净敞口，服务端按需计算 |
| `long_market_value` | number | 风险资产多头市值 |
| `short_market_value` | number | 风险资产空头市值 |
| `long_leverage` | number/null | 多头杠杆倍数 |
| `long_net_risk_exposure` | number/null | 多头净暴露 |
| `capital_efficiency` | number/null | 资金使用率，主要用于期货保证金场景 |
| `benchmark_returns` | number/null | 基准收益率，请求 `excess_returns` 时可能返回 |
| `excess_returns` | number/null | 超额收益率，请求 `excess_returns` 时可能返回 |
| `buy_amount` | number | 买入金额 |
| `sell_amount` | number | 卖出金额 |
| `stock_buy_amount` | number | 股票买入金额 |
| `stock_sell_amount` | number | 股票卖出金额 |
| `bond_buy_amount` | number | 债券买入金额 |
| `bond_sell_amount` | number | 债券卖出金额 |
| `fund_buy_amount` | number | 基金买入金额 |
| `fund_sell_amount` | number | 基金卖出金额 |
| `all_futures_options_has_settlement` | boolean/null | 期货/期权是否都有结算价 |
| `update_time` | string/datetime | 头寸更新时间，实时头寸中常见 |
| `positions[]` | array/object | 持仓明细；平铺且有持仓时为数组，空持仓可返回 `{}`，非平铺时为分类树 |

## 持仓字段

以下字段来自服务端 `Position` 结构和持仓格式化逻辑。不同资产类别、历史/实时头寸、平铺/分类树返回的字段会有差异。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `positions[].order_book_id` | string | 合约 ID |
| `positions[].symbol` | string | 合约名称 |
| `positions[].asset_class` | string | 资产类型 |
| `positions[].direction` | string | 持仓方向，常见为 `long`、`short` |
| `positions[].quantity` | number | 持仓数量 |
| `positions[].cost` | number | 持仓成本，含税费 |
| `positions[].avg_price` | number | 平均开仓价格 |
| `positions[].avg_price_include_fee` | number | 含费平均开仓价格 |
| `positions[].last_avg_price_include_fee` | number | 昨日含费平均开仓价格 |
| `positions[].last_quantity` | number/null | 昨日持仓数量 |
| `positions[].fair_value` | number/null | 公允价格 |
| `positions[].fair_value_setl_ccy` | number/null | 结算币种公允价格 |
| `positions[].clean_price` | number/null | 净价 |
| `positions[].market_value` | number | 市值 |
| `positions[].market_value_setl_ccy` | number/null | 结算币种市值 |
| `positions[].clean_price_market_value` | number/null | 净价市值 |
| `positions[].weight` | number/null | 持仓权重 |
| `positions[].acc_pnl` | number | 累计盈亏 |
| `positions[].last_acc_pnl` | number | 昨日累计盈亏 |
| `positions[].acc_pnl_rate` | number | 累计盈亏率 |
| `positions[].daily_pnl` | number | 当日盈亏 |
| `positions[].daily_pnl_rate` | number | 当日盈亏率 |
| `positions[].contribute_returns` | number/null | 收益率贡献 |
| `positions[].floating_pnl` | number | 浮动盈亏 |
| `positions[].floating_pnl_percentage` | number | 浮动盈亏率 |
| `positions[].accrued_interest` | number | 应计利息 |
| `positions[].exchange_rate` | number | 汇率 |
| `positions[].currency` | string | 币种 |
| `positions[].bonus_share_receivable` | number | 应收红股 |
| `positions[].open_date` | string/date | 建仓日期 |
| `positions[].trade_date_latest` | string/date | 最后交易日期 |
| `positions[].acc_dividend_received` | number/null | 累计股息收入 |
| `positions[].acc_interest_received` | number/null | 累计利息收入 |
| `positions[].open_avg_price` | number | 买入时平均价格，含费用 |
| `positions[].avg_price_mtm` | number | 逐日盯市平均价格 |
| `positions[].daily_payment_amount` | number | 当日自动权益收益金额 |
| `positions[].daily_open_amount` | number | 当日开仓金额 |
| `positions[].price_limit` | string/null | 涨跌停状态，如 `limit_up`、`limit_down` |
| `positions[].price_change` | number/null | 价格涨跌，实时头寸常见 |
| `positions[].price_change_percentage` | number/null | 价格涨跌幅，实时头寸常见 |
| `positions[].price_change_baseline` | number/null | 计算涨跌的基准价 |
| `positions[].has_settlement` | boolean | 是否已更新结算价 |
| `positions[].update_time` | string/datetime | 价格更新时间，实时头寸常见 |
| `positions[].asset_unit_id` | string | 资产单元 ID，穿透资产单元时可能返回 |
| `positions[].industry` | string/null | 行业名称，服务端格式化时可能补充 |
| `positions[].children[]` | array | 子持仓，非平铺或资产单元穿透时可能返回 |
