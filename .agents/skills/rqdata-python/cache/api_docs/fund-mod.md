## 行情数据 {#rqdata-API-fund-overview}

仅有场内基金提供五档行情，日行情、分钟行情、tick 行情数据，具体调用方式请参考 [API-get_price](generic-api.md#rqdata-API-get_price)。场外基金无该数据

::: tip 注意事项

以下基金 API 中，需先单独安装 **rqdatac_fund**，导入后进行调用。<br />
**涉及 order_book_ids 参数无需填后缀**，比如 000001、159001。

:::

## 基金基础数据，净值数据，以及衍生数据 {#rqdata-API-fund-basic_nav_derive}

### fund.instruments - 获取基金基础信息 {#rqdata-API-fund-instruments}

```python
fund.instruments(order_book_ids, market='cn')
```

获取指定公募基金的基础信息及历史转型合约信息，支持中国内地市场基金。例如可获取债券型、股票型、混合型等基金的基础资料，也支持查询如 `000014_CH0` 这类历史合约信息。

#### 参数 {#rqdata-API-fund-instruments-params}

| 参数           | 类型                | 说明                                |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_ | **必填参数**，基金代码，例如 000001 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-instruments-return}

基金 instrument 对象或 instrument list

| 字段                | 类型              | 说明                                                                                                                                                                                                 |
|-----|-----|-----|
| order_book_id       | _str_             | 合约代码                                                                                                                                                                                             |
| transition_time     | _integer_         | 合约代码复用次数，代码从来都属于唯一个基金，则 transition_time 为零                                                                                                                                  |
| symbol              | _str_             | 证券的名称                                                                                                                                                                                           |
| issuer              | _str_             | 基金公司(即将被废弃，同字段请使用`amc`)                                                                                                                                                              |
| fund_manager        | _str_             | 基金经理                                                                                                                                                                                             |
| establishement_date | _pandas.Timestamp_ | 基金成立日                                                                                                                                                                                           |
| listed_date         | _pandas.Timestamp_ | 基金上市日                                                                                                                                                                                           |
| stop_date           | _pandas.Timestamp_ | 基金终止日                                                                                                                                                                                           |
| de_listed_date      | _pandas.Timestamp_ | 基金退市日                                                                                                                                                                                           |
| benchmark           | _str_             | 业绩比较基准                                                                                                                                                                                         |
| latest_size         | _float_           | 最新基金规模（单位：元）                                                                                                                                                                             |
| abbrev_symbol       | _str_             | 基金简称                                                                                                                                                                                             |
| object              | _str_             | 投资目标                                                                                                                                                                                             |
| investment_scope    | _str_             | 投资范围                                                                                                                                                                                             |
| min_investment      | _str_             | 基金最小投资额                                                                                                                                                                                       |
| type                | _str_             | 合约的资产类型                                                                                                                                                                                       |
| fund_type           | _str_             | 基金类型<br />债券型 - `Bond`, 股票型 - `Stock`, 混合型 - `Hybrid`, 货币型 - `Money`, 短期理财型 - `ShortBond`, 股票指数 - `StockIndex`, 债券指数 - `BondIndex`, 联接基金 - `Related`, QDII - `QDII` |
| least_redeem        | _str_             | 最小申赎份额，仅对 ETF 展示                                                                                                                                                                          |
| amc                 | _str_             | 基金公司                                                                                                                                                                                             |
| amc_id              | _str_             | 基金公司 ID                                                                                                                                                                                          |
| accrued_daily       | _bool_            | 货币基金收益分配方式(份额结转方式) 按日结转还是其他结转                                                                                                                                              |
| exchange            | _str_             | 交易所，`XSHE` - 深交所, `XSHG` - 上交所                                                                                                                                                             |
| round_lot           | _int_             | 一手对应多少份，通常公募基金一手是 1 份                                                                                                                                                              |
| trustee             | _int_             | 基金托管人代码                                                                                                                                                                                       |
| redeem_amount_days  | _int_             | 赎回款到账天数                                                                                                                                                                                       |
| confirmation_days   | _int_             | 申赎份额确认天数                                                                                                                                                                                     |

#### 范例 {#rqdata-API-fund-instruments-example}

- 查询某基金合约信息

```
In [20]: fund.instruments('000014')
Out[20]: Instrument(order_book_id='000014', benchmark='100.0％×一年定期存款收益率(税后)加1.2%', issuer='华夏基金管理有 限公司', establishment_date='2013-03-19', listed_date='2013-03-19', de_listed_date='0000-00-00', stop_date='0000-00-00', symbol='华夏聚利债券', fund_manager='何家琪', fund_type='Bond', accrued_daily=False, latest_size=667046240.1, type='PublicFund', transition_time=1, exchange='', amc_id='41511', amc='华夏基金管理有限公司', abbrev_symbol='华夏聚利',..., min_investment=1.0, object='在控制风险的前提下，追求较高的当期收入和总回报。', trustee=3037, redeem_amount_days=7, confirmation_days=1, round_lot=1.0)
```

- 当某个旧基金的合约代码被重复使用，如何查找它的历史合约信息

```
In [10]: fund.instruments('000014_CH0')
Out[7]: Instrument(order_book_id='000014_CH0', benchmark='100.0％×一年定期存款收益率(税后)加1.2%', issuer='华夏基金管理有限公司', establishment_date='2013-03-19', listed_date='2013-03-19', symbol='华夏一年债', accrued_daily=False, fund_type='Bond', transition_time=0, de_listed_date='2014-03-19', stop_date='2014-03-19', latest_size=4016611053.94, type='PublicFund', exchange='', amc_id='41511', amc='华夏基金管理有限公司', round_lot=1.0)
```

### fund.all_instruments - 获取所有公募基金信息 {#rqdata-API-fund-all_instruments}

```python
fund.all_instruments(date=None, market='cn')
```

获取指定日期可交易的全部公募基金基础信息，默认按当前日期过滤尚未上市交易的基金合约。例如包括债券型、股票型、混合型等公募基金。

#### 参数 {#rqdata-API-fund-all_instruments-params}

| 参数 | 类型                                                           | 说明                                                           |
|-----|-----|-----|
| date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前日期。过滤掉在该日期尚未上市交易的基金合约 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-all_instruments-return}

_pandas DataFrame_

| 字段               | 类型              | 说明                                                                                                                                                                                                 |
|-----|-----|-----|
| order_book_id      | _str_             | 合约代码                                                                                                                                                                                             |
| symbol             | _str_             | 证券的简称                                                                                                                                                                                           |
| amc                | _str_             | 基金公司                                                                                                                                                                                             |
| fund_manager       | _str_             | 基金经理                                                                                                                                                                                             |
| establishment_date | _pandas.Timestamp_ | 基金成立日期                                                                                                                                                                                         |
| listed_date        | _pandas.Timestamp_ | 发基金上市日                                                                                                                                                                                         |
| transition_time    | _str_             | 转型次数。'0'-原始基金，'1'-第一次转型后基金，'2'-第二次转型后基金，以此类推                                                                                                                         |
| accrued_daily      | _str_             | 货币基金收益分配方式(份额结转方式) 按日结转还是其他结转                                                                                                                                              |
| de_listed_date     | _pandas.Timestamp_ | 基金退市日                                                                                                                                                                                           |
| stop_date          | _pandas.Timestamp_ | 基金终止日                                                                                                                                                                                           |
| exchange           | _str_             | 交易所，'XSHE' - 深交所, 'XSHG' - 上交所                                                                                                                                                             |
| benchmark          | _str_             | 业绩比较基准                                                                                                                                                                                         |
| latest_size        | _float_           | 最新基金规模（单位：元）                                                                                                                                                                             |
| fund_type          | _str_             | 基金类型<br />债券型 - `Bond`, 股票型 - `Stock`, 混合型 - `Hybrid`, 货币型 - `Money`, 短期理财型 - `ShortBond`, 股票指数 - `StockIndex`, 债券指数 - `BondIndex`, 联接基金 - `Related`, QDII - `QDII` |

#### 范例 {#rqdata-API-fund-all_instruments-example}

```
In [20]: fund.all_instruments().head()
Out[20]:
  order_book_id        listed_date     issuer         symbol   fund_type  \
0        233001    2004-03-26  摩根士丹利华鑫基金       大摩基础行业混合      Hybrid
1        165519    2013-08-16       信诚基金  信诚中证800医药指数分级  StockIndex
2        004234    2017-01-19       中欧基金      中欧数据挖掘混合C      Hybrid
3        370026    2013-02-04     上投摩根基金      上投轮动添利债券C        Bond
4        519320    2016-05-04     浦银安盛基金   浦银安盛幸福聚利定开债A       Other

  fund_manager   latest_size                          benchmark
0          孙海波  1.318854e+08          沪深300指数×55%+ 中证综合债券指数×45%
1           杨旭  2.371657e+08  95%×中证800制药与生物科技指数收益率+5%×金融同业存款利率
2           曲径           NaN       沪深300指数收益率×60%+中债综合指数收益率×40%
3           唐瑭  8.183768e+06                           中证综合债券指数
4          刘大巍  3.018930e+09                 一年期定期存款利率(税后)+1.4%
```

### fund.get_transition_info - 获取基金转型信息 {#rqdata-API-fund-get_transition_info}

```python
fund.get_transition_info(order_book_ids, market='cn')
```

获取基金转型前后各阶段的合约信息，包括不同转型次数对应的基金简称、成立日、上市日和终止日等数据。例如可查看原始基金和第一次转型后基金的对应关系。

#### 参数 {#rqdata-API-fund-get_transition_info-params}

| 参数           | 类型          | 说明                   |
|-----|-----|-----|
| order_book_ids | _str or list_ | **必填参数**，合约代码 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_transition_info-return}

_pandas DataFrame_

| 字段               | 类型  | 说明                                                                         |
|-----|-----|-----|
| order_book_id      | _str_ | 基金合约号                                                                   |
| transition_time    | _str_ | 转型次数。'0'-原始基金，'1'-第一次转型后基金，'2'-第二次转型后基金，以此类推 |
| abbrev_symbol      | _str_ | 基金简称                                                                     |
| symbol             | _str_ | 基金全称                                                                     |
| amc                | _str_ | 基金公司名称                                                                 |
| establishment_date | _pandas.Timestamp_ | 成立日                                                                       |
| listed_date        | _pandas.Timestamp_ | 上市日                                                                       |
| de_listed_date     | _pandas.Timestamp_ | 退市日                                                                       |
| stop_date          | _pandas.Timestamp_ | 终止日                                                                       |
| accrued_daily      | _str_ | 货币基金收益分配方式(份额结转方式) 按日结转还是其他结转                      |

#### 范例 {#rqdata-API-fund-get_transition_info-example}

```
In [4]: fund.get_transition_info('000014')
Out[4]:
                              abbrev_symbol  accrued_daily         amc  ... listed_date   stop_date      symbol
order_book_id transition_time                                           ...
000014        0                       华夏一年债          False  华夏基金管理有限公司  ...  2013-03-19  2014-03-19  华夏一年定期开放债券
              1                        华夏聚利          False  华夏基金管理有限公司  ...  2014-03-19  0000-00-00       华夏聚利债券
```

### fund.get_nav - 获取基金净值信息 {#rqdata-API-fund-get_nav}

```python
fund.get_nav(order_book_ids, start_date=None, end_date=None, fields=None, expect_df=False, market='cn')
```

获取基金净值数据，支持按时间范围查询单位净值、累计单位净值、复权净值等信息。对于货币基金，还可获取每万元收益、7日年化收益率等数据。

#### 参数 {#rqdata-API-fund-get_nav-params}

| 参数           | 类型                                                           | 说明                                                                   |
|-----|-----|-----|
| order_book_ids | _str or list_                                                  | **必填参数**，基金代码                                                 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的开始日期                                                         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的结束日期，start_date ,end_date 不传参数时默认返回所有数据        |
| fields         | _str_ OR _str list_                                            | 查询字段，可选字段见下方返回，默认返回所有字段                         |
| expect_df      | _boolean_                                                      | 默认为 False，返回原有的数据结构。若调为True，则返回 pandas dataframe  |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_nav-return}

_pandas DataFrame_

