## 股票行情数据说明 {#rqdata-API-stock-overview}

可获取股票合约的日行情、分钟行情、tick 行情数据，具体调用方式请参考 [API-get_price](generic-api.md#rqdata-API-get_price).

## A 股财务数据 {#rqdata-API-financials}

米筐科技（RiceQuant）基于量化交易的实际投资研究需求，对财务数据建立了一套完整的上市公司财务数据处理流程。米筐科技的财务数据有如下优点：

- 对三大表（资产负债表、现金流量表、利润表）原生财务数据实现自动化清洗检查入库流程，及时发现异常数据，并基于上市公司公布财报进行人工核对
- 自主实现超过 200 个衍生财务数据计算，并根据量化投研需求，分为估值衍生指标、经营衍生指标、现金流衍生指标、财务衍生指标、成长性衍生指标五类
- 对原生及衍生财务数据均实现了 LF、LYR、TTM 三种计算逻辑，用户可根据实际需求，灵活选择合适的数据实现指标选股/因子构建/策略编写等量化投资研究流程
- 计算过程中考虑历史数据实际公布时间点，严格避免未来数据，为因子/策略的检验回测提供严谨可靠的数据支持

以下表格的字段全部基于新会计准则并直接采集于三大财报（资产负债表、利润表和现金流量表）。财报本身的来源常见有交易所的定期公告中的常规季报和年报、临时公告中的业绩快报和比较式财务报告以及招股说明书等。该部分数据一定来源于完整的财报，所以一般意义上的业绩快报，业绩预增报告中的数据并不会出现。<br/>

### get_pit_financials_ex - 查询季度财务信息(point-in-time 形式) {#rqdata-API-get_pit_financials_ex}

```python
get_pit_financials_ex(order_book_ids, fields, start_quarter, end_quarter, date=None, statements='latest', market='cn')
```

获取按给定查询日期和报告期回溯的季度基础财务数据，包括利润表、资产负债表和现金流量表字段，支持中国内地与香港市场。

#### 参数 {#rqdata-API-get_pit_financials_ex-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                       |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                           |
| fields         | _list_                                                         | **必填参数**，需要传入的财务字段。支持的字段仅限[利润表](#income_statement)，[资产负债表](#balance_sheet)，[现金流量表](#cash_flow_statement)三大表字段    |
| start_quarter  | _str_                                                          | **必填参数**，财报回溯查询的起始报告期，例如'2015q2'代表 2015 年半年报 。                                                                                  |
| end_quarter    | _str_                                                          | **必填参数**，财报回溯查询的截止报告期，例如'2015q4'代表 2015 年年报。                                                                                     |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认查询日期为当前最新日期                                                                                                                       |
| statements     | _str_                                                          | 基于查询日期，返回某一个报告期的所有记录或最新一条记录，设置 statements 为 all 时返回所有记录，statements 等于 latest 时返回最新的一条记录，默认为 latest. |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                        |

#### 返回 {#rqdata-API-get_pit_financials-return_ex}

_pandas DataFrame_

| 字段        | 类型               | 说明                                                                                                                                                                                                |
| ----------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| quarter     | _str_              | 报告期                                                                                                                                                                                              |
| info_date   | _pandas.Timestamp_ | 公告发布日                                                                                                                                                                                          |
| fields      | _list_             | 返回的财务字段。返回的字段仅限[利润表](#income_statement)，[资产负债表](#balance_sheet)，[现金流量表](#cash_flow_statement)三大表字段                                                               |
| if_adjusted | _int_              | 是否为非当期财报数据, 0 代表当期，1 代表非当期（比如 18 年的财报会披露本期和上年同期的数值，17 年年报的财务数值在 18 年年报中披露的记录则为非当期， 17 年年报的财务数值在 17 年年报中披露则为当期。 |

##### 利润表 {#income_statement}

可点击下载<a href="https://assets.ricequant.com/vendor/rqdata/利润表.xlsx" target="_blank">利润表</a >

| 字段                                              | 释义、备注                                                                                                                                                                                                                                           |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| revenue                                           | 营业总收入：公司经营所取得的收入总额 <br/> 金融类公司不公布营业总收入，因此 revenue 指标只能使用类似的一个指标-operating_revenue 来参考 [:mba](http://wiki.mbalib.com/zh-tw/%e8%90%a5%e4%b8%9a%e6%94%b6%e5%85%a5)                                    |
| operating_revenue                                 | 营业收入：公司经营主要业务所取得的收入总额 [:mba](http://wiki.mbalib.com/zh-tw/%e8%90%a5%e4%b8%9a%e6%94%b6%e5%85%a5)                                                                                                                                 |
| net_interest_income                               | 利息净收入                                                                                                                                                                                                                                           |
| net_commission_income                             | 手续费及佣金净收入                                                                                                                                                                                                                                   |
| commission_income                                 | 其中:手续费及佣金收入                                                                                                                                                                                                                                |
| commission_expense                                | 其中:手续费及佣金支出                                                                                                                                                                                                                                |
| net_proxy_security_income                         | 其中:代理买卖证券业务净收入                                                                                                                                                                                                                          |
| sub_issue_security_income                         | 其中:证券承销业务净收入                                                                                                                                                                                                                              |
| net_trust_income                                  | 其中:受托客户资产管理业务净收入                                                                                                                                                                                                                      |
| earned_premiums                                   | 已赚保费                                                                                                                                                                                                                                             |
| premiums_income                                   | 保险业务收入                                                                                                                                                                                                                                         |
| reinsurance_income                                | 其中:分保费收入                                                                                                                                                                                                                                      |
| reinsurance                                       | 减:分出保费                                                                                                                                                                                                                                          |
| unearned_premium_reserve                          | 提取未到期责任准备金                                                                                                                                                                                                                                 |
| total_expense                                     | 营业总成本                                                                                                                                                                                                                                           |
| operating_expense                                 | 营业支出(金融类企业披露)                                                                                                                                                                                                                             |
| refunded_premiums                                 | 退保金                                                                                                                                                                                                                                               |
| compensation_expense                              | 赔付支出                                                                                                                                                                                                                                             |
| amortization_expense                              | 减:摊回赔付支出                                                                                                                                                                                                                                      |
| premium_reserve                                   | 提取保险责任准备金                                                                                                                                                                                                                                   |
| amortization_premium_reserve                      | 减:摊回保险责任准备金                                                                                                                                                                                                                                |
| policy_dividend_payout                            | 保单红利支出                                                                                                                                                                                                                                         |
| reinsurance_cost                                  | 分保费用                                                                                                                                                                                                                                             |
| other_operating_revenue                           | 其他经营收入                                                                                                                                                                                                                                         |
| other_operating_cost                              | 其他经营成本                                                                                                                                                                                                                                         |
| r_n_d                                             | 研发费用                                                                                                                                                                                                                                             |
| other_net_income                                  | 非经营性净收益                                                                                                                                                                                                                                       |
| net_open_hedge_income                             | 净敞口套期收益                                                                                                                                                                                                                                       |
| other_revenue                                     | 其他收益                                                                                                                                                                                                                                             |
| credit_asset_impairment                           | 信用资产减值损失                                                                                                                                                                                                                                     |
| o_n_a_expense                                     | 业务及管理费用                                                                                                                                                                                                                                       |
| amortization_reinsurance_cost                     | 减:摊回分保费用                                                                                                                                                                                                                                      |
| insurance_commission_expense                      | 保险手续费及佣金支出                                                                                                                                                                                                                                 |
| disposal_income_on_asset                          | 资产处置收益                                                                                                                                                                                                                                         |
| cost_of_goods_sold                                | 营业成本(非金融类企业披露)：公司经营主要业务产生的实际成本 [:mba](http://wiki.mbalib.com/wiki/%e8%90%a5%e4%b8%9a%e6%88%90%e6%9c%ac)                                                                                                                  |
| sales_tax                                         | 营业税 [:mba](http://wiki.mbalib.com/wiki/%e8%90%a5%e4%b8%9a%e7%a8%8e%e9%87%91%e5%8f%8a%e9%99%84%e5%8a%a0)                                                                                                                                           |
| gross_profit                                      | 主营业务利润 [:investopedia](http://www.investopedia.com/terms/i/ifo.asp)                                                                                                                                                                            |
| selling_expense                                   | 销售费用：指企业在销售产品、自制半成品和工业性劳务等过程中发生的各项费用 [:mba](http://wiki.mbalib.com/wiki/%e9%94%80%e5%94%ae%e8%b4%b9%e7%94%a8)                                                                                                    |
| ga_expense                                        | 管理费用：指企业的行政管理部门为管理和组织经营而发生的各项费用 [:mba](http://wiki.mbalib.com/wiki/%e7%ae%a1%e7%90%86%e8%b4%b9%e7%94%a8)                                                                                                              |
| financing_expense                                 | 财务费用： 指企业为筹集生产经营所需资金等而发生的费用，包括利息支出（减利息收入）、汇兑损失（减汇兑收益）以及相关的手续费等 [:mba](http://wiki.mbalib.com/wiki/%e8%b4%a2%e5%8a%a1%e8%b4%b9%e7%94%a8)                                                 |
| financing_interest_income                         | 利息收入（财务费用），财务费用科目下进一步细分的子会计科目                                                                                                                                                                                           |
| financing_interest_expense                        | 利息支出（财务费用），财务费用科目下进一步细分的子会计科目                                                                                                                                                                                           |
| exchange_gains_or_losses                          | 兑汇损益：发生外币交易后期末账户因此调整时，由于采用不同货币，或同一货币不同比价的汇率核算时产生的、按记账本位币折算的差额 [:mba](http://wiki.mbalib.com/wiki/%e6%b1%87%e5%85%91%e6%8d%9f%e7%9b%8a)                                                  |
| profit_from_operation                             | 营业利润： 企业在其全部销售业务中实现的利润，又称营业利润、经营利润，它包含主营业务利润 [:mba](http://wiki.mbalib.com/wiki/%e8%90%a5%e4%b8%9a%e5%88%a9%e6%b6%a6)                                                                                     |
| invest_income_associates                          | 对联营合营企业的投资收益                                                                                                                                                                                                                             |
| fair_value_change_income                          | 公允价值变动净收益                                                                                                                                                                                                                                   |
| investment_income                                 | 投资收益：指企业进行投资所获得的经济利益 [:mba](http://wiki.mbalib.com/wiki/%e6%8a%95%e8%b5%84%e6%94%b6%e7%9b%8a)                                                                                                                                    |
| asset_impairment                                  | 资产减值损失                                                                                                                                                                                                                                         |
| interest_income                                   | 利息收入                                                                                                                                                                                                                                             |
| interest_expense                                  | 利息支出                                                                                                                                                                                                                                             |
| non_operating_revenue                             | 营业外收入：指企业发生的与其生产经营无直接关系的各项收入，包括固定资产盘盈、非货币性交易收益、出售无形资产收益等 [:mba](http://wiki.mbalib.com/wiki/%e8%90%a5%e4%b8%9a%e5%a4%96%e6%94%b6%e5%85%a5)                                                   |
| non_operating_expense                             | 营业外支出：企业发生的与其生产经营无直接关系的各项支出，如固定资产盘亏、债务重组损失、罚款支出、捐赠支出、非常损失等 [:mba](http://wiki.mbalib.com/wiki/%e8%90%a5%e4%b8%9a%e5%a4%96%e6%94%af%e5%87%ba)                                               |
| disposal_loss_on_asset                            | 非流动资产处置净损失：包括固定资产处置损失和无形资产出售损失 [:mba](http://wiki.mbalib.com/wiki/%e9%9d%9e%e6%b5%81%e5%8a%a8%e8%b5%84%e4%ba%a7%e5%a4%84%e7%bd%ae%e6%8d%9f%e5%a4%b1)                                                                   |
| other_effecting_total_profits_items               | 影响利润总额的其他科目                                                                                                                                                                                                                               |
| profit_before_tax                                 | 利润总额： 指税前利润，也就是企业在所得税前一定时期内经营活动的总成果 [:mba](http://wiki.mbalib.com/wiki/%e5%88%a9%e6%b6%a6%e6%80%bb%e9%a2%9d)                                                                                                       |
| income_tax                                        | 所得税：以纳税人的所得额为课税对象的各种税收的统称 [:mba](http://wiki.mbalib.com/wiki/%e6%89%80%e5%be%97%e7%a8%8e)                                                                                                                                   |
| unrealised_investment_loss                        | 未确认的投资损失： 因母公司和子公司确认子公司损益方式不同而在合并报表中使用的一个调节性科目                                                                                                                                                          |
| other_effecting_net_profits_items                 | 影响净利润的其他科目                                                                                                                                                                                                                                 |
| net_profit                                        | 净利润（收益）是指在利润总额中按规定交纳了所得税以后公司的利润留存，一般也称为税后利润或净收入 [:mba](http://wiki.mbalib.com/wiki/%e5%87%80%e5%88%a9%e6%b6%a6)                                                                                       |
| non_recurring_pnl                                 | 非经常性损益                                                                                                                                                                                                                                         |
| net_profit_deduct_non_recurring_pnl               | 扣除非经常性损益后的净利润                                                                                                                                                                                                                           |
| classified_by_continuity_operation                | \(一\)按经营持续性分类                                                                                                                                                                                                                               |
| continuous_operation_net_profit                   | 持续经营净利润                                                                                                                                                                                                                                       |
| discontinued_operation_net_profit                 | 终止经营净利润                                                                                                                                                                                                                                       |
| classified_by_ownership                           | \(二\)按所有权归属分类                                                                                                                                                                                                                               |
| net_profit_parent_company                         | 归属母公司净利润： 反映在企业合并净利润中，归属于母公司股东（所有者）所有的那部分净利润 [:others](http://www.baike.com/wiki/%e5%bd%92%e5%b1%9e%e4%ba%8e%e6%af%8d%e5%85%ac%e5%8f%b8%e6%89%80%e6%9c%89%e8%80%85%e5%87%80%e5%88%a9%e6%b6%a6)            |
| minority_profit                                   | 少数股东损益                                                                                                                                                                                                                                         |
| other_income                                      | 其他综合收益：指企业根据企业会计准则规定未在损益中确认的各项利得和损失扣除所得税影响后的净额 [:mba](http://wiki.mbalib.com/wiki/%e5%85%b6%e4%bb%96%e7%bb%bc%e5%90%88%e6%94%b6%e7%9b%8a)                                                              |
| other_income_unclassified_income_statement        | \(一\)以后不能重分类进损益表的其他综合收益                                                                                                                                                                                                           |
| remearsured_other_income                          | 1\.1 重新计量设定收益计划净负债或净资产的变动                                                                                                                                                                                                        |
| other_income_equity_unclassified_income_statement | 1\.2 权益法下在被投资单位不能重分类进损益表的其他综合收益中享有的份额                                                                                                                                                                                |
| other_equity_instruments_change                   | 1\.3 其他权益工具投资公允价值变动                                                                                                                                                                                                                    |
| corporate_credit_risk_change                      | 1\.4 企业自身信用风险公允价值变动                                                                                                                                                                                                                    |
| other_income_classified_income_statement          | \(二\)以后能重分类进损益表的其他综合收益                                                                                                                                                                                                             |
| other_income_equity_classified_income_statement   | 2\.1 权益法下在被投资单位能重分类进损益表的其他综合收益中享有的份额                                                                                                                                                                                  |
| financial_asset_available_for_sale_change         | 2\.2 可供出售金融资产公允价值变动损益                                                                                                                                                                                                                |
| financial_asset_hold_to_maturity_change           | 2\.3 持有至到期投资重分类为可供出售金融资产损益                                                                                                                                                                                                      |
| cash_flow_hedging_effective_portion               | 2\.4 现金流量套期损益的有效部分                                                                                                                                                                                                                      |
| foreign_currency_statement_converted_difference   | 2\.5 外币财务报表分析折算差额                                                                                                                                                                                                                        |
| others                                            | 2\.6 其他                                                                                                                                                                                                                                            |
| other_debt_investment_change                      | 2\.7 其他债权投资公允价值变动                                                                                                                                                                                                                        |
| assets_reclassified_other_income                  | 2\.8 金融资产重分类计入其他综合收益的金额                                                                                                                                                                                                            |
| other_debt_investment_reserve                     | 2\.9 其他债权投资信用减值准备                                                                                                                                                                                                                        |
| other_income_minority                             | 归属于少数股东的其他综合收益总额                                                                                                                                                                                                                     |
| total_income                                      | 综合收益总额：反映企业净利润与其他综合收益的合计金额 [:mba](http://wiki.mbalib.com/wiki/%e7%bb%bc%e5%90%88%e6%94%b6%e7%9b%8a%e6%80%bb%e9%a2%9d)                                                                                                      |
| total_income_parent_company                       | 归属于母公司所有者的综合收益总额                                                                                                                                                                                                                     |
| total_income_minority                             | 归属于少数股东的综合收益总额                                                                                                                                                                                                                         |
| basic_earnings_per_share                          | 基本每股收益：本每股收益是指企业应当按照属于普通股股东的当期净利润，除以发行在外普通股的加权平均数从而计算出的每股收益 [:mba](http://wiki.mbalib.com/wiki/%e5%9f%ba%e6%9c%ac%e6%af%8f%e8%82%a1%e6%94%b6%e7%9b%8a)                                    |
| fully_diluted_earnings_per_share                  | 稀释每股收益                                                                                                                                                                                                                                         |
| adjust_asset_impairment                           | 资产减值损失：根据财政部发布的《关于修订印发 2019 年度一般企业财务报表格式的通知》格式，“资产减值损失”不隶属于营业总成本部分。因企业披露不一致性，经研究，从 2020.07.08 披露的 2020 年半年报开始，字段数值按照原文披露展示，历史报告期维持原有规则。 |
| adjust_credit_asset_impairment                    | 信用减值损失：根据财政部发布的《关于修订印发 2019 年度一般企业财务报表格式的通知》格式，“信用减值损失”不隶属于营业总成本部分。因企业披露不一致性，经研究，从 2020.07.08 披露的 2020 年半年报开始，字段数值按照原文披露展示，历史报告期维持原有规则。 |

##### 资产负债表 {#balance_sheet}

可点击下载<a href="https://assets.ricequant.com/vendor/rqdata/资产负债表.xlsx" target="_blank">资产负债表</a >

| 字段                                  | 释义、备注                                                                                                                                                                                                                                                                                           |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| financial_asset_held_for_trading      | 企业为了近期内出售而持有的金融资产。通常情况下，以赚取差价为目的从二级市场购入的股票、债券和基金会分类为交易性金融资产 [:mba](http://wiki.mbalib.com/wiki/%e4%ba%a4%e6%98%93%e6%80%a7%e9%87%91%e8%9e%8d%e8%b5%84%e4%ba%a7) [:wikipedia](https://en.wikipedia.org/wiki/financial_asset)               |
| cash_equivalent                       | 货币资金                                                                                                                                                                                                                                                                                             |
| client_deposits                       | 其中:客户资金存款                                                                                                                                                                                                                                                                                    |
| bill_receivable                       | 应收票据：指企业持有的还没有到期、尚未兑现的票据[:mba](http://wiki.mbalib.com/wiki/%e5%ba%94%e6%94%b6%e7%a5%a8%e6%8d%ae)                                                                                                                                                                             |
| dividend_receivable                   | 应收股利： 指企业因股权投资而应收取的现金股利以及应收其他单位的利润，不包括应收的股票股利 [:mba](http://wiki.mbalib.com/wiki/%e5%ba%94%e6%94%b6%e8%82%a1%e5%88%a9)                                                                                                                                   |
| bill_accts_receivable                 | 应收票据及应收账款                                                                                                                                                                                                                                                                                   |
| interest_receivable                   | 应收利息：短期债券投资实际支付的价款中包含的已到付息期但尚未领取的债券利息 [:mba](http://wiki.mbalib.com/wiki/%e5%ba%94%e6%94%b6%e5%88%a9%e6%81%af)                                                                                                                                                  |
| net_accts_receivable                  | 应收账款净额                                                                                                                                                                                                                                                                                         |
| contract_assets                       | 合同资产                                                                                                                                                                                                                                                                                             |
| prepayment                            | 预付账款：企业因购货和接受劳务，按照合同规定预付给供应单位的款项 [:mba](http://wiki.mbalib.com/wiki/%e9%a2%84%e4%bb%98%e6%ac%be%e9%a1%b9)                                                                                                                                                            |
| financial_receivable                  | 应收款项融资                                                                                                                                                                                                                                                                                         |
| financial_lease_receivable            | 应收融资租赁款                                                                                                                                                                                                                                                                                       |
| other_equity_investment               | 其他权益工具投资                                                                                                                                                                                                                                                                                     |
| other_illiquidy_financial_assets      | 其他非流动金融资产                                                                                                                                                                                                                                                                                   |
| non_current_asset_due_one_year        | 一年内到期的非流动资产                                                                                                                                                                                                                                                                               |
| other_receivables_interest_dividend   | 其他应收款(含利息和股利)                                                                                                                                                                                                                                                                             |
| inventory                             | 存货: 指企业在日常活动中持有的以备出售的产成品或商品、处在生产过程中的在产品、在生产过程或提供劳务过程中耗用的材料和物料等 [:mba](http://wiki.mbalib.com/wiki/%e5%ad%98%e8%b4%a7)                                                                                                                    |
| consumable_biological_assets          | 消耗性生物资产                                                                                                                                                                                                                                                                                       |
| deferred_expense                      | 待摊费用： 指支出先发生，费用归属后发生的事项，按照时间长短分为短期待摊费用和长期待摊费用 [:mba](http://wiki.mbalib.com/wiki/%e5%be%85%e6%91%8a%e8%b4%b9%e7%94%a8)                                                                                                                                   |
| assets_hold_for_sale                  | 划分为持有待售的资产                                                                                                                                                                                                                                                                                 |
| other_current_assets                  | 其他流动资产： 指除货币资金、短期投资、应收票据、应收账款、其他应收款、存货等流动资产以外的流动资产 [:mba](http://wiki.mbalib.com/wiki/%e5%85%b6%e4%bb%96%e6%b5%81%e5%8a%a8%e8%b5%84%e4%ba%a7)                                                                                                       |
| current_assets                        | 流动资产合计： 指企业可以在一年内或者超过一年的一个营业周期内变现或者耗用的资产 [:mba](http://wiki.mbalib.com/wiki/%e6%b5%81%e5%8a%a8%e8%b5%84%e4%ba%a7%e5%90%88%e8%ae%a1)                                                                                                                           |
| financial_asset_available_for_sale    | 可供出售金融资产： 指初始确认时即被指定为可供出售的非衍生金融资产，<br/>以及贷款和应收款项、持有至到期投资、交易性金融资产之外的非衍生金融资产 [:mba](http://wiki.mbalib.com/wiki/%e5%8f%af%e4%be%9b%e5%87%ba%e5%94%ae%e9%87%91%e8%9e%8d%e8%b5%84%e4%ba%a7)                                          |
| non_current_liability_due_one_year    | 一年内到期的非流动负债                                                                                                                                                                                                                                                                               |
| debt_investment                       | 债权投资                                                                                                                                                                                                                                                                                             |
| other_debt_investment                 | 其他债权投资                                                                                                                                                                                                                                                                                         |
| financial_asset_hold_to_maturity      | 持有至到期投资： 指企业有明确意图并有能力持有至到期，到期日固定、回收金额固定或可确定的非衍生金融资产 [:mba](http://wiki.mbalib.com/wiki/%e6%8c%81%e6%9c%89%e8%87%b3%e5%88%b0%e6%9c%9f%e6%8a%95%e8%b5%84)                                                                                            |
| real_estate_investment                | 投资性房地产： 指为赚取租金或资本增值，或两者兼有而持有的房地产 [:mba](http://wiki.mbalib.com/wiki/%e6%8a%95%e8%b5%84%e6%80%a7%e6%88%bf%e5%9c%b0%e4%ba%a7)                                                                                                                                           |
| long_term_receivables                 | 长期应收款： 长期应收款是根据长期应收款的账户余额减去未确认融资收益还有一年内到期的长期应收款 [:mba](http://wiki.mbalib.com/wiki/%e9%95%bf%e6%9c%9f%e5%ba%94%e6%94%b6%e6%ac%be)                                                                                                                      |
| net_long_term_equity_investment       | 长期股权投资净额                                                                                                                                                                                                                                                                                     |
| net_fixed_assets                      | 固定资产净额： 固定资产原值减累计折旧再减减值准备后的差额 [:mba](http://wiki.mbalib.com/wiki/%e5%9b%ba%e5%ae%9a%e8%b5%84%e4%ba%a7%e5%87%80%e9%a2%9d)                                                                                                                                                 |
| total_fixed_assets                    | 固定资产合计                                                                                                                                                                                                                                                                                         |
| engineer_material                     | 工程物资： 指用于固定资产建造的建筑材料，如钢材、水泥、玻璃等。在资产负债表中并入在建工程项目 [:mba](http://wiki.mbalib.com/wiki/%e5%b7%a5%e7%a8%8b%e7%89%a9%e8%b5%84)                                                                                                                               |
| construction_in_progress              | 在建工程： 指企业固定资产的新建、改建、扩建，或技术改造、设备更新和大修理工程等尚未完工的工程支出 [:mba](http://wiki.mbalib.com/wiki/%e5%9c%a8%e5%bb%ba%e5%b7%a5%e7%a8%8b)                                                                                                                           |
| total_construction_in_progress        | 在建工程合计                                                                                                                                                                                                                                                                                         |
| fixed_asset_to_be_disposed            | 固定资产清理： 指企业因出售、报废和毁损等原因转入清理的固定资产价值及其在清理过程中所发生的清理费用和清理收入等 [:mba](http://wiki.mbalib.com/wiki/%e5%9b%ba%e5%ae%9a%e8%b5%84%e4%ba%a7%e6%b8%85%e7%90%86)                                                                                           |
| capitalized_biological_assets         | 生产性生物资产： 指为产出农产品、提供劳务或出租等目的而持有的生物资产，包括经济林、薪炭林、产畜和役畜等 [:mba](http://wiki.mbalib.com/wiki/%e7%94%9f%e4%ba%a7%e6%80%a7%e7%94%9f%e7%89%a9%e8%b5%84%e4%ba%a7)                                                                                          |
| oil_and_gas_assets                    | 油气资产： 指油气开采企业所拥有或控制的井及相关设施和矿区权益。油气资产属于递耗资产 [:mba](http://wiki.mbalib.com/wiki/%e6%b2%b9%e6%b0%94%e8%b5%84%e4%ba%a7)                                                                                                                                         |
| intangible_assets                     | 无形资产： 指企业拥有或者控制的没有实物形态的可辨认非货币性资产 [:mba](http://wiki.mbalib.com/wiki/%e6%97%a0%e5%bd%a2%e8%b5%84%e4%ba%a7)                                                                                                                                                             |
| seat_costs                            | 交易席位费                                                                                                                                                                                                                                                                                           |
| impairment_intangible_assets          | 开发支出： 反映企业开发无形资产过程中能够资本化形成无形资产成本的支出部分 [:mba](http://wiki.mbalib.com/wiki/%e5%bc%80%e5%8f%91%e6%94%af%e5%87%ba)                                                                                                                                                   |
| use_right_assets                      | 使用权资产                                                                                                                                                                                                                                                                                           |
| goodwill                              | 商誉： 指能在未来期间为企业经营带来超额利润的潜在经济价值，<br/>或一家企业预期的获利能力超过可辨认资产正常获利能力（如社会平均投资回报率）的资本化价值 [:mba](http://wiki.mbalib.com/wiki/%e5%95%86%e8%aa%89)                                                                                        |
| long_term_deferred_expenses           | 长期待摊费用： 指企业已经支出，但摊销期限在 1 年以上(不含 1 年)的各项费用 [:mba](http://wiki.mbalib.com/wiki/%e9%95%bf%e6%9c%9f%e5%be%85%e6%91%8a%e8%b4%b9%e7%94%a8)                                                                                                                                 |
| deferred_income_tax_assets            | 递延所得税资产： 指对于可抵扣暂时性差异，以未来期间很可能取得用来抵扣可抵扣暂时性差异的应纳税所得额为限确认的一项资产 [:mba](http://wiki.mbalib.com/wiki/%e9%80%92%e5%bb%b6%e6%89%80%e5%be%97%e7%a8%8e%e8%b5%84%e4%ba%a7)                                                                            |
| other_non_current_assets              | 其他非流动资产： 指除资产负债表上所列非流动资产项目以外的其他周转期超过 1 年的长期资产 [:mba](http://wiki.mbalib.com/wiki/%e5%85%b6%e4%bb%96%e9%9d%9e%e6%b5%81%e5%8a%a8%e8%b5%84%e4%ba%a7)                                                                                                           |
| non_current_assets                    | 非流动资产合计                                                                                                                                                                                                                                                                                       |
| loan_account_receivables              | 投资-贷款及应收款项(应收款项类投资)                                                                                                                                                                                                                                                                  |
| fund_providing                        | 融出资金                                                                                                                                                                                                                                                                                             |
| reinsurance_reserve_receivable        | 应收分保合同准备金                                                                                                                                                                                                                                                                                   |
| settlement_provision                  | 结算备付金                                                                                                                                                                                                                                                                                           |
| client_provision                      | 客户备付金                                                                                                                                                                                                                                                                                           |
| interbank_deposits                    | 存放同业款项                                                                                                                                                                                                                                                                                         |
| precious_metals                       | 贵金属                                                                                                                                                                                                                                                                                               |
| lend_capital                          | 拆出资金                                                                                                                                                                                                                                                                                             |
| derivative_financial_assets           | 衍生金融资产                                                                                                                                                                                                                                                                                         |
| resale_financial_assets               | 买入返售金融资产                                                                                                                                                                                                                                                                                     |
| loans_advances_to_customers           | 发放贷款和垫款                                                                                                                                                                                                                                                                                       |
| insurance_receivable                  | 应收保费                                                                                                                                                                                                                                                                                             |
| subrogation_fee_receivable            | 应收代位追偿款                                                                                                                                                                                                                                                                                       |
| reinsurance_receivable                | 应收分保账款                                                                                                                                                                                                                                                                                         |
| unearned_reserve_receivable           | 应收分保未到期责任准备金                                                                                                                                                                                                                                                                             |
| unclaimed_reserve_receivable          | 应收分保未决赔款准备金                                                                                                                                                                                                                                                                               |
| life_reserve_receivable               | 应收分保寿险责任准备金                                                                                                                                                                                                                                                                               |
| health_reserve_receivable             | 应收分保长期健康险责任准备金                                                                                                                                                                                                                                                                         |
| insurer_mortgage_loan                 | 保户质押贷款                                                                                                                                                                                                                                                                                         |
| fixed_deposits                        | 定期存款                                                                                                                                                                                                                                                                                             |
| refundable_deposits                   | 存出保证金                                                                                                                                                                                                                                                                                           |
| refundable_capital_deposits           | 存出资本保证金                                                                                                                                                                                                                                                                                       |
| independent_account_assets            | 独立账户资产                                                                                                                                                                                                                                                                                         |
| other_assets                          | 其他资产                                                                                                                                                                                                                                                                                             |
| other_accts_receivable                | 其他应收款(原值)：是企业除应收票据、应收账款和预付账款以外的各种应收暂付款项                                                                                                                                                                                                                         |
| total_assets                          | 总资产： 指企业拥有或可控制的能以货币计量的经济资源，包括各种财产、债权和其他权利 [:mba](http://wiki.mbalib.com/wiki/%e8%b5%84%e4%ba%a7%e6%80%bb%e8%ae%a1)                                                                                                                                           |
| mortgaged_loan                        | 质押借款                                                                                                                                                                                                                                                                                             |
| short_term_loans                      | 短期借款： 还款期一年以下，企业用来维持正常的生产经营所需的资金或为抵偿某项债务而向银行或其他金融机构等外单位借入的资金 [:mba](http://wiki.mbalib.com/wiki/短期借款)                                                                                                                                 |
| financial_liabilities                 | 交易性金融负债： 交易性金融负债，指企业采用短期获利模式进行融资所形成的负债，比如应付短期债券 [:others](http://baike.baidu.com/view/938376.htm)                                                                                                                                                      |
| notes_payable                         | 应付票据： 应付票据是指企业购买材料、商品和接受劳务供应等而开出、承兑的商业汇票，包括商业承兑汇票和银行承兑汇票。<br/>在我国应收票据、应付票据仅指"商业汇票"，包括"银行承兑汇票"和"商业承兑汇票"两种，属于远期票据，付款期一般在 1 个月以上，6 个月以内 [:mba](http://wiki.mbalib.com/wiki/应付票据) |
| accts_payable                         | 应付账款： 应付帐款是指企业因购买材料、物资和接受劳务供应等而付给供货单位的帐款 [:mba](http://wiki.mbalib.com/wiki/应付帐款)                                                                                                                                                                         |
| bill_accts_payable                    | 应付票据及应付账款                                                                                                                                                                                                                                                                                   |
| contract_liabilities                  | 合同负债                                                                                                                                                                                                                                                                                             |
| advance_from_customers                | 预收账款： 预收账款指买卖双方协议商定，由购货方预先支付一部分货款给供应方而发生的一项负债 [:mba](http://wiki.mbalib.com/wiki/预收账款)                                                                                                                                                               |
| payroll_payable                       | 应付职工薪酬： 应付职工薪酬是指企业为获得职工提供的服务而给予各种形式的报酬以及其他相关支出 [:mba](http://wiki.mbalib.com/wiki/应付职工薪酬)                                                                                                                                                         |
| dividend_payable                      | 应付股利： 应付股利是指企业根据年度利润分配方案，确定分配的股利 [:mba](http://wiki.mbalib.com/wiki/应付股利)                                                                                                                                                                                         |
| tax_payable                           | 应交税费： 应交税费是指企业根据在一定时期内取得的营业收入、实现的利润等，按照现行税法规定，采用一定的计税方法计提的应交纳的各种税费 [:mba](http://wiki.mbalib.com/wiki/应交税费)                                                                                                                     |
| interest_payable                      | 应付利息： 应付利息，是指金融企业根据存款或债券金额及其存续期限和规定的利率，按期计提应支付给单位和个人的利息 [:investopedia](http://wiki.mbalib.com/wiki/应付利息)                                                                                                                                  |
| other_fees_payable                    | 其他应交款： 指企业需要向国家缴纳的各项款项中除了税金以外的各种应交款项，主要包括教育附加费、车辆购置附加费等。 [:others](http://baike.baidu.com/view/598949.htm)                                                                                                                                    |
| other_payable                         | 其他应付款： 该科目只核算企业应付其他单位或个人的零星款项，如应付经营租入固定资产和包装物的租金、存入保证金等 [:mba](http://wiki.mbalib.com/wiki/其他应付款)                                                                                                                                         |
| other_payable_interest_dividend       | 其他应付款（含利息和股利）                                                                                                                                                                                                                                                                           |
| short_term_debt                       | 应付短期债券： 应付短期债券是企业筹资发行一年以下期限的债券，属于流动负债 [:others](http://baike.baidu.com/view/3252275.htm)                                                                                                                                                                         |
| accrued_expense                       | 预提费用： 预提费用是指企业按规定预先提取但尚未实际支付的各项费用。 就是企业还没支付，但应该要支付的，要记入负债 [:others](http://baike.baidu.com/view/264935.htm)                                                                                                                                   |
| liabilities_hold_for_sale             | 划分为持有待售的负债                                                                                                                                                                                                                                                                                 |
| estimated_liabilities                 | 预计负债： 预计负债是因或有事项可能产生的负债 [:mba](http://wiki.mbalib.com/wiki/预计负债)                                                                                                                                                                                                           |
| deferred_income                       | 递延收益： 递延收益是指尚待确认的收入或收益，也可以说是暂时未确认的收益，它是权责发生制在收益确认上的运用 [:mba](http://wiki.mbalib.com/wiki/递延收益)                                                                                                                                               |
| long_term_liabilities_due_one_year    | 一年内到期的长期负债： 一年内到期的长期负债是指反映企业长期负债中自编表日起一年内到期的长期负债 [:others](http://baike.baidu.com/view/1485163.htm)【该数据来自旧会计准则】                                                                                                                           |
| other_current_liabilities             | 其他流动负债： 指不能归属于短期借款，应付短期债券券，应付票据，应付帐款，应付所得税，其他应付款，预收账款这七款项目的流动负债。<br/>但以上各款流动负债，其金额未超过流动负债合计金额百分之五者，得并入其他流动负债内 [:others](http://wiki.mbalib.com/wiki/流动负债)                                 |
| current_liabilities                   | 流动负债合计： 流动负债合计是指企业在一年内或超过一年的一个营业周期内需要偿还的债务 [:mba](http://wiki.mbalib.com/wiki/流动负债合计)                                                                                                                                                                 |
| long_term_loans                       | 长期借款： 长期借款是指企业从银行或其他金融机构借入的期限在一年以上(不含一年)的借款 [:mba](http://wiki.mbalib.com/wiki/长期借款)                                                                                                                                                                     |
| bond_payable                          | 应付债券： 公司为筹集长期资金而实际发行的债券及应付的利息 [:mba](http://wiki.mbalib.com/wiki/%e5%ba%94%e4%bb%98%e5%80%ba%e5%88%b8)                                                                                                                                                                   |
| preference_shares                     | 优先股                                                                                                                                                                                                                                                                                               |
| perpetual_bond                        | 永续债（应付债券）                                                                                                                                                                                                                                                                                   |
| long_term_payable                     | 长期应付款： 指企业除了长期借款和应付债券以外的长期负债，包括应付引进设备款、应付融资租入固定资产的租赁费等 [:mba](http://wiki.mbalib.com/wiki/长期应付款)                                                                                                                                           |
| total_long_term_payable                     | 长期应付款合计                                                                                                                                           |
| accrued_staff_costs                   | 长期应付职工薪酬                                                                                                                                                                                                                                                                                     |
| grants_received                       | 专项应付款： 企业接受国家作为企业所有者拨入的具有专门用途的款项所形成的不需要以资产或增加其他负债偿还的负债 [:others](http://baike.baidu.com/view/241758.htm)                                                                                                                                        |
| deferred_income_tax_liabilities       | 递延所得税负债： 指根据应纳税暂时性差异计算的未来期间应付所得税的金额 [:mba](http://wiki.mbalib.com/wiki/递延所得税负债)                                                                                                                                                                             |
| lease_liabilities                     | 租赁负债                                                                                                                                                                                                                                                                                             |
| financial_lease_payable               | 应付融资租赁款                                                                                                                                                                                                                                                                                       |
| other_non_current_liabilities         | 其他非流动负债： 反映企业除长期借款、应付债券等项目以外的其他非流动负债 [:mba](http://wiki.mbalib.com/wiki/其他非流动负债)                                                                                                                                                                           |
| non_current_liabilities               | 非流动负债合计： 指偿还期在一年或者超过一年的一个营业周期以上的债务。非流动负债的主要项目有长期借款和应付债券 [:mba](http://wiki.mbalib.com/wiki/非流动负债)                                                                                                                                         |
| borrowings_from_central_banks         | 向中央银行借款                                                                                                                                                                                                                                                                                       |
| deposits_of_interbank                 | 同业及其他金融机构存放款项                                                                                                                                                                                                                                                                           |
| borrowings_capital                    | 拆入资金                                                                                                                                                                                                                                                                                             |
| derivative_financial_liabilities      | 衍生金融负债                                                                                                                                                                                                                                                                                         |
| buy_back_security_proceeds            | 卖出回购金融资产款                                                                                                                                                                                                                                                                                   |
| deposits                              | 吸收存款                                                                                                                                                                                                                                                                                             |
| proxy_security_proceeds               | 代理买卖证券款                                                                                                                                                                                                                                                                                       |
| sub_issue_security_proceeds           | 代理承销证券款                                                                                                                                                                                                                                                                                       |
| security_deposits_received            | 存入保证金                                                                                                                                                                                                                                                                                           |
| advance_insurance                     | 预收保费                                                                                                                                                                                                                                                                                             |
| comission_payable                     | 应付手续费及佣金                                                                                                                                                                                                                                                                                     |
| reinsurance_payable                   | 应付分保账款                                                                                                                                                                                                                                                                                         |
| compensation_payable                  | 应付赔付款                                                                                                                                                                                                                                                                                           |
| policy_dividend_payable               | 应付保单红利                                                                                                                                                                                                                                                                                         |
| deposits_from_interbank               | 吸收存款及同业存款                                                                                                                                                                                                                                                                                   |
| insurance_contract_reserve            | 保险合同准备金                                                                                                                                                                                                                                                                                       |
| insurer_deposit_investment            | 保户储金及投资款                                                                                                                                                                                                                                                                                     |
| uncertained_premium_reserve           | 未到期责任准备金                                                                                                                                                                                                                                                                                     |
| unclaimed_indemnity_reserve           | 未决赔款准备金                                                                                                                                                                                                                                                                                       |
| life_insurance_reserve                | 寿险责任准备金                                                                                                                                                                                                                                                                                       |
| health_insurance_reserve              | 长期健康险责任准备金                                                                                                                                                                                                                                                                                 |
| independent_account_liabilities       | 独立账户负债                                                                                                                                                                                                                                                                                         |
| other_liabilities                     | 其他负债                                                                                                                                                                                                                                                                                             |
| deferred_revenue                      | 递延收益(长期负债)： 递延收益是指尚待确认的收入或收益，也可以说是暂时未确认的收益，它是权责发生制在收益确认上的运用 [:mba](http://wiki.mbalib.com/wiki/递延收益)                                                                                                                                     |
| total_liabilities                     | 负债合计： 指企业所承担的能以货币计量，将以资产或劳务偿还的债务 [:mba](http://wiki.mbalib.com/wiki/负债合计)                                                                                                                                                                                         |
| paid_in_capital                       | 实收资本(或股本)： 指企业的投资者按照企业章程或合同、协议的约定，实际投入企业的资本 [:mba](http://wiki.mbalib.com/wiki/实收资本)                                                                                                                                                                     |
| other_equity_instruments              | 其他权益工具                                                                                                                                                                                                                                                                                         |
| equity_preferred_stock                | 权益部分的优先股                                                                                                                                                                                                                                                                                     |
| perpetual_equity_debt                 | 永续债（其他权益工具）                                                                                                                                                                                                                                                                               |
| capital_reserve                       | 资本公积金： 企业收到的投资者的超出其在企业注册资本所占份额，以及直接计入所有者权益的利得和损失等 [:mba](http://wiki.mbalib.com/wiki/资本公积)【该数据来自旧会计准则】                                                                                                                               |
| surplus_reserve                       | 盈余公积： 指企业从税后利润中提取形成的、存留于企业内部、具有特定用途的收益积累 [:others](http://baike.baidu.com/view/56294.htm)                                                                                                                                                                     |
| undistributed_profit                  | 未分配利润： 未分配利润是企业未作分配的利润。它在以后年度可继续进行分配，在未进行分配之前，属于所有者权益的组成部分 [:others](http://baike.baidu.com/view/604521.htm)                                                                                                                                |
| treasury_stock                        | 减:库存股                                                                                                                                                                                                                                                                                            |
| equity_parent_company                 | 归属于母公司所有者权益合计： 母公司股东权益反映的是母公司所持股份部分的所有者权益数 [:others](http://zhidao.baidu.com/question/186319037.html)                                                                                                                                                       |
| total_equity                          | 股东权益合计： 所有者权益合计是指企业投资人对企业净资产的所有权 [:others](http://baike.baidu.com/link?url=euskaau05kjhh04ao0yedx4luc46bkppriyg0qgn7oo9jrom65dablsagqmf6knbiyji3ux9qdodsl8*lc_ks*)                                                                                                    |
| general_reserve                       | 一般风险准备                                                                                                                                                                                                                                                                                         |
| trade_risk_allowances                 | 交易风险准备                                                                                                                                                                                                                                                                                         |
| foreign_currency_converted_difference | 外币报表折算差额                                                                                                                                                                                                                                                                                     |
| uncertained_impairment_losses         | 未确认投资损失                                                                                                                                                                                                                                                                                       |
| other_reserves                        | 其他储备\(公允价值变动储备\)                                                                                                                                                                                                                                                                         |
| specific_reserve                      | 专项储备                                                                                                                                                                                                                                                                                             |
| minority_interest                     | 少数股东权益： 少数股东损益是一个流量概念，是指公司合并报表的子公司其它非控股股东享有的损益 [:mba](http://wiki.mbalib.com/wiki/少数股东损益)                                                                                                                                                         |
| total_equity_and_liabilities          | 负债和股东权益总计                                                                                                                                                                                                                                                                                   |

##### 现金流量表 {#cash_flow_statement}

可点击下载<a href="https://assets.ricequant.com/vendor/rqdata/现金流量表.xlsx" target="_blank">现金流量表</a >

| 字段                                             | 释义、备注                                                                                                                                                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| cash_received_from_sales_of_goods                | 销售商品、提供劳务收到的现金： 公司销售商品、提供劳务实际收到的现金 [:investopedia](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                            |
| refunds_of_taxes                                 | 收到的税费返还： 公司按规定收到的增值税、所得税等税费返还额 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                                             |
| net_deposit_increase                             | 客户存款和同业存放款项净增加额                                                                                                                                                                                                             |
| net_increase_from_central_bank                   | 向中央银行借款净增加额                                                                                                                                                                                                                     |
| net_increase_from_other_financial_institutions   | 向其他金融机构拆入资金净增加额                                                                                                                                                                                                             |
| draw_back_canceled_loans                         | 收回已核销贷款                                                                                                                                                                                                                             |
| cash_received_from_interests_and_commissions     | 收取利息、手续费及佣金的现金                                                                                                                                                                                                               |
| net_increase_from_disposing_financial_assets     | 处置交易性金融资产净增加额                                                                                                                                                                                                                 |
| net_increase_from_repurchasing_business          | 回购业务资金净增加额                                                                                                                                                                                                                       |
| cash_received_from_original_insurance            | 收到原保险合同保费取得的现金                                                                                                                                                                                                               |
| cash_received_from_reinsurance                   | 收到再保业务现金净额                                                                                                                                                                                                                       |
| net_increase_from_insurer_deposit_investment     | 保户储金及投资款净增加额                                                                                                                                                                                                                   |
| net_increase_from_financial_institutions         | 拆入资金净增加额                                                                                                                                                                                                                           |
| cash_received_from_proxy_security                | 代理买卖证券收到的现金净额                                                                                                                                                                                                                 |
| cash_received_from_sub_issue_security            | 代理承销证券收到的现金净额                                                                                                                                                                                                                 |
| cash_from_other_operating_activities             | 收到其它与经营活动有关的现金：公司除了上述各项目外，收到的其他与经营活动有关的现金，<br/>如捐赠现金收入、罚款收入、流动资产损失中由个人赔偿的现金收入等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#) |
| cash_from_operating_activities                   | 经营活动现金流入小计                                                                                                                                                                                                                       |
| cash_paid_for_goods_and_services                 | 购买商品、接受劳务支付的现金： 公司购买商品、接受劳务实际支付的现金 [:investopedia](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                            |
| assets_depreciation_reserves                     | 资产减值准备                                                                                                                                                                                                                               |
| exchange_rate_change_effect                      | 汇率变动对现金及现金等价物的影响                                                                                                                                                                                                           |
| other_effecting_cash_equivalent_items            | 影响现金及现金等价物的其他科目                                                                                                                                                                                                             |
| cash_equivalent_increase                         | 现金及现金等价物净增加额（来源现金流量表主表）                                                                                                                                                                                             |
| begin_period_cash_equivalent                     | 加:期初现金及现金等价物余额                                                                                                                                                                                                                |
| end_period_cash_equivalent                       | 期末现金及现金等价物余额                                                                                                                                                                                                                   |
| cash_paid_for_employee                           | 支付给职工以及为职工支付的现金： 公司实际支付给职工，以及为职工支付的现金，<br/>包括本期实际支付给职工的工资、奖金、各种津贴和补贴等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                    |
| cash_paid_for_taxes                              | 支付的各项税费： 反映企业按规定支付的各种税费，包括本期发生并支付的税费，以及本期支付以前各期发生的税费和预交的税金等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                   |
| net_increase_from_loans_and_advances             | 客户贷款及垫款净增加额                                                                                                                                                                                                                     |
| net_increase_from_central_bank_and_banks         | 存放中央银行和同业款项净增加额                                                                                                                                                                                                             |
| net_increase_from_lending_capital                | 拆出资金净增加额                                                                                                                                                                                                                           |
| cash_paid_for_comissions                         | 支付手续费及佣金的现金                                                                                                                                                                                                                     |
| cash_paid_for_orignal_insurance                  | 支付原保险合同赔付款项的现金                                                                                                                                                                                                               |
| cash_paid_for_reinsurance                        | 支付再保业务现金净额                                                                                                                                                                                                                       |
| cash_paid_for_policy_dividends                   | 支付保单红利的现金                                                                                                                                                                                                                         |
| net_increase_from_trading_financial_assets       | 为交易目的而持有的金融资产净增加额                                                                                                                                                                                                         |
| net_increase_from_operating_buy_back             | 返售业务资金净增加额\(经营\)                                                                                                                                                                                                               |
| cash_paid_for_other_operation_activities         | 支付其他与经营活动有关的现金： 反映企业支付的其他与经营活动有关的现金支出，<br/>如罚款支出、支付的差旅费、业务招待费的现金支出、支付的保险费等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)          |
| cash_paid_for_operation_activities               | 经营活动现金流出小计                                                                                                                                                                                                                       |
| cash_flow_from_operating_activities              | 经营活动产生的现金流量净额： 指企业投资活动和筹资活动以外的所有交易活动和事项的现金流入和流出量 [:mba](http://wiki.mbalib.com/wiki/%e7%bb%8f%e8%90%a5%e4%b8%9a%e5%8a%a1%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f)                               |
| cash_received_from_disposal_of_investment        | 收回投资收到的现金                                                                                                                                                                                                                         |
| cash_received_from_investment                    | 取得投资收益收到的现金                                                                                                                                                                                                                     |
| cash_received_from_disposal_of_asset             | 处置固定资产、无形资产和其他长期资产收回的现金净额： 公司处置固定资产、无形资产和其他长期资产收回的现金 [:investopedia](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                        |
| cash_received_from_other_investment_activities   | 收到其他与投资活动有关的现金： 公司除了上述各项以外，收到的其他与投资活动有关的现金 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                     |
| cash_received_from_investment_activities         | 投资活动现金流入小计                                                                                                                                                                                                                       |
| cash_paid_for_asset                              | 购建固定资产、无形资产和其他长期资产所支付的现金 [:wikipedia](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                                                  |
| cash_paid_to_acquire_investment                  | 投资支付的现金： 反映企业进行权益性投资和债权性投资支付的现金，<br/>包括企业取得的除现金等价物以外的股票投资和债券投资等支付的现金等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                    |
| cash_paid_for_other_investment_activities        | 支付其他与投资活动有关的现金： 反映企业除了上述各项以外，支付的其他与投资活动有关的现金流出 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                             |
| cash_paid_for_investment_activities              | 投资活动产生的现金流出小计                                                                                                                                                                                                                 |
| cash_flow_from_investing_activities              | 投资活动产生的现金流量净额：指企业长期资产的购建和对外投资活动（不包括现金等价物范围的投资）的现金流入和流出量 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                          |
| cash_received_from_investors                     | 吸收投资收到的现金：反映企业收到的投资者投入现金，包括以发行股票、债券等方式筹集的资金实际收到的净额 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                    |
| cash_received_from_minority_invest_subsidiaries  | 其中:子公司吸收少数股东投资收到的现金                                                                                                                                                                                                      |
| cash_received_from_issuing_security              | 发行债券收到的现金                                                                                                                                                                                                                         |
| cash_received_from_financial_institution_borrows | 取得借款收到的现金： 公司向银行或其他金融机构等借入的资金 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                                               |
| cash_received_from_issuing_equity_instruments    | 发行其他权益工具收到的现金                                                                                                                                                                                                                 |
| net_increase_from\_\_financing_buy_back          | 回购业务资金净增加额\(筹资\)                                                                                                                                                                                                               |
| cash_received_from_other_financing_activities    | 收到其他与筹资活动有关的现金：反映企业收到的其他与筹资活动有关的现金流入，如接受现金捐赠等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                              |
| cash_received_from_financing_activities          | 筹资活动现金流入小计                                                                                                                                                                                                                       |
| cash_paid_for_debt                               | 偿还债务支付的现金：公司以现金偿还债务的本金，包括偿还银行或其他金融机构等的借款本金、偿还债券本金等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                    |
| cash_paid_for_dividend_and_interest              | 分配股利、利润或偿付利息支付的现金：反映企业实际支付给投资人的利润以及支付的借款利息、债券利息等 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                        |
| dividends_paid_to_minority_by_subsidiaries       | 其中:子公司支付给少数股东的股利、利润或偿付的利息                                                                                                                                                                                          |
| cash_paid_for_other_financing_activities         | 支付其他与筹资活动有关的现金：反映企业支付的其他与筹资活动有关的现金流出 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                                |
| cash_paid_to_financing_activities                | 筹资活动现金流出小计                                                                                                                                                                                                                       |
| cash_flow_from_financing_activities              | 筹资活动产生的现金流量净额：指企业接受投资和借入资金导致的现金流入和流出量 [:mba](http://wiki.mbalib.com/wiki/%e7%8e%b0%e9%87%91%e6%b5%81%e9%87%8f%e8%a1%a8#)                                                                              |
| net_cash_deal_from_sub                           | 处置子公司及其他营业单位收到的现金净额                                                                                                                                                                                                     |
| net_cash_payment_from_sub                        | 取得子公司及其他营业单位支付的现金净额                                                                                                                                                                                                     |
| net_increase_in_pledge_loans                     | 质押贷款净增加额                                                                                                                                                                                                                           |
| net_increase_from_investing_buy_back             | 返售业务资金净增加额\(投资\)                                                                                                                                                                                                               |
| net_inc_cash_and_equivalents                     | 现金及现金等价物净增加额（来源为财务附注）                                                                                                                                                                                                 |
| fixed_asset_depreciation                         | 固定资产折旧                                                                                                                                                                                                                               |
| deferred_expense_amortization                    | 长期待摊费用摊销                                                                                                                                                                                                                           |
| intangible_asset_amortization                    | 无形资产摊销                                                                                                                                                                                                                               |
| usufruct_asset_amortization                      | 使用权资产摊销                                                                                                                                                                                                                             |

#### 范例 {#rqdata-API-get_pit_financials_ex-example}

- 获取股票 2018q2-2018q3 各报告期最新一次记录

```python
[In]
get_pit_financials_ex(fields=['revenue','net_profit'], start_quarter='2018q2', end_quarter='2018q3',order_book_ids=['000001.XSHE','000048.XSHE'])
[Out]
                  info_date revenue if_adjusted net_profit
order_book_id quarter
000001.XSHE 2018q2 2019-08-08 5.724100e+10 1 1.337200e+10
            2018q3 2019-10-22 8.666400e+10 1 2.045600e+10
000048.XSHE 2018q2 2019-08-31 7.362684e+08 1 -3.527276e+07
            2018q3 2019-10-31 1.216331e+09 1 -4.566952e+07
```

- 获取股票 2018q2 所有的记录

```python
[In]
get_pit_financials_ex(fields=['revenue','net_profit'], start_quarter='2018q2', end_quarter='2018q2',order_book_ids=['000001.XSHE','000048.XSHE'],statements='all')
[Out]
                  info_date revenue if_adjusted net_profit
order_book_id quarter
000001.XSHE 2018q2 2018-08-16 5.724100e+10 0 1.337200e+10
            2018q2 2019-08-08 5.724100e+10 1 1.337200e+10
000048.XSHE 2018q2 2018-08-31 1.063670e+09 0 7.790205e+07
            2018q2 2018-10-31 1.060487e+09 0 7.880372e+07
            2018q2 2019-06-15 7.362684e+08 0 -3.527276e+07
            2018q2 2019-08-31 7.362684e+08 1 -3.527276e+07
```

- 获取股票 2018q2 查询日期为 20190807 的记录

```python
[In]
get_pit_financials_ex(fields=['revenue','net_profit'], start_quarter='2018q2', end_quarter='2018q2',order_book_ids=['000001.XSHE','000048.XSHE'],statements='all',date='20190807')
[Out]
                  info_date revenue if_adjusted net_profit
order_book_id quarter
000001.XSHE 2018q2 2018-08-16 5.724100e+10 0 1.337200e+10
000048.XSHE 2018q2 2018-08-31 1.063670e+09 0 7.790205e+07
            2018q2 2018-10-31 1.060487e+09 0 7.880372e+07
            2018q2 2019-06-15 7.362684e+08 0 -3.527276e+07
```

### current_performance - 查询财务快报数据 {#rqdata-API-current_performance}

```python
current_performance(order_book_ids, info_date=None, quarter=None, interval='1q', fields=None, market='cn')
```

获取股票财务快报数据，支持按公告日期或报告期回溯查询一个或多个报告期。例如可获取营业收入、利润总额、归属母公司净利润等快报字段。

#### 参数 {#rqdata-API-current_performance-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                                                                              |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str or str list_                                              | **必填参数**，合约代码，可输入 order_book_id, order_book_id list                                                                                                                                                                                  |
| info_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 公告日期，如果不填(info_date 和 quarter 都为空)，则返回当前日期的最新发布的快报。如果填写，则从 info_date 当天或者之前最新的报告开始抓取。                                                                                                        |
| quarter        | _str_                                                          | info_date 参数优先级高于 quarter。如果 info_date 填写了日期，则不查看 quarter 这个字段。 如果 info_date 没有填写而 quarter 有填写，则财报回溯查询的起始报告期，例如'2015q2', '2015q4'分别代表 2015 年半年报以及年报。默认只获取当前报告期财务信息 |
| interval       | _str_                                                          | 查询财务数据的间隔。例如，填写'5y'，则代表从报告期开始回溯 5 年，每年为相同报告期数据；'3q'则代表从报告期开始向前回溯 3 个季度。不填写默认抓取一期。                                                                                              |
| fields         | _str_ or _str list_                                            | 抓取对应有效字段返回。默认返回所有字段。具体快报字段见下方。                                                                                                                                                                                      |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                                                                                                                                                                                                          |

##### 财务快报可选字段

| fields                              | 说明                            |
| ----------------------------------- | ------------------------------- |
| operating_revenue                   | 营业收入 or 主营业务收入(元)    |
| gross_profit                        | 主营业务利润(元)                |
| operating_profit                    | 营业利润(元)                    |
| total_profit                        | 利润总额(元)                    |
| np_parent_owners                    | 归属母公司净利润(元)            |
| net_profit_cut                      | 扣除非经常性损益后净利润(元)    |
| net_operate_cashflow                | 经营活动现金流量净额(元)        |
| total_assets                        | 总资产(元)                      |
| se_without_minority                 | 归属母公司普通股东权益(元)      |
| se_parent_owners                    | 归属母公司股东权益(元)          |
| total_shares                        | 总股本(股)                      |
| basic_eps                           | 基本每股收益                    |
| eps_weighted                        | 每股收益(加权)(元)              |
| eps_cut_epscut                      | 每股收益(扣除)(元)              |
| eps_cut_weighted                    | 每股收益(扣除加权)(元)          |
| roe                                 | 净资产收益率(摊薄)(%)           |
| roe_weighted                        | 净资产收益率(加权)(%)           |
| roe_cut                             | 净资产收益率(扣除摊薄)(%)       |
| roe_cut_weighted                    | 净资产收益率(扣除加权)(%)       |
| net_operate_cashflow_per_share      | 每股经营活动现金流量净额(元)    |
| equity_per_share                    | 每股净资产(元)                  |
| operating_revenue_yoy               | 主营业务收入同比(%)             |
| gross_profit_yoy                    | 主营业务利润同比(%)             |
| operating_profit_yoy                | 营业利润同比(%)                 |
| total_profit_yoy                    | 利润总额同比(%)                 |
| np_parent_minority_pany_yoy         | 归属母公司净利润同比(%)         |
| ne_t_minority_ty_yoy                | 扣除非经常性损益后净利润同比(%) |
| net_operate_cash_flow_yoy           | 经营活动现金流量净额同比(%)     |
| total_assets_to_opening             | 总资产较期初比(%)               |
| se_without_minority_to_opening      | 归属母公司股东权益较期初比(%)   |
| basic_eps_yoy                       | 每股收益(摊薄) 同比(%)          |
| eps_weighted_yoy                    | 每股收益(加权) 同比(%)          |
| eps_cut_yoy                         | 每股收益(扣除) 同比(%)          |
| eps_cut_weighted_yoy                | 每股收益(扣除加权) 同比(%)      |
| roe_yoy                             | 净资产收益率(摊薄) 同比(%)      |
| roe_weighted_yoy                    | 净资产收益率(加权) 同比(%)      |
| roe_cut_yoy                         | 净资产收益率(扣除摊薄) 同比(%)  |
| roe_cut_weighted_yoy                | 净资产收益率(扣除加权) 同比(%)  |
| net_operate_cash_flow_per_share_yoy | 每股经营活动现金流量净额同比(%) |
| net_asset_psto_opening              | 每股净资产较期初比(%)           |

<br/>

#### 返回 {#rqdata-API-current_performance-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-current_performance-example}

- 获取单只股票过去一个报告期的快报数据

```python
[In]
current_performance('000004.XSHE')
[Out]
      end_date  info_date  operating_revenue    gross_profit    operating_profit    total_profit    np_parent_owners    net_profit_cut    net_operate_cashflow...roe_cut_weighted_yoy    net_operate_cash_flow_per_share_yoy    net_asset_psto_opening
0   2017-12-31  2018-04-14    1.386058e+08           NaN             8796946.37       9716431.21      8566720.65         NaN                NaN                    NaN                                NaN                               NaN


```

- 获取单只股票多个报告期的总利润

```python
[In]
current_performance('000004.XSHE',quarter='2017q4',fields='total_profit',interval='2q')
[Out]
  end_date  info_date  total_profit
0  2017-12-31  2018-04-14  9716431.21
1  2015-12-31  2016-04-15  10808606.48

```

```python
[In]
current_performance('000004.XSHE',info_date=20170331,fields='total_profit',interval='2q')
[Out]
  end_date  info_date  total_profit
0  2015-12-31  2016-04-15  10808606.48
1  2014-12-31  2015-04-16  20665807.64

```

### performance_forecast - 查询业绩预告数据 {#rqdata-API-performance_forecast}

```python
performance_forecast(order_book_ids, info_date=None, end_date=None, fields=None, market='cn')
```

获取股票业绩预告数据，反映公司对即将到来的财务季度的业绩预期信息。有时同一财务季度会有多条记录，例如季度预期和累计预期，也支持整体业绩预期、预期增长幅度区间、预期净利润区间等字段。

#### 参数 {#rqdata-API-performance_forecast-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                    |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list。                                                                                                                      |
| info_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 公告日期，如果不填(info_date 和 end_date 都为空)，则返回当前日期的最新发布的业绩预告。如果填写，则从 info_date 当天或者之前最新的报告开始抓取。<b>注：info_date 优先级高于 end_date</b> |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 对应财务预告期末日期，如'20150331'。                                                                                                                                                    |
| fields         | _str_ or _str list_                                            | 抓取对应有效字段返回。默认返回所有字段。具体业绩预告字段见下方                                                                                                                          |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                                                                                                                                                |

##### 业绩预告可选字段

| fields                        | 说明                 |
| ----------------------------- | -------------------- |
| forecast_type                 | 整体业绩预期         |
| forecast_description          | 业绩预期时间段描述   |
| forecast_growth_rate_floor    | 最小预期增长幅度     |
| forecast_growth_rate_ceiling  | 最大预期增长幅度     |
| forecast_earning_floor        | 最小预期收入         |
| forecast_earning_ceiling      | 最大预期收入         |
| forecast_np_floor             | 最小预期净利润       |
| forecast_np_ceiling           | 最大预期净利润       |
| forecast_eps_floor            | 最小预期每股收益     |
| forecast_eps_ceiling          | 最大预期每股收益     |
| net_profit_yoy_const_forecast | 一致预期净利润增幅   |
| forecast_ne_floor             | 最小预测归母股东权益 |
| forecast_ne_ceiling           | 最大预测归母股东权益 |

<br/>

#### 返回 {#rqdata-API-performance_forecast-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-performance_forecast-example}

- 获取单只股票过去一个报告期的预告数据

```python
[In]
performance_forecast('000001.XSHE')
[Out]
    info_date  end_date  forecast_type  forecast_description  forecast_growth_rate_floor  forecast_growth_rate_ceiling  forecast_earning_floor  forecast_earning_ceiling  forecast_np_floor  forecast_np_ceiling  forecast_eps_floor  forecast_eps_ceiling  net_profit_yoy_const_forecast
0  2016-01-21  2015-12-31  预增          累计利润              5.0                      15.0                          NaN                  NaN                      2.079206e+10      2.277225e+10          1.48              1.62                  16.0


```

- 获取多只股票过去一个报告期指定字段的预告数据

```python
[In]
performance_forecast(['000001.XSHE','000006.XSHE'],fields=['forecast_description','forecast_earning_floor'])
[Out]
        info_date end_date forecast_description forecast_earning_floor
order_book_id
000001.XSHE 2016-01-21 2015-12-31 累计利润         NaN
000006.XSHE 2020-04-09 2020-12-31 累计收入         NaN


```

- 获取单只股票指定报告期预告数据

```python
[In]
performance_forecast('000005.XSHE',end_date=20170331,fields=['forecast_description','forecast_earning_floor'])
[Out]

 info_date  end_date  forecast_description  forecast_earning_floor
0  2017-04-15  2017-03-31  累计利润              NaN

```

## A 股因子数据 {#rqdata-API-factors}

#### 单季度数据处理

除提供三大表基础财务数据外，我们还对其进行了单季度处理：

- 每日提供近 12 期的单季度数据，并以 \_mrq_n 后缀(most recent quarter) 方式在原有基础字段上进行拓展，可以使用 [get_factor](stock-mod.md#rqdata-API-get_factor) 函数调用，例如: net_profit_mrq_0 表示距离当前查询日期最近一期财报当中的单季净利润指标 ,cash_equivalent_mrq_1 表示距离当前查询日最近一期的上一期财报当中的单季货币资金指标
- 对每一期数据进行 Point-in-Time（PIT）处理，考虑如下例子：

在发布财务报告以后，上市公司可能会对数据进行修正。因此，在进行指标计算的时候，需要考虑当前时间点所能取到的最新数据，以避免未来数据的问题。该处理称为 Point-in-Time（PIT）处理。例如，考虑以下例子：

- 某一上市公司的 2018 年 4 月 1 日发布 2018 年一季度报告；
- 5 月 1 日修改了一季报净利润数据；
- 6 月 1 日再次修改净利润数据；
- 7 月 1 日发布 2018 年二季报报告
  则在 2018 年 4 月 2 日、2018 年 5 月 2 日和 2018 年 7 月 2 日计算该公司最近八期的 PIT 单季度净利润数据如下表所示：

| 2018-04-02                     | 2018-05-02                     | 2018-07-02                     |
| ------------------------------ | ------------------------------ | ------------------------------ |
| 2018 年一季度（4 月 1 日发布） | 2018 年一季度（5 月 1 日调整） | 2018 年二季度                  |
| 2017 年四季度                  | 2017 年四季度                  | 2018 年一季度（6 月 1 日调整） |
| 2017 年三季度                  | 2017 年三季度                  | 2017 年四季度                  |
| 2017 年二季度                  | 2017 年二季度                  | 2017 年三季度                  |
| 2017 年一季度                  | 2017 年一季度                  | 2017 年二季度                  |
| 2016 年四季度                  | 2016 年四季度                  | 2017 年一季度                  |
| 2016 年三季度                  | 2016 年三季度                  | 2016 年四季度                  |
| 2016 年二季度                  | 2016 年二季度                  | 2016 年三季度                  |

#### TTM 处理

TTM 是 Trailing Twelve Months 的简称，会使用过去 4 个季度的滚动财务数据进行计算，可避免某一期财报数据的偶然性。（对于来自利润表和现金流量表的数据 TTM 为滚动加和，来自资产负债表的数据 TTM 为滚动求平均）。

- 提供最近 9 期的 TTM 数据，并以 \_ttm_n 后缀的方式在原有基础字段上进行拓展，可以使用 [get_factor](stock-mod.md#rqdata-API-get_factor) 函数调用。 例如：revenue_ttm_0 代表最近一期滚动净利润数据，数值上等于 revenue_mrq_0 + revenue_mrq_1 + revenue_mrq_2 + revenue_mrq_3

::: tip 注意事项 {#rqdata-API-financial-tip}

对于利润表中的基本每股收益，目前米筐的单季度处理以及 TTM 处理都直接采用的每股收益指标相减的方式。

:::

#### LYR 处理

LYR 是 Last Year Ratio 的简称，会使用最近一期年报的数据。

- 提供最近 9 期的 LYR 数据，并以 \_lyr_n 后缀的方式在原有基础字段上进行拓展，可以使用 [get_factor](stock-mod.md#rqdata-API-get_factor) 函数调用。例如：revenue_lyr_0 代表最近一期年报的净利润数据

#### 财务衍生指标处理

- 若衍生指标定义中只涉及资产负债表字段，则提供基于最近一期财报（LF）、基于最近一期年报（LYR）、以及滚动 12 个月（TTM）三种财务数据处理逻辑
- 若衍生指标定义中涉及现金流量表或利润表字段，则提供 LYR 和 TTM 两种处理逻辑

| 处理逻辑                    | 优点                                                          | 缺点                                                                                           |
| --------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| LF, Last File               | 时效性最好                                                    | 某一期报财报数据存在较大的偶然性，且上市公司季报/中报一般没有审计要求，数据可靠性相对较差      |
| LYR, Last Year Ratio        | 上市公司年报有审计要求，数据可靠性最高                        | 时效性最差，例如在 2017 年 11 月，上市公司实际财务和经营情况可能已和 2016 年年报数据有较大差异 |
| TTM, Trailing Twelve Months | 时效性较好，滚动 4 个报告期计算，可避免某一期财报数据的偶然性 | 时效性不如 LF 处理；可靠性不如 LYR 处理                                                        |

##### 衍生指标命名规则

估值、经营、现金流、财务和成长衍生指标，经 LF、LYR、TTM 处理后的命名规则和三大基础会计科目经相同方式处理后的命名规则存在区别

| 类别                                   | 命名规则                                                                      | 范例                                             |
| -------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------ |
| 三大报表基础会计科目                   | 以 \_mrq_n ,\_lyr_n,\_ttm_n 等后缀方式在原有基础字段上进行拓展 ，带数字尾缀 n | 例如：revenue_lyr_0 代表最近一期年报的净利润数据 |
| 估值、经营、现金流、财务和成长衍生指标 | 以 \_lf ,\_lyr,\_ttm 等后缀方式在原有字段上进行拓展 ，不带数字尾缀 n          | 例如：pe_ratio_lyr 代表经 LYR 处理后的市盈率     |

### get_factor - 获取因子值 {#rqdata-API-get_factor}

```python
get_factor(order_book_ids, factor, start_date=None, end_date=None, universe=None,expect_df=True, market='cn')
```

获取股票因子值，默认返回指定因子上一个交易日的值。支持财务衍生指标、技术指标和 alpha101 因子等，例如市盈率、每股收益、KDJ、RSI、alpha101 等因子。

#### 参数 {#rqdata-API-get_factor-params}

| 参数                | 类型                                                           | 说明                                                                               |
| ------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| order_book_ids      | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                   |
| factor              | _str_ or _str list_                                            | **必填参数**，因子名称，可查询 get_all_factor_names() 得到所有有效因子字段         |
| start_date          | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期                                       |
| end_date            | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填                                       |
| ~~universe~~ 已废弃 | _str_                                                          | 指定因子计算时的股票域，米筐所有公共因子均在全市场范围计算，此参数保留为 None 即可 |
| expect_df           | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回 原有的数据结构                   |
| market              | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                |

##### 财务衍生指标说明

| 财务衍生指标   | 说明                                                            |
| -------------- | --------------------------------------------------------------- |
| 估值衍生指标   | 每天随行情变化而变化，反映上市公司估值情况（例如市盈率）        |
| 经营衍生指标   | 利润表衍生的指标，反映上市公司经营情况（例如每股收益）          |
| 现金流衍生指标 | 现金流量表衍生的指标，反映上市公司现金流情况（例如每股现金流）  |
| 财务衍生指标   | 资产负债表衍生的指标，反映上市公司权益/负债情况（例如带息债务） |
| 成长性衍生指标 | 反映上市公司经营/财务情况同比变化（例如每股净资产同比增长率）   |

#### 返回 {#rqdata-API-get_factor-return}

_pandas DataFrame_

<br/>

##### 财务衍生指标因子{#financial_indicators}

<br/>

###### 估值有关指标 {#financial_indicators-value}

_为方便阅读，可点<a href="https://assets.ricequant.com/vendor/rqdata/衍生财务指标.xlsx" target="_blank">这里</a >下载 Excel 版本的指标列表_

| 字段                              | 中文名                                | 说明                                                                                                                                                                           | 公式                                                                                                                                               |
| --------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| pe_ratio_lyr                      | 市盈率 lyr                            | 总市值 / 归属母公司净利润 lyr                                                                                                                                                  | market_cap_3 / net_profit_parent_company_lyr_0                                                                                                     |
| pe_ratio_ttm                      | 市盈率 ttm                            | 总市值 / 归属母公司净利润 ttm                                                                                                                                                  | market_cap_3 / net_profit_parent_company_ttm_0                                                                                                     |
| ep_ratio_lyr                      | 盈市率 lyr                            | 归属母公司净利润 lyr / 总市值                                                                                                                                                  | net_profit_parent_company_lyr_0 / market_cap_3                                                                                                     |
| ep_ratio_ttm                      | 盈市率 ttm                            | 连续四季度报表披露归属母公司净利润之和 / 当前股票总市值                                                                                                                        | net_profit_parent_company_ttm_0 / market_cap_3                                                                                                     |
| pcf_ratio_total_lyr               | 市现率\_总现金流 lyr                  | 总市值 /（经营活动产生的现金流量净额 lyr + 投资活动产生的现金流量净额 lyr + 筹资活动产生的现金流量净额 lyr）                                                                   | market_cap_3 / (cash_flow_from_operating_activities_lyr_0 + cash_flow_from_investing_activities_lyr_0 + cash_flow_from_financing_activities_lyr_0) |
| pcf_ratio_total_ttm               | 市现率\_总现金流 ttm                  | 总市值 /（经营活动产生的现金流量净额 ttm + 投资活动产生的现金流量净额 ttm + 筹资活动产生的现金流量净额 ttm)                                                                    | market_cap_3 / (cash_flow_from_operating_activities_ttm_0 + cash_flow_from_investing_activities_ttm_0 + cash_flow_from_financing_activities_ttm_0) |
| pcf_ratio_lyr                     | 市现率\_经营 lyr                      | 总市值 / 经营活动产生的现金流量净额 lyr                                                                                                                                        | market_cap_3 / cash_flow_from_operating_activities_lyr_0                                                                                           |
| pcf_ratio_ttm                     | 市现率\_经营 ttm                      | 总市值 / 经营活动产生的现金流量净额 ttm                                                                                                                                        | market_cap_3 / cash_flow_from_operating_activities_ttm_0                                                                                           |
| cfp_ratio_lyr                     | 现金收益率 lyr                        | 现金收益率 =（经营活动产生的现金流量净额 lyr + 投资活动产生的现金流量净额 lyr + 筹资活动产生的现金流量净额 lyr）/ 总市值                                                       | (cash_flow_from_operating_activities_lyr_0 + cash_flow_from_investing_activities_lyr_0 + cash_flow_from_financing_activities_lyr_0) / market_cap_3 |
| cfp_ratio_ttm                     | 现金收益率 ttm                        | 现金收益率 = (经营活动产生的现金流量净额 ttm + 投资活动产生的现金流量净额 ttm + 筹资活动产生的现金流量净额 ttm）/ 总市值                                                       | (cash_flow_from_operating_activities_ttm_0 + cash_flow_from_investing_activities_ttm_0 + cash_flow_from_financing_activities_ttm_0) / market_cap_3 |
| pb_ratio_lyr                      | 市净率 lyr                            | 当前股票总市值 / 归属母公司股东权益合计 lyr                                                                                                                                    | market_cap_3 / equity_parent_company_lyr_0                                                                                                         |
| pb_ratio_ttm                      | 市净率 ttm                            | 当前股票总市值 / 归属母公司股东权益合计 ttm                                                                                                                                    | market_cap_3 / equity_parent_company_ttm_0                                                                                                         |
| pb_ratio_lf                       | 市净率 lf                             | 当前股票总市值 / 归属母公司股东权益合计 mrq                                                                                                                                    | market_cap_3 / equity_parent_company_mrq_0                                                                                                         |
| pb_ratio_1_lyr                    | 市净率（股东权益剔除其他权益工具) lyr | 当前股票总市值  / (归属母公司股东权益合计-其他权益工具) lyr                                                                                                                    | market_cap_3 /( equity_parent_company_lyr_0-other_equity_instruments_lyr_0)                                                                        |
| pb_ratio_1_ttm                    | 市净率( 股东权益剔除其他权益工具）ttm | 当前股票总市值  / （归属母公司股东权益合计-其他权益工具）ttm                                                                                                                   | market_cap_3 / (equity_parent_company_ttm_0-other_equity_instruments_ttm_0)                                                                        |
| pb_ratio_1_lf                     | 市净率（股东权益剔除其他权益工具） lf | 当前股票总市值  / （归属母公司股东权益合计-其他权益工具） mrq                                                                                                                  | market_cap_3 /(equity_parent_company_mrq_0-other_equity_instruments_mrq_0)                                                                         |
| book_to_market_ratio_lyr          | 账面市值比 lyr                        | 归属母公司股东权益合计 lyr / 总市值                                                                                                                                            | equity_parent_company_lyr_0 / market_cap_3                                                                                                         |
| book_to_market_ratio_ttm          | 账面市值比 ttm                        | 归属母公司股东权益合计 ttm / 总市值                                                                                                                                            | equity_parent_company_ttm_0 / market_cap_3                                                                                                         |
| book_to_market_ratio_lf           | 账面市值比 lf                         | 归属母公司股东权益合计 mrq / 总市值                                                                                                                                            | equity_parent_company_mrq_0 / market_cap_3                                                                                                         |
| dividend_yield_ttm                | 股息率 ttm                            | 过去12个月中包含的除权除息日的派现(含税10派X元)(人民币)之和/10 / 未复权收盘价                                                                                                                                      | dividend_ttm / close_price                                                                                                                         |
| peg_ratio_lyr                     | PEG 值 lyr                            | 市盈率 lyr / 公司过去一年归属母公司净利润增长率平均值 \*100 lyr                                                                                                                | pe_ratio_lyr / (100\*(net_profit_parent_company_lyr_0 - net_profit_parent_company_lyr_1) / net_profit_parent_company_lyr_1)                        |
| peg_ratio_ttm                     | PEG 值 ttm                            | 市盈率 ttm / 公司过去一年归属母公司净利润增长率平均值\*100 ttm                                                                                                                 | pe_ratio_ttm / (100\*(net_profit_parent_company_ttm_0 - net_profit_parent_company_ttm_4) / net_profit_parent_company_ttm_4)                        |
| ps_ratio_lyr                      | 市销率 lyr                            | 总市值 / 营利收入 lyr                                                                                                                                                          | market_cap_3 / operating_revenue_lyr_0                                                                                                             |
| ps_ratio_ttm                      | 市销率 ttm                            | 总市值 / 营利收入 ttm                                                                                                                                                          | market_cap_3 / operating_revenue_ttm_0                                                                                                             |
| sp_ratio_lyr                      | 销售收益率 lyr                        | 营利收入 lyr / 总市值                                                                                                                                                          | operating_revenue_lyr_0 / market_cap_3                                                                                                             |
| sp_ratio_ttm                      | 销售收益率 ttm                        | 营利收入 ttm / 总市值                                                                                                                                                          | operating_revenue_ttm_0 / market_cap_3                                                                                                             |
| market_cap                        | 总市值 1                              | 总市值 = 总股本 \* A 股未复权收盘价                                                                                                                                            |                                                                                                                                                    |
| market_cap_2                      | 流通股总市值 （不支持科创板）         | 流通股总市值 = 流通股本 \* A 股未复权收盘价                                                                                                                                    |                                                                                                                                                    |
| market_cap_3                      | 总市值                                | 总市值= 总股本 \* A 股未复权收盘价 此处采用了 PIT 处理方式，即公告公布之后才对股本数据进行调节，而不对截止日期（例如，半年报截止日期为 06-30）至公布日期之间的数据进行覆盖更新 | total \* close_price                                                                                                                               |
| a_share_market_val_3              | A 股市值                              | A 股市值 = A 股股本 x A 股未复权收盘价 此处股本采用 PIT 处理方式，股本处理方式同 market_cap_3 说明部分                                                                         | total_a \* close_price                                                                                                                             |
| a_share_market_val_in_circulation | 流通 A 股市值                         | 流通 A 股市值 = 流通 A 股 \* A 股未复权收盘价 此处股本采用 PIT 处理方式，股本处理方式同 market_cap_3 说明部分                                                                  | circulation_a \* close_price                                                                                                                       |
| ev_lyr                            | 企业价值 lyr                          | 总市值 + 负债合计 lyr                                                                                                                                                          | market_cap_3 + total_liabilities_lyr_0                                                                                                             |
| ev_ttm                            | 企业价值 ttm                          | 总市值 + 负债合计 ttm                                                                                                                                                          | market_cap_3 + total_liabilities_ttm_0                                                                                                             |
| ev_lf                             | 企业价值 lf                           | 总市值 + 负债合计 mrq                                                                                                                                                          | market_cap_3 + total_liabilities_mrq_0                                                                                                             |
| ev_no_cash_lyr                    | 企业价值(不含货币资金)lyr             | 总市值 + 负债合计 lyr - 货币资金 lyr                                                                                                                                           | market_cap_3 + total_liabilities_lyr_0 - cash_equivalent_lyr_0                                                                                     |
| ev_no_cash_ttm                    | 企业价值(不含货币资金)ttm             | 总市值 + 负债合计 ttm - 货币资金 ttm                                                                                                                                           | market_cap_3 + total_liabilities_ttm_0 - cash_equivalent_ttm_0                                                                                     |
| ev_no_cash_lf                     | 企业价值(不含货币资金)lf              | 总市值 + 负债合计 mrq - 货币资金 mrq                                                                                                                                           | market_cap_3 + total_liabilities_mrq_0 - cash_equivalent_mrq_0                                                                                     |
| ev_to_ebitda_lyr                  | 企业倍数 lyr                          | 企业价值 lyr / 息税折旧摊销前利润 lyr                                                                                                                                          | ev_lyr / ebitda_lyr                                                                                                                                |
| ev_to_ebitda_ttm                  | 企业倍数 ttm                          | 企业价值 ttm / 息税折旧摊销前利润 ttm                                                                                                                                          | ev_ttm / ebitda_ttm                                                                                                                                |
| ev_no_cash_to_ebit_lyr            | 企业倍数(不含货币资金)lyr             | 企业价值 lyr / 息税折旧摊销前利润 lyr                                                                                                                                          | ev_no_cash_lyr / ebitda_lyr                                                                                                                        |
| ev_no_cash_to_ebit_ttm            | 企业倍数(不含货币资金)ttm             | 企业价值 ttm / 息税折旧摊销前利润 ttm                                                                                                                                          | ev_no_cash_ttm / ebitda_ttm                                                                                                                        |

###### 经营衍生指标表 {#financial_indicators-operation}

_为方便阅读，可点<a href="https://assets.ricequant.com/vendor/rqdata/衍生财务指标.xlsx" target="_blank">这里</a >下载 Excel 版本的指标列表_

| 字段                                          | 中文名                                             | 说明                                                                                                                     | 公式                                                                                                                                                                                      |
| --------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| diluted_earnings_per_share_lyr                | 摊薄每股收益 lyr                                   | 归属母公司净利润 lyr / 该报告期末普通股总股本                                                                            | net_profit_parent_company_lyr_0/ total_shares                                                                                                                                             |
| diluted_earnings_per_share_ttm                | 摊薄每股收益 ttm                                   | 归属母公司净利润 ttm / 该报告期末普通股总股本                                                                            | net_profit_parent_company_ttm_0 / total_shares                                                                                                                                            |
| adjusted_earnings_per_share_lyr               | 基本每股收益\_扣除 lyr                             | 扣除非经常性损益的净利润 lyr / 普通股加权股本 lyr                                                                        | adjusted_net_profit_lyr_0 / weighted_common_stock_lyr                                                                                                                                     |
| adjusted_earnings_per_share_ttm               | 基本每股收益\_扣除 ttm                             | 扣除非经常性损益的净利润 ttm / 普通股加权股本 ttm                                                                        | adjusted_net_profit_ttm_0 / weighted_common_stock_ttm                                                                                                                                     |
| adjusted_fully_diluted_earnings_per_share_lyr | 稀释每股收益\_扣除 lyr                             | 扣除非经常损益的净利润 lyr / 稀释普通股 lyr                                                                              | adjusted_net_profit_lyr_0 / diluted_common_stock_lyr                                                                                                                                      |
| adjusted_fully_diluted_earnings_per_share_ttm | 稀释每股收益\_扣除 ttm                             | 扣除非经常损益的净利润 ttm / 稀释普通股 ttm                                                                              | adjusted_net_profit_ttm_0 / diluted_common_stock_ttm                                                                                                                                      |
| inc_adjusted_net_profit_lyr                   | 扣除非经常损益归属母公司股东的净利润同比增长率 lyr | 扣除非经营性损益归属母公司股东净利润 lyr / 去年扣除非经营性损益归属母公司股东净利润 lyr - 1                              | (net_profit_deduct_non_recurring_pnl_lyr_0 / net_profit_deduct_non_recurring_pnl_lyr_1) -1                                                                                                |
| inc_adjusted_net_profit_ttm                   | 扣除非经常损益归属母公司股东的净利润同比增长率 ttm | 扣除非经营性损益归属母公司股东净利润 ttm / 去年扣除非经营性损益归属母公司股东净利润 ttm - 1                              | (net_profit_deduct_non_recurring_pnl_ttm_0 / net_profit_deduct_non_recurring_pnl_ttm_4) -1                                                                                                |
| weighted_common_stock_lyr                     | 普通股加权股本 lyr                                 | 归属于母公司所有者的净利润 lyr / 基本每股收益 lyr                                                                        | net_profit_parent_company_lyr_0 / basic_earnings_per_share_lyr_0                                                                                                                          |
| weighted_common_stock_ttm                     | 普通股加权股本 ttm                                 | 归属于母公司所有者的净利润 ttm / 基本每股收益 ttm                                                                        | net_profit_parent_company_ttm_0 / basic_earnings_per_share_ttm_0                                                                                                                          |
| diluted_common_stock_lyr                      | 稀释普通股 lyr                                     | 归属于母公司所有者的净利润 lyr / 稀释每股收益 lyr                                                                        | net_profit_parent_company_lyr_0/fully_diluted_earnings_per_share_lyr_0                                                                                                                    |
| diluted_common_stock_ttm                      | 稀释普通股 ttm                                     | 归属于母公司所有者的净利润 ttm / 稀释每股收益 ttm                                                                        | net_profit_parent_company_ttm_0/fully_diluted_earnings_per_share_ttm_0                                                                                                                    |
| operating_total_revenue_per_share_lyr         | 每股营业总收入 lyr                                 | 营业总收入 lyr / 总股本                                                                                                  | revenue_lyr_0 / total_shares                                                                                                                                                              |
| operating_total_revenue_per_share_ttm         | 每股营业总收入 ttm                                 | 营业总收入 ttm / 总股本                                                                                                  | revenue_ttm_0 / total_shares                                                                                                                                                              |
| operating_revenue_per_share_lyr               | 每股营业收入 lyr                                   | 营业收入 lyr / 总股本                                                                                                    | operating_revenue_lyr_0 /total_shares                                                                                                                                                     |
| operating_revenue_per_share_ttm               | 每股营业收入 ttm                                   | 营业收入 ttm / 总股本                                                                                                    | operating_revenue_ttm_0 /total_shares                                                                                                                                                     |
| ebit_lyr                                      | 息税前利润 lyr                                     | 利润总额 lyr + 利息支出(财务费用) lyr - 利息收入(财务费用) lyr                                                           | profit_before_tax_lyr_0 + financing_interest_expense_lyr_0 - financing_interest_income_lyr_0                                                                                              |
| ebit_ttm                                      | 息税前利润 ttm                                     | 利润总额 ttm + 利息支出(财务费用) ttm - 利息收入(财务费用) ttm                                                           | profit_before_tax_ttm_0 + financing_interest_expense_ttm_0 - financing_interest_income_ttm_0                                                                                              |
| ebitda_lyr                                    | 息税折旧摊销前利润 lyr                             | 息税前利润 lyr ＋ 固定资产折旧 lyr ＋ 无形资产摊销 lyr ＋ 长期待摊费用摊销 lyr                                           | (ebit_lyr + fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_lyr_0 + deferred_expense_amort_lyr_0)                                                                          |
| ebitda_ttm                                    | 息税折旧摊销前利润 ttm                             | 息税前利润 ttm + 固定资产折旧 ttm ＋ 无形资产摊销 ttm ＋ 长期待摊费用摊销 ttm                                            | (ebit_ttm + fixed_asset_depreciation_ttm_0 + intangible_asset_amortization_ttm_0 + deferred_expense_amort_ttm_0)                                                                          |
| ebit_per_share_lyr                            | 每股息税前利润 lyr                                 | 息税前利润 lyr / 总股本                                                                                                  | ebit_lyr / total_shares                                                                                                                                                                   |
| ebit_per_share_ttm                            | 每股息税前利润 ttm                                 | 息税前利润 ttm / 总股本                                                                                                  | ebit_ttm / total_shares                                                                                                                                                                   |
| return_on_equity_lyr                          | 净资产收益率 lyr                                   | 归属母公司净利润 lyr \* 2 /（归属母公司股东权益合计 lyr + 上期报表披露归属母公司股东权益合计 lyr）                       | net_profit_parent_company_lyr_0 \* 2 / (equity_parent_company_lyr_0 + equity_parent_company_lyr_1)                                                                                        |
| return_on_equity_ttm                          | 净资产收益率 ttm                                   | 归属母公司净利润 ttm \* 2 / (归属母公司股东权益合计 ttm + 上期报表披露归属母公司股东权益合计 ttm)                        | net_profit_parent_company_ttm_0 \* 2 / (equity_parent_company_ttm_0 + equity_parent_company_ttm_1)                                                                                        |
| return_on_equity_diluted_lyr                  | 摊薄净资产收益率 lyr                               | 归属母公司净利润 lyr / 归属母公司股东权益合计 lyr                                                                        | net_profit_parent_company_lyr_0 / equity_parent_company_lyr_0                                                                                                                             |
| return_on_equity_diluted_ttm                  | 摊薄净资产收益率 ttm                               | 归属母公司净利润 ttm / 归属母公司股东权益合计 ttm                                                                        | net_profit_parent_company_ttm_0 / equity_parent_company_ttm_0                                                                                                                             |
| adjusted_return_on_equity_lyr                 | 净资产收益率\_扣除 lyr                             | 扣除非经常性损益后的归属母公司净利润 lyr \* 2 /（归属母公司股东权益合计 lyr + 上期报表披露的归属母公司股东权益合计 lyr） | (net_profit_parent_company_lyr_0 - non_recurring_pnl_lyr_0)\* 2 / (equity_parent_company_lyr_0 + equity_parent_company_lyr_1)                                                             |
| adjusted_return_on_equity_ttm                 | 净资产收益率\_扣除 ttm                             | 扣除非经常性损益后的归属母公司净利润 ttm \* 2/ （归属母公司股东权益合计 ttm + 上期报表披露的归属母公司股东权益合计 ttm） | (net_profit_parent_company_ttm_0 - non_recurring_pnl_ttm_0)\* 2 / (equity_parent_company_ttm_0+equity_parent_company_ttm_1))                                                              |
| adjusted_return_on_equity_diluted_lyr         | 摊薄净资产收益率\_扣除 lyr                         | 扣除非经常性损益后归属母公司的净利润 lyr / 归属母公司的股东权益合计 lyr                                                  | (net_profit_parent_company_lyr_0 - non_recurring_pnl_lyr_0) / equity_parent_company_lyr_0                                                                                                 |
| adjusted_return_on_equity_diluted_ttm         | 摊薄净资产收益率\_扣除 ttm                         | 扣除非经常性损益后归属母公司的净利润 ttm / 归属母公司的股东权益合计 ttm                                                  | (net_profit_parent_company_ttm_0 - non_recurring_pnl_ttm_0) / equity_parent_company_ttm_0                                                                                                 |
| return_on_asset_lyr                           | 总资产报酬率 lyr                                   | 息税前利润 lyr / 总资产 lyr                                                                                              | ebit_lyr / total_assets_lyr_0                                                                                                                                                             |
| return_on_asset_ttm                           | 总资产报酬率 ttm                                   | 息税前利润 ttm / 总资产 ttm                                                                                              | ebit_ttm / total_assets_ttm_0                                                                                                                                                             |
| return_on_asset_net_profit_lyr                | 总资产净利率 lyr                                   | 净利润 lyr / 总资产 lyr                                                                                                  | net_profit_lyr_0 / total_assets_lyr_0                                                                                                                                                     |
| return_on_asset_net_profit_ttm                | 总资产净利率 ttm                                   | 净利润 ttm / 总资产 ttm                                                                                                  | net_profit_ttm_0 / total_assets_ttm_0                                                                                                                                                     |
| return_on_invested_capital_lyr                | 投入资本回报率 lyr                                 | (净利润 lyr + 财务费用 lyr）/（资产总计 lyr - 流动负债 lyr + 应付票据 lyr + 短期借款 lyr + 一年内到期的非流动负债 lyr）  | (net_profit_lyr_0 + financing_expense_lyr_0) / (total_assets_lyr_0 - current_liabilities_lyr_0 + notes_payable_lyr_0 + short_term_loans_lyr_0 + non_current_liability_due_one_year_lyr_0) |
| return_on_invested_capital_ttm                | 投入资本回报率 ttm                                 | （净利润 ttm + 财务费用 ttm）/（资产总计 ttm - 流动负债 ttm + 应付票据 ttm + 短期借款 ttm + 一年内到期的非流动负债 ttm） | (net_profit_ttm_0 + financing_expense_ttm_0) / (total_assets_ttm_0 - current_liabilities_ttm_0 + notes_payable_ttm_0 + short_term_loans_ttm_0 + non_current_liability_due_one_year_ttm_0) |
| net_profit_margin_lyr                         | 销售净利率 lyr                                     | 净利润 lyr / 营业收入 lyr                                                                                                | net_profit_lyr_0 / operating_revenue_lyr_0                                                                                                                                                |
| net_profit_margin_ttm                         | 销售净利率 ttm                                     | 净利润 ttm / 营业收入 ttm                                                                                                | net_profit_ttm_0 / operating_revenue_ttm_0                                                                                                                                                |
| gross_profit_margin_lyr                       | 销售毛利率 lyr                                     | (营业收入 lyr - 营业成本 lyr）/ 营业收入 lyr                                                                             | (operating_revenue_lyr_0 - cost_of_goods_sold_lyr_0) / operating_revenue_lyr_0                                                                                                            |
| gross_profit_margin_ttm                       | 销售毛利率 ttm                                     | (营业收入 ttm - 营业成本 ttm）/ 营业收入 ttm                                                                             | (operating_revenue_ttm_0 - cost_of_goods_sold_ttm_0) / operating_revenue_ttm_0                                                                                                            |
| cost_to_sales_lyr                             | 销售成本率 lyr                                     | 营业成本 lyr / 营业收入 lyr                                                                                              | cost_of_goods_sold_lyr_0 / operating_revenue_lyr_0                                                                                                                                        |
| cost_to_sales_ttm                             | 销售成本率 ttm                                     | 营业成本 ttm / 营业收入 ttm                                                                                              | cost_of_goods_sold_ttm_0 / operating_revenue_ttm_0                                                                                                                                        |
| net_profit_to_revenue_lyr                     | 经营净利率 lyr                                     | 净利润 lyr / 营业总收入 lyr                                                                                              | net_profit_lyr_0 / revenue_lyr_0                                                                                                                                                          |
| net_profit_to_revenue_ttm                     | 经营净利率 ttm                                     | 净利润 ttm / 营业总收入 ttm                                                                                              | net_profit_ttm_0 / revenue_ttm_0                                                                                                                                                          |
| profit_from_operation_to_revenue_lyr          | 营业利润率 lyr                                     | 营业利润 lyr / 营业总收入 lyr                                                                                            | profit_from_operation_lyr_0 / revenue_lyr_0                                                                                                                                               |
| profit_from_operation_to_revenue_ttm          | 营业利润率 ttm                                     | 营业利润 ttm / 营业总收入 ttm                                                                                            | profit_from_operation_ttm_0 / revenue_ttm_0                                                                                                                                               |
| ebit_to_revenue_lyr                           | 税前收益率 lyr                                     | 息税前利润 lyr / 营业总收入 lyr                                                                                          | ebit_lyr / revenue_lyr_0                                                                                                                                                                  |
| ebit_to_revenue_ttm                           | 税前收益率 ttm                                     | 息税前利润 ttm / 营业总收入 ttm                                                                                          | ebit_ttm / revenue_ttm_0                                                                                                                                                                  |
| expense_to_revenue_lyr                        | 经营成本率 lyr                                     | 营业总成本 lyr / 营业总收入 lyr                                                                                          | total_expense_lyr_0 / revenue_lyr_0                                                                                                                                                       |
| expense_to_revenue_ttm                        | 经营成本率 ttm                                     | 营业总成本 ttm / 营业总收入 ttm                                                                                          | total_expense_ttm_0 / revenue_ttm_0                                                                                                                                                       |
| operating_profit_to_profit_before_tax_lyr     | 经营活动净收益与利润总额之比 lyr                   | (营业总收入 lyr－营业总成本 lyr) / 利润总额 lyr                                                                          | (revenue_lyr_0 - total_expense_lyr_0) / profit_before_tax_lyr_0                                                                                                                           |
| operating_profit_to_profit_before_tax_ttm     | 经营活动净收益与利润总额之比 ttm                   | (营业总收入 ttm－营业总成本 ttm) / 利润总额 ttm                                                                          | (revenue_ttm_0 - total_expense_ttm_0) / profit_before_tax_ttm_0                                                                                                                           |
| investment_profit_to_profit_before_tax_lyr    | 价值变动净收益与利润总额之比 lyr                   | (投资收益 lyr + 公允价值变动净收益 lyr + 兑汇损益 lyr - 对联营合营公司的投资收益 lyr) / 利润总额 lyr                     | （investment_income_lyr_0 + fair_value_change_income_lyr_0 + exchange_gains_or_losses_lyr_0 - invest_income_associates_lyr_0） / profit_before_tax_lyr_0                                  |
| investment_profit_to_profit_before_tax_ttm    | 价值变动净收益与利润总额之比 ttm                   | (投资收益 ttm + 公允价值变动净收益 ttm + 兑汇损益 ttm - 对联营合营公司的投资收益 ttm) / 利润总额 ttm                     | （investment_income_ttm_0 + fair_value_change_income_ttm_0 + exchange_gains_or_losses_ttm_0 - invest_income_associates_ttm_0） / profit_before_tax_ttm_0                                  |
| non_operating_profit_to_profit_before_tax_lyr | 营业外收支净额与利润总额之比 lyr                   | 营业外收支净额 lyr / 利润总额 lyr                                                                                        | (non_operating_revenue_lyr_0 - non_operating_expense_lyr_0) / profit_before_tax_lyr_0                                                                                                     |
| non_operating_profit_to_profit_before_tax_ttm | 营业外收支净额与利润总额之比 ttm                   | 营业外收支净额 ttm / 利润总额 ttm                                                                                        | (non_operating_revenue_ttm_0 - non_operating_expense_ttm_0) / profit_before_tax_ttm_0                                                                                                     |
| income_tax_to_profit_before_tax_lyr           | 所得税与利润总额之比 lyr                           | 所得税 lyr / 利润总额 lyr                                                                                                | income_tax_lyr_0 / profit_before_tax_lyr_0                                                                                                                                                |
| income_tax_to_profit_before_tax_ttm           | 所得税与利润总额之比 ttm                           | 所得税 ttm / 利润总额 ttm                                                                                                | income_tax_ttm_0 / profit_before_tax_ttm_0                                                                                                                                                |
| adjusted_profit_to_total_profit_lyr           | 扣除非经常损益后的净利润与净利润之比 lyr           | 扣除非经常性损益后的净利润 lyr / 净利润 lyr                                                                              | adjusted_net_profit_lyr_0 / net_profit_lyr_0                                                                                                                                              |
| adjusted_profit_to_total_profit_ttm           | 扣除非经常损益后的净利润与净利润之比 ttm           | 扣除非经常性损益后的净利润 ttm / 净利润 ttm                                                                              | adjusted_net_profit_ttm_0 / net_profit_ttm_0                                                                                                                                              |
| ebitda_to_debt_lyr                            | 息税折旧摊销前利润/负债总计 lyr                    | 息税折旧摊销前利润 lyr / 负债总计 lyr                                                                                    | ebitda_lyr / total_liabilities_lyr_0                                                                                                                                                      |
| ebitda_to_debt_ttm                            | 息税折旧摊销前利润/负债总计 ttm                    | 息税折旧摊销前利润 ttm / 负债总计 ttm                                                                                    | ebitda_ttm / total_liabilities_ttm_0                                                                                                                                                      |
| account_payable_turnover_rate_lyr             | 应付账款周转率 lyr                                 | 营业成本 lyr / 最新年报披露应付账款 lyr                                                                                  | cost_of_goods_sold_lyr_0 / accts_payable_lyr_0                                                                                                                                            |
| account_payable_turnover_rate_ttm             | 应付账款周转率 ttm                                 | 营业成本 ttm /当期报表披露应付账款 ttm                                                                                   | cost_of_goods_sold_ttm_0 / accts_payable_ttm_0                                                                                                                                            |
| account_payable_turnover_days_lyr             | 应付账款周转天数 lyr                               | 360 / 应付账款周转率 lyr                                                                                                 | 360 / account_payable_turnover_rate_lyr                                                                                                                                                   |
| account_payable_turnover_days_ttm             | 应付账款周转天数 ttm                               | 360 / 应付账款周转率 ttm                                                                                                 | 360 / account_payable_turnover_rate_ttm                                                                                                                                                   |
| account_receivable_turnover_rate_lyr          | 应收账款周转率 lyr                                 | 营业收入 lyr / 最新年报披露应收账款净额 lyr                                                                              | operating_revenue_lyr_0 / net_accts_receivable_lyr_0                                                                                                                                      |
| account_receivable_turnover_rate_ttm          | 应收账款周转率 ttm                                 | 营业收入 ttm / 当期报表披露应收账款净额 ttm                                                                              | operating_revenue_ttm_0 / net_accts_receivable_ttm_0                                                                                                                                      |
| account_receivable_turnover_days_lyr          | 应收账款周转天数 lyr                               | 360 / 应收账款周转率 lyr                                                                                                 | 360 / account_receivable_turnover_rate_lyr                                                                                                                                                |
| account_receivable_turnover_days_ttm          | 应收账款周转天数 ttm                               | 360 / 应收账款周转率 ttm                                                                                                 | 360 / account_receivable_turnover_rate_ttm                                                                                                                                                |
| inventory_turnover_lyr                        | 存货周转率 lyr                                     | 营业成本 lyr / 本期年报披露存货 lyr                                                                                      | cost_of_goods_sold_lyr_0 / inventory_lyr_0                                                                                                                                                |
| inventory_turnover_ttm                        | 存货周转率 ttm                                     | 营业成本 ttm / 当期报表披露存货 ttm                                                                                      | cost_of_goods_sold_ttm_0 / inventory_ttm_0                                                                                                                                                |
| current_asset_turnover_lyr                    | 流动资产周转率 lyr                                 | 营业收入 lyr /最新年报披露流动资产总计 lyr                                                                               | operating_revenue_lyr_0 / current_assets_lyr_0                                                                                                                                            |
| current_asset_turnover_ttm                    | 流动资产周转率 ttm                                 | 营业收入 ttm / 当期报表披露流动资产总计 ttm                                                                              | operating_revenue_ttm_0 / current_assets_ttm_0                                                                                                                                            |
| fixed_asset_turnover_lyr                      | 固定资产周转率 lyr                                 | 营业收入 lyr /最新年报披露固定资产总计 lyr                                                                               | operating_revenue_lyr_0 / total_fixed_assets_lyr_0                                                                                                                                        |
| fixed_asset_turnover_ttm                      | 固定资产周转率 ttm                                 | 营业收入 ttm / 当期报表披露固定资产总计 ttm                                                                              | operating_revenue_ttm_0 / total_fixed_assets_ttm_0                                                                                                                                        |
| total_asset_turnover_lyr                      | 总资产周转率 lyr                                   | 营业收入 lyr /（最新年报披露总资产 lyr                                                                                   | operating_revenue_lyr_0 / total_assets_lyr_0                                                                                                                                              |
| total_asset_turnover_ttm                      | 总资产周转率 ttm                                   | 营业收入 ttm / 当期报表披露总资产 ttm                                                                                    | operating_revenue_ttm_0 / total_assets_ttm_0                                                                                                                                              |
| du_profit_margin_lyr                          | 净利率(杜邦分析）lyr                               | 净利润 lyr / 利润总额 lyr                                                                                                | net_profit_lyr_0 / profit_before_tax_lyr_0                                                                                                                                                |
| du_profit_margin_ttm                          | 净利率(杜邦分析）ttm                               | 净利润 ttm / 利润总额 ttm                                                                                                | net_profit_ttm_0 / profit_before_tax_ttm_0                                                                                                                                                |
| du_return_on_equity_lyr                       | 净资产收益率 ROE(杜邦分析)lyr                      | 净利率(杜邦分析)lyr *总资产周转率 lyr*权益乘数(杜邦分析)lyr                                                              | du_profit_margin_lyr*total_asset_turnover_lyr* du_equity_multiplier_lyr                                                                                                                   |
| du_return_on_equity_ttm                       | 净资产收益率 ROE(杜邦分析)ttm                      | 净利率(杜邦分析)ttm *总资产周转率 ttm*权益乘数(杜邦分析)ttm                                                              | du_profit_margin_ttm*total_asset_turnover_ttm* du_equity_multiplier_ttm                                                                                                                   |
| du_return_on_sales_lyr                        | 息税前利润/营业总收入 lyr                          | 息税前利润 lyr / 营业总收入 lyr                                                                                          | ebit_lyr / revenue_lyr_0                                                                                                                                                                  |
| du_return_on_sales_ttm                        | 息税前利润/营业总收入 ttm                          | 息税前利润 ttm / 营业总收入 ttm                                                                                          | ebit_ttm / revenue_ttm_0                                                                                                                                                                  |
| income_from_main_operations_lyr               | 主营业务利润 lyr                                   | 营业收入 lyr - 营业成本 lyr - 营业税金及附加 lyr                                                                         | operating_revenue_lyr_0 - cost_of_goods_sold_lyr_0 - sales_tax_lyr_0                                                                                                                      |
| income_from_main_operations_ttm               | 主营业务利润 ttm                                   | 营业收入 ttm - 营业成本 ttm - 营业税金及附加 ttm                                                                         | operating_revenue_ttm_0 - cost_of_goods_sold_ttm_0 - sales_tax_ttm_0                                                                                                                      |
| time_interest_earned_ratio_lyr                | 利息保障倍数 lyr                                   | 息税前利润 lyr / (利息支出(财务费用) lyr - 利息收入(财务费用) lyr)                                                       | ebit_lyr / (financing_interest_expense_lyr_0 - financing_interest_income_lyr_0)                                                                                                           |
| time_interest_earned_ratio_ttm                | 利息保障倍数 ttm                                   | 息税前利润 ttm / (利息支出(财务费用) ttm - 利息收入(财务费用) ttm)                                                       | ebit_ttm / (financing_interest_expense_ttm_0 - financing_interest_income_ttm_0)                                                                                                           |
| equity_turnover_ratio_lyr                     | 股东权益周转率 lyr                                 | 营业收入 lyr / 归属母公司股东权益合计 lyr                                                                                | operating_revenue_lyr_0 / equity_parent_company_lyr_0                                                                                                                                     |
| equity_turnover_ratio_ttm                     | 股东权益周转率 ttm                                 | 营业收入 ttm / 归属母公司股东权益合计 ttm                                                                                | operating_revenue_ttm_0 / equity_parent_company_ttm_0                                                                                                                                     |
| operating_cycle_lyr                           | 营业周期 lyr                                       | 应收账款周转天数 lyr + 存货周转天数 lyr                                                                                  | account_receivable_turnover_days_lyr + 360/inventory_turnover_lyr                                                                                                                         |
| operating_cycle_ttm                           | 营业周期 ttm                                       | 应收账款周转天数 ttm + 存货周转天数 ttm                                                                                  | account_receivable_turnover_days_ttm + 360/inventory_turnover_ttm                                                                                                                         |
| average_payment_period_lyr                    | 应付账款付款期 lyr                                 | 平均应付账款 lyr / 营业成本 lyr / 360                                                                                    | accts_payable_lyr_0 / cost_of_goods_sold_lyr_0 / 360                                                                                                                                      |
| average_payment_period_ttm                    | 应付账款付款期 ttm                                 | 平均应付账款 ttm / 营业成本 ttm / 360                                                                                    | accts_payable_ttm_0 / cost_of_goods_sold_ttm_0 / 360                                                                                                                                      |
| cash_conversion_cycle_lyr                     | 现金转换周期 lyr                                   | 营业周期 lyr - 应付账款付款期 lyr                                                                                        | operating_cycle_lyr_0 - average_payment_period_lyr_0                                                                                                                                      |
| cash_conversion_cycle_ttm                     | 现金转换周期 ttm                                   | 营业周期 ttm - 应付账款付款期 ttm                                                                                        | operating_cycle_ttm_0 - average_payment_period_ttm_0                                                                                                                                      |

###### 现金流衍生指标 {#financial_indicators-cash_flow}

_为方便阅读，可点<a href="https://assets.ricequant.com/vendor/rqdata/衍生财务指标.xlsx" target="_blank">这里</a >下载 Excel 版本的指标列表_

| 字段                                  | 中文名                                  | 说明                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | 公式                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| cash_flow_per_share_lyr               | 每股现金流 lyr                          | （经营活动产生的现金流量净额 lyr + 投资活动产生的现金流量净额 lyr + 筹资活动产生的现金流量净额 lyr）/ 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | (cash_flow_from_operating_activities_lyr_0 + cash_flow_from_investing_activities_lyr_0 + cash_flow_from_financing_activities_lyr_0) / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| cash_flow_per_share_ttm               | 每股现金流 ttm                          | （经营活动产生的现金流量净额 ttm + 投资活动产生的现金流量净额 ttm + 筹资活动产生的现金流量净额 ttm）/ 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | (cash_flow_from_operating_activities_ttm_0 + cash_flow_from_investing_activities_ttm_0 + cash_flow_from_financing_activities_ttm_0) / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| operating_cash_flow_per_share_lyr     | 每股经营现金流 lyr                      | 经营活动产生的现金流量净额 lyr / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | cash_flow_from_operating_activities_lyr_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| operating_cash_flow_per_share_ttm     | 每股经营现金流 ttm                      | 经营活动产生的现金流量净额 ttm / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | cash_flow_from_operating_activities_ttm_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| fcff_lyr                              | 企业自由现金流量 lyr                    | 归属于母公司所有者的净利润 lyr ＋ 资产减值准备 lyr ＋ 固定资产折旧 lyr ＋ 无形资产摊销 lyr ＋ 长期待摊费用摊销 lyr + 利息费用 lyr \*（1 － 所得税 lyr / 利润总额 lyr）－（本期固定资产合计 lyr－上期固定资产合计 lyr ＋ 固定资产折旧 lyr）－营运资本变动额 lyr 其中：利息费用=利息支出(财务费用)-利息收入(财务费用)，如果企业未披露利息收入(财务费用)和利息支出(财务费用)，则“利息费用=财务费用”；营运资本变动额＝期末[（流动资产合计－货币资金）－(流动负债合计－应付票据－一年内到期的非流动负债）]－期初[（流动资产合计－货币资金）－(流动负债合计－应付票据－一年内到期的非流动负债）   | net_profit_parent_company_lyr_0 + assets_depreciation_reserves_lyr_0 + fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_lyr_0 + deferred_expense_amortization_lyr_0 + (financing_interest_expense_lyr_0 - financing_interest_income_lyr_0) \* (1 - income_tax_lyr_0 / profit_before_tax_lyr_0) - (total_fixed_assets_lyr_0 - total_fixed_assets_lyr_1 + fixed_asset_depreciation_lyr_0) - (current_assets_lyr_0 - cash_equivalent_lyr_0 - current_liabilities_lyr_0 + notes_payable_lyr_0 + non_current_liability_due_one_year_lyr_0 - (current_assets_lyr_1 - cash_equivalent_lyr_1 - current_liabilities_lyr_1 + notes_payable_lyr_1 + non_current_liability_due_one_year_lyr_1))                      |
| fcff_ttm                              | 企业自由现金流量 ttm                    | 归属于母公司所有者的净利润 ttm ＋ 资产减值准备 ttm ＋ 固定资产折旧 ttm ＋ 无形资产摊销 ttm ＋ 长期待摊费用摊销 ttm + 利息费用 ttm \*（1 － 所得税 ttm / 利润总额 ttm）－（本期固定资产合计 ttm－上期固定资产合计 ttm ＋ 固定资产折旧 ttm）－营运资本变动额 ttm 其中：利息费用=利息支出(财务费用)-利息收入(财务费用)，如果企业未披露利息收入(财务费用）和利息支出（财务费用)，则“利息费用=财务费用”；营运资本变动额＝期末[（流动资产合计－货币资金）－(流动负债合计－应付票据－一年内到期的非流动负债）]－期初[（流动资产合计－货币资金）－(流动负债合计－应付票据－一年内到期的非流动负债） | net_profit_parent_company_ttm_0 + assets_depreciation_reserves_ttm_0 + fixed_asset_depreciation_ttm_0 + intangible_asset_amortization_ttm_0 + deferred_expense_amortization_ttm_0 + (financing_interest_expense_ttm_0 - financing_interest_income_ttm_0) \* (1 - income_tax_ttm_0 / profit_before_tax_ttm_0) - (total_fixed_assets_ttm_0 - total_fixed_assets_ttm_1 + fixed_asset_depreciation_ttm_0) - (current_assets_ttm_0 - cash_equivalent_ttm_0 - current_liabilities_ttm_0 + notes_payable_ttm_0 + non_current_liability_due_one_year_ttm_0 - (current_assets_ttm_1 - cash_equivalent_ttm_1 - current_liabilities_ttm_1 + notes_payable_ttm_1 + non_current_liability_due_one_year_ttm_1))                      |
| fcfe_lyr                              | 股权自由现金流量 lyr                    | 归属于母公司所有者的净利润 lyr ＋ 资产减值准备 lyr ＋ 固定资产折旧 lyr ＋ 无形资产摊销 lyr ＋ 长期待摊费用摊销 lyr -（本期固定资产合计 lyr - 上期固定资产合计 lyr + 固定资产折旧 lyr）- 营运资本变动额 lyr + 净债务增加 lyr 其中：营运资本变动额＝期末[（流动资产合计－货币资金）－(流动负债合计-应付票据－一年内到期的非流动负债）]－期初[（流动资产合计－货币资金）－(流动负债合计-应付票据－一年内到期的非流动负债）]；净债务增加＝期末（短期借款+长期借款+应付债券）－期初（短期借款+长期借款+应付债券）                                                                                | net_profit_parent_company_lyr_0 + assets_depreciation_reserves_lyr_0 + fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_lyr_0 + deferred_expense_amortization_lyr_0 - (total_fixed_assets_lyr_0 - total_fixed_assets_lyr_1 + fixed_asset_depreciation_lyr_0) - (current_assets_lyr_0 - cash_equivalent_lyr_0 - current_liabilities_lyr_0 + notes_payable_lyr_0 + non_current_liability_due_one_year_lyr_0 - (current_assets_lyr_1 - cash_equivalent_lyr_1 - current_liabilities_lyr_1 + notes_payable_lyr_1 + non_current_liability_due_one_year_lyr_1)) + (short_term_loans_lyr_0 + long_term_loans_lyr_0 + bond_payable_lyr_0 - (short_term_loans_lyr_1 + long_term_loans_lyr_1 + bond_payable_lyr_1)) |
| fcfe_ttm                              | 股权自由现金流量 ttm                    | 归属于母公司所有者的净利润 ttm ＋ 资产减值准备 ttm ＋ 固定资产折旧 ttm ＋ 无形资产摊销 ttm ＋ 长期待摊费用摊销 ttm -（本期固定资产合计 ttm - 上期固定资产合计 ttm + 固定资产折旧 ttm）- 营运资本变动额 ttm + 净债务增加 ttm 其中：营运资本变动额＝期末[（流动资产合计－货币资金）－(流动负债合计-应付票据－一年内到期的非流动负债）]－期初[（流动资产合计－货币资金）－(流动负债合计-应付票据－一年内到期的非流动负债）]；净债务增加＝期末（短期借款+长期借款+应付债券）－期初（短期借款+长期借款+应付债券）                                                                                | net_profit_parent_company_ttm_0 + assets_depreciation_reserves_ttm_0 + fixed_asset_depreciation_ttm_0 + intangible_asset_amortization_ttm_0 + deferred_expense_amortization_ttm_0 - (total_fixed_assets_ttm_0 - total_fixed_assets_ttm_1 + fixed_asset_depreciation_ttm_0) - (current_assets_ttm_0 - cash_equivalent_ttm_0 - current_liabilities_ttm_0 + notes_payable_ttm_0 + non_current_liability_due_one_year_ttm_0 - (current_assets_ttm_1 - cash_equivalent_ttm_1 - current_liabilities_ttm_1 + notes_payable_ttm_1 + non_current_liability_due_one_year_ttm_1)) + (short_term_loans_ttm_0 + long_term_loans_ttm_0 + bond_payable_ttm_0 - (short_term_loans_ttm_1 + long_term_loans_ttm_1 + bond_payable_ttm_1)) |
| free_cash_flow_company_per_share_lyr  | 每股企业自由现金流 lyr                  | 企业自由现金流量 lyr / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | fcff_lyr_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| free_cash_flow_company_per_share_ttm  | 每股企业自由现金流 ttm                  | 企业自由现金流量 ttm / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | fcff_ttm_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| free_cash_flow_equity_per_share_lyr   | 每股股东自由现金流 lyr                  | 股东自由现金流量 lyr / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | fcfe_lyr_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| free_cash_flow_equity_per_share_ttm   | 每股股东自由现金流 ttm                  | 股东自由现金流量 ttm / 总股本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | fcfe_ttm_0 / total_shares                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ocf_to_debt_lyr                       | 经营活动产生的现金流量净额/负债合计 lyr | 经营活动产生的现金流量净额 lyr / 负债合计 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | cash_flow_from_operating_activities_lyr_0 / total_liabilities_lyr_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ocf_to_debt_ttm                       | 经营活动产生的现金流量净额/负债合计 ttm | 经营活动产生的现金流量净额 ttm / 负债合计 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | cash_flow_from_operating_activities_ttm_0 / total_liabilities_ttm_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| surplus_cash_protection_multiples_lyr | 盈余现金保障倍数 lyr                    | 经营活动产生的现金流量净额 lyr/净利润 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | cash_flow_from_operating_activities_lyr_0/net_profit_lyr_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| surplus_cash_protection_multiples_ttm | 盈余现金保障倍数 ttm                    | 经营活动产生的现金流量净额 ttm/净利润 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | cash_flow_from_operating_activities_ttm_0/net_profit_ttm_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ocf_to_interest_bearing_debt_lyr      | 经营活动产生的现金流量净额/带息债务 lyr | 经营活动产生的现金流量净额 lyr / 带息债务 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | cash_flow_from_operating_activities_lyr_0 / interest_bearing_debt_lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ocf_to_interest_bearing_debt_ttm      | 经营活动产生的现金流量净额/带息债务 ttm | 经营活动产生的现金流量净额 ttm / 带息债务 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | cash_flow_from_operating_activities_ttm_0 / interest_bearing_debt_ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ocf_to_current_ratio_lyr              | 经营活动产生的现金流量净额/流动负债 lyr | 连续四季度经营活动产生的现金流量净额 lyr / 流动负债 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | cash_flow_from_operating_activities_lyr_0 / current_liabilities_lyr_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ocf_to_current_ratio_ttm              | 经营活动产生的现金流量净额/流动负债 ttm | 连续四季度经营活动产生的现金流量净额 ttm / 流动负债 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | cash_flow_from_operating_activities_ttm_0 / current_liabilities_ttm_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ocf_to_net_debt_lyr                   | 经营活动产生的现金流量净额/净债务 lyr   | 经营活动产生的现金流量净额 lyr / 净债务 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | cash_flow_from_operating_activities_lyr_0 / net_debt_lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ocf_to_net_debt_ttm                   | 经营活动产生的现金流量净额/净债务 ttm   | 经营活动产生的现金流量净额 ttm / 净债务 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | cash_flow_from_operating_activities_ttm_0 / net_debt_ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| depreciation_and_amortization_lyr     | 当期计提折旧与摊销 lyr                  | 固定资产折旧 lyr ＋ 无形资产摊销 lyr ＋ 长期待摊费用摊销 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_lyr_0 + deferred_expense_amortization_lyr_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| depreciation_and_amortization_ttm     | 当期计提折旧与摊销 ttm                  | 固定资产折旧 ttm ＋ 无形资产摊销 ttm ＋ 长期待摊费用摊销 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_ttm_0 + deferred_expense_amortization_ttm_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| cash_flow_ratio_lyr                   | 现金流量比率 lyr                        | 未扣除利息所得税折旧和摊销前的盈余 lyr / 年利息支出 lyr                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | ebitda_lyr / financing_interest_expense_lyr_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| cash_flow_ratio_ttm                   | 现金流量比率 ttm                        | 未扣除利息所得税折旧和摊销前的盈余 ttm / 年利息支出 ttm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | ebitda_ttm / financing_interest_expense_ttm_0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

###### 财务衍生指标 {#financial_indicators-derived_indicators}

_为方便阅读，可点<a href="https://assets.ricequant.com/vendor/rqdata/衍生财务指标.xlsx" target="_blank">这里</a >下载 Excel 版本的指标列表_

| 字段                                      | 中文名                               | 说明                                                                                                                                   | 公式                                                                                                                                                                                                   |
| ----------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| non_interest_bearing_current_debt_lyr     | 无息流动负债 lyr                     | 应付帐款 lyr ＋ 预收帐款 lyr ＋ 应付职工薪酬 lyr ＋ 应交税费 lyr ＋ 其他应付款 lyr ＋ 预提费用 lyr ＋ 递延收益 lyr ＋ 其他流动负债 lyr | accts_payable_lyr_0 + advance_from_customers_lyr_0 + payroll_payable_lyr_0 + tax_payable_lyr_0 + other_payable_lyr_0 + accrued_expense_lyr_0 + deferred_income_lyr_0 + other_current_liabilities_lyr_0 |
| non_interest_bearing_current_debt_ttm     | 无息流动负债 ttm                     | 应付帐款 ttm ＋ 预收帐款 ttm ＋ 应付职工薪酬 ttm ＋ 应交税费 ttm ＋ 其他应付款 ttm ＋ 预提费用 ttm ＋ 递延收益 ttm ＋ 其他流动负债 ttm | accts_payable_ttm_0 + advance_from_customers_ttm_0 + payroll_payable_ttm_0 + tax_payable_ttm_0 + other_payable_ttm_0 + accrued_expense_ttm_0 + deferred_income_ttm_0 + other_current_liabilities_ttm_0 |
| non_interest_bearing_current_debt_lf      | 无息流动负债 lf                      | 应付帐款 mrq ＋ 预收帐款 mrq ＋ 应付职工薪酬 mrq ＋ 应交税费 mrq ＋ 其他应付款 mrq ＋ 预提费用 mrq ＋ 递延收益 mrq ＋ 其他流动负债 mrq | accts_payable_mrq_0 + advance_from_customers_mrq_0 + payroll_payable_mrq_0 + tax_payable_mrq_0 + other_payable_mrq_0 + accrued_expense_mrq_0 + deferred_income_mrq_0 + other_current_liabilities_mrq_0 |
| non_interest_bearing_non_current_debt_lyr | 无息非流动负债 lyr                   | 非流动负债合计 lyr － 长期借款 lyr － 应付债券 lyr                                                                                     | non_current_liabilities_lyr_0 - long_term_loans_lyr_0 - bond_payable_lyr_0                                                                                                                             |
| non_interest_bearing_non_current_debt_ttm | 无息非流动负债 ttm                   | 非流动负债合计 ttm － 长期借款 ttm － 应付债券 ttm                                                                                     | non_current_liabilities_ttm_0 - long_term_loans_ttm_0 - bond_payable_ttm_0                                                                                                                             |
| non_interest_bearing_non_current_debt_lf  | 无息非流动负债 lf                    | 非流动负债合计 mrq － 长期借款 mrq － 应付债券 mrq                                                                                     | non_current_liabilities_mrq_0 - long_term_loans_mrq_0 - bond_payable_mrq_0                                                                                                                             |
| interest_bearing_debt_lyr                 | 带息债务 lyr                         | 负债合计 lyr - 无息流动负债 lyr - 无息非流动负债 lyr                                                                                   | total_liabilities_lyr_0 - non_interest_bearing_current_debt_lyr - non_interest_bearing_non_current_debt_lyr                                                                                            |
| interest_bearing_debt_ttm                 | 带息债务 ttm                         | 负债合计 ttm - 无息流动负债 ttm - 无息非流动负债 ttm                                                                                   | total_liabilities_ttm_0 - non_interest_bearing_current_debt_ttm - non_interest_bearing_non_current_debt_ttm                                                                                            |
| interest_bearing_debt_lf                  | 带息债务 lf                          | 负债合计 mrq - 无息流动负债 lf - 无息非流动负债 lf                                                                                     | total_liabilities_mrq_0 - non_interest_bearing_current_debt_lf - non_interest_bearing_non_current_debt_lf                                                                                              |
| capital_reserve_per_share_lyr             | 每股资本公积金 lyr                   | 资本公积金 lyr / 总股本                                                                                                                | capital_reserve_lyr_0 / total_shares                                                                                                                                                                   |
| capital_reserve_per_share_ttm             | 每股资本公积金 ttm                   | 资本公积金 ttm / 总股本                                                                                                                | capital_reserve_ttm_0 / total_shares                                                                                                                                                                   |
| capital_reserve_per_share_lf              | 每股资本公积金 lf                    | 资本公积金 mrq / 总股本                                                                                                                | capital_reserve_mrq_0 / total_shares                                                                                                                                                                   |
| earned_reserve_per_share_lyr              | 每股盈余公积金 lyr                   | 盈余公积金 lyr / 总股本                                                                                                                | surplus_reserve_lyr_0 / total_shares                                                                                                                                                                   |
| earned_reserve_per_share_ttm              | 每股盈余公积金 ttm                   | 盈余公积金 ttm / 总股本                                                                                                                | surplus_reserve_ttm_0 / total_shares                                                                                                                                                                   |
| earned_reserve_per_share_lf               | 每股盈余公积金 lf                    | 盈余公积金 mrq / 总股本                                                                                                                | surplus_reserve_mrq_0 / total_shares                                                                                                                                                                   |
| undistributed_profit_per_share_lyr        | 每股未分配利润 lyr                   | 企业当期未分配利润总额 lyr / 总股本                                                                                                    | undistributed_profit_lyr_0 / total_shares                                                                                                                                                              |
| undistributed_profit_per_share_ttm        | 每股未分配利润 ttm                   | 企业当期未分配利润总额 ttm / 总股本                                                                                                    | undistributed_profit_ttm_0 / total_shares                                                                                                                                                              |
| undistributed_profit_per_share_lf         | 每股未分配利润 lf                    | 企业当期未分配利润总额 mrq / 总股本                                                                                                    | undistributed_profit_mrq_0 / total_shares                                                                                                                                                              |
| retained_earnings_lyr                     | 留存收益 lyr                         | 盈余公积金 lyr + 未分配利润 lyr                                                                                                        | surplus_reserve_lyr_0 + undistributed_profit_lyr_0                                                                                                                                                     |
| retained_earnings_ttm                     | 留存收益 ttm                         | 盈余公积金 ttm + 未分配利润 ttm                                                                                                        | surplus_reserve_ttm_0 + undistributed_profit_ttm_0                                                                                                                                                     |
| retained_earnings_lf                      | 留存收益 lf                          | 盈余公积金 mrq + 未分配利润 mrq                                                                                                        | surplus_reserve_mrq_0 + undistributed_profit_mrq_0                                                                                                                                                     |
| retained_earnings_per_share_lyr           | 每股留存收益 lyr                     | 留存收益 lyr / 总股本                                                                                                                  | retained_earnings_lyr / total_shares                                                                                                                                                                   |
| retained_earnings_per_share_ttm           | 每股留存收益 ttm                     | 留存收益 ttm / 总股本                                                                                                                  | retained_earnings_ttm / total_shares                                                                                                                                                                   |
| retained_earnings_per_share_lf            | 每股留存收益 lf                      | 留存收益 lf / 总股本                                                                                                                   | retained_earnings_lf / total_shares                                                                                                                                                                    |
| debt_to_asset_ratio_lyr                   | 资产负债率 lyr                       | 负债合计 lyr / 总资产                                                                                                                  | total_liabilities_lyr_0 / total_assets_lyr_0                                                                                                                                                           |
| debt_to_asset_ratio_ttm                   | 资产负债率 ttm                       | 负债合计 ttm / 总资产                                                                                                                  | total_liabilities_ttm_0 / total_assets_ttm_0                                                                                                                                                           |
| debt_to_asset_ratio_lf                    | 资产负债率 lf                        | 负债合计 mrq / 总资产                                                                                                                  | total_liabilities_mrq_0 / total_assets_mrq_0                                                                                                                                                           |
| equity_multiplier_lyr                     | 权益乘数 lyr                         | 总资产 lyr / 股东权益合计 lyr                                                                                                          | total_assets_lyr_0 / total_equity_lyr_0                                                                                                                                                                |
| equity_multiplier_ttm                     | 权益乘数 ttm                         | 总资产 ttm / 股东权益合计 ttm                                                                                                          | total_assets_ttm_0 / total_equity_ttm_0                                                                                                                                                                |
| equity_multiplier_lf                      | 权益乘数 lf                          | 总资产 mrq / 股东权益合计 mrq                                                                                                          | total_assets_mrq_0 / total_equity_mrq_0                                                                                                                                                                |
| capital_to_equity_ratio_lyr               | 长期资本固定比率 lyr                 | (资产总计 lyr-流动资产 lyr)/所有者权益平均余额 lyr                                                                                     | 2\*(total_assets_lyr_0-current_assets_lyr_0)/(total_equity_lyr_0+total_equity_lyr_1)                                                                                                                   |
| capital_to_equity_ratio_ttm               | 长期资本固定比率 ttm                 | (资产总计 ttm-流动资产 ttm)/所有者权益平均余额 ttm                                                                                     | 2\*(total_assets_ttm_0-current_assets_ttm_0)/(total_equity_ttm_0+total_equity_ttm_1)                                                                                                                   |
| capital_to_equity_ratio_lf                | 长期资本固定比率 lf                  | (资产总计 lf-流动资产 lf)/所有者权益平均余额 lf                                                                                        | 2\*(total_assets_mrq_0-current_assets_mrq_0)/(total_equity_mrq_0+total_equity_mrq_1)                                                                                                                   |
| current_asset_to_total_asset_lyr          | 流动资产比率 lyr                     | 流动资产合计 lyr / 总资产 lyr                                                                                                          | current_assets_lyr_0 / total_assets_lyr_0                                                                                                                                                              |
| current_asset_to_total_asset_ttm          | 流动资产比率 ttm                     | 流动资产合计 ttm / 总资产 ttm                                                                                                          | current_assets_ttm_0 / total_assets_ttm_0                                                                                                                                                              |
| current_asset_to_total_asset_lf           | 流动资产比率 lf                      | 流动资产合计 mrq / 总资产 mrq                                                                                                          | current_assets_mrq_0 / total_assets_mrq_0                                                                                                                                                              |
| non_current_asset_to_total_asset_lyr      | 非流动资产比率 lyr                   | 非流动资产合计 lyr / 总资产 lyr                                                                                                        | non_current_assets_lyr_0 / total_assets_lyr_0                                                                                                                                                          |
| non_current_asset_to_total_asset_ttm      | 非流动资产比率 ttm                   | 非流动资产合计 ttm / 总资产 ttm                                                                                                        | non_current_assets_ttm_0 / total_assets_ttm_0                                                                                                                                                          |
| non_current_asset_to_total_asset_lf       | 非流动资产比率 lf                    | 非流动资产合计 mrq / 总资产 mrq                                                                                                        | non_current_assets_mrq_0 / total_assets_mrq_0                                                                                                                                                          |
| invested_capital_lyr                      | 全部投入资本 lyr                     | 归属于母公司所有者权益合计 lyr + 带息债务 lyr                                                                                          | equity_parent_company_lyr_0 + interest_bearing_debt_lyr                                                                                                                                                |
| invested_capital_ttm                      | 全部投入资本 ttm                     | 归属于母公司所有者权益合计 ttm + 带息债务 ttm                                                                                          | equity_parent_company_ttm_0 + interest_bearing_debt_ttm                                                                                                                                                |
| invested_capital_lf                       | 全部投入资本 lf                      | 归属于母公司所有者权益合计 mrq + 带息债务 lf                                                                                           | equity_parent_company_mrq_0 + interest_bearing_debt_lf                                                                                                                                                 |
| interest_bearing_debt_to_capital_lyr      | 带息债务占企业全部投入成本的比重 lyr | 带息债务 lyr / 全部投入资本 lyr                                                                                                        | interest_bearing_debt_lyr / invested_capital_lyr                                                                                                                                                       |
| interest_bearing_debt_to_capital_ttm      | 带息债务占企业全部投入成本的比重 ttm | 带息债务 ttm / 全部投入资本 ttm                                                                                                        | interest_bearing_debt_ttm / invested_capital_ttm                                                                                                                                                       |
| interest_bearing_debt_to_capital_lf       | 带息债务占企业全部投入成本的比重 lf  | 带息债务 lf / 全部投入资本 lf                                                                                                          | interest_bearing_debt_lf / invested_capital_lf                                                                                                                                                         |
| current_debt_to_total_debt_lyr            | 流动负债率 lyr                       | 流动负债合计 lyr / 负债合计 lyr                                                                                                        | current_liabilities_lyr_0 / total_liabilities_lyr_0                                                                                                                                                    |
| current_debt_to_total_debt_ttm            | 流动负债率 ttm                       | 流动负债合计 ttm / 负债合计 ttm                                                                                                        | current_liabilities_ttm_0 / total_liabilities_ttm_0                                                                                                                                                    |
| current_debt_to_total_debt_lf             | 流动负债率 lf                        | 流动负债合计 mrq / 负债合计 mrq                                                                                                        | current_liabilities_mrq_0 / total_liabilities_mrq_0                                                                                                                                                    |
| non_current_debt_to_total_debt_lyr        | 非流动负债率 lyr                     | 非流动负债合计 lyr / 负债合计 lyr                                                                                                      | non_current_liabilities_lyr_0 / total_liabilities_lyr_0                                                                                                                                                |
| non_current_debt_to_total_debt_ttm        | 非流动负债率 ttm                     | 非流动负债合计 ttm / 负债合计 ttm                                                                                                      | non_current_liabilities_ttm_0 / total_liabilities_ttm_0                                                                                                                                                |
| non_current_debt_to_total_debt_lf         | 非流动负债率 lf                      | 非流动负债合计 mrq / 负债合计 mrq                                                                                                      | non_current_liabilities_mrq_0 / total_liabilities_mrq_0                                                                                                                                                |
| current_ratio_lyr                         | 流动比率 lyr                         | 流动资产合计 lyr / 流动负债合计 lyr                                                                                                    | current_assets_lyr_0 / current_liabilities_lyr_0                                                                                                                                                       |
| current_ratio_ttm                         | 流动比率 ttm                         | 流动资产合计 ttm / 流动负债合计 ttm                                                                                                    | current_assets_ttm_0 / current_liabilities_ttm_0                                                                                                                                                       |
| current_ratio_lf                          | 流动比率 lf                          | 流动资产合计 mrq / 流动负债合计 mrq                                                                                                    | current_assets_mrq_0 / current_liabilities_mrq_0                                                                                                                                                       |
| quick_ratio_lyr                           | 速动比率 lyr                         | （流动资产合计 lyr - 存货 lyr - 预付账款 lyr - 待摊费用 lyr）/ 流动负债合计 lyr                                                        | (current_assets_lyr_0 - inventory_lyr_0 - prepayment_lyr_0 - deferred_expense_lyr_0) / current_liabilities_lyr_0                                                                                       |
| quick_ratio_ttm                           | 速动比率 ttm                         | （流动资产合计 ttm - 存货 ttm - 预付账款 ttm - 待摊费用 ttm）/ 流动负债合计 ttm                                                        | (current_assets_ttm_0 - inventory_ttm_0 - prepayment_ttm_0 - deferred_expense_ttm_0) / current_liabilities_ttm_0                                                                                       |
| quick_ratio_lf                            | 速动比率 lf                          | （流动资产合计 mrq - 存货 mrq - 预付账款 mrq - 待摊费用 mrq）/ 流动负债合计 mrq                                                        | (current_assets_mrq_0 - inventory_mrq_0 - prepayment_mrq_0 - deferred_expense_mrq_0) / current_liabilities_mrq_0                                                                                       |
| super_quick_ratio_lyr                     | 超速动比率 lyr                       | （货币资金 lyr + 交易性金融资产 lyr + 应收票据 lyr + 应收账款 lyr + 其他应收款 lyr）/ 流动负债合计 lyr                                 | (cash_equivalent_lyr_0 + financial_asset_held_for_trading_lyr_0 + bill_receivable_lyr_0 + net_accts_receivable_lyr_0 + other_accts_receivable_lyr_0) / current_liabilities_lyr_0                       |
| super_quick_ratio_ttm                     | 超速动比率 ttm                       | （货币资金 ttm + 交易性金融资产 ttm + 应收票据 ttm + 应收账款 ttm + 其他应收款 ttm）/ 流动负债合计 ttm                                 | (cash_equivalent_ttm_0 + financial_asset_held_for_trading_ttm_0 + bill_receivable_ttm_0 + net_accts_receivable_ttm_0 + other_accts_receivable_ttm_0) / current_liabilities_ttm_0                       |
| super_quick_ratio_lf                      | 超速动比率 lf                        | （货币资金 mrq + 交易性金融资产 mrq + 应收票据 mrq + 应收账款 mrq + 其他应收款 mrq）/ 流动负债合计 mrq                                 | (cash_equivalent_mrq_0 + financial_asset_held_for_trading_mrq_0 + bill_receivable_mrq_0 + net_accts_receivable_mrq_0 + other_accts_receivable_mrq_0) / current_liabilities_mrq_0                       |
| debt_to_equity_ratio_lyr                  | 产权比率 lyr                         | 负债合计 lyr / 股东权益合计 lyr                                                                                                        | total_liabilities_lyr_0 / equity_parent_company_lyr_0                                                                                                                                                  |
| debt_to_equity_ratio_ttm                  | 产权比率 ttm                         | 负债合计 ttm / 股东权益合计 ttm                                                                                                        | total_liabilities_ttm_0 / equity_parent_company_ttm_0                                                                                                                                                  |
| debt_to_equity_ratio_lf                   | 产权比率 lf                          | 负债合计 mrq / 股东权益合计 mrq                                                                                                        | total_liabilities_mrq_0 / equity_parent_company_mrq_0                                                                                                                                                  |
| equity_to_debt_ratio_lyr                  | 权益负债比率 lyr                     | 归属于母公司所有者权益合计 lyr / 负债合计 lyr                                                                                          | equity_parent_company_lyr_0 / total_liabilities_lyr_0                                                                                                                                                  |
| equity_to_debt_ratio_ttm                  | 权益负债比率 ttm                     | 归属于母公司所有者权益合计 ttm / 负债合计 ttm                                                                                          | equity_parent_company_ttm_0 / total_liabilities_ttm_0                                                                                                                                                  |
| equity_to_debt_ratio_lf                   | 权益负债比率 lf                      | 归属于母公司所有者权益合计 mrq / 负债合计 mrq                                                                                          | equity_parent_company_mrq_0 / total_liabilities_mrq_0                                                                                                                                                  |
| equity_to_interest_bearing_debt_lyr       | 权益带息负债比率 lyr                 | 归属于母公司所有者权益合计 lyr / 带息债务 lyr                                                                                          | equity_parent_company_lyr_0 / interest_bearing_debt_lyr                                                                                                                                                |
| equity_to_interest_bearing_debt_ttm       | 权益带息负债比率 ttm                 | 归属于母公司所有者权益合计 ttm / 带息债务 ttm                                                                                          | equity_parent_company_ttm_0 / interest_bearing_debt_ttm                                                                                                                                                |
| equity_to_interest_bearing_debt_lf        | 权益带息负债比率 lf                  | 归属于母公司所有者权益合计 mrq / 带息债务 lf                                                                                           | equity_parent_company_mrq_0 / interest_bearing_debt_lf                                                                                                                                                 |
| net_debt_lyr                              | 净债务 lyr                           | 带息债务 lyr - 货币资金 lyr                                                                                                            | interest_bearing_debt_lyr - cash_equivalent_lyr_0                                                                                                                                                      |
| net_debt_ttm                              | 净债务 ttm                           | 带息债务 ttm - 货币资金 ttm                                                                                                            | interest_bearing_debt_ttm - cash_equivalent_ttm_0                                                                                                                                                      |
| net_debt_lf                               | 净债务 lf                            | 带息债务 lf - 货币资金 mrq                                                                                                             | interest_bearing_debt_lf - cash_equivalent_mrq_0                                                                                                                                                       |
| working_capital_lyr                       | 营运资本 lyr                         | 流动资产合计 lyr - 流动负债合计 lyr                                                                                                    | current_assets_lyr_0 - current_liabilities_lyr_0                                                                                                                                                       |
| working_capital_ttm                       | 营运资本 ttm                         | 流动资产合计 ttm - 流动负债合计 ttm                                                                                                    | current_assets_ttm_0 - current_liabilities_ttm_0                                                                                                                                                       |
| working_capital_lf                        | 营运资本 lf                          | 流动资产合计 mrq - 流动负债合计 mrq                                                                                                    | current_assets_mrq_0 - current_liabilities_mrq_0                                                                                                                                                       |
| net_working_capital_lyr                   | 净营运资本 lyr                       | 流动资产合计 lyr - 货币资金 lyr - 无息流动负债 lyr                                                                                     | current_assets_lyr_0 - cash_equivalent_lyr_0 - non_interest_bearing_current_debt_lyr                                                                                                                   |
| net_working_capital_ttm                   | 净营运资本 ttm                       | 流动资产合计 ttm - 货币资金 ttm - 无息流动负债 ttm                                                                                     | current_assets_ttm_0 - cash_equivalent_ttm_0 - non_interest_bearing_current_debt_ttm                                                                                                                   |
| net_working_capital_lf                    | 净营运资本 lf                        | 流动资产合计 mrq - 货币资金 mrq - 无息流动负债 lf                                                                                      | current_assets_mrq_0 - cash_equivalent_mrq_0 - non_interest_bearing_current_debt_lf                                                                                                                    |
| long_term_debt_to_working_capital_lyr     | 长期债务与营运资金比率 lyr           | 长期负债 lyr/营运资本 lyr                                                                                                              | non_current_liabilities_lyr_0 / working_capital_lyr                                                                                                                                                    |
| long_term_debt_to_working_capital_ttm     | 长期债务与营运资金比率 ttm           | 长期负债 ttm/营运资本 ttm                                                                                                              | non_current_liabilities_ttm_0 / working_capital_ttm                                                                                                                                                    |
| long_term_debt_to_working_capital_lf      | 长期债务与营运资金比率 lf            | 长期负债 lf/营运资本 lf                                                                                                                | non_current_liabilities_mrq_0 / working_capital_lf                                                                                                                                                     |
| book_value_per_share_lyr                  | 每股净资产 lyr                       | 归属母公司股东权益合计 lyr / 总股本                                                                                                    | equity_parent_company_lyr_0 / total_shares                                                                                                                                                             |
| book_value_per_share_ttm                  | 每股净资产 ttm                       | 归属母公司股东权益合计 ttm / 总股本                                                                                                    | equity_parent_company_ttm_0 / total_shares                                                                                                                                                             |
| book_value_per_share_lf                   | 每股净资产 lf                        | 股东权益合计 mrq / 总股本                                                                                                              | equity_parent_company_mrq_0 / total_shares                                                                                                                                                             |
| du_equity_multiplier_lyr                  | 权益乘数(杜邦分析)lyr                | （本期总资产 lyr + 上年总资产 lyr）/ (本期股东权益合计 lyr + 上年股东权益合计 lyr)                                                     | (total_assets_lyr_0 + total_assets_lyr_1) / (total_equity_lyr_0 + total_equity_lyr_1)                                                                                                                  |
| du_equity_multiplier_ttm                  | 权益乘数(杜邦分析)ttm                | （本期总资产 ttm + 上期总资产 ttm）/ (本期股东权益合计 ttm + 上期股东权益合计 ttm)                                                     | (total_assets_ttm_0 + total_assets_ttm_1) / (total_equity_ttm_0 + total_equity_ttm_1)                                                                                                                  |
| du_equity_multiplier_lf                   | 权益乘数(杜邦分析)lf                 | （本期总资产 mrq + 上期总资产 mrq）/ (本期股东权益合计 mrq + 上期股东权益合计 mrq)                                                     | (total_assets_mrq_0 + total_assets_mrq_1) / (total_equity_mrq_0 + total_equity_mrq_1)                                                                                                                  |
| book_leverage_lyr                         | 账面杠杆 lyr                         | 非流动复债合计 lyr / 归母公司股东权益合计 lyr                                                                                          | non_current_liabilities_lyr_0 / equity_parent_company_lyr_0                                                                                                                                            |
| book_leverage_ttm                         | 账面杠杆 ttm                         | 非流动复债合计 ttm / 归母公司股东权益合计 ttm                                                                                          | non_current_liabilities_ttm_0 / equity_parent_company_ttm_0                                                                                                                                            |
| book_leverage_lf                          | 账面杠杆 lf                          | 非流动复债合计 mrq / 归母公司股东权益合计 mrq                                                                                          | non_current_liabilities_mrq_0 / equity_parent_company_mrq_0                                                                                                                                            |
| market_leverage_lyr                       | 市场杠杆 lyr                         | 非流动负债合计 lyr / (非流动负债合计 lyr + 总市值)                                                                                     | non_current_liabilities_lyr_0 / (non_current_liabilities_lyr_0 + market_cap_3)                                                                                                                         |
| market_leverage_ttm                       | 市场杠杆 ttm                         | 非流动负债合计 ttm / (非流动负债合计 ttm + 总市值)                                                                                     | non_current_liabilities_ttm_0 / (non_current_liabilities_ttm_0 + market_cap_3)                                                                                                                         |
| market_leverage_lf                        | 市场杠杆 lf                          | 非流动负债合计 mrq / (非流动负债合计 mrq + 总市值)                                                                                     | non_current_liabilities_mrq_0 /(non_current_liabilities_mrq_0 + market_cap_3)                                                                                                                          |
| equity_ratio_lyr                          | 股东权益比率 lyr                     | 归属母公司股东权益总计 lyr / 资产总计 lyr                                                                                              | equity_parent_company_lyr_0 / total_assets_lyr_0                                                                                                                                                       |
| equity_ratio_ttm                          | 股东权益比率 ttm                     | 归属母公司股东权益总计 ttm / 资产总计 ttm                                                                                              | equity_parent_company_ttm_0 / total_assets_ttm_0                                                                                                                                                       |
| equity_ratio_lf                           | 股东权益比率 lf                      | 归属母公司股东权益总计 mrq / 资产总计 mrq                                                                                              | equity_parent_company_mrq_0 / total_assets_mrq_0                                                                                                                                                       |
| fixed_asset_ratio_lyr                     | 固定资产比率 lyr                     | (固定资产 lyr + 工程物资 lyr + 在建工程合计 lyr) / 资产总计 lyr                                                                        | (total_fixed_assets_lyr_0 + engineer_material_lyr_0 + total_construction_in_progress_lyr_0) / total_assets_lyr_0                                                                                       |
| fixed_asset_ratio_ttm                     | 固定资产比率 ttm                     | (固定资产 ttm + 工程物资 ttm + 在建工程合计 ttm) / 资产总计 ttm                                                                        | (total_fixed_assets_ttm_0 + engineer_material_ttm_0 + total_construction_in_progress_ttm_0) / total_assets_ttm_0                                                                                       |
| fixed_asset_ratio_lf                      | 固定资产比率 lf                      | (固定资产 mrq + 工程物资 mrq + 在建工程合计 mrq) / 资产总计 mrq                                                                        | (total_fixed_assets_mrq_0 + engineer_material_mrq_0 + total_construction_in_progress_mrq_0) / total_assets_mrq_0                                                                                       |
| intangible_asset_ratio_lyr                | 无形资产比率 lyr                     | (无形资产 lyr + 开发支出 lyr + 商誉 lyr) / 资产总计 lyr                                                                                | (intangible_assets_lyr_0 + impairment_intangible_assets_lyr_0 + goodwill_lyr_0) / total_assets_lyr_0                                                                                                   |
| intangible_asset_ratio_ttm                | 无形资产比率 ttm                     | (无形资产 ttm + 开发支出 ttm + 商誉 ttm) / 资产总计 ttm                                                                                | (intangible_assets_ttm_0 + impairment_intangible_assets_ttm_0 + goodwill_ttm_0) / total_assets_ttm_0                                                                                                   |
| intangible_asset_ratio_lf                 | 无形资产比率 lf                      | (无形资产 mrq + 开发支出 mrq + 商誉 mrq) / 资产总计 mrq                                                                                | (intangible_assets_mrq_0 + impairment_intangible_assets_mrq_0 + goodwill_mrq_0) / total_assets_mrq_0                                                                                                   |
| equity_fixed_asset_ratio_lyr              | 股东权益与固定资产比率 lyr           | 归属母公司股东权益合计 lyr / (固定资产合计 lyr + 工程物资 lyr + 在建工程合计 lyr)                                                      | equity_parent_company_lyr_0 / (total_fixed_assets_lyr_0 + engineer_material_lyr_0 + total_construction_in_progress_lyr_0)                                                                              |
| equity_fixed_asset_ratio_ttm              | 股东权益与固定资产比率 ttm           | 归属母公司股东权益合计 ttm / (固定资产合计 ttm + 工程物资 ttm + 在建工程合计 ttm)                                                      | equity_parent_company_ttm_0 / (total_fixed_assets_ttm_0 + engineer_material_ttm_0 + total_construction_in_progress_ttm_0)                                                                              |
| equity_fixed_asset_ratio_lf               | 股东权益与固定资产比率 lf            | 归属母公司股东权益合计 mrq / (固定资产合计 mrq + 工程物资 mrq + 在建工程合计 mrq)                                                      | equity_parent_company_mrq_0 / (total_fixed_assets_mrq_0 + engineer_material_mrq_0 + total_construction_in_progress_mrq_0)                                                                              |
| tangible_asset_per_share_lyr              | 每股有形资产 lyr                     | （资产总计 lyr - 无形资产 lyr - 商誉 lyr）/ 总股本                                                                                     | (total_assets_lyr_0 - intangible_assets_lyr_0 - goodwill_lyr_0) / total_shares                                                                                                                         |
| tangible_asset_per_share_ttm              | 每股有形资产 ttm                     | （资产总计 ttm - 无形资产 ttm - 商誉 ttm）/ 总股本                                                                                     | (total_assets_ttm_0 - intangible_assets_ttm_0 - goodwill_ttm_0) / total_shares                                                                                                                         |
| tangible_asset_per_share_lf               | 每股有形资产 lf                      | （资产总计 mrq - 无形资产 mrq - 商誉 mrq）/ 总股本                                                                                     | (total_assets_mrq_0 - intangible_assets_mrq_0 - goodwill_mrq_0) / total_shares                                                                                                                         |
| liabilities_per_share_lyr                 | 每股负债 lyr                         | 负债合计 lyr / 总股本                                                                                                                  | total_liabilities_lyr_0 / total_shares                                                                                                                                                                 |
| liabilities_per_share_ttm                 | 每股负债 ttm                         | 负债合计 ttm / 总股本                                                                                                                  | total_liabilities_ttm_0 / total_shares                                                                                                                                                                 |
| liabilities_per_share_lf                  | 每股负债 lf                          | 负债合计 mrq / 总股本                                                                                                                  | total_liabilities_mrq_0 / total_shares                                                                                                                                                                 |
| depreciation_per_share_lyr                | 每股折旧和摊销 lyr                   | （固定资产折旧 lyr + 无形资产摊销 lyr + 长期待摊费用摊销 lyr）/ 总股本                                                                 | (fixed_asset_depreciation_lyr_0 + intangible_asset_amortization_lyr_0 + deferred_expense_amortization_lyr_0) / total_shares                                                                            |
| depreciation_per_share_ttm                | 每股折旧和摊销 ttm                   | （固定资产折旧 ttm + 无形资产摊销 ttm + 长期待摊费用摊销 ttm）/ 总股本                                                                 | (fixed_asset_depreciation_ttm_0 + intangible_asset_amortization_ttm_0 + deferred_expense_amortization_ttm_0) / total_shares                                                                            |
| depreciation_per_share_lf                 | 每股折旧和摊销 lf                    | （固定资产折旧 lf + 无形资产摊销 lf + 长期待摊费用摊销 lf）/ 总股本                                                                    | (fixed_asset_depreciation_mrq_0 + intangible_asset_amortization_mrq_0 + deferred_expense_amortization_mrq_0) / total_shares                                                                            |
| cash_ratio_lyr                            | 现金比率 lyr                         | 货币资金余额 lyr / 流动负债合计 lyr                                                                                                    | cash_equivalent_lyr_0 / current_liabilities_lyr_0                                                                                                                                                      |
| cash_ratio_ttm                            | 现金比率 ttm                         | 货币资金余额 ttm / 流动负债合计 ttm                                                                                                    | cash_equivalent_ttm_0 / current_liabilities_ttm_0                                                                                                                                                      |
| cash_ratio_lf                             | 现金比率 lf                          | 货币资金余额 mrq / 流动负债合计 mrq                                                                                                    | cash_equivalent_mrq_0 / current_liabilities_mrq_0                                                                                                                                                      |
| cash_equivalent_per_share_lyr             | 每股货币资金余额 lyr                 | 货币资金余额 lyr / 总股本                                                                                                              | cash_equivalent_lyr_0 / total_shares                                                                                                                                                                   |
| cash_equivalent_per_share_ttm             | 每股货币资金余额 ttm                 | 货币资金余额 ttm / 总股本                                                                                                              | cash_equivalent_ttm_0 / total_shares                                                                                                                                                                   |
| cash_equivalent_per_share_lf              | 每股货币资金余额 lf                  | 货币资金余额 mrq / 总股本                                                                                                              | cash_equivalent_mrq_0 / total_shares                                                                                                                                                                   |
| dividend_amount_ly0                       | 最近年度分红总额                     | 事件进度仅包含方案实施                                                                                                                 |                                                                                                                                                                                                        |
| dividend_amount_ly1                       | 最近年度分红总额                     | 事件进度包含决案、方案实施                                                                                                             |                                                                                                                                                                                                        |
| dividend_amount_ly2                       | 最近年度分红总额                     | 事件进度包含预案、决案和方案实施                                                                                                       |                                                                                                                                                                                                        |
| dividend_amount_ttm0                      | 最近四个季度分红总额                 | 事件进度仅包含方案实施                                                                                                                 |                                                                                                                                                                                                        |
| dividend_amount_ttm1                      | 最近四个季度分红总额                 | 事件进度包含决案、方案实施                                                                                                             |                                                                                                                                                                                                        |
| dividend_amount_ttm2                      | 最近四个季度分红总额                 | 事件进度包含预案、决案和方案实施                                                                                                       |                                                                                                                                                                                                        |

###### 增长衍生指标 {#financial_indicators-growth}

_为方便阅读，可点<a href="https://assets.ricequant.com/vendor/rqdata/衍生财务指标.xlsx" target="_blank">这里</a >下载 Excel 版本的指标列表_

| 字段                                       | 中文名                                 | 说明                                                                                        | 公式                                                                                                    |
| ------------------------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| inc_revenue_lyr                            | 营业总收入同比增长率 lyr               | 营业总收入 lyr / 上年营业总收入 lyr - 1                                                     | revenue_lyr_0 / revenue_lyr_1 - 1                                                                       |
| inc_revenue_ttm                            | 营业总收入同比增长率 ttm               | 营业总收入 ttm / 上年营业总收入 ttm - 1                                                     | revenue_ttm_0 / revenue_ttm_4 - 1                                                                       |
| inc_return_on_equity_lyr                   | 净资产收益率(摊薄）同比增长率 lyr      | 摊薄净资产收益率 lyr / 去年摊薄净资产收益率 lyr - 1                                         | (net_profit_lyr_0 / total_equity_lyr_0) / (net_profit_lyr_1 / total_equity_lyr_1) - 1                   |
| inc_return_on_equity_ttm                   | 净资产收益率(摊薄）同比增长率 ttm      | 摊薄净资产收益率 ttm / 去年摊薄净资产收益率 ttm - 1                                         | (net_profit_ttm_0 / total_equity_ttm_0) / (net_profit_ttm_4 / total_equity_ttm_4) - 1                   |
| inc_book_per_share_lyr                     | 每股净资产同比增长率 lyr               | 每股净资产 lyr / 去年每股净资产 lyr - 1                                                     | (equity_parent_company_lyr_0 / total_shares) / (equity_parent_company_lyr_1 / prev_year_total_shares)-1 |
| inc_book_per_share_ttm                     | 每股净资产同比增长率 ttm               | 每股净资产 ttm / 去年每股净资产 ttm - 1                                                     | (equity_parent_company_ttm_0 / total_shares) / (equity_parent_company_ttm_4 / prev_year_total_shares)-1 |
| inc_book_per_share_lf                      | 每股净资产同比增长率 lf                | 每股净资产 lf / 去年每股净资产 lf - 1                                                       | (equity_parent_company_mrq_0 / total_shares) / (equity_parent_company_mrq_4 / prev_year_total_shares)-1 |
| operating_profit_growth_ratio_lyr          | 营业利润同比增长率 lyr                 | (营业利润 lyr - 去年营业利润 lyr) / 去年营业利润 lyr                                        | (profit_from_operation_lyr_0 - profit_from_operation_lyr_1) / profit_from_operation_lyr_1               |
| operating_profit_growth_ratio_ttm          | 营业利润同比增长率 ttm                 | (营业利润 ttm - 去年营业利润 ttm) / 去年营业利润 ttm                                        | (profit_from_operation_ttm_0 - profit_from_operation_ttm_4) / profit_from_operation_ttm_4               |
| net_profit_growth_ratio_lyr                | 净利润同比增长率 lyr                   | (净利润 lyr - 去年净利润 lyr) / 去年净利润 lyr                                              | (net_profit_lyr_0 - net_profit_lyr_1) / net_profit_lyr_1                                                |
| net_profit_growth_ratio_ttm                | 净利润同比增长率 ttm                   | (净利润 ttm - 去年净利润 ttm) / 去年净利润 ttm                                              | (net_profit_ttm_0 - net_profit_ttm_4) / net_profit_ttm_4                                                |
| profit_growth_ratio_lyr                    | 利润总额同比增长率 lyr                 | (利润总额 lyr - 去年利润总额 lyr) / 去年利润总额 lyr                                        | (profit_before_tax_lyr_0 - profit_before_tax_lyr_1) / profit_before_tax_lyr_1                           |
| profit_growth_ratio_ttm                    | 利润总额同比增长率 ttm                 | (利润总额 ttm - 去年利润总额 ttm) / 去年利润总额 ttm                                        | (profit_before_tax_ttm_0 - profit_before_tax_ttm_4) / profit_before_tax_ttm_4                           |
| gross_profit_growth_ratio_lyr              | 毛利润同比增长率 lyr                   | (营业收入 lyr - 营业总成本 lyr) / (去年营业收入 lyr - 去年营业总成本 lyr) - 1               | (operating_revenue_lyr_0-total_expense_lyr_0)/(operating_revenue_lyr_1-total_expense_lyr_1)-1           |
| gross_profit_growth_ratio_ttm              | 毛利润同比增长率 ttm                   | (营业收入 ttm - 营业总成本 ttm) / (去年营业收入 ttm - 去年营业总成本 ttm) - 1               | (operating_revenue_ttm_0-total_expense_ttm_0)/(operating_revenue_ttm_4-total_expense_ttm_4)-1           |
| operating_revenue_growth_ratio_lyr         | 营业收入同比增长率 lyr                 | (营业收入 lyr - 去年营业收入 lyr) / 去年营业收入 lyr                                        | (operating_revenue_lyr_0 - operating_revenue_lyr_1) / operating_revenue_lyr_1                           |
| operating_revenue_growth_ratio_ttm         | 营业收入同比增长率 ttm                 | (营业收入 ttm - 去年营业收入 ttm) / 去年营业收入 ttm                                        | (operating_revenue_ttm_0 - operating_revenue_ttm_4) / operating_revenue_ttm_4                           |
| net_asset_growth_ratio_lyr                 | 净资产同比增长率 lyr                   | 归属于母公司所有者权益合计 lyr / 去年归属于母公司所有者权益合计 lyr - 1                     | equity_parent_company_lyr_0 / equity_parent_company_lyr_1 - 1                                           |
| net_asset_growth_ratio_ttm                 | 净资产同比增长率 ttm                   | 归属于母公司所有者权益合计 ttm / 去年归属于母公司所有者权益合计 ttm - 1                     | equity_parent_company_ttm_0 / equity_parent_company_ttm_4 - 1                                           |
| net_asset_growth_ratio_lf                  | 净资产同比增长率 lf                    | 归属于母公司所有者权益合计 mrq / 去年归属于母公司所有者权益合计 mrq - 1                     | equity_parent_company_mrq_0 / equity_parent_company_mrq_4 - 1                                           |
| total_asset_growth_ratio_lyr               | 总资产同比增长率 lyr                   | (总资产 lyr - 去年总资产 lyr) / 去年总资产 lyr                                              | (total_assets_lyr_0 - total_assets_lyr_1) / total_assets_lyr_1                                          |
| total_asset_growth_ratio_ttm               | 总资产同比增长率 ttm                   | (总资产 ttm - 去年总资产 ttm) / 去年总资产 ttm                                              | (total_assets_ttm_0 - total_assets_ttm_4) / total_assets_ttm_4                                          |
| total_asset_growth_ratio_lf                | 总资产同比增长率 lf                    | (总资产 mrq - 去年总资产 mrq) / 去年总资产 mrq                                              | (total_assets_mrq_0 - total_assets_mrq_4) / total_assets_mrq_4                                          |
| net_profit_parent_company_growth_ratio_lyr | 归属母公司所有者的净利润同比增长率 lyr | 归属于母公司所有者的净利润 lyr / 去年归属于母公司所有者的净利润 lyr - 1                     | net_profit_parent_company_lyr_0 / net_profit_parent_company_lyr_1 - 1                                   |
| net_profit_parent_company_growth_ratio_ttm | 归属母公司所有者的净利润同比增长率 ttm | 归属于母公司所有者的净利润 ttm / 去年归属于母公司所有者的净利润 ttm - 1                     | net_profit_parent_company_ttm_0 / net_profit_parent_company_ttm_4 - 1                                   |
| net_cash_flow_growth_ratio_lyr             | 净现金流增长率 lyr                     | 最近年报的现金及现金等价物净增加额 lyr / 上年年报的现金及现金等价物净增加额 lyr - 1         | cash_equivalent_increase_lyr_0 / cash_equivalent_increase_lyr_1 - 1                                     |
| net_cash_flow_growth_ratio_ttm             | 净现金流增长率 ttm                     | 连续四季度的现金及现金等价物净增加额 ttm / 上年连续四季度的现金及现金等价物净增加额 ttm - 1 | cash_equivalent_increase_ttm_0 / cash_equivalent_increase_ttm_4 - 1                                     |
| net_operate_cash_flow_growth_ratio_lyr     | 经营现金流量净额同比增长率 lyr         | 经营活动产生的现金流量净额 lyr / 去年经营活动产生的现金流量净额 lyr - 1                     | cash_flow_from_operating_activities_lyr_0 / cash_flow_from_operating_activities_lyr_1 - 1               |
| net_operate_cash_flow_growth_ratio_ttm     | 经营现金流量净额同比增长率 ttm         | 经营活动产生的现金流量净额 ttm / 去年经营活动产生的现金流量净额 ttm - 1                     | cash_flow_from_operating_activities_ttm_0 / cash_flow_from_operating_activities_ttm_4 - 1               |
| net_investing_cash_flow_growth_ratio_lyr   | 投资现金流量净额同比增长率 lyr         | 投资活动产生的现金流量净额 lyr / 去年投资活动产生的现金流量净额 lyr - 1                     | cash_flow_from_investing_activities_lyr_0 / cash_flow_from_investing_activities_lyr_1 - 1               |
| net_investing_cash_flow_growth_ratio_ttm   | 投资现金流量净额同比增长率 ttm         | 投资活动产生的现金流量净额 ttm / 去年投资活动产生的现金流量净额 ttm - 1                     | cash_flow_from_investing_activities_ttm_0 / cash_flow_from_investing_activities_ttm_4 - 1               |
| net_financing_cash_flow_growth_ratio_lyr   | 筹资现金流量净额同比增长率 lyr         | 筹资活动产生的现金流量净额 lyr / 去年筹资活动产生的现金流量净额 lyr - 1                     | cash_flow_from_financing_activities_lyr_0 / cash_flow_from_financing_activities_lyr_1 - 1               |
| net_financing_cash_flow_growth_ratio_ttm   | 筹资现金流量净额同比增长率 ttm         | 筹资活动产生的现金流量净额 ttm / 去年筹资活动产生的现金流量净额 ttm - 1                     | cash_flow_from_financing_activities_ttm_0 / cash_flow_from_financing_activities_ttm_4 - 1               |

##### 技术指标因子{#technicals}

<br/>

###### 均线类指标 {#technicals_1}

| 因子字段                              | 函数名与默认参数                                                 | 因子计算逻辑                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MACD_DIFF, MACD_DEA, MACD_HIST        | 指数平滑移动平均线 MACD SHORT = 12, LONG = 26, M = 9             | DIFF = EMA(CLOSE, SHORT) - EMA(CLOSE, LONG) <br>DEA = EMA(DIFF, M) <br>HIST = (DIFF - DEA) \* 2                                                                                                                                                                                                                                                                                                |
| TRIX, MATRIX                          | 三重指数平均移动平均 TRIX M1 = 12, M2 = 20                       | TRIX = (TR - REF(TR, 1)) / REF(TR, 1) \* 100; <br>TR = EMA(EMA(EMA(CLOSE, M1), M1), M1) <br>MATRIX= MA(TRIX, M2)                                                                                                                                                                                                                                                                               |
| BOLL, BOLL_UP, BOLL_DOWN              | 布林带 BOLL N = 20, P = 2                                        | BOLL = MA(CLOSE, N) <br>BOLL*UP = BOLL + STD(CLOSE, N) * P <br>BOLL*DOWN = BOLL - STD(CLOSE, N) * P                                                                                                                                                                                                                                                                                            |
| ASI, ASIT                             | 震动升降指标 ASI M1= 26, M2 = 10                                 | LC = REF(CLOSE, 1) <br>AA = ABS(HIGH - LC) <br>BB = ABS(LOW - LC) <br>CC = ABS(HIGH - REF(LOW, 1)) <br>DD = ABS(LC - REF(OPEN, 1)) <br>R = IF((AA BB) & (AA CC), AA + BB / 2 + DD / 4, IF((BB CC) & (BB AA), BB + AA / 2 + DD / 4, CC + DD / 4)) <br>X = (CLOSE - LC + (CLOSE - OPEN) / 2 + LC - REF(OPEN, 1)) <br>SI = X _ 16 / R _ MAX(AA, BB) <br>ASI = SUM(SI, M1) <br>ASIT = MA(ASI, M2)" |
| MA3, 5, 10, 20, 30, 55, 60, 120, 250  | 移动均线 MA N: 3, 5, 10, 20, 30, 55, 60, 120, 250                | MA3, 5, 10… = MA(CLOSE, N)                                                                                                                                                                                                                                                                                                                                                                     |
| EMA3, 5, 10, 20, 30, 55, 60, 120, 250 | 指数移动均线 EMA N: 3, 5, 10, 20, 30, 55, 60, 120, 250           | EMA3, 5, 10... = EMA(CLOSE, N)                                                                                                                                                                                                                                                                                                                                                                 |
| HMA3, 5, 10, 20, 30, 55, 60, 120, 250 | 高价平均线 HMA N: 3, 5, 10, 20, 30, 55, 60, 120, 250             | HMA3, 5, 10... = MA(HIGH, N)                                                                                                                                                                                                                                                                                                                                                                   |
| LMA3, 5, 10, 20, 30, 55, 60, 120, 250 | 低价平均线 LMA N: 3, 5, 10, 20, 30, 55, 60, 120, 250             | LMA3, 5, 10… = MA(LOW, N)…                                                                                                                                                                                                                                                                                                                                                                     |
| VMA3, 5, 10, 20, 30, 55, 60, 120, 250 | 变异平均线 VMA N: 3, 5, 10, 20, 30, 55, 60, 120, 250             | VV = (HIGH+OPEN+LOW+CLOSE)/4 <br>VMA3, 5, 10... = MA(VV, N)…                                                                                                                                                                                                                                                                                                                                   |
| AMV3, 5, 10, 20, 30, 55, 60, 120, 250 | 成本均线 AMV N: 3, 5, 10, 20, 30, 55, 60, 120, 250               | AMOV = VOLUME \* (OPEN + CLOSE) / 2 <br>AMV3, 5, 10… = SUM(AMOV, N) / SUM(VOLUME, N)…                                                                                                                                                                                                                                                                                                          |
| VOL3, 5, 10, 20, 30, 55, 60, 120, 250 | 平均换手率(%) VOL N: 3, 5, 10, 20, 30, 55, 60, 120, 250          | HSL =100\* VOLUME / CAPITAL <br>VOL3, 5, 10... = MA(HSL, N) <br>HSL 代表换手率 <br>CAPITAL 代表流通股本                                                                                                                                                                                                                                                                                        |
| DAVOL5, 10, 20                        | 平均换手率与 120 日平均换手率比值 DAVOL N: 5, 10, 20             | DAVOL3, 5... = VOLN / VOL120                                                                                                                                                                                                                                                                                                                                                                   |
| BBI, BBIBOLL_UP, BBIBOLL_DOWN         | 多空指标 BBIBOLL M1 = 3, M2 = 6, M3 = 12, M4 = 24, M = 6, N = 11 | BBI = (MA(CLOSE, M1) + MA(CLOSE, M2) + MA(CLOSE, M3) + MA(CLOSE, M4)) / 4 <br>BBIBOLL*UP = BBI + M * STD(BBI, N) <br>BBIBOLL*DOWN = BBI - M * STD(BBI, N)"                                                                                                                                                                                                                                     |
| DPO, MADPO                            | 区间震荡线 DPO M1 = 20, M2 = 10, M = 6                           | DPO = CLOSE - REF(MA(CLOSE, M1), M2) <br>MADPO = MA(DPO, M3)                                                                                                                                                                                                                                                                                                                                   |
| MCST                                  | 市场成本 MCST                                                    | MCST = DMA(AMOUNT / VOLUME, 100 \* VOLUME / CAPITAL) <br>AMOUNT 代表成交额 <br>CAPITAL 代表流通股本                                                                                                                                                                                                                                                                                            |

###### 超买超卖指标 {#technicals_2}

| 因子字段                | 函数名与默认参数                                  | 因子计算逻辑                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OBOS                    | 超买超卖指标 OBOS N = 10                          | 过去 N 日股票上涨家数之和 – 过去 N 日股票下跌家数之和。<br>如果当日股票收盘价大于上一交易日股票收盘价，则该股票今日为上涨。                                                                                                                                                                                                                                                                  |
| KDJ_K, KDJ_D, KDJ_J     | 随机波动指标 KDJ N = 9, M1 = 3, M2 = 3            | RSV = (CLOSE - LLV(LOW, N)) / (HHV(HIGH, N) - LLV(LOW, N)) \* 100 <br>K = EMA(RSV, (M1 \* 2 - 1)) <br>D = EMA(K, (M2 \* 2 - 1)) <br>J = K \* 3 - D \* 2                                                                                                                                                                                                                                      |
| RSI6, RSI10             | 相对强弱指标 RSI N1 = 6, 10                       | LC = REF(CLOSE, 1) <br>RSI = MA(MAX(CLOSE - LC, 0), N) / MA(ABS(CLOSE - LC), N) \* 100                                                                                                                                                                                                                                                                                                       |
| WR                      | 威廉指标 WR N = 10, L1 = 6                        | WR = (HHV(HIGH, N) - CLOSE) / (HHV(HIGH, N) - LLV(LOW, N)) \* 100                                                                                                                                                                                                                                                                                                                            |
| LWR1, LWR2              | LWR 威廉指标 LWR N = 9, M1 = 3, M2 = 3            | RSV = (HHV(HIGH,N)-CLOSE)/(HHV(HIGH,N)-LLV(LOW,N))\*100 <br>LWR1 = SMA_CN(RSV,M1,1) <br>LWR2 = SMA_CN(LWR1,M2,1)                                                                                                                                                                                                                                                                             |
| BIAS5, BIAS10, BIAS20   | 乖离率 BIAS L1 = 5, 10, 20                        | (CLOSE - MA(CLOSE, L1)) / MA(CLOSE, L1) \* 100                                                                                                                                                                                                                                                                                                                                               |
| BIAS36, BIAS612, MABIAS | 36 乖离 BIAS36                                    | BIAS36 = MA(CLOSE, 3) – MA(CLOSE, 6) <br>BIAS612 = MA(CLOSE, 6) – MA(CLOSE, 12) <br>MABIAS = MA(BIAS36, M)                                                                                                                                                                                                                                                                                   |
| ACCER                   | 幅度涨速 ACCER N = 8                              | ACCER = SLOPE (CLOSE, N) / CLOSE                                                                                                                                                                                                                                                                                                                                                             |
| CYF                     | 市场能量 CYF N = 21                               | CYF = 100 – 100 / (1 + EMA(HSL, N ))                                                                                                                                                                                                                                                                                                                                                         |
| SWL, SWS                | 分水岭 FSL                                        | SWL = (EMA(CLOSE,5)*7+EMA(CLOSE,10)*3)/10 <br>SWS = DMA(EMA(CLOSE,12),MAX(1,100*(SUM(VOLUME,5)/(3*CAPITAL)))) <br>CAPITAL 代表流通股本                                                                                                                                                                                                                                                       |
| ADTM, MAADTM            | 动态买卖气指标 ADTM N = 23, M = 8                 | DTM = IF(OPEN<=REF(OPEN,1),0,MAX((HIGH-OPEN),(OPEN-REF(OPEN,1)))) <br>DBM = IF(OPEN>=REF(OPEN,1),0,MAX((OPEN-LOW),(OPEN-REF(OPEN,1)))) <br>STM = SUM(DTM,N) <br>SBM = SUM(DBM,N) <br>ADTM = IF(STM>SBM,(STM-SBM)/STM,IF(STM=SBM,0,(STM-SBM)/SBM)) <br>MAADTM = MA(ADTM, M)                                                                                                                   |
| TR, ATR                 | 真实波幅 ATR N = 14，M1 = 9                       | TR = SUM(MAX(MAX(HIGH - LOW, ABS(HIGH - REF(CLOSE, 1))), ABS(LOW - REF(CLOSE, 1))), M1) <br>ATR = MA(TR, N)                                                                                                                                                                                                                                                                                  |
| DKX, MADKX              | 多空线 DKX M = 10                                 | MID = (3*CLOSE+LOW+OPEN+HIGH)/6 <br>DKX = (20*MID+19*REF(MID,1)+18*REF(MID,2)+17*REF(MID,3)+16*REF(MID,4)+15*REF(MID,5)+14*REF(MID,6)+ <br>13*REF(MID,7)+12*REF(MID,8)+11*REF(MID,9)+10*REF(MID,10)+9*REF(MID,11)+8*REF(MID,12)+7*REF(MID,13)+ <br>6*REF(MID,14)+5*REF(MID,15)+4*REF(MID,16)+3*REF(MID,17)+2*REF(MID,18)+REF(MID,20))/210 <br>MADKX = MA(DKX, M)                             |
| TAPI, MATAPI            | 加权指数成交值 TAPI M = 6                         | TAPI = AMOUNT / CLOSE <br>MATAPI = MA(TAPI, M) <br>AMOUNT 代表成交额                                                                                                                                                                                                                                                                                                                         |
| OSC                     | 变动速率线 OSC N = 10                             | 100 \* (CLOSE – MA(CLOSE, N))                                                                                                                                                                                                                                                                                                                                                                |
| CCI                     | 商品路径指标 CCI N = 14                           | CCI = (TYP – MA(TYP, N)) / (0.015 \* AVEDEV (TYP, N)) <br>TYP = (HIGH + LOW + CLOSE) / 3                                                                                                                                                                                                                                                                                                     |
| ROC                     | 变形率指标 ROC N = 12                             | ROC = 100 \* (CLOSE – REF(CLOSE, N) / REF(CLOSE, N)                                                                                                                                                                                                                                                                                                                                          |
| MFI                     | 资金流量指标 MFI N = 14                           | TYP = (HIGH + LOW + CLOSE) / 3 <br>V1 = SUM(IF(TYP > REF(TYP, 1), TYP \* VOLUME, 0), N) / SUM(IF(TYP < REF(TYP, 1), TYP \* VOLUME, 0), N) <br>MFI = 100 - ( 100 / ( 1 + V1 ) )                                                                                                                                                                                                               |
| MTM, MAMTM              | 动量线 MTM N = 14                                 | MTM = CLOSE – REF(CLOSE, N) <br>MAMTM = MA(MTM, M)                                                                                                                                                                                                                                                                                                                                           |
| MARSI6, MARSI10         | 相对强弱平均线 MARSI N = 6, 10                    | LC = REF(CLOSE, 1) <br>RSI = SMA(MAX(CLOSE - LC, 0), N) / SMA(ABS(CLOSE - LC), N) \* 100 <br>MARSI = MA(RSI, N)                                                                                                                                                                                                                                                                              |
| SKD_K, SKD_D            | 慢速随机指标 SKD N = 9, M = 3                     | LOWV = LLV(LOW, N) <br>HIGHV = HHV(HIGH, N) <br>RSV = EMA((CLOSE – LOWV) / (HIGHV – LOWV) \* 100, M) <br>SKD_K = EMA(RSV , M) <br>SKD_D = MA(SKD_K, M)                                                                                                                                                                                                                                       |
| UDL, MAUDL              | 引力线 UDL N1 = 3, N2 = 5, N3 = 10, N4 = 20, M =6 | UDL = (MA(CLOSE,N1)+MA(CLOSE,N2)+MA(CLOSE,N3)+MA(CLOSE,N4))/4 <br>MAUDL = MA(UDL,M)                                                                                                                                                                                                                                                                                                          |
| DI1, DI2, ADX, ADXR     | 趋向指标 DMI M1 = 14, M2 = 6                      | TR = SUM(MAX(MAX(HIGH - LOW, ABS(HIGH - REF(CLOSE, 1))), ABS(LOW - REF(CLOSE, 1))), M1) <br>HD = HIGH - REF(HIGH, 1) <br>LD = REF(LOW, 1) - LOW <br>DMP = SUM(IF((HD 0) & (HD LD), HD, 0), M1) <br>DMM = SUM(IF((LD 0) & (LD HD), LD, 0), M1) <br>DI1 = DMP \* 100 / TR <br>DI2 = DMM \* 100 / TR <br>ADX = MA(ABS(DI2 - DI1) / (DI1 + DI2) \* 100, M2) <br>ADXR = (ADX + REF(ADX, M2)) / 2" |

###### 能量指标 {#technicals_3}

| 因子字段                                      | 函数名与默认参数                                      | 因子计算逻辑                                                                                                                                                                                                                         |
| --------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| AR, BR                                        | 人气意愿指标 ARBR M1 = 26                             | AR = SUM(HIGH - OPEN, M1) / SUM(OPEN - LOW, M1) \* 100 <br>BR = SUM(MAX(0, HIGH - REF(CLOSE, 1)), M1) / SUM(MAX(0, REF(CLOSE, 1) - LOW), M1) \* 100                                                                                  |
| VR, MAVR                                      | 容量比例 VR M1 = 26, M = 6                            | LC = REF(CLOSE, 1) <br>VR = SUM(IF(CLOSE LC, VOL, 0), M1) / SUM(IF(CLOSE <= LC, VOL, 0), M1) \* 100 <br>MAVR = MA(VR, M)                                                                                                             |
| CR,MACR1, MACR2, MACR3, MACR4                 | CR 指标 CR N = 26, M1 = 10, M2 = 20, M3 = 40, M4 = 62 | MID = REF(HIGH+LOW, 1) / 2 <br>CR = SUM(MAX(0,HIGH-MID),N)/SUM(MAX(0,MID-LOW),N)\*100 <br>MACR1 = REF(MA(CR,M1),1+M1/2.5) <br>MACR2 = REF(MA(CR,M2),1+M2/2.5) <br>MACR3 = REF(MA(CR,M3),1+M3/2.5) <br>MACR4= REF(MA(CR,M4),1+M4/2.5) |
| MASS, MAMASS                                  | 梅斯线 MASS N1 = 9, N2 = 25, M = 6                    | MASS = SUM(MA(HIGH-LOW,N1)/MA(MA(HIGH-LOW,N1),N1),N2) <br>MAMASS = MA(MASS, M)                                                                                                                                                       |
| SY                                            | 心理线 SY N = 9                                       | SY = COUNT(CLOSE>REF(CLOSE,1),N)/N\*100                                                                                                                                                                                              |
| PCNT                                          | 幅度比 PCNT                                           | PCNT = (CLOSE-REF(CLOSE,1))/CLOSE\*100;                                                                                                                                                                                              |
| CYR, MACYR                                    | 市场强弱 CYR N = 13, M = 5                            | DIVE = 0.01*EMA(AMOUNT,N)/EMA(VOLUME,N) <br>CYR = (DIVE/REF(DIVE,1)-1)*100 <br>MACYR = MA(CYR, M) <br>AMOUNT 代表成交额                                                                                                              |
| AMP1,AMP3,AMP5,<br>AMP10,AMP20,AMP60          | 振幅 AMP N:1，3，5，10，20，60                        | AMP1,3,5… = (HHV(HIGH,N)-LLV(LOW,N))/REF(CLOSE,N)                                                                                                                                                                                    |
| WMA3,WMA5,WMA10,WMA20,<br>WMA60,WMA120,WMA250 | 加权移动平均线 WMA N:3，5，10，20，60，120，250       | WMA1,3,5… = (CLOSE\*N+REF(CLOSE, 1)\*(N-1)+…+REF(CLOSE, N-1)/(1+2+…+N))                                                                                                                                                              |
| VOLT20, VOLT60                                | 近 20 日/60 日波动率 N:20,60                          | 20 日/60 日收盘价的标准差                                                                                                                                                                                                            |
| MDD20，MDD60                                  | 近 20 日/60 日最大回撤 N:20,60                        | 20 日/60 日收盘价的最大回撤                                                                                                                                                                                                          |
| AROON_UP，AROON_DOWN                          | 阿隆指标 N=14                                         | AROON_UP = [(计算期天数-最高价后的天数)/计算期天数]*100 <br> AROON_DOWN = [(计算期天数-最低价后的天数)/计算期天数]*100                                                                                                               |
| QTYR_5_20                                     | 5 日 20 日量比 N=5, M=20                              | MA(VOLUME, N) / MA(VOLUME, M)                                                                                                                                                                                                        |
| OBV                                           | 能量潮 OBV                                            | OBV=REF(OBV, 1) + sgn × VOLUME <br> 其中，sgn 是符号函数，其数值由下式决定：<br> sgn=1 , CLOSE>REF(CLOSE, 1) <br> sgn=0, CLOSE = REF(CLOSE, 1) <br> sgn=-1 , CLOSE< REF(CLOSE, 1)                                                    |

<br/>

##### alpha101 因子{#alpha101}

<b>见下方范例</b>

<br/>

#### 范例 {#rqdata-API-get_factor-example}

- 获取财务指标因子数据

```python
[In]
get_factor(['000001.XSHE','000002.XSHE'],'debt_to_equity_ratio',start_date='20180102',end_date='20180103')
[Out]

                                  debt_to_equity_ratio
order_book_id      date
000002.XSHE        2018-01-02     7.3097
                   2018-01-03     7.3097
000001.XSHE        2018-01-02     13.3848
                   2018-01-03     13.3848

```

- 获取技术指标因子数据

```python
[In]
get_factor(['000001.XSHE','600000.XSHG'],['MACD_DIFF','OBOS','AR'],'20200401','20200402')
[Out]
                               MACD_DIFF	OBOS	AR
order_book_id	date
600000.XSHG	2020-04-01	-0.252972	2.0	86.486486
            2020-04-02	-0.237592	4.0	79.701493
000001.XSHE	2020-04-01	-0.564380	2.0	110.490694
            2020-04-02	-0.530793	4.0	105.396290

```

- 获取 alpha101 因子数据

```python
[In]
get_factor(['000001.XSHE', '600000.XSHG'],'WorldQuant_alpha010', '20190601', '20190610')

[Out]
                        WorldQuant_alpha010
order_book_id	date
600000.XSHG	2019-06-03	0.162771
            2019-06-04	0.255633
            2019-06-05	0.789430
            2019-06-06	0.437743
            2019-06-10	0.935448
000001.XSHE	2019-06-03	0.093489
            2019-06-04	0.281502
            2019-06-05	0.222253
            2019-06-06	0.415231
            2019-06-10	0.134391


```

```
CLOSE = Factor('close')
RETURNS = (CLOSE - REF(CLOSE, 1)) / REF(CLOSE, 1)
CAP = Factor('market_cap')
VWAP = Factor('total_turnover') / Factor('volume)

alpha001 = (RANK(TS_ARGMAX(SIGNEDPOWER(IF((RETURNS < 0), STDDEV(RETURNS, 20), CLOSE), 2.), 5)) - 0.5)

alpha002 = (-1 * CORRELATION(RANK(DELTA(LOG(VOLUME), 2)), RANK(((CLOSE - OPEN) / OPEN)), 6))

alpha003 = (-1 * CORRELATION(RANK(OPEN), RANK(VOLUME), 10))

alpha004 = (-1 * TS_RANK(RANK(LOW), 9))

alpha005 = (RANK((OPEN - (SUM(VWAP, 10) / 10))) * (-1 * ABS(RANK((CLOSE - VWAP)))))

alpha006 = (-1 * CORRELATION(OPEN, VOLUME, 10))

alpha007 = IF((ADV(20) < VOLUME), ((-1 * TS_RANK(ABS(DELTA(CLOSE, 7)), 60)) * SIGN(DELTA(CLOSE, 7))), (-1 * 1))

alpha008 = (-1 * RANK(((SUM(OPEN, 5) * SUM(RETURNS, 5)) - DELAY((SUM(OPEN, 5) * SUM(RETURNS, 5)), 10))))

alpha009 = IF((0 < TS_MIN(DELTA(CLOSE, 1), 5)), DELTA(CLOSE, 1), (IF((TS_MAX(DELTA(CLOSE, 1), 5) < 0), DELTA(CLOSE, 1), (-1 * DELTA(CLOSE, 1)))))

alpha010 = RANK(IF((0 < TS_MIN(DELTA(CLOSE, 1), 4)), DELTA(CLOSE, 1), IF((TS_MAX(DELTA(CLOSE, 1), 4) < 0), DELTA(CLOSE, 1), (-1 * DELTA(CLOSE, 1)))))

alpha011 = ((RANK(TS_MAX((VWAP - CLOSE), 3)) + RANK(TS_MIN((VWAP - CLOSE), 3))) * RANK(DELTA(VOLUME, 3)))

alpha012 = (SIGN(DELTA(VOLUME, 1)) * (-1 * DELTA(CLOSE, 1)))

alpha013 = (-1 * RANK(COVARIANCE(RANK(CLOSE), RANK(VOLUME), 5)))

alpha014 = ((-1 * RANK(DELTA(RETURNS, 3))) * CORRELATION(OPEN, VOLUME, 10))

alpha015 = (-1 * SUM(RANK(CORRELATION(RANK(HIGH), RANK(VOLUME), 3)), 3))

alpha016 = (-1 * RANK(COVARIANCE(RANK(HIGH), RANK(VOLUME), 5)))

alpha017 = (((-1 * RANK(TS_RANK(CLOSE, 10))) * RANK(DELTA(DELTA(CLOSE, 1), 1))) * RANK(TS_RANK((VOLUME / ADV(20)), 5)))

alpha018 = (-1 * RANK(((STDDEV(ABS((CLOSE - OPEN)), 5) + (CLOSE - OPEN)) + CORRELATION(CLOSE, OPEN, 10))))

alpha019 = ((-1 * SIGN(((CLOSE - DELAY(CLOSE, 7)) + DELTA(CLOSE, 7)))) * (1 + RANK((1 + SUM(RETURNS, 250)))))

alpha020 = (((-1 * RANK((OPEN - DELAY(HIGH, 1)))) * RANK((OPEN - DELAY(CLOSE, 1)))) * RANK((OPEN - DELAY(LOW, 1))))

alpha021 = IF((((SUM(CLOSE, 8) / 8) + STDDEV(CLOSE, 8)) < (SUM(CLOSE, 2) / 2)), (-1 * 1), IF(((SUM(CLOSE, 2) / 2) < ((SUM(CLOSE, 8) / 8) - STDDEV(CLOSE, 8))), 1, IF(((1 < (VOLUME / ADV(20))) | ((VOLUME / ADV(20)) == 1)), 1, (-1 * 1))))

alpha022 = (-1 * (DELTA(CORRELATION(HIGH, VOLUME, 5), 5) * RANK(STDDEV(CLOSE, 20))))

alpha023 = IF(((SUM(HIGH, 20) / 20) < HIGH), (-1 * DELTA(HIGH, 2)), 0)

alpha024 = IF((((DELTA((SUM(CLOSE, 100) / 100), 100) / DELAY(CLOSE, 100)) < 0.05) | ((DELTA((SUM(CLOSE, 100) / 100), 100) / DELAY(CLOSE, 100)) == 0.05)), (-1 * (CLOSE - TS_MIN(CLOSE, 100))), (-1 * DELTA(CLOSE, 3)))

alpha025 = RANK(((((-1 * RETURNS) * ADV(20)) * VWAP) * (HIGH - CLOSE)))

alpha026 = (-1 * TS_MAX(CORRELATION(TS_RANK(VOLUME, 5), TS_RANK(HIGH, 5), 5), 3))

alpha027 = IF((0.5 < RANK((SUM(CORRELATION(RANK(VOLUME), RANK(VWAP), 6), 2) / 2.0))), (-1 * 1), 1)

alpha028 = SCALE(((CORRELATION(ADV(20), LOW, 5) + ((HIGH + LOW) / 2)) - CLOSE))

alpha029 = (MIN(PRODUCT(RANK(RANK(SCALE(LOG(SUM(TS_MIN(RANK(RANK((-1 * RANK(DELTA((CLOSE - 1), 5))))), 2), 1))))), 1), 5) + TS_RANK(DELAY((-1 * RETURNS), 6), 5))

alpha030 = (((1.0 - RANK(((SIGN((CLOSE - DELAY(CLOSE, 1))) + SIGN((DELAY(CLOSE, 1) - DELAY(CLOSE, 2)))) + SIGN((DELAY(CLOSE, 2) - DELAY(CLOSE, 3)))))) * SUM(VOLUME, 5)) / SUM(VOLUME, 20))

alpha031 = ((RANK(RANK(RANK(DECAY_LINEAR((-1 * RANK(RANK(DELTA(CLOSE, 10)))), 10)))) + RANK((-1 * DELTA(CLOSE, 3)))) + SIGN(SCALE(CORRELATION(ADV(20), LOW, 12))))

alpha032 = (SCALE(((SUM(CLOSE, 7) / 7) - CLOSE)) + (20 * SCALE(CORRELATION(VWAP, DELAY(CLOSE, 5), 230))))

alpha033 = RANK((-1 * ((1 - (OPEN / CLOSE))**1)))

alpha034 = RANK(((1 - RANK((STDDEV(RETURNS, 2) / STDDEV(RETURNS, 5)))) + (1 - RANK(DELTA(CLOSE, 1)))))

alpha035 = ((TS_RANK(VOLUME, 32) * (1 - TS_RANK(((CLOSE + HIGH) - LOW), 16))) * (1 - TS_RANK(RETURNS, 32)))

alpha036 = (((((2.21 * RANK(CORRELATION((CLOSE - OPEN), DELAY(VOLUME, 1), 15))) + (0.7 * RANK((OPEN - CLOSE)))) + (0.73 * RANK(TS_RANK(DELAY((-1 * RETURNS), 6), 5)))) + RANK(ABS(CORRELATION(VWAP, ADV(20), 6)))) + (0.6 * RANK((((SUM(CLOSE, 200) / 200) - OPEN) * (CLOSE - OPEN)))))

alpha037 = (RANK(CORRELATION(DELAY((OPEN - CLOSE), 1), CLOSE, 200)) + RANK((OPEN - CLOSE)))

alpha038 = ((-1 * RANK(TS_RANK(CLOSE, 10))) * RANK((CLOSE / OPEN)))

alpha039 = ((-1 * RANK((DELTA(CLOSE, 7) * (1 - RANK(DECAY_LINEAR((VOLUME / ADV(20)), 9)))))) * (1 + RANK(SUM(RETURNS, 250))))

alpha040 = ((-1 * RANK(STDDEV(HIGH, 10))) * CORRELATION(HIGH, VOLUME, 10))

alpha041 = (((HIGH * LOW)**0.5) - VWAP)

alpha042 = (RANK((VWAP - CLOSE)) / RANK((VWAP + CLOSE)))

alpha043 = (TS_RANK((VOLUME / ADV(20)), 20) * TS_RANK((-1 * DELTA(CLOSE, 7)), 8))

alpha044 = (-1 * CORRELATION(HIGH, RANK(VOLUME), 5))

alpha045 = (-1 * ((RANK((SUM(DELAY(CLOSE, 5), 20) / 20)) * CORRELATION(CLOSE, VOLUME, 2)) * RANK(CORRELATION(SUM(CLOSE, 5), SUM(CLOSE, 20), 2))))

alpha046 = IF((0.25 < (((DELAY(CLOSE, 20) - DELAY(CLOSE, 10)) / 10) - ((DELAY(CLOSE, 10) - CLOSE) / 10))), (-1 * 1), IF(((((DELAY(CLOSE, 20) - DELAY(CLOSE, 10)) / 10) - ((DELAY(CLOSE, 10) - CLOSE) / 10)) < 0), 1, ((-1 * 1) * (CLOSE - DELAY(CLOSE, 1)))))

alpha047 = ((((RANK((1 / CLOSE)) * VOLUME) / ADV(20)) * ((HIGH * RANK((HIGH - CLOSE))) / (SUM(HIGH, 5) / 5))) - RANK((VWAP - DELAY(VWAP, 5))))

alpha048 = (INDUSTRY_NEUTRALIZE(((CORRELATION(DELTA(CLOSE, 1), DELTA(DELAY(CLOSE, 1), 1), 250) * DELTA(CLOSE, 1)) / CLOSE)) / SUM(((DELTA(CLOSE, 1) / DELAY(CLOSE, 1))**2), 250))

alpha049 = IF(((((DELAY(CLOSE, 20) - DELAY(CLOSE, 10)) / 10) - ((DELAY(CLOSE, 10) - CLOSE) / 10)) < (-1 * 0.1)), 1, ((-1 * 1) * (CLOSE - DELAY(CLOSE, 1))))

alpha050 = (-1 * TS_MAX(RANK(CORRELATION(RANK(VOLUME), RANK(VWAP), 5)), 5))

alpha051 = IF(((((DELAY(CLOSE, 20) - DELAY(CLOSE, 10)) / 10) - ((DELAY(CLOSE, 10) - CLOSE) / 10)) < (-1 * 0.05)), 1, ((-1 * 1) * (CLOSE - DELAY(CLOSE, 1))))

alpha052 = ((((-1 * TS_MIN(LOW, 5)) + DELAY(TS_MIN(LOW, 5), 5)) * RANK(((SUM(RETURNS, 240) - SUM(RETURNS, 20)) / 220))) * TS_RANK(VOLUME, 5))

alpha053 = (-1 * DELTA((((CLOSE - LOW) - (HIGH - CLOSE)) / (CLOSE - LOW)), 9))

alpha054 = ((-1 * ((LOW - CLOSE) * (OPEN**5))) / ((LOW - HIGH) * (CLOSE**5)))

alpha055 = (-1 * CORRELATION(RANK(((CLOSE - TS_MIN(LOW, 12)) / (TS_MAX(HIGH, 12) - TS_MIN(LOW, 12)))), RANK(VOLUME), 6))

alpha056 = (0 - (1 * (RANK((SUM(RETURNS, 10) / SUM(SUM(RETURNS, 2), 3))) * RANK((RETURNS * CAP)))))

alpha057 = (0 - (1 * ((CLOSE - VWAP) / DECAY_LINEAR(RANK(TS_ARGMAX(CLOSE, 30)), 2))))

alpha058 = (-1 * TS_RANK(DECAY_LINEAR(CORRELATION(INDUSTRY_NEUTRALIZE(VWAP), VOLUME, 4), 8), 6))

alpha059 = (-1 * TS_RANK(DECAY_LINEAR(CORRELATION(INDUSTRY_NEUTRALIZE(((VWAP * 0.728317) + (VWAP * (1 - 0.728317)))), VOLUME, 4), 16), 8))

alpha060 = (0 - (1 * ((2 * SCALE(RANK(((((CLOSE - LOW) - (HIGH - CLOSE)) / (HIGH - LOW)) * VOLUME)))) - SCALE(RANK(TS_ARGMAX(CLOSE, 10))))))

alpha061 = (RANK((VWAP - TS_MIN(VWAP, 16))) < RANK(CORRELATION(VWAP, ADV(180), 18)))

alpha062 = ((RANK(CORRELATION(VWAP, SUM(ADV(20), 22), 10)) < RANK(((RANK(OPEN) + RANK(OPEN)) < (RANK(((HIGH + LOW) / 2)) + RANK(HIGH))))) * -1)

alpha063 = ((RANK(DECAY_LINEAR(DELTA(INDUSTRY_NEUTRALIZE(CLOSE), 2), 8)) - RANK(DECAY_LINEAR(CORRELATION(((VWAP * 0.318108) + (OPEN * (1 - 0.318108))), SUM(ADV(180), 37), 14), 12))) * -1)

alpha064 = ((RANK(CORRELATION(SUM(((OPEN * 0.178404) + (LOW * (1 - 0.178404))), 13), SUM(ADV(120), 13), 17)) < RANK(DELTA(((((HIGH + LOW) / 2) * 0.178404) + (VWAP * (1 - 0.178404))), 4))) * -1)

alpha065 = ((RANK(CORRELATION(((OPEN * 0.00817205) + (VWAP * (1 - 0.00817205))), SUM(ADV(60), 9), 6)) < RANK((OPEN - TS_MIN(OPEN, 14)))) * -1)

alpha066 = ((RANK(DECAY_LINEAR(DELTA(VWAP, 4), 7)) + TS_RANK(DECAY_LINEAR(((((LOW * 0.96633) + (LOW * (1 - 0.96633))) - VWAP) / (OPEN - ((HIGH + LOW) / 2))), 11), 7)) * -1)

alpha067 = ((RANK((HIGH - TS_MIN(HIGH, 2)))**RANK(CORRELATION(INDUSTRY_NEUTRALIZE(VWAP), INDUSTRY_NEUTRALIZE(ADV(20)), 6))) * -1)

alpha068 = ((TS_RANK(CORRELATION(RANK(HIGH), RANK(ADV(15)), 9), 14) < RANK(DELTA(((CLOSE * 0.518371) + (LOW * (1 - 0.518371))), 1))) * -1)

alpha069 = ((RANK(TS_MAX(DELTA(INDUSTRY_NEUTRALIZE(VWAP), 3), 5))**TS_RANK(CORRELATION(((CLOSE * 0.490655) + (VWAP * (1 - 0.490655))), ADV(20), 5), 9)) * -1)

alpha070 = ((RANK(DELTA(VWAP, 1))**TS_RANK(CORRELATION(INDUSTRY_NEUTRALIZE(CLOSE), ADV(50), 18), 18)) * -1)

alpha071 = MAX(TS_RANK(DECAY_LINEAR(CORRELATION(TS_RANK(CLOSE, 3), TS_RANK(ADV(180), 12), 18), 4), 16), TS_RANK(DECAY_LINEAR((RANK(((LOW + OPEN) - (VWAP + VWAP)))**2), 16), 4))

alpha072 = (RANK(DECAY_LINEAR(CORRELATION(((HIGH + LOW) / 2), ADV(40), 9), 10)) / RANK(DECAY_LINEAR(CORRELATION(TS_RANK(VWAP, 4), TS_RANK(VOLUME, 19), 7), 3)))

# Modify DELTA(VWAP, 4.72775) to DELTA(VWAP, 5)
alpha073 = (MAX(RANK(DECAY_LINEAR(DELTA(VWAP, 5), 3)), TS_RANK(DECAY_LINEAR(((DELTA(((OPEN * 0.147155) + (LOW * (1 - 0.147155))), 2) / ((OPEN * 0.147155) + (LOW * (1 - 0.147155)))) * -1), 3), 17)) * -1)

alpha074 = ((RANK(CORRELATION(CLOSE, SUM(ADV(30), 37), 15)) < RANK(CORRELATION(RANK(((HIGH * 0.0261661) + (VWAP * (1 - 0.0261661)))), RANK(VOLUME), 11))) * -1)

alpha075 = (RANK(CORRELATION(VWAP, VOLUME, 4)) < RANK(CORRELATION(RANK(LOW), RANK(ADV(50)), 12)))

# Modify TS_RANK(CORRELATION(INDUSTRY_NEUTRALIZE(LOW), ADV(81), 8), 19.569) to TS_RANK(CORRELATION(INDUSTRY_NEUTRALIZE(LOW), ADV(81), 8), 20)
alpha076 = (MAX(RANK(DECAY_LINEAR(DELTA(VWAP, 1), 12)), TS_RANK(DECAY_LINEAR(TS_RANK(CORRELATION(INDUSTRY_NEUTRALIZE(LOW), ADV(81), 8), 20), 17), 19)) * -1)

alpha077 = MIN(RANK(DECAY_LINEAR(((((HIGH + LOW) / 2) + HIGH) - (VWAP + HIGH)), 20)), RANK(DECAY_LINEAR(CORRELATION(((HIGH + LOW) / 2), ADV(40), 3), 6)))

alpha078 = (RANK(CORRELATION(SUM(((LOW * 0.352233) + (VWAP * (1 - 0.352233))), 20), SUM(ADV(40), 20), 7))**RANK(CORRELATION(RANK(VWAP), RANK(VOLUME), 6)))

alpha079 = (RANK(DELTA(INDUSTRY_NEUTRALIZE(((CLOSE * 0.60733) + (OPEN * (1 - 0.60733)))), 1)) < RANK(CORRELATION(TS_RANK(VWAP, 4), TS_RANK(ADV(150), 9), 15)))

alpha080 = ((RANK(SIGN(DELTA(INDUSTRY_NEUTRALIZE(((OPEN * 0.868128) + (HIGH * (1 - 0.868128)))), 4)))**TS_RANK(CORRELATION(HIGH, ADV(10), 5), 6)) * -1)

alpha081 = ((RANK(LOG(PRODUCT(RANK((RANK(CORRELATION(VWAP, SUM(ADV(10), 50), 8))**4)), 15))) < RANK(CORRELATION(RANK(VWAP), RANK(VOLUME), 5))) * -1)

alpha082 = (MIN(RANK(DECAY_LINEAR(DELTA(OPEN, 1), 15)), TS_RANK(DECAY_LINEAR(CORRELATION(INDUSTRY_NEUTRALIZE(VOLUME), ((OPEN * 0.634196) + (OPEN * (1 - 0.634196))), 17), 7), 13)) * -1)

alpha083 = ((RANK(DELAY(((HIGH - LOW) / (SUM(CLOSE, 5) / 5)), 2)) * RANK(RANK(VOLUME))) / (((HIGH - LOW) / (SUM(CLOSE, 5) / 5)) / (VWAP - CLOSE)))

alpha084 = SIGNEDPOWER(TS_RANK((VWAP - TS_MAX(VWAP, 15)), 21), DELTA(CLOSE, 5))

alpha085 = (RANK(CORRELATION(((HIGH * 0.876703) + (CLOSE * (1 - 0.876703))), ADV(30), 10))**RANK(CORRELATION(TS_RANK(((HIGH + LOW) / 2), 4), TS_RANK(VOLUME, 10), 7)))

alpha086 = ((TS_RANK(CORRELATION(CLOSE, SUM(ADV(20), 15), 6), 20) < RANK(((OPEN + CLOSE) - (VWAP + OPEN)))) * -1)

alpha087 = (MAX(RANK(DECAY_LINEAR(DELTA(((CLOSE * 0.369701) + (VWAP * (1 - 0.369701))), 2), 3)), TS_RANK(DECAY_LINEAR(ABS(CORRELATION(INDUSTRY_NEUTRALIZE(ADV(81)), CLOSE, 13)), 5), 14)) * -1)

# Modify TS_RANK(ADV(60), 20.6966) to TS_RANK(ADV(60), 21),
alpha088 = MIN(RANK(DECAY_LINEAR(((RANK(OPEN) + RANK(LOW)) - (RANK(HIGH) + RANK(CLOSE))), 8)), TS_RANK(DECAY_LINEAR(CORRELATION(TS_RANK(CLOSE, 8), TS_RANK(ADV(60), 21), 8), 7), 3))

alpha089 = (TS_RANK(DECAY_LINEAR(CORRELATION(((LOW * 0.967285) + (LOW * (1 - 0.967285))), ADV(10), 7), 6), 4) - TS_RANK(DECAY_LINEAR(DELTA(INDUSTRY_NEUTRALIZE(VWAP), 3), 10), 15))

alpha090 = ((RANK((CLOSE - TS_MAX(CLOSE, 5)))**TS_RANK(CORRELATION(INDUSTRY_NEUTRALIZE(ADV(40)), LOW, 5), 3)) * -1)

alpha091 = ((TS_RANK(DECAY_LINEAR(DECAY_LINEAR(CORRELATION(INDUSTRY_NEUTRALIZE(CLOSE), VOLUME, 10), 16), 4), 5) - RANK(DECAY_LINEAR(CORRELATION(VWAP, ADV(30), 4), 3))) * -1)

alpha092 = MIN(TS_RANK(DECAY_LINEAR(AS_FLOAT((((HIGH + LOW) / 2) + CLOSE) < (LOW + OPEN)), 15), 19), TS_RANK(DECAY_LINEAR(CORRELATION(RANK(LOW), RANK(ADV(30)), 8), 7), 7))

alpha093 = (TS_RANK(DECAY_LINEAR(CORRELATION(INDUSTRY_NEUTRALIZE(VWAP), ADV(81), 17), 20), 8) / RANK(DECAY_LINEAR(DELTA(((CLOSE * 0.524434) + (VWAP * (1 - 0.524434))), 3), 16)))

alpha094 = ((RANK((VWAP - TS_MIN(VWAP, 12)))**TS_RANK(CORRELATION(TS_RANK(VWAP, 20), TS_RANK(ADV(60), 4), 18), 3)) * -1)

alpha095 = (RANK((OPEN - TS_MIN(OPEN, 12))) < TS_RANK((RANK(CORRELATION(SUM(((HIGH + LOW) / 2), 19), SUM(ADV(40), 19), 13))**5), 12))

# Modify TS_RANK(ADV(60), 4.13242) to TS_RANK(ADV(60), 4)
alpha096 = MAX(TS_RANK(DECAY_LINEAR(CORRELATION(RANK(VWAP), RANK(VOLUME), 4), 4), 8), TS_RANK(DECAY_LINEAR(TS_ARGMAX(CORRELATION(TS_RANK(CLOSE, 7), TS_RANK(ADV(60), 4), 4), 13), 14), 13)) * -1

# Modify TS_RANK(LOW, 7.87871) to TS_RANK(LOW, 8)
alpha097 = ((RANK(DECAY_LINEAR(DELTA(INDUSTRY_NEUTRALIZE(((LOW * 0.721001) + (VWAP * (1 - 0.721001)))), 3), 20)) - TS_RANK(DECAY_LINEAR(TS_RANK(CORRELATION(TS_RANK(LOW, 8), TS_RANK(ADV(60), 17), 5), 19), 16), 7)) * -1)

alpha098 = (RANK(DECAY_LINEAR(CORRELATION(VWAP, SUM(ADV(5), 26), 6), 7)) - RANK(DECAY_LINEAR(TS_RANK(TS_ARGMIN(CORRELATION(RANK(OPEN), RANK(ADV(15)), 21), 9), 7), 8)))

alpha099 = ((RANK(CORRELATION(SUM(((HIGH + LOW) / 2), 20), SUM(ADV(60), 20), 9)) < RANK(CORRELATION(LOW, VOLUME, 6))) * -1)

alpha100 = (0 - (1 * (((1.5 * SCALE(INDUSTRY_NEUTRALIZE(INDUSTRY_NEUTRALIZE(RANK(((((CLOSE - LOW) - (HIGH - CLOSE)) / (HIGH - LOW)) * VOLUME)))))) - SCALE(INDUSTRY_NEUTRALIZE((CORRELATION(CLOSE, RANK(ADV(20)), 5) - RANK(TS_ARGMIN(CLOSE, 30)))))) * (VOLUME / ADV(20)))))

alpha101 = ((CLOSE - OPEN) / ((HIGH - LOW) + .001))

```

### get_all_factor_names - 获取因子字段列表 {#rqdata-API-get_all_factor_names}

```python
get_all_factor_names(type=None, market='cn')
```

获取可用因子字段名称列表，支持按因子类型筛选。例如可返回利润表、资产负债表、现金流量表、估值指标、技术指标和 alpha101 等类型的因子名称。

#### 参数 {#rqdata-API-get_all_factor_names-params}

| 参数   | 类型  | 说明                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------ | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| type   | _str_ | 默认返回所有因子<br/>'income_statement'：利润表( 基础财务字段 + 其 mrq_n、ttm_n 、lyr_n 因子)<br/>'balance_sheet'：资产负债表 ( 基础财务字段 + 其 mrq_n、ttm_n 、lyr_n 因子)<br/>'cash_flow_statement'：现金流量表 (基础财务字段 + 其 mrq_n、ttm_n 、lyr_n 因子)<br/>'eod_indicator'：估值有关指标<br/>'operational_indicator'：经营衍生指标表<br/>'cash_flow_indicator'：现金流衍生指标<br/>'financial_indicator'：财务衍生指标<br/>'growth_indicator'：增长衍生指标<br/>'alpha101'：alpha101 因子<br/>'moving_average_indicator'：均线类指标<br/>'obos_indicator'：超买超卖指标<br/>'energy_indicator'：能量指标 |
| market | _str_ | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

#### 返回 {#rqdata-API-get_all_factor_names-return}

_list_

#### 范例 {#rqdata-API-get_all_factor_names-example}

- 获取超买超卖指标 因子

```python
[In]
rqdatac.get_all_factor_names(type='obos_indicator')
[Out]
['OBOS', 'KDJ_K', 'KDJ_D', 'KDJ_J', 'RSI6', 'WR', 'LWR1', 'BIAS5', 'BIAS36', 'ACCER', 'CYF', 'SWL', 'ADTM', 'TR', 'DKX', 'TAPI', 'OSC', 'CCI', 'ROC', 'MFI', 'MTM', 'MARSI6', 'SKD_K', 'UDL', 'DI1', 'RSI10', 'LWR2', 'BIAS10', 'BIAS612', 'SWS', 'MAADTM', 'ATR', 'MADKX', 'MATAPI', 'MAMTM', 'MARSI10', 'SKD_D', 'MAUDL', 'DI2', 'BIAS20', 'MABIAS', 'ADX', 'ADXR']

```

## 基础日行情

### get_share_transformation - 获取股票转换股票代码信息 {#rqdata-API-get_share_transformation}

```python
get_share_transformation(predecessor=None, market='cn')
```

获取股票因代码变更或并购等情况产生的代码转换信息，包括历史股票代码、变更后股票代码、变更比例和事件原因。

#### 参数 {#rqdata-API-get_share_transformation-params}

| 参数        | 类型  | 说明                                                             |
| ----------- | ----- | ---------------------------------------------------------------- |
| predecessor | _str_ | 合约代码(来自交易所或其他平台), 空值返回所有变更过股票代码的股票 |
| market      | _str_ | 目前仅支持国内市场('cn')。                                       |

#### 返回 {#rqdata-API-get_share_transformation-return}

_pandas Dataframe_

| 字段                      | 类型               | 说明                 |
| ------------------------- | ------------------ | -------------------- |
| predecessor               | _str_              | 历史股票代码         |
| successor                 | _str_              | 变更后股票代码       |
| effective_date            | _pandas.Timestamp_ | 变更生效日期         |
| share_conversion_ratio    | _float_            | 股票变更比例         |
| predecessor_delisted      | _boolean_          | 变更后旧代码是否退市 |
| discretionary_execution   | _boolean_          | 是否有变更自主选择权 |
| predecessor_delisted_date | _pandas.Timestamp_ | 历史股票代码退市日期 |
| event                     | _str_              | 股票代码变更原因     |

#### 范例 {#rqdata-API-get_share_transformation-example}

```python
[In]get_share_transformation(predecessor="000022.XSHE")
[Out]
    predecessor  successor    effective_date   share_conversion_ratio  predecessor_delisted  discretionary_execution  predecessor_delisted_date  event
0  000022.XSHE  001872.XSHE  2018-12-26                        1.0      True                     False                 2018-12-26               code_change
```

### sector - 获取某板块股票列表 {#rqdata-API-sector}

```python
sector(code, market='cn')
```

获取指定板块的股票列表。例如支持能源、金融、信息技术等板块。

#### 参数 {#rqdata-API-sector-params}

| 参数   | 类型                         | 说明                                                                                                        |
| ------ | ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| code   | _str_ OR _sector_code items_ | **必填参数**，板块名称或板块代码。可选字段见下方。例如，能源板块可填写'Energy'、'能源'或 sector_code.Energy |
| market | _str_                        | 默认是中国市场('cn')，目前仅支持中国市场。                                                                  |

##### 板块分类列表 {#rqdata-API-sector-category}

目前支持的 code 板块分类如下，其取值参考自 MSCI 发布的<a href="https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard" target="_blank">全球行业标准分类</a>:

| 板块代码                  | 中文板块名称 | 英文板块名称               |
| ------------------------- | ------------ | -------------------------- |
| Energy                    | 能源         | energy                     |
| Materials                 | 原材料       | materials                  |
| ConsumerDiscretionary     | 非必需消费品 | consumer discretionary     |
| ConsumerStaples           | 必需消费品   | consumer staples           |
| HealthCare                | 医疗保健     | health care                |
| Financials                | 金融         | financials                 |
| RealEstate                | 房地产       | real estate                |
| InformationTechnology     | 信息技术     | information technology     |
| TelecommunicationServices | 电信服务     | telecommunication services |
| Utilities                 | 公共服务     | utilities                  |
| Industrials               | 工业         | industrials                |

#### 返回 {#rqdata-API-sector-return}

属于该板块的order_book_id list.

#### 范例 {#rqdata-API-sector-example}

```python
[In]sector('Energy')
[Out]
['300023.XSHE', '000571.XSHE', '600997.XSHG', '601798.XSHG', '603568.XSHG', .....]
```

```python
[In]sector(sector_code.Energy)
[Out]
['300023.XSHE', '000571.XSHE', '600997.XSHG', '601798.XSHG', '603568.XSHG', .....]
```

### industry - 获取某行业股票列表 {#rqdata-API-industry}

```python
industry(code, market='cn')
```

获取按国家统计局国民经济行业分类划分的行业股票列表。例如支持农业、银行、软件和信息技术服务业等行业。

#### 参数 {#rqdata-API-industry-params}

| 参数   | 类型                           | 说明                                                                                          |
| ------ | ------------------------------ | --------------------------------------------------------------------------------------------- |
| code   | _str_ OR _industry_code items_ | **必填参数**，行业名称或行业代码。可选字段见下方。例如，农业可填写 industry_code.A01 或 'A01' |
| market | _str_                          | 默认是中国市场('cn')，目前仅支持中国市场                                                      |

##### 行业分类列表 {#rqdata-API-industry-category}

我们目前使用的行业分类来自于中国国家统计局的国民经济行业分类，可以使用这里的任何一个行业代码来调用行业的股票列表：

| 行业代码 | 行业名称                                 |
| -------- | ---------------------------------------- |
| A01      | 农业                                     |
| A02      | 林业                                     |
| A03      | 畜牧业                                   |
| A04      | 渔业                                     |
| A05      | 农、林、牧、渔服务业                     |
| B06      | 煤炭开采和洗选业                         |
| B07      | 石油和天然气开采业                       |
| B08      | 黑色金属矿采选业                         |
| B09      | 有色金属矿采选业                         |
| B10      | 非金属矿采选业                           |
| B11      | 开采辅助活动                             |
| B12      | 其他采矿业                               |
| C13      | 农副食品加工业                           |
| C14      | 食品制造业                               |
| C15      | 酒、饮料和精制茶制造业                   |
| C16      | 烟草制品业                               |
| C17      | 纺织业                                   |
| C18      | 纺织服装、服饰业                         |
| C19      | 皮革、毛皮、羽毛及其制品和制鞋业         |
| C20      | 木材加工及木、竹、藤、棕、草制品业       |
| C21      | 家具制造业                               |
| C22      | 造纸及纸制品业                           |
| C23      | 印刷和记录媒介复制业                     |
| C24      | 文教、工美、体育和娱乐用品制造业         |
| C25      | 石油加工、炼焦及核燃料加工业             |
| C26      | 化学原料及化学制品制造业                 |
| C27      | 医药制造业                               |
| C28      | 化学纤维制造业                           |
| C29      | 橡胶和塑料制品业                         |
| C30      | 非金属矿物制品业                         |
| C31      | 黑色金属冶炼及压延加工业                 |
| C32      | 有色金属冶炼和压延加工业                 |
| C33      | 金属制品业                               |
| C34      | 通用设备制造业                           |
| C35      | 专用设备制造业                           |
| C36      | 汽车制造业                               |
| C37      | 铁路、船舶、航空航天和其它运输设备制造业 |
| C38      | 电气机械及器材制造业                     |
| C39      | 计算机、通信和其他电子设备制造业         |
| C40      | 仪器仪表制造业                           |
| C41      | 其他制造业                               |
| C42      | 废弃资源综合利用业                       |
| C43      | 金属制品、机械和设备修理业               |
| D44      | 电力、热力生产和供应业                   |
| D45      | 燃气生产和供应业                         |
| D46      | 水的生产和供应业                         |
| E47      | 房屋建筑业                               |
| E48      | 土木工程建筑业                           |
| E49      | 建筑安装业                               |
| E50      | 建筑装饰和其他建筑业                     |
| F51      | 批发业                                   |
| F52      | 零售业                                   |
| G53      | 铁路运输业                               |
| G54      | 道路运输业                               |
| G55      | 水上运输业                               |
| G56      | 航空运输业                               |
| G57      | 管道运输业                               |
| G58      | 装卸搬运和运输代理业                     |
| G59      | 仓储业                                   |
| G60      | 邮政业                                   |
| H61      | 住宿业                                   |
| H62      | 餐饮业                                   |
| I63      | 电信、广播电视和卫星传输服务             |
| I64      | 互联网和相关服务                         |
| I65      | 软件和信息技术服务业                     |
| J66      | 货币金融服务                             |
| J67      | 资本市场服务                             |
| J68      | 保险业                                   |
| J69      | 其他金融业                               |
| K70      | 房地产业                                 |
| L71      | 租赁业                                   |
| L72      | 商务服务业                               |
| M73      | 研究和试验发展                           |
| M74      | 专业技术服务业                           |
| M75      | 科技推广和应用服务业                     |
| N76      | 水利管理业                               |
| N77      | 生态保护和环境治理业                     |
| N78      | 公共设施管理业                           |
| O79      | 居民服务业                               |
| O80      | 机动车、电子产品和日用产品修理业         |
| O81      | 其他服务业                               |
| P82      | 教育                                     |
| Q83      | 卫生                                     |
| Q84      | 社会工作                                 |
| R85      | 新闻和出版业                             |
| R86      | 广播、电视、电影和影视录音制作业         |
| R87      | 文化艺术业                               |
| R88      | 体育                                     |
| R89      | 娱乐业                                   |
| S90      | 综合                                     |

#### 返回 {#rqdata-API-industry-return}

属于该行业的order_book_id list.

#### 范例 {#rqdata-API-industry-example}

```python
[In]
industry('A01')
[Out]
['600540.XSHG', '600371.XSHG', '600359.XSHG', '600506.XSHG',...]
```

```python
[In]
industry(industry_code.A01)
[Out]
['600540.XSHG', '600371.XSHG', '600359.XSHG', '600506.XSHG',...]
```

### get_concept_list - 获取概念列表 {#rqdata-API-concept_list}

```python
get_concept_list(start_date=None, end_date=None, market='cn')
```

获取股票概念列表及其纳入日期。例如可查询 ETC概念、维生素、无线耳机等概念。

#### 参数 {#rqdata-API-concept_list-params}

| 参数       | 类型                                                           | 说明                                                   |
| ---------- | -------------------------------------------------------------- | ------------------------------------------------------ |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询 概念纳入日期 开始时间，不传入默认返回所有时段数据 |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询 概念纳入日期 结束时间，不传入默认返回所有时段数据 |
| market     | _str_                                                          | 默认是中国内地市场('cn')                               |

#### 返回 {#concept-API-concept_list-return}

_pandas Series_

返回概念纳入日期对应的概念名称

#### 范例 {#concept-API-concept_list-example}

```python
[In]
get_concept_list(start_date='2019-01-01', end_date='2020-01-01')
[Out]
date
2019-01-17    360私有化
2019-01-17      油气改革
2019-01-17    浦东国资改革
2019-01-17     海南自贸区
2019-01-17      海绵城市
               ...
2019-07-15     ETC概念
2019-07-17     光刻机概念
2019-08-12       维生素
2019-12-12      胎压监测
2019-12-20      无线耳机
```

### get_concept - 获取所选概念对应股票列表 {#rqdata-API-get-concept}

```python
get_concept(concepts, start_date=None, end_date=None, market='cn')
```

获取指定概念对应的股票列表及纳入日期，支持同时查询一个或多个概念。例如 ETC概念、维生素等概念对应的股票列表。

#### 参数 {#rqdata-API-get-concept-params}

| 参数       | 类型                                                           | 说明                                                           |
| ---------- | -------------------------------------------------------------- | -------------------------------------------------------------- |
| concepts   | _str_ OR multiple _str_                                        | **必填参数**，概念名称。可以从概念列表中选择一个或多个概念填写 |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询 股票纳入概念日期 开始时间，不传入默认返回所有时段数据     |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询 股票纳入概念日期 结束时间，不传入默认返回所有时段数据     |
| market     | _str_                                                          | 默认是中国内地市场('cn')                                       |

#### 返回 {#rqdata-API-get-concept-return}

_pandas DataFrame_

| 返回           | 类型               | 说明                            |
| -------------- | ------------------ | ------------------------------- |
| concept        | _str_              | index，所输入合约代码对应的概念 |
| order_book_id  | _str_              | column，合约代码                |
| inclusion_date | _pandas.Timestamp_ | column，股票纳入概念日期        |

#### 范例 {#rqdata-API-get-concept-example}

```python
[In]
get_concept(['ETC概念','维生素'],start_date='2019-01-01', end_date='2021-01-01')
[Out]
 order_book_id inclusion_date
concept
ETC概念 000938.XSHE 2019-07-15
ETC概念 002104.XSHE 2019-10-16
ETC概念 002161.XSHE 2019-08-08
ETC概念 002373.XSHE 2019-07-15
ETC概念 002401.XSHE 2019-07-15
ETC概念 002512.XSHE 2019-07-15
ETC概念 002869.XSHE 2019-07-15
ETC概念 300014.XSHE 2019-07-15
ETC概念 300020.XSHE 2019-10-29
ETC概念 300075.XSHE 2019-07-15
ETC概念 300205.XSHE 2019-07-15
ETC概念 300376.XSHE 2019-07-23
ETC概念 300438.XSHE 2019-09-10
ETC概念 300448.XSHE 2019-07-15
ETC概念 300462.XSHE 2019-07-15
ETC概念 300552.XSHE 2019-07-15
ETC概念 300717.XSHE 2019-07-15
ETC概念 600035.XSHG 2019-07-15
ETC概念 603068.XSHG 2019-07-15
ETC概念 603458.XSHG 2019-07-31
ETC概念 603936.XSHG 2019-12-23
ETC概念 688208.XSHG 2020-02-24
维生素 000597.XSHE 2019-08-12
维生素 000952.XSHE 2019-08-12
维生素 002001.XSHE 2019-08-12
维生素 002019.XSHE 2019-08-12
维生素 002332.XSHE 2019-08-12
维生素 002562.XSHE 2019-08-12
维生素 002626.XSHE 2019-08-12
维生素 300267.XSHE 2019-08-12
维生素 300401.XSHE 2019-08-12
维生素 600216.XSHG 2019-08-12
维生素 600299.XSHG 2019-08-12
维生素 600812.XSHG 2019-08-12
维生素 603079.XSHG 2019-08-12
```

### get_stock_concept - 获取所选股票对应概念 {#rqdata-API-get_stock_concept}

```python
get_stock_concept(order_book_ids, market='cn')
```

获取单只或多只股票对应的概念标签及纳入日期。例如可查询房地产、深港通等概念标签。

#### 参数 {#rqdata-API-get_stock_concept-params}

| 参数          | 类型                | 说明                                                             |
| ------------- | ------------------- | ---------------------------------------------------------------- |
| order_book_id | _str_ or _str list_ | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| market        | _str_               | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_stock_concept-return}

_pandas DataFrame_

| 返回           | 类型               | 说明                             |
| -------------- | ------------------ | -------------------------------- |
| order_book_id  | _str_              | index，合约代码                  |
| inclusion_date | _pandas.Timestamp_ | index，股票纳入概念日期          |
| concept        | _str_              | column，所输入合约代码对应的概念 |

#### 范例 {#rqdata-API-get_stock_concept-example}

```python
[In]
get_stock_concept (['000002.XSHE','000504.XSHE'])
[Out]
                      concept
order_book_id inclusion_date
000002.XSHE     2019-01-17 房地产
                2019-01-17 深港通
                2019-01-17 租售同权
                2019-01-17 广东自贸区
                2019-01-22 举牌概念
                2019-03-04 粤港澳大湾区
                2019-03-18 雄安概念
                2019-03-18 特色小镇
                2019-05-07 互联网金融
                2019-08-19 体育
                2019-08-19 冬奥会
                2020-01-15 超级品牌
                2020-11-16 长江三角洲概念
                2022-01-06 碳中和
                2024-01-17 智能家居
                2024-01-17 智慧城市
000504.XSHE     2019-01-17 美丽中国
                2019-01-22 举牌概念
                2019-05-07 文化传媒
                2021-12-01 医药
                2021-12-01 节能环保
                2022-11-28 国企混改
                2024-05-11 生物医药
```

### get_industry_mapping - 获取行业分类概览 {#rqdata-API-get-industry-mapping}

```python
get_industry_mapping(source='citics_2019', date=None, market='cn')
```

获取行业分类代码和名称映射，支持一级、二级、三级行业分类。例如可返回石油石化、煤炭、银行等行业分类体系。

#### 参数 {#rqdata-API-get-industry-mapping-params}

| 参数   | 类型                                                           | 说明                                                                                                                                                  |
| ------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| source | _str_                                                          | 分类依据。 citics: 中信, gildata: 聚源,citics_2019:中信 2019 分类,默认 source='citics_2019'.**注意**：citics 为中信 2019 年新的行业分类未发布前的分类 |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                                                                          |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                   |

#### 返回 {#rqdata-API-get-industry-mapping-return}

_pandas DataFrame_

| 字段                 | 类型  | 说明         |
| -------------------- | ----- | ------------ |
| first_industry_code  | _str_ | 一级行业代码 |
| first_industry_name  | _str_ | 一级行业名称 |
| second_industry_code | _str_ | 二级行业代码 |
| second_industry_name | _str_ | 二级行业名称 |
| third_industry_code  | _str_ | 三级行业代码 |
| third_industry_name  | _str_ | 三级行业名称 |

#### 范例 {#rqdata-API-get-industry-mapping-sampels}

- 得到当前行业分类的概览：

```python
[In]
get_industry_mapping()
[Out]
     first_industry_code first_industry_name second_industry_code second_industry_name third_industry_code third_industry_name
0                    10                石油石化                 1010                 石油开采              101010                石油开采
1                    10                石油石化                 1020                 石油化工              102010                  炼油
2                    10                石油石化                 1020                 石油化工              102040             油品销售及仓储
3                    10                石油石化                 1020                 石油化工              102050                其他石化
4                    10                石油石化                 1030                 油田服务              103010                油田服务
5                    11                  煤炭                 1110               煤炭开采洗选              111010                 动力煤
...
```

### get_industry - 获取某行业的股票列表 {#rqdata-API-get-industry}

```python
get_industry(industry, source='citics_2019', date=None, market='cn')
```

获取指定行业的股票列表，支持按行业名称、行业指数代码或行业代号查询。例如可查询银行或 `621020` 等行业分类对应的股票列表。

#### 参数 {#rqdata-API-get-industry-params}

| 参数     | 类型                                                           | 说明                                                                                                                                                     |
| -------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| industry | _str_                                                          | **必填参数**，可传入行业名称、行业指数代码或者行业代号                                                                                                   |
| source   | _str_                                                          | 分类依据。 citics: 中信, gildata: 聚源, citics_2019:中信 2019 分类, 默认 source='citics_2019'. **注意**：citics 为中信 2019 年新的行业分类未发布前的分类 |
| date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                                                                             |
| market   | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                      |

#### 返回 {#rqdata-API-get-industry-return}

_list_

#### 范例 {#rqdata-API-get-industry-sampels}

- 得到当前某一级行业的股票列表：

```python
[In]
get_industry('银行')
[Out]
['000001.XSHE',
 '002142.XSHE',
 '002807.XSHE',
 '002839.XSHE',
 '002936.XSHE',
 '002948.XSHE',
 '002958.XSHE',
 '002966.XSHE',
 '600000.XSHG',
 '600015.XSHG',
 '600016.XSHG',
 '600036.XSHG',
 '600908.XSHG',
 '600919.XSHG',
 '600926.XSHG',
 '600928.XSHG',
 '601009.XSHG',
 '601128.XSHG',
 '601166.XSHG',
 '601169.XSHG',
 '601229.XSHG',
 '601288.XSHG',
 '601328.XSHG',
 '601398.XSHG',
 '601577.XSHG',
 '601818.XSHG',
 '601838.XSHG',
 '601860.XSHG',
 '601939.XSHG',
 '601988.XSHG',
 '601997.XSHG',
 '601998.XSHG',
 '603323.XSHG']
```

- 用中信行业代码获得股票列表：

```python
[In]
get_industry(industry='621020',source='citics')
[Out]
['000997.XSHE',
 '002152.XSHE',
 '002177.XSHE',
 '002268.XSHE',
 '002308.XSHE',
 '002312.XSHE',
 '002376.XSHE',
 '002383.XSHE',
 '002512.XSHE',
 '002518.XSHE',
 '002546.XSHE',
 '002635.XSHE',
 '002771.XSHE',
 '002829.XSHE',
 '002835.XSHE',
 '002906.XSHE',
 '300074.XSHE',
 '300076.XSHE',
 '300078.XSHE',
 '300098.XSHE',
 '300130.XSHE',
 '300167.XSHE',
 '300177.XSHE',
 '300270.XSHE',
 '300275.XSHE',
 '300311.XSHE',
 '300449.XSHE',
 '300455.XSHE',
 '300458.XSHE',
 '300479.XSHE',
 '300743.XSHE',
 '603106.XSHG',
 '603660.XSHG',
 '603890.XSHG']
```

### get_industry_change - 获取某行业的股票纳入剔除日期 {#rqdata-API-get-industry-change}

```python
get_industry_change(industry, source='citics_2019', level=None, market='cn')
```

获取指定行业股票的纳入和剔除日期，支持中信 2019、中信旧版和聚源分类，也支持一级、二级、三级行业级别。

#### 参数 {#rqdata-API-get-industry-change-params}

| 参数     | 类型      | 说明                                                                                                                        |
| -------- | --------- | --------------------------------------------------------------------------------------------------------------------------- |
| industry | _str_     | **必填参数**，可传入行业名称、行业指数代码或者行业代号                                                                      |
| source   | _str_     | 分类依据。 citics_2019 - 中信新分类（2019 发布）, citics - 中信旧分类（退役中）, gildata -聚源。 默认 source='citics_2019'. |
| level    | _integer_ | 行业分类级别，共三级，默认一级分类。参数 1,2,3 一一对应                                                                     |
| market   | _str_     | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                         |

#### 返回 {#rqdata-API-get-industry-change-return}

_pandas DataFrame_

| 字段        | 类型               | 说明                            |
| ----------- | ------------------ | ------------------------------- |
| start_date  | _pandas.Timestamp_ | 起始日期                        |
| cancel_date | _pandas.Timestamp_ | 取消日期，2200-12-31 表示未披露 |

#### 范例 {#rqdata-API-get-industry-change-sampels}

- 得到当前某一级行业的股票纳入剔除日期：

```python
[In]
get_industry_change(industry='银行', level=1,source='citics_2019')
[Out]
start_date cancel_date
order_book_id
601988.XSHG   2019-12-02  2200-12-31
601398.XSHG   2019-12-02  2200-12-31
601328.XSHG   2019-12-02  2200-12-31
601939.XSHG   2019-12-02  2200-12-31
601288.XSHG   2019-12-02  2200-12-31
...                  ...         ...
601963.XSHG   2021-02-05  2200-12-31
601665.XSHG   2021-06-18  2200-12-31
601528.XSHG   2021-06-25  2200-12-31
601825.XSHG   2021-08-19  2200-12-31
001227.XSHE   2022-01-17  2200-12-31
```

### get_instrument_industry - 获取股票的指定行业分类 {#rqdata-API-get-instrument-industry-stockmod}

```python
get_instrument_industry(order_book_ids, source='citics_2019', level=1, date=None, market='cn')
```

获取股票在指定日期的行业分类数据，支持返回一级到三级行业，也支持 `citics_2019` 的衍生板块和风格归属。例如可获取银行、全国性股份制银行Ⅱ、金融风格等分类结果。

#### 参数 {#rqdata-API-get-instrument-industry-params-stockmod}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                 |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，股票合约代码，可输入 order_book_id, order_book_id list                                                                                                                 |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                                                                                                         |
| source         | _str_                                                          | 分类依据。citics_2019 - 中信新分类（2019 发布）, citics - 中信旧分类（退役中）, gildata -聚源。 默认 source='citics_2019'.                                                           |
| level          | _integer_                                                      | 行业分类级别，共三级，默认返回一级分类。参数 0,1,2,3 一一对应，其中 0 返回三级分类完整情况<br>当 source='citics_2019' 时，level 可传入'citics_sector' 获取该股票的衍生板块及风格归属 |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                  |

#### 返回 {#rqdata-API-get-instrument-industry-return-stockmod}

_pandas DataFrame_

| 字段                 | 类型  | 说明         |
| -------------------- | ----- | ------------ |
| first_industry_code  | _str_ | 一级行业代码 |
| first_industry_name  | _str_ | 一级行业名称 |
| second_industry_code | _str_ | 二级行业代码 |
| second_industry_name | _str_ | 二级行业名称 |
| third_industry_code  | _str_ | 三级行业代码 |
| third_industry_name  | _str_ | 三级行业名称 |

#### 范例 {#rqdata-API-get-instrument-industry-sampels-stockmod}

- 得到当前股票所对应的一级行业：

```python
[In]
get_instrument_industry('000001.XSHE')
[Out]
                   first_industry_code first_industry_name
order_book_id
000001.XSHE                    40                  银行
```

- 得到当前股票组所对应的中信行业的全部分类：

```python
In [7]: get_instrument_industry(['000001.XSHE','000002.XSHE'],source='citics_2019',level=0)
Out[7]:
              first_industry_code first_industry_name second_industry_code second_industry_name third_industry_code third_industry_name
order_book_id
000001.XSHE                    40                  银行                 4020            全国性股份制银行Ⅱ              402010           全国性股份制银行Ⅲ
000002.XSHE                    42                 房地产                 4210             房地产开发和运营              421010              住宅物业开发
```

- 得到当前股票组所对应的中信 2019 衍生板块及风格归属：

```python
[In]: get_instrument_industry(['000001.XSHE','000002.XSHE'],source='citics_2019',level='citics_sector')
[Out]:
                industry_sector_name  industry_chain_sector_name  style_sector_name
order_book_id
000001.XSHE 金融产业              大金融                   金融风格
000002.XSHE 基础设施与地产产业     大金融                   金融风格

```

### get_turnover_rate - 获取历史换手率 {#rqdata-API-get_turnover_rate}

```python
get_turnover_rate(order_book_ids, start_date=None, end_date=None, fields=None, expect_df=True, market='cn')
```

获取股票历史换手率数据。例如可查询当日换手率、过去一周平均换手率、过去一个月平均换手率、过去一年平均换手率和当年平均换手率。

#### 参数 {#rqdata-API-get_turnover_rate-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                            |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list                                                                                                |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                                                                                        |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据                                                                                               |
| fields         | _str_ OR _str list_                                            | 默认为所有字段。当天换手率 - `today`，过去一周平均换手率 - `week`，过去一个月平均换手率 - `month`，过去一年平均换手率 - `year`，当年平均换手率 - `current_year` |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构                                                                                                 |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                             |

#### 返回 {#rqdata-API-get_turnover_rate-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-get_turnover_rate-example}

- 获取平安银行历史换手率情况

```
In [17]: get_turnover_rate('000001.XSHE',20160801,20160806)
Out[17]:
                        today   week  month   year current_year
order_book_id tradedate
000001.XSHE   2016-08-01 0.5190 0.4033 0.3175 0.5027 0.3585
              2016-08-02 0.3070 0.4243 0.3206 0.5019 0.3581
              2016-08-03 0.2902 0.4104 0.3193 0.5011 0.3576
              2016-08-04 0.9189 0.4703 0.3443 0.5000 0.3615
              2016-08-05 0.4962 0.4984 0.3476 0.4993 0.3624
```

- 获取平安银行与中信银行一段时间内的周平均换手率

```python
[In]
get_turnover_rate(['000001.XSHE', '601998.XSHG'], '20160801', '20160812', 'week')

[Out]

                               week
order_book_id    tradedate
000001.XSHE      2016-08-01    0.4033
                 2016-08-02    0.4243
601998.XSHG      2016-08-01    0.1184
                 2016-08-02    0.1113
```

### get_dividend_info - 获取股票的分红信息 {#rqdata-API-get_dividend_info}

```python
get_dividend_info(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票分红事件信息，支持按时间范围查询。例如可获取现金、转增股份、赠送股份、现金加送转等分红形式，以及对应的公布日期和除权除息日。

#### 参数 {#rqdata-API-get_dividend_info-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回全部分红数据    |
| market         | _str_                                                          | 默认是中国市场('cn')，目前仅支持中国市场                         |

#### 返回 {#rqdata-API-get_dividend_info-return}

- 单只股票
  _pandas single-index DataFrame_ - 查询时间段内的某个股票的分红数据

- 一组股票
  _pandas multi-index DataFrame_ - 查询时间段内的一组股票的分红数据

| 字段             | 类型               | 说明                                                                                                                                               |
| ---------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| info_date        | _pandas.Timestamp_ | 公布日期                                                                                                                                           |
| effective_date   | _pandas.Timestamp_ | 常规分红对应的有效财政季度；特殊分红则对应股权登记日                                                                                               |
| dividend_type    | _str_              | 是否分红及具体分红形式:<br/>transferred share 代表转增股份；bonus share 代表赠送股份；cash 为现金；cash and share 代表现金、转增股和送股都有涉及。 |
| ex_dividend_date | _pandas.Timestamp_ | 除权除息日，该天股票的价格会因为分红而进行调整                                                                                                     |

#### 范例 {#rqdata-API-get_dividend_info-example}

- 获取平安银行的历史分红信息：

```python
[In]
get_dividend_info('000001.XSHE')

[Out]
            dividend_type ex_dividend_date info_date order_book_id
effective_date
1990-12-31 cash and bonus share 1991-04-03 1991-02-10 000001.XSHE
1991-12-31 cash and bonus share 1992-03-23 1992-03-14 000001.XSHE
1992-12-31 cash and share       1993-05-24 1993-05-07 000001.XSHE
1993-12-31 cash and share       1994-07-11 1994-07-02 000001.XSHE
1994-12-31 cash and bonus share 1995-09-25 1995-09-15 000001.XSHE
1995-12-31 bonus and transferred share 1996-05-27 1996-05-23 000001.XSHE
...
```

### get_dividend - 获取股票现金分红数据 {#rqdata-API-get_dividend}

```python
get_dividend(order_book_ids, start_date=None, end_date=None, expect_df=True, market='cn')
```

获取股票现金分红数据，包括分红宣布日、股权登记日、除权除息日、分红到账日和对应报告期等信息，支持中国内地与香港市场。

::: tip 注意事项 {#rqdata-API-financial-tip}

1、rqdatac 3.4.3 起，expect_df 默认参数值由 False 更改为True <br/>
2、market='hk' 不支持 expect_df = False

:::

#### 参数 {#rqdata-API-get_dividend-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回全部分红数据    |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe,如果调为 False ,则返回原有的数据结构   |
| market         | _str_                                                          | 默认是中国内地市场('cn')。cn-中国内地市场，hk-中国香港市场       |

#### 返回 {#rqdata-API-get_dividend-return}

- 单只股票
  _pandas single-index DataFrame_ - 查询时间段内的某个股票的现金分红数据

- 一组股票
  _pandas multi-index DataFrame_ - 查询时间段内的一组股票的现金分红数据

| 字段                          | 类型               | 说明                                                                            |
| ----------------------------- | ------------------ | ------------------------------------------------------------------------------- |
| declaration_announcement_date | _pandas.Timestamp_ | 分红宣布日，上市公司一般会提前一段时间公布未来的分红派息事件                    |
| book_closure_date             | _pandas.Timestamp_ | 股权登记日                                                                      |
| dividend_cash_before_tax      | _float_            | 税前分红                                                                        |
| ex_dividend_date              | _pandas.Timestamp_ | 除权除息日，该天股票的价格会因为分红而进行调整                                  |
| payable_date                  | _pandas.Timestamp_ | 分红到帐日，这一天最终分红的现金会到账                                          |
| round_lot                     | _float_            | 分红最小单位，例如：10 代表每 10 股派发 dividend_cash_before_tax 单位的税前现金 |
| advance_date                  | _pandas.Timestamp_ | 股东会日期                                                                      |
| quarter                       | _str_              | 报告期                                                                          |

#### 范例 {#rqdata-API-get_dividend-example}

- 获取平安银行 2013-01-04 到 2014-01-06 的现金分红数据：

```python
[In]
get_dividend('000001.XSHE', start_date='20130104', end_date='20140106')

[Out]
                              dividend_cash_before_tax	book_closure_date	ex_dividend_date	payable_date	round_lot	advance_date	quarter
order_book_id	declaration_announcement_date
000001.XSHE	2013-06-14	1.7	2013-06-19	2013-06-20	2013-06-20	10.0	2013-03-08	2012q4

```

### get_dividend_amount - 获取股票分红总额数据 {#rqdata-API-get_dividend_amount}

```python
get_dividend_amount(order_book_ids, start_quarter = None, end_quarter = None, date = None, market = 'cn')
```

获取股票按报告期统计的分红总额数据。例如可查询预案、决案、方案实施等不同事件进程下的分红总额。

#### 参数 {#rqdata-API-get_dividend_amount-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_quarter  | _str_                                                          | 起始报告期，默认返回全部。<br/>传入样例'2023q4'期                |
| end_quarter    | _str_                                                          | 截止报告期，默认返回全部。<br/>传入样例'2023q4'期                |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认值为当前最新日期                                   |
| market         | _str_                                                          | 默认是中国内地市场('cn')。cn-中国内地市场，hk-中国香港市场       |

#### 返回 {#rqdata-API-get_dividend_amount-return}

- 单只股票
  _pandas single-index DataFrame_ - 查询时间段内的某个股票的分红总额数据

- 一组股票
  _pandas multi-index DataFrame_ - 查询时间段内的一组股票的分红总额数据

| 字段            | 类型               | 说明                           |
| --------------- | ------------------ | ------------------------------ |
| event_procedure | _str_              | 事件进程。预案，决案，方案实施 |
| info_date       | _pandas.Timestamp_ | 公告日期                       |
| amount          | _float_            | 分红总额                       |

#### 范例 {#rqdata-API-get_dividend_amount-example}

- 获取平安银行 有史以来现金分红总额数据：

```python
[In]
rqdatac.get_dividend_amount('000001.XSHE')
[Out]
                      event_procedure info_date amount
order_book_id quarter
000001.XSHE   2018q4 预案 2019-03-07 2.489710e+09
              2018q4 决案 2019-05-31 2.489710e+09
              2018q4 方案实施 2019-06-20 2.489710e+09
              2019q4 预案 2020-02-14 4.230000e+09
              2019q4 决案 2020-05-15 4.230000e+09
              2019q4 方案实施 2020-05-22 4.230490e+09
              2020q4 预案 2021-02-02 3.493000e+09
              2020q4 决案 2021-04-09 3.493000e+09
              2020q4 方案实施 2021-05-07 3.493065e+09
              2021q4 预案 2022-03-10 4.425000e+09
              2021q4 决案 2022-06-29 4.425000e+09
              2021q4 方案实施 2022-07-15 4.424549e+09
              2022q4 预案 2023-03-09 5.530687e+09
              2022q4 决案 2023-06-01 5.530687e+09
              2022q4 方案实施 2023-06-07 5.530687e+09
              2023q4 预案 2024-03-15 1.395286e+10
              2023q4 决案 2024-05-25 1.395286e+10
              2023q4 方案实施 2024-06-06 1.395286e+10

```

### get_split - 获取股票拆分数据 {#rqdata-API-get_split}

```python
get_split(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票拆分数据，包括股权登记日、除权除息日、送转股上市日和拆分前后系数，支持中国内地与香港市场。

#### 参数 {#rqdata-API-get_split-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认返回全部                                           |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期 ，默认返回全部                                          |
| market         | _str_                                                          | 默认是中国内地市场('cn')。cn-中国内地市场，hk-中国香港市场       |

#### 返回 {#rqdata-API-get_split-return}

- 单只股票
  _pandas single-index DataFrame_ - 查询时间段内的某个股票的拆分数据

- 一组股票
  _pandas multi-index DataFrame_ - 查询时间段内的一组股票的拆分数据

| 字段                   | 类型               | 说明                                           |
| ---------------------- | ------------------ | ---------------------------------------------- |
| ex_dividend_date       | _pandas.Timestamp_ | 除权除息日，该天股票的价格会因为拆分而进行调整 |
| book_closure_date      | _pandas.Timestamp_ | 股权登记日                                     |
| split_coefficient_from | _float_            | 拆分因子（拆分前）                             |
| split_coefficient_to   | _float_            | 拆分因子（拆分后）                             |
| payable_date           | _pandas.Timestamp_ | 送转股上市日                                   |
| cum_factor             | _float_            | 累计复权因子（拆分）                           |

例如：每 10 股转增 2 股，则 split_coefficient_from = 10, split_coefficient_to = 12.

#### 范例 {#rqdata-API-get_split-example}

- 获取平安银行 2010-01-04 到 当天之间的拆分信息：

```python
[In]
get_split('000001.XSHE', start_date='20100104', end_date='20140104')

[Out]
book_closure_date order_book_id payable_date split_coefficient_from split_coefficient_to cum_factor
ex_dividend_date
2013-06-20 2013-06-19 000001.XSHE 2013-06-20 10 16.0 1.6
```

### get_ex_factor - 获取复权因子 {#rqdata-API-get_ex_factor}

```python
get_ex_factor(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票复权因子数据，综合反映分红派息和拆分对股价的调整影响，包括当期复权因子和累计复权因子。

#### 参数 {#rqdata-API-get_ex_factor-param}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认返回全部                                              |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认返回全部                                              |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_ex_factor-return}

_pandas dataframe_ - 包含了复权因子的日期和对应的各项数值

| 字段              | 类型               | 说明                                                                                                                                                                                                                                                                                                                                                   |
| ----------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ex_date           | _pandas.Timestamp_ | 除权除息日                                                                                                                                                                                                                                                                                                                                             |
| ex_factor         | _float_            | 复权因子，考虑了分红派息与拆分的影响，为一段时间内的股价调整乘数。<br/>举例来说，平安银行（'000001.XSHE'）在 2016 年 6 月 15 日每 10 股派发现金股利人民币 1.53 元（含税），并以资本公积转增股本每 10 股转增 2 股。<br/>6 月 15 日的收盘价为 10.44 元，其除权除息后的价格应当为 (10.44-1.53/10) / 1.2 = 8.5725.本期复权因子为 10.44 / 8.5725 = 1.217847 |
| ex_cum_factor     | _float_            | 累计复权因子，X 日所在期复权因子 = 当前最新累计复权因子 / 截至 X 日最新累计复权因子。<br/>举例来说，2016 年 5 月 05 日所在期复权因子 = 122.424143 / 100.525060 = 1.217847                                                                                                                                                                              |
| announcement_date | _pandas.Timestamp_ | 股权登记日                                                                                                                                                                                                                                                                                                                                             |
| ex_end_date       | _pandas.Timestamp_ | 复权因子所在期的截止日期                                                                                                                                                                                                                                                                                                                               |

#### 范例 {#rqdata-API-get_ex_factor-example}

```python
[In]
get_ex_factor('000001.XSHE', start_date='2013-01-04', end_date='2017-01-04')

[Out]
            order_book_id  ex_factor  ex_cum_factor announcement_date  \
ex_date
2013-06-20   000001.XSHE   1.614263      68.255824        2013-06-19
2014-06-12   000001.XSHE   1.216523      83.034780        2014-06-11
2015-04-13   000001.XSHE   1.210638     100.525060        2015-04-10
2016-06-16   000001.XSHE   1.217847     122.424143        2016-06-15

           ex_end_date
ex_date
2013-06-20  2014-06-11
2014-06-12  2015-04-12
2015-04-13  2016-06-15
2016-06-16         NaT

```

### is_suspended - 判断股票是否全天停牌 {#rqdata-API-is_suspended}

```python
is_suspended(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票在指定时间范围内是否全天停牌的数据。

#### 参数 {#rqdata-API-is_suspended-params}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码。传入单只或多支股票的 order_book_id          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为股票上市日期                                        |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期，如果股票已经退市，则为退市日期            |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-is_suspended-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-is_suspended-example}

- 获取武钢股份从 2016 年 6 月 24 日至今（2016 年 8 月 31 日）的停牌情况：

```python
[In]
is_suspended('武钢股份', start_date='20160624')
[Out]
               武钢股份
2016-06-24       False
2016-06-27        True
2016-06-28        True
2016-06-29        True
2016-06-30        True
2016-07-01        True
2016-07-04        True
2016-07-05        True
2016-07-06        True
...
2016-08-30        True
2016-08-31        True

[In]
is_suspended(['武钢股份','000001.XSHE'], start_date='20160624')
[Out]
   000001.XSHE 600005.XSHG
2016-06-24 False False
2016-06-27 False True
2016-06-28 False True
2016-06-29 False True
2016-06-30 False True
2016-07-01 False True
2016-07-04 False True
...
2016-09-22 False True
2016-09-23 False True
```

### is_st_stock - 查询股票是否为 ST 股 {#rqdata-API-is_st_stock}

```python
is_st_stock(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票在指定时间范围内是否为 ST 股的数据，从公告日的下一个交易日开始标记。

#### 参数 {#rqdata-API-is_st_stock-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为股票上市日期                                     |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期，如果股票已经退市，则为退市日期         |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-is_st_stock-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-is_st_stock-example}

```python
[In]
is_st_stock("002336.XSHE", "20160411", "20160510")
[Out]
         002336.XSHE
2016-04-11 False
2016-04-12 False
...
2016-05-09 True
2016-05-10 True

[In]
is_st_stock(["002336.XSHE", "000001.XSHE"], "2016-04-11", "2016-05-10")
[Out]
   002336.XSHE 000001.XSHE
2016-04-11 False False
2016-04-12 False False
...
2016-05-09 True False
2016-05-10 True False

```

### get_shares - 获取股本数据 {#rqdata-API-get_shares}

```python
get_shares(order_book_ids, start_date=None, end_date=None, fields=None, expect_df=True, market='cn')
```

获取股票股本数据，支持按时间范围查询。例如包括总股本、A股总股本、流通A股、非流通A股、自由流通股本和优先股等数据。

#### 参数 {#rqdata-API-get_shares-params}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                            |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据   |
| fields         | _str_ OR _str list_                                            | 默认为所有字段。见下方列表                                          |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe,如果调为 False ,则返回原有的数据结构      |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_shares-return}

_pandas  DataFrame_

| 字段                   | 类型    | 说明                                   |
| ---------------------- | ------- | -------------------------------------- |
| total                  | _float_ | 总股本                                 |
| circulation_a          | _float_ | 流通 A 股                              |
| management_circulation | _float_ | 已过禁售期的高管持有的股份（已废弃）   |
| non_circulation_a      | _float_ | 非流通 A 股                            |
| total_a                | _float_ | A 股总股本                             |
| free_circulation       | _float_ | 自由流通股本（提供范围为 2005 年至今） |
| preferred_shares       | _float_ | 优先股                                 |

#### 范例 {#rqdata-API-get_shares-example}

- 获取平安银行流通股概况

```python
[In]
get_shares('000001.XSHE', start_date='20160801', end_date='20160806',expect_df=False)
[Out]
            circulation_a  non_circulation_a       total_a  free_circulation  preferred_shares         total
date
2016-08-01   1.463118e+10       2.539231e+09  1.717041e+10      7.220546e+09               0.0  1.717041e+10
2016-08-02   1.463118e+10       2.539231e+09  1.717041e+10      7.220546e+09               0.0  1.717041e+10
2016-08-03   1.463118e+10       2.539231e+09  1.717041e+10      7.220546e+09               0.0  1.717041e+10
2016-08-04   1.463118e+10       2.539231e+09  1.717041e+10      7.220546e+09               0.0  1.717041e+10
2016-08-05   1.463118e+10       2.539231e+09  1.717041e+10      7.220546e+09               0.0  1.717041e+10
```

- 获取平安银行总股本数据

```python
[In]
get_shares('000001.XSHE', start_date='20160801', end_date='20160806', fields='total')
[Out]

                                    total
order_book_id     date
000001.XSHE     2016-08-01     1.717041e+10
                    2016-08-02     1.717041e+10
                    2016-08-03     1.717041e+10
                    2016-08-04     1.717041e+10
                    2016-08-05     1.717041e+10
```

### get_main_shareholder - 获取主要 A 股股东信息 {#rqdata-API-get_main_shareholder}

```python
get_main_shareholder(order_book_ids, start_date=None, end_date=None, is_total=False, start_rank=None, end_rank=None, market='cn')
```

获取主要 A 股股东数据，支持按总股本或流通 A 股口径查询，并可按股东排名筛选。例如包括股东名称、持股比例、股东属性、股权质押和冻结情况等信息。

#### 参数 {#rqdata-API-get_main_shareholder-params}

| 参数           | 类型                                                           | 说明                                                                     |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list         |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年当日。                                               |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为查询当日。                                               |
| is_total       | _bool_                                                         | 默认为 False, 即基于持有 A 股流通股。若为 True 则基于所有发行出的 A 股。 |
| start_rank     | _int_                                                          | 排名开始值                                                               |
| end_rank       | _int_                                                          | 排名结束值 ,start_rank ,end_rank 不传参时返回全部的十位股东名单          |
| market         | _str_                                                          | 市场，默认'cn'为中国内地市场。                                           |

#### 返回 {#rqdata-API-get_main_shareholder-return}

_pandas DataFrame_

| 字段               | 类型               | 说明                                                                    |
| ------------------ | ------------------ | ----------------------------------------------------------------------- |
| info_date          | _pandas.Timestamp_ | 公告发布日                                                              |
| end_date           | _pandas.Timestamp_ | 截止日期                                                                |
| rank               | _int_              | 排名                                                                    |
| shareholder_name   | _str_              | 股东名称                                                                |
| shareholder_attr   | _str_              | 股东属性                                                                |
| shareholder_kind   | _str_              | 股东性质                                                                |
| shareholder_type   | _str_              | 股东类别                                                                |
| hold_percent_total | _float_            | 占股比例（%） 当 fields=‘total'时，持股数(股)/总股本\*100。             |
| hold_percent_float | _float_            | 占流通 A 股比例（%）,无限售流通 A 股/已上市流通 A 股（不含高管股）\*100 |
| share_pledge       | _float_            | 股权质押涉及股数（股）                                                  |
| share_freeze       | _float_            | 股权冻结涉及股数（股）                                                  |

#### 范例 {#rqdata-API-get_main_shareholder-example}

- 获取平安银行在 2018 年三月上旬的主要的 A 股股东名单

```python
[In]
get_main_shareholder('000001.XSHE', start_date='20180301', end_date='20180315', is_total=False)
[Out]

            end_date  rank  shareholder_name                          shareholder_attr  shareholder_kind  shareholder_type  hold_percent_total  hold_percent_float  share_pledge  share_freeze
info_date
2018-03-15  2017-12-31  1      中国平安保险(集团)股份有限公司-集团本级-自有资金       企业           金融机构—保险公司       None             48.095791         48.813413               NaN   NaN
2018-03-15  2017-12-31  2      中国平安人寿保险股份有限公司-自有资金                 企业          金融机构—保险公司       None            6.112042            6.203238                  NaN  NaN
2018-03-15  2017-12-31  3      中国证券金融股份有限公司                           企业            金融机构—证券、信托公司  None           2.854768           2.897363                 NaN     NaN
2018-03-15  2017-12-31  4      中国平安人寿保险股份有限公司-传统-普通保险产品           证券品种        保险投资组合            None              2.269811          2.303679               NaN     NaN
2018-03-15  2017-12-31  5      香港中央结算有限公司                               企业           外资独资企业           None             2.124405         2.156103               NaN  NaN
2018-03-15  2017-12-31  6      中央汇金资产管理有限责任公司                        企业             资产管理公司         None          1.259219           1.278007                NaN     NaN
2018-03-15  2017-12-31  7      深圳中电投资股份有限公司                           企业            投资、咨询公司         None          1.083561           1.099729                NaN    NaN
2018-03-15  2017-12-31  8      河南鸿宝集团有限公司                               企业            一般企业               None            0.459273             0.466125              NaN  NaN
2018-03-15  2017-12-31  9      南方基金-农业银行-南方中证金融资产管理计划              证券品种        基金专户理财            None              0.336683          0.341707              NaN      NaN
2018-03-15  2017-12-31  10      新华人寿保险股份有限公司-分红-个人分红-018L-FH002深  证券品种        保险投资组合            None               0.311545          0.316193              NaN      NaN
```

### get_private_placement - 获取股票定向增发信息 {#rqdata-API-get_private_placement}

```python
get_private_placement(order_book_ids, start_date=None, end_date=None, progress='complete',issue_type='private', market='cn')
```

获取股票定向增发数据，支持按实施进度和发行方式筛选。例如可查询非公开发行、公开发行，以及已完成、未完成等状态的数据。

#### 参数 {#rqdata-API-get_private_placement-params}

| 参数          | 类型                                                           | 说明                                                                       |
| ------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| order_book_id | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list           |
| start_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认返回全部                                                     |
| end_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认返回全部                                                     |
| progress      | _str_                                                          | 是否已完成定增，默认为 complete。可选参数["complete", "incomplete", "all"] |
| issue_type    | _str_                                                          | 发行方式，默认为 private。可选参数["private", "public", "all"]             |
| market        | _str_                                                          | 市场，默认'cn'为中国内地市场。                                             |

#### 返回 {#rqdata-API-get_private_placement-return}

_pandas DataFrame_

| 字段               | 类型               | 说明         |
| ------------------ | ------------------ | ------------ |
| initial_info_date  | _pandas.Timestamp_ | 公告发布日   |
| issue_type         | _str_              | 发行方式     |
| progress           | _str_              | 目前进度     |
| listed_date        | _pandas.Timestamp_ | 上市日期     |
| issued_shares      | _float_            | 发行股数     |
| issue_price        | _float_            | 定增发行价   |
| csrc_approval_date | _pandas.Timestamp_ | 证监会批准日 |

#### 范例 {#rqdata-API-get_private_placement-example}

- 获取平安银行非公开发行实施完成的定增数据

```python
[In]
get_private_placement("000001.XSHE")
[Out]
                                     csrc_approval_date  issue_price  issue_type  issued_shares  listed_date  progress
order_book_id  initial_info_date
000001.XSHE     2009-06-13          2010-06-29                18.26  非公开发行      3.795800e+08  2010-09-17  实施完成
                 2010-09-02          2011-06-29                17.75  非公开发行      1.638337e+09  2011-08-05  实施完成
                 2013-09-09          2013-12-31                11.17  非公开发行      1.323385e+09  2014-01-09  实施完成
                 2014-07-16          2015-04-25                16.70  非公开发行      5.988024e+08  2015-05-21  实施完成
```

### get_allotment - 获取股票配股信息 {#rqdata-API-get-allotment}

```python
get_allotment(order_book_ids, start_date=None, end_date=None, fields=None, market='cn')
```

获取股票配股数据，包括计划配股比例、实际配股比例、实际配股数量、配股价格和除权日等信息。

#### 参数 {#rqdata-API-get_allotment-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认返回全部                                           |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认返回全部                                           |
| fields         | _str_ or _str list_                                            | 字段名称，默认返回全部                                           |
| market         | _str_                                                          | 市场，默认'cn'为中国内地市场                                     |

#### 返回 {#rqdata-API-get-allotment-return}

_pandas DataFrame_

| 字段                          | 类型               | 说明             |
| ----------------------------- | ------------------ | ---------------- |
| declaration_announcement_date | _pandas.Timestamp_ | 首次信息发布日期 |
| proportion                    | _float_            | 计划配股比例     |
| allotted_proportion           | _float_            | 实际配股比例     |
| allotted_shares               | _float_            | 实际配股数量(股) |
| allotment_price               | _float_            | 每股配股价格(元) |
| book_closure_date             | _pandas.Timestamp_ | 股权登记日       |
| ex_right_date                 | _pandas.Timestamp_ | 除权除息日       |

#### 范例 {#rqdata-API-get-allotment-example}

- 获取凯伦股份 20180101 到 20200101 的配股信息

```python
[In]
get_allotment('300715.XSHE','20180101','20200101')
[Out]

                                               proportion allotted_proportion  allotted_shares  \
order_book_id   declaration_announcement_date
300715.XSHE     2019-04-19                     0.3        0.29639              39074500.0


                          allotment_price   book_closure_date   ex_right_date
300715.XSHE  2019-04-19   12.64             2019-12-19          2019-12-30

```

### get_block_trade - 获取大宗交易数据 {#rqdata-API-get-block-trade}

```python
get_block_trade(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票大宗交易数据，包括成交价、成交量、成交额、买方营业部和卖方营业部等信息。

#### 参数 {#rqdata-API-get_block_trade-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                         |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_block_trade-return}

_pandas DataFrame_

| 字段           | 类型    | 说明       |
| -------------- | ------- | ---------- |
| price          | _float_ | 成交价     |
| volume         | _float_ | 成交量     |
| total_turnover | _float_ | 成交额     |
| buyer          | _str_   | 买方营业部 |
| seller         | _str_   | 卖方营业部 |

#### 范例 {#rqdata-API-get_block_trade-example}

- 获取单个合约大宗交易数据

```python
[In]
rqdatac.get_block_trade('000001.XSHE','20190101','20191010')
[Out]
                        price    volume  total_turnover                  buyer                  seller
order_book_id trade_date
000001.XSHE   2019-02-28  11.16    289300    3.228588e+06   广发证券股份有限公司汕头珠池路证券营业部    中信证券股份有限公司汕头海滨路证券营业部
              2019-05-06  12.47  36000000    4.489200e+08        华泰证券股份有限公司河南分公司         华泰证券股份有限公司河南分公司
              2019-05-07  11.58  33400000    3.867720e+08        华泰证券股份有限公司河南分公司         华泰证券股份有限公司河南分公司
              2019-05-08  11.66  28314899    3.301517e+08        申万宏源证券有限公司河南分公司  中国银河证券股份有限公司郑州经三路证券营业部
              2019-05-20  12.38   7362200    9.114404e+07                   机构专用                    机构专用
              2019-07-10  13.56    610000    8.271600e+06                   机构专用                    机构专用
              2019-08-15  14.67    763800    1.120495e+07      申万宏源证券有限公司上海第二分公司   中信证券股份有限公司广州花城大道证券营业部
              2019-08-19  14.50   1581699    2.293464e+07      申万宏源证券有限公司上海第二分公司    天风证券股份有限公司广州华夏路证券营业部
              2019-09-24  13.84    216000    2.989440e+06   天风证券股份有限公司深圳卓越城证券营业部    天风证券股份有限公司深圳卓越城证券营业部
              2019-09-24  15.03    135000    2.029050e+06  东兴证券股份有限公司上海肇嘉浜路证券营业部                    机构专用
              2019-09-25  13.66    240000    3.278400e+06   天风证券股份有限公司深圳卓越城证券营业部    天风证券股份有限公司深圳卓越城证券营业部


```

- 获取多个合约大宗交易数据

```python
[In]
rqdatac.get_block_trade(['000001.XSHE','000046.XSHE'],'20190101','20191010')
[Out]
                          price    volume  total_turnover                  buyer                  seller
order_book_id trade_date
000001.XSHE   2019-02-28  11.16    289300    3.228588e+06   广发证券股份有限公司汕头珠池路证券营业部    中信证券股份有限公司汕头海滨路证券营业部
              2019-05-06  12.47  36000000    4.489200e+08        华泰证券股份有限公司河南分公司         华泰证券股份有限公司河南分公司
              2019-05-07  11.58  33400000    3.867720e+08        华泰证券股份有限公司河南分公司         华泰证券股份有限公司河南分公司
              2019-05-08  11.66  28314899    3.301517e+08        申万宏源证券有限公司河南分公司  中国银河证券股份有限公司郑州经三路证券营业部
              2019-05-20  12.38   7362200    9.114404e+07                   机构专用                    机构专用
              2019-07-10  13.56    610000    8.271600e+06                   机构专用                    机构专用
              2019-08-15  14.67    763800    1.120495e+07      申万宏源证券有限公司上海第二分公司   中信证券股份有限公司广州花城大道证券营业部
              2019-08-19  14.50   1581699    2.293464e+07      申万宏源证券有限公司上海第二分公司    天风证券股份有限公司广州华夏路证券营业部
              2019-09-24  13.84    216000    2.989440e+06   天风证券股份有限公司深圳卓越城证券营业部    天风证券股份有限公司深圳卓越城证券营业部
              2019-09-24  15.03    135000    2.029050e+06  东兴证券股份有限公司上海肇嘉浜路证券营业部                    机构专用
              2019-09-25  13.66    240000    3.278400e+06   天风证券股份有限公司深圳卓越城证券营业部    天风证券股份有限公司深圳卓越城证券营业部
000046.XSHE   2019-09-27   3.91  44139500    1.725854e+08  中信证券股份有限公司天津大港证券交易营业部   申万宏源证券有限公司温州车站大道证券营业部

```

### get_symbol_change_info - 获取合约的历史简称信息 {#rqdata-API-get-symbol-change-info}

```python
get_symbol_change_info(order_book_ids, market='cn')
```

获取股票历史简称变更数据，包括简称变更日期、信息发布日期和各阶段简称。

#### 参数 {#rqdata-API-get-symbol-change-info-params}

| 参数           | 类型                | 说明                         |
| -------------- | ------------------- | ---------------------------- |
| order_book_ids | _str_ or _str list_ | 给出单个或多个 order_book_id |
| market         | _str_               | 默认是中国内地市场('cn')     |

#### 返回 {#rqdata-API-get-symbol-change-info-return}

_pandas DataFrame_

| 字段        | 类型               | 说明         |
| ----------- | ------------------ | ------------ |
| change_date | _pandas.Timestamp_ | 简称变更日期 |
| info_date   | _pandas.Timestamp_ | 信息发布日期 |
| symbol      | _str_              | 证券简称     |

#### 范例 {#rqdata-API-get-symbol-change-info-example}

- 获取单个合约简称变更数据

```python
[In]
rqdatac.get_symbol_change_info('000001.XSHE')
[Out]
                           info_date    symbol
order_book_id change_date
000001.XSHE   1991-04-03   1991-04-03    深发展Ａ
              2006-10-09   2006-09-28    S深发展A
              2007-06-20   2007-06-14    深发展Ａ
              2012-08-02   2012-01-20    平安银行
```

### get_special_treatment_info - 获取合约特殊处理状态信息 {#rqdata-API-get-special-treatment-info}

```python
get_special_treatment_info(order_book_ids, market='cn')
```

获取股票特殊处理状态变更数据。例如包括 ST、撤销ST、从ST变为\*ST、撤销\*ST并实行ST 等状态及对应说明。

#### 参数 {#rqdata-API-get-special-treatment-info-params}

| 参数           | 类型                | 说明                         |
| -------------- | ------------------- | ---------------------------- |
| order_book_ids | _str_ or _str list_ | 给出单个或多个 order_book_id |
| market         | _str_               | 默认是中国内地市场('cn')     |

#### 返回 {#rqdata-API-get-special-treatment-info-return}

_pandas DataFrame_

| 字段        | 类型               | 说明                     |
| ----------- | ------------------ | ------------------------ |
| change_date | _pandas.Timestamp_ | 特别处理(或撤销)实施日期 |
| info_date   | _pandas.Timestamp_ | 信息发布日期             |
| symbol      | _str_              | 证券简称                 |
| type        | _str_              | 特别处理(或撤销)类别     |
| description | _str_              | 特别处理(或撤销)事项描述 |

#### 范例 {#rqdata-API-get-special-treatment-info-example}

- 获取单个合约特殊处理状态数据

```python
[In]
rqdatac.get_special_treatment_info('000020.XSHE')
[Out]
                           info_date    symbol        type              description
order_book_id change_date
000020.XSHE   1999-04-27   1999-04-24   ST华发Ａ       ST
              2000-03-29   2000-03-28   深华发Ａ       撤销ST
              2004-04-27   2004-04-26   ST华发Ａ       ST                None
              2005-04-29   2005-04-28   *ST华发Ａ      从ST变为*ST        None
              2006-11-22   2006-11-21   SST华发A       撤消*ST并实行ST    None
              2009-05-19   2009-05-18   深华发Ａ       撤销ST             None
```

### current_freefloat_turnover - 获取当日累计自由流通换手率 {#rqdata-API-current-freefloat-turnover}

```python
rqdatac.current_freefloat_turnover(order_book_ids)
```

获取股票当日累计自由流通换手率数据，反映截至调用时点的盘中自由流通换手率。

#### 参数 {#rqdata-API-current-freefloat-turnover-params}

| 参数           | 类型                | 说明                         |
| -------------- | ------------------- | ---------------------------- |
| order_book_ids | _str_ or _str list_ | 给出单个或多个 order_book_id |

#### 返回 {#rqdata-API-current-freefloat-turnover-return}

_pandas Series_

| 字段           | 类型    | 说明                                                                                                        |
| -------------- | ------- | ----------------------------------------------------------------------------------------------------------- |
| 自由流通换手率 | _float_ | 截至到调用时间的当日累计自由流通换手率<br/>自由流通换手率=当日累计成交金额/自由流通市值（盘中实时分钟级别） |

#### 范例 {#rqdata-API-current-freefloat-turnover-example}

- 获取多个合约当日累计自由流通换手率

```python
[In]
rqdatac.current_freefloat_turnover(['000001.XSHE','600000.XSHG'])
[Out]
000001.XSHE    0.007206
600000.XSHG    0.002283
dtype: float64
```

### get_holder_number - 获取股东户数 {#rqdata-API-get_holder_number}

```python
rqdatac.get_holder_number(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票股东户数数据。例如包括股东总户数、A 股股东户数、户均持股数和无限售 A 股股东户均持股数。

#### 参数 {#rqdata-API-get_holder_number-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年当日                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为去年当日                             |
| market         | _str_                                                          | 默认是中国市场('cn')，目前仅支持中国市场             |

#### 返回 {#rqdata-API-get_holder_number-return}

_pandas DataFrame_

| 字段                          | 类型               | 说明                             |
| ----------------------------- | ------------------ | -------------------------------- |
| order_book_ids                | _str_              | 合约代码                         |
| info_date                     | _pandas.Timestamp_ | 发布日期                         |
| end_date                      | _pandas.Timestamp_ | 截止日期                         |
| share_holders                 | _float_            | 股东总户数(户)                   |
| avg_share_holders             | _float_            | 户均持股数(股/户)                |
| a_share_holders               | _float_            | A 股股东户数(户)                 |
| avg_a_share_holders           | _float_            | A 股股东户均持股数(股/户)        |
| avg_circulation_share_holders | _float_            | 无限售 A 股股东户均持股数(股/户) |

#### 范例 {#rqdata-API-get_holder_number-example}

- 获取一个合约最近一年的股东户数数据

```python
[In]
rqdatac.get_holder_number('000001.XSHE')
[Out]
                           end_date  share_holders  a_share_holders  avg_circulation_share_holders  avg_share_holders  avg_a_share_holders
order_book_id info_date
000001.XSHE   2023-03-09 2022-12-31       487200.0         487200.0                        39830.0           39831.52             39831.52
              2023-03-09 2023-02-28       477304.0         477304.0                        40656.0           40657.36             40657.36
              2023-04-25 2023-03-31       506867.0         506867.0                        38285.0           38286.02             38286.02
              2023-08-24 2023-06-30       536701.0         536701.0                        36157.0           36157.78             36157.78
              2023-10-25 2023-09-30       530229.0         530229.0                        36598.0           36599.13             36599.13
```

### get_abnormal_stocks - 获取龙虎榜每日明细 {#rqdata-API-get_abnormal_stocks}

```python
rqdatac.get_abnormal_stocks(start_date=None, end_date=None,types=None,market='cn')
```

获取龙虎榜每日明细数据，包括异动类型、异动起止日期、成交量、成交额、换手率、振幅和上榜原因等信息。

#### 参数 {#rqdata-API-get_abnormal_stocks-params}

| 参数       | 类型                                                           | 说明                                                                                                                                                                        |
| ---------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年当日                                                                                                                                                    |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为去年当日                                                                                                                                                    |
| types      | _str_                                                          | 异动类型。具体类型及描述见<a href="https://assets.ricequant.com/vendor/rqdata/异动类型代码及其对应原因.xlsx" target="_blank">异动类型代码及其对应原因</a ><br/>默认返回全部 |
| market     | _str_                                                          | 默认是中国市场('cn')，目前仅支持中国市场                                                                                                                                    |

#### 返回 {#rqdata-API-get_abnormal_stocks-return}

_pandas DataFrame_

| 字段            | 类型               | 说明                     |
| --------------- | ------------------ | ------------------------ |
| order_book_ids  | _str_              | 合约代码                 |
| date            | _pandas.Timestamp_ | 日期                     |
| type            | _str_              | 异动类型                 |
| abnormal_s_date | _pandas.Timestamp_ | 异动起始日期             |
| abnormal_e_date | _pandas.Timestamp_ | 异动截至日期             |
| volume          | _float_            | 成交量                   |
| total_turnover  | _float_            | 成交额                   |
| change_rate     | _float_            | 涨跌幅                   |
| turnover_rate   | _float_            | 换手率                   |
| amplitude       | _float_            | 振幅                     |
| deviation       | _float_            | 涨跌幅偏离值             |
| reason          | _str_              | 异动类型名称，即上榜原因 |

#### 范例 {#rqdata-API-get_abnormal_stocks-example}

- 获取某一天的龙虎榜数据

```python
[In]
rqdatac.get_abnormal_stocks(20240606,20240606)
[Out]
                         type abnormal_s_date abnormal_e_date       volume  total_turnover  change_rate  turnover_rate  amplitude  deviation                 reason
order_book_id date
000037.XSHE   2024-06-06  U01      2024-06-06      2024-06-06  60760000.00    6.371700e+08          NaN            NaN        NaN     0.1168              日涨幅偏离值达7%
002579.XSHE   2024-06-06  U01      2024-06-06      2024-06-06  42820000.00    3.247400e+08          NaN            NaN        NaN     0.1168              日涨幅偏离值达7%
003008.XSHE   2024-06-06  U01      2024-06-06      2024-06-06   7440000.00    1.334500e+08          NaN            NaN        NaN     0.1168              日涨幅偏离值达7%
002356.XSHE   2024-06-06  U01      2024-06-06      2024-06-06  20870000.00    7.025000e+07          NaN            NaN        NaN     0.1168              日涨幅偏离值达7%
003026.XSHE   2024-06-06  U01      2024-06-06      2024-06-06   1240000.00    3.906000e+07          NaN            NaN        NaN     0.1168              日涨幅偏离值达7%
...                       ...             ...             ...          ...             ...          ...            ...        ...        ...                    ...
600647.XSHG   2024-06-06  L01      2024-06-06      2024-06-06   9118026.00    1.309210e+07          NaN            NaN        NaN        NaN                   退市整理
600766.XSHG   2024-06-06  L01      2024-06-06      2024-06-06  27377520.00    9.662712e+06          NaN            NaN        NaN        NaN                   退市整理
603133.XSHG   2024-06-06  L01      2024-06-06      2024-06-06  25534776.00    8.026108e+06          NaN            NaN        NaN        NaN                   退市整理
600306.XSHG   2024-06-06  L01      2024-06-06      2024-06-06   4969300.00    1.642356e+06          NaN            NaN        NaN        NaN                   退市整理
600220.XSHG   2024-06-06  N03      2024-05-22      2024-06-06      2229.17    1.513860e+03          NaN            NaN        NaN        NaN  连续10个交易日内4次出现负向异常波动情形

[77 rows x 10 columns]
```

### get_abnormal_stocks_detail - 获取龙虎榜机构交易明细数据 {#rqdata-API-get_abnormal_stocks_detail}

```python
rqdatac.get_abnormal_stocks_detail(order_book_ids,start_date=None,end_date=None,sides=None,types=None,market='cn')
```

获取龙虎榜机构交易明细数据，支持按买卖方向和异动类型筛选，包括营业部名称、买入金额、卖出金额和上榜原因等信息。

#### 参数 {#rqdata-API-get_abnormal_stocks_detail-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                        |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                                            |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年当日                                                                                                                                                    |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为去年当日                                                                                                                                                    |
| sides          | _str_                                                          | 买卖方向，<br/>'buy'：买；<br/>'sell'：卖；<br/>'cum'：严重异常期间的累计数据。注意这里并不是指买卖方向的数据总和。<br/>默认返回全部                                        |
| types          | _str_                                                          | 异动类型。具体类型及描述见<a href="https://assets.ricequant.com/vendor/rqdata/异动类型代码及其对应原因.xlsx" target="_blank">异动类型代码及其对应原因</a ><br/>默认返回全部 |
| market         | _str_                                                          | 默认是中国市场('cn')，目前仅支持中国市场                                                                                                                                    |

#### 返回 {#rqdata-API-get_abnormal_stocks_detail-return}

_pandas DataFrame_

| 字段           | 类型               | 说明                     |
| -------------- | ------------------ | ------------------------ |
| order_book_ids | _str_              | 合约代码                 |
| date           | _pandas.Timestamp_ | 日期                     |
| rank           | _int_              | 排名                     |
| side           | _str_              | 买卖方向                 |
| agency         | _str_              | 营业部名称               |
| buy_value      | _float_            | 买入金额                 |
| sell_value     | _float_            | 卖出金额                 |
| reason         | _str_              | 异动类型名称，即上榜原因 |

#### 范例 {#rqdata-API-get_abnormal_stocks_detail-example}

- 获取某一天的龙虎榜机构交易明细数据

```python
[In]
rqdatac.get_abnormal_stocks_detail('000037.XSHE',20240606,20240606)
[Out]
                          side  rank                   agency    buy_value  sell_value type     reason
order_book_id date
000037.XSHE   2024-06-06   buy     1   国泰君安证券股份有限公司宜昌珍珠路证券营业部  19984430.00    145680.0  U01  日涨幅偏离值达7%
              2024-06-06   buy     2          中泰证券股份有限公司湖北分公司  15909115.00         0.0  U01  日涨幅偏离值达7%
              2024-06-06   buy     3        东亚前海证券有限责任公司广东分公司  11229691.00         0.0  U01  日涨幅偏离值达7%
              2024-06-06   buy     4   中泰证券股份有限公司莱芜鲁中东大街证券营业部  10631391.00    150130.0  U01  日涨幅偏离值达7%
              2024-06-06   buy     5     华鑫证券有限责任公司深圳益田路证券营业部   9847864.00         0.0  U01  日涨幅偏离值达7%
              2024-06-06  sell     1    海通证券股份有限公司泰安迎胜东路证券营业部   3703098.00  20295550.0  U01  日涨幅偏离值达7%
              2024-06-06  sell     2                     机构专用   5370201.99  12796800.0  U01  日涨幅偏离值达7%
              2024-06-06  sell     3     招商证券股份有限公司上海长柳路证券营业部   1229167.00   6726082.0  U01  日涨幅偏离值达7%
              2024-06-06  sell     4  海通证券股份有限公司上海黄浦区福州路证券营业部    140537.00   5134030.0  U01  日涨幅偏离值达7%
              2024-06-06  sell     5                     机构专用   2354284.00   5016705.0  U01  日涨幅偏离值达7%

```

### get_buy_back - 获取回购数据 {#rqdata-API-get-buy-back}

```python
rqdatac.get_buy_back(order_book_ids, start_date=None, end_date=None, fields=None, market='cn')
```

获取股份回购数据，包括事件进程、股份类别、回购期限、回购股数、回购金额、回购价格和回购方式等信息。

#### 参数 {#rqdata-API-get-buy-back-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 起始日期，默认返回最近三个月数据                                 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认返回最近三个月数据                                 |
| fields         | _str_ or _str list_                                            | 字段名称，默认返回全部                                           |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get-buy-back-return}

_pandas DataFrame_

| 字段                | 类型               | 说明                                                                                   |
| ------------------- | ------------------ | -------------------------------------------------------------------------------------- |
| order_book_ids      | _str_              | 合约代码                                                                              |
| date                | _pandas.Timestamp_ | 首次信息发布日                                                                         |
| seller              | _str_              | 股份被回购方                                                                           |
| procedure           | _str_              | 事件进程                                                                               |
| complete_info_date  | _pandas.Timestamp_ | 实施完成公告日                                                                         |
| share_type          | _str_              | 股份类别                                                                               |
| annoucement_dt      | _pandas.Timestamp_ | 公告发布当天的日期时间戳                                                               |
| buy_back_start_date | _pandas.Timestamp_ | 回购期限起始日                                                                         |
| buy_back_end_date   | _pandas.Timestamp_ | 回购期限截至日                                                                         |
| write_off_date      | _pandas.Timestamp_ | 回购注销公告日（该字段为空的时候代表这行记录尚未完成注销，有日期的时候代表已完成注销） |
| maturity_desc       | _str_              | 股份回购期限说明                                                                       |
| buy_back_volume     | _float_            | 回购股数(股)(份)                                                                       |
| volume_ceiling      | _float_            | 回购数量上限(股)(份)                                                                   |
| volume_floor        | _float_            | 回购数量下限(股)(份)                                                                   |
| buy_back_value      | _float_            | 回购总金额(元)                                                                         |
| buy_back_price      | _float_            | 回购价格(元/股)(元/份)                                                                 |
| price_ceiling       | _float_            | 回购价格上限(元)                                                                       |
| price_floor         | _float_            | 回购价格下限(元)                                                                       |
| currency            | _str_              | 货币单位                                                                               |
| purpose             | _str_              | 回购目的                                                                               |
| buy_back_percent    | _str_              | 占总股本比例                                                                           |
| volume_floor        | _float_            | 拟回购资金总额下限(元)                                                                 |
| value_ceiling       | _float_            | 拟回购资金总额上限(元)                                                                 |
| buy_back_mode       | _str_              | 股份回购方式                                                                           |

#### 范例 {#rqdata-API-get-buy-back-example}

- 获取某一天的回购数据

```python
[In]
rqdatac.get_buy_back('000026.XSHE',20200707,20200707)
[Out]
                          seller procedure complete_info_date  ... value_ceiling buy_back_mode      rice_create_tm
order_book_id date                                               ...
000026.XSHE   2020-07-07  1名离职激励对象      实施完成         2020-09-16  ...  8.966526e+04          协议回购 2024-06-28 18:22:52
              2020-07-07    社会公众股东      实施完成         2021-03-02  ...  1.755500e+08          集中竞价 2024-06-28 18:22:52

```

## 融资融券和南北向数据 {#rqdata-API-capital_flow}

### get_capital_flow - 获取股票资金流入流出 {#rqdata-API-get_capital_flow}

```python
get_capital_flow(order_book_ids, start_date=None, end_date=None, frequency='1d', market='cn')
```

获取股票资金流入流出数据，支持日线、分钟和 tick 级别。例如可获取主动买入股数与金额、主动卖出股数与金额，或快照级别的方向、股数和金额。

#### 参数 {#rqdata-API-get_capital_flow-params}

| 参数           | 类型                                                           | 说明                                                                                    |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                        |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                                |
| frequency      | _str_                                                          | 默认为'1d' 即单日级别，另支持'1m'和'tick'。目前不支持 resample，即 5d,5m 等分时图无内置 |
| market         | _str_                                                          | 默认是中国市场('cn')，目前仅支持中国市场                                                |

#### 返回 {#rqdata-API-get_capital_flow-return}

_pandas multi-index DataFrame_

##### 日线及分钟线返回的字段：

| 字段             | 类型               | 说明             |
| ---------------- | ------------------ | ---------------- |
| order_book_id    | _str_              | 合约代码，索引一 |
| date 或 datetime | _pandas.Timestamp_ | 时间，索引二     |
| buy_volume       | _integer_          | 主动买的股数     |
| buy_value        | _integer_          | 主动买的合计金额 |
| sell_volume      | _integer_          | 主动卖的股数     |
| sell_value       | _integer_          | 主动卖的合计金额 |

##### 快照级别返回的字段：

| 字段          | 类型               | 说明                    |
| ------------- | ------------------ | ----------------------- |
| order_book_id | _str_              | 合约代码，索引一        |
| datetime      | _pandas.Timestamp_ | 时间，索引二            |
| direction     | _integer_          | 1 为主动买，-1 为主动卖 |
| volume        | _integer_          | 变动股数                |
| value         | _integer_          | 变动金额                |

::: tip 计算逻辑说明 {#rqdata-API-get_capital_flow-tip}

其中，关于买卖方向的判断：

1. 对于涨停，即卖一询价为空，买一非空，则为主动买
2. 对于跌停，即买一询价为空，卖一非空，则为主动卖
3. 如果，最新价>=上一笔的卖一询价，则为主动买
4. 如果，最新价<=上一笔的买一询价，则为主动卖
5. 否则，取前一笔的买卖方向

另，连续竞价撮合成当天第一笔交易的，成交价>=上一笔卖询价，为主动买，否则为主动卖。

该 API 基于 level 1 数据合成，所以暂且不对资金量（大中小）作主观分类。

:::

#### 范例 {#rqdata-API-get_capital_flow-example}

- 获取平安银行某日快照级别资金流入流出：

```python
[In]
get_capital_flow('000001.XSHE',start_date=20190412,end_date=20190412,frequency='tick')

[Out]
  direction  value  volume
datetime
2019-04-12 09:25:03  1  4311404  319600
2019-04-12 09:26:03  1  0  0
2019-04-12 09:27:03  1  0  0
2019-04-12 09:28:03  1  0  0
2019-04-12 09:29:03  1  0  0
2019-04-12 09:30:00  1  0  0
2019-04-12 09:30:03  1  3472850  256860
2019-04-12 09:30:06  1  836686  61936
2019-04-12 09:30:09  -1  994734  73600
2019-04-12 09:30:12  -1  550366  40700
2019-04-12 09:30:15  -1  1002377  74200
...
```

- 获取多只股票日级别资金流入流出：

```python
[In]
get_capital_flow(['000001.XSHE','000002.XSHE'],start_date=20190412,end_date=20190415,frequency='1d')

[Out]
  buy_volume  buy_value  sell_volume  sell_value
order_book_id  date
000001.XSHE  2019-04-12  42805075  572261719  34627389  462877954
2019-04-15  72481761  1008887497  80907307  1125821484
000002.XSHE  2019-04-12  22722286  708667739  25521391  795822317
2019-04-15  25321496  799505139  30459357  959805142
...
```

### current_capital_flow_minute - 获取最近的分钟资金流数据 {#rqdata-API-current_capital_flow_minute}

```python
current_capital_flow_minute(order_book_ids, market='cn')
```

获取股票当日最近一分钟的资金流入流出数据，包括主动买入和主动卖出的股数与金额。

#### 参数 {#rqdata-API-current_capital_flow_minute-params}

| 参数           | 类型                | 说明                     |
| -------------- | ------------------- | ------------------------ |
| order_book_ids | _str_ or _str list_ | 合约代码                 |
| market         | _str_               | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-current_capital_flow_minute-return}

_pandas DataFrame_

| 字段             | 类型               | 说明             |
| ---------------- | ------------------ | ---------------- |
| order_book_id    | _str_              | 合约代码，索引一 |
| date 或 datetime | _pandas.Timestamp_ | 时间，索引二     |
| buy_volume       | _integer_          | 主动买的股数     |
| buy_value        | _integer_          | 主动买的合计金额 |
| sell_volume      | _integer_          | 主动卖的股数     |
| sell_value       | _integer_          | 主动卖的合计金额 |

#### 范例 {#rqdata-API-current_capital_flow_minute-example}

- 获取某股票最近一分钟的资金流入流出：

```python
[In]
current_capital_flow_minute(['000001.XSHE','600000.XSHG'])

[Out]
                              buy_volume buy_value sell_volume sell_value
order_book_id   datetime
000001.XSHE 2024-09-19 11:30:00   55400.0 542977.0 51500.0     504757.0
600000.XSHG 2024-09-19 11:30:00   28200.0 238271.0 9600.0     81092.0
```

### get_securities_margin - 获取融资融券信息 {#rqdata-API-get_securities_margin}

```python
get_securities_margin(order_book_ids, start_date=None, end_date=None, fields=None, expect_df=True, market='cn')

```

获取融资融券数据，既支持个股，也支持上证和深证市场整体数据。例如可查询融资余额、融资买入额、融券余量、融券卖出量和融资融券余额等信息。

#### 参数 {#rqdata-API-get_securities_margin-params}

| 参数           | 类型                                                           | 说明                                                                                                                             |
| -------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，可输入 order_book_id, order_book_id list。另外，输入'XSHG'或'sh'代表整个上证整体情况；'XSHE'或'sz'代表深证整体情况 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认取最近三个月的数据                                                                                                 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前有数据的最新日期                                                                                             |
| fields         | _str_ or _str list_                                            | 默认为所有字段。见下方列表                                                                                                       |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构                                                                  |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                                                                                         |

#### 返回 {#rqdata-API-get_securities_margin-return}

_pandas DataFrame_

| 字段                     | 类型    | 说明         |
| ------------------------ | ------- | ------------ |
| margin_balance           | _float_ | 融资余额     |
| buy_on_margin_value      | _float_ | 融资买入额   |
| margin_repayment         | _float_ | 融资偿还额   |
| short_balance            | _float_ | 融券余额     |
| short_balance_quantity   | _float_ | 融券余量     |
| short_sell_quantity      | _float_ | 融券卖出量   |
| short_repayment_quantity | _float_ | 融券偿还量   |
| total_balance            | _float_ | 融资融券余额 |

#### 范例 {#rqdata-API-get_securities_margin-example}

- 获取沪深两个市场一段时间内的融资余额

```python
[In]
get_securities_margin('510050.XSHG', start_date='20160801', end_date='20160805',expect_df=False)
[Out]
margin_balance buy_on_margin_value short_sell_quantity margin_repayment short_balance_quantity short_repayment_quantity short_balance total_balance
2016-08-01 7.811396e+09 50012306.0 3597600.0 41652042.0 15020600.0 1645576.0 NaN NaN
2016-08-02 7.826381e+09 34518238.0 2375700.0 19532586.0 14154000.0 3242300.0 NaN NaN
2016-08-03 7.733306e+09 17967333.0 4719700.0 111043009.0 16235600.0 2638100.0 NaN NaN
2016-08-04 7.741497e+09 30259359.0 6488600.0 22068637.0 17499000.0 5225200.0 NaN NaN
2016-08-05 7.726343e+09 25270756.0 2865863.0 40423859.0 14252363.0 6112500.0 NaN NaN
```

- 获取沪深两个市场一段时间内的融资余额

```python
[In]
get_securities_margin(['XSHE', 'XSHG'],start_date='20160801', end_date='20160802', fields='margin_balance')
[Out]
                         margin_balance
order_book_id date
XSHE        2016-08-01    383762696120
             2016-08-02    382892321734
XSHG        2016-08-01    476355670754
             2016-08-02    476393053057
```

- 获取 50ETF 融资偿还额情况

```python
[In]
get_securities_margin('510050.XSHG', start_date='20160801', end_date='20160805', fields='margin_repayment')
[Out]
                                      margin_repayment
order_book_id   date
510050.XSHG     2016-08-01             41652042
                2016-08-02             19532586
                2016-08-03             111043009
                2016-08-04             22068637
                2016-08-05             40423859
```

### get_margin_stocks - 获取融资融券股票列表 {#rqdata-API-get_margin_stocks}

```python
get_margin_stocks(date=None, exchange=None,margin_type='stock',market='cn')
```

获取指定日期的融资融券证券列表，支持按深交所或上交所、融券卖出或融资买入口径查询。

#### 参数 {#rqdata-API-get_margin_stocks-params}

| 参数        | 类型                                                           | 说明                                                                                              |
| ----------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| date        | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为今天上一交易日                                                                    |
| exchange    | _str_                                                          | 交易所，默认为 None，返回所有字段。可选字段包括：'XSHE', 'sz' 代表深交所；'XSHG', 'sh' 代表上交所 |
| margin_type | _str_                                                          | 'stock' 代表融券卖出，'cash'，代表融资买入，默认为'stock'                                         |

#### 返回 {#rqdata-API-get_margin_stocks-return}

_list 证券列表_ - 如果所查询日期没有融资融券股票列表，则返回空 list

#### 范例 {#rqdata-API-get_margin_stocks-example}

- 获取沪深市场的融券卖出列表

```python
[In]
get_margin_stocks(date='20190819',exchange=None,margin_type='stock')
[Out]
['000001.XSHE',
 '000002.XSHE',
 '000006.XSHE',
 ...]

```

- 获取沪深市场融资买入列表

```python
[In]
get_margin_stocks(date='20190819',exchange=None,margin_type='cash')
[Out]
['000001.XSHE',
 '000002.XSHE',
 '000006.XSHE',
 ...]

```

- 获取深证融券卖出列表

```python
[In]
get_margin_stocks(date='20190819',exchange='XSHE',margin_type='stock')
[Out]
['000001.XSHE',
 '000002.XSHE',
 '000006.XSHE',
 ...]
```

- 获取上证融资买入列表

```python
[In]
get_margin_stocks(date='20190819',exchange='XSHG',margin_type='cash')
[Out]
['510050.XSHG',
 '510160.XSHG',
 '510180.XSHG',
 ...]
```

### get_eligible_securities_margin - 获取融资融券可充抵保证金证券信息 {#rqdata-API-get_eligible_securities_margin}

```python
get_eligible_securities_margin(date=None, exchange=None,market='cn')
```

获取融资融券可充抵保证金证券列表，支持按交易所查询，不含地方债和公司债。

#### 参数 {#rqdata-API-get_eligible_securities_margin-params}

| 参数     | 类型                                                           | 说明                                                                                                                                                  |
| -------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为调用日期上一交易日                                                                                                                    |
| exchange | _str_                                                          | 交易所，默认为 None，返回上交所深交所全部数据。可选字段包括：'XSHE', 'sz' 代表深交所；'XSHG', 'sh' 代表上交所（上交所目前仅提供2026-01-12至今的数据） |

#### 返回 {#rqdata-API-get_eligible_securities_margin-return}

_list 证券列表_ - 如果所查询日期没有融资融券可充抵保证金证券信息，则返回空 list

#### 范例 {#rqdata-API-get_eligible_securities_margin-example}

- 获取深市的融资融券可充抵保证金证券信息

```python
[In]
rqdatac.get_eligible_securities_margin(date=20260112,exchange='sh')
[Out]
['600876.XSHG', '603758.XSHG', '603097.XSHG', '688981.XSHG', '688272.XSHG', ... , '601728.XSHG', '600593.XSHG', '688721.XSHG', '688372.XSHG', '600830.XSHG']

```

### get_margin_haircut - 获取可充抵保证金证券及折算率数据 {#rqdata-API-get_margin_haircut}

```python
get_margin_haircut(order_book_ids,start_date=None,end_date=None,market='cn')
```

获取可充抵保证金证券及折算率数据，提供范围 2012-08-30 至今

#### 参数 {#rqdata-API-get_margin_haircut-params}

| 参数          | 类型                                                           | 说明                                                      |
|-----|-----|-----|
| order_book_id | _str or str list_                                              | **必填参数**，可输入 order_book_id, order_book_id list     |
| start_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market        | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；      |

#### 返回 {#rqdata-API-get_margin_haircut-return}

_pandas DataFrame_

| 字段                     | 类型    | 说明         |
| ------------------------ | ------- | ------------ |
| advance_rate             | _float_ | 折算率       |
| haircut_rate             | _float_ | 折扣率       |


#### 范例 {#rqdata-API-get_margin_haircut-example}

- 获取深市的融资融券可充抵保证金证券信息

```python
[In]
rqdatac.get_margin_haircut('000001.XSHE',20260610,20260621)
[Out]
                        advance_rate	haircut_rate
order_book_id	date		
000001.XSHE	2026-06-10	0.65	0.35
            2026-06-11	0.65	0.35
            2026-06-12	0.65	0.35
            2026-06-15	0.65	0.35
            2026-06-16	0.65	0.35
            2026-06-17	0.65	0.35
            2026-06-18	0.65	0.35


```


### get_stock_connect - 获取沪深股通持股信息 {#rqdata-API-get_stock_connect}

```python
get_stock_connect(order_book_ids, start_date=None, end_date=None, fields=None, expect_df=True)
```

获取沪深股通持股数据，支持单只股票以及沪股通、深股通或全部北向标的。例如可查询持股量、持股比例和调整后持股比例。

#### 参数 {#rqdata-API-get_stock_connect-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                                                  |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_                                                          | 可输入 order_book_id 或 symbol。另，<br/>1、输入‘shanghai_connect'可返回沪股通的全部股票数据。<br/>2、输入'shenzhen_connect'可返回深股通的全部股票数据。<br/>3、输入'all_connect'可返回沪股通、深股通的全部股票数据。 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为'2017-03-17'                                                                                                                                                                                          |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为'2018-03-16'                                                                                                                                                                                          |
| fields         | _str_ OR _str list_                                            | 默认为所有字段。见下方列表                                                                                                                                                                                            |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构                                                                                                                                                       |

#### 返回 {#rqdata-API-get_stock_connect-return}

_pandas DataFrame_

| 字段                   | 类型    | 说明           |
| ---------------------- | ------- | -------------- |
| shares_holding         | _float_ | 持股量         |
| holding_ratio          | _float_ | 持股比例       |
| adjusted_holding_ratio | _float_ | 调整后持股比例 |

#### 范例 {#rqdata-API-get_stock_connect-example}

- 获取德赛电池持股概况

```python
[In]
get_stock_connect('000049.XSHE',start_date='2018-05-08',end_date='2018-05-10')
[Out]
                            shares_holding holding_ratio    adjusted_holding_ratio
order_book_id   trading_date
000049.XSHE     2018-05-08 194295.0 0.09             0.0947
                2018-05-09 144228.0 0.07             0.0703
                2018-05-10 136628.0 0.06             0.0666
```

- 获取沪股通持股概况

```python
[In]
df = get_stock_connect('shanghai_connect',start_date='20180508',end_date='20180510',expect_df=True)
df.head()
[Out]
                            shares_holding  holding_ratio  adjusted_holding_ratio
order_book_id trading_date
600000.XSHG   2018-05-08       156945807.0           0.55                  0.5585
              2018-05-09       157301679.0           0.55                  0.5597
              2018-05-10       160277136.0           0.57                  0.5703
600004.XSHG   2018-05-08       259814825.0          12.55                 12.5556
              2018-05-09       261758055.0          12.64                 12.6495

```

### current_stock_connect_quota - 获取沪深港通实时每日额度数据 {#rqdata-API-current_stock_connect_quota}

```python
current_stock_connect_quota(connect=None, fields=None)
```

获取沪深港通实时每日额度数据，支持沪股通、深股通、港股通（上海）和港股通（深圳）。例如可查询额度余额、额度占比、买方金额和卖方金额。

#### 参数 {#rqdata-API-current_stock_connect_quota-params}

| 参数    | 类型                | 说明                                                                                                                                                                                                                     |
| ------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| connect | _str_ or _str list_ | 默认返回全部 connect <br/>1、输入输入'hk_to_sh'返回沪股通的额度信息。<br/>2、输入'hk_to_sz'返回深股通的额度信息。<br/>3、输入'sh_to_hk'返回港股通（上海）的额度信息。 <br/>4、输入'sz_to_hk'返回港股通（深圳）的额度信息 |
| fields  | _str_ or _str list_ | 默认为所有字段。见下方列表                                                                                                                                                                                               |

#### 返回 {#rqdata-API-current_stock_connect_quota-return}

_pandas DataFrame_

| fields              | 类型    | 字段名   | 说明                                                                                 |
| ------------------- | ------- | -------- | ------------------------------------------------------------------------------------ |
| quota_balance       | _float_ | 余额     |                                                                                      |
| quota_balance_ratio | _float_ | 占比     |                                                                                      |
| buy_turnover        | _float_ | 买方金额 | <br/>1、沪股通和深股通单位为 RMB ，<br/>2、 港股通（上海）. 港股通（深圳）单位为 HKD |
| sell_turnover       | _float_ | 卖方金额 | <br/>1、沪股通和深股通单位为 RMB ，<br/>2、 港股通（上海）. 港股通（深圳）单位为 HKD |

#### 范例 {#rqdata-API-current_stock_connect_quota-example}

```python
[In]
current_stock_connect_quota()
[Out]
  buy_turnover sell_turnover quota_balance quota_balance_ratio
datetime connect
2020-05-26 16:10:00 sh_to_hk 5.463000e+09 3.548000e+09 3.969274e+10 0.945065
2020-05-26 15:01:00 hk_to_sh 1.115100e+10 1.015700e+10 5.024400e+10 0.960000
2020-05-26 16:10:00 sz_to_hk 5.474000e+09 3.178000e+09 3.926800e+10 0.934952
2020-05-26 15:01:00 hk_to_sz 1.803100e+10 1.513800e+10 4.847800e+10 0.930000

```

### get_stock_connect_quota - 获取沪深港通历史每日额度数据 {#rqdata-API-get_stock_connect_quota}

```python
get_stock_connect_quota(connect=None, start_date=None, end_date=None, fields=None)
```

获取沪深港通历史每日额度数据，支持沪股通、深股通、港股通（上海）和港股通（深圳）。例如可查询额度余额、额度占比、买方金额和卖方金额。

#### 参数 {#rqdata-API-get_stock_connect_quota-params}

| 参数       | 类型                                                           | 说明                                                                                                                                                                                                                 |
| ---------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| connect    | _str_ or _str list_                                            | 默认返回全部 connect <br/>1、输入'hk_to_sh'返回沪股通的额度信息。<br/>2、输入'hk_to_sz'返回深股通的额度信息。<br/>3、输入'sh_to_hk'返回港股通（上海）的额度信息。 <br/>4、输入'sz_to_hk'返回港股通（深圳）的额度信息 |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 默认为全部历史数据                                                                                                                                                                                                   |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 默认为最新日期                                                                                                                                                                                                       |
| fields     | _str_ or _str list_                                            | 默认为所有字段。见下方列表                                                                                                                                                                                           |

#### 返回 {#rqdata-API-get_stock_connect_quota-return}

_pandas DataFrame_

| fields              | 类型    | 字段名   | 说明                                                                                 |
| ------------------- | ------- | -------- | ------------------------------------------------------------------------------------ |
| quota_balance       | _float_ | 余额     |                                                                                      |
| quota_balance_ratio | _float_ | 占比     |                                                                                      |
| buy_turnover        | _float_ | 买方金额 | <br/>1、沪股通和深股通单位为 RMB ，<br/>2、 港股通（上海）. 港股通（深圳）单位为 HKD |
| sell_turnover       | _float_ | 卖方金额 | <br/>1、沪股通和深股通单位为 RMB ，<br/>2、 港股通（上海）. 港股通（深圳）单位为 HKD |

#### 范例 {#rqdata-API-get_stock_connect_quota-example}

获取指定时间段的深股通的额度信息

```
In [20]: get_stock_connect_quota(connect='hk_to_sz',start_date=20200101,end_date=20200401)
Out[20]:
                     buy_turnover  quota_balance  quota_balance_ratio  sell_turnover
datetime   connect
2020-01-02 hk_to_sz  4.353300e+09   4.018800e+12             0.956857   2.846830e+09
2020-01-03 hk_to_sz  3.477980e+09   4.079900e+12             0.971405   2.572800e+09
2020-01-06 hk_to_sz  3.737750e+09   4.094900e+12             0.974976   3.033440e+09
2020-01-07 hk_to_sz  3.248760e+09   4.076700e+12             0.970643   2.357280e+09
2020-01-08 hk_to_sz  3.299240e+09   4.114200e+12             0.979571   2.790880e+09
···

```

## 公告相关 {#rqdata-API-announcement}

### get_incentive_plan - 获取合约股权激励数据 {#rqdata-API-get-incentive-plan}

```python
rqdatac.get_incentive_plan(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取股票股权激励数据。例如可查询草案或调整记录，以及首次信息发布日期、生效日期、激励股票数量、激励价格和激励模式。

#### 参数 {#rqdata-API-get-incentive-plan-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填         |
| market         | _str_                                                          | 默认是中国内地市场('cn')                             |

#### 返回 {#rqdata-API-get-incentive-plan-return}

_pandas DataFrame_

| 字段            | 类型               | 说明                   |
| --------------- | ------------------ | ---------------------- |
| info_date       | _pandas.Timestamp_ | 信息发布日期           |
| first_info_date | _pandas.Timestamp_ | 首次信息发布日期       |
| effective_date  | _pandas.Timestamp_ | 生效日期               |
| shares_num      | _float_            | 激励股票数量           |
| incentive_price | _float_            | 激励价格(元)           |
| incentive_mode  | _str_              | 激励模式               |
| info_type       | _str_              | 公告类型，草案或者调整 |

#### 范例 {#rqdata-API-get-incentive-plan-example}

- 获取单个合约股权激励数据

```python
[In]
rqdatac.get_incentive_plan('002074.XSHE')
[Out]
                              first_info_date   effective_date  shares_num    incentive_price incentive_mode info_type
order_book_id info_date
002074.XSHE   2021-08-28      2021-08-28        2021-08-28      29980000.0    39.30           股票期权        草案
              2022-04-29      2022-04-29        2022-04-29      60000000.0    18.77           股票期权        草案
              2022-07-09      2021-08-28        2022-07-09      29980000.0    39.20           股票期权        调整
              2022-07-09      2022-04-29        2022-07-09      59687500.0    18.67           股票期权        调整
```

### get_investor_ra - 获取投资者关系活动数据 {#rqdata-API-get-investor-ra}

```python
rqdatac.get_investor_ra(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取投资者关系活动数据，包括信息发布日期、参与人员、调研机构和与会描述。

#### 参数 {#rqdata-API-get-investor-ra-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填         |
| market         | _str_                                                          | 默认是中国内地市场('cn')                             |

#### 返回 {#rqdata-API-get-investor-ra-return}

_pandas DataFrame_

| 字段              | 类型               | 说明         |
| ----------------- | ------------------ | ------------ |
| info_date         | _pandas.Timestamp_ | 信息发布日期 |
| participant       | _str_              | 参与人员     |
| institution       | _str_              | 调研机构     |
| detail            | _str_              | 与会描述     |
| reception_date    | _str_              | 接待日期     |
| activity_category | _str_              | 活动类别     |

#### 范例 {#rqdata-API-get-investor-ra-example}

- 获取单个合约投资者关系活动数据

```python
[In]
rqdatac.get_investor_ra('002507.XSHE')
[Out]
                              participant  institute   detail
order_book_id info_date
002507.XSHE   2012-08-15          唐桦      博时基金     None
              2012-08-15         张延鹏      朱雀投资    None
              2012-08-15         黄仕川      西南证券    None
              2012-08-15          解睿      平安证券     None
              2012-09-17        None          None      吕耀子
...                              ...          ...       ...
              2022-08-29         陈硕旸      长江证券    None
              2022-09-09         王亦沁      鹏扬基金    None
              2022-09-09          沈瑞      浦银安盛     None
              2022-09-09          赵钦  国海富兰克林基金  None
              2022-09-09         王明明      嘉实基金    None

[592 rows x 3 columns]
```

### get_announcement - 获取公司公告数据 {#rqdata-API-get-announcement}

```python
rqdatac.get_announcement(order_book_ids, start_date=None, end_date=None, fields=None, market='cn')
```

获取公司公告数据。例如可查询媒体出处、内容类别、标题、语言、文件格式、信息类别和公告链接等信息。

#### 参数 {#rqdata-API-get-announcement-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填         |
| fields         | _list_                                                         | 可选字段见下方返回，若不指定，则默认获取所有字段     |
| market         | _str_                                                          | 默认是中国内地市场('cn')                             |

#### 返回 {#rqdata-API-get-announcement-return}

_pandas DataFrame_

| 字段              | 类型               | 说明     |
| ----------------- | ------------------ | -------- |
| order_book_ids    | _str_              | 合约代码 |
| info_date         | _pandas.Timestamp_ | 发布日期 |
| meida             | _str_              | 媒体出处 |
| category          | _str_              | 内容类别 |
| title             | _str_              | 标题     |
| language          | _str_              | 语言     |
| file_type         | _str_              | 文件格式 |
| info_type         | _str_              | 信息类别 |
| announcement_link | _str_              | 公告链接 |
| create_tm         | _pandas.Timestamp_ | 入库时间 |

#### 范例 {#rqdata-API-get-announcement-example}

- 获取一个合约某个时间段内的公司公告数据

```python
[In]
rqdatac.get_announcement('000001.XSHE',20221001,20221010)
[Out]
                          media  category                           title language file_type info_type                                  announcement_link           create_tm
order_book_id info_date
000001.XSHE   2022-10-09  中国货币网        16    平安银行股份有限公司2022年第117期同业存单发行公告     简体中文       PDF     发行上市书  https://www.chinamoney.com.cn/dqs/cm-s-notice-... 2022-10-09 16:43:03
              2022-10-10  中国货币网        99  平安银行股份有限公司2022年第117期同业存单发行情况公告     简体中文       PDF      临时公告  https://www.chinamoney.com.cn/dqs/cm-s-notice-... 2022-10-10 16:41:28
              2022-10-10  中国货币网        16    平安银行股份有限公司2022年第118期同业存单发行公告     简体中文       PDF     发行上市书  https://www.chinamoney.com.cn/dqs/cm-s-notice-... 2022-10-10 17:41:15

```

### get_audit_opinion - 获取财务报告审计意见 {#rqdata-API-get-audit-opinion}

```python
get_audit_opinion(order_book_ids, start_quarter, end_quarter, date=None, type=None, opinion_types=None, market='cn')
```

获取财务报告审计意见数据，支持财务报表审计报告和内部控制审计报告，也支持无保留、保留意见、否定意见等审计意见类型。

#### 参数 {#rqdata-API-get-audit-opinion-params}

| 参数           | 类型                                                           | 说明                                                                                                          |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id                                                          |
| start_quarter  | _str_                                                          | **必填参数**，财报回溯查询的起始报告期，例如'2015q2'代表 2015 年半年报                                        |
| end_quarter    | _str_                                                          | **必填参数**，财报回溯查询的截止报告期，例如'2015q4'代表 2015 年年报                                          |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认查询日期为当前最新日期                                                                          |
| type           | _str or list_                                                  | 需要返回的审计报告类型:<br/>'financial_statements'：财务报表审计报告<br/>'internal_control'：内部控制审计报告 |
| opinion_types  | _str or list_                                                  | 需要返回的审计意见类型，详细类型见下方表格。默认返回所有                                                      |
| market         | _str_                                                          | 市场，默认'cn'为中国内地市场                                                                                  |

##### 审计意见类型 {#rqdata-API-get-audit-opinion-type}

| opinion_type                 | 说明                         |
| ---------------------------- | ---------------------------- |
| unqualified                  | 无保留                       |
| unqualified_with_explanation | 无保留带解释性说明           |
| qualified                    | 保留意见                     |
| disclaimer                   | 拒绝/无法表示意见            |
| adverse                      | 否定意见                     |
| unaudited                    | 未经审计                     |
| qualified_with_explanation   | 保留带解释性说明             |
| uncertainty_audit            | 经审计(不确定具体意见类型)   |
| material_uncertainty         | 无保留带持续经营重大不确定性 |

#### 返回 {#rqdata-API-get-audit-opinion-return}

_pandas DataFrame_

| 字段         | 类型               | 说明         |
| ------------ | ------------------ | ------------ |
| info_date    | _pandas.Timestamp_ | 公告发布日   |
| quarter      | _str_              | 报告期       |
| type         | _str_              | 审计报告类型 |
| audit_agency | _str_              | 会计师事务所 |
| opinion_type | _str_              | 审计意见类型 |

#### 范例 {#rqdata-API-get-audit-opinion-example}

- 获取一个合约某个报告期的审计意见数据

```python
[In]
rqdatac.get_audit_opinion('000001.XSHE', start_quarter='2023q4', end_quarter='2023q4',opinion_types=None)
[Out]
                                audit_agency              type             info_date opinion_type
order_book_id quarter
000001.XSHE     2023q4 安永华明会计师事务所(特殊普通合伙) internal_control     2024-03-15 unqualified
                2023q4 安永华明会计师事务所(特殊普通合伙) financial_statements 2024-03-15 unqualified

```

### get_restricted_shares - 获取股票限售解禁明细数据 {#rqdata-API-get_restricted_shares}

```python
rqdatac.get_restricted_shares(order_book_ids, start_date=None, end_date=None,market='cn')
```

获取股票限售解禁明细数据，包括解禁日期、股东属性、解除限售股份数量、实际上市流通数量和解禁原因。

#### 参数 {#rqdata-API-get_restricted_shares-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填         |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。                          |

#### 返回 {#rqdata-API-get_restricted_shares-return}

_pandas DataFrame_

| 字段                   | 类型               | 说明                                             |
| ---------------------- | ------------------ | ------------------------------------------------ |
| order_book_ids         | _str_              | 合约代码                                         |
| info_date              | _pandas.Timestamp_ | 发布日期                                         |
| relieve_date           | _pandas.Timestamp_ | 解禁日期                                         |
| shareholder_attr       | _str_              | 股东属性                                         |
| relieve_shares         | _float_            | 解除限售股份数量(股)                             |
| auctual_relieve_shares | _float_            | 实际上市流通数量(股)(提供范围为 2024-01-01 至今) |
| reason                 | _str_              | 解禁原因                                         |

#### 范例 {#rqdata-API-get_restricted_shares-example}

- 获取一个合约某个时间段内的解禁明细数据

```python
[In]
rqdatac.get_restricted_shares('000001.XSHE',20100101,20240101)
[Out]
                         relieve_date          shareholder_name shareholder_attr  relieve_shares auctual_relieve_shares       reason
order_book_id info_date
000001.XSHE   2010-06-25   2010-06-28          中国平安保险（集团）股份有限公司               企业    1.812557e+08                   None     股权分置限售流通
              2010-09-16   2013-11-12            中国平安人寿保险股份有限公司               企业    6.073280e+08                   None   增发A股法人配售上市
              2011-07-29   2014-09-01          中国平安保险（集团）股份有限公司               企业    3.145606e+09                   None  增发A股原股东配售上市
              2014-01-08   2017-01-09          中国平安保险（集团）股份有限公司               企业    2.286809e+09                   None  增发A股原股东配售上市
              2015-05-20   2016-05-23  财通基金-兴业银行-鹏华资产管理(深圳)有限公司             证券品种    2.952090e+05                   None   增发A股法人配售上市



```

### get_staff_count - 获取员工数量数据 {#rqdata-API-get_staff_count}

```python
rqdatac.get_staff_count(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取员工数量数据，包括截止日期和职工总数。

#### 参数 {#rqdata-API-get_staff_count-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认值 None，返回全部数据                              |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认值 None，返回全部数据                              |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_staff_count-return}

_pandas DataFrame_

| 字段           | 类型               | 说明     |
| -------------- | ------------------ | -------- |
| order_book_ids | _str_              | 合约代码 |
| info_date      | _pandas.Timestamp_ | 发布日期 |
| end_date       | _pandas.Timestamp_ | 截止日期 |
| total_staff    | _int_              | 职工总数 |

#### 范例 {#rqdata-API-get_staff_count-example}

- 获取 000001.XSHE 员工总数

```python
[In]
rqdatac.get_staff_count('000001.XSHE',start_date = 20240101,end_date = 20250801)
[Out]
                        end_date staff_count
order_book_id info_date
000001.XSHE 2024-03-15 2023-12-31 43119
            2024-08-16 2024-06-30 40830
            2025-03-15 2024-12-31 41011


```

### get_leader_shares_change - 获取高管持股变动数据 {#rqdata-API-get_leader_shares_change}

```python
rqdatac.get_leader_shares_change(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取高管持股变动数据，包括变动日期、姓名、职务、变动股数、变动后持股数、变动比例、变动价格和变动原因。

#### 参数 {#rqdata-API-get_leader_shares_change-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，根据变动日期查询                                       |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，根据变动日期查询                                       |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_leader_shares_change-return}

_pandas DataFrame_

| 字段           | 类型               | 说明             |
| -------------- | ------------------ | ---------------- |
| order_book_id  | _str_              | 合约代码         |
| change_date    | _pandas.Timestamp_ | 变动日期         |
| leader_name    | _str_              | 姓名             |
| position       | _str_              | 职务             |
| shares_change  | _float_            | 变动数(股)       |
| current_shares | _float_            | 变动后持股数(股) |
| ratio_change   | _float_            | 变动比例(%)      |
| price_change   | _float_            | 变动价格         |
| change_reason  | _str_              | 变动原因         |

#### 范例 {#rqdata-API-get_leader_shares_change-example}

- 获取单只股票指定时间内的持股变动

```python
[In]
rqdatac.get_leader_shares_change('002559.XSHE',start_date= 20250723 ,end_date=20250729 , market='cn')
[Out]

                         leader_name position shares_change current_shares ratio_change price_change change_reason rice_create_tm
order_book_id change_date
002559.XSHE 2025-07-25 潘恩海 董事、高管 -701700.0 4349800.0 0.12764 9.86 竞价交易 2025-08-11 14:22:46
            2025-07-25 朱鹏程 董事、高管 -200000.0 4771000.0 0.03638 9.85 竞价交易 2025-08-11 14:22:46
            2025-07-28 朱鹏程 董事、高管 -100000.0 4671000.0 0.01819 9.91 竞价交易 2025-08-11 14:22:46
            2025-07-29 朱鹏程 董事、高管 -170000.0 4501000.0 0.03092 9.89 竞价交易 2025-08-11 14:22:46


```

### get_forecast_report_date - 获取定期报告预约披露日 {#rqdata-API-get_forecast_report_date}

```python
rqdatac.get_forecast_report_date(order_book_ids , start_quarter , end_quarter, market='cn')
```

获取定期报告预约披露日数据，包括首次预约日、首次变更日、二次变更日、三次变更日和实际披露日。

#### 参数 {#rqdata-API-get_forecast_report_date-params}

| 参数           | 类型          | 说明                                                             |
| -------------- | ------------- | ---------------------------------------------------------------- |
| order_book_ids | _str or list_ | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_quarter  | _str_         | **必填参数**，开始报告期                                         |
| end_quarter    | _str_         | **必填参数**，结束报告期                                         |
| market         | _str_         | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_forecast_report_date-return}

_pandas DataFrame_

| 字段                | 类型               | 说明       |
| ------------------- | ------------------ | ---------- |
| order_book_ids      | _str_              | 合约代码   |
| quarter             | _str_              | 报告期     |
| info_date           | _pandas.Timestamp_ | 公告日期   |
| first_forecase_date | _pandas.Timestamp_ | 首次预约日 |
| first_change_date   | _pandas.Timestamp_ | 首次变更日 |
| second_change_date  | _pandas.Timestamp_ | 二次变更日 |
| third_change_date   | _pandas.Timestamp_ | 三次变更日 |
| auctual_info_date   | _pandas.Timestamp_ | 实际披露日 |

#### 范例 {#rqdata-API-get_forecast_report_date-example}

- 获取 000001.XSHE 指定报告期对应的预约披露日

```python
[In]
rqdatac.get_forecast_report_date(order_book_ids='000001.XSHE' , start_quarter='2024q1',end_quarter='2025q1', market='cn')
[Out]

                    info_date first_forecast_date first_change_date second_change_date third_change_date actual_info_date rice_create_tm
order_book_id quarter
000001.XSHE 2024q1 2024-03-31 2024-04-20 NaT None None 2024-04-20 2025-08-11 14:54:56
            2024q2 2024-06-30 2024-08-16 NaT None None 2024-08-16 2025-08-11 14:57:35
            2024q3 2024-09-30 2024-10-26 2024-10-19 None None 2024-10-19 2025-08-11 15:01:09
            2024q4 2024-12-31 2025-03-15 NaT None None 2025-03-15 2025-08-11 15:00:14
            2025q1 2025-03-31 2025-04-19 NaT None None 2025-04-19 2025-08-11 14:59:27

```

### get_investor_qa - 获取投资者问答数据 {#rqdata-API-get_investor_qa}

```python
rqdatac.get_investor_qa(order_book_ids, start_date, end_date, market='cn')
```

获取来自深交所互动易、上证e互动和全景网的投资者问答数据

#### 参数 {#rqdata-API-get_investor_qa-params}

| 参数           | 类型          | 说明                                                             |
| -------------- | ------------- | ---------------------------------------------------------------- |
| order_book_ids | _str or list_ | **必填参数**，合约代码，可传入 order_book_id, order_book_id list |
| start_date  | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | 开始日期，默认为三月前当日                                         |
| end_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | 结束日期，默认为查询当日                                         |
| market         | _str_         | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-get_investor_qa-return}

_pandas DataFrame_
返回结果以 (order_book_id, date) 作为索引

| 字段                | 类型               | 说明       |
| ------------------- | ------------------ | ---------- |
| order_book_ids      | _str_              | 合约代码   |
| info_source             | _str_              | 提问来源     |
| questioner | _str_ | 提问者 |
| date   | _pandas.Timestamp_ | 提问发布时间 |
| question_text  | _str_ | 提问内容 |
| reply_text   | _str_ | 回复内容 |
| reply_time   | _pandas.Timestamp_ | 回复时间 |

#### 范例 {#rqdata-API-get_investor_qa-example}

- 获取 000001.XSHE 指定日期期间的投资者问答数据

```python
[In]
rqdatac.get_investor_qa(order_book_ids="000001.XSHE", start_date="2024-01-01", end_date="2024-01-10")
[Out]

                    info_source	question_text	questioner	reply_text	reply_time	rice_create_tm
order_book_id date
000001.XSHE 2024-01-02	深交所互动易	平安银行的优势在哪里?请用线性分析回答	cninfo1198038	您好。本行的核心竞争力包括：党建引领保驾护航、发展战略科学清晰、综合金融优势突出、科技赋能模...	2024-01-09	2026-06-11 00:32:03
            2024-01-03	深交所互动易	刚刚通过最新的资本规划中，核心一级资本充足率不低于8.8%，是不是超过8.8%的部分，都可以分红？	cninfo662719	您好。本行于2023年12月举行的第三次临时股东大会通过了《关于资本管理规划（2024-20...	2024-01-09	2026-06-11 00:32:03
            2024-01-04	深交所互动易	请问公司在新规下，是否会响应新规将分红提高到不低于30%？	cninfo936260	您好。本行于2023年12月举行的第三次临时股东大会通过了《关于资本管理规划（2024-20...	2024-01-09	2026-06-11 00:32:03
            2024-01-04	深交所互动易	公司业绩如何	irm113820179	您好。本行2023年年度报告预计于2024年3月发布，届时请关注相关公告。感谢您的关注。	2024-01-09	2026-06-11 00:32:03
            2024-01-10	深交所互动易	请问2023年报什么时候发布	irm114385375	您好。本行2023年年度报告预计于2024年3月发布，届时请关注相关公告。感谢您的关注。	2024-01-11	2026-06-11 00:32:04

```