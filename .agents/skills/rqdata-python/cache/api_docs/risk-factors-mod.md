## 米筐风险模型 {#rqdata-API-risk-model-spec}

#### 标准风险模型

| 模型名称  | 股票池    | 行业因子          | 风险预测期限 | 模型特色                                                                                        |
|-----|-----|-----|-----|-----|
| v1       | 沪深 A 股 | 中信一级/申万一级 | 日/月/季     | 稳定经典模型，长期被市场使用并不断得到验证                                                      |
| v2       | 沪深 A 股 | 中信一级/申万一级 | 日/月/季     | 长期模型，相较于 v1 新定义 6 个长期风格因子，包含更多的基本面数据，在 R2 以及 Bias 上面表现优秀 |
| v2trd     | 沪深 A 股 | 中信一级/申万一级 | 日/月/季     | 交易模型，相较于 v2 增加 4 个交易类短期因子，在日度交易上有更好的表现                           |

#### 定制风险模型

| 模型名称      | 股票池   | 行业因子          | 风险预测期限 | 模型特色                                                                                               |
|-----|-----|-----|-----|-----|
| v2_bjse      | 中证全 A | 中信一级/申万一级 | 日/月/季     | 在长期模型 v2 中引入了北交所股票，扩大了投资范围                                                       |
| v2trd_bjse   | 中证全 A | 中信一级/申万一级 | 日/月/季     | 在 v2trd 交易模型中引入了北交所股票，扩大了投资范围                                                    |
| HKv1（公测版）  | 港股通 | 申万一级/中证一级 | 日/月/季     |  交易模型，相较于长期模型增加3个交易类短期因子，聚焦港股通股票                                                  |
| AHv1（公测版）  | 港股通 + 沪深A股 | 申万一级 | 日/月/季     |  交易模型，相较于长期模型增加3个交易类短期因子，移除了原国家因子comovement，新增CN（中国内地）、HK（中国香港）两个地区因子，明确两地市场的风险归属与联动逻辑。                                                  |


::: tip 定制化模型说明：

定制化风险模型需安装 rqdatac_risk_model 包，安装，调用方法以及模型详情请联系米筐工作人员获取
定制风险模型目前支持的 API 有：