| 字段               | 类型    | 说明           |
|-----|-----|-----|
| unit_net_value     | _float_ | 单位净值       |
| acc_net_value      | _float_ | 累计单位净值   |
| adjusted_net_value | _float_ | 复权净值       |
| change_rate        | _float_ | 涨跌幅         |
| daily_profit       | _float_ | 每万元收益     |
| weekly_yield       | _float_ | 7 日年化收益率 |

#### 范例 {#rqdata-API-fund-get_nav-example}

```
In [11]: fund.get_nav(['000003','519505'],start_date=20200910,end_date=20200917)
Out[11]:
                          unit_net_value  acc_net_value  change_rate  adjusted_net_value  daily_profit  weekly_yield
order_book_id datetime
000003        2020-09-10           0.912          1.122    -0.009771            1.072268           NaN           NaN
              2020-09-11           0.915          1.125     0.003289            1.075795           NaN           NaN
              2020-09-14           0.915          1.125     0.000000            1.075795           NaN           NaN
              2020-09-15           0.915          1.125     0.000000            1.075795           NaN           NaN
              2020-09-16           0.914          1.124    -0.001093            1.074619           NaN           NaN
              2020-09-17           0.911          1.121    -0.003282            1.071092           NaN           NaN
519505        2020-09-10           1.000          1.000     0.000046            1.498024        0.4591       0.01971
              2020-09-11           1.000          1.000     0.000046            1.498093        0.4607       0.01921
              2020-09-13           1.000          1.000     0.000046            1.498231        0.9221       0.01934
              2020-09-14           1.000          1.000     0.000047            1.498302        0.4698       0.01832
              2020-09-15           1.000          1.000     0.000047            1.498373        0.4719       0.01713
              2020-09-16           1.000          1.000     0.000048            1.498445        0.4837       0.01718
              2020-09-17           1.000          1.000     0.000048            1.498517        0.4790       0.01729
```

### fund.get_transaction_status - 获取基金申购赎回相关信息 {#rqdata-API-fund-get_transaction_status}

```python
fund.get_transaction_status(order_book_ids, start_date=None, end_date=None, fields=None,investor='institution', market='cn')
```

获取基金申购、赎回和募集状态相关数据，支持区分机构和个人投资者。例如可查询开放、暂停、限制大额申购或封闭期等状态，也可获取申购上限、申购下限、赎回下限等信息。

#### 参数 {#rqdata-API-fund-get_transaction_status-params}

| 参数           | 类型                                                           | 说明                                                            |
|-----|-----|-----|
| order_book_ids | _str or list_                                                  | **必填参数**，基金代码                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| fields         | _str_ OR _str list_                                            | 查询字段，可选字段见下方返回，默认返回所有字段                  |
| investor       | _str_                                                          | 默认为 institution<br />institution - 机构 , retail - 个人      |
| market         | _str_                                                          | 指定市场，目前仅有中国市场('cn')的基金数据                      |

#### 返回 {#rqdata-API-fund-get_transaction_status-return}

_pandas DataFrame_

| 字段                  | 类型    | 说明                                                                                    |
|-----|-----|-----|
| subscribe_status      | _str_   | 订阅状态。开放 - `Open`, 暂停 - `Suspended`, 限制大额申购 - `Limited`, 封闭期 - `Close` |
| redeem_status         | _str_   | 赎回状态。开放 - `Open`, 暂停 - `Suspended`, 限制大额赎回 - `Limited`, 封闭期 - `Close` |
| issue_status          | _str_   | 募集状态。募集中 - `Open`, 非募集期 - `Close`                                           |
| subscribe_upper_limit | _float_ | 申购上限（金额）                                                                        |
| subscribe_lower_limit | _float_ | 申购下限（金额）                                                                        |
| redeem_lower_limit    | _float_ | 赎回下限（份额）                                                                        |
| redeem_upper_limit    | _float_ | 赎回上限（份额），仅支持 ETF                                                            |

#### 范例 {#rqdata-API-fund-get_transaction_status-example}

获取个人申赎状态及相关信息

```
In [14]: fund.get_transaction_status('040001',start_date='2020-11-01',end_date='2020-11-10',investor='retail')
Out[14]:
                         subscribe_status redeem_status issue_status subscribe_upper_limit subscribe_lower_limit redeem_lower_limit
order_book_id datetime
040001        2020-11-01             Open          Open        Close                  None                     1                  1
              2020-11-02             Open          Open        Close                  None                     1                  1
              2020-11-03             Open          Open        Close                  None                     1                  1
              2020-11-04             Open          Open        Close                  None                     1                  1
              2020-11-05             Open          Open        Close                  None                     1                  1
              2020-11-06             Open          Open        Close                  None                     1                  1
              2020-11-07             Open          Open        Close                  None                     1                  1
              2020-11-08             Open          Open        Close                  None                     1                  1
              2020-11-09             Open          Open        Close                  None                     1                  1
              2020-11-10             Open          Open        Close                  None                     1                  1
```

获取机构申赎状态及相关信息

```
In [18]: fund.get_transaction_status('040001',start_date='2020-01-15',end_date='2020-01-25',investor='institution')
Out[18]:
                         subscribe_status redeem_status issue_status subscribe_upper_limit subscribe_lower_limit redeem_lower_limit
order_book_id datetime
040001        2020-01-15             Open          Open        Close                  None                     1                  1
              2020-01-16          Limited          Open        Close                 1e+06                     1                  1
              2020-01-17          Limited          Open        Close                 1e+06                     1                  1
              2020-01-18          Limited          Open        Close                 1e+06                     1                  1
              2020-01-19          Limited          Open        Close                 1e+06                     1                  1
              2020-01-20          Limited          Open        Close                 1e+06                     1                  1
              2020-01-21          Limited          Open        Close                 1e+06                     1                  1
              2020-01-22             Open          Open        Close                  None                     1                  1
              2020-01-23             Open          Open        Close                  None                     1                  1
              2020-01-24             Open          Open        Close                  None                     1                  1
              2020-01-25             Open          Open        Close                  None                     1                  1
```

### fund.get_credit_quality - 获取基金债券持仓投资信用评级信息 {#rqdata-API-fund-get_credit_quality}

```python
fund.get_credit_quality(order_book_ids, date=None, market='cn')
```

获取基金债券持仓的投资信用评级数据，支持从指定日期回溯最近披露期或查询全部日期。例如可获取债券长期信用评级、债券短期信用评级、资产支持证券长期信用评级等评级数据。

#### 参数 {#rqdata-API-fund-get_credit_quality-params}

| 参数           | 类型                                                           | 说明                                                                                                     |
|-----|-----|-----|
| order_book_ids | _str or list_                                                  | **必填参数**，基金代码                                                                                   |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的债券投资信用评级数据。如不指定日期，则获取所有日期的债券投资评级数据 |
| market         | _str_                                                          | 指定市场，目前仅有中国市场('cn')的基金数据                                                               |

#### 返回 {#rqdata-API-fund-get_credit_quality-return}

_pandas DataFrame_

| 字段                    | 说明              | 说明                 |
|-----|-----|-----|
| date                    | _pandas.Timestamp_ | 持仓披露日期         |
| credit_rating           | _str_             | 债券信用等级         |
| bond_sector_rating_type | _str_             | 债券持仓评级类别     |
| market_value            | _float_           | 持仓市值（单位：元） |

#### 范例 {#rqdata-API-fund-get_credit_quality-example}

```
In [8]: fund.get_credit_quality(['000003','000033'],20200620)
Out[8]:
                         credit_rating bond_sector_rating_type  market_value
order_book_id date
000003        2019-12-31           未评级                债券短期信用评级  6.721030e+06
              2019-12-31           AAA                债券长期信用评级  1.083061e+08
              2019-12-31         AAA以下                债券长期信用评级  4.014485e+07
000033        2019-12-31           A-1                债券短期信用评级  8.182628e+07
              2019-12-31           未评级                债券短期信用评级  3.466683e+08
              2019-12-31           AAA                债券长期信用评级  4.052186e+09
              2019-12-31         AAA以下                债券长期信用评级  1.284435e+09
              2019-12-31           AAA           资产支持证券将长期信用评级  2.036309e+07
```

### fund.get_etf_components - 获取 ETF 每日申购赎回清单数据（即将废弃） {#rqdata-API-fund-get_etf_components}

```python
fund.get_etf_components(order_book_ids, trading_date=None, market='cn')
```

获取 ETF 每日申购赎回清单中的成份证券数据，包括成份证券数量及现金替代相关信息，如现金替代规则、现金替代比例、固定现金替代金额等。

::: tip 注意事项

由于该接口只涉及场内基金，后续迁移至对应目录下，并逐渐废弃，见 [etf.get_components](../python/indices-mod.md#rqdata-API-etf-get_components)

:::

#### 参数 {#rqdata-API-fund-get_etf_components-params}

| 参数           | 类型                                                           | 说明                                                         |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                       |
| trading_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，如不指定日期，则获取当天数据（注意仅交易日有效）。 |

#### 返回 {#rqdata-API-fund-get_etf_components-return}

_pandas DataFrame_

| 字段                       | 说明              | 说明                                                         |
|-----|-----|-----|
| trading_date               | _pandas.Timestamp_ | 持仓日期                                                     |
| stock_amount               | _float_           | 股票数量                                                     |
| cash_substitute            | _str_             | 现金替代规则                                                 |
| cash_substitute_proportion | _float_           | 现金替代比例                                                 |
| fixed_cash_substitute      | _float_           | 固定现金金额（上交所字段，深交所是用申购替换金额填充该字段） |
| redeem_cash_substitute     | _float_           | 赎回替代金额(元)（深交所）                                   |

#### 范例 {#rqdata-API-fund-get_etf_components-example}

```
In [10]: fund.get_etf_components('510050.XSHG',trading_date=20190117)
Out[10]:

 trading_date  order_book_id  stock_code  stock_amount  cash_substitute  cash_substitute_proportion  fixed_cash_substitute
0  2019-01-17  510050.XSHG    600000      5600.0              允许                               0.1    NaN
1  2019-01-17  510050.XSHG    600016      11900.0            允许                               0.1    NaN
2  2019-01-17  510050.XSHG    600019      4300.0              允许                               0.1    NaN
3  2019-01-17  510050.XSHG    600028      5800.0              允许                               0.1    NaN
4  2019-01-17  510050.XSHG    600029      1600.0              允许                               0.1    NaN
5  2019-01-17  510050.XSHG    600030      3800.0              允许                               0.1    NaN
6  2019-01-17  510050.XSHG    600036      4900.0              允许                               0.1    NaN
7  2019-01-17  510050.XSHG    600048      3400.0              允许                               0.1    NaN
8  2019-01-17  510050.XSHG    600050      4500.0              允许                               0.1    NaN
...

```

### fund.get_etf_cash_components - 获取 ETF 现金差额数据（即将废弃） {#rqdata-API-fund-get_etf_cash_components}

```python
fund.get_etf_cash_components(order_book_ids,start_date=None,end_date=None, market='cn')
```

获取 ETF 现金差额数据，支持按时间范围查询现金差额、预估现金差额、最小申购赎回单位资产净值等信息。

::: tip 注意事项

由于该接口只涉及场内基金，后续迁移至对应目录下，并逐渐废弃，见 [etf.get_cash_components](../python/indices-mod.md#rqdata-API-etf-get_cash_components)

:::

#### 参数 {#rqdata-API-fund-get_etf_cash_components-params}

| 参数          | 类型                                                     | 说明                                                      |
|-----|-----|-----|
| order_book_id | _str_ or _list_                                          | **必填参数**，基金代码                                    |
| start_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_etf_cash_components-return}

_pandas DataFrame_

| 字段                  | 类型              | 说明                                |
|-----|-----|-----|
| date                  | _pandas.Timestamp_ | 预估日期                            |
| pre_date              | _pandas.Timestamp_ | 交易日期                            |
| cash_component        | _float_           | 现金差额（单位:元）                 |
| nav_per_basket        | _float_           | 最小申购赎回单位资产净值（单位:元） |
| est_cash_component    | _float_           | 预估现金差额（单位:元）             |
| max_cash_ratio        | _float_           | 现金替代上限                        |
| unit_subscribe_redeem | _float_           | 最小申赎单位（份）                  |

#### 范例 {#rqdata-API-fund-get_etf_cash_components-example}

- 获取单个 ETF 现金差额数据

```
In[]:fund.get_etf_cash_components('510050.XSHG','20191201','20191205')
Out[]:

order_book_id date cash_component est_cash_component max_cash_ratio nav_per_basket pre_date
510050.XSHG 2019-12-02 55959.24 31237.24 0.5 2646969.24 2019-11-29
            2019-12-03 31488.64 35832.64 0.5 2608899.64 2019-12-02
            2019-12-04 34927.55 33264.55 0.5 2617784.55 2019-12-03
            2019-12-05 33230.56 35727.56 0.5 2610131.56 2019-12-04

```

- 获取多个 ETF 现金差额数据

```
In[]:fund.get_etf_cash_components(['510050.XSHG','510300.XSHG'],'20191201','20191205')
Out[]:

order_book_id date cash_component est_cash_component max_cash_ratio nav_per_basket pre_date
510050.XSHG 2019-12-02 55959.24 31237.24 0.5 2646969.24 2019-11-29
            2019-12-03 31488.64 35832.64 0.5 2608899.64 2019-12-02
            2019-12-04 34927.55 33264.55 0.5 2617784.55 2019-12-03
            2019-12-05 33230.56 35727.56 0.5 2610131.56 2019-12-04
510300.XSHG 2019-12-02 -34311.25 -29329.25 0.5 3501800.75 2019-11-29
            2019-12-03 -28545.40 -30993.40 0.5 3508327.60 2019-12-02
            2019-12-04 -30828.28 -29276.28 0.5 3522019.72 2019-12-03
            2019-12-05 -29934.94 -32790.94 0.5 3520765.06 2019-12-04

```

### fund.get_split - 获取基金拆分信息 {#rqdata-API-fund-get_split}

```python
fund.get_split(order_book_ids, market='cn')
```

获取基金拆分信息，包括除权除息日和拆分折算比例。

#### 参数 {#rqdata-API-fund-get_split-params}

| 参数           | 类型          | 说明                   |
|-----|-----|-----|
| order_book_ids | _str or list_ | **必填参数**，基金代码 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_split-return}

