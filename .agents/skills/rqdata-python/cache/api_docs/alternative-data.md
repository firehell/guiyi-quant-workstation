# 另类数据

## 一致预期数据 {#rqdata-API-jrtz-overview}

可获取期一致预期数据，包含个股一致预期和盈利预测数据等。

::: tip 注意事项
现 API 的命名格式存在一些变化，如下：

| 旧 API 命名（待废弃）                | 现 API 命名                       |
|-----|-----|
| get_consensus_comp_indicators | consensus.get_comp_indicators  |
| get_consensus_indicator       | consensus.get_indicator        |
| get_consensus_price           | consensus.get_price            |
| get_consensus_industry_rating | consensus.get_industry_rating  |
| get_consensus_market_estimate | consensus.get_market_estimate  |

:::

### consensus.get_comp_indicators - 获取个股一致预期数据 {#rqdata-API-get_consensus_comp_indicators}

```python
consensus.get_comp_indicators(order_book_ids, start_date=None, end_date=None, fields=None, report_range=0, market='cn')
```

获取个股一致预期数据，支持按时间范围和研报范围查询。例如可获取一致预期营业收入、净利润、每股收益等财务数据，也包括一致预期目标价、评级系数以及未来 12 个月口径的数据。

#### 参数 {#rqdata-API-get_consensus_comp_indicators-params}

| 参数           | 类型                   | 说明                                                                                                                                                                                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ or _str list_    | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                                                                                                       |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 传入日期，默认为当天                                                                                                                                                                                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 传入日期，默认为当天                                                                                                                                                                                                                         |
| fields         | _str or str list_      | 字段名称，默认返回全部字段                                                                                                                                                                                                                   |
| report_range   | _int_                  | 研报范围<br/>0-不考虑补录入&包括所有报告数据（历史值修复会存在数值变动，需要不变的话传入 3）<br/>1-考虑补录入&包括所有报告数据<br/>2-考虑补录入&仅包括公司报告数据<br/>3-不考虑补录入&包括所有报告数据<br/>4-不考虑补录入&仅包括公司报告数据 |
| market         | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_consensus_comp_indicators-return}

_pandas DataFrame_

| 返回           | 类型            | 说明                                                                                                                                                                                                                                         |
|-----|-----|-----|
| order_book_ids | _str_           | 合约代码                                                                                                                                                                                                                                     |
| date           | _pandas.Timestamp_ | 发布日期,每个交易日都会有数据                                                                                                                                                                                                                |
| report_year_t  | _str_           | 最近年报的年度                                                                                                                                                                                                                               |
| rice_create_tm | _pandas.Timestamp_      | 米筐入库时间                                                                                                                                                                                                                                 |
| create_tm      | _pandas.Timestamp_      | 数据商入库时间                                                                                                                                                                                                                               |
| fields         | *list*          | 字段中的 t 代表最近一期年报<br/>report_range=0 字段详情见下方表 1<br/>report_range=1、2、3、4 字段详情见下方表 1.1                                                                                                                           |
| report_range   | _int_           | 研报范围<br/>0-不考虑补录入&包括所有报告数据（历史值修复会存在数值变动，需要不变的话传入 3）<br/>1-考虑补录入&包括所有报告数据<br/>2-考虑补录入&仅包括公司报告数据<br/>3-不考虑补录入&包括所有报告数据<br/>4-不考虑补录入&仅包括公司报告数据 |

##### 表 1. 个股一致预期字段说明 {#rqdata-API-jrtz-fields-1}

| 字段名                                      | 字段说明                                     |
|-----|-----|
| comp_operating_revenue_t                    | 营业收入（T 年）                             |
| comp_con_operating_revenue_t1               | 一致预期营业收入（T+1 年）                   |
| comp_con_operating_revenue_t2               | 一致预期营业收入（T+2 年）                   |
| comp_con_operating_revenue_t3               | 一致预期营业收入（T+3 年）                   |
| comp_con_operating_revenue_ftm              | 一致预期营业收入（未来 12 个月）             |
| comp_net_profit_t                           | 净利润（T 年）                               |
| comp_con_net_profit_t1                      | 一致预期净利润（T+1 年）                     |
| comp_con_net_profit_t2                      | 一致预期净利润（T+2 年）                     |
| comp_con_net_profit_t3                      | 一致预期净利润（T+3 年）                     |
| comp_con_net_profit_ftm                     | 一致预期净利润（未来 12 个月）               |
| comp_eps_t                                  | 每股收益（T 年）                             |
| comp_con_eps_t1                             | 一致预期每股收益（T+1 年）                   |
| comp_con_eps_t2                             | 一致预期每股收益（T+2 年）                   |
| comp_con_eps_t3                             | 一致预期每股收益（T+3 年）                   |
| comp_con_eps_ftm                            | 一致预期每股收益（未来 12 个月）             |
| comp_net_asset_t                            | 净资产（T 年）                               |
| comp_con_net_asset_t1                       | 一致预期净资产（T+1 年）                     |
| comp_con_net_asset_t2                       | 一致预期净资产（T+2 年）                     |
| comp_con_net_asset_t3                       | 一致预期净资产（T+3 年）                     |
| comp_con_net_asset_ftm                      | 一致预期净资产（未来 12 个月）               |
| comp_cash_flow_t                            | 经营性活动现金净流量（T 年）                 |
| comp_con_cash_flow_t1                       | 一致预期经营性活动现金净流量（T+1 年）       |
| comp_con_cash_flow_t2                       | 一致预期经营性活动现金净流量（T+2 年）       |
| comp_con_cash_flow_t3                       | 一致预期经营性活动现金净流量（T+3 年）       |
| comp_con_cash_flow_ftm                      | 一致预期经营性活动现金净流量（未来 12 个月） |
| comp_roe_t                                  | 净资产收益率（T 年）                         |
| comp_con_roe_t1                             | 一致预期净资产收益率（T+1 年）               |
| comp_con_roe_t2                             | 一致预期净资产收益率（T+2 年）               |
| comp_con_roe_t3                             | 一致预期净资产收益率（T+3 年）               |
| comp_con_roe_ftm                            | 一致预期净资产收益率（未来 12 个月）         |
| comp_pe_t                                   | 市盈率（T 年）                               |
| comp_con_pe_t1                              | 一致预期市盈率（T+1 年）                     |
| comp_con_pe_t2                              | 一致预期市盈率（T+2 年）                     |
| comp_con_pe_t3                              | 一致预期市盈率（T+3 年）                     |
| comp_con_pe_ftm                             | 一致预期市盈率（未来 12 个月）               |
| comp_ps_t                                   | 市销率（T 年）                               |
| comp_con_ps_t1                              | 一致预期市销率（T+1 年）                     |
| comp_con_ps_t2                              | 一致预期市销率（T+2 年）                     |
| comp_con_ps_t3                              | 一致预期市销率（T+3 年）                     |
| comp_con_ps_ftm                             | 一致预期市销率（未来 12 个月）               |
| comp_pb_t                                   | 市净率（T 年）                               |
| comp_con_pb_t1                              | 一致预期市净率（T+1 年）                     |
| comp_con_pb_t2                              | 一致预期市净率（T+2 年）                     |
| comp_con_pb_t3                              | 一致预期市净率（T+3 年）                     |
| comp_con_pb_ftm                             | 一致预期市净率（未来 12 个月）               |
| comp_peg                                    | 一致预期 PEG                                 |
| comp_operating_revenue_growth_ratio_t       | 营业收入同比增长率（T 年）                   |
| comp_con_operating_revenue_growth_ratio_t1  | 一致预期营业收入同比增长率（T+1 年）         |
| comp_con_operating_revenue_growth_ratio_t2  | 一致预期营业收入同比增长率（T+2 年）         |
| comp_con_operating_revenue_growth_ratio_t3  | 一致预期营业收入同比增长率（T+3 年）         |
| comp_con_operating_revenue_growth_ratio_ftm | 一致预期营业收入同比增长率（未来 12 个月）   |
| comp_net_profit_growth_ratio_t              | 净利润同比增长率（T 年）                     |
| comp_con_net_profit_growth_ratio_t1         | 一致预期净利润同比增长率（T+1 年）           |
| comp_con_net_profit_growth_ratio_t2         | 一致预期净利润同比增长率（T+2 年）           |
| comp_con_net_profit_growth_ratio_t3         | 一致预期净利润同比增长率（T+3 年）           |
| comp_con_net_profit_growth_ratio_ftm        | 一致预期净利润同比增长率（未来 12 个月）     |
| con_grd_coef                                | 一致预期评级系数(6 个月)                     |
| con_targ_price                              | 一致预期目标价(6 个月)                       |
| ty_profit_t1                                | 天眼预期净利润（T+1 年）                     |
| ty_profit_t2                                | 天眼预期净利润（T+2 年）                     |
| ty_profit_t3                                | 天眼预期净利润（T+3 年）                     |
| ty_profit_ftm                               | 天眼预期净利润（未来 12 个月）               |
| ty_eps_t1                                   | 天眼预期每股收益（T+1 年）                   |
| ty_eps_t2                                   | 天眼预期每股收益（T+2 年）                   |
| ty_eps_t3                                   | 天眼预期每股收益（T+3 年）                   |
| ty_eps_ftm                                  | 天眼预期每股收益（未来 12 个月）             |

##### 表 1.1 个股一致预期字段说明 {#rqdata-API-jrtz-fields-1-1}

