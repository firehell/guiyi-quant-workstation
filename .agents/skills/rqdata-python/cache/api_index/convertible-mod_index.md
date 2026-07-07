# API Index for convertible-mod.md

## Summary

- Source File: convertible-mod.md
- Total APIs: 16

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `convertible.all_instruments` | 获取所有可转债合约<br/>获取所有可转债合约的基础信息，传入日期时可筛选该日上市状态的合约列表。例如可获取债券全称、上市日、到期日等基础信息，也包括转股起始日、转股截止日和对应股票代码等数据。 | 7-70 |
| `convertible.instruments` | 获取可转债合约基础信息<br/>获取指定可转债合约的基础信息。例如可获取债券全称、上市日、到期日、转股起始日等数据，也支持获取不同付息期的票息率以及赎回、回售条款数据。 | 71-238 |
| `convertible.get_conversion_price` | 获取可转债转股价信息<br/>获取可转债合约在一段时期内的转股价变动数据，信息来源为交易所的可转债转股统计公告。例如可查询 110013.XSHG 在 2011-01-21 和 2011-07-04 公告对应的转股价变动数据。 | 239-279 |
| `convertible.get_conversion_info` | 获取可转债转股导致的规模变动情况<br/>获取可转债合约在一段时期内因转股导致的规模变动数据。例如可获取累计转股金额、累计转股数、剩余未转股金额等数据，也包括本期转股金额、本期转股股数和本次转股价。 | 280-328 |
| `convertible.get_call_info` | 获取可转债强赎信息<br/>获取可转债合约在一段时期内的强制赎回信息，支持按转债代码和时间范围查询。 | 329-374 |
| `convertible.get_put_info` | 获取可转债回售信息<br/>获取可转债合约在一段时期内的持有人回售信息，支持按转债代码和时间范围查询。 | 375-422 |
| `convertible.get_cash_flow` | 获取可转债的现金流<br/>获取可转债合约的现金流数据，支持按时间范围查询兑付日对应的数据。 | 423-471 |
| `convertible.is_suspended` | 判断可转债是否全天停牌<br/>获取可转债在一段时间内是否全天停牌的数据，支持单只或多只可转债查询。 | 472-519 |
| `convertible.get_instrument_industry` | 获取转债所属行业分类信息<br/>获取指定日期可转债所属的行业分类数据，转债行业分类即为对应正股上市公司行业分类。例如分类标准可选 `citics`、`citics_2019`、`gildata`，也支持一级、二级、三级分类数据。 | 520-573 |
| `convertible.get_industry` | 获取指定行业分类下的转债列表<br/>获取指定行业分类下的可转债列表，支持通过行业名称、行业指数代码或行业代号查询。例如分类标准可选 `citics`、`citics_2019`、`gildata`，也可按指定日期筛选仍处于上市状态的转债列表。 | 574-613 |
| `convertible.get_accrued_interest_eod` | 获取可转债日终应计利息<br/>获取可转债日终应计利息数据，应计利息从转债起息日起算，支持按时间范围查询。 | 614-658 |
| `convertible.get_call_announcement` | 获取可转债赎回提示性公告数据<br/>获取可转债赎回提示性公告数据，包含赎回和不赎回信息，支持按时间范围查询。 | 659-703 |
| `convertible.get_close_price` | 获取可转债全价净价数据<br/>获取可转债收盘价的全价和净价数据，支持按时间范围查询。例如可获取 clean_price 和 dirty_price 数据。 | 704-746 |
| `convertible.get_indicators` | 获取可转债衍生指标<br/>获取可转债衍生指标数据，支持按时间范围查询多类指标。例如可获取转股系数、转股价值、转股溢价率等转股相关指标，也包括到期收益率、回售收益率以及隐含波动率、delta、gamma、vega 等指标。 | 747-818 |
| `convertible.get_credit_rating` | 获取可转债债项评级数据<br/>获取可转债债项评级数据，支持按时间范围和评级机构筛选。例如评级机构可选联合信用评级有限公司、联合资信评估股份有限公司、中诚信国际信用评级有限责任公司等。 | 819-893 |
| `convertible.get_std_discount` | 获取可转债标准劵折算率<br/>获取可转债标准券折算率数据，支持按转债代码和时间范围查询。 | 894-932 |

