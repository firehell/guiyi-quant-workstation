# API Index for alternative-data.md

## Summary

- Source File: alternative-data.md
- Total APIs: 12

## API Definitions (Sorted by Line Number)

| API Name | Description | Line Range |
|----------|-------------|------------|
| `consensus.get_comp_indicators` | 获取个股一致预期数据<br/>获取个股一致预期数据，支持按时间范围和研报范围查询。例如可获取一致预期营业收入、净利润、每股收益等财务数据，也包括一致预期目标价、评级系数以及未来 12 个月口径的数据。 | 20-178 |
| `consensus.get_indicator` | 获取个股盈利预测综合指标<br/>获取个股盈利预测综合指标数据，支持按查询年份或时间区间查询。例如可获取预测净利润、预测营业收入、预测净资产等指标，也包括报告标题、作者和摘要等研报信息。<br/>::: tip 注意事项<br/>传入 start_date、end_date 的时候，fiscal_year 可以传入 None，返回日期区间内的指定股票所有查询年份的明细数据<br/>::: | 179-326 |
| `consensus.get_price` | 获取个股预测股价数据<br/>获取个股预测股价数据，支持按时间范围和复权方式查询。例如可获取预测价格、评级系数等数据，也支持 `none`、`pre`、`post` 三种复权方式。 | 327-396 |
| `consensus.get_industry_rating` | 获取行业投资评级数据<br/>获取行业投资评级数据，支持按行业和时间范围查询。例如可获取评级系数、评级时段、行业代码等数据，也包括研究机构信息。 | 397-477 |
| `consensus.get_market_estimate` | 获取机构预测大势数据<br/>获取机构预测大势数据，支持按指数代码和查询年份查询。例如支持 000001.XSHG、399006.XSHE、000300.XSHG 等指数，也包含预测高点、预测地点、预测值和研究机构等数据。 | 478-536 |
| `consensus.get_security_change` | 获取个股调整明细数据<br/>获取机构报告统计周期内的个股调整明细数据，支持按时间范围和统计周期查询。例如统计周期可选 WEEK1、MON1、MON3，也支持 MON6 和 YEAR1。 | 537-604 |
| `consensus.get_expect_appr_exceed` | 获取个股超预期鉴定数据<br/>获取个股超预期鉴定数据，支持按报告年份、报告期、报告类型和鉴定结果查询。例如报告期可选 q1、q2、q4，报告类型可选财务定期报告、业绩预告、业绩快报，鉴定结果可选 exceed 和 below。 | 605-659 |
| `consensus.get_expect_prob` | 获取个股可能超预期数据<br/>获取个股可能超预期数据，支持按时间范围查询超预期或低于预期数据。例如 `expect_prob` 可选 `exceed` 和 `below`。 | 660-793 |
| `consensus.get_factor` | 获取个股因子库数据<br/>获取个股一致预期因子库数据。例如可获取一致预期情绪因子、一致预期基础财务因子、一致预期成长因子，也包括一致预期估值因子数据。 | 794-831 |
| `consensus.get_analyst_momentum` | 获取一致预期分析师动能数据<br/>获取个股一致预期分析师动能数据，支持按预测年份、时间范围、预测时段和研报范围查询。例如预测时段可选 q1、q2、q4，研报范围可选 1 和 3。 | 832-981 |
| `news.get_stock_news` | 获取个股新闻情绪指标<br/>获取个股新闻情绪指标数据，支持按股票和时间区间查询。例如可获取新闻标题、新闻舆情指标、公司舆情指标等数据。<br/>::: tip 注意事项<br/>请先单独安装 rqdatac_news，导入后使用<br/>::: | 982-1056 |
| `esg.get_rating` | 获取个股 ESG 评价数据<br/>获取个股 ESG 评价数据，支持按时间范围、横向层级和纵向类别查询。例如 level 可选 0、1、2，type 可选 E、S、G，也包括 ESG 综合评价、环境、社会责任和治理相关评价数据。<br/>::: tip 注意事项<br/>请先单独安装 rqdatac_esg，导入后使用<br/>::: | 1057-1144 |