| 字段名                        | 字段说明                                                    |
|-----|-----|
| comp_con_operating_revenue_t1 | 一致预期营业收入（T+1 年）                                  |
| comp_con_operating_revenue_t2 | 一致预期营业收入（T+2 年）                                  |
| comp_con_operating_revenue_t3 | 一致预期营业收入（T+3 年）                                  |
| comp_con_net_profit_t1        | 一致预期净利润（T+1 年）                                    |
| comp_con_net_profit_t2        | 一致预期净利润（T+2 年）                                    |
| comp_con_net_profit_t3        | 一致预期净利润（T+3 年）                                    |
| comp_con_eps_t1               | 一致预期每股收益（T+1 年）                                  |
| comp_con_eps_t2               | 一致预期每股收益（T+2 年）                                  |
| comp_con_eps_t3               | 一致预期每股收益（T+3 年）                                  |
| comp_con_eps_ftm              | 一致预期每股收益（未来 12 个月）                            |
| comp_con_cash_flow_t1         | 一致预期经营性活动现金净流量（T+1 年）                      |
| comp_con_cash_flow_t2         | 一致预期经营性活动现金净流量（T+2 年）                      |
| comp_con_cash_flow_t3         | 一致预期经营性活动现金净流量（T+3 年）                      |
| con_targ_price                | 一致预期目标价(6 个月)<br/>仅在 report_range=0、1、3 时返回 |

#### 范例 {#rqdata-API-get_consensus_comp_indicators-example}

- 获取一个股票在 2021-03-01~2021-04-01 的数据

```python
[In]
rqdatac.consensus.get_comp_indicators('600000.XSHG','2021-03-01','2021-04-01',fields=['comp_con_eps_t1','comp_con_eps_ftm','ty_eps_t2'])
[Out]
                          report_year_t comp_con_eps_t1 comp_con_eps_ftm ty_eps_t2
order_book_id date
600000.XSHG   2021-03-01           2019          1.9871           2.1152    2.0649
              2021-03-02           2019          1.9871           2.1152    2.0648
              2021-03-03           2019          1.9871           2.1152    2.0648
              2021-03-04           2019          1.9871           2.1152    2.0648
              2021-03-05           2019          1.9871           2.1152    2.0648
              2021-03-08           2019          1.9871           2.1152    2.0648
              2021-03-09           2019          1.9871           2.1152    2.0647
              2021-03-10           2019          1.9871           2.1152    2.0647
              2021-03-11           2019          1.9871           2.1152    2.0647
              2021-03-12           2019          1.9871           2.1152    2.0647
              2021-03-15           2019          1.9871           2.1152    2.0634
              2021-03-16           2019          1.9871           2.1152    2.0634
              2021-03-17           2019          1.9871           2.1152    2.0633
              2021-03-18           2019          1.9871           2.1152    2.0623
              2021-03-19           2019          1.9871           2.1143    2.0632
              2021-03-22           2019          1.9871           2.1229    2.0655
              2021-03-23           2019          1.9871           2.1229    2.0654
              2021-03-24           2019          1.9871           2.1229    2.0793
              2021-03-25           2019          1.9871           2.1229    2.0794
              2021-03-26           2019          1.9871           2.1229    2.0793
              2021-03-29           2020          2.1021           2.1598    2.3390
              2021-03-30           2020          2.1107           2.1660    2.3380
              2021-03-31           2020          2.1095           2.1660    2.3430
              2021-04-01           2020          2.1114           2.1882    2.3430
```

### consensus.get_indicator - 获取个股盈利预测综合指标 {#rqdata-API-consensus-get_indicator}

```python
rqdatac.consensus.get_indicator(order_book_ids, fiscal_year, fields=None, start_date=None, end_date=None, date_rule=None, market='cn')
```

获取个股盈利预测综合指标数据，支持按查询年份或时间区间查询。例如可获取预测净利润、预测营业收入、预测净资产等指标，也包括报告标题、作者和摘要等研报信息。

::: tip 注意事项

传入 start_date、end_date 的时候，fiscal_year 可以传入 None，返回日期区间内的指定股票所有查询年份的明细数据

:::

#### 参数 {#rqdata-API-consensus-get_indicator-params}

| 参数           | 类型                   | 说明                                                                                                                                                                                                                                                                                                      |
|-----|-----|-----|
| order_book_ids | _str or  str list_     | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                                                                                                                                                                          |
| fiscal_year    | _str_                  | **必填参数**，查询年份                                                                                                                                                                                                                                                                                    |
| fields         | _str or str list_      | 字段名称，默认返回全部字段                                                                                                                                                                                                                                                                                |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 传入日期，默认为 None，不生效；有值传入返回 date 在这区间的数据                                                                                                                                                                                                                                           |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 传入日期，默认为 None，不生效；有值传入返回 date 在这区间的数据                                                                                                                                                                                                                                           |
| date_rule      | _str_                  | 日期截取规则，和 start_date\end_date 一起使用，默认为 None 不生效<br/>传入'RPT_DT'，根据研报发布日期 date 截取返回的数据<br/>传入‘create_tm',根据今日投资入库时间截取返回的数据<br/>传入‘rice_create_tm',根据米筐入库时间截取返回的数据<br/>备注：在 2022-06-09 之前 rice_create_tm 是用 create_tm 填充的 |
| market         | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-consensus-get_indicator-return}

_pandas DataFrame_

| 返回           | 类型                                                           | 说明                                                  |
|-----|-----|-----|
| order_book_ids | *list*                                                         | 合约代码                                              |
| date           | _pandas.Timestamp_                                              | 发布日期                                              |
| institute      | _str_                                                          | 研究机构名称（注 1）                                  |
| fiscal_year    | _str_                                                          | 查询年份                                              |
| rice_create_tm | _pandas.Timestamp_                                              | 米筐入库时间                                          |
| create_tm      | _pandas.Timestamp_                                              | 数据商入库时间（研报入库时间）                        |
| fields         | _list_                                                         | 字段中的 t 代表研报基准年份+1 <br/>字段详情见下方表 2 |

#### 表 2. 个股盈利预测综合指标说明 {#rqdata-API-jrtz-get_indicator-fields-2}

| 字段名                            | 字段说明                                       |
|-----|-----|
| report_title                      | 报告标题                                       |
| data_source                       | 数据来源<br/>0-公司报告数据<br/>1-行业报告数据 |
| author                            | 作者姓名                                       |
| summary                           | 摘要                                           |
| net_profit_t                      | 预测净利润(T 年)                               |
| net_profit_t1                     | 预测净利润(T+1 年)                             |
| net_profit_t2                     | 预测净利润(T+2 年)                             |
| revenue_t                         | 预测营业收入(T 年)                             |
| revenue_t1                        | 预测营业收入(T+1 年)                           |
| revenue_t2                        | 预测营业收入(T+2 年)                           |
| net_asset_t                       | 预测净资产(T 年)                               |
| net_asset_t1                      | 预测净资产(T+1 年)                             |
| net_asset_t2                      | 预测净资产(T+2 年)                             |
| cash_from_operating_activities_t  | 预测经营性活动现金净流量(T 年)                 |
| cash_from_operating_activities_t1 | 预测经营性活动现金净流量(T+1 年)               |
| cash_from_operating_activities_t2 | 预测经营性活动现金净流量(T+2 年)               |
| profit_from_operation_t           | 预测营业利润(T 年)                             |
| profit_from_operation_t1          | 预测营业利润(T+1 年)                           |
| profit_from_operation_t2          | 预测营业利润(T+2 年)                           |
| cost_of_goods_sold_t              | 预测营业成本(T 年)                             |
| cost_of_goods_sold_t1             | 预测营业成本(T+1 年)                           |
| cost_of_goods_sold_t2             | 预测营业成本(T+2 年)                           |
| profit_before_tax_t               | 预测税前利润(T 年)                             |
| profit_before_tax_t1              | 预测税前利润(T+1 年)                           |
| profit_before_tax_t2              | 预测税前利润(T+2 年)                           |
| ebit_t                            | 预测息税前利润(EBIT)(T 年)                     |
| ebit_t1                           | 预测息税前利润(EBIT)(T+1 年)                   |
| ebit_t2                           | 预测息税前利润(EBIT)(T+2 年)                   |
| operating_revenue_per_share_t     | 预测每股营业收入(T 年)                         |
| operating_revenue_per_share_t1    | 预测每股营业收入(T+1 年)                       |
| operating_revenue_per_share_t2    | 预测每股营业收入(T+2 年)                       |
| eps_t                             | 预测每股收益(T 年)                             |
| eps_t1                            | 预测每股收益(T+1 年)                           |
| eps_t2                            | 预测每股收益(T+2 年)                           |
| bps_t                             | 预测每股净资产(T 年)                           |
| bps_t1                            | 预测每股净资产(T+1 年)                         |
| bps_t2                            | 预测每股净资产(T+2 年)                         |
| share_cap_chg_date                | 摊薄股本变动日                                 |
| report_main_id                    | 报告主要股票代码或行业代码                     |
| grade_coef                        | 评级系数                                       |
| targ_price                        | 目标价位                                       |
| ebitda_t                          | 预测税息折旧及摊销前利润(EBITDA)(T 年)         |
| ebitda_t1                         | 预测税息折旧及摊销前利润(EBITDA)(T+1 年)       |
| ebitda_t2                         | 预测税息折旧及摊销前利润(EBITDA)(T+2 年)       |
| profit_res_t                      | 预测净利润（备考）(T 年)                       |
| profit_res_t1                     | 预测净利润（备考）(T+1 年)                     |
| profit_res_t2                     | 预测净利润（备考）(T+2 年)                     |
| operate_cash_flow_per_share_t     | 预测每股经营性活动现金净流量(T 年)             |
| operate_cash_flow_per_share_t1    | 预测每股经营性活动现金净流量(T+1 年)           |
| operate_cash_flow_per_share_t2    | 预测每股经营性活动现金净流量(T+2 年)           |
| profit_chg_t                      | 盈利预测变动(T 年)                             |
| profit_chg_t1                     | 盈利预测变动(T+1 年)                           |
| profit_chg_t2                     | 盈利预测变动(T+2 年)                           |
| grade_chg_t                       | 投资评级变动(T 年)                             |
| grade_chg_t1                      | 投资评级变动(T+1 年)                           |
| grade_chg_t2                      | 投资评级变动(T+2 年)                           |
| targ_price_chg_t                  | 目标价变动(T 年)                               |
| targ_price_chg_t1                 | 目标价变动(T+1 年)                             |
| targ_price_chg_t2                 | 目标价变动(T+2 年)                             |
| chg_reason_t                      | 变动原因(T 年)                                 |
| chg_reason_t1                     | 变动原因(T+1 年)                               |
| chg_reason_t2                     | 变动原因(T+2 年)                               |