_pandas DataFrame_

| 字段             | 类型              | 说明                 |
|-----|-----|-----|
| ex_dividend_date | _pandas.Timestamp_ | 除权除息日           |
| split_ratio      | _float_           | 拆分折算比例，1 拆几 |

#### 范例 {#rqdata-API-fund-get_split-example}

```
In [13]: fund.get_split('000246').head()
Out[13]:
           split_ratio
2013-11-01  1.00499349
2013-12-02  1.00453123
2014-01-02  1.00455316
2014-02-07  1.00456182
2014-03-03  1.00452639

```

### fund.get_dividend - 获取基金分红信息 {#rqdata-API-fund-get_dividend}

```python
fund.get_dividend(order_book_ids, market='cn')
```

获取基金分红信息，包括权益登记日、每份税前分红、除权除息日和分红发放日等数据。

#### 参数 {#rqdata-API-fund-get_dividend-params}

| 参数           | 类型            | 说明                   |
|-----|-----|-----|
| order_book_ids | _str_ or _list_ | **必填参数**，基金代码 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_dividend-return}

_pandas DataFrame_

| 字段                | 类型              | 说明         |
|-----|-----|-----|
| ex_dividend_date    | _pandas.Timestamp_ | 除权除息日   |
| book_closure_date   | _pandas.Timestamp_ | 权益登记日   |
| dividend_before_tax | _float_           | 每份税前分红 |
| payable_date        | _pandas.Timestamp_ | 分红发放日   |

#### 范例 {#rqdata-API-fund-get_dividend-example}

```
In [11]: fund.get_dividend('050116')
Out[11]:
           book_closure_date payable_date  dividend_before_tax
2012-01-17        2012-01-17   2012-01-19                0.002
2013-01-16        2013-01-16   2013-01-18                0.013
2015-01-14        2015-01-14   2015-01-16                0.028

```

### fund.get_ratings - 获取基金评级信息 {#rqdata-API-fund-get_ratings}

```python
fund.get_ratings(order_book_ids, date=None, market='cn')
```

获取基金评级数据，支持回溯最近披露期或查询全部日期。例如包括招商评级、上海证券三年期评级、上海证券五年期评级、济安金信评级。

#### 参数 {#rqdata-API-fund-get_ratings-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                                       |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的数据。如不指定日期，则获取所有日期的数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_ratings-return}

_pandas DataFrame_

| 字段     | 类型              | 说明               |
|-----|-----|-----|
| datetime | _pandas.Timestamp_ | 评级日期           |
| zs       | _float_           | 招商评级           |
| sh3      | _float_           | 上海证券评级三年期 |
| sh5      | _float_           | 上海证券评级五年期 |
| jajx     | _float_           | 济安金信评级       |

#### 范例 {#rqdata-API-fund-get_ratings-example}

```
In [16]: fund.get_ratings('202101')
Out[16]:
             zs  sh3  sh5  jajx
2009-12-31  NaN  NaN  NaN   3.0
2010-03-31  NaN  NaN  NaN   3.0
2010-04-30  2.0  NaN  NaN   NaN
2010-06-30  NaN  3.0  4.0   1.0
2010-09-30  NaN  3.0  4.0   1.0
2010-12-31  NaN  2.0  4.0   1.0

```

### fund.get_units_change - 获取基金份额变动信息 {#rqdata-API-fund-get_units_change}

```python
fund.get_units_change(order_book_ids, date=None, market='cn')
```

获取基金份额变动数据，包括期间申购份额、赎回份额、期末总份额和期末总净资产值等信息。

#### 参数 {#rqdata-API-fund-get_units_change-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                                       |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的数据。如不指定日期，则获取所有日期的数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_units_change-return}

_pandas DataFrame_

| 字段            | 类型              | 说明                     |
|-----|-----|-----|
| datetime        | _pandas.Timestamp_ | 报告期                   |
| subscribe_units | _float_           | 期间申购（单位：份）     |
| redeem_units    | _float_           | 期间赎回（单位：份）     |
| info_date       | _pandas.Timestamp_ | 公告日期                 |
| units           | _float_           | 期末总份额（单位：份）   |
| net_asset       | _float_           | 期末总净资产值(单位：元) |

#### 范例 {#rqdata-API-fund-get_units_change-example}

```
In [20]: fund.get_units_change('001554')
Out[20]:
                          subscribe_units  redeem_units  info_date        units    net_asset
order_book_id datetime
001554        2015-06-30              NaN           NaN        NaT          NaN   5000049.32
              2015-09-30      71408891.69   37755554.39 2015-10-24  38653337.30  27630465.58
              2015-12-31      19756969.98   20692807.21 2016-01-22  37717500.07  29573475.62
              2016-03-31      17467356.40   16372818.76 2016-04-21  38812037.71  25200577.87
              2016-06-30      21264325.34   15937884.63 2016-07-19  44138478.42  26526043.52
              2016-09-30      37842604.31   32218403.07 2016-10-26  49762679.66  30466565.39
              2016-12-31      19158060.76   25157817.68 2017-01-20  43762922.74  27451195.12
              2017-03-31      12145314.55   18072618.82 2017-04-22  37835618.47  25060465.04
              2017-06-30      27133401.79   21380926.25 2017-07-21  43588094.01  28659171.47
              2017-09-30      12997778.42   19264758.68 2017-10-26  37321113.75  25039774.80
              2017-12-31      10697714.94   12001467.35 2018-01-19  36017361.34  24185742.78
              2018-03-31      11924561.78   12505966.08 2018-04-23  35435957.04  22390195.84
              2018-06-30       4840103.56   16326724.31 2018-07-19  23949336.29  13476927.82
```

### fund.get_holder_structure - 获取基金持有人结构 {#rqdata-API-fund-get_holder_structure}

```python
fund.get_holder_structure(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取基金持有人结构数据，包括机构投资者和个人投资者的持有份额及占比。

#### 参数 {#rqdata-API-fund-get_holder_structure-params}

| 参数           | 类型                                                     | 说明                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | **必填参数**，基金代码                                    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期, start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |


#### 返回 {#rqdata-API-fund-get_holder_structure-return}

_pandas DataFrame_

| 字段          | 类型              | 说明                      |
|-----|-----|-----|
| date          | _pandas.Timestamp_ | 报告期                    |
| info_date     | _pandas.Timestamp_ | 公告日期                  |
| instl         | _float_           | 机构投资者持有份额(份)    |
| instl_weight  | _float_           | 构投资者持有份额占比(%)   |
| retail        | _float_           | 个人投资者持有份额(份)    |
| retail_weight | _float_           | 个人投资者持有份额占比(%) |

#### 范例 {#rqdata-API-fund-get_holder_structure-example}

```
In [10]: fund.get_holder_structure('000001','20190101','20200101')
Out[10]:
                instl instl_weight retail retail_weight
order_book_id date
000001 2019-06-30 16995587.39 0.40 4.277759e+09 99.60
2019-12-31 18827745.40 0.45 4.142996e+09 99.55
```

### fund.get_benchmark - 获取基金基准 {#rqdata-API-fund-get_benchmark}

```python
fund.get_benchmark(order_book_ids, market='cn')
```

获取基金业绩比较基准构成数据，包括基准起止日期、指数代码、指数名称和指数权重。例如可获取中证小盘500指数、活期存款利率（税后）等基准构成项。

#### 参数 {#rqdata-API-fund-get_benchmark-params}

| 参数           | 类型            | 说明                   |
|-----|-----|-----|
| order_book_ids | _str_ or _list_ | **必填参数**，基金代码 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_benchmark-return}

_pandas DataFrame_

| 字段         | 类型              | 说明     |
|-----|-----|-----|
| start_date   | _pandas.Timestamp_ | 起始日   |
| end_date     | _pandas.Timestamp_ | 截止日   |
| index_code   | _str_             | 指数代码 |
| index_name   | _str_             | 指数名称 |
| index_weight | _float_           | 指数权重 |

#### 范例 {#rqdata-API-fund-get_benchmark-example}

```
In [10]:fund.get_benchmark('000006')
Out[10]:  end_date index_code index_name index_weight
order_book_id start_date
000006 2019-02-15 2019-12-25 000905.XSHG 中证小盘500指数 0.75
2019-02-15 2019-12-25 B00009 活期存款利率(税后) 0.25
2019-12-25 NaT 000905.XSHG 中证小盘500指数 0.75
2019-12-25 NaT B00009 活期存款利率(税后) 0.25
```

### fund.get_financials - 获取基金财务信息 {#rqdata-API-fund-get_financials}

```python
fund.get_financials(order_book_ids,start_date=None, end_date=None, fields=None, market='cn')
```

获取基金财务数据，支持按时间范围查询总资产、总权益、杠杆率等信息，也支持股票买入成本、股票买入收入等字段。

#### 参数 {#rqdata-API-fund-get_financials-params}

| 参数           | 类型                                                           | 说明                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | 基金代码                                                  |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| fields         | str or list                                                    | 查询字段，可选字段见下方返回，默认返回所有字段            |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_financials-return}

_pandas DataFrame_

| 字段                             | 说明                 |
|-----|-----|
| cash_equivalent                  | 现金及现金等价物     |
| financial_asset_held_for_trading | 交易性金融资产       |
| dividend_receivable              | 应收股利             |
| interest_receivable              | 应收利息             |
| deferred_income_tax_assets       | 递延所得税资产       |
| other_accts_receivable           | 其他应收账款         |
| accts_receivable                 | 应收账款             |
| other_assets                     | 其他资产             |
| deferred_expense                 | 待摊费用             |
| total_asset                      | 总资产               |
| financial_liabilities            | 交易性金融负债       |
| redemption_money_payable         | 应付赎回款           |
| redemption_fee_payable           | 应付赎回费           |
| management_fee_payable           | 应付管理人报酬       |
| trust_fee_payable                | 应付托管费           |
| sales_fee_payable                | 应付销售服务费       |
| transaction_fee_payable          | 应付交易费用         |
| tax_payable                      | 应交税费             |
| interest_payable                 | 应付利息             |
| profit_payable                   | 应付利润             |
| deferred_income_tax_liabilities  | 递延所得税负债       |
| accts_payable                    | 应付帐款             |
| other_accts_payable              | 其他应付款           |
| other_liabilities                | 其他负债             |
| total_liabilities                | 负债合计             |
| paid_in_capital                  | 实收基金             |
| undistributed_profit             | 未分配利润           |
| other_equity                     | 其他权益             |
| total_equity                     | 总权益               |
| total_equity_and_liabilities     | 负债和所有者权益合计 |
| leverage                         | 杠杆率               |
| stock_cost                       | 股票买入成本         |
| stock_income                     | 股票买入收入         |

#### 范例 {#rqdata-API-fund-get_financials-example}

```
In [10]:fund.get_financials('000001','20190101','20191231',fields=['total_asset','total_equity','leverage','stock_cost','stock_income'])

