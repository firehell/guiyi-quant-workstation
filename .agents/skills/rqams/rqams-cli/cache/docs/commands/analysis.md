# 分析 API

分析命令的分析对象可以是产品，也可以是产品组。单个分析对象统一使用 `product_like_id_or_name`；投资概览命令支持多个分析对象，使用 `product_like_ids_or_names`。

本页的返回说明均指 CLI 成功输出中的 `data` 字段；CLI 会处理服务端任务并返回最终业务数据。

## `get indicator`

获取产品或产品组在日期区间内的风险指标汇总。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `fields` | string[]/string | 否 | 指标字段 |

返回：`data` 为风险指标对象，包含 `daily_risk`、`weekly_risk`、`monthly_risk` 和 `last_unit_net_value`。表中的 `*_risk` 表示同一字段同时适用于 `daily_risk`、`weekly_risk` 和 `monthly_risk` 三个对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `daily_risk` | object | 日频风险指标 |
| `weekly_risk` | object | 周频风险指标 |
| `monthly_risk` | object | 月频风险指标 |
| `last_unit_net_value` | number/null | 最新单位净值 |
| `*_risk.total_returns` | number/null | 区间收益 |
| `*_risk.total_annual_returns` | number/null | 年化收益 |
| `*_risk.total_arithmetic_excess_return` | number/null | 算术超额收益 |
| `*_risk.total_geometric_excess_return` | number/null | 几何超额收益 |
| `*_risk.arithmetic_excess_annual_return` | number/null | 年化算术超额收益 |
| `*_risk.geometric_excess_annual_return` | number/null | 年化几何超额收益 |
| `*_risk.annual_simple_interest` | number/null | 年化单利 |
| `*_risk.annual_volatility` | number/null | 年化波动率 |
| `*_risk.excess_annual_volatility` | number/null | 年化超额波动率 |
| `*_risk.annual_tracking_error` | number/null | 年化跟踪误差 |
| `*_risk.annual_downside_risk` | number/null | 年化下行风险 |
| `*_risk.alpha` | number/null | Alpha |
| `*_risk.absolute_alpha` | number/null | 绝对 Alpha |
| `*_risk.beta` | number/null | Beta |
| `*_risk.sharpe` | number/null | 夏普比率 |
| `*_risk.absolute_sharpe` | number/null | 绝对夏普比率 |
| `*_risk.excess_sharpe` | number/null | 超额夏普比率 |
| `*_risk.information_ratio` | number/null | 信息比率 |
| `*_risk.max_drawdown` | number/null | 最大回撤 |
| `*_risk.geometric_excess_max_drawdown` | number/null | 几何超额最大回撤 |
| `*_risk.calmar_ratio` | number/null | Calmar 比率 |

示例：

```powershell
rqamsc get indicator --payload '{"product_like_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31"}'
```

## `get indicator-series`

获取指标日期序列。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `indicators` | string[]/string | 否 | 指标名列表；可用指标见下表 |

可用指标：

| 指标名 | 返回值类型 | 说明 | 适用对象 |
| --- | --- | --- | --- |
| `unit_net_value` | date map<number/null> | 单位净值 | 产品、产品组 |
| `adjusted_net_value` | date map<number/null> | 累计净值 | 产品、产品组 |
| `total_assets` | date map<number/null> | 总资产 | 产品、产品组 |
| `total_equity` | date map<number/null> | 净资产 | 产品、产品组 |
| `daily_pnl` | date map<number/null> | 当日盈亏 | 产品、产品组 |
| `equity_net_exposure` | date map<number/null> | 权益净敞口 | 产品、产品组 |
| `cash` | date map<number/null> | 现金 | 产品、产品组 |
| `buy_amount` | date map<number/null> | 买入金额 | 产品、产品组 |
| `sell_amount` | date map<number/null> | 卖出金额 | 产品、产品组 |
| `net_cash_in` | date map<number/null> | 净投入 | 产品、产品组 |
| `subscribe_units` | date map<number/null> | 申购份额；有申购数据时返回 | 产品、产品组 |
| `subscribe_amount` | date map<number/null> | 申购金额；有申购数据时返回 | 产品、产品组 |
| `redeem_units` | date map<number/null> | 赎回份额；有赎回数据时返回 | 产品、产品组 |
| `redeem_amount` | date map<number/null> | 赎回金额；有赎回数据时返回 | 产品、产品组 |
| `risk_exposure` | date map<number/null> | 风险总敞口 | 产品、产品组 |
| `net_risk_exposure` | date map<number/null> | 风险净敞口 | 产品、产品组 |
| `weekly_pnl` | array<object> | 周度收益，按年、月、周分层 | 产品、产品组 |
| `leverage_ratio` | date map<number/null> | 杠杆率 | 产品 |