#### 范例 {#rqdata-API-consensus-get_indicator-example}

- 获取一个股票公告日在 2023-01-01~2023-11-03 数据

```python
[In]
rqdatac.consensus.get_indicator('000001.XSHE',start_date='20230101',end_date='20231103',fiscal_year=None,date_rule='rpt_dt')

[out]
                         institute  fiscal_year                          report_title          author  data_source  ... chg_reason_t chg_reason_t1  chg_reason_t2         create_time                                            summary
order_book_id date                                                                                                  ...
000001.XSHE   2023-01-01      招商证券         2022          银行业2023年信贷与社融展望：2023年社融如何展望？             廖志明          1.0  ...         None          None           None 2023-01-03 11:19:54  　　本篇报告提出国内信贷需求分析三部分框架-基建、地产以及市场化需求（含制造业），正好与投资...
              2023-01-02      广发证券         2022              银行投资观察：不要在中期趋势中做反方向的短期交易     倪军,屈俊,王先爽 等          1.0  ...         None          None           None 2023-01-03 16:17:01  　　上周银行复盘：上周银行由前两周的调整转为上涨，银行指数（中信一级）上涨2.2%，跑赢万得...
              2023-01-02      华泰证券         2022         金融行业周报（第五十二周）：双创板优化发审 金融修复启新篇      沈娟,李健,王可 等          1.0  ...         None          None           None 2023-01-02 13:14:45  　　本周观点：双创板优化发审，金融修复启新篇。看好金融股配置机遇，保险>银行>券商。展望20...
              2023-01-03      广发证券         2022           银行行业2022年12月社融前瞻：预计社融增速9.7%          倪军,王先爽          1.0  ...         None          None           None 2023-01-04 18:20:13  　　预计2022年12月社融增速9.7%，增速环比回落0.3pct。预计12月社融当月增量约...
              2023-01-03      中信证券         2022                     银行业投资观察：托管新规影响几何？          肖斐斐,彭博          1.0  ...         None          None           None 2023-01-03 15:25:22  　　托管新规出台后，预计一方面会进一步完善托管业务监管标准，另一方面将对商业银行资质、能力管...
...                            ...          ...                                   ...             ...          ...  ...          ...           ...            ...                 ...                                                ...
              2023-10-31      广发证券         2023  银行业2023Q3公募基金持仓分析：公募配置继续回升 复苏板块是配置主线  鍊啗,鐜嬪厛鐖?鏉庝匠楦?          1.0  ...         None          None           None 2023-11-01 16:16:56  　　核心观点：Wind数据显示公募基金2023年3季度报告披露完毕，我们分析如下：Q3公募基...
              2023-11-01      财信证券         2023                  银行业月度点评：三季报落地 估值修复可期          刘敏,洪欣佼          1.0  ...         None          None           None 2023-11-06 15:20:42  　　10月，申万银行录得涨跌幅-3.90%，跑输上证指数0.95pct.，跑输沪深300指数...
              2023-11-01      国泰君安         2023             商业银行业：资本新规如期而至 较征求意见稿略有放松           张宇,刘源          1.0  ...         None          None           None 2023-11-02 09:32:57  　　国家金融监督管理总局发布《商业银行资本管理办法》，较此前征求意见稿略有放松，预计新规实施...
              2023-11-02      中泰证券         2023         银行业解读与测算：资本新规终稿落地 银行资本压力进一步缓解         戴志锋,邓美君          1.0  ...         None          None           None 2023-11-03 15:20:48  　　核心观点：1、终稿与征求意见稿主要区别：优化校准部分权重、调低信用证转换系数、明确资管产...
              2023-11-02      广发证券         2023       银行行业《商业银行资本管理办法》正式稿点评：较征求意见稿更友好          倪军,王先爽          1.0  ...         None          None           None 2023-11-03 17:47:25  　　11月1日，金融监管总局发布《商业银行资本管理办法》正式稿（简称《办法》）。资本是银行经...

[440 rows x 67 columns]
```

- 获取一个股票在 2023-11-10~2023-11-12 今日投资入库的数据

```python
[In]
rqdatac.consensus.get_indicator('000063.XSHE',start_date='20231110',end_date='20231112',fiscal_year=None,date_rule='create_tm')

[out]
                         institute  fiscal_year                         report_title       author  data_source      rice_create_tm           create_tm  net_profit_t  ...  targ_price_chg_t  targ_price_chg_t1  targ_price_chg_t2  chg_reason_t  chg_reason_t1  chg_reason_t2         create_time                                            summary
order_book_id date                                                                                                                                                    ...
000063.XSHE   2023-11-10      东莞证券         2023  通信行业2023年三季报业绩综述：前三季度业绩增速放缓 净利率水平上行  陈伟光,罗炜斌,陈湛谦          1.0 2023-11-10 22:10:42 2023-11-10 17:30:14  9.853498e+09  ...               NaN                NaN                NaN          None           None           None 2023-11-10 16:53:33  　　整体业绩持续增长，同比增速有所放缓。通信板块2023年前三季度实现营业收入19,195....

[1 rows x 67 columns]

```

### consensus.get_price - 获取个股预测股价数据 {#rqdata-API-get_consensus_price}

```python
rqdatac.consensus.get_price(order_book_ids, start_date=None, end_date=None, fields=None, adjust_type='none', market='cn')
```

获取个股预测股价数据，支持按时间范围和复权方式查询。例如可获取预测价格、评级系数等数据，也支持 `none`、`pre`、`post` 三种复权方式。

#### 参数 {#rqdata-API-get_consensus_price-params}

| 参数           | 类型                                                             | 说明                                                                     |
|-----|-----|-----|
| order_book_ids | _str or  str list_                                               | **必填参数**，合约代码，可传入 order_book_id, order_book_id list         |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 开始日期 （start_date,end_date 不传时，返回最近三个月的数据）            |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 结束日期                                                                 |
| fields         | _str or str list_                                                | 字段名称，默认返回全部字段                                               |
| adjust_type    | _str_                                                            | 复权方式，默认为'none' ,不复权 - 'none'，前复权 - 'pre'，后复权 - 'post' |
| market         | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_consensus_price-return}

_pandas DataFrame_

| 返回           | 类型                                                           | 说明                                                                               |
|-----|-----|-----|
| order_book_ids | *list*                                                         | 合约代码                                                                           |
| date           | _pandas.Timestamp_                                     | 发布日期                                                                           |
| institute      | _str_                                                          | 研究机构名称                                                                       |
| rice_create_tm | _pandas.Timestamp_                                               | 米筐入库时间                                                                       |
| create_tm      | _pandas.Timestamp_                                              | 数据商入库时间                                                                     |
| fields         | _str_                                                          | 字段中的 t 代表研报发布日期那个时间 <br/>部分需要返回的价格字段,字段详情见下方表 3 |

##### 表 3. 个股一致预期股价预测字段说明 {#rqdata-API-jrtz-fields-3}

| 字段名                   | 字段说明                                                                  |
|-----|-----|
| half_year_target_price   | 预测价格(T+0.5 年)                                                        |
| one_year_target_price    | 预测价格(T+1 年)                                                          |
| quarter_recommendation   | 评级系数(T+0.25 年)                                                       |
| half_year_recommendation | 评级系数（T+0.5 年）                                                      |
| one_year_recommendation  | 评级系数 （ T+1 年）                                                      |
| price_raw                | 目标价位（原始值）                                                        |
| price_prd                | 价位时段 M06 6 个月,Y01 1 年                                              |
| grd_coef                 | 评级系数 强力买入 1.00、 买入 2.00 、 观望 3.00、适度减持 4.00、卖出 5.00 |
| grd_prd                  | 评级时段 1 短期(3 个月)；2 中期(6 个月)；3 长期(12 个月)                  |

#### 范例 {#rqdata-API-get_consensus_price-example}

- 获取一个股票在 2022-01-01~2022-02-01 的股价预测数据预测净利润(T+1 年)数据

```python
[In]
rqdatac.consensus.get_price(order_book_ids='000001.XSHE',start_date='20220101',end_date='20220201')
[Out]
                                institute half_year_target_price one_year_target_price quarter_recommendation half_year_recommendation one_year_recommendation
order_book_id date
000001.XSHE 2022-01-02 东北证券     NaN              NaN              1.0                     NaN                         NaN
                2022-01-03 浙商证券     33.03            NaN                 1.0                     NaN                         NaN
                2022-01-03 华泰证券     NaN              NaN                 1.0                     NaN                      NaN
                2022-01-04 华安证券     NaN              NaN                 1.0                  NaN                      NaN
                2022-01-04 广发证券     NaN                 NaN                 1.0                 NaN                         NaN
                ... ... ... ... ... ... ...
                2022-01-24 国泰君安     NaN              NaN              1.0                  NaN                         NaN
                2022-01-25 中泰证券     NaN              NaN              2.0              NaN                         NaN
                2022-01-25 中金公司     NaN              NaN                     2.0                 NaN                         NaN
                2022-01-28 广发证券     NaN              NaN                     1.0                 NaN                         NaN
                2022-01-30 中泰证券     NaN                 NaN              2.0                 NaN                         NaN
65 rows × 6 columns
```

### consensus.get_industry_rating - 获取行业投资评级数据 {#rqdata-API-get_consensus_industry_rating}

```python
rqdatac.consensus.get_industry_rating(industries, start_date, end_date, market='cn')
```

获取行业投资评级数据，支持按行业和时间范围查询。例如可获取评级系数、评级时段、行业代码等数据，也包括研究机构信息。

#### 参数 {#rqdata-API-get_consensus_industry_rating-params}

| 参数       | 类型            | 说明                                                                                         |
|-----|-----|-----|
| industries | _str or list_   | **必填参数**，行业 code 是今日投资行业分类代码，all_consensus_industries()获取支持传入的代码 |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，起始日期                                                                       |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，结束日期                                                                       |
| market     | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_consensus_industry_rating-return}