Out[10]:   leverage stock_cost stock_income total_asset total_equity
order_book_id date
000001 2019-06-30 1.007034 6.082403e+09 6.246101e+09 4.747522e+09 4.714361e+09
2019-12-31 1.010894 1.364662e+10 1.378563e+10 4.648447e+09 4.598352e+09
```

### fund.get_fee - 获取基金费率信息 {#rqdata-API-fund-get_fee}

```python
fund.get_fee(order_book_ids,fee_type=None,charge_type='front',date=None,market_type='otc',market='cn')
```

获取基金费率数据，支持按费率类型、前端或后端费率、场内或场外费率查询。例如可获取申购费率、赎回费率、管理费率、托管费率、认购费率等数据。

#### 参数 {#rqdata-API-fund-get_fee-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                                                                                               |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                                                                                                                                                                                                                             |
| fee_type       | _str_ or _list_                                                | 费率类型，默认为 None 返回所有类型，可选：<br /> `subscription_fee` - 申购费率，<br /> `redemption_fee` - 赎回费率，<br /> `management_fee` - 管理费率，<br /> `custodian_fee` - 托管费率，<br /> `sales_service_fee` - 营销费率，<br /> `purchase_fee` - 认购费率 |
| charge_type    | _str_                                                          | 默认为 front <br /> `front` - 前端费率 ，`back` - 后端费率                                                                                                                                                                                                         |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，获取距离指定日期最近的数据。如不指定日期，则默认为当前最新时点                                                                                                                                                                                           |
| market_type    | _str_                                                          | 费率适用渠道，默认为 otc <br /> `otc` - 场外费率 ，`exchange` - 场内费率                                                                                                                                                                                           |

#### 返回 {#rqdata-API-fund-get_fee-return}

_pandas DataFrame_

| 字段                 | 类型    | 说明                    |
|-----|-----|-----|
| fee_type             | _str_   | 费率类型                |
| fee_value            | _float_ | 费率金额（元）          |
| fee_ratio            | _float_ | 费率                    |
| inv_floor            | _float_ | 金额下限（万元）        |
| inv_cap              | _float_ | 金额上限（万元）        |
| share_floor          | _float_ | 份额下限（万份）        |
| share_cap            | _float_ | 份额上限（万份）        |
| holding_period_floor | _float_ | 持有期下限（天）        |
| holding_period_cap   | _float_ | 持有期上限（天）        |
| return_floor         | _float_ | 基金年化收益率下限（%） |
| return_cap           | _float_ | 基金年化收益率上限（%） |

#### 范例 {#rqdata-API-fund-get_fee-example}

获取后端场外费率

```
In [23]: fund.get_fee("000001", charge_type='back')
Out[23]:
                                fee_ratio  fee_value  inv_floor  ...  holding_period_cap  return_floor  return_cap
order_book_id fee_type                                           ...
000001        custodian_fee        0.0025        NaN        NaN  ...                 NaN           NaN         NaN
              management_fee       0.0150        NaN        NaN  ...                 NaN           NaN         NaN
              redemption_fee       0.0050        NaN        NaN  ...                 NaN           NaN         NaN
              redemption_fee       0.0150        NaN        NaN  ...                 7.0           NaN         NaN
              subscription_fee     0.0150        NaN        NaN  ...               730.0           NaN         NaN
              subscription_fee     0.0180        NaN        NaN  ...               365.0           NaN         NaN
              subscription_fee     0.0120        NaN        NaN  ...              1095.0           NaN         NaN
              subscription_fee     0.0100        NaN        NaN  ...              1460.0           NaN         NaN
              subscription_fee     0.0000        NaN        NaN  ...                 NaN           NaN         NaN
              subscription_fee     0.0050        NaN        NaN  ...              2920.0           NaN         NaN
```

获取前端场外费率

```
In [24]: fund.get_fee("000001", charge_type='front')
Out[24]:
                                fee_ratio  fee_value  inv_floor  ...  holding_period_cap  return_floor  return_cap
order_book_id fee_type                                           ...
000001        custodian_fee        0.0025        NaN        NaN  ...                 NaN           NaN         NaN
              management_fee       0.0150        NaN        NaN  ...                 NaN           NaN         NaN
              purchase_fee         0.0100        NaN        NaN  ...                 NaN           NaN         NaN
              redemption_fee       0.0150        NaN        NaN  ...                 7.0           NaN         NaN
              redemption_fee       0.0050        NaN        NaN  ...                 NaN           NaN         NaN
              subscription_fee        NaN     1000.0     1000.0  ...                 NaN           NaN         NaN
              subscription_fee     0.0120        NaN      100.0  ...                 NaN           NaN         NaN
              subscription_fee     0.0080        NaN      500.0  ...                 NaN           NaN         NaN
              subscription_fee     0.0150        NaN        0.0  ...                 NaN           NaN         NaN
```

### fund.get_benchmark_price - 获取特殊的基金基准行情 {#rqdata-API-fund-get_benchmark_price}



```python
fund.get_benchmark_price(order_book_ids,start_date=None,end_date=None, market='cn')
```

获取基金风格分类指数对应的基准行情数据，支持按时间范围查询收盘价。例如可获取偏股型等分类指数代码对应的行情。

#### 参数 {#rqdata-API-fund-get_benchmark_price-params}

| 参数           | 类型                                                     | 说明                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | **必填参数**，基金对应指数分类代码，对应指数可通过 [fund.get_instrument_category](./fund-mod.md#rqdata-API-fund-get_instrument_category) 获取                                  |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |



#### 返回 {#rqdata-API-fund-get_benchmark_price-return}

| 字段  | 类型              | 说明     |
|-----|-----|-----|
| date  | _pandas.Timestamp_ | 交易日期 |
| close | _float_           | 收盘价   |

#### 范例 {#rqdata-API-fund-get_benchmark_price-example}

- 获取 000001 对应指数偏股型行情

```
In [10]: fund.get_benchmark_price('1201',20251201,20251210)
Out[10]:
                              close
order_book_id	date	
1201	        2025-12-01	11957.0851
                2025-12-02	11881.7087
                2025-12-03	11822.3933
                2025-12-04	11869.7807
                2025-12-05	11976.5504
                2025-12-08	12085.6558
                2025-12-09	12025.9445
                2025-12-10	12055.2109

```

### fund.get_snapshot - 获取基金最新的衍生数据 {#rqdata-API-fund-get_snapshot}

```python
fund.get_snapshot(order_book_ids, fields=None, rule='ricequant', indicator_type='value', market='cn')
```

获取基金最新一期衍生指标值或指标排名数据。例如可获取累计收益率、超额收益率、Sharpe Ratio（年化）等指标，也包含指标计算基准或排名范围信息。

#### 参数 {#rqdata-API-fund-get_snapshot-params}

| 参数           | 类型            | 说明                                                                   |
|-----|-----|-----|
| order_book_ids | _str_ or _list_ | 基金代码                                                               |
| fields         | _str_ or _list_ | 查询字段，可选字段见下方返回，默认返回所有字段                         |
| rule           | _str_           | 指定算法，目前仅支持返回算法 'ricequant'                               |
| indicator_type | _str_           | 指标类别，默认为 value <br /> value - 衍生指标值 ，rank - 衍生指标排名 |
| market         | _str_           | 指定市场，目前仅有中国市场('cn')的基金衍生数据                         |

#### 返回 {#rqdata-API-fund-get_snapshot-return}

标准版涵盖的衍生指标及频率如下，字段的组成方式为 “支持的频率\_字段”, 如 “日度累计收益” 字段名为 'daily_return'，货币基金仅支持展示下面部分衍生指标数据。

| 字段               | 说明                             | 支持的频率                                         |
|-----|-----|-----|
| return             | 累计收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| return_a           | 累计收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| benchmark_return   | 累计收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| excess             | 超额收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| excess_a           | 超额收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| excess_win         | 超额胜率                         | m3、m6、y2、y1、y3、y5、total                      |
| stdev_a            | 波动率（年化）                   | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_avg_a | 下行波动率 - 均值（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_rf_a  | 下行波动率 - 无风险利率 （年化） | m3、m6、y2、y1、y3、y5、total                      |
| mdd                | 期间最大回撤                     | m3、m6、y2、y1、y3、y5、total                      |
| excess_mdd         | 期间超额收益最大回撤             | m3、m6、y2、y1、y3、y5、total                      |
| mdd_days           | 最大回撤持续期                   | m3、m6、y2、y1、y3、y5、total                      |
| recovery_days      | 最大回撤恢复期                   | m3、m6、y2、y1、y3、y5、total                      |
| max_drop           | 最大单日跌幅                     | m3、m6、y2、y1、y3、y5、total                      |
| max_drop_period    | 最大连跌期数                     | m3、m6、y2、y1、y3、y5、total                      |
| neg_return_ratio   | 亏损期占比                       | m3、m6、y2、y1、y3、y5、total                      |
| kurtosis           | 峰度                             | m3、m6、y2、y1、y3、y5、total                      |
| skewness           | 偏度                             | m3、m6、y2、y1、y3、y5、total                      |
| tracking_error     | 跟踪误差                         | m3、m6、y2、y1、y3、y5、total                      |
| beta_downside      | 下行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| beta_upside        | 上行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| var                | VaR                              | m3、m6、y2、y1、y3、y5、total                      |
| alpha_a            | Alpha（年化）                    | m3、m6、y2、y1、y3、y5、total                      |
| alpha_tstats       | Alpha Tstat                      | m3、m6、y2、y1、y3、y5、total                      |
| beta               | Beta                             | m3、m6、y2、y1、y3、y5、total                      |
| sharpe_a           | Sharpe Ratio（年化）             | m3、m6、y2、y1、y3、y5、total                      |
| inf_a              | Information Ratio（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| sortino_a          | Sortino Ratio（年化）            | m3、m6、y2、y1、y3、y5、total                      |
| calmar_a           | Calmar Ratio                     | m3、m6、y2、y1、y3、y5、total                      |
| timing_ratio       | 择时比率                         | m3、m6、y2、y1、y3、y5、total                      |
| benchmark          | 指标计算基准/排名范围            | 无                                                 |

#### 范例 {#rqdata-API-fund-get_snapshot-example}

- 获取基金最新衍生指标值

```
In [95]: fund.get_snapshot('000001')
Out[95]:
                         benchmark  daily_benchmark_return  daily_excess  daily_excess_a  ...  y5_tracking_error    y5_var year_return  year_return_a
order_book_id datetime                                                                    ...
000001        2021-01-27   偏股型基金指数                     0.0     -0.009129       -2.300567  ...           0.062154 -0.016652    0.038263       0.691631

```

- 获取基金最新衍生指标值的排名

```
In [96]: fund.get_snapshot('000001',indicator_type='rank')
Out[96]:
                         benchmark daily_benchmark_return daily_excess daily_excess_a  ... y5_tracking_error  y5_var year_return year_return_a
order_book_id datetime                                                                 ...
000001        2021-01-27       偏股型                 1/1528    1382/1528      1382/1528  ...           508/521  47/521   1266/1507     1266/1507


