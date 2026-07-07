# API Index for macro-economy.md

## Summary

- Source File: macro-economy.md
- Total APIs: 10

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `econ.get_reserve_ratio` | 获取存款准备金率<br/>获取存款准备金率数据，支持按信息公布日期范围查询不同类别机构的存款准备金率。例如可获取大型金融机构（major）和其他金融机构（other）的存款准备金率数据。 | 1-44 |
| `econ.get_money_supply` | 获取货币供应量<br/>获取货币供应量数据，支持按信息公布日期范围查询市场现金流通量、狭义货币和广义货币数据。例如可获取 M0、M1、M2 及其同比数据。 | 45-90 |
| `econ.get_factors` | 获取宏观因子数据<br/>获取宏观因子数据，支持按因子名称和时间范围查询指定宏观指标。例如可获取工业品出厂价格指数 PPI 当月同比等宏观因子数据。 | 91-136 |
| `econ.get_fixing_repo_rate` | 获取回购定盘利率<br/>获取一段时间内的回购定盘利率，数据为2004年至今，fileds可选FR001,FR007,FR014,FDR001,FDR007,FDR014 | 137-176 |
| `econ.get_us_treasury_yield` | 获取美国国债利率<br/>获取美国市场国债利率 | 177-222 |
| `econ.get_index` | 获取宏观指数数据<br/>获取宏观指数数据，支持按指数名称和时间范围查询指定宏观指数行情。<br/>支持的指数列表如下 | 223-293 |
| `econ.get_oil_price` | 获取中国汽柴油历史调价信息<br/>获取中国汽柴油历史调价信息 | 294-328 |
| `econ.get_gold_reserves` | 获取黄金储备数据<br/>获取中国黄金储备数据 | 329-365 |
| `econ.get_interbank_pledged_repo_rate` | 获取银行间质押式回购加权利率<br/>获取银行间质押式回购加权利率，例如 `DR001`、`DR007` 等。 | 366-410 |
| `econ.get_cny_reference_rate` | 获取人民币参考汇率<br/>获取人民币参考汇率中间价数据 | 411-472 |