_pandas DataFrame_

| 返回           | 类型              | 说明                                                                   |
|-----|-----|-----|
| grade_coef     | _int_             | 评级系数<br/>1 强力买入<br/>2 增持<br/>3 观望<br/>4 减持<br/>5 卖出    |
| grade_period   | _str_             | 评级时段<br/>1 短期(3 个月)；<br/>2 中期(6 个月)；<br/>3 长期(12 个月) |
| industry_name  | _str_             | 行业代码                                                               |
| institute      | _str_             | 研究机构                                                               |
| info_date      | _pandas.Timestamp_ | 报告日期                                                               |
| rice_create_tm | _pandas.Timestamp_ | 米筐入库时间                                                           |
| create_tm      | _pandas.Timestamp_ | 数据商入库时间                                                         |

#### 范例 {#rqdata-API-get_consensus_industry_rating-example}

- 获取酒店、度假村与豪华游轮行业一致预期数据

```python
[In]
rqdatac.consensus.get_industry_rating(industries='25301020',start_date='2022-01-01',end_date='2022-03-01')
[Out]
          industry_code grade_coef grade_period institute
industry_name         info_date
酒店、度假村与豪华游轮 2022-02-18 25301020 2 1 信达证券
                        2022-02-25 25301020 1 1 东莞证券
                        2022-02-16 25301020 2 1 国泰君安
                        2022-01-20 25301020 2 1 信达证券
                        2022-01-23 25301020 2 1 财通证券
                        2022-02-14 25301020 2 1 民生证券
                        2022-01-04 25301020 2 1 东兴证券
                        2022-01-04 25301020 2 1 民生证券
                        2022-01-30 25301020 2 1 国泰君安
                        2022-01-16 25301020 2 1 财通证券
                        2022-01-24 25301020 2 1 民生证券
                        2022-01-29 25301020 2 1 财通证券
                        2022-02-27 25301020 3 1 西南证券
                        2022-02-27 25301020 1 1 国金证券
                        2022-01-07 25301020 4 1 国泰君安
                        2022-02-12 25301020 1 1 国金证券
```

- 查询今日投资行业分类数据

```python
[In]
rqdatac.all_consensus_industries()
[Out]
                industry_name
industry_code
35202010 制药
45203010 电子设备和仪器
25401030 电影与娱乐
20102010 建筑产品
55101010 电力公用事业
... ...
6010         房地产
551020       燃气公用事业
40       金融
20201060        办公服务与用品
2520         耐用消费品与服装
161 rows × 1 columns
```

### consensus.get_market_estimate - 获取机构预测大势数据 {#rqdata-API-get_consensus_market_estimate}

```python
rqdatac.consensus.get_market_estimate(indexes, fiscal_year, market='cn')
```

获取机构预测大势数据，支持按指数代码和查询年份查询。例如支持 000001.XSHG、399006.XSHE、000300.XSHG 等指数，也包含预测高点、预测地点、预测值和研究机构等数据。

#### 参数 {#rqdata-API-get_consensus_market_estimate-params}

| 参数        | 类型                | 说明                                                                                                                                                                                            |
|-----|-----|-----|
| indexes     | _str_ or _str list_ | **必填参数**，预测指数代码，默认返回全部，主要数据量都是 000001.XSHG，支持传入下列指数<br>000001.XSHG<br>399006.XSHE<br>000016.XSHG<br>399005.XHSE<br>399300.XSHE<br>000905.XSHG<br>000300.XSHG |
| fiscal_year | _str_ or _str list_ | **必填参数**，查询年份，必填，目前仅支持 2017、2018、2019、2020、2021、2022                                                                                                                     |
| market         | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_consensus_market_estimate-return}

_pandas DataFrame_

| 返回           | 类型              | 说明                                                                   |
|-----|-----|-----|
| indexes        | _str_             | 预测指数合约代码 |
| info_date      | _pandas.Timestamp_ | 报告日期         |
| rice_create_tm | _pandas.Timestamp_ | 米筐入库时间     |
| create_tm      | _pandas.Timestamp_ | 数据商入库时间   |
| fiscal_year    | _str_             | 预测年份         |
| institute      | _str_             | 研究机构         |
| start_date     | _pandas.Timestamp_ | 预测开始时间     |
| end_date       | _pandas.Timestamp_ | 预测结束时间     |
| high           | _numpy.float64_   | 预测高点         |
| low            | _numpy.float64_   | 预测低点         |
| period         | _str_             | 预测时段         |
| value          | _str_             | 预测值           |

#### 范例 {#rqdata-API-get_consensus_market_estimate-example}

- 获取各机构关于 000001.XSHG 在 2021 的预测数据

```python
[In]
rqdatac.consensus.get_market_estimate(indexes='000001.XSHG', fiscal_year='2021')
[Out]
                         fiscal_year institute start_date end_date high low period         value
order_book_id info_date
000001.XSHG 2020-10-13 2021         财信证券         2021-01-01 2021-12-31 NaN NaN 策略年度报告 中性
                2020-10-16 2021         华融证券         2021-01-01 2021-12-31 NaN NaN 策略年度报告 中性
                2020-10-23 2021         东北证券         2021-01-01 2021-12-31 NaN NaN 策略年度报告 中性
                2020-11-01 2021         方正证券         2021-01-01 2021-12-31 NaN NaN 策略年度报告 中性
                2020-11-02 2021         西南证券         2021-01-01 2021-12-31 NaN NaN 策略年度报告 中性
                ...  ...      ... ... ... ... ... ... ...
                2021-12-31 2021         山西证券         2022-01-01 2022-01-31 NaN NaN 策略月度报告 中性
                2021-12-31 2021         方正证券         2021-12-31 2021-12-31 NaN NaN 策略日报等 中性
                2021-12-31 2021         东亚前海证券     2022-01-01 2022-01-31 NaN NaN 策略月度报告 中性
                2021-12-31 2021         粤开证券         2022-01-01 2022-01-31 NaN NaN 策略月度报告 乐观
                2021-12-31 2021         渤海证券         2022-01-01 2022-01-31 NaN NaN 策略月度报告 中性
5893 rows × 8 columns
```

### consensus.get_security_change - 获取个股调整明细数据 {#rqdata-API-get_security_change}

```python
rqdatac.consensus.get_security_change(order_book_ids,start_date=None,end_date=None,stat_periods=None)
```

获取机构报告统计周期内的个股调整明细数据，支持按时间范围和统计周期查询。例如统计周期可选 WEEK1、MON1、MON3，也支持 MON6 和 YEAR1。

#### 参数 {#rqdata-API-get_security_change-params}

| 参数           | 类型                | 说明                                                                                                                       |
|-----|-----|-----|
| order_book_ids | _str or str list_   | **必填参数**，合约代码，必填，可传入 order_book_id, order_book_id list                                                     |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_     | 起始日期                                                                                                                   |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_     | 结束日期                                                                                                                   |
| stat_periods   | _str_ or _str list_ | 统计周期，不传入默认返回全部，支持传入<br/>WEEK1，一周(上周) <br/>MON1，一月<br/>MON3，三月<br/>MON6，六月<br/>YEAR1，一年 |

#### 返回 {#rqdata-API-get_security_change-return}

_pandas DataFrame_

| 返回                  | 类型  | 说明                                                                                                                             |
|-----|-----|-----|
| stat_period           | _str_ | 统计周期，WEEK1，一周(上周) <br/>MON1，一月<br/>MON3，三月<br/>MON6，六月<br/>YEAR1，一年                                        |
| institute             | _str_ | 研究机构                                                                                                                         |
| adjust_classification | _int_ | 调整类别<br/>1 盈利预测调高; <br/>2 盈利预测调低;<br/>3 投资评级调高;<br/>4 投资评级调低;<br/>5 盈利预测维持;<br/>6 投资评级维持 |

#### 范例 {#rqdata-API-get_security_change-example}

- 获取近 3 个月 000001.XSHG 机构报告统计周期内个股调整明细

```python
[In]
rqdatac.consensus.get_security_change('000001.XSHE',start_date=None,end_date=None,stat_periods=None)
[Out]
                         stat_period institute  adjust_classification
order_book_id date
000001.XSHE   2023-04-14        Mon1      长城证券                      5
              2023-04-14        Mon1      长城证券                      6
              2023-04-14        Mon3      长城证券                      2
              2023-04-14        Mon3      长城证券                      6
              2023-04-14        Mon6      长城证券                      2
...                              ...       ...                    ...
              2023-07-07       Year1    华泰金融控股                      6
              2023-07-07        Mon3      海通国际                      6
              2023-07-07        Mon6      海通国际                      6
              2023-07-07       Year1      海通国际                      1
              2023-07-07       Year1      海通国际                      6

[3019 rows x 3 columns]
```

- 获取近 2023-06-02 000001.XSHG 一周内机构报告调整明细

```python
[In]
rqdatac.consensus.get_security_change('000001.XSHE',start_date=20230602,end_date=20230602,stat_periods=['WEEK1'])
[Out]
                         stat_period institute  adjust_classification
order_book_id date
000001.XSHE   2023-06-02       Week1      长城证券                      5
              2023-06-02       Week1      长城证券                      6
              2023-06-02       Week1      中金公司                      6
              2023-06-02       Week1      广发证券                      5
              2023-06-02       Week1      广发证券                      6
              2023-06-02       Week1      海通国际                      6
```

### consensus.get_expect_appr_exceed - 获取个股超预期鉴定数据 {#rqdata-API-get_expect_appr_exceed}

```python
rqdatac.consensus.get_expect_appr_exceed(order_book_ids, start_date=None, end_date=None, report_year=None, report_periods=None, report_types=None, appraisal_results=None)
```

获取个股超预期鉴定数据，支持按报告年份、报告期、报告类型和鉴定结果查询。例如报告期可选 q1、q2、q4，报告类型可选财务定期报告、业绩预告、业绩快报，鉴定结果可选 exceed 和 below。

#### 参数 {#rqdata-API-get_expect_appr_exceed-params}