```

### fund.get_indicators - 获取基金的衍生数据 {#rqdata-API-fund-get_indicator}

```python
fund.get_indicators(order_book_ids, start_date=None, end_date=None, fields=None, rule='ricequant', indicator_type='value', market='cn')
```

获取基金在时间范围内的衍生指标值或指标排名数据。例如可查询 alpha_a、beta、tracking_error 等指标，也包含指标计算基准或排名范围信息。

#### 参数 {#rqdata-API-fund-get_indicators-params}

| 参数           | 类型                                                     | 说明                                                                   |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | 基金代码                                                               |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期,                                                              |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期, start_date ,end_date 不传参数时默认返回所有数据              |
| fields         | _str_ or _list_                                          | 查询字段，可选字段见下方返回，默认返回所有字段                         |
| rule           | _str_                                                    | 指定算法，目前仅支持返回'ricequant'                                    |
| indicator_type | _str_                                                    | 指标类别，默认为 value <br /> value - 衍生指标值 ，rank - 衍生指标排名 |
| market         | _str_                                                    | 指定市场，目前仅有中国市场('cn')的基金衍生数据                         |

#### 返回 {#rqdata-API-fund-get_indicators-return}

_pandas DataFrame_

标准版涵盖的衍生指标及频率如下，字段的组成方式为 “支持的频率\_字段”, 如 “日度累计收益” 字段名为 'daily_return'，货币基金仅支持展示下面部分衍生指标数据。

| 字段               | 说明                             | 支持的频率                                         |
|-----|-----|-----|
| return             | 累计收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| return_a           | 累计收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| benchmark_return   | 基准收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess             | 超额收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess_a           | 超额收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess_win         | 超额胜率                         | m3、m6、y2、y1、y3、y5、total                      |
| stdev_a            | 波动率（年化）                   | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_avg_a | 下行波动率 - 均值（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_rf_a  | 下行波动率 - 无风险利率 （年化） | m3、m6、y2、y1、y3、y5、total                      |
| mdd                | 期间最大回撤                     | m3、m6、y2、y1、y3、y5、total                      |
| excess_mdd         | 期间超额收益最大回撤             | m3、m6、y2、y1、y3、y5、total                      |
| mdd_days           | 最大回撤持续期                   | m3、m6、y2、y1、y3、y5、total                      |
| recovery_days      | 最大回撤恢复期                   | m3、m6、y2、y1、y3、y5、total                      |
| max_drop           | 最大单日跌幅                     | m3、m6、y2、y1、y3、y5、total                      |
| max_drop_period    | 最大连跌期数                     | m3、m6、y2、y1、y3、y5、total                      |
| neg_return_ratio   | 亏损期占比                       | m3、m6、y2、y1、y3、y5、total                      |
| kurtosis           | 峰度                             | m3、m6、y2、y1、y3、y5、total                      |
| skewness           | 偏度                             | m3、m6、y2、y1、y3、y5、total                      |
| tracking_error     | 跟踪误差                         | m3、m6、y2、y1、y3、y5、total                      |
| var                | VaR                              | m3、m6、y2、y1、y3、y5、total                      |
| alpha_a            | Alpha（年化）                    | m3、m6、y2、y1、y3、y5、total                      |
| alpha_tstats       | Alpha Tstat                      | m3、m6、y2、y1、y3、y5、total                      |
| beta               | Beta                             | m3、m6、y2、y1、y3、y5、total                      |
| beta_downside      | 下行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| beta_upside        | 上行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| sharpe_a           | Sharpe Ratio（年化）             | m3、m6、y2、y1、y3、y5、total                      |
| inf_a              | Information Ratio（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| sortino_a          | Sortino Ratio（年化）            | m3、m6、y2、y1、y3、y5、total                      |
| calmar_a           | Calmar Ratio                     | m3、m6、y2、y1、y3、y5、total                      |
| timing_ratio       | 择时比率                         | m3、m6、y2、y1、y3、y5、total                      |
| benchmark          | 指标计算基准/排名范围            | 无                                                 |

#### 范例 {#rqdata-API-fund-get_indicators-example}

- 返回基金衍生指标值数据

```
In [98]: fund.get_indicators('000001',start_date=20200601,rule='ricequant',indicator_type='value',fields=['m3_alpha_a','m6_beta','benchmark'])
Out[98]:
                          m3_alpha_a   m6_beta benchmark
order_book_id datetime
000001        2020-06-01   -0.017309  0.897002   偏股型基金指数
              2020-06-02   -0.032750  0.897575   偏股型基金指数
              2020-06-03   -0.036943  0.897945   偏股型基金指数
              2020-06-04   -0.061339  0.897735   偏股型基金指数
              2020-06-05   -0.072694  0.895500   偏股型基金指数
...                              ...       ...       ...
              2021-01-21   -0.544216  0.905062   偏股型基金指数
              2021-01-22   -0.492470  0.914805   偏股型基金指数
              2021-01-25   -0.419185  0.924407   偏股型基金指数
              2021-01-26   -0.431358  0.922676   偏股型基金指数
              2021-01-27   -0.455787  0.923730   偏股型基金指数

```

- 返回基金衍生指标排名数据

```
In [99]: fund.get_indicators('000001',start_date=20200601,rule='ricequant',indicator_type='rank',fields=['m3_alpha_a','m6_beta','benchmark'])
Out[99]:
                         m3_alpha_a   m6_beta benchmark
order_book_id datetime
000001        2020-06-01   555/1116  746/1015       偏股型
              2020-06-02   590/1116  749/1015       偏股型
              2020-06-03   601/1117  749/1015       偏股型
              2020-06-04   648/1117  749/1018       偏股型
              2020-06-05   691/1120  753/1018       偏股型
...                             ...       ...       ...
              2021-01-21  1446/1475  921/1273       偏股型
              2021-01-22  1425/1471  898/1277       偏股型
              2021-01-25  1403/1475  897/1308       偏股型
              2021-01-26  1351/1423  897/1259       偏股型
              2021-01-27  1359/1415  893/1251       偏股型

```

### fund.get_related_code - 获取分级基金的分级关系 {#rqdata-API-fund-get_related_code}

```python
fund.get_related_code(order_book_ids, market='cn')
```

获取分级基金相关代码关系数据。例如包括同一基金分级关系、母子基金分级关系，以及同一基金不同货币关系（QDII）。

#### 参数 {#rqdata-API-fund-get_related_code-params}

| 参数           | 类型            | 说明                                           |
|-----|-----|-----|
| order_book_ids | _str_ or _list_ | **必填参数**，基金代码                         |
| market         | _str_           | 指定市场，目前仅有中国市场('cn')的分级基金数据 |

#### 返回 {#rqdata-API-fund-get_related_code-return}

_pandas DataFrame_

| 字段           | 类型              | 说明                                                                                                                                    |
|-----|-----|-----|
| main_code      | _str_             | 平级关系或母子关系的主代码                                                                                                              |
| related_code   | _str_             | 平级关系或母子关系的次代码                                                                                                              |
| type           | _str_             | 分级基金关系：<br />同一基金分级关系 - multi_share， 母子基金分级关系 - parent_and_child， 同一基金不同货币关系（QDII）- multi_currency |
| effective_date | _pandas.Timestamp_ | 该条记录的有效起始日                                                                                                                    |
| cancel_date    | _pandas.Timestamp_ | 该条记录的失效日                                                                                                                        |

#### 范例 {#rqdata-API-fund-get_related_code-example}

```
In [23]: fund.get_related_code(['000003','000004','005929','160513'])
Out[23]:
  main_code related_code              type effective_date cancel_date
0    000003       000004       multi_share     2013-02-20         NaT
1    005929       005930       multi_share     2018-10-12  2019-01-16
2    160513       160514       multi_share     2014-06-10         NaT
3    160513       160514  parent_and_child     2011-05-20  2014-06-10
4    160513       150043  parent_and_child     2011-05-20  2014-06-10
```

### fund.get_daily_units - 获取基金的日度份额数据 {#rqdata-API-fund-get_daily_units}

```python
fund.get_daily_units(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取基金日度份额数据，即各日期对应的期末总份额。

#### 参数 {#rqdata-API-fund-get_daily_units-params}

| 参数           | 类型                                                     | 说明                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | **必填参数**，基金代码                                    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_daily_units-return}

_pandas DataFrame_

| 字段  | 类型    | 说明                   |
|------ |--------|-----|
| units | _float_ | 期末总份额（单位：份） |
| size  | _float_ | 基金规模              |

#### 范例 {#rqdata-API-fund-get_daily_units-example}

```
In [23]: fund.get_daily_units('159001',20260415,20260430)
Out[23]:
                          units	       size
order_book_id	datetime		
159001	      2026-04-15	17065207.0	1.706521e+09
              2026-04-16	17059665.0	1.705966e+09
              2026-04-17	20126158.0	2.012616e+09
              2026-04-20	18126201.0	1.812620e+09
              2026-04-21	16915819.0	1.691582e+09
              2026-04-22	16911252.0	1.691125e+09
              2026-04-23	17326860.0	1.732686e+09
              2026-04-24	20705043.0	2.070504e+09
              2026-04-27	18713202.0	1.871320e+09
              2026-04-28	18530708.0	1.853071e+09
              2026-04-29	23457080.0	2.345708e+09
              2026-04-30	22929284.0	2.292928e+09

```

## 基金持仓与配置信息数据 {#rqdata-API-fund-holdings}

### fund.get_holdings - 获取基金持仓信息 {#rqdata-API-fund-get_holdings}

```python
fund.get_holdings(order_book_ids, date=None, market='cn')
```

获取基金持仓数据，支持从指定日期回溯最近披露期或查询全部日期。例如可获取股票、债券、基金等持仓，也区分 AShare、Hshare、ConvertibleBond 等类别。

#### 参数 {#rqdata-API-fund-get_holdings-params}

| 参数           | 类型                                                           | 说明                                                                                 |
|-----|-----|-----|
| order_book_ids | _str or list_                                                  | **必填参数**，基金合约代码                                                           |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的持仓数据。如不指定日期，则获取所有日期的持仓数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_holdings-return}

_pandas DataFrame_

| 字段          | 类型              | 说明                                                                                                               |
|-----|-----|-----|
| order_book_id | _str_             | 持仓合约代码，如股票持仓、债券持仓等合约代码                                                                       |
| weight        | _float_           | 持仓百分比                                                                                                         |
| date          | _pandas.Timestamp_ | 报告期                                                                                                             |
| release_date  | _pandas.Timestamp_ | 公告发布日                                                                                                         |
| shares        | _float_           | 持仓股数（如股票单位：1 股，债券为 NaN）                                                                           |
| market_value  | _float_           | 持仓市值（单位：元，债券为 NaN）                                                                                   |
| symbol        | _str_             | 持仓简称                                                                                                           |
| type          | _str_             | 持仓资产类别大类，股票 - `Stock`，债券 - `Bond`，基金 - `Fund`，权证 - `Warrant`, 期权 - `Futures`，其他 - `Other` |
| category      | _str_             | 持仓资产类别细类 （如：category='Hshare'港股，category='Ashare'A 股均属于 type='Stock' ）                          |

#### 范例 {#rqdata-API-fund-get_holdings-example}

```
In [171]: fund.get_holdings('000001',20190930)
Out[171]:
                   order_book_id  weight      shares  ...   type         category       symbol
fund_id date                                          ...
000001  2019-09-30  101564021.IB  0.0221   1000000.0  ...   Bond    CorporateBond  15华能集MTN002
        2019-09-30   128016.XSHE  0.0001      4172.0  ...   Bond  ConvertibleBond         雨虹转债
        2019-09-30   128022.XSHE  0.0001      6248.0  ...   Bond  ConvertibleBond         众信转债
        2019-09-30   128046.XSHE  0.0013     59048.0  ...   Bond  ConvertibleBond         利尔转债
        2019-09-30     180208.IB  0.0333   1500000.0  ...   Bond    FinancialBond       18国开08
        2019-09-30     180409.IB  0.0290   1300000.0  ...   Bond    FinancialBond       18农发09
        2019-09-30     190201.IB  0.0219   1000000.0  ...   Bond    FinancialBond       19国开01
        2019-09-30     190303.IB  0.0218   1000000.0  ...   Bond    FinancialBond       19进出03
        2019-09-30   000858.XSHE  0.0428   1509443.0  ...  Stock           AShare        五 粮 液
        2019-09-30   002127.XSHE  0.0309  13733457.0  ...  Stock           AShare         南极电商
        2019-09-30   002384.XSHE  0.0369   8571900.0  ...  Stock           AShare         东山精密

```

### fund.get_stock_change - 获取基金报告期内重大股票持仓变动情况 {#rqdata-API-fund-get_stock_change}

```python
fund.get_stock_change(order_book_ids,start_date=None,end_date=None, market='cn')
```

获取基金报告期内重大股票持仓变动数据，包括买入和卖出股票的持仓市值、持仓百分比和变动类型。

#### 参数 {#rqdata-API-fund-get_stock_change-params}