- 因子暴露度：[get_factor_exposure](./risk-factors-mod.md#rqdata-API-get_factor_exposure)
- 因子收益率：[get_factor_return](./risk-factors-mod.md#rqdata-API-get_factor_return)(注：定制模型该 API 不支持可选 univers 参数，默认返回股票池的因子收益率)
- 特异收益率：[get_specific_return](./risk-factors-mod.md#rqdata-API-get_specific_return)
- 特异风险：[get_specific_risk](./risk-factors-mod.md#rqdata-API-get_specific_risk)
- 因子协方差：[get_factor_covariance](./risk-factors-mod.md#rqdata-API-get_factor_covariance)

:::

**如需更详细的米筐多因子风险模型白皮书，请联系我们的销售或者致电公司官方电话**

## 数据说明 {#rqdata-API-risk-model-spec-data}

### 因子结构 {#rqdata-API-risk-model-structure}

#### v1风格因子结构{#rqdata-API-risk-model-structure-v1}

| 风格因子           | 细分因子 | 说明                                                      |
|-----|-----|-----|
| Liquidity          | STOM     | Monthly share turnover 月换手率                           |
|                    | STOQ     | Quarterly share turnover 季换手率                         |
|                    | STOA     | Annual share turnover 年换手率                            |
| Leverage           | MLEV     | Market Leverage 市场杠杆                                  |
|                    | BLEV     | Book Leverage 账面杠杆                                    |
|                    | DTOA     | Debt to asset ratio 资产负债比                            |
| BTOP               | BTOP     | book to price 账面市值比                                  |
| Earnings Yield     | ETOP     | Trailing Earnings-to-Price ratio EP 比                    |
|                    | EPIBS    | Analyst predicted earnings to price 分析师预测 EP 比      |
|                    | CETOP    | cash earnings to price 现金盈利价格比                     |
| Growth             | EGRLF    | Predicted growth 3 year 分析师预测长期盈利增长率          |
|                    | EGRSF    | Predicted growth 1 year 分析师预测短期盈利增长率          |
|                    | EGRO     | Historical earnings per share growth rate 每股收益增长率  |
|                    | SGRO     | Historical sales per share growth rate 每股营业收入增长率 |
| Momentum           | RSTR     | Relative strength 相对于市场的强度                        |
| None_linear_size   | MIDCAP   | None_linear_size 非线性市值在新模型中改为中市值           |
| Size               | LSIZE    | size 规模                                                 |
| Beta               | BETA     | beta 贝塔                                                 |
| Resival Volatility | HSIGMA   | Hist sigma 历史 sigma                                     |
|                    | DASTD    | daily std dec 日标准差                                    |
|                    | CMRA     | Cumulative range 累计收益范围                             |

#### v2 风格因子结构{#rqdata-API-risk-model-structure-v2}

| 风格因子           | 细分因子 | 说明                                                           |
|-----|-----|-----|
| Liquidity          | STOM     | Monthly share turnover 月换手率                                |
|                    | STOQ     | Quarterly share turnover 季换手率                              |
|                    | STOA     | Annual share turnover 年换手率                                 |
|                    | ATVR     | Annualized traded value ratio 年化交易量比率                   |
| Leverage           | MLEV     | Market Leverage 市场杠杆                                       |
|                    | BLEV     | Book Leverage 账面杠杆                                         |
|                    | DTOA     | Debt to asset ratio 资产负债比                                 |
| Earning Variablity | VSAL     | Variation in Sales 营业收入波动率                              |
|                    | VERN     | Variation in Earings 盈利波动率                                |
|                    | VFLO     | Variation in Cash Flows 现金流波动率                           |
|                    | SPIBS    | Variation in FW EPS 分析师预测盈市率标准差                     |
| Earnings Quality   | ACBS     | Accruals Balancesheet version 资产负债表应计项目               |
|                    | ACCF     | Accruals Cashflow version 现金流量表应计项目                   |
| Profitability      | ATO      | Asset turnover 资产周转率                                      |
|                    | GP       | Gross profitability 资产毛利率                                 |
|                    | GM       | Gross Margin 销售毛利率                                        |
|                    | ROA      | Return on asset 总资产收益率                                   |
| Investment Quality | AGRO     | asset growth 资产增长率                                        |
|                    | IGRO     | issuance growth 股票发行量增长率                               |
|                    | CXGRO    | capital expenditure growth 资本支出增长率                      |
| BTOP               | BTOP     | book to price 账面市值比                                       |
| Earnings Yield     | ETOP     | Trailing Earnings-to-Price ratio EP 比                         |
|                    | EPIBS    | Analyst predicted earnings to price 分析师预测 EP 比           |
|                    | CETOP    | cash earnings to price 现金盈利价格比                          |
|                    | ENMU     | Enterprise multiple（Ebitda to Ev）企业价值倍数的倒数          |
| Long Term reversal | LTRSTR   | Longterm relative strength 长期相对强度                        |
|                    | LTHALPHA | Longterm historical alpha 长期历史 Alpha                       |
| Growth             | EGRLF    | Predicted growth 3 year 分析师预测长期盈利增长率               |
|                    | EGRO     | Historical earnings per share growth rate 每股收益增长率       |
|                    | SGRO     | Historical sales per share growth rate 每股营业收入增长率      |
| Momentum           | RSTR     | Relative strength 相对于市场的强度                             |
|                    | HALPHA   | Historical alpha 历史 Alpha                                    |
| Mid cap            | MIDCAP   | mid cap 中市值                                                 |
| Size               | LSIZE    | size 规模                                                      |
| Beta               | BETA     | beta 贝塔                                                      |
| Resival Volatility | HSIGMA   | Hist sigma 历史 sigma                                          |
|                    | DASTD    | daily std dec 日标准差                                         |
|                    | CMRA     | Cumulative range 累计收益范围                                  |
| Dividend Yield     | DTOP     | Dividend-to-price ratio 股息率                                 |
|                    | DPIBS    | Analyst predicted dividend to price ratio 分析师预测分红价格比 |

#### v2trd 风格因子结构{#rqdata-API-risk-model-structure-v2trd}

| 风格因子            | 细分因子 | 说明                                                                   |
|-----|-----|-----|
| Liquidity           | STOM     | Monthly share turnover 月换手率                                        |
|                     | STOQ     | Quarterly share turnover 季换手率                                      |
|                     | STOA     | Annual share turnover 年换手率                                         |
|                     | ATVR     | Annualized traded value ratio 年化交易量比率                           |
| Leverage            | MLEV     | Market Leverage 市场杠杆                                               |
|                     | BLEV     | Book Leverage 账面杠杆                                                 |
|                     | DTOA     | Debt to asset ratio 资产负债比                                         |
| Earning Variablity  | VSAL     | Variation in Sales 营业收入波动率                                      |
|                     | VERN     | Variation in Earings 盈利波动率                                        |
|                     | VFLO     | Variation in Cash Flows 现金流波动率                                   |
|                     | SPIBS    | Variation in FW EPS 分析师预测盈市率标准差                             |
| Earnings Quality    | ACBS     | Accruals Balancesheet version 资产负债表应计项目                       |
|                     | ACCF     | Accruals Cashflow version 现金流量表应计项目                           |
| Profitability       | ATO      | Asset turnover 资产周转率                                              |
|                     | GP       | Gross profitability 资产毛利率                                         |
|                     | GM       | Gross Margin 销售毛利率                                                |
|                     | ROA      | Return on asset 总资产收益率                                           |
| Investment Quality  | AGRO     | asset growth 资产增长率                                                |
|                     | IGRO     | issuance growth 股票发行量增长率                                       |
|                     | CXGRO    | capital expenditure growth 资本支出增长率                              |
| BTOP                | BTOP     | book to price 账面市值比                                               |
| Earnings Yield      | ETOP     | Trailing Earnings-to-Price ratio EP 比                                 |
|                     | EPIBS    | Analyst predicted earnings to price 分析师预测 EP 比                   |
|                     | CETOP    | cash earnings to price 现金盈利价格比                                  |
|                     | ENMU     | Enterprise multiple（Ebitda to Ev）企业价值倍数的倒数                  |
| Long Term reversal  | LTRSTR   | Longterm relative strength 长期相对强度                                |
|                     | LTHALPHA | Longterm historical alpha 长期历史 Alpha                               |
| Growth              | EGRLF    | Predicted growth 3 year 分析师预测长期盈利增长率                       |
|                     | EGRO     | Historical earnings per share growth rate 每股收益增长率               |
|                     | SGRO     | Historical sales per share growth rate 每股营业收入增长率              |
| Momentum            | RSTR     | Relative strength 相对于市场的强度                                     |
|                     | HALPHA   | Historical alpha 历史 Alpha                                            |
| Mid cap             | MIDCAP   | mid cap 中市值                                                         |
| Size                | LSIZE    | size 规模                                                              |
| Beta                | BETA     | beta 贝塔                                                              |
| Resival Volatility  | HSIGMA   | Hist sigma 历史 sigma                                                  |
|                     | DASTD    | daily std dec 日标准差                                                 |
|                     | CMRA     | Cumulative range 累计收益范围                                          |
| Dividend Yield      | DTOP     | Dividend-to-price ratio 股息率                                         |
|                     | DPIBS    | Analyst predicted dividend to price ratio 分析师预测分红价格比         |
| Sentiment           | RREVR    | Ratings revision Ratio 历史评级修正比                                  |
|                     | CANAPEP  | Change in Analyst Predicted earnings to price 分析预期收益价格比的变化 |
|                     | CANAPEPS | Change in Analyst Predicted Earnings per Share 分析预期每股收益的变化  |
| Short term reversal | STREVRSL | Short term reversal 短期反转                                           |
| Seasonality         | SEASON   | Seasonality 日历效应                                                   |
| Industry momentum   | INDMOM   | Industry momentum 行业动量                                             |

#### HKv1 风格因子结构{#rqdata-API-risk-model-structure-HKv1}

| 风格因子            | 细分因子 | 说明                                                                   |
|-----|-----|-----|
| Liquidity           | STOM     | Monthly share turnover 月换手率                                        |
|                     | STOQ     | Quarterly share turnover 季换手率                                      |
|                     | STOA     | Annual share turnover 年换手率                                         |
|                     | ATVR     | Annualized traded value ratio 年化交易量比率                           |
| Leverage            | MLEV     | Market Leverage 市场杠杆                                               |
|                     | BLEV     | Book Leverage 账面杠杆                                                 |
|                     | DTOA     | Debt to asset ratio 资产负债比                                         |
| Earning Variablity  | VSAL     | Variation in Sales 营业收入波动率                                      |
|                     | VERN     | Variation in Earings 盈利波动率                                        |
|                     | VFLO     | Variation in Cash Flows 现金流波动率                                   |
|                     | SPIBS    | Variation in FW EPS 分析师预测盈市率标准差                             |
| Earnings Quality    | ACBS     | Accruals Balancesheet version 资产负债表应计项目                       |
|                     | ACCF     | Accruals Cashflow version 现金流量表应计项目                           |
| Profitability       | ATO      | Asset turnover 资产周转率                                              |
|                     | GP       | Gross profitability 资产毛利率                                         |
|                     | GM       | Gross Margin 销售毛利率                                                |
|                     | ROA      | Return on asset 总资产收益率                                           |
| Investment Quality  | AGRO     | asset growth 资产增长率                                                |
|                     | IGRO     | issuance growth 股票发行量增长率                                       |
|                     | CXGRO    | capital expenditure growth 资本支出增长率                              |
| BTOP                | BTOP     | book to price 账面市值比                                               |
| Earnings Yield      | ETOP     | Trailing Earnings-to-Price ratio EP 比                                 |
|                     | EPIBS    | Analyst predicted earnings to price 分析师预测 EP 比                   |
|                     | CETOP    | cash earnings to price 现金盈利价格比                                  |
|                     | ENMU     | Enterprise multiple（Ebitda to Ev）企业价值倍数的倒数                  |
| Long Term reversal  | LTRSTR   | Longterm relative strength 长期相对强度                                |
|                     | LTHALPHA | Longterm historical alpha 长期历史 Alpha                               |
| Growth              | EGRLF    | Predicted growth 3 year 分析师预测长期盈利增长率                       |
|                     | EGRO     | Historical earnings per share growth rate 每股收益增长率               |
|                     | SGRO     | Historical sales per share growth rate 每股营业收入增长率              |
| Momentum            | RSTR     | Relative strength 相对于市场的强度                                     |
|                     | HALPHA   | Historical alpha 历史 Alpha                                            |
| Mid cap             | MIDCAP   | mid cap 中市值                                                         |
| Size                | LSIZE    | size 规模                                                              |
| Beta                | BETA     | beta 贝塔                                                              |
| Resival Volatility  | HSIGMA   | Hist sigma 历史 sigma                                                  |
|                     | DASTD    | daily std dec 日标准差                                                 |
|                     | CMRA     | Cumulative range 累计收益范围                                          |
| Dividend Yield      | DTOP     | Dividend-to-price ratio 股息率                                         |
|                     | DPIBS    | Analyst predicted dividend to price ratio 分析师预测分红价格比         |
| Short term reversal | STREVRSL | Short term reversal 短期反转                                           |
| Seasonality         | SEASON   | Seasonality 日历效应                                                   |
| Industry momentum   | INDMOM   | Industry momentum 行业动量                                             |

#### AHv1 风格因子结构{#rqdata-API-risk-model-structure-AHv1}

| 风格因子            | 细分因子 | 说明                                                                   |
|-----|-----|-----|
| Liquidity           | STOM     | Monthly share turnover 月换手率                                        |
|                     | STOQ     | Quarterly share turnover 季换手率                                      |
|                     | STOA     | Annual share turnover 年换手率                                         |
|                     | ATVR     | Annualized traded value ratio 年化交易量比率                           |
| Leverage            | MLEV     | Market Leverage 市场杠杆                                               |
|                     | BLEV     | Book Leverage 账面杠杆                                                 |
|                     | DTOA     | Debt to asset ratio 资产负债比                                         |
| Earning Variablity  | VSAL     | Variation in Sales 营业收入波动率                                      |
|                     | VERN     | Variation in Earings 盈利波动率                                        |
|                     | VFLO     | Variation in Cash Flows 现金流波动率                                   |
|                     | SPIBS    | Variation in FW EPS 分析师预测盈市率标准差                             |
| Earnings Quality    | ACBS     | Accruals Balancesheet version 资产负债表应计项目                       |
|                     | ACCF     | Accruals Cashflow version 现金流量表应计项目                           |
| Profitability       | ATO      | Asset turnover 资产周转率                                              |
|                     | GP       | Gross profitability 资产毛利率                                         |
|                     | GM       | Gross Margin 销售毛利率                                                |
|                     | ROA      | Return on asset 总资产收益率                                           |
| Investment Quality  | AGRO     | asset growth 资产增长率                                                |
|                     | IGRO     | issuance growth 股票发行量增长率                                       |
|                     | CXGRO    | capital expenditure growth 资本支出增长率                              |
| BTOP                | BTOP     | book to price 账面市值比                                               |
| Earnings Yield      | ETOP     | Trailing Earnings-to-Price ratio EP 比                                 |
|                     | EPIBS    | Analyst predicted earnings to price 分析师预测 EP 比                   |
|                     | CETOP    | cash earnings to price 现金盈利价格比                                  |
|                     | ENMU     | Enterprise multiple（Ebitda to Ev）企业价值倍数的倒数                  |
| Long Term reversal  | LTRSTR   | Longterm relative strength 长期相对强度                                |
|                     | LTHALPHA | Longterm historical alpha 长期历史 Alpha                               |
| Growth              | EGRLF    | Predicted growth 3 year 分析师预测长期盈利增长率                       |
|                     | EGRO     | Historical earnings per share growth rate 每股收益增长率               |
|                     | SGRO     | Historical sales per share growth rate 每股营业收入增长率              |
| Momentum            | RSTR     | Relative strength 相对于市场的强度                                     |
|                     | HALPHA   | Historical alpha 历史 Alpha                                            |
| Mid cap             | MIDCAP   | mid cap 中市值                                                         |
| Size                | LSIZE    | size 规模                                                              |
| Beta                | BETA     | beta 贝塔                                                              |
| Resival Volatility  | HSIGMA   | Hist sigma 历史 sigma                                                  |
|                     | DASTD    | daily std dec 日标准差                                                 |
|                     | CMRA     | Cumulative range 累计收益范围                                          |
| Dividend Yield      | DTOP     | Dividend-to-price ratio 股息率                                         |
|                     | DPIBS    | Analyst predicted dividend to price ratio 分析师预测分红价格比         |
| Short term reversal | STREVRSL | Short term reversal 短期反转                                           |
| Seasonality         | SEASON   | Seasonality 日历效应                                                   |
| Industry momentum   | INDMOM   | Industry momentum 行业动量                                             |

#### 行业因子与市场联动因子

行业因子采用**申万一级 2021**或**中信一级 2019**行业分类，用户可根据实际投资研究需求选择相应的行业分类体系。

| 市场联动因子 | 解释                                                                                                                                                                                                                                                                                                                     |
|----------|-----------|
| comovement| **AHv1模型不适用** <br>反映市场整体涨落对个股或投资组合的影响。个股对市场联动因子的暴露度均为 1，因此对于任意两个满仓的股票组合，其获得的市场收益及承担的市场整体波动风险相同。而对于“股票+现金”的组合，随着组合中股票仓位比例的增加，市场联动因子对组合收益影响越大； 例如：组合的股票平均仓位是 70%，那么该组合对市场联动因子的暴露度为 0.7。 |
| cn/hk  | **仅适用于AHv1模型** <br>AHv1模型移除了原市场联动因子comovement，新增cn（中国内地）、hk（中国香港）两个地区因子用于精准拆分跨市场系统性风险，明确两地市场的风险归属与联动逻辑。地区因子暴露规则严格遵循以下设定： <br> - 仅有A股：CN因子暴露为1，HK因子暴露为0；<br> - 仅有港股：CN因子暴露为0，HK因子暴露为1；<br>- AH两地上市股票：按两地股本比例，在CN与HK两个地区因子上分配暴露度，确保跨市场风险暴露的精准计量。 |

### 数据类型 {#rqdata-API-risk-model-data-type}

| 因子数据           | 解释                                                                                                                                                                                                                             |
|-----|-----|
| 风格因子暴露度     | 个股对于特定风格因子的风险暴露。 暴露度绝对值越大,则投资组合表现对因子表现变化越敏感。 可用于投资组合风格评估、风险敞口管理等。部分风格因子由多个细分风格因子组合而成。                                                          |
| 细分风格因子暴露度 | 个股对细分风格因子的风险暴露。细分风格因子表示某一类风格中的细分风险维度，用户可根据实际投资研究需求， 使用细分风格因子代替风格因子。**仅限于标准模型**                                                                          |
| 个股对指数贝塔     | 个股对指数（上证 50、沪深 300、中证 500 等）的原始贝塔值（未进行标准化， 因此区别于贝塔因子） ， 可用于指数跟踪或贝塔中性处理。 **仅限于标准模型**                                                                               |
| 因子收益率         | 因子在给定股票池产生的超额收益。 目前提供全市场、沪深 300、中证 500、 中证 800 四个股票池的因子收益。 用户可根据实际投资研究中所使用的股票池，选择相应的因子收益进行风格追踪和构建指数增强策略。**股票池可选参数仅限于标准模型** |
| 特异收益率         | 个股收益中无法被因子解释的部分。 例如上市公司出现高管人员变动， 可能引起股价剧烈波动，产生较大的特异收益。 此时上市公司股价主要由消息面驱动，而与其所处行业、基本面、 及市场行情相关性较低。                                     |
| 因子协方差         | 投资组合风险中能被因子解释的系统性风险部分。 目前提供日度、月度、季度三套不同预测期限的风险模型，适用于不同调仓频率的交易策略。                                                                                                  |
| 特异风险           | 投资组合风险中不能被因子解释的，与个股自身特殊因素相关的部分（见上述特异收益率解释） 。 目前提供日度、月度、季度三个不同预测期限的风险模型，适用于不同调仓频率的交易策略。                                                       |

## get_factor_exposure - 获取一组股票的因子暴露度 {#rqdata-API-get_factor_exposure}

```python
get_factor_exposure(order_book_ids, start_date=None, end_date=None, factors=None, industry_mapping='sws_2021', model='v1', market='cn')
```

获取一组股票的因子暴露度数据，支持按时间范围、行业分类和风险模型查询风格因子及行业因子暴露度。例如可获取 momentum、beta、book_to_price 等风格因子暴露度，也包括银行、计算机、环保等行业因子暴露度。

#### 参数 {#rqdata-API-get_factor_exposure-params}

| 参数             | 类型                  | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| order_book_ids   | _str or list of str_  | **必填参数**，证券代码（例如： '600705.XSHG'），可传入 order_book_id, order_book_id list                                                                                                                                          |
| start_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | 开始日期（例如： '2017-03-03'）                                                                                                                                                                                                   |
| end_date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | 结束日期（例如： '2017-03-20'），不传入 start_date ,end_date 则 默认返回最近三个月的数据                                                                                                                                          |
| factors          | _None or list of str_ | 风险因子。默认获取全部风格因子暴露度（ None）。                                                                                                                                                                                   |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。<br/>港股通风险模型除默认申万行业分类外可选'csi_2021'-中证行业分类<br/>A+H 跨市场模型仅支持默认行业分类：industry_mapping = 'sws_2021'                                                                                                                  |
| model            | _str_                 | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)）<br/>'HKv1' 米筐港股通风险模型（[HKv1](#rqdata-API-risk-model-structure-HKv1)） <br/>'AHv1' 米筐 A+H 跨市场风险模型（[AHv1](#rqdata-API-risk-model-structure-AHv1)）|
| market         | _str_                  | 默认是中国内地市场('cn'), 港股通风险模型 'HKv1' 需使用('hk') |

#### 返回 {#rqdata-API-get_factor_exposure-return}

_MultiIndex 的 pandas.DataFrame_

index 第一个 level 为 order_book_id，第二个 level 为 date， columns 为因子字段名称。

#### 范例 {#rqdata-API-get_factor_exposure-example}

- 获取单一股票的因子暴露度

```
In [24]: rqdatac.get_factor_exposure('600705.XSHG','20170302','20170307',factors=None,industry_mapping='sws_2021' )
Out[24]:
                          momentum      beta  book_to_price  earnings_yield  liquidity      size  residual_volatility  non_linear_size  comovement  leverage    growth  银行  计算机  环保  商贸零售  电力设备  建筑装饰  建筑材料  农林牧渔  电子  交通运输  汽车  纺织服饰  医药生物  房地产  通信  公用事业  综合  机械设备  石油石化  有色金属  传媒  家用电器  基础化工  非银金融  社会服务  轻工制造  国防军工  美容护理  煤炭  食品饮料  钢铁
date       order_book_id
2017-03-02 600705.XSHG   -0.765684 -0.085280       0.368789        0.285730  -0.145475  1.423206            -0.643894        -0.779187           1  1.519396 -1.712015   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
2017-03-03 600705.XSHG   -0.707014 -0.088001       0.373052        0.290378  -0.171835  1.428292            -0.801934        -0.773588           1  1.521861 -1.711590   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
2017-03-06 600705.XSHG   -0.733606 -0.142462       0.392585        0.310572  -0.199674  1.423293            -0.796411        -0.792342           1  1.523406 -1.711635   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
2017-03-07 600705.XSHG   -0.755761 -0.108790       0.403361        0.076728  -0.159671  1.450870            -0.727523        -0.743816           1  1.593371 -1.300758   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
```

- 获取多股票的因子暴露度

```
In [21]: rqdatac.get_factor_exposure(['600705.XSHG','601600.XSHG'],'20170302','20170307',factors=None,industry_mapping='sws_2021' )
Out[21]:
                          momentum      beta  book_to_price  earnings_yield  liquidity      size  residual_volatility  non_linear_size  comovement  leverage    growth  银行  计算机  环保  商贸零售  电力设备  建筑装饰  建筑材料  农林牧渔  电子  交通运输  汽车  纺织服饰  医药生物  房地产  通信  公用事业  综合  机械设备  石油石化  有色金属  传媒  家用电器  基础化工  非银金融  社会服务  轻工制造  国防军工  美容护理  煤炭  食品饮料  钢铁
date       order_book_id
2017-03-02 600705.XSHG   -0.765684 -0.085280       0.368789        0.285730  -0.145475  1.423206            -0.643894        -0.779187           1  1.519396 -1.712015   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
           601600.XSHG    0.632379 -0.577844       2.116718        0.256038   0.471672  1.394988             0.846457        -0.826099           1  1.431694  0.067756   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     1   0     0     0     0     0     0     0     0   0     0   0
2017-03-03 600705.XSHG   -0.707014 -0.088001       0.373052        0.290378  -0.171835  1.428292            -0.801934        -0.773588           1  1.521861 -1.711590   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
           601600.XSHG    0.515550 -0.589616       2.126162        0.289633   0.445027  1.378327             0.863395        -0.855620           1  1.433824  0.067364   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     1   0     0     0     0     0     0     0     0   0     0   0
2017-03-06 600705.XSHG   -0.733606 -0.142462       0.392585        0.310572  -0.199674  1.423293            -0.796411        -0.792342           1  1.523406 -1.711635   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
           601600.XSHG    0.360484 -0.741722       2.126348        0.324218   0.421461  1.352377             0.936466        -0.905581           1  1.435153  0.067866   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     1   0     0     0     0     0     0     0     0   0     0   0
2017-03-07 600705.XSHG   -0.755761 -0.108790       0.403361        0.076728  -0.159671  1.450870            -0.727523        -0.743816           1  1.593371 -1.300758   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     0   0     0     0     1     0     0     0     0   0     0   0
           601600.XSHG    0.388384 -0.764634       2.132366        0.344829   0.409443  1.334277             0.914831        -0.933042           1  1.437516  0.068503   0    0   0     0     0     0     0     0   0     0   0     0     0    0   0     0   0     0     0     1   0     0     0     0     0     0     0     0   0     0   0
```

## get_descriptor_exposure - 获取一组股票的细分风格因子暴露度 {#rqdata-API-get_descriptor_exposure}

```python
get_descriptor_exposure(order_book_ids, start_date, end_date, descriptors=None, model='v1', industry_mapping='sws_2021', market='cn')
```

获取一组股票的细分风格因子暴露度数据，支持按时间范围、行业分类和风险模型查询。例如可获取 earnings_growth、cash_earnings_to_price_ratio、sales_growth 等细分风格因子暴露度。

#### 参数 {#rqdata-API-get_descriptor_exposure-params}

| 参数           | 类型                  | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| order_book_ids | _str or list of str_  | **必填参数**，证券代码（例如： '600705.XSHG'），可传入 order_book_id, order_book_id list                                                                                                                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                     |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | **必填参数**，结束日期（例如： '2017-03-20'）                                                                                                                                                                                     |
| descriptors    | _None or list of str_ | 细分风格因子。默认获取全部细分风格因子的暴露度（ None）                                                                                                                                             |
| model          | _str_                 | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)） |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。                                                                                                                |
| market         | _str_                  | 默认是中国内地市场('cn') |


#### 返回 {#rqdata-API-get_descriptor_exposure-return}

_MultiIndex 的 pandas.DataFrame_

index 第一个 level 为 order_book_id，第二个 level 为 date， column 为细分风格因子字段名称。

#### 范例 {#rqdata-API-get_descriptor_exposure-example}

- 获取一只股票的全部细分因子暴露度

```
In [11]: get_descriptor_exposure('600705.XSHG','20170302','20170307',descriptors=None)
Out[11]:
                          book_leverage  cash_earnings_to_price_ratio  ...  three_months_share_turnover  twelve_months_share_turnover
order_book_id date                                                     ...
600705.XSHG   2017-03-02       1.716070                     -2.174376  ...                    -0.572241                      0.073076
              2017-03-03       1.718035                     -2.161017  ...                    -0.628732                      0.065085
              2017-03-06       1.719792                     -2.166595  ...                    -0.681997                      0.063982
              2017-03-07       1.716341                     -2.167661  ...                    -0.685791                      0.071536
```

- 获取一只股票一组细分风格因子暴露度

```
In [26]: get_descriptor_exposure('600705.XSHG','20170302','20170307',descriptors=['earnings_growth','cash_earnings_to_price_ratio','sales_growth'])
Out[26]:
                          cash_earnings_to_price_ratio  earnings_growth  sales_growth
order_book_id date
600705.XSHG   2017-03-02                     -2.174376        -0.412443     -0.434541
              2017-03-03                     -2.161017        -0.412443     -0.434541
              2017-03-06                     -2.166595        -0.412443     -0.434541
              2017-03-07                     -2.167661        -0.438942     -0.454265
```

## get_stock_beta - 获取个股相对于某个基准的贝塔 {#rqdata-API-get_stock_beta}

```python
get_stock_beta(order_book_ids, start_date, end_date, benchmark='000300.XSHG', model='v1', industry_mapping='sws_2021', market='cn')
```

获取个股相对于指定基准指数的贝塔数据，支持按时间范围、行业分类和风险模型查询。例如基准指数可选沪深 300、上证 50、中证 500，也支持中证 800 和中证全指。

#### 参数 {#rqdata-API-get_stock_beta-params}

| 参数           | 类型                 | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| order_book_ids | _str or list of str_ | **必填参数**，证券代码（例如： '600705.XSHG'），可传入 order_book_id, order_book_id list                                                                                                                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                     |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                | **必填参数**，结束日期（例如： '2017-03-20'）                                                                                                                                                                                     |
| benchmark      | _str_                | 基准指数。默认为沪深 300（ '000300.XSHG'），可选上证 50（'000016.XSHG'）、中证 500（ '000905.XSHG'）、中证 800（ '000906.XSHG'）以及中证全指（ '000985.XSHG'）                                                                    |
| model          | _str_                | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)）|
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。                                                          |
| market         | _str_                  | 默认是中国内地市场('cn')  |

#### 返回 {#rqdata-API-get_stock_beta-return}

_pandas.DataFrame_

index 为日期， column 为个股的 order_book_id

#### 范例 {#rqdata-API-get_stock_beta-example}

- 获取一只股票的基准贝塔值

```
In [12]: get_stock_beta('600705.XSHG','20170302','20170307' )
Out[12]:
order_book_id  600705.XSHG
date
2017-03-02        1.396796
2017-03-03        1.395106
2017-03-06        1.378063
2017-03-07        1.399051
```

## get_factor_return - 获取因子收益率 {#rqdata-API-get_factor_return}

```python
get_factor_return(start_date, end_date, factors=None, universe='whole_market', method='implicit', industry_mapping='sws_2021', model='v1', market='cn')
```

获取因子收益率数据，支持按时间范围、股票池、行业分类和风险模型查询。例如可获取全市场、沪深 300、中证 500 等股票池的因子收益率，也支持 implicit 和 explicit 两种计算方法。

#### 参数 {#rqdata-API-get_factor_return-params}

| 参数             | 类型                  | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| start_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                     |
| end_date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                 | **必填参数**，结束日期（例如： '2017-03-20'）                                                                                                                                                                                     |
| factors          | _None or list of str_ | 因子。默认获取全部因子的因子收益率(None)。                                                                                                                                                                                        |
| universe         | _str or list_         | 基准指数。默认为全市场('whole_market')， 可选沪深 300 ('000300.XSHG'),中证 500 ('000905.XSHG')、中证 800（'000906.XSHG'）                                                                                                         |
| method           | _str_                 | 计算方法 （ 1 ） 。默认为 'implicit'（隐式因子收益率） ，可选'explicit'（显式风格因子收益率）                               |
| model            | _str_                 | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)） <br/>'HKv1' 米筐港股通风险模型 ([HKv1](#rqdata-API-risk-model-structure-HKv1)）<br/>'AHv1' 米筐 A+H 跨市场风险模型（[AHv1](#rqdata-API-risk-model-structure-AHv1)） |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。<br/>港股通风险模型除默认申万行业分类外可选'csi_2021'-中证行业分类<br/>A+H 跨市场模型仅支持默认行业分类：industry_mapping = 'sws_2021'                                             |
| market         | _str_                  | 默认是中国内地市场('cn')，港股通风险模型'HKv1'需使用('hk')  |  

#### 返回 {#rqdata-API-get_factor_return-return}

_pandas.DataFrame_

index 为日期， column 为因子字段名称

#### 范例 {#rqdata-API-get_factor_return-example}

- 获取全部因子的因子收益率

```
In [14]: rqdatac.get_factor_return('20170302','20170307',factors=None,universe='whole_market',industry_mapping='sws_2021')
Out[14]:
factor          beta  book_to_price  comovement  earnings_yield    growth  leverage  liquidity  momentum  non_linear_size  residual_volatility      size      交通运输        传媒      公用事业      农林牧渔      医药生物      商贸零售  ...        汽车        煤炭        环保      电力设备        电子      石油石化      社会服务      纺织服饰        综合      美容护理       计算机      轻工制 造        通信        钢铁        银行      非银金融      食品饮料
date                                                                                                                                                                                                                  ...
2017-03-02 -0.001044      -0.003007   -0.005161        0.000895 -0.000558  0.000269   0.000050  0.000680        -0.000147            -0.003483  0.000171 -0.006161 -0.002081  0.000525 -0.004602 -0.002468 -0.003860  ...  0.000504  0.000077 -0.002917  0.004257  0.000370 -0.000766 -0.001737  0.002724  0.000486  0.004157 -0.002981 -0.000922  0.000394  0.005574  0.006018  0.001711  0.000042
2017-03-03  0.001259      -0.001100   -0.001086        0.001748  0.000521 -0.000775  -0.001693  0.000446         0.000820            -0.001096 -0.001652 -0.007279 -0.000296 -0.000124  0.000697  0.000994 -0.001389  ...  0.005918 -0.008764  0.002470  0.009808  0.011413 -0.006552  0.006445 -0.000879 -0.000159  0.000600  0.005042  0.002710  0.002237 -0.008201 -0.006301 -0.001433  0.001814
2017-03-06  0.002535      -0.001496    0.009265        0.000960  0.000021 -0.000851  -0.000870 -0.000549        -0.000989             0.000002 -0.001650 -0.000152 -0.001880 -0.000092 -0.004033 -0.002653 -0.003367  ... -0.001338  0.008903 -0.001816 -0.001218  0.006256 -0.000935 -0.001956 -0.003656 -0.004730  0.000664  0.003920  0.000532  0.005297  0.001956 -0.000836 -0.001430 -0.000331
2017-03-07 -0.000222      -0.001369    0.002965        0.000156 -0.000555 -0.001759  -0.001441 -0.000478        -0.000535            -0.000521 -0.001305 -0.000647 -0.001396  0.000425 -0.000495 -0.000400  0.001695  ... -0.001178 -0.007857 -0.001802 -0.002089 -0.000649 -0.001059 -0.002213 -0.003938 -0.000919  0.000182  0.004406  0.001884  0.001422 -0.005280  0.006863 -0.000516  0.009694

[4 rows x 42 columns]

```

## get_specific_return - 获取个股特异收益率 {#rqdata-API-get_specific_return}

```python
get_specific_return(order_book_ids, start_date, end_date, model = 'v1',industry_mapping='sws_2021')
```

获取个股特异收益率数据，支持按时间范围、行业分类和风险模型查询单只或多只股票。例如可查询 600705.XSHG 的特异收益率，也可获取 600705.XSHG、600100.XSHG 等股票在 `sws_2021` 或 `citics_2019` 分类下的数据。

#### 参数 {#rqdata-API-get_specific_return-params}

| 参数             | 类型          | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| order_book_ids   | _str or list_ | **必填参数**，证券代码（例如： '600705.XSHG'），可传入 order_book_id, order_book_id list                                                                                                                                          |
| start_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                     |
| end_date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | **必填参数**，结束日期（例如： '2017-03-20'）                                                                                                                                                                                     |
| model            | _str_         | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)） <br/>'HKv1' 米筐港股通风险模型（[HKv1](#rqdata-API-risk-model-structure-HKv1)）<br/>'AHv1' 米筐 A+H 跨市场风险模型（[AHv1](#rqdata-API-risk-model-structure-AHv1)） |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。<br/>港股通风险模型除默认申万行业分类外可选'csi_2021'-中证行业分类<br/>A+H 跨市场模型仅支持默认行业分类：industry_mapping = 'sws_2021'                                                                                                              |
| market         | _str_                  | 默认是中国内地市场('cn')，港股通风险模型'HKv1'需使用('hk')  |                                                                           

#### 返回 {#rqdata-API-get_specific_return-return}

_pandas.DataFrame_

index 为日期， column 为个股的 order_book_id

#### 范例 {#rqdata-API-get_specific_return-example}

- 获取一只股票的特异收益率

```
In [16]: get_specific_return('600705.XSHG','20170302','20170307' )
Out[16]:
order_book_id  600705.XSHG
date
2017-03-02       -0.012205
2017-03-03        0.004288
2017-03-06       -0.005601
2017-03-07        0.022702
```

- 获取一组股票的特异收益率

```
In [29]: get_specific_return(['600705.XSHG','600100.XSHG'],'20170302','20170307' )
Out[29]:
order_book_id  600100.XSHG  600705.XSHG
date
2017-03-02        0.000004    -0.012205
2017-03-03       -0.004658     0.004288
2017-03-06       -0.003140    -0.005601
2017-03-07        0.013050     0.022702
```

- 获取一个股票中信 2019 分类下的特异收益率

```
In [29]: rqdatac.get_specific_return('600705.XSHG','20170302','20170307',industry_mapping='citics_2019' )
Out[29]:
order_book_id  600705.XSHG
date
2017-03-02       -0.015470
2017-03-03        0.005021
2017-03-06       -0.003329
2017-03-07        0.022044
```

## get_factor_covariance - 获取因子协方差矩阵 {#rqdata-API-get_factor_covariance}

```python
get_factor_covariance(date, horizon= 'daily', model = 'v1',industry_mapping='sws_2021')
```

获取指定日期的因子协方差矩阵数据，支持不同预测期限、行业分类和风险模型。例如预测期限可选日度、月度、季度，也支持 `sws_2021` 和 `citics_2019` 行业分类下的因子协方差矩阵。

#### 参数 {#rqdata-API-get_factor_covariance-params}

| 参数             | 类型  | 说明                                                                                                                                                                                                                                   |
|-----|-----|-----|
| date             | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_   | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                          |
| horizon          | _str_   | 预测期 限。默 认为 日度 （ 'daily' ）， 可选月度（ 'monthly'）或季度（ 'quarterly'）                                                                                                                                                   |
| model            | _str_ | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)）<br/>'HKv1' 米筐港股通风险模型（[HKv1](#rqdata-API-risk-model-structure-HKv1)）<br/>'AHv1' 米筐 A+H 跨市场风险模型（[AHv1](#rqdata-API-risk-model-structure-AHv1)） |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。<br/>港股通风险模型除默认申万行业分类外可选'csi_2021'-中证行业分类<br/>A+H 跨市场模型仅支持默认行业分类：industry_mapping = 'sws_2021'                                                                                                             |
| market         | _str_                  | 默认是中国内地市场('cn')，港股通风险模型'HKv1'需使用('hk')  |                                        

#### 返回 {#rqdata-API-get_factor_covariance-return}

_pandas.DataFrame_

index 和 column 均为因子名称

#### 范例 {#rqdata-API-get_factor_covariance-example}

```
In [17]: get_factor_covariance('20170303',horizon='daily')
Out[17]:
                         beta  book_to_price  comovement  earnings_yield    growth  ...      采掘      钢铁       银行     非银金融      食品饮料
beta                 0.001163  -2.385022e-04    0.002044   -6.211431e-05 -0.000042  ... -0.000155 -0.000455 -0.000377  0.000040 -0.000311
book_to_price       -0.000239   2.517092e-03   -0.000964   -1.118821e-04  0.000054  ...  0.000697  0.001682  0.000427  0.000162  0.000362
comovement           0.002044  -9.643928e-04    0.016008   -1.260676e-04 -0.000253  ...  0.000226  0.000192 -0.004963  0.001152 -0.001320
earnings_yield      -0.000062  -1.118821e-04   -0.000126    5.460846e-04 -0.000049  ... -0.000208 -0.000219  0.000070  0.000150  0.000187
growth              -0.000042   5.362409e-05   -0.000253   -4.887124e-05  0.000171  ... -0.000020 -0.000155  0.000185 -0.000051  0.000077
leverage            -0.000050   2.557107e-04   -0.000145   -1.153423e-05 -0.000002  ...  0.000203  0.000691 -0.000176  0.000078  0.000115
liquidity            0.000118  -5.388243e-07    0.001384   -5.870778e-05  0.000011  ...  0.000140  0.000314 -0.000606 -0.000068  0.000047
momentum            -0.000260   1.096554e-04   -0.000522   -1.625567e-05  0.000022  ... -0.000072 -0.000302  0.000247 -0.000053  0.000041
non_linear_size      0.000087  -1.806789e-04    0.000144   -3.357935e-05 -0.000007  ... -0.000071  0.000102 -0.000159 -0.000084 -0.000039
residual_volatility  0.000632  -3.166259e-04    0.001609   -8.017871e-05 -0.000019  ... -0.000173 -0.000612 -0.000197 -0.000120 -0.000466
size                -0.000226   3.508242e-04   -0.001208    3.006616e-04  0.000034  ...  0.000252  0.000720  0.000300  0.000206  0.000330
交通运输                 0.000014   2.175025e-04    0.000782   -2.044910e-04  0.000015  ... -0.000289  0.001544 -0.002213 -0.001391  0.000661
休闲服务                -0.000056   7.833654e-05   -0.001222    5.397482e-05  0.000014  ... -0.000589  0.000032 -0.001537 -0.000974  0.001098
···
银行                  -0.000377   4.270598e-04   -0.004963    6.968579e-05  0.000185  ... -0.000726 -0.005122  0.010001  0.000824 -0.001567
非银金融                 0.000040   1.620042e-04    0.001152    1.504377e-04 -0.000051  ... -0.000602 -0.001897  0.000824  0.006821 -0.001082
食品饮料                -0.000311   3.616767e-04   -0.001320    1.873396e-04  0.000077  ... -0.000083  0.001159 -0.001567 -0.001082  0.005584
```

```
In [17]: rqdatac.get_factor_covariance('20170303',horizon='daily',industry_mapping='citics_2019')
Out[17]:
                         beta  book_to_price  comovement  earnings_yield        growth  leverage     liquidity      momentum  non_linear_size  residual_volatility  ...      纺织服装        综合      综合金融       计算机      轻工制造        通信        钢铁        银行     非银行金融      食品饮料
beta                 0.001399      -0.000007    0.004359        0.000088 -6.770298e-05 -0.000095 -6.687593e-05 -4.446151e-04     1.121304e-05             0.000915  ... -0.000035 -0.000162 -0.000015  0.000496  0.000119  0.000188 -0.000318 -0.000891  0.000075  0.000007
book_to_price       -0.000007       0.001188    0.000354        0.000074 -5.944671e-05  0.000229  7.424089e-05  3.840258e-05    -1.089268e-04            -0.000048  ... -0.000080  0.000009  0.000479 -0.000683 -0.000270 -0.000372  0.001352 -0.000476  0.000317  0.000462
comovement           0.004359       0.000354    0.016260        0.000564 -2.733087e-04 -0.000328 -1.883315e-04 -1.597542e-03    -1.618321e-05             0.003254  ... -0.000432 -0.001010 -0.000307  0.000750  0.000249  0.000031 -0.001076 -0.002098  0.000910  0.000374
earnings_yield       0.000088       0.000074    0.000564        0.000341 -1.657873e-05 -0.000039 -3.718981e-05 -2.519291e-05    -2.958569e-05             0.000008  ... -0.000067 -0.000126 -0.000046 -0.000028  0.000020 -0.000026 -0.000140 -0.000226  0.000198  0.000475
growth              -0.000068      -0.000059   -0.000273       -0.000017  1.651912e-04 -0.000053 -1.308102e-07  3.171995e-05     1.839054e-05            -0.000027  ... -0.000046 -0.000021 -0.000031  0.000156 -0.000065  0.000111 -0.000296  0.000303 -0.000100 -0.000135
leverage            -0.000095       0.000229   -0.000328       -0.000039 -5.293993e-05  0.000275  5.422277e-05  2.748743e-05    -2.591696e-05            -0.000135  ...  0.000103  0.000075  0.000117 -0.000439 -0.000009 -0.000245  0.000739 -0.000294  0.000129  0.000184
liquidity           -0.000067       0.000074   -0.000188       -0.000037 -1.308102e-07  0.000054  6.349408e-04 -4.340426e-05    -7.344311e-06            -0.000027  ... -0.000097 -0.000064 -0.000191 -0.000284 -0.000115 -0.000235  0.000048 -0.000024 -0.000099  0.000152
momentum            -0.000445       0.000038   -0.001598       -0.000025  3.171995e-05  0.000027 -4.340426e-05  4.285512e-04     4.915310e-07            -0.000385  ... -0.000101  0.000003 -0.000009 -0.000101 -0.000080 -0.000068 -0.000223  0.000514 -0.000009 -0.000104
non_linear_size      0.000011      -0.000109   -0.000016       -0.000030  1.839054e-05 -0.000026 -7.344311e-06  4.915310e-07     1.000601e-04             0.000031  ...  0.000037  0.000022 -0.000059  0.000138  0.000052  0.000045  0.000066 -0.000041 -0.000093 -0.000071
residual_volatility  0.000915      -0.000048    0.003254        0.000008 -2.668991e-05 -0.000135 -2.728752e-05 -3.853061e-04     3.093620e-05             0.001066  ... -0.000113 -0.000150  0.000166  0.000526  0.000054  0.000263 -0.000454 -0.000448 -0.000161 -0.000217
size                -0.000358       0.000295   -0.000832        0.000153 -1.484045e-05  0.000090  3.278297e-04  8.068121e-05    -5.206873e-05            -0.000388  ... -0.000076 -0.000223 -0.000136 -0.000574 -0.000193 -0.000463  0.000606 -0.000018  0.000377  0.000378
交通运输                -0.000102       0.000150   -0.000332       -0.000145 -1.001581e-04  0.000303  3.600846e-04 -1.730589e-04    -6.712213e-05            -0.000025  ...  0.000545  0.000771  0.000963 -0.000309  0.000773  0.000176  0.001407 -0.002519 -0.001657  0.000813
传媒                   0.000158      -0.000449   -0.000262       -0.000062  1.034563e-04 -0.000243 -2.328359e-04  3.048113e-05     1.974499e-05             0.000205  ...  0.000318  0.000759  0.000956  0.002107  0.000762  0.001588 -0.001282 -0.001594 -0.001332 -0.000295
农林牧渔                -0.000076       0.000258   -0.000249        0.000116 -1.219678e-04  0.000257  1.056987e-05 -9.805772e-05     1.223279e-05            -0.000130  ...  0.000612  0.000502  0.000347 -0.000671  0.000589 -0.000249  0.001948 -0.002567 -0.000891  0.001917
医药                   0.000372      -0.000185    0.000947        0.000234  8.351098e-06 -0.000152 -1.239801e-04 -1.238810e-04     1.905877e-05             0.000207  ...  0.000468  0.000296  0.000403  0.000851  0.000640  0.000573 -0.000599 -0.002098 -0.001150  0.001156
商贸零售                 0.000142      -0.000080    0.000310       -0.000004 -1.377363e-04  0.000045  1.288081e-04 -2.074744e-04     1.592768e-05             0.000146  ...  0.001178  0.001221  0.001280 -0.000059  0.001023  0.000149  0.000564 -0.003222 -0.000770  0.001014
国防军工                 0.000776       0.000140    0.001911       -0.000085 -1.402052e-05  0.000291  6.471573e-05 -3.466389e-04    -5.263616e-05             0.000593  ...  0.000030 -0.000172  0.000424  0.000298 -0.000199  0.001194  0.000685 -0.003790 -0.001595  0.000298
基础化工                 0.000216      -0.000329    0.000400       -0.000026 -8.059124e-05 -0.000083  1.655167e-05 -1.808071e-04     8.051281e-05             0.000195  ...  0.000746  0.000668  0.000151  0.000264  0.000666  0.000487  0.000896 -0.002623 -0.001467  0.000510
家电                   0.000075      -0.000127    0.000135        0.000208 -7.764720e-05 -0.000063  9.480138e-05 -2.370653e-04    -1.065073e-05            -0.000067  ...  0.000686  0.000414  0.000285  0.000088  0.000720  0.000468  0.000529 -0.002337 -0.000867  0.001731
建材                   0.000034       0.000537   -0.000116       -0.000109 -3.763579e-04  0.000442  3.322789e-04 -1.453769e-04     8.369679e-05            -0.000035  ...  0.001229  0.001458  0.000911 -0.001123  0.001111 -0.000456  0.007036 -0.005746 -0.002363  0.001917
建筑                  -0.000136       0.000651   -0.000116        0.000018 -1.237513e-04  0.000283  4.542388e-05  3.644480e-05    -9.319595e-06            -0.000142  ...  0.000215  0.000434  0.000528 -0.000403  0.000449  0.000140  0.001039 -0.002048 -0.000734  0.000155
房地产                 -0.000056       0.000024   -0.000311       -0.000004 -2.817610e-05  0.000035  9.880655e-05 -6.599190e-05    -1.578748e-05            -0.000114  ...  0.000375  0.000825  0.000483 -0.000321  0.000235 -0.000123 -0.000119 -0.000917 -0.000233  0.000211
有色金属                -0.000212       0.000909   -0.000932       -0.000127 -2.694873e-04  0.000558 -7.352625e-05 -6.875829e-09    -4.801330e-05            -0.000262  ...  0.000547  0.000297 -0.000338 -0.002009  0.000105 -0.001164  0.008366 -0.003554 -0.001110  0.000531
机械                   0.000194      -0.000093    0.000479        0.000009 -3.434340e-05 -0.000013 -1.440233e-05 -5.398043e-05     4.997692e-05             0.000152  ...  0.000234  0.000164  0.000145  0.000310  0.000310  0.000355  0.000218 -0.001445 -0.000792  0.000055
汽车                   0.000170      -0.000315    0.000091       -0.000006  1.631817e-05 -0.000052  1.313062e-04 -1.220259e-04     6.749136e-05             0.000096  ...  0.000630  0.000464  0.000372  0.000182  0.000592  0.000365  0.000525 -0.002128 -0.000983  0.000562
消费者服务                0.000033      -0.000123   -0.000566        0.000149  2.958023e-05  0.000047 -8.186208e-05  4.652137e-05     2.568024e-05            -0.000114  ...  0.000511  0.000650  0.000981  0.000680  0.000591  0.000420  0.000273 -0.002048 -0.000781  0.000910
煤炭                  -0.000285       0.000848   -0.000266        0.000053 -6.842190e-05  0.000318  2.361473e-04 -2.647335e-04    -1.578106e-04            -0.000505  ...  0.000468 -0.000059 -0.000921 -0.002150 -0.000406 -0.001354  0.008761 -0.001411 -0.000050  0.000557
电力及公用事业              0.000137       0.000090    0.000265       -0.000089 -4.733007e-05  0.000038  1.291258e-04 -1.126767e-04     3.723079e-06             0.000094  ...  0.000308  0.000460  0.000164 -0.000190  0.000417  0.000014  0.000924 -0.001747 -0.000978  0.000068
电力设备及新能源             0.000344      -0.000208    0.000780       -0.000020 -1.284099e-05 -0.000068  7.599085e-05 -8.151875e-05     7.738806e-05             0.000322  ...  0.000242  0.000256 -0.000006  0.000545  0.000403  0.000628  0.000077 -0.001995 -0.001165  0.000147
电子                   0.000365      -0.000586    0.000656       -0.000003  7.686605e-05 -0.000337 -1.584191e-04 -8.880432e-05     1.345832e-04             0.000408  ...  0.000205  0.000454  0.000135  0.001516  0.000542  0.001436 -0.000536 -0.001820 -0.001685 -0.000385
石油石化                -0.000297       0.000679   -0.000449       -0.000238 -3.903648e-05  0.000244  2.784371e-04  2.575526e-04    -3.535490e-05             0.000007  ... -0.000284 -0.000166 -0.000537 -0.001216 -0.000686 -0.000740  0.000705 -0.000166 -0.000565 -0.000205
纺织服装                -0.000035      -0.000080   -0.000432       -0.000067 -4.638686e-05  0.000103 -9.714661e-05 -1.014918e-04     3.687117e-05            -0.000113  ...  0.002112  0.000753  0.000433 -0.000162  0.000548  0.000252  0.001265 -0.001965 -0.000730  0.000644
综合                  -0.000162       0.000009   -0.001010       -0.000126 -2.097626e-05  0.000075 -6.421795e-05  3.071627e-06     2.201877e-05            -0.000150  ...  0.000753  0.003068  0.000865  0.000225  0.000735  0.000472  0.001226 -0.002276 -0.001080  0.000329
综合金融                -0.000015       0.000479   -0.000307       -0.000046 -3.131022e-05  0.000117 -1.907693e-04 -9.316430e-06    -5.916113e-05             0.000166  ...  0.000433  0.000865  0.012777  0.000259  0.000042  0.000386  0.000531 -0.001891 -0.000631  0.000231
计算机                  0.000496      -0.000683    0.000750       -0.000028  1.562095e-04 -0.000439 -2.839100e-04 -1.010311e-04     1.378490e-04             0.000526  ... -0.000162  0.000225  0.000259  0.004219  0.000371  0.002199 -0.001691 -0.000930 -0.001175 -0.000786
轻工制造                 0.000119      -0.000270    0.000249        0.000020 -6.506015e-05 -0.000009 -1.151912e-04 -8.041214e-05     5.191646e-05             0.000054  ...  0.000548  0.000735  0.000042  0.000371  0.002153  0.000392  0.000598 -0.001971 -0.000976  0.000565
通信                   0.000188      -0.000372    0.000031       -0.000026  1.113834e-04 -0.000245 -2.348988e-04 -6.803749e-05     4.457633e-05             0.000263  ...  0.000252  0.000472  0.000386  0.002199  0.000392  0.003877 -0.000836 -0.001544 -0.001467 -0.000430
钢铁                  -0.000318       0.001352   -0.001076       -0.000140 -2.963463e-04  0.000739  4.826072e-05 -2.230691e-04     6.597295e-05            -0.000454  ...  0.001265  0.001226  0.000531 -0.001691  0.000598 -0.000836  0.019536 -0.005261 -0.001310  0.001378
银行                  -0.000891      -0.000476   -0.002098       -0.000226  3.028849e-04 -0.000294 -2.352887e-05  5.137291e-04    -4.090413e-05            -0.000448  ... -0.001965 -0.002276 -0.001891 -0.000930 -0.001971 -0.001544 -0.005261  0.013030  0.001157 -0.003146
非银行金融                0.000075       0.000317    0.000910        0.000198 -1.004018e-04  0.000129 -9.926253e-05 -8.829111e-06    -9.349944e-05            -0.000161  ... -0.000730 -0.001080 -0.000631 -0.001175 -0.000976 -0.001467 -0.001310  0.001157  0.006073 -0.000987
食品饮料                 0.000007       0.000462    0.000374        0.000475 -1.351070e-04  0.000184  1.522055e-04 -1.041277e-04    -7.117080e-05            -0.000217  ...  0.000644  0.000329  0.000231 -0.000786  0.000565 -0.000430  0.001378 -0.003146 -0.000987  0.007102

[41 rows x 41 columns]

```

## get_specific_risk - 获取一组股票的特异波动率 {#rqdata-API-get_specific_risk}

```python
get_specific_risk(order_book_ids, start_date, end_date, horizon= 'daily', model = 'v1',industry_mapping='sws_2021')
```

获取一组股票的特异波动率数据，支持按时间范围、预测期限、行业分类和风险模型查询。例如可获取单只股票或多只股票的特异波动率，也支持日度、月度、季度三种预测期限。

#### 参数 {#rqdata-API-get_specific_risk-params}

| 参数             | 类型          | 说明                                                                                                                                                                                                                              |
|-----|-----|-----|
| order_book_ids   | _str or list_ | **必填参数**，证券代码（例如： '600705.XSHG'），可传入 order_book_id, order_book_id list                                                                                                                                          |
| start_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | **必填参数**，开始日期（例如： '2017-03-03'）                                                                                                                                                                                     |
| end_date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_         | **必填参数**，结束日期（例如： '2017-03-20'）                                                                                                                                                                                     |
| horizon          | _str_         | 预测期限。默认为日度（ 'daily'），可选月度（ 'monthly'）或季度（'quarterly'）                                                                                                                                                     |
| model            | _str_         | 'v1' 米筐老风险模型（[v1](#rqdata-API-risk-model-structure-v1)）<br/>'v2' 米筐新风险模型（[v2](#rqdata-API-risk-model-structure-v2)）<br/>'v2trd' 米筐新风险模型交易模型（[v2trd](#rqdata-API-risk-model-structure-v2trd)） <br/>'HKv1' 米筐港股通风险模型（[HKv1](#rqdata-API-risk-model-structure-HKv1)）<br/>'AHv1' 米筐 A+H 跨市场风险模型（[AHv1](#rqdata-API-risk-model-structure-AHv1)） |
| industry_mapping | _str_                 | 'sws_2021' - 申万 2021 行业分类<br/>'citics_2019' - 中信 2019 行业分类<br/>默认：industry_mapping = 'sws_2021'。<br/>港股通风险模型除默认申万行业分类外可选'csi_2021'-中证行业分类<br/>A+H 跨市场模型仅支持默认行业分类：industry_mapping = 'sws_2021'                                                                                             |
| market         | _str_                  | 默认是中国内地市场('cn')，港股通风险模型'HKv1'需使用('hk')  |                                                                                                                    |

#### 返回 {#rqdata-API-get_specific_risk-return}

_pandas.DataFrame_

index 为日期， column 为个股的 order_book_id

#### 范例 {#rqdata-API-get_specific_risk-example}

- 获取一只股票的特异波动率

```
In [18]: get_specific_risk('600705.XSHG','20170303','20170308',horizon='daily')
Out[18]:
order_book_id  600705.XSHG
date
2017-03-03        0.191777
2017-03-06        0.187424
2017-03-07        0.189880
2017-03-08        0.186224
```

- 获取一组股票的特异波动率

```
In [31]: get_specific_risk(['600705.XSHG','600100.XSHG'],'20170303','20170308',horizon='daily')
Out[31]:
order_book_id  600100.XSHG  600705.XSHG
date
2017-03-03        0.146083     0.191777
2017-03-06        0.142691     0.187424
2017-03-07        0.142536     0.189880
2017-03-08        0.139857     0.186224
```

- 获取一只股票中信 2019 的特异波动率

```
In [18]: rqdatac.get_specific_risk('600705.XSHG','20170303','20170308',horizon='daily',industry_mapping='citics_2019')
Out[18]:
order_book_id  600705.XSHG
date
2017-03-03        0.192311
2017-03-06        0.187687
2017-03-07        0.190031
2017-03-08        0.186779
```