| 参数              | 类型              | 说明                                                                                                                         |
|-----|-----|-----|
| order_book_ids    | _str or str list_ | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                       |
| start_date        | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 起始日期                                                                                                                     |
| end_date          | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 结束日期                                                                                                                     |
| report_year       | _str_             | 默认返回全部，比如填入'2021'                                                                                                 |
| report_periods    | _str or str list_ | 默认返回全部 <br/>q1’：一季度<br/>'q2'：半年度<br/>'q3'：三季度<br/>'q4'：年度                                               |
| report_types      | _str or str list_ | 默认返回全部 <br/>'financial_reports'：财务定期报告<br/>'performance_forecast'：业绩预告<br/>'current_performance'：业绩快报 |
| appraisal_results | _str or str list_ | 默认返回全部 <br/>'exceed':超预期<br/>'below':低于预期                                                                       |

#### 返回 {#rqdata-API-get_expect_appr_exceed-return}

_pandas DataFrame_

| 返回                | 类型       | 说明                                                                                                       |
|-----|-----|-----|
| date                | _pandas.Timestamp_ | 发布日期                                                                                                   |
| report_period       | _str_             | 报告时段<br/>'q1'：一季度<br/>'q2'：半年度<br/>'q3'：三季度<br/>'q4'：年度                                  |
| report_type         | _str_             | 'financial_reports'：财务定期报告<br/>'performance_forecast'：业绩预告<br/>'current_performance'：业绩快报 |
| appraisal_result    | _str_             | 默认返回全部 <br/>'exceed':超预期<br/>'below':低于预期                                                     |
| info_date           | _pandas.Timestamp_ | 业绩报告公布日                                                                                             |
| forecast_profit_max | _float_           | 业绩预告净利润上限                                                                                         |
| forecast_profit_min | _float_           | 业绩预告净利润下限                                                                                         |
| forecast_profit     | _float_           | 业绩预告净利润                                                                                             |
| adjust_con_profit   | _float_           | 调整后一致预期净利润                                                                                       |
| appraisal_date      | _pandas.Timestamp_ | 鉴定日                                                                                                     |
| appraisal_standard  | _float_           | 鉴定标准 1 报表发布日鉴定 2 报表发布周期鉴定                                                               |
| con_cal_date        | _pandas.Timestamp_ | 一致预期计算日                                                                                             |
| con_profit          | _float_           | 一致预期净利润                                                                                             |
| profit_ex_rate      | _float_           | 业绩超预期幅度                                                                                             |

#### 范例 {#rqdata-API-get_expect_appr_exceed-example}

- 获取近 2023 年 4 月 000001.XSHG 的超预期鉴定数据

```python
[In]
rqdatac.consensus.get_expect_appr_exceed(['000001.XSHE'],start_date=20230401,end_date=20230430,report_year=None,report_periods=None,report_types=None,appraisal_results=None)
[Out]
                          report_year report_period        report_type appraisal_result  info_date forecast_profit_max forecast_profit_min forecast_profit adjust_con_profit appraisal_date  appraisal_standard con_calc_date        con_profit profit_ex_rate
order_book_id date
000001.XSHE   2023-04-25         2023            q1  financial_reports            below 2023-04-25                None                None            None  52466684210.5263     2023-04-25                   1    2023-04-24  53667978389.5961        -0.0224
              2023-04-25         2023            q1  financial_reports            below 2023-04-25                None                None            None  52466684210.5263     2023-04-25                   2    2023-03-31  53976575697.2556        -0.0280
```

### consensus.get_expect_prob - 获取个股可能超预期数据 {#rqdata-API-get_expect_prob}

```python
rqdatac.consensus.get_expect_prob(order_book_ids,expect_prob,start_date=None,end_date=None)
```

获取个股可能超预期数据，支持按时间范围查询超预期或低于预期数据。例如 `expect_prob` 可选 `exceed` 和 `below`。

#### 参数 {#rqdata-API-get_expect_prob-params}

| 参数           | 类型              | 说明                                                             |
|-----|-----|-----|
| order_book_ids | _str or str list_ | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| expect_prob    | _str_             | **必填参数**，可能性，<br/>'below' 低于预期<br/>'exceed' 超预期  |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 起始日期                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 结束日期                                                         |

#### 返回 {#rqdata-API-get_expect_prob-return}

_pandas DataFrame_

| 返回                           | 类型       | 说明                                                                                                                                                  |
|-----|-----|-----|
| date                           | _pandas.Timestamp_ | 发布日期                                                                                                                                              |
| report_year                    | _str_      | 报告年度                                                                                                                                              |
| report_period                  | _str_      | 报告时段<br/>'q1'：一季度<br/>'q2'：半年度<br/>'q3'：三季度<br/>'q4'：年度                                                                            |
| info_classification            | _int_      | 字段详情见下方表 4                                                                                                                                    |
| institute                      | _str_      | 研究机构简称                                                                                                                                          |
| info_summary                   | _str_      | 超预期信息简述                                                                                                                                        |
| report_date                    | _pandas.Timestamp_ | 本次研究报告撰写日                                                                                                                                    |
| title                          | _str_      | 本次研报标题                                                                                                                                          |
| author                         | _str_      | 本次研报作者                                                                                                                                          |
| est_profit                     | _float_    | 本次研报预测净利润                                                                                                                                    |
| report_date_last               | _pandas.Timestamp_ | 上次研究报告撰写日                                                                                                                                    |
| title_last                     | _str_      | 上次研报标题                                                                                                                                          |
| est_profit_last                | _float_    | 上次研报预测净利润                                                                                                                                    |
| info_date                      | _pandas.Timestamp_ | 本次业绩报告日                                                                                                                                        |
| report_type                    | _str_      | 本次业绩报告类型                                                                                                                                      |
| forecast_profit_max            | _float_    | 本次业绩预告上限净利润                                                                                                                                |
| forecast_profit_min            | _float_    | 本次业绩预告下限净利润                                                                                                                                |
| profit                         | _float_    | 本次业绩报告净利润                                                                                                                                    |
| profit_q                       | _float_    | 本次业绩报告净利润（单季度）                                                                                                                          |
| forecast_profit_growth_limit   | _float_    | 本次业绩预告净利润同比增速上下限                                                                                                                      |
| profit_growth                  | _float_    | 本次业绩报告净利润同比增速                                                                                                                            |
| forecast_profit_growth_limit_q | _float_    | 本次业绩预告净利润同比增速上下限（单季度）                                                                                                            |
| profit_growth_q                | _float_    | 本次业绩报告净利润同比增速（单季度）                                                                                                                  |
| fin_report_date_last           | _pandas.Timestamp_ | 上次业绩报告公告日                                                                                                                                    |
| fin_report_type_last           | _float_    | 上次业绩报告类型                                                                                                                                      |
| forecast_profit_max_last       | _float_    | 上次业绩预告上限净利润                                                                                                                                |
| forecast_profit_min_last       | _float_    | 上次业绩预告下限净利润                                                                                                                                |
| profit_last                    | _float_    | 上次业绩快报净利润                                                                                                                                    |
| con_calc_date                  | _pandas.Timestamp_ | 本次一致预期计算日                                                                                                                                    |
| con_profit                     | _float_    | 本次一致预期净利润                                                                                                                                    |
| con_calc_date_last             | _pandas.Timestamp_ | 上次一致预期计算日                                                                                                                                    |
| con_profit_last                | _float_    | 上次一致预期净利润                                                                                                                                    |
| con_profit_q_last              | _float_    | 上次一致预期净利润（单季度）                                                                                                                          |
| con_profit_growth_last         | _float_    | 上次一致预期净利润同比增速（年度）                                                                                                                    |
| con_profit_growth_q_last       | _float_    | 上次一致预期净利润同比增速（单季度）                                                                                                                  |
| expect_rate                    | _float_    | 业绩上下调幅度或低于预期幅度 <br/>超预期：业绩增速上调/超预期幅度为前后增速直接相减获得<br/>低于预期：业绩增速下调/低于预期幅度为前后增速直接相减获得 |

##### 表 4. 预期类别代码说明 {#rqdata-API-jrtz-fields-4}

<br/>

###### 超预期

| info_classification | 字段说明                                                      |
|-----|-----|
| 1101                | 分析师上调（剔除明星分析师）                                  |
| 1102                | 明星分析师上调                                                |
| 1103                | 业绩公告后分析师全部上调                                      |
| 1201                | 业绩公告后一致预期净利润大幅上调                              |
| 1301                | 研报标题超预期                                                |
| 1302                | 研报摘要超预期                                                |
| 1401                | 业绩预告/快报超上次预期                                       |
| 1403                | 业绩预告/快报超一致预期                                       |
| 1405                | 本期财报净利润超一致预期净利润（单季度）                      |
| 1501                | 本期财报净利润同比增速超年度一致预期净利润同比增速            |
| 1502                | 本次预告/快报净利润同比增速超年度一致预期净利润同比增速       |
| 1503                | 本期财报净利润同比增速超一致预期净利润同比增速（单季度）      |
| 1504                | 本次预告/快报净利润同比增速超一致预期净利润同比增速（单季度） |

###### 低于预期

| info_classification | 字段说明                                                        |
|-----|-----|
| 2101                | 分析师下调                                                      |
| 2102                | 明星分析师下调（名字待定）                                      |
| 2103                | 业绩公告后分析师全部下调                                        |
| 2201                | 研报标题低于预期                                                |
| 2302                | 研报摘要低于预期                                                |
| 2401                | 业绩预告/快报低于上次预期                                       |
| 2403                | 业绩预告/快报低于一致预期                                       |
| 2405                | 本期财报净利润低于一致预期净利润（单季度）                      |
| 2501                | 本期财报净利润同比增速低于年度一致预期净利润同比增速            |
| 2502                | 本次预告/快报净利润同比增速低于年度一致预期净利润同比增速       |
| 2503                | 本期财报净利润同比增速低于一致预期净利润同比增速（单季度）      |
| 2504                | 本次预告/快报净利润同比增速低于一致预期净利润同比增速（单季度） |

#### 范例 {#rqdata-API-get_expect_prob-example}