| 参数           | 类型                                                           | 说明                               |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | 基金代码                           |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的开始日期，默认为最新一期数据 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的结束日期，默认为最新一期数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_stock_change-return}

_pandas DataFrame_

| 字段          | 类型              | 说明                     |
|-----|-----|-----|
| order_book_id | _str_             | 股票合约代码             |
| date          | _pandas.Timestamp_ | 持仓披露日期             |
| weight        | _float_           | 持仓百分比               |
| market_value  | _float_           | 持仓市值                 |
| change_type   | _str_             | 变动类型。1-买入，2-卖出 |

#### 范例 {#rqdata-API-fund-get_stock_change-example}

```
In [19]: fund.get_stock_change('519933','20190101','20191001')
Out[19]:
           order_book_id  market_value  weight  change_type
date
2019-06-30   000921.XSHE     361296.00  0.0497            2
2019-06-30   601288.XSHG     744548.00  0.1025            2
2019-06-30   600660.XSHG     194344.00  0.0267            2
2019-06-30   601398.XSHG     601000.00  0.0827            1
2019-06-30   600519.XSHG     852090.00  0.1173            1
2019-06-30   600004.XSHG    1005822.00  0.1384            2
···
2019-06-30   002025.XSHE     493102.00  0.0679            1
2019-06-30   601398.XSHG     575489.00  0.0792            2
2019-06-30   600519.XSHG     853209.00  0.1174            2
2019-06-30   603589.XSHG     465176.00  0.0640            2
```

### fund.get_term_to_maturity - 获取货币型基金持仓期限数据 {#rqdata-API-fund-get_term_to_maturity}

```python
fund.get_term_to_maturity(order_book_ids,start_date=None,end_date=None, market='cn')
```

获取货币型基金持仓期限分布数据。例如包括 `0_30`、`30_60`、`60_90`、`90_120`、`120_397` 等剩余期限范围。

#### 参数 {#rqdata-API-fund-get_term_to_maturity-params}

| 参数           | 类型                                                           | 说明                               |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码             |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的开始日期，默认为最新一期数据 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询的结束日期，默认为最新一期数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_term_to_maturity-return}

_pandas DataFrame_

| 字段   | 类型              | 说明                   |
|-----|-----|-----|
| date   | _pandas.Timestamp_ | 报告期                 |
| term   | _str_             | 剩余期限范围           |
| weight | _float_           | 剩余期限占资产净值比例 |

#### 范例 {#rqdata-API-fund-get_term_to_maturity-example}

```
In [18]: fund.get_term_to_maturity('050003','20190101','20191120')
Out[18]:
               term  weight
date
2019-03-31     0_30  0.5013
2019-03-31    30_60  0.1077
2019-03-31    60_90  0.1419
2019-03-31   90_120  0.0624
2019-03-31  120_397  0.2090
2019-06-30     0_30  0.4116
2019-06-30    30_60  0.0749
2019-06-30    60_90  0.2211
2019-06-30   90_120  0.0781
2019-06-30  120_397  0.2123
2019-09-30     0_30  0.3682
2019-09-30    30_60  0.1786
2019-09-30    60_90  0.1537
2019-09-30   90_120  0.0647
2019-09-30  120_397  0.2454
```

### fund.get_bond_structure - 获取基金持仓中债券组合结构信息 {#rqdata-API-fund-get_bond_structure}

```python
fund.get_bond_structure(order_book_ids, date=None, market='cn')
```

获取基金债券组合结构数据，支持从指定日期回溯最近披露期或查询全部日期。例如可获取国债、金融债、企业债、可转换债、中期票据等债券类型的结构信息。

#### 参数 {#rqdata-API-fund-get_bond_structure-params}

| 参数           | 类型                                                           | 说明                                                                                                 |
|-----|-----|-----|
| order_book_ids | _str or list_                                                  | **必填参数**，基金代码                                                                               |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的债券组合结构数据。如不指定日期，则获取所有日期的债券组合结构数据 |
| market         | _str_                                                          | 指定市场，目前仅有中国市场('cn')的基金数据                                                           |

#### 返回 {#rqdata-API-fund-get_bond_structure-return}

_pandas DataFrame_

| 字段           | 类型              | 说明                                                                                                                                                                                                                                                                                                        |
|-----|-----|-----|
| order_book_id  | _str_             | 基金合约代码                                                                                                                                                                                                                                                                                                |
| date           | _pandas.Timestamp_ | 持仓披露日期                                                                                                                                                                                                                                                                                                |
| bond_type      | _str_             | 债券种类：国债 - `government`，金融债券 - `financial`，企业债券 - `corporate`，可转换债券 - `convertible`，央行票据 - `bank_notes`，短期融资券 - `short_financing`，中期票据 - `medium_notes`，同业存单 - `ncd`，中小企业私募债 - `s_m_private`，地方政府债券 - `local_government`，其他债券 - `other_bond` |
| weight_nv      | _float_           | 持仓占资产净值百分比                                                                                                                                                                                                                                                                                        |
| weight_bond_mv | _float_           | 持仓占债券组合市值百分比                                                                                                                                                                                                                                                                                    |
| market_value   | _float_           | 持仓市值（单位：元）                                                                                                                                                                                                                                                                                        |

#### 范例 {#rqdata-API-fund-get_bond_structure-example}

```
In [28]: fund.get_bond_structure(['000014','000005'],20200630)
Out[28]:
                             bond_type  weight_nv  weight_bond_mv  market_value
order_book_id date
000005        2020-06-30     financial     0.2370        0.183999   13469400.00
              2020-06-30   convertible     0.0347        0.026921    1970729.00
              2020-06-30     corporate     0.3668        0.284768   20846100.00
              2020-06-30  medium_notes     0.6495        0.504312   36917600.00
000014        2020-06-30    government     0.1423        0.127257   14705500.00
              2020-06-30   convertible     0.7407        0.662522   76559552.12
              2020-06-30     corporate     0.2350        0.210221   24292667.20

```

### fund.get_asset_allocation - 获取基金资产配置 {#rqdata-API-fund-get_asset_allocation}

```python
fund.get_asset_allocation(order_book_ids, date=None, market='cn')
```

获取基金资产配置数据，例如股票、债券、现金、其他资产占净资产比例，以及净资产和总资产等信息。

#### 参数 {#rqdata-API-fund-get_asset_allocation-params}

| 参数           | 类型                                                           | 说明                                                                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                                                                    |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，查询日期和报告期去比较,回溯获取距离指定日期最近的报告期数据。如不指定日期，则获取所有日期的数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_asset_allocation-return}

_pandas DataFrame_

| 字段        | 类型              | 说明                                                                                        |
|-----|-----|-----|
| datetime    | _pandas.Timestamp_ | 报告期                                                                                      |
| info_date   | _pandas.Timestamp_ | 公告发布日                                                                                  |
| stock       | _float_           | 股票占净资产比例                                                                            |
| bond        | _float_           | 债券占净资产比例（由于债券通过质押式回购进行融资杠杆交易的存在，债券占比数值可能超过 100%） |
| cash        | _float_           | 现金占净资产比例                                                                            |
| other       | _float_           | 其他资产占净资产比例                                                                        |
| nav         | _float_           | 基金净资产（单位：元）（该字段即将被废弃，被 net_asset 替代）                               |
| net_asset： | _float_           | 基金净资产（单位：元）                                                                      |
| total_asset | _float_           | 基金总资产（单位：元）                                                                      |

#### 范例 {#rqdata-API-fund-get_asset_allocation-example}

```
In [12]: fund.get_asset_allocation('000058',date='20201231')
Out [12]
                  info_date   stock     bond   fund cash other nav net_asset total_asset
order_book_id datetime
000058       2020-12-31 2021-01-22 0.311344 0.6614 NaN 0.013306 0.015539 6.928471e+08 6.928471e+08 693971161.4
```

### fund.get_industry_allocation - 获取基金权益类持仓行业配置 {#rqdata-API-fund-get_industry_allocation}

```python
fund.get_industry_allocation(order_book_ids, date=None, market='cn')
```

获取基金权益类持仓行业配置数据，支持多种行业划分标准。例如可按 CSRC、GICS、MSCI、Bloomberg、CSRC_2012、Gildata 查询金融业、制造业、房地产业等行业配置。

#### 参数 {#rqdata-API-fund-get_industry_allocation-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                                | **必填参数**，基金代码                                                       |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，回溯获取距离指定日期最近的数据。如不指定日期，则获取所有日期的数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_industry_allocation-return}

_pandas DataFrame_

| 字段         | 类型              | 说明                                                                                                                                                                                                              |
|-----|-----|-----|
| datetime     | _pandas.Timestamp_ | 报告期                                                                                                                                                                                                            |
| standard     | _str_             | 行业划分标准 <br /> `CSRC` - CSRC 行业分类, `GICS` - GICS 行业分类， `MSCI` - MSCI 行业分类， `Bloomberg` - Bloomberg 行业分类， `CSRC_2012` - 证监会行业分类 2012 版， `Gildata` - 聚合行业分类（QDII 基金专用） |
| industry     | _str_             | 行业名称                                                                                                                                                                                                          |
| weight       | _float_           | 行业占比                                                                                                                                                                                                          |
| market_value | _float_           | 现持仓市值（单位：元）                                                                                                                                                                                            |

#### 范例 {#rqdata-API-fund-get_industry_allocation-example}

- 获取 00001 基金的权益类持仓行业配置

```
In [55]: fund.get_industry_allocation('000001',date='20200630')
Out[55]:
                           standard          industry  weight  market_value
order_book_id datetime
000001        2020-06-30  CSRC_2012               金融业  0.0003  1.702350e+06
              2020-06-30  CSRC_2012               采矿业  0.0622  3.145813e+08
              2020-06-30  CSRC_2012                综合  0.0009  4.671139e+06
              2020-06-30  CSRC_2012          租赁和商务服务业  0.0954  4.821860e+08
              2020-06-30  CSRC_2012        科学研究和技术服务业  0.0244  1.231741e+08
              2020-06-30  CSRC_2012  电力、热力、燃气及水生产和供应业  0.0218  1.103732e+08
              2020-06-30  CSRC_2012     水利、环境和公共设施管理业  0.0002  1.167722e+06
              2020-06-30  CSRC_2012         文化、体育和娱乐业  0.0017  8.767187e+06
              2020-06-30  CSRC_2012            批发和零售业  0.0020  9.917138e+06
              2020-06-30  CSRC_2012              房地产业  0.0039  1.968217e+07
              2020-06-30  CSRC_2012               建筑业  0.0000  6.025800e+02
              2020-06-30  CSRC_2012               制造业  0.4653  2.352107e+09
              2020-06-30  CSRC_2012   信息传输、软件和信息技术服务业  0.0979  4.949599e+08

```

### fund.get_qdii_scope - 获取 QDII 地区配置 {#rqdata-API-fund-get_qdii_scope}

```python
fund.get_qdii_scope(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取 QDII 基金地区配置数据，包括各地区的持仓市值和占净资产比例。例如可获取中国香港等地区配置数据。

#### 参数 {#rqdata-API-fund-get_qdii_scope-params}

| 参数           | 类型                                                     | 说明                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | **必填参数**，基金代码                                    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_qdii_scope-return}

_pandas DataFrame_

| 字段         | 类型              | 说明         |
|-----|-----|-----|
| date         | _pandas.Timestamp_ | 报告期       |
| region       | _str_             | 地区         |
| market_value | _float_           | 市值(元)     |
| weight       | _float_           | 占净资产比列 |

#### 范例 {#rqdata-API-fund-get_qdii_scope-example}

```
In [10]: fund.get_qdii_scope('183001','20190101','20200101')
Out[10]:   region market_value weight
order_book_id date
183001 2019-03-31 中国香港 12540825.98 20.00
2019-06-30 中国香港 13108299.05 20.50
2019-09-30 中国香港 12177202.64 18.99
2019-12-31 中国香港 9065869.58 13.94