返回：`data` 为指标序列对象，键为指标名。除 `weekly_pnl` 外，值为按日期索引的对象，例如 `data.total_equity["2026-01-01"]`；`weekly_pnl` 返回按年、月、周分层的数组。

示例：

```powershell
rqamsc get indicator-series --payload '{"product_like_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31","indicators":["total_equity","daily_pnl"]}'
```

## `get investment-overview-summary-indicator`

获取多个产品或产品组的投资概览指标汇总。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `benchmark_id` | string | 否 | 基准 ID |
| `params` | object | 否 | 额外查询参数 |

返回：`data[]` 为概览指标项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 产品或产品组 ID |
| `name` | string | 产品或产品组名称 |
| `start_date` | string/date | 产品或产品组起始日期 |
| `benchmark_name` | string/null | 基准名称 |
| `net_value` | number/null | 区间结束日净值 |
| `annual_twoside_turnover_rate` | number/null | 年化双边换手率 |
| `period_acc_returns` | number/null | 区间累计收益 |
| `daily` | object | 日频业绩指标和资产负债指标 |
| `weekly` | object | 周频业绩指标 |
| `monthly` | object | 月频业绩指标 |

`daily` 字段包含业绩指标和资产负债指标：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `daily.alpha` | number/null | Alpha |
| `daily.beta` | number/null | Beta |
| `daily.sharpe` | number/null | 夏普比率 |
| `daily.max_drawdown` | number/null | 最大回撤 |
| `daily.information_ratio` | number/null | 信息比率 |
| `daily.annual_volatility` | number/null | 年化波动率 |
| `daily.annual_tracking_error` | number/null | 年化跟踪误差 |
| `daily.geometric_excess_max_drawdown` | number/null | 几何超额最大回撤 |
| `daily.geometric_excess_annual_return` | number/null | 几何超额年化收益 |
| `daily.arithmetic_excess_annual_return` | number/null | 算术超额年化收益 |
| `daily.net_cash_in` | number/null | 净投入 |
| `daily.period_pnl` | number/null | 区间盈亏 |
| `daily.equity_net_exposure` | number/null | 权益净敞口 |
| `daily.period_buy_amount` | number/null | 区间买入金额 |
| `daily.period_sell_amount` | number/null | 区间卖出金额 |
| `daily.cash` | number/null | 现金余额 |
| `daily.total_equity` | number/null | 总权益 |
| `daily.cn_stock_market_value` | number/null | A 股市值 |
| `daily.hk_stock_market_value` | number/null | 港股市值 |
| `daily.max_drawdown_period` | string/null | 最大回撤时间段 |
| `daily.max_drawdown_recovery_days` | string/null | 最大回撤修复 |
| `daily.total_annual_returns` | string/null | 期间年化收益 |
| `daily.geometric_excess_max_drawdown_period` | string/null | 超额最大回撤时间段 |
| `daily.geometric_excess_max_drawdown_recovery_days` | string/null | 超额回撤修复 |

`weekly` 和 `monthly` 字段只包含业绩指标子集，不返回 `daily` 中的资产负债、区间交易和回撤时间段字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `alpha` | number/null | Alpha |
| `beta` | number/null | Beta |
| `sharpe` | number/null | 夏普比率 |
| `max_drawdown` | number/null | 最大回撤 |
| `information_ratio` | number/null | 信息比率 |
| `annual_volatility` | number/null | 年化波动率 |
| `annual_tracking_error` | number/null | 年化跟踪误差 |
| `geometric_excess_max_drawdown` | number/null | 几何超额最大回撤 |
| `geometric_excess_annual_return` | number/null | 几何超额年化收益 |
| `arithmetic_excess_annual_return` | number/null | 算术超额年化收益 |
| `total_annual_returns` | string/null | 期间年化收益 |

示例：
```powershell
rqamsc get investment-overview-summary-indicator --payload '{"product_like_ids_or_names":["demo"],"start_date":"2026-01-01","end_date":"2026-01-31"}'
```

## `get investment-overview-returns-series`

获取多个产品或产品组的收益序列，并可附加基准。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `benchmark_id` | string | 是 | 基准 ID |
| `params` | object | 否 | 额外请求体字段 |

返回：`data[]` 为收益序列项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 产品、产品组或基准 ID |
| `name` | string | 名称 |
| `type` | string | 返回项类型 |
| `daily[]` | array | 日频收益序列 |
| `weekly[]` | array | 周频收益序列 |
| `monthly[]` | array | 月频收益序列 |
| `daily[].date` | string/date | 日期 |
| `daily[].daily_returns` | number | 当期收益 |
| `daily[].cumulative_returns` | number | 累计收益 |
| `weekly[]`、`monthly[]` 单条记录 | object | 包含 `date`、`cumulative_returns` |

