# API Index for options-mod.md

## Summary

- Source File: options-mod.md
- Total APIs: 5

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `options.get_contracts` | 筛选期权合约<br/>获取符合标的、期权类型、到期月份、行权价和查询日期条件的期权合约列表。例如可筛选铜期权 2019 年 2 月到期、行权价 52000 的合约，也可查询 50ETF 期权在 2016-11-29 行权价 2.006 的合约。 | 80-119 |
| `options.get_greeks` | 获取期权风险指标<br/>获取期权风险指标数据，支持按合约和时间范围查询日频或分钟频指标。例如可获取隐含波动率、Delta、Gamma 等指标，也包括 Vega、Theta、Rho 等风险指标；分钟级别仅支持股指期货期权。 | 120-223 |
| `options.get_contract_property` | 获取 ETF 期权合约属性（时间序列）<br/>获取交易所 ETF 期权的每日合约属性数据，支持按时间范围查询合约属性变动。例如可获取合约乘数、期权行权价、合约简称等数据。 | 224-280 |
| `options.get_dominant_month` | 获取期权主力月份<br/>获取商品期权在一段时间内的主力月份列表，支持主力月份和次主力月份数据，目前仅支持商品期权。例如可查询 CU 期权在 2023-07-01 至 2023-07-26 期间的主力月份数据。 | 281-332 |
| `options.get_indicators` | 获取期权衍生指标<br/>获取期权衍生指标数据，支持按期权标的、到期月份和时间范围查询。例如可获取成交额 PCR、持仓量 PCR、成交量 PCR 等指标，也包括 delta 为 0.25 的认购合约隐含波动率、delta 为 -0.25 的认沽合约隐含波动率和 skew。 | 333-404 |