```

### fund.get_instrument_category - 获取基金的风格分类数据 {#rqdata-API-fund-get_instrument_category}

```python
fund.get_instrument_category(order_book_ids,date=None,category_type=None,source='gildata',market='cn')
```

获取基金风格分类数据，支持按分类类型查询。例如包括 `value`、`size`、`operating_style`、`duration`、`bond_type`、`fund_type` 等分类，也支持 `concept`、`industry_citics`、`universe` 等分类数据。

#### 参数 {#rqdata-API-fund-get_instrument_category-params}

| 参数           | 说明                                                     | 说明                                                                                                                                                                                                      |
|-----|-----|-----|
| order_book_ids | _str_ or _list_                                          | **必填参数**，基金代码                                                                                                                                                                                    |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 日期，默认为最新                                                                                                                                                                                          |
| category_type  | _str_ or _list_                                          | 分类类型，可传入 list ,默认返回以下分类：<br/>value - 价值风格<br/>size - 规模风格<br/>operating_style - 操作风格 <br/> duration - 久期分布 <br/> bond_type - 券种配置 <br/> **其他枚举值见下方完整表格** |
| source         | _str_                                                    | 分类来源，目前仅支持 'gildata' 聚源分类                                                                                                                                                                   |
| market         | _str_                                                    | 指定市场，目前仅支持中国市场('cn')的基金数据                                                                                                                                                              |

::: tip 参数字段说明

| category_type 枚举值 | 说明                 | 备注                                                                                                                  |
|-----|-----|-----|
| value                | 价值风格             |                                                                                                                       |
| size                 | 规模风格             |                                                                                                                       |
| operating_style      | 操作风格             |                                                                                                                       |
| duration             | 久期分布             |                                                                                                                       |
| bond_type            | 券种配置             |                                                                                                                       |
| fund_type            | 基金分类（聚源）     | 该分类数据返回结构与其他不同，**需要单独调取**                                                                        |
| concept              | 概念板块             |                                                                                                                       |
| industry_citics      | 行业分类（中信一级） |                                                                                                                       |
| investment_style     | 投资风格分类         |                                                                                                                       |
| structured_fund      | 分级基金标识         |                                                                                                                       |
| universe             | 基金属性             | 返回值参照：`close_end` - 封闭型基金，`open_end` - 开放型基金，`fund_of_etf` - ETF 联接基金，`lof` - LOF，`etf` - ETF |

:::

#### 返回 {#rqdata-API-fund-get_instrument_category-return}

_pandas DataFrame_

| 字段             | 类型  | 说明                                             |
|-----|-----|-----|
| category_type    | _str_ | 分类类型                                         |
| category_index   | _str_ | 基金细分分类指数代码                             |
| category         | _str_ | 基金细分分类名称                                 |
| first_type_code  | _str_ | 一级分类代码 （仅限 category_type='fund_type' ） |
| first_type       | _str_ | 一级分类名称 （仅限 category_type='fund_type' ） |
| second_type_code | _str_ | 二级分类代码 （仅限 category_type='fund_type' ） |
| second_type      | _str_ | 二级分类名称 （仅限 category_type='fund_type' ） |
| third_type_code  | _str_ | 三级分类代码 （仅限 category_type='fund_type' ） |
| third_type       | _str_ | 三级分类名称 （仅限 category_type='fund_type' ） |

#### 范例 {#rqdata-API-fund-get_instrument_category-example}

- 不指定 category_type，获取 000001 默认分类类型数据

```
In [8]: fund.get_instrument_category('000001')
Out[8]:
                               category  category_index
order_book_id category_type
000001        value               blend         1014002
              operating_style  flexible         1015003
              size              mid_cap         1013002

```

- 指定获取基金的基金属性、概念板块

```
In [12]: fund.get_instrument_category('000001',category_type=['universe','concept'])
Out[12]:
                                   category_index	  category
order_book_id	category_type
00001	        size	           1013002	          mid_cap
                operating_style	   1015003	          flexible
                investment_style   None	              None
                concept	           1010054	          MSCI概念
                universe	       None	              open_end
                concept	           1010027	          机器人概念
                value	           1014003	          value
                industry_citics	   1012028	          国防军工
```

- 获取多个基金的聚源分类数据

```
In [14]: fund.get_instrument_category(['000001','000014'],category_type='fund_type')
Out[14]:
                             first_type_code first_type  second_type_code second_type  third_type_code third_type
order_book_id category_type
000001        fund_type                   12        混合型              1201         偏股型           120101        偏股型
000014        fund_type                   13        债券型              1302       普通债券型           130201  普通债券型(一级)
```

### fund.get_category - 获取风格分类所属基金列表 {#rqdata-API-fund-get_category}

```python
fund.get_category(category, date=None, source='gildata', market='cn')
```

获取指定风格分类条件对应的基金列表，支持同时按多个 `category_type` 和 `category` 组合查询。例如可按 `concept`、`size`、`operating_style` 等分类条件筛选基金。

#### 参数 {#rqdata-API-fund-get_category-params}

| 参数     | 类型                                                     | 说明                                                                                                                                                    |
|-----|-----|-----|
| category | _dict_                                                   | 以 dict 的形式输入：支持输入多个 category_type、category。<br />结构为{"category_type":["category"],"category_type":["category"]} ,可参考范例帮助理解。 |
| date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 默认最新日期                                                                                                                                            |
| source   | _str_             | 分类来源，目前仅支持 'gildata' 聚源分类        |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_category-return}

_order_book_id list_

#### 范例 {#rqdata-API-fund-get_category-example}

- 传入类别名称和名称查询列表

```
In [8]: fund.get_category(category={"concept": ["人工智能","MSCI概念"], "size": "large","operating_style":"flexible"})
Out[8]:
['040001',
 '202005',
 '270021',
···
 '006573',
 '006574',
 '005029']
```

### fund.get_category_mapping - 获取风格分类清单 {#rqdata-API-fund-get_category_mapping}

```python
fund.get_category_mapping(source='gildata',category_type=None, market='cn')
```

获取基金风格分类清单，支持返回 `value`、`size`、`operating_style`、`duration`、`bond_type` 等分类，也支持 `fund_type` 的一级、二级、三级分类映射。

#### 参数 {#rqdata-API-fund-get_category_mapping-params}

| 参数          | 类型  | 说明                                                                                                                |
|-----|-----|-----|
| source        | _str_ | 分类来源，目前仅支持 'gildata' 聚源分类                                                                             |
| category_type | _str_ | 默认返回除 fund_type 以外的风格，可选字段见 [category_type 枚举值](#rqdata-API-fund-get_instrument_category-params) |

#### 返回 {#rqdata-API-fund-get_category_mapping-return}

_pandas DataFrame_

| 字段             | 类型  | 说明                                             |
|-----|-----|-----|
| category_type    | _str_ | 分类类型                                         |
| category_index   | _str_ | 基金细分分类指数代码                             |
| category         | _str_ | 基金细分分类名称                                 |
| first_type_code  | _str_ | 一级分类代码 （仅限 category_type='fund_type' ） |
| first_type       | _str_ | 一级分类名称 （仅限 category_type='fund_type' ） |
| second_type_code | _str_ | 二级分类代码 （仅限 category_type='fund_type' ） |
| second_type      | _str_ | 二级分类名称 （仅限 category_type='fund_type' ） |
| third_type_code  | _str_ | 三级分类代码 （仅限 category_type='fund_type' ） |
| third_type       | _str_ | 三级分类名称 （仅限 category_type='fund_type' ） |

::: tip 返回字段说明

| category_type 中文 | category_type 英文 | category 中文 | category 英文      | 股债偏重   |
|-----|-----|-----|-----|-----|
| 价值风格           | value              | 成长          | growth             | 偏股型基金 |
| 价值风格           | value              | 价值          | value              | 偏股型基金 |
| 价值风格           | value              | 平衡          | blend              | 偏股型基金 |
| 规模风格           | size               | 大盘          | large              | 偏股型基金 |
| 规模风格           | size               | 小盘          | small              | 偏股型基金 |
| 规模风格           | size               | 中盘          | mid_cap            | 偏股型基金 |
| 操作风格           | operating_style    | 激进操作      | aggressive         | 偏股型基金 |
| 操作风格           | operating_style    | 灵活操作      | flexible           | 偏股型基金 |
| 操作风格           | operating_style    | 平均操作      | balanced           | 偏股型基金 |
| 操作风格           | operating_style    | 稳健操作      | moderate           | 偏股型基金 |
| 操作风格           | operating_style    | 积极操作      | active             | 偏股型基金 |
| 久期分布           | duration           | 1 年(含)以下  | 1_year             | 偏债型基金 |
| 久期分布           | duration           | 1-3 年(含)    | 1_to_3_years       | 偏债型基金 |
| 久期分布           | duration           | 3-5 年(含)    | 3_to_5_years       | 偏债型基金 |
| 久期分布           | duration           | 5 年以上      | 5_years            | 偏债型基金 |
| 券种配置           | bond_type          | 可转债        | convertible_bond   | 偏债型基金 |
| 券种配置           | bond_type          | 利率债        | interest_rate_bond | 偏债型基金 |
| 券种配置           | bond_type          | 信用债        | credit_bond        | 偏债型基金 |

:::

#### 范例 {#rqdata-API-fund-get_category_mapping-example}

- 获取除 fund_type 以外的风格分类清单

```
In [17]: fund.get_category_mapping()
Out[17]:
                         category category_index
category_type
structured_fund   structured_fund           None
universe              fund_of_etf           None
universe                      lof           None
universe                close_end           None
concept                      一带一路        1010005
...                           ...            ...
duration                   1_year        1111001
industry_citics              基础化工        1012022
industry_citics                建材        1012024
investment_style              其他型           None
concept                      北斗导航        1010025

[155 rows x 2 columns]
```

- 获取 fund_type 聚源分类的风格清单

```
In [17]: fund.get_category_mapping(category_type='fund_type')
Out[17]:
                first_type_code	first_type	second_type_code	second_type	third_type_code	third_type
category_type
fund_type	      13	债券型	1305	同业存单型	130501	同业存单型
fund_type	      99	其他	9903	MOM	990302	MOM灵活配置型
fund_type	      18	FOF	1802	债券型FOF	180201	债券型FOF
fund_type	      15	QDII	1503	QDII混合型	150303	QDII平衡混合型
fund_type	      15	QDII	1502	QDII股票型	150204	QDII增强指数股票型
...	...	...	...	...	...	...
fund_type	      18	FOF	1801	股票型FOF	180101	股票型FOF
fund_type	      13	债券型	1304	指数债券型	130401	标准指数债券型
fund_type	      15	QDII	1504	QDII商品型	150499	QDII其他商品型
fund_type	      99	其他	9903	MOM	990303	MOM股债平衡型
fund_type	      17	REITs	1701	基础设施基金REITs	170101	产权REITs
53 rows × 6 columns
```

## 基金管理人信息，以及衍生数据 {#rqdata-API-fund-manager_and_derive}

### fund.get_manager - 获取指定基金的基金经理管理信息 {#rqdata-API-fund-get_manager}

```python
fund.get_manager(order_book_ids,expect_df=True, market='cn')
```

获取指定基金的基金经理管理信息，包括基金经理姓名、管理起止日期、累计管理天数、任职回报和职位等数据。

#### 参数 {#rqdata-API-fund-get_manager-params}

| 参数           | 类型                | 说明                                                                   |
|-----|-----|-----|
| order_book_ids | _str_ or _str list_ | **必填参数**，基金代码                                                 |
| expect_df      | _boolean_           | 默认为True，返回 pandas dataframe。若调为 False，则返回原有的数据结构  |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_manager-return}

_pandas DataFrame_

| 字段       | 类型              | 说明                                               |
|-----|-----|-----|
| name       | _str_             | 基金经理名称                                       |
| id         | _str_             | 基金经理代码                                       |
| days       | _int_             | 基金经理管理当前基金累计天数                       |
| start_date | _pandas.Timestamp_ | 基金经理开始管理当前基金的日期                     |
| end_date   | _pandas.Timestamp_ | 基金经理结束管理当前基金的日期（NaT 代表任职至今） |
| return     | _float_           | 基金经理任职回报                                   |
| title      | _str_             | 职位                                               |

#### 范例 {#rqdata-API-fund-get_manager-example}

- 获取单只基金的基金经理管理信息

```
In [47]: fund.get_manager('000001')
Out[47]:
 name days start_date end_date return title