- 获取近 2023 年 4 月 000001.XSHG 的超预期鉴定数据

```python
[In]
rqdatac.consensus.get_expect_prob('000001.XSHE',expect_prob='below',start_date=None,end_date=None)
[Out]
                          report_year report_period  info_classification institute                                  info_summary report_date  ... con_calc_date_last   con_profit_last con_profit_q_last con_profit_gr_last con_profit_gr_q_last expect_rate
order_book_id date                                                                                                                            ...
000001.XSHE   2023-04-24         2023            q4                 2101      长城证券          长城证券2023-04-24发布的报告下调了该股盈利预测,分析师：邹恒超  2023-04-24  ...                NaT              None              None               None                 None     -0.0250
              2023-04-24         2023            q4                 2101      招商证券      招商证券2023-04-24发布的报告下调了该股盈利预测,分析师：廖志明,邵春雨  2023-04-24  ...                NaT              None              None               None                 None     -0.0712
              2023-04-24         2023            q4                 2101      华泰证券        华泰证券2023-04-24发布的报告下调了该股盈利预测,分析师：沈娟,安娜  2023-04-24  ...                NaT              None              None               None                 None     -0.0757
              2023-04-24         2023            q4                 2101      安信证券           安信证券2023-04-24发布的报告下调了该股盈利预测,分析师：李双  2023-04-24  ...                NaT              None              None               None                 None     -0.0106
              2023-04-24         2023            q4                 2102      中泰证券      中泰证券2023-04-24发布的报告下调了该股盈利预测,分析师：戴志锋,邓美君  2023-04-24  ...                NaT              None              None               None                 None     -0.0671
              2023-04-25         2023            q1                 2405      None            2023-04-25发布的财报中，1季度净利润增速低于机构的一致预期         NaT  ...         2023-04-24              None  15151435000.0000               None                 None     -0.0363
              2023-04-25         2023            q1                 2501      None          2023-04-25发布的财报净利润同比增速低于一致预期2023同比增速         NaT  ...         2023-04-24  53667978389.5961              None             0.1791                 None     -0.0428
              2023-04-25         2023            q1                 2503      None          2023-04-25发布的财报净利润同比增速低于2023一致预期同比增速         NaT  ...         2023-04-24              None  15151435000.0000               None               0.1791     -0.0428
              2023-04-25         2023            q4                 2101      国泰君安        国泰君安2023-04-25发布的报告下调了该股盈利预测,分析师：张宇,刘源  2023-04-25  ...                NaT              None              None               None                 None     -0.0181
              2023-04-25         2023            q4                 2101      申万宏源  申万宏源2023-04-25发布的报告下调了该股盈利预测,分析师：郑庆明,林颖颖,冯思远  2023-04-25  ...                NaT              None              None               None                 None     -0.0469
              2023-04-25         2023            q4                 2101      中信证券       中信证券2023-04-25发布的报告下调了该股盈利预测,分析师：肖斐斐,彭博  2023-04-25  ...                NaT              None              None               None                 None     -0.0200
              2023-04-25         2023            q4                 2101      兴业证券   兴业证券2023-04-25发布的报告下调了该股盈利预测,分析师：陈绍兴,王尘,曹欣童  2023-04-25  ...                NaT              None              None               None                 None     -0.0321
              2023-04-25         2023            q4                 2101      信达证券      信达证券2023-04-25发布的报告下调了该股盈利预测,分析师：王舫朝,廖紫苑  2023-04-25  ...                NaT              None              None               None                 None     -0.0289
              2023-04-25         2023            q4                 2101      东兴证券      东兴证券2023-04-25发布的报告下调了该股盈利预测,分析师：林瑾璐,田馨宇  2023-04-25  ...                NaT              None              None               None                 None     -0.1018
              2023-04-25         2023            q4                 2101      财通证券      财通证券2023-04-25发布的报告下调了该股盈利预测,分析师：夏昌盛,刘斐然  2023-04-25  ...                NaT              None              None               None                 None     -0.0182
              2023-04-25         2023            q4                 2101      天风证券          天风证券2023-04-25发布的报告下调了该股盈利预测,分析师：郭其伟  2023-04-25  ...                NaT              None              None               None                 None     -0.0642
              2023-04-25         2023            q4                 2102      广发证券    广发证券2023-04-25发布的报告下调了该股盈利预测,分析师：倪军,屈俊,王先爽  2023-04-25  ...                NaT              None              None               None                 None     -0.0515
              2023-04-25         2023            q4                 2102      中信建投       中信建投2023-04-25发布的报告下调了该股盈利预测,分析师：马鲲鹏,李晨  2023-04-25  ...                NaT              None              None               None                 None     -0.0454
              2023-04-25         2023            q4                 2102      浙商证券  浙商证券2023-04-25发布的报告下调了该股盈利预测,分析师：梁凤洁,邱冠华,陈建宇  2023-04-25  ...                NaT              None              None               None                 None     -0.0281
              2023-04-28         2023            q4                 2101      万联证券           万联证券2023-04-28发布的报告下调了该股盈利预测,分析师：郭懿  2023-04-28  ...                NaT              None              None               None                 None     -0.0357
              2023-04-28         2023            q4                 2101    华泰金融控股      华泰金融控股2023-04-28发布的报告下调了该股盈利预测,分析师：沈娟,安娜  2023-04-28  ...                NaT              None              None               None                 None     -0.0757

[21 rows x 35 columns]
```

### consensus.get_factor - 获取个股因子库数据 {#consensus-API-get_factor}

```python
rqdatac.consensus.get_factor(order_book_ids,factors,start_date=None,end_date=None)
```

获取个股一致预期因子库数据。例如可获取一致预期情绪因子、一致预期基础财务因子、一致预期成长因子，也包括一致预期估值因子数据。

#### 参数 {#consensus-API-get_factor-params}

| 参数           | 类型              | 说明                                                                                                                                                     |
|-----|-----|-----|
| order_book_ids | _str or str list_ | **必填参数**，合约代码，必填，可传入 order_book_id, order_book_id list                                                                                   |
| factors        | _str or str list_ | **必填参数**，因子字段，可选字段可点击<a href="https://assets.ricequant.com/vendor/rqdata/一致预期因子.xlsx" target="_blank">一致预期因子</a >下载，必填 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 起始日期                                                                                                                                                 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据                                                                                        |

#### 返回 {#consensus-API-get_factor-return}

_pandas DataFrame_

#### 范例 {#consensus-API-get_factor-example}

- 获取近 2023-07-01~2023-07-07 000001.XSHG 的一致预期净资产变化率（T+1 年）数据

```python
[In]
rqdatac.consensus.get_factor('000001.XSHE',factors='ASSET_T',start_date=20230701,end_date=20230707)
[Out]
                               ASSET_T
order_book_id date
000001.XSHE   2023-07-03  4.346800e+11
              2023-07-04  4.346800e+11
              2023-07-05  4.346800e+11
              2023-07-06  4.346800e+11
              2023-07-07  4.346800e+11
```

### consensus.get_analyst_momentum - 获取一致预期分析师动能数据 {#rqdata-API-get_analyst_momentum}

```python
rqdatac.consensus.get_analyst_momentum(order_book_ids,fiscal_year=None,start_date=None,end_date=None,fields=None,report_periods=None,report_range=None,market='cn')
```

获取个股一致预期分析师动能数据，支持按预测年份、时间范围、预测时段和研报范围查询。例如预测时段可选 q1、q2、q4，研报范围可选 1 和 3。

#### 参数 {#rqdata-API-get_analyst_momentum-params}

| 参数           | 类型                | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str or str list_   | **必填参数**，合约代码，必填，可传入 order_book_id, order_book_id list       |
| fiscal_year    | _str_               | 预测年份，默认返回全部                                                       |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_     | 起始日期                                                                     |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_     | 结束日期                                                                     |
| fields         | _str_ or _str list_ | 数据字段, 默认返回全部                                                       |
| report_periods | _str or str list_   | 预测时段，默认返回全部<br/>q1 一季度<br/>q2 半年度<br/>q3 三季度<br/>q4 年度 |
| report_range   | _int_               | 研报范围，默认返回全部 <br/>1 考虑补录入；<br/>3 不考虑补录入                |
| market         | _str_                  | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_analyst_momentum-return}

_pandas DataFrame_