示例：

```powershell
rqamsc get investment-overview-returns-series --payload '{"product_like_ids_or_names":["demo"],"start_date":"2026-01-01","end_date":"2026-01-31","benchmark_id":"000300.XSHG"}'
```

## `get investment-overview-asset-capital-size`

获取多个产品或产品组的资产规模序列。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `params` | object | 否 | 额外请求体字段 |

返回：`data[]` 为资产规模序列项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string/date | 日期 |
| `asset_classes[]` | array | 资产类别规模列表 |
| `asset_classes[].asset_class_name` | string | 资产类别名称 |
| `asset_classes[].value` | number | 该资产类别总权益 |

## `get investment-overview-asset-allocation`

获取多个产品或产品组的资产配置结果。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `params` | object | 否 | 额外请求体字段 |

返回：`data` 为资产配置对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `<资产大类>` | object | 资产大类到子类权重的映射 |
| `<资产大类>.<资产子类>` | number | 子类市值占总权益比例 |

## `get investment-overview-excess-correlation`

获取多个产品或产品组相对基准的超额收益相关性。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `benchmark_id` | string | 是 | 基准 ID |
| `params` | object | 否 | 额外请求体字段 |

返回：`data` 为超额收益相关性矩阵。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `daily` | object | 日频相关性矩阵 |
| `weekly` | object | 周频相关性矩阵 |
| `monthly` | object | 月频相关性矩阵；长区间或有月频样本时返回 |
| `<频率>.<行名称>.<列名称>` | number | 两个产品或产品组的相关系数 |

## `get investment-overview-returns-correlation`

获取多个产品或产品组的收益相关性。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_ids_or_names` | string[] | 是 | 产品或产品组 ID/名称列表 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `params` | object | 否 | 额外请求体字段 |

返回：`data` 为收益相关性矩阵。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `daily` | object | 日频相关性矩阵 |
| `weekly` | object | 周频相关性矩阵 |
| `monthly` | object | 月频相关性矩阵；长区间或有月频样本时返回 |
| `<频率>.<行名称>.<列名称>` | number | 两个产品或产品组的相关系数 |

## `get performance-attribution`

获取绩效归因结果。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 是 | 起始日期 |
| `end_date` | string/date | 是 | 结束日期 |
| `benchmark_id` | string | 否 | 基准 ID |
| `template` | string | 否 | 归因模板；默认 `equity/brinson` |
| `industry_standard` | string | 否 | 行业分类；默认 `sws` |
| `drilldown` | boolean | 否 | 是否下钻 |

返回：`data` 为归因报告结果。CLI 输出的是报告中的 `result`，`template` 不同时 `result` 的业务字段不同。

## `get returns-decomposition`

获取收益分解结果。该命令会设置 `only_returns_decomposition:true`。

Payload：同 [`get performance-attribution`](#get-performance-attribution)。

返回：`data` 为收益分解结果，结构同 [`get performance-attribution`](#get-performance-attribution) 返回的报告 `result`。

## `get trading-analysis-list`

获取交易分析列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `params` | object | 否 | 额外查询参数 |

返回：`data[]` 为交易分析列表项。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string/date | 分析日期 |
| `asset_class` | string | 资产类型 |
| `asset_category` | string | 资产类别 |
| `order_book_id` | string | 合约 ID |
| `direction` | string | 持仓方向 |
| `symbol` | string | 合约名称 |
| `period_pnl` | number | 区间累计交易盈亏 |

## `get trading-analysis`

获取单标的交易分析。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `order_book_id` | string | 否 | 合约 ID |
| `asset_class` | string | 否 | 资产类型 |
| `direction` | string | 否 | 持仓方向 |
| `params` | object | 否 | 额外查询参数 |

返回：`data` 为单标的交易分析对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `prev_adjusted_price_series[]` | array | 前复权价格序列 |
| `prev_adjusted_price_series[].date` | string/date | 日期 |
| `prev_adjusted_price_series[].price` | number | 前复权价格 |
| `position_quantity_series[]` | array | 持仓数量序列 |
| `position_quantity_series[].date` | string/date | 日期 |
| `position_quantity_series[].quantity` | number | 持仓数量 |
| `pnl_series[]` | array | 盈亏序列 |
| `pnl_series[].date` | string/date | 日期 |
| `pnl_series[].pnl` | number | 区间累计盈亏 |
| `buy_points[]` | string/date[] | 买入日期列表 |
| `sell_points[]` | string/date[] | 卖出日期列表 |