id
101000229 王亚伟 1211 2001-12-18 2005-04-12 0.133084 基金经理
101000228 田擎 605 2002-07-01 2004-02-26 0.110716 基金经理助理
101002472 乔巍 730 2002-07-01 2004-06-30 0.007694 基金经理助理
101000228 田擎 610 2004-02-27 2005-10-29 -0.151132 基金经理
101000595 巩怀志 1540 2005-10-29 2010-01-16 3.922946 基金经理
101000348 童汀 1616 2010-01-16 2014-06-20 -0.077224 基金经理
101001854 孙振峰 449 2012-04-05 2013-06-28 0.119477 基金经理
101000866 倪邈 612 2014-03-17 2015-11-19 0.469314 基金经理
101001125 李铧汶 1033 2014-03-17 2017-01-13 0.130557 基金经理
101000925 崔同魁 201 2014-06-20 2015-01-07 0.244463 基金经理
101001090 董阳阳 2238 2015-01-07 2021-02-22 0.501579 基金经理
101002061 许利明 574 2015-09-01 2017-03-28 -0.098604 基金经理
101001669 孙萌 463 2015-11-19 2017-02-24 -0.173107 基金经理
101001757 阳琨 149 2021-02-22 NaT         -0.039810 基金经理

```

- 获取基金列表的基金经理管理信息

```
In [50]: fund.get_manager(['160224', '217019'])
Out[50]:
                         days   end_date name    return start_date title
order_book_id id
160224        101002093  1879        NaT  艾小军 -0.119662 2015-03-26  基金经理
217019        101001928  2027 2017-01-13   王平  0.345410 2011-06-27  基金经理
              101001014  1624 2017-07-01   罗毅  0.833497 2013-01-19  基金经理
              101004652  1220        NaT  苏燕青  0.215929 2017-01-13  基金经理
              101012888   607 2020-01-02  刘重杰  0.073923 2018-05-05  基金经理
```

### fund.get_manager_info - 获取基金经理背景信息 {#rqdata-API-fund-get_manager_info}

```python
fund.get_manager_info(manager_id,fields=None, market='cn')
```

获取基金经理背景信息，例如性别、出生地、学历、执业开始时间、执业年限和个人简介。

#### 参数 {#rqdata-API-fund-get_manager_info-params}

| 参数       | 类型            | 说明                                                           |
|-----|-----|-----|
| manager_id | _str_ or _list_ | **必填参数**，可传入基金经理 id 或名字。名字与 id 不能同时传入 |
| fields     | _str_ or _list_ | 对应返回字段，默认为所有字段                                   |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-fund-get_manager_info-return}

_pandas DataFrame_

| 字段            | 类型              | 说明         |
|-----|-----|-----|
| id              | _str_             | 基金经理代码 |
| name            | _str_             | 基金经理名称 |
| gender          | _str_             | 性别         |
| region          | _str_             | 出生地       |
| birthdate       | _pandas.Timestamp_ | 生日         |
| education       | _str_             | 学历         |
| practice_date   | _pandas.Timestamp_ | 执业开始时间 |
| experience_time | _float_           | 执业年限     |
| background      | _str_             | 个人简介     |

#### 范例 {#rqdata-API-fund-get_manager_info-example}

- 获取单个基金经理背景信息

```
In [11]: fund.get_manager_info('101002094',fields=None)
Out[11]:
                  chinesename gender region birthdate education practice_date  experience_time                                         background
id
101002094          胡剑      男     中国      None        硕士    2006-01-01             12.8      胡剑先生，经济学硕士。曾任易方达基金管理有限公 司固定收益部债券研究员、基金经理助理兼...


```

- 获取多个基金经理背景信息

```
In [10]: fund.get_manager_info(['101002094','101010264'],fields=None)
Out [10]:
              chinesename gender region birthdate education practice_date  experience_time                                         background
id
101002094          胡剑      男     中国      None        硕士    2006-01-01             12.8      胡剑先生，经济学硕士。曾任易方达基金管理有限公 司固定收益部债券研究员、基金经理助理兼...
101010264          刘杰   None   None      None        硕士    2010-01-01              8.8                                               核心人员
```

### fund.get_manager_indicators - 获取基金经理人的衍生数据 {#rqdata-API-fund-get_manager_indicators}

```python
fund.get_manager_indicators(manager_ids, start_date=None, end_date=None, fields=None, asset_type='stock', manage_type='all', rule='ricequant', market='cn')
```

获取基金经理衍生指标数据，支持按股票型或债券型、独立管理或全部参与管理进行查询。例如可获取累计收益率、超额收益率、最大回撤、Sharpe Ratio（年化）等指标。

#### 参数 {#rqdata-API-fund-get_manager_indicators-params}

| 参数        | 类型                                                     | 说明                                                                   |
|-----|-----|-----|
| manager_ids | _str_ or _list_                                          | **必填参数**，基金经理代码，建议结合 fund.get_manager_info 一起使用    |
| start_date  | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                               |
| end_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期, start_date ,end_date 不传参数时默认返回所有数据              |
| fields      | _str_ or _list_                                          | 查询字段，可选字段见下方返回，默认返回所有字段                         |
| asset_type  | _str_                                                    | 在管基金类型，默认为 stock <br /> stock - 股票型，bond - 债券型        |
| manage_type | _str_                                                    | 管理方式，默认为 all <br /> independent - 独立管理，all - 所有参与管理 |
| rule        | _str_                                                    | 指定算法，目前仅支持算法 ricequant                                     |
| market      | _str_                                                    | 指定市场，目前仅有中国市场('cn')的基金经理人衍生数据                   |

#### 返回 {#rqdata-API-fund-get_manager_indicators-return}

_pandas DataFrame_

标准版涵盖的衍生指标及频率如下，字段的组成方式为 “支持的频率\_字段”, 如 “日度累计收益” 字段名为 'daily_return'

| 字段               | 说明                             | 支持的频率                                         |
|-----|-----|-----|
| return             | 累计收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| return_a           | 累计收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total、year |
| benchmark_return   | 基准收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess             | 超额收益率                       | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess_a           | 超额收益率（年化）               | daily、w1、m1、m3、m6、y2、y1、y3、y5、total       |
| excess_win         | 超额胜率                         | m3、m6、y2、y1、y3、y5、total                      |
| stdev_a            | 波动率（年化）                   | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_avg_a | 下行波动率 - 均值（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| dev_downside_rf_a  | 下行波动率 - 无风险利率 （年化） | m3、m6、y2、y1、y3、y5、total                      |
| mdd                | 期间最大回撤                     | m3、m6、y2、y1、y3、y5、total                      |
| excess_mdd         | 期间超额收益最大回撤             | m3、m6、y2、y1、y3、y5、total                      |
| mdd_days           | 最大回撤持续期                   | m3、m6、y2、y1、y3、y5、total                      |
| recovery_days      | 最大回撤恢复期                   | m3、m6、y2、y1、y3、y5、total                      |
| max_drop           | 最大单日跌幅                     | m3、m6、y2、y1、y3、y5、total                      |
| max_drop_period    | 最大连跌期数                     | m3、m6、y2、y1、y3、y5、total                      |
| neg_return_ratio   | 亏损期占比                       | m3、m6、y2、y1、y3、y5、total                      |
| kurtosis           | 峰度                             | m3、m6、y2、y1、y3、y5、total                      |
| skewness           | 偏度                             | m3、m6、y2、y1、y3、y5、total                      |
| tracking_error     | 跟踪误差                         | m3、m6、y2、y1、y3、y5、total                      |
| var                | VaR                              | m3、m6、y2、y1、y3、y5、total                      |
| alpha_a            | Alpha（年化）                    | m3、m6、y2、y1、y3、y5、total                      |
| alpha_tstats       | Alpha Tstat                      | m3、m6、y2、y1、y3、y5、total                      |
| beta               | Beta                             | m3、m6、y2、y1、y3、y5、total                      |
| beta_downside      | 下行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| beta_upside        | 上行 Beta                        | m3、m6、y2、y1、y3、y5、total                      |
| sharpe_a           | Sharpe Ratio（年化）             | m3、m6、y2、y1、y3、y5、total                      |
| inf_a              | Information Ratio（年化）        | m3、m6、y2、y1、y3、y5、total                      |
| sortino_a          | Sortino Ratio（年化）            | m3、m6、y2、y1、y3、y5、total                      |
| calmar_a           | Calmar Ratio                     | m3、m6、y2、y1、y3、y5、total                      |
| timing_ratio       | 择时比率                         | m3、m6、y2、y1、y3、y5、total                      |
| benchmark          | 指标计算基准                     | 无                                                 |

#### 范例 {#rqdata-API-fund-get_manager_indicators-example}

```
In [25]: fund.get_manager_indicators('101000932',fields=['daily_return','total_calmar_a'],start_date='2018-02-06',end_date='2018-02-12',manage_type='independent',asset_type='stock')
Out[25]:
                       daily_return  total_calmar_a
manager_id datetime
101000932  2018-02-06     -0.031451        0.006801
           2018-02-07     -0.021206        0.006622
           2018-02-08      0.006771        0.006667
           2018-02-09     -0.028918        0.006426
           2018-02-12      0.027701        0.006639

```

### fund.get_manager_weight_info - 获取基金经理人在管产品权重信息 {#rqdata-API-fund-get_manager_weight_info}

```python
fund.get_manager_weight_info(managers, start_date=None, end_date=None, asset_type='stock', manage_type='all', market='cn')
```

获取基金经理在管产品权重数据，支持按股票型或债券型、独立管理或全部参与管理查询，反映各基金在当期管理规模中的占比。

#### 参数 {#rqdata-API-fund-get_manager_weight_info-params}

| 参数        | 类型                                                     | 说明                                                                   |
|-----|-----|-----|
| managers | _str_ or _list_                                          | **必填参数**，可传入基金经理 id 或名字。名字与 id 不能同时传入         |
| start_date  | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                               |
| end_date    | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期, start_date ,end_date 不传参数时默认返回所有数据              |
| asset_type  | _str_                                                    | 在管基金类型，默认为 stock <br /> stock - 股票型，bond - 债券型        |
| manage_type | _str_                                                    | 管理方式，默认为 all <br /> independent - 独立管理，all - 所有参与管理 |
| market      | _str_                                                    | 指定市场，目前仅有中国市场('cn')的基金经理人衍生数据                   |

#### 返回 {#rqdata-API-fund-get_manager_weight_info-return}

_pandas DataFrame_

| 字段          | 类型              | 说明                                   |
|-----|-----|-----|
| datetime      | _pandas.Timestamp_ | 在管时间                               |
| order_book_id | _str_             | 在管基金代码                           |
| weight        | _float_           | 基金占经理人当期管理所有基金的规模比例 |
| manager_name  | _str_             | 经理人名字                             |

#### 范例 {#rqdata-API-fund-get_manager_weight_info-example}

- 获取 id 为 101002315 的基金经理在管产品权重信息

```
In [27]: fund.get_manager_weight_info('101002315',asset_type='bond',manage_type='independent',start_date=20200101)
Out[27]:
                      order_book_id    weight manager_name
manager_id datetime
101002315  2020-03-31        007834  0.297317           蔡宾
           2020-03-31        007833  0.297317           蔡宾
           2020-03-31        007745  0.202683           蔡宾
           2020-03-31        007744  0.202683           蔡宾
           2020-06-30        007834  0.310725           蔡宾
           2020-06-30        007833  0.310725           蔡宾
           2020-06-30        007745  0.189275           蔡宾
           2020-06-30        007744  0.189275           蔡宾

```

- 获取某基金经理在管产品权重信息

```
In [30]: fund.get_manager_weight_info('李博',asset_type='stock',manage_type='independent',start_date=20200101)
Out[30]:
                      order_book_id    weight manager_name
manager_id datetime
101001503  2020-03-31        001144  0.389673           李博
           2020-03-31        090004  0.610327           李博
           2020-06-30        001144  0.351493           李博
           2020-06-30        090004  0.648507           李博
           2020-09-30        001144  0.279292           李博
           2020-09-30        090004  0.720708           李博
101001538  2020-03-31        000457  0.623594           李博
           2020-03-31        005983  0.008162           李博
           2020-03-31        377010  0.368245           李博
           2020-06-30        000457  0.602569           李博
           2020-06-30        005983  0.007005           李博
           2020-06-30        377010  0.390426           李博
           2020-09-30        005983  0.009946           李博
           2020-09-30        377010  0.467850           李博
           2020-09-30        000457  0.522204           李博
```