| 参数                  | 类型       | 说明                                 |
|-----|-----|-----|
| order_book_id         | _str_      | 合约代码                             |
| date                  | _pandas.Timestamp_ | 发布日期                             |
| fiscal_year           | _str_      | 预测年份                             |
| report_period         | _str_      | 预测时段                             |
| report_range          | _str_      | 研报范围                             |
| profit_chg_1w         | _float_    | 净利润 1 周变化率                    |
| profit_chg_1w_rank    | _int_      | 净利润 1 周变化率排名                |
| profit_chg_1w_sco     | _float_    | 净利润 1 周变化率得分                |
| profit_chg_2w         | _float_    | 净利润 2 周变化率                    |
| profit_chg_2w_rank    | _int_      | 净利润 2 周变化率排名                |
| profit_chg_2w_sco     | _float_    | 净利润 2 周变化率得分                |
| profit_chg_1m         | _float_    | 净利润 1 月变化率                    |
| profit_chg_1m_rank    | _int_      | 净利润 1 月变化率排名                |
| profit_chg_1m_sco     | _float_    | 净利润 1 月变化率得分                |
| profit_chg_2m         | _float_    | 净利润 2 月变化率                    |
| profit_chg_2m_rank    | _int_      | 净利润 2 月变化率排名                |
| profit_chg_2m_sco     | _float_    | 净利润 2 月变化率得分                |
| profit_chg_3m         | _float_    | 净利润 3 月变化率                    |
| profit_chg_3m_rank    | _int_      | 净利润 3 月变化率排名                |
| profit_chg_3m_sco     | _float_    | 净利润 3 月变化率得分                |
| op_reven_chg_1w       | _float_    | 业务收入 1 周变化率                  |
| op_reven_chg_1w_rank  | _int_      | 业务收入 1 周变化率排名              |
| op_reven_chg_1w_sco   | _float_    | 业务收入 1 周变化率得分              |
| op_reven_chg_2w       | _float_    | 业务收入 2 周变化率                  |
| op_reven_chg_2w_rank  | _int_      | 业务收入 2 周变化率排名              |
| op_reven_chg_2w_sco   | _float_    | 业务收入 2 周变化率得分              |
| op_reven_chg_1m       | _float_    | 业务收入 1 月变化率                  |
| op_reven_chg_1m_rank  | _int_      | 业务收入 1 月变化率排名              |
| op_reven_chg_1m_sco   | _float_    | 业务收入 1 月变化率得分              |
| op_reven_chg_2m       | _float_    | 业务收入 2 月变化率                  |
| op_reven_chg_2m_rank  | _int_      | 业务收入 2 月变化率排名              |
| op_reven_chg_2m_sco   | _float_    | 业务收入 2 月变化率得分              |
| op_reven_chg_3m       | _float_    | 业务收入 3 月变化率                  |
| op_reven_chg_3m_rank  | _int_      | 业务收入 3 月变化率排名              |
| op_reven_chg_3m_sco   | _float_    | 业务收入 3 月变化率得分              |
| ty_est_dev            | _float_    | 天眼预期偏离度                       |
| ty_est_dev_rank       | _int_      | 天眼预期偏离度排名                   |
| ty_est_dev_sco        | _float_    | 天眼预期偏离度得分                   |
| est_em_bic_sco        | _float_    | 预期动能得分(考虑业务收入变化率)     |
| est_em_non_bic_sco    | _float_    | 预期动能得分(不考虑业务收入变化率)   |
| grd_em_1m             | _float_    | 评级动能 1 月                        |
| grd_em_1m_rank        | _int_      | 评级动能 1 月排名                    |
| grd_em_1m_sco         | _float_    | 评级动能 1 月得分                    |
| grd_em_2m             | _float_    | 评级动能 2 月                        |
| grd_em_2m_rank        | _int_      | 评级动能 2 月排名                    |
| grd_em_2m_sco         | _float_    | 评级动能 2 月得分                    |
| grd_em_3m             | _float_    | 评级动能 3 月                        |
| grd_em_3m_rank        | _int_      | 评级动能 3 月排名                    |
| grd_em_3m_sco         | _float_    | 评级动能 3 月得分                    |
| targ_price_space      | _float_    | 目标价涨升空间                       |
| targ_price_space_rank | _int_      | 目标价涨升空间排名                   |
| targ_price_space_sco  | _float_    | 目标价涨升空间得分                   |
| grd_em_sco            | _float_    | 评级动能得分                         |
| ana_em_bic_sco        | _float_    | 分析师动能得分(考虑业务收入变化率)   |
| ana_em_non_bic_sco    | _float_    | 分析师动能得分(不考虑业务收入变化率) |

#### 范例 {#rqdata-API-get_analyst_momentum-example}

- 获取 2024-03-01~2024-03-26 000001.XSHE 的考虑补录入的一致预期分析师动能数据

```python
[In]
rqdatac.consensus.get_analyst_momentum('000001.XSHE',start_date=20240301,end_date=20240326,report_range=1)
[Out]
                          fiscal_year report_period  report_range  profit_chg_1w  ...  targ_price_space_sco  grd_em_sco  ana_em_bic_sco  ana_em_non_bic_sco
order_book_id date                                                                ...
000001.XSHE   2024-03-01         2023            q4             1        -0.0170  ...               79.5529     44.3326             NaN             64.0755
              2024-03-01         2024            q4             1         0.0000  ...               78.7097     44.5010             NaN             56.1690
              2024-03-01         2025            q4             1         0.0000  ...               78.9570     44.3938             NaN             65.7358
              2024-03-04         2023            q4             1        -0.0170  ...               84.5650     44.2611             NaN             65.1073
              2024-03-04         2024            q4             1         0.0000  ...               83.7651     44.3416             NaN             58.7515
              2024-03-04         2025            q4             1         0.0000  ...               84.1743     44.2410             NaN             68.6895
              2024-03-05         2023            q4             1        -0.0212  ...               77.7674     46.2387             NaN             66.2059
              2024-03-05         2024            q4             1        -0.0061  ...               75.9653     46.1452             NaN             63.5599
              2024-03-05         2025            q4             1         0.0000  ...               76.8983     46.1120             NaN             66.6957
              2024-03-06         2023            q4             1        -0.0212  ...               82.0056     46.4060             NaN             67.4164
              2024-03-06         2024            q4             1        -0.0061  ...               80.9524     46.2512             NaN             65.6695
              2024-03-06         2025            q4             1         0.0000  ...               81.3419     46.2551             NaN             68.4966
              2024-03-07         2023            q4             1        -0.0043  ...               75.4206     46.7157             NaN             65.4906
              2024-03-07         2024            q4             1        -0.0061  ...               74.0613     46.6017             NaN             63.5211
              2024-03-07         2025            q4             1         0.0000  ...               74.8741     46.6050             NaN             66.2040
              2024-03-08         2023            q4             1        -0.0043  ...               77.6636     47.0659             NaN             66.0966
              2024-03-08         2024            q4             1        -0.0061  ...               77.1355     46.9415             NaN             64.4987
              2024-03-08         2025            q4             1         0.0000  ...               77.2644     46.8964             NaN             67.0258
              2024-03-11         2023            q4             1        -0.0043  ...               81.7453     46.7686             NaN             67.7654
              2024-03-11         2024            q4             1        -0.0061  ...               81.4366     46.7272             NaN             65.9262
              2024-03-11         2025            q4             1         0.0000  ...               81.6843     46.5934             NaN             70.4595
              2024-03-12         2023            q4             1         0.0000  ...               81.6935     48.9729             NaN             69.5530
              2024-03-12         2024            q4             1         0.0000  ...               81.1280     48.8875             NaN             68.4896
              2024-03-12         2025            q4             1         0.0000  ...               81.5328     48.9071             NaN             70.7536
              2024-03-13         2023            q4             1         0.0000  ...               86.5940     48.7919             NaN             70.9894
              2024-03-13         2024            q4             1         0.0000  ...               86.5076     48.6579             NaN             70.1666
              2024-03-13         2025            q4             1         0.0000  ...               86.6975     48.7294             NaN             72.4456
              2024-03-14         2023            q4             1         0.0000  ...               92.5154     79.2227             NaN             79.1019
              2024-03-14         2024            q4             1        -0.0602  ...               92.3010     79.8479             NaN             69.9284
              2024-03-14         2025            q4             1        -0.0892  ...               92.5104     79.1011             NaN             71.5185
              2024-03-15         2023            q4             1            NaN  ...               68.0680     64.3674             NaN                 NaN
              2024-03-15         2024            q4             1        -0.1160  ...               66.2651     65.0821             NaN             49.0306
              2024-03-15         2025            q4             1        -0.1491  ...               67.8637     64.0956             NaN             57.5602
              2024-03-18         2024            q4             1        -0.1154  ...               75.5662     66.7460             NaN             51.8615
              2024-03-18         2025            q4             1        -0.1485  ...               76.7474     65.9015             NaN             48.3330
              2024-03-19         2024            q4             1        -0.1154  ...               83.8639     77.7120             NaN             56.4149
              2024-03-19         2025            q4             1        -0.1485  ...               84.3064     76.7392             NaN             52.6831
              2024-03-20         2024            q4             1        -0.1154  ...               82.9630     77.5365             NaN             56.2082
              2024-03-20         2025            q4             1        -0.1485  ...               83.1466     76.6601             NaN             52.4388
              2024-03-21         2024            q4             1        -0.0587  ...               80.1825     76.0564             NaN             55.1362
              2024-03-21         2025            q4             1        -0.0651  ...               80.2429     75.0917             NaN             51.3008
              2024-03-21         2026            q4             1         0.0303  ...               86.6667     81.1333             NaN                 NaN
              2024-03-22         2024            q4             1        -0.0018  ...               81.0099     73.7112             NaN             55.2463
              2024-03-22         2025            q4             1         0.0008  ...               81.0209     72.5582             NaN             52.7317
              2024-03-22         2026            q4             1         0.0005  ...               89.1304     75.8601             NaN                 NaN
              2024-03-25         2024            q4             1         0.0000  ...               70.5172     73.2818             NaN             53.0433
              2024-03-25         2025            q4             1         0.0000  ...               71.7130     72.0876             NaN             49.5778
              2024-03-25         2026            q4             1         0.0000  ...               80.5825     72.7421             NaN                 NaN

[48 rows x 53 columns]
```


## 新闻舆情数据 {#rqdata-API-news-overview}

可获取 2017 年起至今的个股新闻情绪指标，正式数据日内每半小时更新

### news.get_stock_news - 获取个股新闻情绪指标 {#rqdata-API-news_get_stock_news}

```python
news.get_stock_news(order_book_ids, start_date=None, end_date=None, fields=None)
```

获取个股新闻情绪指标数据，支持按股票和时间区间查询。例如可获取新闻标题、新闻舆情指标、公司舆情指标等数据。

::: tip 注意事项

请先单独安装 rqdatac_news，导入后使用

:::

#### 参数 {#rqdata-API-news_get_stock_news-params}

| 参数           | 类型                                                     | 说明                                                             |
|-----|-----|-----|
| order_book_ids | _str_ or _str list_                                      | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询开始时间，不传入默认返回最近 1 个月的数据                    |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询结束时间，不传入默认返回最近 1 个月的数据                    |
| fields         | _str_ or _str list_                                      | 字段名称，默认返回全部字段                                       |

#### 返回 {#rqdata-API-news_get_stock_news-return}

_pandas DataFrame_

| 返回                      | 类型             | 说明                                                   |
|-----|-----|-----|
| datetime                  | _pandas.Timestamp_| 新闻时间戳                                             |
| order_book_id             | _str_            | 股票代码                                               |
| news_id                   | _int(11)_        | 新闻 Id                                                |
| title                     | _varchar(2000)_  | 新闻标题                                               |
| original_time             | _pandas.Timestamp_| 新闻发布时间                                           |
| url                       | *varchar(2000)*  | 新闻 Url                                               |
| source                    | *varchar(200)*   | 新闻源                                                 |
| news_emotion_indicator    | *tinyint(2)*     | 新闻舆情指标，其中 -1 代表负向、0 代表中性、1 代表正向 |
| news_neutral_weight       | *double*         | 新闻舆情中性指标权重                                   |
| news_positive_weight      | *double*         | 新闻舆情正向指标权重                                   |
| news_negative_weight      | *double*         | 新闻舆情负向指标权重                                   |
| company_relevance         | *float*          | 公司标签的相关度                                       |
| company_emotion_indicator | *Integer*        | 公司舆情指标，其中 -1 代表负向、0 代表中性、1 代表正向 |
| company_neutral_weight    | *float*          | 公司舆情中性指标权重                                   |
| company_positive_weight   | *float*          | 公司舆情正向指标权重                                   |
| company_negative_weight   | *float*          | 公司舆情负向指标权重                                   |

#### 范例 {#rqdata-API-news_get_stock_news-example}

- 获取一个股票在 2021-03-01 的新闻舆情数据

```python
[In]
import rqdatac
import rqdatac_news
rqdatac.init()
rqdatac.news.get_stock_news('000001.XSHE','2021-03-01','2021-03-01')
[Out]
                               news_id title                                                       original_time          url                                              source   news_emotion_indicator news_neutral_weight news_positive_weight news_negative_weight company_relevance company_emotion_indicator company_neutral_weight company_positive_weight company_negative_weight
order_book_id datetime
000001.XSHE  2021-03-01 00:15:56 29752958 区域房企在行动 成都之后花样年、德商云南再联手                     2021-02-28 23:44:00   http://www.guandian.cn/article/20210228/256235...   观点地产网 1                    0.030015          0.969985            0.000000               0.0274                           0             0.7115             0.0316             0.2569
             2021-03-01 09:17:15 29759908 哈尔滨南岗区5个重点项目集中签约 涉华润、平安银行、绿地等        2021-03-01 09:14:00   https://kuaixun.stcn.com/cj/202103/t20210301_2...    证券时报网 1                     0.072500       0.927500             0.000000            0.8333             0                    0.8652             0.1152             0.0197
             2021-03-01 11:05:18 29766059 ​似曾相似的震荡回调市场，后来“基金们”都怎样了？                 2021-03-01 10:32:00   https://finance.sina.com.cn/money/fund/jjzl/20...  新浪网   -1                    0.525500           0.474500             0.000000              0.0177             1                    0.3488             0.6482             0.0030
             2021-03-01 11:23:01 29767212 起风了：银行揽储压力升级 自营渠道挑战加剧                       2021-03-01 11:23:01  https://finance.sina.cn/bank/yhgd/2021-03-01/d...   新浪网  -1                       0.646000         0.354000            0.000000              0.0423             0                    0.4052             0.2164             0.3783
             2021-03-01 11:57:40 29768799 平安银行台州分行被罚79万：信贷资金被挪用流入股市                2021-03-01 11:57:40   https://finance.sina.cn/2021-03-01/detail-ikft...  新浪网  -1                       0.985500         0.014500            0.000000               0.8333             -1                   0.0030             0.0005             0.9966
             2021-03-01 12:21:03 29769583 平安银行台州分行被罚79万元：贷后管理不到位，信贷资金被挪用于购房 2021-03-01 12:12:00  https://www.jiemian.com/article/5741403.html     界面新闻  -1                     0.954000       0.046000           0.000000              1.0000               -1                   0.0059             0.0010             0.9931
             2021-03-01 12:26:01 29769736 细数金融工作成就，开启青岛发展新篇章！                           2021-03-01 12:20:17  http://biz.jrj.com.cn/2021/03/01122032049210.s...   金融界 1                      0.000000         0.954500            0.045500              0.0563              0                    0.7625             0.2259             0.0116
             2021-03-01 12:26:02 29769737 青岛全市金融工作座谈会召开                                      2021-03-01 12:22:05 http://biz.jrj.com.cn/2021/03/01122232049215.s...  金融界    1                     0.000000       0.955500               0.044500              0.1146             0                    0.9064             0.0922             0.0014
             2021-03-01 12:26:09 29769745 继四大行后平安银行官宣：将按二手房参考价办理房贷                2021-03-01 08:29:48  https://new.qq.com/omn/20210301/20210301A01I2T...    腾讯网 -1                       0.921500          0.078000          0.000500              0.3534             0                       0.8004             0.1240             0.0756
```


## ESG 评价数据 {#rqdata-API-esg-overview}

正式数据可获取 2014 年 4 月 30 日至今的个股 ESG 评价数据，日度更新。

### esg.get_rating - 获取个股 ESG 评价数据 {#rqdata-API-esg_get_rating}

```python
esg.get_rating(order_book_ids, start_date=None, end_date=None, level=None, type=None)
```

获取个股 ESG 评价数据，支持按时间范围、横向层级和纵向类别查询。例如 level 可选 0、1、2，type 可选 E、S、G，也包括 ESG 综合评价、环境、社会责任和治理相关评价数据。

::: tip 注意事项

请先单独安装 rqdatac_esg，导入后使用

:::

#### 参数 {#rqdata-API-esg_get_rating-params}

| 参数           | 类型                                                            | 说明                                                                                                                 |
|-----|-----|-----|
| order_book_ids | _str or str list_                                               | **必填参数**，合约代码，输入 order_book_id 或 order_book_id list。                                                   |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_  | 查询开始时间，不传入默认返回所有时段数据                                                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询结束时间，不传入默认返回所有时段数据                                                                             |
| level          | _integer or integer list_                                       | ESG 评价级别，共三级。默认返回所有级别分类。参数 0，1,2。0 返回为 ESG 综合评价，1 返回为一级维度，2 返回为二级维度。 |
| type           | _str or str list_                                               | 分为 E,S,G 三个类别：E 表示环境，S 表示社会责任，G 表示治理。默认返回所有类别。                                      |

#### 返回 {#rqdata-API-esg_get_rating-return}

_pandas DataFrame_

| 字段          | 类型                      | 说明             | 描述                                                                                                                                                                                                                                                                                                            | 备注                                            |
|-----|-----|-----|-----|-----|
| order_book_id | _str_                     | 股票代码         | 上市公司股票代码                                                                                                                                                                                                                                                                                                |                                                 |
| rating_date   | _pandas.Timestamp_         | 评价日期         | 评价结果对应日期                                                                                                                                                                                                                                                                                                | 每月底评价一次，评价历史最早可追溯到 2014-04-30 |
| name          | _varchar or varchar list_ | 单个评价的名称   | 取值列表：[esg_overall, environmental, social, governance, environment_management, resources_efficiency, environment_discharge, climate_change, human_capital, health_and_safety, product_liability, business_innovation, social_capital, governance_structure, shareholders, compliance, audit, transparency ] |                                                 |
| type          | _str or str list_         | 评价所属纵向维度 | 分为三个大类：环境一级维度和环境二级维度为 E，社会责任一级维度和社会责任二级维度为 S，治理一级维度和治理二级维度为 G。ESG 综合评价则输出为空。                                                                                                                                                                  |                                                 |
| level         | _integer_                 | 评价所属横向维度 | ESG 评价所属级别，共三级。ESG 综合评价等级/得分的 level=0，一级维度评价/得分 level=1，二级维度评价/得分 level=2。level=0 时无论输入哪个 type 输出均为 ESG 综合评价等级/得分                                                                                                                                     |                                                 |
| rating        | _varchar_                 | 评级等级         | 单个评价的评价等级                                                                                                                                                                                                                                                                                              |                                                 |
| score         | _numeric_                 | 评价得分         | 单个评价的评价得分                                                                                                                                                                                                                                                                                              |                                                 |

::: tip 计算逻辑说明：

对于纵向评价以及得分的标准如下：

Level 0：ESG 综合评价等级和得分

- ESG 综合评价等级：根据 ESG 综合评价分数高低分为高（AAA、AA、A）、中（BBB、BB、B）、低（CCC、CC、C）3 档共 9 个等级。

- ESG 综合评价得分：取值范围为 0-100 分，根据环境、社会责任、治理 3 个一级维度综合计算得出。

Level 1： 包含环境，社会责任，治理这三个方面的评价等级和得分

- 等级：根据评价分数高低分成 9 个等级。

- 得分：取值范围为 0-100 分，评价得分根据单个一级维度下的二级维度评价得分综合计算得出。（针对不同行业采用不同权重计算）

Level 2：4+5+5 共 14 个二级维度的评价等级和得分

- 等级：根据评价分数高低分为 9 个等级。

- 得分：取值范围为 0-100 分，评价得分根据单个二级维度下的细分指标综合计算得出。

:::

#### 范例 {#rqdata-API-esg_get_rating-example}

- 获取单只股票的 ESG 数据

```python
[In]
import rqdatac
import rqdatac_esg
rqdatac.init()
rqdatac.esg.get_rating('000039.XSHE')
[Out]
                                                   rice_create_time rating score level type
order_book_id rating_date   name
000039.XSHE     2014-04-30
                              audit                 2024-02-27 14:46:47 AAA 100.00 2 G
                              business_innovation 2024-02-27 14:46:47 A 65.82 2 S
                              climate_change     2024-02-27 14:46:47 AAA 85.00 2 E
                              compliance         2024-02-27 14:46:47 AAA 100.00 2 G
                              environment_discharge 2024-02-27 14:46:47 C None 2 E
                              ... ... ... ... ... ... ...
                2024-01-31   resources_efficiency 2024-02-27 14:46:47 AAA 98.17 2 E
                              shareholders         2024-02-27 14:46:47 AA 77.43 2 G
                              social             2024-02-27 14:46:47 A 69.91 1 S
                              social_capital     2024-02-27 14:46:47 B 45.96 2 S
                              transparency         2024-02-27 14:46:47 AAA 80.00 2 G
```
