## 港交所股票合约基础信息 {#rqdata-API-contract_hk}

<b>API 传参 `market='hk'` 即可获取港交所合约数据</b>

### all_instruments - 获取所有合约基础信息 {#rqdata-API-all_instruments_hk}

```python
rqdatac.all_instruments(type=None, market='hk', date=None)
```

获取港交所全部股票合约的基础信息，支持按合约类型和日期筛选。例如可按 `CS` 类型筛选，也可按指定日期筛选可交易合约。

#### 参数 {#rqdata-API-all_instruments_hk-params}

| 参数   | 类型                                                           | 说明                                                                |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| type   | _str_                                                          | 需要查询合约类型，例如：type='CS'代表股票。默认是所有类型           |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定日期，筛选指定日期可交易的合约                                  |

##### 其中 type 参数传入的合约类型和对应的解释如下：

| 合约类型 | 说明                 |
| -------- | -------------------- |
| CS       | Common Stock, 即股票 |

#### 返回 {#rqdata-API-all_instruments_hk-return}

_pandas DataFrame_ - 所有合约的基本信息。
详细字段注释请参考 [instruments](#rqdata-API-instruments_hk) 返回字段说明

#### 范例 {#rqdata-API-all_instruments_hk-example}

- 获取香港市场所有合约的基础信息：

```python
[In]rqdatac.all_instruments('CS',market='hk')
[Out]
     order_book_id      eng_symbol abbrev_symbol board_type    symbol listed_date de_listed_date  status  round_lot a_share_id exchange type trading_code      unique_id stock_connect
0       00001.XHKG    CKH HOLDINGS            CH  MainBoard        长和  1972-11-01     0000-00-00  Active      500.0       None     XHKG   CS        00001  00001_01.XHKG     sh_and_sz
1       00002.XHKG    CLP HOLDINGS          ZDKG  MainBoard      中电控股  1980-01-02     0000-00-00  Active      500.0       None     XHKG   CS        00002  00002_01.XHKG     sh_and_sz
2       00003.XHKG  HK & CHINA GAS        XGZHMQ  MainBoard    香港中华煤气  1960-04-11     0000-00-00  Active     1000.0       None     XHKG   CS        00003  00003_01.XHKG     sh_and_sz
3       00004.XHKG  WHARF HOLDINGS         JLCJT  MainBoard     九龙仓集团  1921-01-01     0000-00-00  Active     1000.0       None     XHKG   CS        00004  00004_01.XHKG     sh_and_sz
4       00005.XHKG   HSBC HOLDINGS          HFKG  MainBoard      汇丰控股  1980-01-02     0000-00-00  Active      400.0       None     XHKG   CS        00005  00005_01.XHKG     sh_and_sz
...            ...             ...           ...        ...       ...         ...            ...     ...        ...        ...      ...  ...          ...            ...           ...
3309    83690.XHKG      MEITUAN-WR          MTWR  MainBoard     美团-WR  2023-06-19     0000-00-00  Active      100.0       None     XHKG   CS        83690  83690_01.XHKG
3310    86618.XHKG     JD HEALTH-R         JDJKR  MainBoard    京东健康-R  2023-06-19     0000-00-00  Active       50.0       None     XHKG   CS        86618  86618_01.XHKG
3311    89618.XHKG          JD-SWR       JDJTSWR  MainBoard  京东集团-SWR  2023-06-19     0000-00-00  Active       50.0       None     XHKG   CS        89618  89618_01.XHKG
3312    89888.XHKG        BIDU-SWR       BDJTSWR  MainBoard  百度集团-SWR  2023-06-19     0000-00-00  Active       50.0       None     XHKG   CS        89888  89888_01.XHKG
3313    89988.XHKG         BABA-WR        ALBBWR  MainBoard   阿里巴巴-WR  2023-06-19     0000-00-00  Active      100.0       None     XHKG   CS        89988  89988_01.XHKG

[3314 rows x 15 columns]

```

### instruments - 获取合约详细信息 {#rqdata-API-instruments_hk}

```python
rqdatac.instruments(order_book_ids, market='hk')
```

获取一个或多个港交所股票合约最新的详细信息。

::: tip 注意事项

目前系统并不支持跨市场的同时调用。

:::

#### 参数 {#rqdata-API-instruments-hk-params}

| 参数           | 类型                | 说明                                                                                                       |
| -------------- | ------------------- | ---------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ OR _str list_ | 合约代码，可传入 order_book_id, order_book_id list。<br/>港交所股票的 order_book_id 通常类似'00001.XHKG'。 |
| market         | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                        |

#### 返回 {#rqdata-API-instruments-hk-return}

一个 instrument 对象，或一个 instrument list。

##### 股票 Instrument 对象

| 字段           | 类型  | 说明                                                                                                                            |
| -------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------- |
| order_book_id  | _str_ | 证券代码，证券的独特的标识符。港股以'.XHKG'结尾。                                                                               |
| symbol         | _str_ | 证券的简称，例如'长和'                                                                                                          |
| abbrev_symbol  | _str_ | 证券的名称缩写，在中国 A 股就是股票的拼音缩写。例如：'CH'就是长和股票的证券拼音名缩写                                           |
| eng_symbol     | _str_ | 证券的英文名称。例如：'CKH HOLDINGS'就是长和股票的英文名称                                                                      |
| round_lot      | _int_ | 一手对应多少股                                                                                                                  |
| listed_date    | _str_ | 该证券上市日期                                                                                                                  |
| de_listed_date | _str_ | 退市日期                                                                                                                        |
| type           | _str_ | 合约类型，目前支持的类型有: 股票:'CS'                                                                                           |
| exchange       | _str_ | 交易所，'XHKG' - 港交所                                                                                                         |
| board_type     | _str_ | 板块类别，'MainBoard' - 主板,'GEM' - 创业板                                                                                     |
| status         | _str_ | 合约状态。'Active' - 正常上市, 'Delisted' - 终止上市                                                                            |
| stock_connect  | _str_ | 沪深港通标识。<br/>'sh_and_sz':沪深港通''<br/> 'sz':'深港通'<br/> 'sh':沪港通                                                   |
| a_share_id     | _str_ | 对应 A 股 order_book_id                                                                                                         |
| trading_code   | _str_ | 交易代码                                                                                                                        |
| unique_id      | _str_ | 米筐内部编码，因为港股存在代码复用，所以米筐内部用这个编码作为合约的唯一标识，如\_02 代表复用一次（一般用户可以不关注这个字段） |

#### 范例 {#rqdata-API-instruments_hk-example}

- 获取单一股票合约的详细信息：

```
In [5]: rqdatac.instruments('00013.XHKG',market='hk')
Out[5]:
Instrument(order_book_id='00013.XHKG', eng_symbol='HUTCHMED', abbrev_symbol='HHYY', board_type='MainBoard', symbol='和黄医药', listed_date='2021-06-30', de_listed_date='0000-00-00', status='Active', round_lot=500.0, exchange='XHKG', type='CS', trading_code='00013', unique_id='00013_02.XHKG', stock_connect='sh_and_sz')
```

### get_ex_factor - 获取复权因子 {#rqdata-API-get_ex_factor_hk}

```python
get_ex_factor(order_book_ids, start_date=None, end_date=None, market='hk')
```

获取港股股票在一段时间内的复权因子数据，以除权除息日为查询基准，支持单只股票和股票列表查询。

#### 参数 {#rqdata-API-get_ex_factor_hk-param}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | 合约代码                                                            |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                            |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                            |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_ex_factor_hk-return}

_pandas DataFrame_ - 包含了复权因子的日期和对应的各项数值

| 字段              | 类型               | 说明                                                                                                                                                                                                                                                                                        |
| ----------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ex_date           | _pandas.Timestamp_ | 除权除息日                                                                                                                                                                                                                                                                                  |
| ex_factor         | _float_            | 复权因子，考虑了分红派息与拆分的影响，为一段时间内的股价调整乘数。<br/>举例来说，长和（'00001.XHKG'）在 2024 年 9 月 13 日每股派发现金股利港币 0.688 元，。<br/>9 月 12 日的收盘价为 41.85 元，其除权除息后的价格应当为 (41.85-0.688) / 1 = 41.162.本期复权因子为 41.85 / 41.162 = 1.016714 |
| ex_cum_factor     | _float_            | 累计复权因子，X 日所在期复权因子 = 当前最新累计复权因子 / 截至 X 日最新累计复权因子。<br/>长和（'00001.XHKG'）2024 年 9 月 13 日所在期复权因子 = 4.117329 / 4.049641 = 1.016714                                                                                                             |
| announcement_date | _pandas.Timestamp_ | 股权登记日                                                                                                                                                                                                                                                                                  |
| ex_end_date       | _pandas.Timestamp_ | 复权因子所在期的截止日期                                                                                                                                                                                                                                                                    |

#### 范例 {#rqdata-API-get_ex_factor_hk-example}

```python
[In]
rqdatac.get_ex_factor('00001.XHKG',market='hk')
[Out]
            ex_cum_factor ex_end_date  ex_factor announcement_date order_book_id
ex_date
1999-10-08       1.005224  2000-05-16   1.005224        1999-10-07    00001.XHKG
2000-05-16       1.018303  2000-10-10   1.013011        2000-05-15    00001.XHKG
2000-10-10       1.022481  2001-05-15   1.004103        2000-10-09    00001.XHKG
2001-05-15       1.036414  2001-10-09   1.013627        2001-05-14    00001.XHKG
2001-10-09       1.042884  2002-05-14   1.006243        2001-10-08    00001.XHKG
2002-05-14       1.060013  2002-06-19   1.016424        2002-05-13    00001.XHKG
2002-06-19       1.060013  2002-10-08   1.000000        2002-06-18    00001.XHKG
2002-10-08       1.068804  2003-05-13   1.008293        2002-10-07    00001.XHKG
2003-05-13       1.098119  2003-10-07   1.027428        2003-05-12    00001.XHKG
2003-10-07       1.104430  2004-05-11   1.005747        2003-10-06    00001.XHKG
2004-05-11       1.130678  2004-10-05   1.023766        2004-05-10    00001.XHKG
2004-10-05       1.136985  2005-05-10   1.005578        2004-10-04    00001.XHKG
2005-05-10       1.159078  2005-10-04   1.019431        2005-05-09    00001.XHKG
2005-10-04       1.164662  2005-11-10   1.004818        2005-10-03    00001.XHKG
2005-11-10       1.164662  2006-05-09   1.000000        2005-11-09    00001.XHKG
2006-05-09       1.185556  2006-10-03   1.017940        2006-05-08    00001.XHKG
2006-10-03       1.192112  2007-05-08   1.005530        2006-09-29    00001.XHKG
2007-05-08       1.211451  2007-10-02   1.016222        2007-05-07    00001.XHKG
2007-10-02       1.216194  2008-05-13   1.003915        2007-09-28    00001.XHKG
2008-05-13       1.236048  2008-09-29   1.016325        2008-05-09    00001.XHKG
2008-09-29       1.242658  2009-05-12   1.005348        2008-09-26    00001.XHKG
2009-05-12       1.271765  2009-09-24   1.023423        2009-05-11    00001.XHKG
2009-09-24       1.278111  2010-05-18   1.004990        2009-09-23    00001.XHKG
2010-05-18       1.309476  2010-09-10   1.024540        2010-05-17    00001.XHKG
2010-09-10       1.315908  2011-05-11   1.004912        2010-09-09    00001.XHKG
2011-05-11       1.343475  2011-09-12   1.020949        2011-05-09    00001.XHKG
2011-09-12       1.350492  2012-05-30   1.005223        2011-09-09    00001.XHKG
2012-05-30       1.389237  2012-09-11   1.028690        2012-05-29    00001.XHKG
2012-09-11       1.396007  2013-05-24   1.004873        2012-09-10    00001.XHKG
2013-05-24       1.428449  2013-09-03   1.023239        2013-05-23    00001.XHKG
2013-09-03       1.435812  2014-05-05   1.005155        2013-09-02    00001.XHKG
2014-05-05       1.515076  2014-05-21   1.055205        2014-05-02    00001.XHKG
2014-05-21       1.548186  2014-09-01   1.021854        2014-05-20    00001.XHKG
2014-09-01       1.555209  2015-03-11   1.004536        2014-08-29    00001.XHKG
2015-03-11       1.586461  2015-05-27   1.020095        2015-03-10    00001.XHKG
2015-05-27       2.754203  2015-09-22   1.736067        2015-05-26    00001.XHKG
2015-09-22       2.772958  2016-05-18   1.006809        2015-09-21    00001.XHKG
2016-05-18       2.829894  2016-09-09   1.020533        2016-05-17    00001.XHKG
2016-09-09       2.850393  2017-05-16   1.007244        2016-09-08    00001.XHKG
2017-05-16       2.905528  2017-09-04   1.019343        2017-05-15    00001.XHKG
2017-09-04       2.927984  2018-05-15   1.007729        2017-09-01    00001.XHKG
2018-05-15       2.994493  2018-09-03   1.022715        2018-05-14    00001.XHKG
2018-09-03       3.023575  2019-05-21   1.009712        2018-08-31    00001.XHKG
2019-05-21       3.114958  2019-09-02   1.030223        2019-05-20    00001.XHKG
2019-09-02       3.155148  2020-05-19   1.012902        2019-08-30    00001.XHKG
2020-05-19       3.290033  2020-09-07   1.042751        2020-05-18    00001.XHKG
2020-09-07       3.330937  2021-05-18   1.012433        2020-09-04    00001.XHKG
2021-05-18       3.423539  2021-09-06   1.027800        2021-05-17    00001.XHKG
2021-09-06       3.472229  2022-05-24   1.014222        2021-09-03    00001.XHKG
2022-05-24       3.590644  2022-09-05   1.034103        2022-05-23    00001.XHKG
2022-09-05       3.651935  2023-05-23   1.017070        2022-09-02    00001.XHKG
2023-05-23       3.807677  2023-09-04   1.042646        2023-05-22    00001.XHKG
2023-09-04       3.876225  2024-05-28   1.018003        2023-08-31    00001.XHKG
2024-05-28       4.049641  2024-09-13   1.044739        2024-05-27    00001.XHKG
2024-09-13       4.117329         NaT   1.016714               NaT    00001.XHKG

```

### get_exchange_rate - 获取汇率信息 {#rqdata-API-get_exchange_rate_hk}

```python
get_exchange_rate(start_date=None, end_date=None, fields=None)
```

获取汇率信息，支持按时间范围查询。例如可获取 `currency_pair` 和 `middle_referrence_rate` 数据，也包括如 `HKDCNY` 这类货币对。

#### 参数 {#rqdata-API-get_exchange_rate_hk-params}

| 参数       | 类型                                                           | 说明                                                                       |
| ---------- | -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                   |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                   |
| fields     | _list_                                                         | 字段名称，如需计算财务数据，可指定 currency_pair 和 middle_referrence_rate |

#### 返回 {#rqdata-API-get_exchange_rate_hk-return}

_pandas DataFrame_

| 字段                   | 类型               | 说明                                                     |
| ---------------------- | ------------------ | -------------------------------------------------------- |
| date                   | _pandas.Timestamp_ | 时间戳                                                   |
| currency_pair          | _str_              | 货币对。返回值见下方，如'HKDCNY'表示 1 港币对应的人民币  |
| middle_referrence_rate | _str_              | 中间价，香港金融管理局披露值，<b>月更新</b>              |
| bid_referrence_rate    | _str_              | 买入参考汇率，上交所和深交所披露值，日更新 (仅限 HKDCNY) |
| ask_referrence_rate    | _str_              | 卖出参考汇率，上交所和深交所披露值，日更新 (仅限 HKDCNY) |
| bid_settlement_rate_sh | _str_              | 买入结算汇率-沪港通，盘后更新 (仅限 HKDCNY)              |
| ask_settlement_rate_sh | _str_              | 卖出结算汇率-沪港通，盘后更新 (仅限 HKDCNY)              |
| bid_settlement_rate_sz | _str_              | 买入结算汇率-深港通，盘后更新 (仅限 HKDCNY)              |
| ask_settlement_rate_sz | _str_              | 卖出结算汇率-深港通，盘后更新 (仅限 HKDCNY)              |

##### currency_pair 返回值：

| 货币单位       | 货币对 |
| -------------- | ------ |
| 美元           | HKDUSD |
| 日本元         | HKDJPY |
| 澳门元         | HKDMOP |
| 新加坡元       | HKDSGD |
| 泰国铢         | HKDTHB |
| 人民币元       | HKDCNY |
| 台湾元         | HKDTWD |
| 欧元           | HKDEUR |
| 加拿大元       | HKDCAD |
| 澳大利亚元     | HKDAUD |
| 马来西亚林吉特 | HKDMYR |
| 英镑           | HKDGBP |
| 南非兰特       | HKDZAR |
| 印度尼西亚卢比 | HKDIDR |

#### 范例 {#rqdata-API-get_exchange_rate_hk-example}

- 获取 HKDCNY 20250101 - 20250630 所有字段

```python
[In]
df = get_exchange_rate(20250101,20250630)
df[df['currency_pair'] =='HKDCNY']
[Out]
           currency_pair bid_referrence_rate  ask_referrence_rate ... ask_settlement_rate_sh bid_settlement_rate_sz ask_settlement_rate_sz
date
2025-01-02 HKDCNY 0.9165            0.9731                ...  0.94448                0.94479                0.94481
2025-01-03 HKDCNY 0.9137            0.9703                ...  0.94258                0.94149                0.94251
2025-01-04 HKDCNY NaN                 NaN                   ... NaN                     NaN                     NaN
2025-01-06 HKDCNY 0.9175            0.9743                ... 0.94597                0.94588                0.94592
2025-01-07 HKDCNY 0.9174            0.9742                ... 0.94545                0.94578                0.94582
...
2025-06-25 HKDCNY 0.8868            0.9416                ... 0.91418                0.91423                0.91417
2025-06-26 HKDCNY 0.8862            0.9410                ... 0.91358                0.91362                0.91358
2025-06-27 HKDCNY 0.8852            0.9400                ... 0.91261                0.91256                0.91264
2025-06-28 HKDCNY NaN                 NaN                     ...  NaN                     NaN                     NaN
2025-06-30 HKDCNY 0.8858            0.9406                ... 0.91319                0.91323                0.91317
```

- 获取日期为 20250210 1 港币对应的所有货币汇率

```python
[In]
get_exchange_rate(20250210,20250210,fields =['currency_pair','middle_referrence_rate'])
[Out]
               currency_pair middle_referrence_rate
date
2025-02-10 HKDAUD 0.2046
2025-02-10 HKDCAD 0.1841
2025-02-10 HKDCNY 0.9384
2025-02-10 HKDEUR 0.1244
2025-02-10 HKDJPY 19.5065
2025-02-10 HKDMYR 0.5738
2025-02-10 HKDSGD 0.1738
2025-02-10 HKDTHB 4.3403
2025-02-10 HKDTWD 4.1152
2025-02-10 HKDUSD 0.1284
2025-02-10 HKDGBP 0.1035


```

### get_shares - 获取流通股信息 {#rqdata-API-get_shares_hk}

```python
get_shares(order_book_ids, start_date=None, end_date=None, fields=None, market='hk', expect_df=True)
```

获取港股股票在一段时间内的流通股数据，支持单只股票和股票列表查询。

#### 参数 {#rqdata-API-get_shares_hk-params}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | 可输入 order_book_id 或 symbol                                      |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，                                                          |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据   |
| fields         | _str_ OR _str list_                                            | 默认为所有字段。见下方列表                                          |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe,如果调为 False ,则返回原有的数据结构      |

#### 返回 {#rqdata-API-get_shares_hk-return}

_pandas  DataFrame_

| 字段              | 类型    | 说明                   |
| ----------------- | ------- | ---------------------- |
| total             | _float_ | 总股本                 |
| authorized_shares | _float_ | 法定股数(股)           |
| total_a           | _float_ | A 股总股本             |
| not_hk_shares     | _float_ | 非港股股数(股)         |
| preferred_shares  | _float_ | 优先股                 |
| total_hk          | _float_ | 已上市港股股数(股)     |
| total_hk1         | _float_ | 可在港股交易的股数(股) |

#### 范例 {#rqdata-API-get_shares_hk-example}

- 获取平安银行流通股概况

```python
[In]
get_shares(order_book_ids='00038.XHKG', start_date=20250715, end_date=20250720, fields=None, market='hk')
[Out]
               authorized_shares not_hk_shares preferred_shares total total_a
order_book_id date
00038.XHKG 2025-07-15 1.123645e+09 731705275.0 0.0 1.123645e+09 731705275.0
               2025-07-16 1.123645e+09 731705275.0 0.0 1.123645e+09 731705275.0
               2025-07-17 1.123645e+09 731705275.0 0.0 1.123645e+09 731705275.0
               2025-07-18 1.123645e+09 731705275.0 0.0 1.123645e+09 731705275.0

```

### is_suspended - 判断股票是否全天停牌 {#rqdata-API-is_suspended_hk}

```python
is_suspended(order_book_ids, start_date=None, end_date=None, market='hk')
```

获取港股股票在一段时间内是否全天停牌的数据，支持单只股票和股票列表查询。

#### 参数 {#rqdata-API-is_suspended_hk-params}

| 参数           | 类型                                                           | 说明                                                                |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码。传入单只或多支股票的 order_book_id          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为股票上市日期                                        |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期，如果股票已经退市，则为退市日期            |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-is_suspended_hk-return}

_pandas DataFrame_
如果在查询期间内股票尚未上市，或已经退市，则函数返回 None；如果开始日期早于股票上市日期，则以股票上市日期作为开始日期。

#### 范例 {#rqdata-API-is_suspended_hk-example}

- 获取福寿园从 2026 年 3 月 1 日至今（2026 年 3 月 26 日）的停牌情况：

```python
[In]
rqdatac.is_suspended('01448.XHKG', start_date='20260301',end_date='20260326',market='hk')
[Out]
            01448.XHKG
date
2026-03-02       False
2026-03-03       False
2026-03-04       False
2026-03-05       False
2026-03-06       False
2026-03-09       False
2026-03-10       False
2026-03-11       False
2026-03-12       False
2026-03-13       False
2026-03-16       False
2026-03-17       False
2026-03-18       False
2026-03-19       False
2026-03-20        True
2026-03-23        True
2026-03-24        True
2026-03-25        True
2026-03-26       False

```

### get_industry - 获取某行业的股票列表 {#rqdata-API-get_industry_hk}

```python
get_industry(industry, source='citics_2019', date=None, market='hk')
```

获取指定行业分类下的港股股票列表，支持通过行业名称、行业指数代码或行业代号查询。例如分类依据可选 `citics_2019`、`sws_2021`、`hsi`、`csi`。

#### 参数 {#rqdata-API-get_industry_hk-params}

| 参数     | 类型                                                           | 说明                                                                                                       |
| -------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| industry | _str_                                                          | **必填参数**，可传入行业名称、行业指数代码或者行业代号                                                     |
| source   | _str_                                                          | 分类依据。 citics_2019:中信 2019 分类，sws_2021:申万行业分类，hsi:恒生行业分类，csi :中证行业分类。 默认 source='citics_2019' |
| date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                               |
| market   | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                        |

#### 返回 {#rqdata-API-get_industry_hk-return}

_list_

#### 范例 {#rqdata-API-get_industry_hk-example}

- 得到当前某一级行业的股票列表：

```python
[In]
get_industry('原材料业',source='hsi',market='hk')
[Out]
['00094.XHKG',
 '00098.XHKG',
 '00159.XHKG',
 '00166.XHKG',
 '00189.XHKG',
 '00195.XHKG',
 '00217.XHKG',
 '00235.XHKG',
 '00274.XHKG',
 '00297.XHKG',
 '00301.XHKG',
 '00323.XHKG',
 '00338.XHKG',
 '00340.XHKG',
 '00347.XHKG',
 '00358.XHKG',
 '00362.XHKG',
 '00372.XHKG',
...

]
```

### get_industry_change - 获取某行业的股票纳入剔除日期 {#rqdata-API-get_industry_change_hk}

```python
get_industry_change(industry, source='citics_2019', level=None, market='hk')
```

获取指定行业分类下港股股票的纳入和剔除日期数据。例如分类依据可选 `citics_2019`、`sws_2021`、`hsi`、`csi`，行业级别支持 1、2、3。

#### 参数 {#rqdata-API-get_industry_change_hk-params}

| 参数     | 类型      | 说明                                                                                                      |
| -------- | --------- | --------------------------------------------------------------------------------------------------------- |
| industry | _str_     | **必填参数**，可传入行业名称、行业指数代码或者行业代号                                                    |
| source   | _str_     | 分类依据。 citics_2019:中信 2019 分类，sws_2021:申万行业分类，hsi:恒生行业分类，csi :中证行业分类。默认 source='citics_2019' |
| level    | _integer_ | 行业分类级别，共三级，默认一级分类。参数 1,2,3 一一对应                                                   |
| market   | _str_     | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                       |

#### 返回 {#rqdata-API-get_industry_change_hk-return}

_pandas DataFrame_

| 字段        | 类型               | 说明                            |
| ----------- | ------------------ | ------------------------------- |
| start_date  | _pandas.Timestamp_ | 起始日期                        |
| cancel_date | _pandas.Timestamp_ | 取消日期，2200-12-31 表示未披露 |

#### 范例 {#rqdata-API-get_industry_change_hk-example}

- 得到当前某一级行业的股票纳入剔除日期：

```python
[In]
get_industry_change(industry='原材料业', level=1,source='hsi',market='hk')
[Out]
               start_date cancel_date
order_book_id
01812.XHKG 2013-09-09 2200-12-31
00347.XHKG 2013-09-09 2200-12-31
00358.XHKG 2013-09-09 2200-12-31
01787.XHKG 2018-09-28 2200-12-31
00338.XHKG 2013-09-09 2200-12-31
... ... ...
09879.XHKG 2024-03-21 2200-12-31
06616.XHKG 2021-07-16 2200-12-31
02237.XHKG 2022-07-18 2200-12-31
02881.XHKG 2024-06-18 2200-12-31
02610.XHKG 2025-03-25 2200-12-31

```

### get_instrument_industry - 获取股票的指定行业分类 {#rqdata-API-get_instrument_industry_hk}

```python
get_instrument_industry(order_book_ids, source='citics_2019', level=1, date=None, market='hk')
```

获取港股股票在指定日期的行业分类数据。例如分类依据可选 `citics_2019`、`sws_2021`、`hsi`、`csi`，也支持一级、二级、三级分类数据。

#### 参数 {#rqdata-API-get_instrument_industry_hk-params}

| 参数          | 类型                                                           | 说明                                                                                                       |
| ------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| order_book_id | _str_ or _str list_                                            | **必填参数**，股票合约代码，可输入 order_book_id, order_book_id list                                       |
| date          | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                               |
| source        | _str_                                                          | 分类依据。citics_2019:中信 2019 分类，sws_2021:申万行业分类，hsi:恒生行业分类，csi :中证行业分类。 默认 source='citics_2019'. |
| level         | _integer_                                                      | 行业分类级别，共三级，默认返回一级分类。参数 0,1,2,3 一一对应，其中 0 返回三级分类完整情况                 |
| market        | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                        |

#### 返回 {#rqdata-API-get_instrument_industry_hk-return}

_pandas DataFrame_

| 字段                 | 类型  | 说明         |
| -------------------- | ----- | ------------ |
| first_industry_code  | _str_ | 一级行业代码 |
| first_industry_name  | _str_ | 一级行业名称 |
| second_industry_code | _str_ | 二级行业代码 |
| second_industry_name | _str_ | 二级行业名称 |
| third_industry_code  | _str_ | 三级行业代码 |
| third_industry_name  | _str_ | 三级行业名称 |

#### 范例 {#rqdata-API-get_instrument_industry_hk-example}

- 得到当前股票所对应的一级行业：

```python
[In]
get_instrument_industry(order_book_ids='00001.XHKG',market='hk')
[Out]
                   first_industry_code first_industry_name
order_book_id
00001.XHKG     43                综合金融

```

- 得到当前股票组所对应的中信行业的全部分类：

```python
In [7]: get_instrument_industry(['00001.XHKG','00038.XHKG'],source='citics_2019',level=0,market='hk')
Out[7]:
              first_industry_code first_industry_name second_industry_code second_industry_name third_industry_code third_industry_name
order_book_id
00038.XHKG 26 机械 2620 专用机械 262030 其他专用机械
00001.XHKG 43 综合金融 4320 多领域控股Ⅱ 432010 多领域控股Ⅲ

```

### get_industry_mapping - 获取行业分类概览 {#rqdata-API-get_industry_mapping_hk}

```python
get_industry_mapping(source='citics_2019', date=None, market='hk')
```

获取行业分类概览数据，支持按分类依据和日期查询一、二、三级行业代码与名称。例如分类依据可选 `citics_2019`、`sws_2021`、`hsi`、`csi`。

#### 参数 {#rqdata-API-get_industry_mapping_hk-params}

| 参数   | 类型                                                           | 说明                                                                                                      |
| ------ | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| source | _str_                                                          | 分类依据。 citics_2019:中信 2019 分类，sws_2021:申万行业分类，hsi:恒生行业分类，csi :中证行业分类。默认 source='citics_2019' |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为当前最新日期                                                                              |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                       |

#### 返回 {#rqdata-API-get_industry_mapping_hk-return}

_pandas DataFrame_

| 字段                 | 类型  | 说明         |
| -------------------- | ----- | ------------ |
| first_industry_code  | _str_ | 一级行业代码 |
| first_industry_name  | _str_ | 一级行业名称 |
| second_industry_code | _str_ | 二级行业代码 |
| second_industry_name | _str_ | 二级行业名称 |
| third_industry_code  | _str_ | 三级行业代码 |
| third_industry_name  | _str_ | 三级行业名称 |

#### 范例 {#rqdata-API-get_industry_mapping_hk-example}

- 得到当前行业分类的概览：

```python
[In]
get_industry_mapping(market='hk')
[Out]
     first_industry_code first_industry_name second_industry_code second_industry_name third_industry_code third_industry_name
0 10 石油石化 1010 石油开采Ⅱ 101010 石油开采Ⅲ
1 10 石油石化 1020 石油化工 102010 炼油
2 10 石油石化 1020 石油化工 102040 油品销售及仓储
3 10 石油石化 1030 油服工程 103010 油田服务
4 10 石油石化 1030 油服工程 103020 工程服务
...
```

### get_turnover_rate - 获取历史换手率 {#rqdata-API-get_turnover_rate_hk}

```python
get_turnover_rate(order_book_ids, start_date=None, end_date=None, fields=None,expect_df=True,market='hk')
```

获取港股历史换手率数据，支持按时间范围和字段查询。例如字段可选 `today`、`week`、`month`、`year`，也包括 `current_year`。

#### 参数 {#rqdata-API-get_turnover_rate_hk-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                            |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list                                                                                                |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                                                                                        |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据                                                                                               |
| fields         | _str_ OR _str list_                                            | 默认为所有字段。当天换手率 - `today`，过去一周平均换手率 - `week`，过去一个月平均换手率 - `month`，过去一年平均换手率 - `year`，当年平均换手率 - `current_year` |
| expect_df      | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构                                                                                                 |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                             |

#### 返回 {#rqdata-API-get_turnover_rate_hk-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-get_turnover_rate_hk-example}

- 获取长和 00001.XHKG 历史换手率情况

```
In [17]: get_turnover_rate('00001.XHKG',20250801,20250810,market='hk')
Out[17]:
                              today	week	     month	year	     current_year
order_book_id	tradedate
00001.XHKG	2025-08-01	0.2842	0.2667	0.2035	0.2562	0.3156
               2025-08-04	0.2290	0.2372	0.2088	0.2566	0.3150
               2025-08-05	0.1249	0.2097	0.2050	0.2564	0.3137
               2025-08-06	0.1689	0.2133	0.2034	0.2564	0.3127
               2025-08-07	0.1340	0.1882	0.2046	0.2564	0.3115
               2025-08-08	0.2370	0.1788	0.2083	0.2570	0.3110
```

- 获取多支股票一段时间内的周平均换手率

```python
[In]
get_turnover_rate(['00001.XHKG', '00038.XHKG'], '20250804', '20250805', 'week', market='hk')

[Out]

                               week
order_book_id	tradedate
00001.XHKG	2025-08-04	0.2372
               2025-08-05	0.2097
00038.XHKG	2025-08-04	1.1502
               2025-08-05	1.1519

```

### get_dividend - 获取股票现金分红数据 {#rqdata-API-get_dividend}

```python
get_dividend(order_book_ids, start_date=None, end_date=None, expect_df=True, market='cn')
```

获取港股股票在一段时间内的现金分红数据，以分红宣布日为查询基准，支持单只股票和股票列表查询。

#### 参数 {#rqdata-API-get_dividend-params}

::: tip 注意事项 {#rqdata-API-financial-tip}

1、rqdatac 3.4.3 起，expect_df 默认参数值由 False 更改为True <br/>
2、market='hk' 不支持 expect_df = False

:::

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

#### 范例 {#rqdata-API-get_dividend-example}

- 获取 00001.XHKG 长和历史至今的现金分红数据：

```python
[In]
get_dividend('00001.XHKG',market='hk')

[Out]
                             ex_dividend_date	book_closure_date	payable_date	dividend_cash_before_tax	round_lot
order_book_id	declaration_announcement_date
00001.XHKG	1999-08-26	1999-10-08	1999-10-11	1999-10-20	0.330	1
               2000-03-23	2000-05-16	2000-05-17	2000-05-30	1.050	1
               2000-08-24	2000-10-10	2000-10-11	2000-10-20	0.380	1
               ... ... ...
               2024-08-15	2024-09-13	2024-09-16	2024-09-26	0.688	1
               2025-03-20	2025-05-27	2025-05-28	2025-06-12	1.514	1
               2025-08-14	2025-09-15	2025-09-16	2025-09-25	0.710	1

```

### hk.get_southbound_eligible_secs - 获取港股通成分股数据 {#rqdata-API-get_southbound_eligible_secs_hk}

```python
hk.get_southbound_eligible_secs(trading_type='sh', date=None, start_date=None, end_date=None, market='hk')
```

获取港股通成分股数据，支持按日期或时间范围查询。例如 `trading_type` 可选港股通（沪）`sh` 和港股通（深）`sz`。

::: tip 注意事项

请先单独安装 rqdatac_hk，导入后使用

:::

#### 参数 {#rqdata-API-get_southbound_eligible_secs_hk-params}

| 参数         | 类型                                                           | 说明                                                              |
| ------------ | -------------------------------------------------------------- | ----------------------------------------------------------------- |
| trading_type | _str_                                                          | **必填参数**，支持填入 'sh':'港股通（沪）</br>'sz':'港股通（深）' |
| date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认为最新记录日期                                      |
| start_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定开始日期，不能和 date 同时指定                                |
| end_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定结束日期, 需和 start_date 同时指定并且应当不小于开始日期      |
| market       | _str_                                                          | 市场，仅限'hk'香港市场                                            |

#### 返回 {#rqdata-API-get_turget_southbound_eligible_secs_hknover_rate_hk-return}

_某一天港股通成分股的 order_book_id list_

#### 范例 {#rqdata-API-get_southbound_eligible_secs_hk-example}

- 指定 date 获取某一天的 sh 港股通成分股数据

```python
[In]
import rqdatac_hk
import rqdatac
rqdatac.init()
rqdatac.hk.get_southbound_eligible_secs(trading_type='sh',date=20250929)
[Out]
['00001.XHKG',
 '00002.XHKG',
 '00003.XHKG',
 .....
]
```

- 获取某段时间的 sz 港股通成分股数据

```python
[In]
rqdatac.hk.get_southbound_eligible_secs(trading_type='sz',start_date=20250925,end_date=20250929)
[Out]
[{datetime.datetime(2025, 9, 25, 0, 0): ['00001.XHKG',
  '00002.XHKG',
  '00003.XHKG',
  '00004.XHKG'
  ...
  ],
 datetime.datetime(2025, 9, 29, 0, 0): ['00001.XHKG',
  '00002.XHKG',
  '00003.XHKG',
  '00004.XHKG',
  ...]}
]
```

## 港交所股票行情（基于港交所延时行情） {#rqdata-API-get_price_hk}

### get_price - 获取合约历史行情数据 {#rqdata-API-get_price_hk_function}

```python
get_price(order_book_ids, start_date=None, end_date=None, frequency='1d', fields=None, adjust_type='pre', skip_suspended=False, expect_df=True, time_slice=None, market='cn')
```

获取港股合约历史行情数据，支持周线、日线、分钟线和 tick 数据。

::: tip 注意事项

周线数据目前只支持'1w',依据日线数据进行合成，例如股票周线的前复权数据使用前复权日线数据进行合成，股票周线的不复权数据使用不复权的日线数据合成。

:::

#### 参数 {#rqdata-API-get_price_hk-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                                                                                                                                          |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                                                                                                                                                                              |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                                                                                                                                                                                                                                      |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                                                                                                                                                                                                                                                      |
| frequency      | _str_                                                          | 历史数据的频率。 现在支持**周/日/分钟/tick 级别**的历史数据，默认为'1d'。<br/> 1m - 分钟线<br/> 1d - 日线 <br/>1w - 周线，只支持'1w' <br/> 日线和分钟可选取不同频率，例如'5m'代表 5 分钟线。                                                                                                                  |
| fields         | _str_ OR _str list_                                            | 字段名称                                                                                                                                                                                                                                                                                                      |
| adjust_type    | _str_                                                          | 权息修复方案，默认为`pre`。<br/>不复权 - `none`，<br/>前复权 - `pre`，后复权 - `post`，<br/>前复权 - `pre_volume`, 后复权 - `post_volume` <br/>两组前后复权方式仅 volume 字段处理不同，其他字段相同。其中'pre'、'post'中的 volume 采用拆分因子调整；'pre_volume'、'post_volume'中的 volume 采用复权因子调整。 |
| skip_suspended | _bool_                                                         | 是否跳过停牌数据。默认为 False，不跳过，用停牌前数据进行补齐。True 则为跳过停牌期。                                                                                                                                                                                                                           |
| expect_df      | _bool_                                                         | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构,周线数据需设置 expect_df=True                                                                                                                                                                                                                 |
| time_slice     | _str, datetime.time_                                           | 开始、结束时间段。默认返回当天所有数据。<br/>支持分钟 / tick 级别的切分，详见下方范例。                                                                                                                                                                                                                       |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                                                                                                                                           |

#### 返回 {#rqdata-API-get_price_hk-return}

_pandas DataFrame_

##### bar 数据

| 字段           | 类型    | 说明                                                        |
| -------------- | ------- | ----------------------------------------------------------- |
| open           | _float_ | 开盘价                                                      |
| close          | _float_ | 收盘价                                                      |
| high           | _float_ | 最高价                                                      |
| low            | _float_ | 最低价                                                      |
| limit_up       | _float_ | 涨停价，港股该字段为 nan                                    |
| limit_down     | _float_ | 跌停价，港股该字段为 nan                                    |
| total_turnover | _float_ | 成交额                                                      |
| volume         | _float_ | 成交量                                                      |
| num_trades     | _int_   | 成交笔数 ，港股该字段为 nan                                 |
| prev_close     | _float_ | 昨日收盘价 （交易所披露的原始昨收价，复权方法对该字段无效） |

##### tick 数据

| 字段           | 类型               | 说明                       |
| -------------- | ------------------ | -------------------------- |
| datetime       | _pandas.Timestamp_ | 交易所时间戳               |
| open           | _float_            | 当日开盘价                 |
| high           | _float_            | 当日最高价                 |
| low            | _float_            | 当日最低价                 |
| last           | _float_            | 最新价                     |
| prev_close     | _float_            | 昨日收盘价                 |
| total_turnover | _float_            | 当天累计成交额             |
| volume         | _float_            | 当天累计成交量             |
| num_trades     | _int_              | 成交笔数，港股该字段为 nan |
| limit_up       | _float_            | 涨停价，港股该字段为 nan   |
| limit_down     | _float_            | 跌停价，港股该字段为 nan   |
| a1~a10         | _float_            | 卖一至十档报盘价格         |
| a1_v~a10_v     | _float_            | 卖一至十档报盘量           |
| b1~b10         | _float_            | 买一至十档报盘价           |
| b1_v~b10_v     | _float_            | 买一至十档报盘量           |
| change_rate    | _float_            | 涨跌幅                     |
| trading_date   | _pandas.Timestamp_ | 交易日期                   |

#### 范例 {#rqdata-API-get_price_hk-example}

- 获取单一股票 20250101 - 20250301 的前复权日行情（返回*pandas DataFrame*）:

```python
[In] rqdatac.get_price('00013.XHKG',20250201,20250301,'1d',adjust_type='pre',market='hk')
[Out]
                          limit_up   high      volume  close  prev_close  limit_down  num_trades    low  total_turnover   open
order_book_id date
00013.XHKG    2025-02-03       NaN  21.00   1991902.0  20.50       20.90         NaN         NaN  19.80      40487322.0  21.00
              2025-02-04       NaN  21.10   1776500.0  20.95       20.50         NaN         NaN  20.40      37165850.0  20.40
              2025-02-05       NaN  21.95   3349788.0  21.45       20.95         NaN         NaN  20.60      71867476.0  20.90
              2025-02-06       NaN  22.25   3913626.0  22.15       21.45         NaN         NaN  21.40      85387156.0  21.70
              2025-02-07       NaN  22.15  10548253.0  20.95       22.15         NaN         NaN  20.75     223640681.0  22.15
              2025-02-10       NaN  21.20   6369895.0  21.00       20.95         NaN         NaN  20.55     133005019.0  20.95
              2025-02-11       NaN  21.20   3942204.0  20.70       21.00         NaN         NaN  20.45      81879917.0  21.20
              2025-02-12       NaN  20.85   7415758.0  20.25       20.70         NaN         NaN  19.98     150108216.0  20.80
              2025-02-13       NaN  20.80   6638000.0  20.35       20.25         NaN         NaN  20.20     135960312.0  20.35
              2025-02-14       NaN  21.30   8699765.0  21.30       20.35         NaN         NaN  20.50     182535018.0  20.55
              2025-02-17       NaN  22.05   7436135.0  21.25       21.30         NaN         NaN  20.90     159586141.0  21.70
              2025-02-18       NaN  21.50   6783079.0  21.50       21.25         NaN         NaN  20.75     143799674.0  21.15
              2025-02-19       NaN  23.10  10917076.0  22.95       21.50         NaN         NaN  21.20     246025831.0  21.50
              2025-02-20       NaN  24.60  17384900.0  23.80       22.95         NaN         NaN  23.10     415939321.0  23.25
              2025-02-21       NaN  25.70  14068700.0  25.45       23.80         NaN         NaN  24.10     353311420.0  24.15
              2025-02-24       NaN  25.70  12209181.0  24.80       25.45         NaN         NaN  24.05     302581084.0  25.45
              2025-02-25       NaN  26.20   9420500.0  24.80       24.80         NaN         NaN  23.55     234801813.0  23.70
              2025-02-26       NaN  26.50  10825094.0  26.10       24.80         NaN         NaN  24.35     279598939.0  24.80
              2025-02-27       NaN  27.15  10507606.0  26.70       26.10         NaN         NaN  25.85     278954072.0  26.30
              2025-02-28       NaN  26.60   9462325.0  25.75       26.70         NaN         NaN  25.55     245058462.0  26.60

```

- 获取单一股票 20250101 - 20250301 的后复权分钟行情（返回*pandas DataFrame*）:

```python
[In] rqdatac.get_price('00001.XHKG',20250101,20250301,'1m',adjust_type='post',market='hk')
[Out]
                                       high     volume     close  num_trades       low  total_turnover      open
order_book_id datetime
00001.XHKG    2025-01-02 09:31:00  170.8691   126234.0  169.6339         NaN  169.2222       5207436.0  170.0457
              2025-01-02 09:32:00  169.6339   321500.0  169.4281         NaN  168.3988      13204550.0  169.2222
              2025-01-02 09:33:00  169.4281        0.0  169.4281         NaN  169.4281             0.0  169.4281
              2025-01-02 09:34:00  169.4281     6500.0  169.4281         NaN  169.2222        267300.0  169.2222
              2025-01-02 09:35:00  169.2222   116500.0  169.2222         NaN  168.3988       4781750.0  169.0164
...                                     ...        ...       ...         ...       ...             ...       ...
              2025-02-28 15:56:00  160.5758    58000.0  160.5758         NaN  160.3700       2261675.0  160.5758
              2025-02-28 15:57:00  160.7817   263000.0  160.5758         NaN  160.5758      10257225.0  160.5758
              2025-02-28 15:58:00  160.7817    46999.0  160.5758         NaN  159.3406       1832136.0  160.7817
              2025-02-28 15:59:00  160.5758    20803.0  160.3700         NaN  160.3700        810942.0  160.5758
              2025-02-28 16:00:00  160.5758  8032500.0  159.9582         NaN  159.9582     312071325.0  160.3700

[12690 rows x 7 columns]
```

- 获取单一股票 20250303 的 tick 行情（返回*pandas DataFrame*）:

```python
[In] rqdatac.get_price('00001.XHKG',20250303,20250303,'tick',market='hk')
[Out]
                                      trading_date   open   last   high    low  prev_close     volume  total_turnover  limit_up  limit_down  ...     b6     b7     b8     b9    b10      b6_v      b7_v     b8_v      b9_v    b10_v
order_book_id datetime                                                                                                                       ...
00001.XHKG    2025-03-03 09:20:38.791   2025-03-03  39.05  39.05  39.05  39.05       38.85   731329.0      28436662.0       NaN         NaN  ...   0.00   0.00   0.00   0.00   0.00       0.0       0.0      0.0       0.0      0.0
              2025-03-03 09:30:00.107   2025-03-03  39.05  39.05  39.05  39.05       38.85   731829.0      28456187.0       NaN         NaN  ...  38.75  38.70  38.65  38.60  38.55    1000.0    3500.0    500.0   11500.0   2500.0
              2025-03-03 09:30:00.150   2025-03-03  39.05  39.10  39.10  39.05       38.85   732329.0      28475737.0       NaN         NaN  ...  38.75  38.70  38.65  38.60  38.55    1000.0    3500.0    500.0   11500.0   2500.0
              2025-03-03 09:30:00.151   2025-03-03  39.05  39.15  39.15  39.05       38.85   736829.0      28651912.0       NaN         NaN  ...  38.80  38.75  38.70  38.65  38.60   13500.0    1000.0   3500.0     500.0  11500.0
              2025-03-03 09:30:01.026   2025-03-03  39.05  39.15  39.15  39.05       38.85   737329.0      28671487.0       NaN         NaN  ...  38.80  38.75  38.70  38.65  38.60   13500.0    1000.0   3500.0     500.0  21500.0
...                                            ...    ...    ...    ...    ...         ...        ...             ...       ...         ...  ...    ...    ...    ...    ...    ...       ...       ...      ...       ...      ...
              2025-03-03 15:59:38.721   2025-03-03  39.05  39.15  39.55  38.90       38.85  7474200.0     292224839.0       NaN         NaN  ...  38.85  38.80  38.75  38.70  38.65  100500.0  225000.0  12500.0  167000.0   6500.0
              2025-03-03 15:59:49.550   2025-03-03  39.05  39.15  39.55  38.90       38.85  7475200.0     292263989.0       NaN         NaN  ...  38.85  38.80  38.75  38.70  38.65  100500.0  225000.0  12500.0  167000.0   6500.0
              2025-03-03 15:59:50.546   2025-03-03  39.05  39.10  39.55  38.90       38.85  7475700.0     292283539.0       NaN         NaN  ...  38.85  38.80  38.75  38.70  38.65  100500.0  225000.0  12500.0  167000.0   6500.0
              2025-03-03 15:59:51.898   2025-03-03  39.05  39.15  39.55  38.90       38.85  7476200.0     292303114.0       NaN         NaN  ...  38.85  38.80  38.75  38.70  38.65  100500.0  225000.0  12500.0  167000.0   6500.0
              2025-03-03 16:08:13.506   2025-03-03  39.05  39.15  39.55  38.90       38.85  8207200.0     320921764.0       NaN         NaN  ...   0.00   0.00   0.00   0.00   0.00       0.0       0.0      0.0       0.0      0.0

[1317 rows x 52 columns]
```

## 港股财务数据 {#rqdata-API-financials_hk}

### get_pit_financials_ex - 查询季度财务信息(point-in-time 形式) {#rqdata-API-get_pit_financials_ex_hk}

```python
get_pit_financials_ex(order_book_ids, fields, start_quarter, end_quarter, date=None, statements='latest', market='cn')
```

以 point-in-time 方式获取港股季度基础财务数据。例如支持利润表、资产负债表、现金流量表三大表字段，也支持按 `latest` 或 `all` 查询记录。

::: tip 注意事项

该 API 返回的因子值均为做了港币汇率转换后的值，除了货币单位为港币的合约，其余并非财报披露的原始值。若需获取原始值，请参考[hk.get_detailed_financial_items-params](#rqdata-API-hk_get_detailed_financial_items)

:::

#### 参数 {#rqdata-API-get_pit_financials_ex_hk-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                       |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list ，该参数必填                                                                              |
| fields         | _list_                                                         | **必填参数**，需要传入的财务字段。支持的字段仅限<b>利润表、资产负债表、现金流量表三大表字段</b>，具体字段见下方返回。                                      |
| start_quarter  | _str_                                                          | **必填参数**，财报回溯查询的起始报告期，例如'2015q2'代表 2015 年半年报， 该参数必填 。                                                                     |
| end_quarter    | _str_                                                          | **必填参数**，财报回溯查询的截止报告期，例如'2015q4'代表 2015 年年报，该参数必填。                                                                         |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认查询日期为当前最新日期                                                                                                                       |
| statements     | _str_                                                          | 基于查询日期，返回某一个报告期的所有记录或最新一条记录，设置 statements 为 all 时返回所有记录，statements 等于 latest 时返回最新的一条记录，默认为 latest. |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                        |

#### 返回 {#rqdata-API-get_pit_financials_ex_hk-return}

_pandas DataFrame_

| 字段        | 类型               | 说明                                                                                                                                                                                                                                               |
| ----------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| quarter     | _str_              | 报告期                                                                                                                                                                                                                                             |
| info_date   | _pandas.Timestamp_ | 公告发布日                                                                                                                                                                                                                                         |
| fields      | _list_             | 返回的财务字段。返回的字段仅限<b>利润表、资产负债表、现金流量表三大表字段</b>，具体字段见下方返回。                                                                                                                                                |
| if_adjusted | _int_              | 是否为非当期财报数据, 0 代表当期，1 代表非当期（比如 18 年的财报会披露本期和上年同期的数值，17 年年报的财务数值在 18 年年报中披露的记录则为非当期， 17 年年报的财务数值在 17 年年报中披露则为当期。                                                |
| fiscal_year | _pandas.Timestamp_ | 财政年度                                                                                                                                                                                                                                           |
| standard    | _str_              | 会计准则，[中国会计准则](#Chinese_standards)、[非中国会计准则\_金融公司](#nonchinese_finance_standards)、[非中国会计准则\_保险公司](#nonchinese_insurance_standards)、[非中国会计准则\_非金融非保险公司](#non_chinese_finance_insurance_standards) |

##### 中国会计准则 {#Chinese_standards}

<br/>

###### 利润表 {#income_statement_chinese}

| 字段                                              | 释义、备注                                           |
| ------------------------------------------------- | ---------------------------------------------------- |
| other_income_equity_classified_income_statement   | 2.1 权益法下在被投资单位以后将重分类进损益的其他综合 |
| remearsured_other_income                          | 1.1 重新计量设定收益计划净负债或净资产的变动         |
| other_income_equity_unclassified_income_statement | 1.2 权益法下在被投资单位不能重分类进损益的其他综合   |
| other_debt_investment_change                      | 2.7 其他债权投资公允价值变动                         |
| assets_reclassified_other_income                  | 2.8 金融资产重分类计入其他综合收益的金额             |
| other_equity_instruments_change                   | 1.3 其他权益工具投资公允价值变动                     |
| other_debt_investment_reserve                     | 2.9 其他债权投资信用减值准备                         |
| corporate_credit_risk_change                      | 1.4 企业自身信用风险公允价值变动                     |
| cash_flow_hedging_effective_portion               | 2.4 现金流量套期损益的有效部分                       |
| foreign_currency_statement_converted_difference   | 2.5 外币财务报表折算差额                             |
| others                                            | 2.6 其他（以后能重分类进损益表的其他综合收益）       |
| other_income_minority                             | 归属于少数股东的其他综合收益的税后净额               |
| other_income_parent_company                       | 归属于母公司所有者的其他综合收益的税后净额           |
| net_profit_parent_company                         | 归属于母公司所有者的净利润                           |
| other_income_unclassified_income_statement        | （一）以后不能重分类进损益的其他综合收益             |
| continuous_operation_net_profit                   | 持续经营净利润                                       |
| other_income_classified_income_statement          | （二）以后将重分类进损益的其他综合收益               |
| discontinued_operation_net_profit                 | 终止经营净利润                                       |
| minority_profit                                   | 少数股东损益                                         |
| exchange_gains_or_losses                          | 汇兑收益                                             |
| net_open_hedge_income                             | 净敞口套期收益                                       |
| non_operating_expense                             | 减：营业外支出                                       |
| income_tax                                        | 减：所得税                                           |
| policy_dividend_payout                            | 保单红利支出                                         |
| total_expense                                     | 营业总成本                                           |
| reinsurance_cost                                  | 分保费用                                             |
| fair_value_change_income                          | 加：公允价值变动净收益                               |
| ga_expense                                        | 管理费用                                             |
| non_operating_revenue                             | 加：营业外收入                                       |
| other_revenue                                     | 其他收益                                             |
| interest_income                                   | 其中：利息收入                                       |
| other_income                                      | 其他综合收益的税后净额                               |
| cost_of_goods_sold                                | 减：营业成本                                         |
| operating_revenue                                 | 营业收入                                             |
| financing_interest_income                         | 其中：利息收入(财务费用)                             |
| financing_interest_expense                        | 其中:利息费用(财务费用)                              |
| profit_from_operation                             | 营业利润                                             |
| profit_before_tax                                 | 利润总额                                             |
| investment_income                                 | 加：投资净收益                                       |
| refunded_premiums                                 | 退保金                                               |
| net_profit                                        | 净利润                                               |
| adjust_credit_asset_impairment                    | 信用减值损失                                         |
| r_n_d                                             | 研发费用                                             |
| revenue                                           | 营业总收入                                           |
| earned_premiums                                   | 已赚保费                                             |
| financing_expense                                 | 财务费用                                             |
| adjust_asset_impairment                           | 资产减值损失                                         |
| disposal_income_on_asset                          | 资产处置收益                                         |
| selling_expense                                   | 销售费用                                             |
| invest_income_associates                          | 其中：对联营合营企业的投资收益                       |
| commission_income                                 | 其中：手续费及佣金收入                               |
| insurance_commission_expense                      | 手续费及佣金支出(成本)                               |
| fully_diluted_earnings_per_share                  | 稀释每股收益                                         |
| total_income_minority                             | 归属于少数股东的综合收益总额                         |
| basic_earnings_per_share                          | 基本每股收益                                         |
| total_income_parent_company                       | 归属于母公司所有者的综合收益总额                     |
| total_income                                      | 综合收益总额                                         |
| classified_by_continuity_operation                | (一)按经营持续性分类                                 |
| classified_by_ownership                           | (二)按所有权归属分类                                 |
| reinsurance                                       | 减：分出保费                                         |
| premiums_income                                   | 保险业务收入                                         |
| financial_asset_available_for_sale_change         | 2.2 可供出售金融资产公允价值变动损益                 |
| reinsurance_income                                | 其中：分保费收入                                     |
| unearned_premium_reserve                          | 减：提取未到期责任准备金                             |
| operating_expense                                 | 营业支出                                             |
| amortization_premium_reserve                      | 减：摊回保险责任准备金                               |
| amortization_reinsurance_cost                     | 减：摊回分保费用                                     |
| amortization_expense                              | 减：摊回赔付支出                                     |
| compensation_expense                              | 赔付支出                                             |
| premium_reserve                                   | 提取保险责任准备金                                   |
| o_n_a_expense                                     | 业务及管理费                                         |
| disposal_loss_on_asset                            | 其中：非流动资产处置净损失                           |
| net_interest_income                               | 利息净收入                                           |
| interest_expense                                  | 其中：利息支出                                       |
| sub_issue_security_income                         | 其中：证券承销业务净收入                             |
| net_trust_income                                  | 其中：受托客户资产管理业务净收入                     |
| net_proxy_security_income                         | 其中：代理买卖证券业务净收入                         |
| net_commission_income                             | 手续费及佣金净收入                                   |
| financial_asset_hold_to_maturity_change           | 2.3 持有至到期投资重分类为可供出售金融资产损益       |
| commission_expense                                | 其中：手续费及佣金支出                               |
| insurance_service_expense                         | 保险服务费用                                         |
| other_effecting_net_profits_items                 | 加：影响净利润的其他科目                             |

<br/>

###### 资产负债表 {#balance_sheet_chinese}

| 字段                                  | 释义、备注                            |
| ------------------------------------- | ------------------------------------- |
| use_right_assets                      | 使用权资产                            |
| unearned_reserve_receivable           | 应收分保未到期责任准备金              |
| undistributed_profit                  | 未分配利润                            |
| unclaimed_reserve_receivable          | 应收分保未决赔款准备金                |
| unclaimed_indemnity_reserve           | 未决赔款准备金                        |
| uncertained_premium_reserve           | 未到期责任准备金                      |
| treasury_stock                        | 减：库存股                            |
| total_liabilities                     | 负债合计                              |
| total_fixed_assets                    | 固定资产                              |
| total_equity_and_liabilities          | 负债和所有者（或股东权益）总计        |
| total_equity                          | 所有者权益（或股东权益）合计          |
| total_assets                          | 资产总计                              |
| tax_payable                           | 应交税费                              |
| surplus_reserve                       | 盈余公积                              |
| sub_issue_security_proceeds           | 代理承销证券款                        |
| specific_reserve                      | 专项储备                              |
| short_term_loans                      | 短期借款                              |
| short_term_debt                       | 应付短期债券                          |
| settlement_provision                  | 结算备付金                            |
| resale_financial_assets               | 买入返售金融资产                      |
| reinsurance_reserve_receivable        | 应收分保合同准备金                    |
| reinsurance_receivable                | 应收分保账款                          |
| reinsurance_payable                   | 应付分保账款                          |
| refundable_deposits                   | 存出保证金                            |
| refundable_capital_deposits           | 存出资本保证金                        |
| real_estate_investment                | 投资性房地产                          |
| proxy_security_proceeds               | 代理买卖证券款                        |
| prepayment                            | 预付账款                              |
| preference_shares                     | 其中：优先股（应付债券）              |
| precious_metals                       | 贵金属                                |
| policy_dividend_payable               | 应付保单红利                          |
| perpetual_equity_debt                 | 其中：永续债（其他权益工具）          |
| perpetual_bond                        | 其中：永续债（应付债券）              |
| payroll_payable                       | 应付职工薪酬                          |
| paid_in_capital                       | 实收资本（或股本）                    |
| other_payable                         | 其他应付款                            |
| other_non_current_liabilities         | 其他非流动负债                        |
| other_non_current_assets              | 其他非流动资产                        |
| other_liabilities                     | 其他负债                              |
| other_illiquidy_financial_assets      | 其他非流动金融资产                    |
| other_equity_investment               | 其他权益工具投资                      |
| other_equity_instruments              | 其他权益工具                          |
| other_debt_investment                 | 其他债权投资                          |
| other_current_liabilities             | 其他流动负债                          |
| other_current_assets                  | 其他流动资产                          |
| other_assets                          | 其他资产                              |
| other_accts_receivable                | 其他应收款                            |
| oil_and_gas_assets                    | 油气资产                              |
| notes_payable                         | 应付票据                              |
| non_current_liability_due_one_year    | 一年内到期的非流动负债                |
| non_current_liabilities               | 非流动负债合计                        |
| non_current_assets                    | 非流动资产合计                        |
| non_current_asset_due_one_year        | 一年内到期的非流动资产                |
| net_long_term_equity_investment       | 长期股权投资                          |
| minority_interest                     | 少数股东权益                          |
| long_term_receivables                 | 长期应收款                            |
| long_term_payable                     | 长期应付款                            |
| long_term_loans                       | 长期借款                              |
| long_term_deferred_expenses           | 长期待摊费用                          |
| loans_advances_to_customers           | 发放贷款和垫款                        |
| loan_account_receivables              | 投资-贷款及应收账款（应收账款类投资） |
| life_reserve_receivable               | 应收分保寿险责任准备金                |
| life_insurance_reserve                | 寿险责任准备金                        |
| liabilities_hold_for_sale             | 划分为持有待售的负债                  |
| lend_capital                          | 拆出资金                              |
| lease_liabilities                     | 租赁负债                              |
| inventory                             | 存货                                  |
| interest_receivable                   | 应收利息                              |
| interest_payable                      | 应付利息                              |
| interbank_deposits                    | 存放同业款项                          |
| intangible_assets                     | 无形资产                              |
| insurer_deposit_investment            | 保户储金及投资款                      |
| insurance_receivable                  | 应收保费                              |
| insurance_contract_reserve            | 长期保险合同准备金                    |
| independent_account_liabilities       | 独立账户负债                          |
| independent_account_assets            | 独立账户资产                          |
| impairment_intangible_assets          | 开发支出                              |
| health_reserve_receivable             | 应收分保长期健康险责任准备金          |
| health_insurance_reserve              | 长期健康险责任准备金                  |
| grants_received                       | 专项应付款                            |
| goodwill                              | 商誉                                  |
| general_reserve                       | 一般风险准备                          |
| fund_providing                        | 融出资金                              |
| foreign_currency_converted_difference | 外币报表折算差额                      |
| fixed_deposits                        | 定期存款                              |
| fixed_asset_to_be_disposed            | 固定资产清理                          |
| financial_receivable                  | 应收款项融资                          |
| financial_liabilities                 | 交易性金融负债                        |
| financial_lease_receivable            | 应收融资租赁款                        |
| financial_asset_hold_to_maturity      | 持有至到期投资                        |
| financial_asset_held_for_trading      | 交易性金融资产                        |
| financial_asset_available_for_sale    | 可供出售金融资产                      |
| estimated_liabilities                 | 预计负债                              |
| equity_preferred_stock                | 其中：优先股（其他权益工具）          |
| equity_parent_company                 | 归属母公司所有者权益合计              |
| engineer_material                     | 工程物资                              |
| dividend_receivable                   | 应收股利                              |
| dividend_payable                      | 应付股利                              |
| derivative_financial_liabilities      | 衍生金融负债                          |
| derivative_financial_assets           | 衍生金融资产                          |
| deposits_of_interbank                 | 同业及其他金融机构存放款项            |
| deposits_from_interbank               | 吸收存款及同业存款                    |
| deposits                              | 吸收存款                              |
| deferred_revenue                      | 长期递延收益                          |
| deferred_income_tax_liabilities       | 递延所得税负债                        |
| deferred_income_tax_assets            | 递延所得税资产                        |
| debt_investment                       | 债权投资                              |
| current_liabilities                   | 流动负债合计                          |
| current_assets                        | 流动资产合计                          |
| contract_liabilities                  | 合同负债                              |
| contract_assets                       | 合同资产                              |
| construction_in_progress              | 在建工程                              |
| compensation_payable                  | 应付赔付款                            |
| comission_payable                     | 应付手续费及佣金                      |
| client_provision                      | 其中：客户备付金                      |
| client_deposits                       | 其中：客户资金存款                    |
| cash_equivalent                       | 货币资金/现金及存放中央银行款项       |
| capitalized_biological_assets         | 生产性生物资产                        |
| capital_reserve                       | 资本公积                              |
| buy_back_security_proceeds            | 卖出回购金融资产款                    |
| borrowings_from_central_banks         | 向中央银行借款                        |
| borrowings_capital                    | 拆入资金                              |
| bond_payable                          | 应付债券                              |
| bill_receivable                       | 应收票据                              |
| bill_accts_receivable                 | 应收账款                              |
| assets_hold_for_sale                  | 划分为持有待售的资产                  |
| advance_insurance                     | 预收保费                              |
| advance_from_customers                | 预收账款                              |
| accts_payable                         | 应付账款                              |
| accrued_staff_costs                   | 长期应付职工薪酬                      |
| deferred_expense                      | 待摊费用                              |
| subrogation_fee_receivable            | 应收代位追偿款                        |
| insurer_mortgage_loan                 | 保户质押贷款                          |
| bill_accts_payable                    | 应付票据及应付账款                    |
| accrued_expense                       | 预提费用                              |
| deferred_income                       | 递延收益                              |
| financial_lease_payable               | 应付融资租赁款                        |
| security_deposits_received            | 存入保证金                            |
| trade_risk_allowances                 | 交易风险准备                          |
| uncertained_impairment_losses         | 未确认投资损失                        |

<br/>

###### 现金流量表 {#cash_flow_statement_chinese}

| 字段                                             | 释义、备注                                         |
| ------------------------------------------------ | -------------------------------------------------- |
| net_increase_from_other_financial_institutions   | 向其他金融机构拆入资金净增加额                     |
| net_increase_from_central_bank                   | 向中央银行借款净增加额                             |
| cash_paid_for_policy_dividends                   | 支付保单红利的现金                                 |
| cash_paid_for_taxes                              | 支付的各项税费                                     |
| cash_paid_for_employee                           | 支付给职工以及为职工支付的现金                     |
| cash_paid_for_other_financing_activities         | 支付其他与筹资活动有关的现金                       |
| cash_paid_for_other_operation_activities         | 支付其他与经营活动有关的现金                       |
| cash_paid_for_other_investment_activities        | 支付其他与投资活动有关的现金                       |
| cash_paid_for_orignal_insurance                  | 支付原保险合同赔付款项的现金                       |
| net_increase_in_pledge_loans                     | 质押贷款净增加额                                   |
| cash_paid_for_asset                              | 购建固定资产、无形资产和其他长期资产支付的现金     |
| cash_paid_for_goods_and_services                 | 购买商品、接受劳务支付的现金                       |
| cash_received_from_sales_of_goods                | 销售商品、提供劳务收到的现金                       |
| cash_received_from_investors                     | 吸收投资收到的现金                                 |
| cash_equivalent_increase                         | 现金及现金等价物净增加额                           |
| cash_paid_to_acquire_investment                  | 投资支付的现金                                     |
| cash_flow_from_investing_activities              | 投资活动产生的现金流量净额                         |
| cash_received_from_investment_activities         | 投资活动现金流入小计                               |
| cash_paid_for_investment_activities              | 投资活动现金流出小计                               |
| net_cash_deal_from_sub                           | 处置子公司及其他营业单位收到的现金净额             |
| exchange_rate_change_effect                      | 汇率变动对现金的影响                               |
| cash_received_from_disposal_of_investment        | 收回投资收到的现金                                 |
| cash_received_from_reinsurance                   | 收到再保业务现金净额                               |
| cash_received_from_original_insurance            | 收到原保险合同保费取得的现金                       |
| cash_received_from_other_investment_activities   | 收到其他与投资活动有关的现金                       |
| cash_from_other_operating_activities             | 收到其他与经营活动有关的现金                       |
| cash_received_from_other_financing_activities    | 收到其他与筹资活动有关的现金                       |
| refunds_of_taxes                                 | 收到的税费返还                                     |
| net_cash_payment_from_sub                        | 取得子公司及其他营业单位支付的现金净额             |
| cash_received_from_investment                    | 取得投资收益收到的现金                             |
| cash_received_from_financial_institution_borrows | 取得借款收到的现金                                 |
| dividends_paid_to_minority_by_subsidiaries       | 其中:子公司支付给少数股东的股利、利润或偿付的利息  |
| cash_received_from_minority_invest_subsidiaries  | 其中:子公司吸收少数股东投资收到的现金              |
| end_period_cash_equivalent                       | 期末现金及现金等价物余额                           |
| net_increase_from_loans_and_advances             | 客户贷款及垫款净增加额                             |
| net_deposit_increase                             | 客户存款和同业存放款项净增加额                     |
| cash_flow_from_operating_activities              | 经营活动产生的现金流量净额                         |
| cash_from_operating_activities                   | 经营活动现金流入小计                               |
| cash_paid_for_operation_activities               | 经营活动现金流出小计                               |
| begin_period_cash_equivalent                     | 期初现金及现金等价物余额                           |
| net_increase_from_repurchasing_business          | 回购业务资金净增加额                               |
| cash_flow_from_financing_activities              | 筹资活动产生的现金流量净额                         |
| cash_received_from_financing_activities          | 筹资活动现金流入小计                               |
| cash_paid_to_financing_activities                | 筹资活动现金流出小计                               |
| cash_paid_for_dividend_and_interest              | 分配股利、利润或偿付利息支付的现金                 |
| net_increase_from_central_bank_and_banks         | 存放中央银行和同业款项净增加额                     |
| net_increase_from_lending_capital                | 拆出资金净增加额                                   |
| net_increase_from_insurer_deposit_investment     | 保户储金及投资款净增加额                           |
| cash_paid_for_debt                               | 偿还债务支付的现金                                 |
| cash_received_from_interests_and_commissions     | 收取利息、手续费及佣金的现金                       |
| cash_paid_for_comissions                         | 支付利息、手续费及佣金的现金                       |
| cash_received_from_disposal_of_asset             | 处置固定资产、无形资产和其他长期资产收回的现金净额 |
| cash_received_from_issuing_security              | 发行债券收到的现金                                 |
| cash_paid_for_reinsurance                        | 支付再保业务现金净额                               |
| net_increase_from_disposing_financial_assets     | 处置交易性金融资产净增加额                         |
| fixed_asset_depreciation                         | 固定资产折旧                                       |
| intangible_asset_amortization                    | 无形资产摊销                                       |
| assets_depreciation_reserves                     | 加:资产减值准备                                    |
| deferred_expense_amortization                    | 长期待摊费用摊销                                   |
| net_inc_cash_and_equivalents                     | (附注)现金及现金等价物净增加额                     |
| net_increase_from_financial_institutions         | 拆入资金净增加额                                   |
| cash_received_from_proxy_security                | 代理买卖证券收到的现金净额                         |
| net_increase_from\_\_financing_buy_back          | 回购业务资金净增加额(筹资)                         |
| net_increase_from_operating_buy_back             | 返售业务资金净增加额(经营)                         |
| net_increase_from_investing_buy_back             | 返售业务资金净增加额(投资)                         |
| cash_received_from_sub_issue_security            | 代理承销证券收到的现金净额                         |
| cash_received_from_issuing_equity_instruments    | 发行其他权益工具收到的现金                         |

##### 非中国会计准则\_金融公司 {#nonchinese_finance_standards}

<br/>

###### 利润表 {#income_statement_nonchinese_finance}

| 字段                                                       | 释义、备注                            |
| ---------------------------------------------------------- | ------------------------------------- |
| net_interest_income                                        | 净利息收入                            |
| operating_revenue                                          | 经营收入                              |
| operating_expense_before_deducting_impairment              | 营业支出-扣除减值前                   |
| profit_after_tax                                           | 除税后溢利                            |
| profit_before_tax_income                                   | 除税前溢利                            |
| net_income_from_securities_trading_and_investment          | 证券交易及投资净收入                  |
| net_income_from_foreign_exchange_trading                   | 外汇交易净收入                        |
| interest_income                                            | 利息收入                              |
| interest_expense                                           | 利息支出                              |
| attributable_profit_to_associated_company                  | 应占联营公司溢利                      |
| other_operating_income_items                               | 经营收入其他项目                      |
| net_service_fee_income                                     | 净服务费收入                          |
| service_fee_revenue                                        | 服务费收入                            |
| service_fee_expense                                        | 服务费支出                            |
| taxation                                                   | 税项                                  |
| attributable_profit                                        | 股东应占溢利                          |
| minority_profit                                            | 少数股东损益                          |
| other_impairment_and_provisions_income                     | 其他减值及拨备                        |
| diluted_earnings_per_share                                 | 每股摊薄盈利                          |
| dividend_revenue                                           | 股息收入                              |
| basic_earnings_per_share                                   | 每股基本盈利                          |
| revaluation_surplus                                        | 重估盈余                              |
| operating_profit_before_deducting_impairment               | 扣除减值前经营溢利                    |
| other_operating_revenue                                    | 其他经营收入                          |
| other_operating_expense_items                              | 营业支出其他项目                      |
| operating_profit                                           | 经营溢利(补充)                        |
| attributable_profit_to_joint_venture                       | 应占合营公司溢利                      |
| other_operating_profit_items                               | 经营溢利其他项目                      |
| common_shareholders_for_attributable_profit                | 其中:母公司普通股股东应占溢利         |
| other_equity_instruments_holders_for_attributable_profit   | 其中:母公司其他权益工具持有者应占溢利 |
| operating_expense_after_deducting_impairment               | 营业支出-扣除减值后                   |
| designated_net_income_instruments_from_fair_value          | 指定以公平值列账之金融工具净收益      |
| operating_profit_after_deducting_impairment                | 扣除减值后经营溢利                    |
| net_exchange                                               | 汇兑净额                              |
| other_items_before_deducting_impairment                    | 扣除减值前其他项目                    |
| other_profit_items                                         | 溢利其他项目                          |
| discontinued_or_non_continuing_business_profit             | 终止或非持续业务溢利                  |
| profit_adjustment_items_after_tax                          | 除税后溢利调整项目                    |
| loans_and_advance_assets_impairment                        | 贷款及垫款资产减值损失                |
| intangible_assets_amortization_and_impairment              | 无形资产摊销及减值                    |
| employee_compensation_and_benefits                         | 雇员报酬及福利                        |
| depreciation_and_impairment_of_property_machine_and_device | 物业、机器及设备折旧与减值            |
| dividend_per_share                                         | 每股股息                              |
| net_profit_from_selling_fixed_assets                       | 出售固定资产净溢利                    |
| net_profit_from_selling_subcompany                         | 出售附属公司净溢利                    |
| net_rental_income                                          | 租金净收入                            |
| profit_from_selling_assets                                 | 出售资产之溢利                        |
| adjust_credit_asset_impairment                             | 信用减值损失                          |
| adjust_asset_impairment                                    | 资产减值损失                          |
| taxes_and_surcharges                                       | 税金及附加                            |
| goodwill_impairment                                        | 商誉减值                              |
| o_n_a_expense                                              | 业务及管理费                          |
| dividend                                                   | 股息                                  |
| other_revenue                                              | 其他收益                              |
| net_profit_from_selling_investment_property                | 出售投资物业净溢利                    |
| net_open_hedge_income                                      | 净敞口套期收益                        |
| operating_revenue_adjustment_items                         | 经营收入调整项目                      |
| net_insurance_claims_and_policy_holding_liabilities        | 保险索偿净额及保单持有负债            |
| profit_adjustment_items                                    | 溢利调整项目                          |
| attributable_profit_to_adjustment_items                    | 股东应占溢利调整项目                  |
| operating_profit_adjustment_items                          | 经营溢利调整项目                      |
| adjustment_items_before_deducting_impairment               | 扣除减值前调整项目                    |
| adjustment_items_after_deducting_impairment                | 扣除减值后调整项目                    |
| investments_impairment_hold_to_maturity_change             | 持至到期投资减值损失                  |
| financial_asset_impairment_available_for_sale              | 可供出售金融资产减值损失              |
| net_profit_from_securities_available_for_sale              | 出售可供出售证券净溢利                |
| deferred_tax                                               | 递延税项                              |
| other_items_of_profit_after_tax                            | 除税后溢利其他项目                    |

<br/>

###### 资产负债表 {#balance_sheet_nonchinese_finance}

| 字段                                                                                             | 释义、备注                                     |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| revaluation_reserve                                                                              | 重估储备                                       |
| fixed_assets                                                                                     | 固定资产                                       |
| borrowings_from_central_banks                                                                    | 向中央银行借款                                 |
| derivative_financial_liabilities                                                                 | 衍生性金融负债                                 |
| derivative_financial_assets                                                                      | 衍生性金融资产                                 |
| issued_bonds                                                                                     | 已发行债券                                     |
| financial_assets_recognized_in_profit_or_loss_at_fair_value                                      | 按公平值入损益金融资产                         |
| resale_financial_assets                                                                          | 买入返售金融资产                               |
| buy_back_security_proceeds                                                                       | 卖出回购金融资产款                             |
| deferred_tax_assets                                                                              | 递延税项资产                                   |
| equity_of_joint_venture_companies                                                                | 联营公司权益                                   |
| liabilities_interbank_and_other_financial_institution_deposits                                   | 银行同业及其他金融机构存款(负债)               |
| other_assets                                                                                     | 其他资产                                       |
| other_accounts_and_preparations                                                                  | 其他帐项及准备                                 |
| loans_and_other_accounts                                                                         | 贷款及其他账项                                 |
| customer_deposit                                                                                 | 客户存款                                       |
| total_assets                                                                                     | 总资产                                         |
| total_liabilities                                                                                | 总负债                                         |
| equity                                                                                           | 股本                                           |
| minority_interest                                                                                | 少数股东权益                                   |
| assets_interbank_and_other_financial_institution_deposits                                        | 银行同业及其他金融机构存款(资产)               |
| borrowings_capital                                                                               | 拆入资金                                       |
| lend_capital                                                                                     | 拆出资金                                       |
| shareholders_equity                                                                              | 股东权益                                       |
| cash_on_hand_and_short_term_funds                                                                | 库存现金及短期资金                             |
| total_funding_sources                                                                            | 资金来源合计                                   |
| total_equity_and_liabilities                                                                     | 权益及负债合计                                 |
| payable_taxes                                                                                    | 应交税项                                       |
| undistributed_profit                                                                             | 未分配利润                                     |
| capital_reserve                                                                                  | 资本公积                                       |
| surplus_reserve                                                                                  | 盈余公积                                       |
| other_assets_projects                                                                            | 资产其他项目                                   |
| deferred_tax_liabilities                                                                         | 递延税项负债                                   |
| precious_metals                                                                                  | 贵金属                                         |
| statutory_general_reserve_fund                                                                   | 法定一般准备金                                 |
| goodwill                                                                                         | 商誉                                           |
| intangible_assets                                                                                | 无形资产                                       |
| payroll_payable                                                                                  | 应付职工薪酬                                   |
| other_equity_instruments                                                                         | 其他权益工具                                   |
| real_estate_investment                                                                           | 投资性房地产                                   |
| liabilities_for_other_items                                                                      | 负债其他项目                                   |
| accumulated_losses_retained_profits                                                              | 保留溢利(累计亏损)                             |
| other_reserves                                                                                   | 其他储备                                       |
| reserve                                                                                          | 储备                                           |
| issued_deposit_certificates                                                                      | 已发行存款证                                   |
| issuing_bonds                                                                                    | 发行债券                                       |
| foreign_currency_converted_difference                                                            | 外币报表折算差额                               |
| other_items_related_to_shareholder_equity                                                        | 股东权益其他项目                               |
| investment_in_joint_ventures                                                                     | 对合营企业的投资                               |
| interest_receivable                                                                              | 应收利息                                       |
| trading_financial_assets                                                                         | 交易性金融资产                                 |
| investment_property                                                                              | 投资物业                                       |
| customer_loans_and_other_payments                                                                | 客户贷款及其他款项                             |
| equity_premium                                                                                   | 股本溢价                                       |
| asset_adjustment_project                                                                         | 资产调整项目                                   |
| portfolio_investment                                                                             | 证券投资                                       |
| trade_documents                                                                                  | 贸易票据                                       |
| loan_capital                                                                                     | 借贷资本                                       |
| post_paid_liabilities                                                                            | 后偿负债                                       |
| other_rights_and_interests                                                                       | 其他权益                                       |
| hong_kong_special_administrative_region_government_circulating_banknotes                         | 香港特区政府流通纸币                           |
| hong_kong_sar_government_debt_certificate                                                        | 香港特区政府负债证明书                         |
| financial_asset_available_for_sale                                                               | 可供出售金融资产                               |
| assets_to_be_sold                                                                                | 待出售之资产                                   |
| interest_payable                                                                                 | 应付利息                                       |
| subsidiary_companies_and_other_equity                                                            | 附属公司及其他权益                             |
| accounts_receivable_investments                                                                  | 应收款项类投资                                 |
| issued_debt_instruments                                                                          | 已发行债务工具                                 |
| perpetual_subordinated_capital_securities                                                        | 永续次级资本证券                               |
| translation_reserve                                                                              | 汇兑储备                                       |
| deposit_certificate_held                                                                         | 所持存款证                                     |
| debt_adjustment_project                                                                          | 负债调整项目                                   |
| insurance_contract_assets                                                                        | 保险合同资产                                   |
| transfer_reinsurance_contract_assets                                                             | 分出再保险合同资产                             |
| contract_assets                                                                                  | 合同资产                                       |
| use_right_assets                                                                                 | 使用权资产                                     |
| other_receivables                                                                                | 其他应收款                                     |
| financial_liabilities_recognized_at_fair_value_through_profit_or_loss                            | 以公平值计入损益金融负债                       |
| non_trading_equity_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income | 按公平值计入其他全面收益的非交易性权益工具投资 |
| treasury_stocks                                                                                  | 减:库存股                                      |
| financial_assets_measured_at_amortized_cost                                                      | 以摊余成本计量的金融资产                       |
| lease_liabilities                                                                                | 租赁负债                                       |
| estimated_liabilities                                                                            | 预计负债                                       |
| other_comprehensive_income                                                                       | 其他综合收益                                   |
| financial_assets_recognized_at_fair_value_in_other_comprehensive_income                          | 按公平值计入其他全面收益的金融资产             |
| contract_liabilities                                                                             | 合同负债                                       |
| debt_investment                                                                                  | 债权投资                                       |
| debt_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income               | 按公平值计入其他全面收益的债务工具投资         |
| financial_investment                                                                             | 金融投资                                       |
| insurance_contract_liability                                                                     | 保险合同负债                                   |
| held_for_sale_liabilities                                                                        | 持有待售负债                                   |
| disburse_reinsurance_contract_liabilities                                                        | 分出再保险合同负债                             |
| accounts_receivable_loans                                                                        | 应收贷款                                       |
| goodwill_and_intangible_assets                                                                   | 商誉及无形资产                                 |
| hold_until_maturity_investment                                                                   | 持至到期投资                                   |
| proposed_dividend_payout                                                                         | 拟派股息                                       |
| accumulation_fund                                                                                | 公积金                                         |
| equity_adjustment_project                                                                        | 权益调整项目                                   |
| borrowing_capital                                                                                | 借入资本                                       |
| perpetual_bond                                                                                   | 其中:永续债（其他权益工具）                    |
| preferred_stock                                                                                  | 其中:优先股（其他权益工具）                    |
| statutory_reserve                                                                                | 法定储备                                       |
| other_financial_assets                                                                           | 其他金融资产                                   |
| equity_and_liabilities_special_project                                                           | 负债和权益特殊项目                             |

<br/>

###### 现金流量表 {#cash_flow_statement_nonchinese_finance}

| 字段                                                           | 释义、备注                                     |
| -------------------------------------------------------------- | ---------------------------------------------- |
| cash_paid_to_acquire_investment                                | 投资支付现金                                   |
| net_cash_from_investment_business                              | 投资业务现金净额                               |
| sell_fixed_assets                                              | 出售固定资产                                   |
| profit_from_selling_other_assets                               | 出售其他资产损（益）                           |
| cash_received_from_disposal_of_investment                      | 收回投资所得现金                               |
| acquisition_of_subcompany                                      | 收购附属公司                                   |
| other_impairment_and_provision_cashflow                        | 其他减值与拨备                                 |
| other_bank_operation_assets_change_items                       | 银行—经营资产变动其他项目                      |
| other_operation_business_items                                 | 经营业务其他项目                               |
| bank_borrowings_from_central_banks_change                      | 银行—向中央银行借款增(减)                      |
| net_cash_from_financing_business                               | 融资业务现金净额                               |
| dividend_income_adjustment                                     | 股息（收入）-调整                              |
| paid_financing_dividend                                        | 已付股息(融资)                                 |
| profit_before_tax_cashflow                                     | 除税前溢利(业务利润)                           |
| other_bank_operation_liabilities_changes_items                 | 银行—经营负债变动其他项目                      |
| other_financing_business_items                                 | 融资业务其他项目                               |
| issuing_bond                                                   | 发行债券                                       |
| bank_loan_and_advance_change                                   | 银行—发放贷款及垫款（增）减                    |
| investment_profit                                              | 投资损（益）                                   |
| exchange_rate_impact                                           | 汇率影响                                       |
| repay_loan                                                     | 偿还借款                                       |
| paid_financing_interest                                        | 已付利息(融资)                                 |
| unrealized_exchange_profit                                     | 未实现汇兑损（益）                             |
| bank_client_deposits_change                                    | 银行—客戶存款增(减)                            |
| interest_income_adjustment                                     | 利息(收入)-调整                                |
| interest_expense_adjustment                                    | 利息支出—调整                                  |
| other_fair_value_change                                        | 其他公平值变动                                 |
| profit_from_bank_financial_liabilities_with_fair_value         | 银行—按公平值计入损益的金融负债增(减)          |
| depreciation                                                   | 折旧                                           |
| interest_payment_cash_balance                                  | 支付利息-现金结存                              |
| other_paid_income_tax                                          | 其他已缴所得税                                 |
| absorb_investment_income                                       | 吸收投资所得                                   |
| purchase_resale_financial_assets_change                        | 买入返售金融资产(增)减                         |
| purchase_fixed_assets                                          | 购买固定资产                                   |
| issuance_fee_and_expense_for_redeeming_security                | 发行费用及赎回证券支出                         |
| begin_period_cash                                              | 期初现金                                       |
| net_cash                                                       | 现金净额                                       |
| net_cash_from_operation_business                               | 经营业务现金净额                               |
| operating_profit_before_working_capital_change                 | 营运资金变动前经营溢利                         |
| end_period_cash                                                | 期末现金                                       |
| sell_subsidiary_company                                        | 出售附属公司                                   |
| derivative_financial_instruments_change                        | 衍生金融工具公平值（增）减                     |
| profit_from_bank_financial_assets_with_fair_value              | 银行—按公平值计入损益的金融资产(增)减          |
| other_operation_adjustment_items                               | 经营调整其他项目                               |
| selling_property_machine_and_device_profit                     | 出售物业、机器及设备损（益）                   |
| accts_receivable_and_prepayment_change                         | 应收帐款及预付款(增加)减少                     |
| attributable_profit_to_subcompany                              | 应占附属公司（盈）亏                           |
| other_depreciation_and_amortization                            | 其他折旧及摊销                                 |
| intangible_assets_amortization                                 | 无形资产摊销                                   |
| issuing_stock                                                  | 发行股份                                       |
| exchange_profit                                                | 汇兑损（益）                                   |
| cash_from_operation                                            | 经营产生现金                                   |
| cash_paid_for_intangible_assets_and_other_assets               | 购建无形资产及其他资产                         |
| received_investment_dividend                                   | 已收股息—投资                                  |
| received_investment_interest                                   | 已收利息—投资                                  |
| selling_intangible_and_other_assets                            | 出售无形资产及其他资产                         |
| selling_subcompany_interests_profit                            | 出售附属公司权益损（益）                       |
| other_investment_business_items                                | 投资业务其他项目                               |
| received_operation_dividend                                    | 已收股息-经营                                  |
| received_operation_interest                                    | 已收利息—经营                                  |
| derivative_financial_instruments_increase                      | 衍生金融工具（增）                             |
| paid_hk_profits_tax                                            | 已缴香港利得税                                 |
| bank_deposits_change                                           | 银行—银行存款（增）减                          |
| investment_property_change                                     | 投资物业公平值（增）减                         |
| newly_added_loan                                               | 新增借款                                       |
| interest_collection_cash_balance                               | 收取利息-现金结存                              |
| accts_receivable_change                                        | 应收贷款(增)减                                 |
| profit_from_financial_liabilities_with_fair_value_change       | 按公平值计入损益的金融负债增（减）             |
| paid_operation_interest                                        | 已付利息—经营                                  |
| paid_cn_income_tax                                             | 已缴中国所得税                                 |
| accts_payable_and_accrued_expense_change                       | 应付帐款及应计费用增加(减少)                   |
| accts_payable_from_related_party_change                        | 应付关联方款项增加(减少)                       |
| financial_expense                                              | 财务费用                                       |
| selling_available_for_sale_investment_profit                   | 出售可供出售投资损（益）                       |
| accts_receivable_trade_impairment_reversal                     | 应收贸易账款减值（回拨）                       |
| selling_joint_venture_profit                                   | 出售联营公司损（益）                           |
| profit_from_financial_assets_with_fair_value_change            | 按公平值计入损益的金融资产(增)减               |
| accts_receivable_from_related_party_change                     | 应收关联方款项(增加)减少                       |
| deposit_change                                                 | 存款减少(增加)                                 |
| prepayment_change                                              | 预付款项(增)减                                 |
| inventory_change                                               | 存货(增加)减少                                 |
| cash_equivalent_surplus                                        | 现金及现金等值项目结余                         |
| goodwill_profit_impairment                                     | 商誉减值亏损                                   |
| adjustment_items_for_financing_business                        | 融资业务调整项目                               |
| adjustment_items_for_period_changes                            | 期间变动调整项目                               |
| amortization_or_depreciation_of_use_right_assets               | 使用权资产摊销/折旧                            |
| other_working_capital_change_items                             | 营运资本变动其他项目                           |
| depreciation_of_fixed_oil_gas_and_productive_biological_assets | 固定资产折旧、油气资产折耗、生产性生物资产折旧 |
| amortization_or_depreciation_of_investment_property            | 投资性房地产折旧/摊销                          |
| repay_lease_liabilities                                        | 偿还租赁负债                                   |
| other_cash_from_operation_items                                | 经营产生现金其他项目                           |
| adjustment_items_for_investment_business                       | 投资业务调整项目                               |
| adjustment_items_effecting_net_cash                            | 影响现金净额调整项目                           |
| bad_debts_provision_reversal                                   | 呆坏账拨备（回拨）                             |
| adjustment_items_for_working_capital_change                    | 营运资金变动调整项目                           |
| adjustment_items_for_operation_business                        | 经营业务调整项目                               |
| shares_reduction                                               | 股本减少                                       |
| property_machine_and_device_impairment_reversal                | 物业、厂房及设备减值（回拨）                   |
| available_for_investment_impairment_reversal                   | 可供出售投资减值（回拨）                       |
| deferred_income_amortization                                   | 递延收入摊销                                   |
| adjustment_items_for_operation_adjustment                      | 经营调整调整项目                               |
| developing_property_change                                     | 发展中物业（增）减                             |
| financing_customer_advance_payment_change                      | 融资客户垫款(增)减                             |
| taxation_cashflow                                              | 税项                                           |
| financing_costs_and_investment_return                          | 融资费用及投资回报                             |
| cash_before_financing_for_other_items                          | 融资前现金其他项目                             |
| net_cash_before_financing                                      | 融资前现金净额                                 |
| issuing_stock_bond                                             | 发行股份债券                                   |
| mortgage_bank_deposit_financing_change                         | 已抵押银行存款(增)减-融资                      |
| other_effecting_net_cash_items                                 | 影响现金净额其他项目                           |
| other_period_change_items                                      | 期间变动其他项目                               |
| bank_deposits                                                  | 银行存款                                       |

##### 非中国会计准则\_保险公司 {#nonchinese_insurance_standards}

<br/>

###### 利润表 {#income_statement_nonchinese_insurance}

| 字段                                                         | 释义、备注                    |
| ------------------------------------------------------------ | ----------------------------- |
| exchange_profit_expense                                      | 汇兑损益-支出                 |
| other_income_items                                           | 收入其他项目                  |
| ga_expense                                                   | 管理费用                      |
| total_premium_income                                         | 总保费收入                    |
| financing_expense                                            | 财务费用-支出                 |
| other_expense                                                | 其他支出                      |
| taxation                                                     | 税项                          |
| other_operating_expense_items                                | 支出其他项目                  |
| investment_income                                            | 投资收益                      |
| minority_profit                                              | 少数股东损益                  |
| payment_compensation_and_total_expenses                      | 给付、赔付及费用总计          |
| banks_income                                                 | 银行业务收入                  |
| profit_after_tax                                             | 除税后溢利                    |
| profit_before_tax_income                                     | 除税前溢利                    |
| total_income                                                 | 收入合计                      |
| attributable_profit                                          | 股东应占溢利                  |
| basic_earnings_per_share                                     | 每股基本盈利                  |
| diluted_earnings_per_share                                   | 每股摊薄盈利                  |
| dividend_per_share                                           | 每股股息                      |
| other_attributable_profit_items                              | 股东应占溢利其他项目          |
| realized_net_premium_income                                  | 已实现净保费收入              |
| commission_expense                                           | 佣金及手续费支出              |
| attributable_profit_to_associated_company_and_joint_ventures | 应占联营企业和合营企业收益    |
| other_payment_and_compensation_items                         | 给付及赔付其他项目            |
| adjust_asset_impairment                                      | 资产减值损失                  |
| underwriting_financing_loss                                  | 承保财务损失                  |
| premium_allocation                                           | 分出保费的分摊                |
| distribut_reinsurance_financial_income                       | 减:分出再保险财务收益         |
| premium_expense                                              | 保险服务费用                  |
| amortization_premium_expense                                 | 减:摊回保险服务费             |
| adjust_credit_asset_impairment                               | 信用减值损失                  |
| net_expense_from_reinsurance_contract                        | 分出再保险合同的净支出        |
| other_insurance_expense                                      | 其他保险开支                  |
| ga_expense_after_tax                                         | 财务费用-税前                 |
| investment_contract_expense                                  | 投资合同支出                  |
| other_profit_items                                           | 利润其他项目                  |
| exchange_profit_income                                       | 汇兑损益-收入                 |
| dividend                                                     | 股息                          |
| net_premium_income                                           | 净保费收入                    |
| reinsurance                                                  | 分出保费                      |
| net_payment_compensation                                     | 给付及赔付净额                |
| unearned_premium_reserve                                     | 提取未到期责任准备金          |
| commissions                                                  | 佣金收入                      |
| amortization_reinsurance                                     | 摊回分保费用                  |
| life_insurance_death_and_other_benefits                      | 寿险死亡和其他给付            |
| long_term_life_insurance_contract_liabilities                | 提取长期寿险合同负债          |
| indemnity_expense_and_unclaimed_indemnity_reserve            | 赔款支出及提取未决赔款准备金  |
| amortization_compensation_and_policyholders_benefits         | 摊回赔款及保户利益            |
| policy_dividend_payout                                       | 保单红利支出                  |
| savings_based_interest_expenses_of_policyholders             | 保户储蓄型利息支出            |
| statutory_insurance_protection_fund_reserve                  | 提取法定保险保障基金          |
| operating_profit                                             | 经营溢利                      |
| taxes_and_surcharges                                         | 税金及附加                    |
| continuous_operation_after_tax_profit                        | 持续经营业务税后利润          |
| discontinued_or_non_continuing_business_profit               | 终止或非持续业务溢利          |
| common_shareholders_for_attributable_profit                  | 其中:母公司普通股股东应占溢利 |
| other_equity_instruments_holders_for_attributable_profit     | 其他权益工具持有者应占溢利    |

<br/>

###### 资产负债表 {#balance_sheet_nonchinese_insurance}

| 字段                                                                                             | 释义、备注                                     |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| cash_and_equivalents                                                                             | 现金及等价物                                   |
| loan                                                                                             | 贷款                                           |
| insurance_contract                                                                               | 保险合同                                       |
| refundable_capital_deposits                                                                      | 存出资本保证金                                 |
| special_asset_projects                                                                           | 资产特殊项目                                   |
| equity                                                                                           | 股本                                           |
| fixed_assets                                                                                     | 固定资产                                       |
| liabilities_for_other_items                                                                      | 负债其他项目                                   |
| minority_interest                                                                                | 少数股东权益                                   |
| undistributed_profit                                                                             | 未分配利润                                     |
| derivative_financial_liabilities                                                                 | 衍生金融负债                                   |
| financial_liabilities_recognized_at_fair_value_through_profit_or_loss                            | 以公平值计入损益金融负债                       |
| financial_assets_recognized_in_profit_or_loss_at_fair_value                                      | 按公平值入损益金融资产                         |
| total_liabilities                                                                                | 总负债                                         |
| resale_financial_assets                                                                          | 买入返售金融资产                               |
| investment_in_joint_ventures_and_associates                                                      | 于联营企业和合营企业的投资                     |
| accounts_payable_to_banks_and_other_financial_institutions                                       | 应付银行及其他金融机构款项                     |
| reserve                                                                                          | 储备                                           |
| shareholders_equity                                                                              | 股东权益                                       |
| total_equity                                                                                     | 总权益                                         |
| total_equity_and_total_liabilities                                                               | 总权益及总负债                                 |
| total_assets                                                                                     | 总资产                                         |
| other_items_related_to_shareholder_equity                                                        | 股东权益其他项目                               |
| investment_contract                                                                              | 投资合同                                       |
| other_rights_and_interests                                                                       | 其他权益                                       |
| accumulated_losses_retained_profits                                                              | 保留溢利(累计亏损)                             |
| receivable_investment_income                                                                     | 应收投资收益                                   |
| deferred_tax_assets                                                                              | 递延税项资产                                   |
| property_factory_and_equipment                                                                   | 物业厂房及设备                                 |
| investment_property                                                                              | 投资物业                                       |
| recoverable_taxes                                                                                | 可收回税项                                     |
| current_income_tax_liabilities                                                                   | 当期所得税负债                                 |
| debt_securities                                                                                  | 债务证券                                       |
| statutory_deposit                                                                                | 法定存款                                       |
| perpetual_subordinated_capital_securities                                                        | 永续次级资本证券                               |
| net_assets                                                                                       | 净资产                                         |
| sell_repurchased_securities                                                                      | 卖出回购证券                                   |
| financial_asset_hold_to_maturity                                                                 | 持有至到期投资                                 |
| fixed_deposits                                                                                   | 定期存款                                       |
| financial_asset_available_for_sale                                                               | 可供出售金融资产                               |
| investments_classified_as_loans_and_receivables                                                  | 归入贷款及应收款的投资                         |
| advance_insurance                                                                                | 预收保费                                       |
| proposed_dividend_payout                                                                         | 拟派股息                                       |
| equity_of_joint_venture_companies                                                                | 联营公司权益                                   |
| use_right_assets                                                                                 | 使用权资产                                     |
| insurance_contract_assets                                                                        | 保险合同资产                                   |
| debt_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income               | 按公平值计入其他全面收益的债务工具投资         |
| financial_assets_measured_at_amortized_cost                                                      | 以摊余成本计量的金融资产                       |
| disburse_reinsurance_contract_liabilities                                                        | 分出再保险合同负债                             |
| non_trading_equity_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income | 按公平值计入其他全面收益的非交易性权益工具投资 |
| contract_liabilities                                                                             | 合同负债                                       |
| financial_assets_recognized_at_fair_value_in_other_comprehensive_income                          | 按公平值计入其他全面收益的金融资产             |
| treasury_stocks                                                                                  | 减:库存股                                      |
| prepaid_lease_payment                                                                            | 预付租赁付款                                   |
| transfer_reinsurance_contract_assets                                                             | 分出再保险合同资产                             |
| other_loans_non_current                                                                          | 其他贷款(非流动)                               |
| insurance_accounts_payable_current_liabilities                                                   | 保险应付账款-流动负债                          |
| derivative_financial_instruments_current_assets                                                  | 衍生金融工具-流动资产                          |
| goodwill_and_intangible_assets                                                                   | 商誉及无形资产                                 |
| portfolio_investment                                                                             | 证券投资                                       |
| other_reserves                                                                                   | 其他储备                                       |
| translation_reserve                                                                              | 汇兑储备                                       |
| reinsurance_assets                                                                               | 再保险资产                                     |
| receivable_premium                                                                               | 应收保费                                       |
| insurance_accounts_payable                                                                       | 保险应付账款                                   |
| dealing_with_subordinated_debt                                                                   | 应付次级债                                     |
| pending_compensation_preparation                                                                 | 未决赔款准备                                   |
| policyholder_savings                                                                             | 保户储金                                       |
| payable_reinsurance_premiums                                                                     | 应付再保险保费                                 |
| payable_policyholder_dividends                                                                   | 应付保户红利                                   |
| deposit_certificate                                                                              | 存款证                                         |
| accounts_receivable_reinsurance                                                                  | 应收分保账款                                   |
| guarantor_pledged_loan                                                                           | 保户质押贷款                                   |
| insurance_and_other_receivables                                                                  | 保险及其他应收款项                             |
| equity_securities_and_unit_trust_fund_investment_portfolio                                       | 股本证券及单位信托基金投资组合                 |
| other_equity_instruments                                                                         | 其他权益工具                                   |
| shareholder_equity_adjustment_project                                                            | 股东权益调整项目                               |
| holding_liabilities_for_sale                                                                     | 持有待售负债                                   |
| equity_premium                                                                                   | 股本溢价                                       |
| expected_liabilities                                                                             | 预计负债                                       |
| holding_assets_for_sale                                                                          | 持有待售资产                                   |
| other_financial_assets_non_current                                                               | 其他金融资产(非流动)                           |
| accounts_receivable_loans_current                                                                | 应收贷款(流动)                                 |
| financial_investment                                                                             | 金融投资                                       |
| intangible_assets                                                                                | 无形资产                                       |
| goodwill                                                                                         | 商誉                                           |
| real_estate_investment                                                                           | 投资性房地产                                   |
| bill_accts_receivable                                                                            | 应收帐款                                       |
| accts_payable                                                                                    | 应付帐款                                       |
| prepayment_deposits_and_other_receivables                                                        | 预付款按金及其他应收款                         |
| deposit_funds_from_the_central_bank                                                              | 存放中央银行款项                               |
| interest_receivable                                                                              | 应收利息                                       |
| payable_taxes                                                                                    | 应付税项                                       |
| current_accts_payable_from_related_party                                                         | 应付关连方款项(流动)                           |
| provision_current                                                                                | 拨备（流动）                                   |
| unfired_liability_reserve                                                                        | 未到期责任准备金                               |
| investment_contract_liabilities_current_liabilities                                              | 投资合同负债-流动负债                          |
| customers_deposit                                                                                | 客户存款                                       |
| buy_back_security_proceeds                                                                       | 卖出回购金融资产款                             |
| reinsurance_contract_liabilities                                                                 | 保险合同负债                                   |
| deferred_tax_liabilities                                                                         | 递延税项负债                                   |
| other_comprehensive_income                                                                       | 其他综合收益                                   |

<br/>

###### 现金流量表 {#cash_flow_statement_nonchinese_insurance}

| 字段                                                           | 释义、备注                                     |
| -------------------------------------------------------------- | ---------------------------------------------- |
| cash_received_from_disposal_of_investment                      | 收回投资所得现金                               |
| sell_fixed_assets                                              | 出售固定资产                                   |
| sell_subsidiary_company                                        | 出售附属公司                                   |
| net_cash_from_investment_business                              | 投资业务现金净额                               |
| cash_paid_to_acquire_investment                                | 投资支付现金                                   |
| paid_financing_dividend                                        | 已付股息(融资)                                 |
| paid_financing_interest                                        | 已付利息(融资)                                 |
| absorb_investment_income                                       | 吸收投资所得                                   |
| issuance_fee_and_expense_for_redeeming_security                | 发行费用及赎回证券支出                         |
| purchase_fixed_assets                                          | 购买固定资产                                   |
| other_financing_business_items                                 | 融资业务其他项目                               |
| other_investment_business_items                                | 投资业务其他项目                               |
| received_investment_interest                                   | 已收利息—投资                                  |
| received_investment_dividend                                   | 已收股息—投资                                  |
| newly_added_loan                                               | 新增借款                                       |
| net_cash_from_operation_business                               | 经营业务现金净额                               |
| net_cash_from_financing_business                               | 融资业务现金净额                               |
| issuing_bond                                                   | 发行债券                                       |
| end_period_cash                                                | 期末现金                                       |
| begin_period_cash                                              | 期初现金                                       |
| net_cash                                                       | 现金净额                                       |
| exchange_rate_impact                                           | 汇率影响                                       |
| repay_loan                                                     | 偿还借款                                       |
| other_operation_adjustment_items                               | 经营调整其他项目                               |
| other_depreciation_and_amortization                            | 其他折旧及摊销                                 |
| other_operation_business_items                                 | 经营业务其他项目                               |
| operating_profit_before_working_capital_change                 | 营运资金变动前经营溢利                         |
| issuing_stock                                                  | 发行股份                                       |
| interest_payment_cash_balance                                  | 支付利息-现金结存                              |
| interest_collection_cash_balance                               | 收取利息-现金结存                              |
| profit_before_tax_cashflow                                     | 除税前溢利(业务利润)                           |
| cash_paid_for_intangible_assets_and_other_assets               | 购建无形资产及其他资产                         |
| cash_from_operation                                            | 经营产生现金                                   |
| acquisition_of_subcompany                                      | 收购附属公司                                   |
| received_operation_interest                                    | 已收利息—经营                                  |
| received_operation_dividend                                    | 已收股息-经营                                  |
| paid_operation_interest                                        | 已付利息—经营                                  |
| other_paid_income_tax                                          | 其他已缴所得税                                 |
| investment_profit                                              | 投资损（益）                                   |
| inventory_change                                               | 存货(增加)减少                                 |
| accts_receivable_and_prepayment_change                         | 应收帐款及预付款(增加)减少                     |
| profit_from_selling_other_assets                               | 出售其他资产损（益）                           |
| interest_expense_adjustment                                    | 利息支出—调整                                  |
| exchange_profit                                                | 汇兑损（益）                                   |
| intangible_assets_amortization                                 | 无形资产摊销                                   |
| other_fair_value_change                                        | 其他公平值变动                                 |
| other_impairment_and_provision_cashflow                        | 其他减值与拨备                                 |
| deposit_change                                                 | 存款减少(增加)                                 |
| property_machine_and_device_impairment_reversal                | 物业、厂房及设备减值（回拨）                   |
| accts_payable_and_accrued_expense_change                       | 应付帐款及应计费用增加(减少)                   |
| interest_income_adjustment                                     | 利息(收入)-调整                                |
| dividend_income_adjustment                                     | 股息（收入）-调整                              |
| selling_property_machine_and_device_profit                     | 出售物业、机器及设备损（益）                   |
| attributable_profit_to_subcompany                              | 应占附属公司（盈）亏                           |
| selling_joint_venture_profit                                   | 出售联营公司损（益）                           |
| goodwill_profit_impairment                                     | 商誉减值亏损                                   |
| depreciation                                                   | 折旧                                           |
| investment_property_change                                     | 投资物业公平值（增）减                         |
| financial_expense                                              | 财务费用                                       |
| insurance_contract_liabilities_change                          | 保险合同负债增（减）                           |
| bank_deposits                                                  | 银行存款                                       |
| profit_from_financial_assets_with_fair_value_change            | 按公平值计入损益的金融资产(增)减               |
| profit_from_financial_liabilities_with_fair_value_change       | 按公平值计入损益的金融负债增（减）             |
| accts_receivable_change                                        | 应收贷款(增)减                                 |
| paid_hk_profits_tax                                            | 已缴香港利得税                                 |
| cash_and_bank_surplus                                          | 现金及银行结余                                 |
| amortization_or_depreciation_of_use_right_assets               | 使用权资产摊销/折旧                            |
| other_working_capital_change_items                             | 营运资本变动其他项目                           |
| amortization_or_depreciation_of_investment_property            | 投资性房地产折旧/摊销                          |
| repay_lease_liabilities                                        | 偿还租赁负债                                   |
| depreciation_of_fixed_oil_gas_and_productive_biological_assets | 固定资产折旧、油气资产折耗、生产性生物资产折旧 |
| bad_debts_provision_reversal                                   | 呆坏账拨备（回拨）                             |
| shares_reduction                                               | 股本减少                                       |
| available_for_investment_impairment_reversal                   | 可供出售投资减值（回拨）                       |
| accts_receivable_trade_impairment_reversal                     | 应收贸易账款减值（回拨）                       |
| derivative_financial_instruments_change_cashflow               | 衍生金融工具公平值（增）减                     |
| selling_available_for_sale_investment_profit                   | 出售可供出售投资损（益）                       |
| selling_subcompany_interests_profit                            | 出售附属公司权益损（益）                       |
| adjustment_items_for_operation_adjustment                      | 经营调整调整项目                               |
| accts_receivable_from_related_party_change                     | 应收关联方款项(增加)减少                       |
| other_cash_from_operation_items                                | 经营产生现金其他项目                           |
| accts_payable_from_related_party_change                        | 应付关联方款项增加(减少)                       |
| advance_from_customers_increase                                | 预收款项增（减）                               |
| prepayment_change                                              | 预付款项(增)减                                 |
| derivative_financial_instruments_change                        | 衍生金融工具（增）                             |
| accts_receivable_insurance_change                              | 保险业务应收款(增)减                           |
| accts_payable_reinsurance_change                               | 应付分保账款增（减）                           |
| policyholder_investment_contract_liabilities_change            | 保单持有人投资合同负债增（减）                 |
| bank_client_deposits_change                                    | 银行—客戶存款增(减)                            |
| paid_cn_income_tax                                             | 已缴中国所得税                                 |
| paid_operation_dividend                                        | 己付股息-经营                                  |
| adjustment_items_for_operation_business                        | 经营业务调整项目                               |
| taxation_cashflow                                              | 税项                                           |
| financing_costs_and_investment_return                          | 融资费用及投资回报                             |
| restricted_cash_change                                         | 受限制现金(增)减                               |
| selling_intangible_and_other_assets                            | 出售无形资产及其他资产                         |
| net_cash_before_financing                                      | 融资前现金净额                                 |
| issuing_stock_bond                                             | 发行股份债券                                   |
| other_effecting_net_cash_items                                 | 影响现金净额其他项目                           |
| other_period_change_items                                      | 期间变动其他项目                               |
| cash_equivalent_surplus                                        | 现金及现金等值项目结余                         |

##### 非中国会计准则\_非金融非保险公司 {#non_chinese_finance_insurance_standards}

<br/>

###### 利润表 {#income_statement_nonchinese_nonfinance}

| 字段                                                                          | 释义、备注                            |
| ----------------------------------------------------------------------------- | ------------------------------------- |
| turnover                                                                      | 营业额                                |
| operating_revenue                                                             | 营运收入                              |
| operating_profit                                                              | 经营溢利                              |
| profit_after_tax                                                              | 除税后溢利                            |
| profit_before_tax_income                                                      | 除税前溢利                            |
| financing_cost                                                                | 融资成本                              |
| salary_and_welfare_expenses                                                   | 薪金福利支出                          |
| other_expense                                                                 | 其他支出                              |
| minority_profit                                                               | 少数股东损益                          |
| attributable_profit                                                           | 股东应占溢利                          |
| sales_and_distribution_expense                                                | 销售及分销费用                        |
| taxation                                                                      | 税项                                  |
| basic_earnings_per_share                                                      | 每股基本盈利                          |
| attributable_profit_to_joint_venture                                          | 应占合营公司溢利                      |
| other_revenue                                                                 | 其他收益                              |
| diluted_earnings_per_share                                                    | 每股摊薄盈利                          |
| depreciation_and_amortization                                                 | 折旧与摊销                            |
| other_income                                                                  | 其他收入                              |
| financing_interest_income                                                     | 利息收入（财务费用）                  |
| other_profit_items                                                            | 溢利其他项目                          |
| cost_to_sales                                                                 | 销售成本                              |
| attributable_profit_to_associated_company                                     | 应占联营公司溢利                      |
| gross_profit                                                                  | 毛利                                  |
| administration_expense                                                        | 行政开支                              |
| r_n_d                                                                         | 研发费用                              |
| operating_interest_expense                                                    | 营运利息支出                          |
| other_cost                                                                    | 其他成本                              |
| investment_property_change_income                                             | 投资物业公平值变动                    |
| other_operating_income_items                                                  | 营运收入其他项目                      |
| other_impairment_and_provision_income                                         | 其他减值及拨备                        |
| other_profit_items_after_tax                                                  | 除税后溢利其他项目                    |
| common_shareholders_for_attributable_profit                                   | 其中:母公司普通股股东应占溢利         |
| continuous_operation_after_tax_profit                                         | 持续经营业务税后利润                  |
| discontinued_or_non_continuing_business_profit                                | 终止或非持续业务溢利                  |
| profit_adjustment_items                                                       | 溢利调整项目                          |
| profit_attributable_to_other_equity_instruments_holders_of_the_parent_company | 其中:母公司其他权益工具持有者应占溢利 |
| derivative_financial_instruments_change_income                                | 衍生金融工具公平值变动                |
| financial_assets_change                                                       | 财务资产公平值变动                    |
| gross_profit_adjustment_project                                               | 毛利调整项目                          |
| attributable_diluted_eps_from_continuous_business                             | 应占来自持续业务摊薄每股盈利          |
| attributable_basic_eps_from_continuous_business                               | 应占来自持续业务基本每股盈利          |
| profit_from_selling_assets                                                    | 出售资产之溢利                        |
| attributable_diluted_eps_from_termination_business                            | 应占来自已终止业务摊薄每股盈利        |
| attributable_basic_eps_from_termination_business                              | 应占来自已终止业务基本每股盈利        |
| attributable_profit_from_termination_business                                 | 股东应占来自已终止业务溢利            |
| attributable_profit_to_non_controlling_interest_from_continuous_business      | 非控股权益应占来自持续业务溢利        |
| attributable_profit_to_non_controlling_interest_from_termination_business     | 非控股权益应占来自已终止业务溢利      |
| attributable_profit_from_continuous_business                                  | 股东应占来自持续业务溢利              |
| dividend                                                                      | 股息                                  |
| other_assets_change                                                           | 其他资产公平值变动                    |
| intangible_assets_impairment                                                  | 无形资产减值                          |
| adjustment_items_for_attributable_profit                                      | 股东应占溢利调整项目                  |
| operating_profit_adjustment_items                                             | 经营溢利调整项目                      |
| goodwill_impairment                                                           | 商誉减值                              |
| profit_adjustment_items_after_tax                                             | 除税后溢利调整项目                    |
| property_machine_and_device_impairment                                        | 物业、机器及设备减值                  |
| deferred_tax                                                                  | 递延税项                              |
| revaluation_surplus                                                           | 重估盈余                              |
| adjust_asset_impairment                                                       | 资产减值损失                          |
| investment_income                                                             | 投资收益                              |
| taxes_and_surcharges                                                          | 税金及附加                            |
| net_exchange                                                                  | 汇兑净额                              |
| brokerage_commission_income                                                   | 经纪佣金收入                          |
| designated_net_income_assets_from_fair_value                                  | 指定以公平值列账之资产净收益          |
| commission_expense                                                            | 佣金及手续费支出                      |
| total_cost                                                                    | 总成本                                |
| assets_expense_income                                                         | 资产管理费收入                        |
| adjust_credit_asset_impairment                                                | 信用减值损失                          |
| other_attributable_profit_items                                               | 股东应占溢利其他项目                  |
| dividend_per_share                                                            | 每股股息                              |
| other_gross_profit_items                                                      | 毛利其他项目                          |
| attributable_profit_to_jointly_controlled_entity                              | 应占共同控制实体溢利                  |
| other_operating_profit_items                                                  | 经营溢利其他项目                      |
| operating_revenue_adjustment_items                                            | 营运收入调整项目                      |
| commission_income                                                             | 手续费及佣金收入                      |
| interest_income                                                               | 利息收入                              |
| investment_recognition_impairment_available_for_sale                          | 可供出售投资确认减值亏损              |
| operating_expense_adjustment_items                                            | 营业支出调整项目                      |
| other_equity_instruments_holders_for_attributable_profit                      | 其他权益工具持有者应占溢利            |

<br/>

###### 资产负债表 {#balance_sheet_nonchinese_nonfinance}

| 字段                                                                                             | 释义、备注                                     |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| current_financial_leasing_liabilities                                                            | 融资租赁负债(流动)                             |
| total_equity_and_total_liabilities                                                               | 总权益及总负债                                 |
| deferred_tax_liabilities                                                                         | 递延税项负债                                   |
| payable_taxes                                                                                    | 应付税项                                       |
| deferred_tax_assets                                                                              | 递延税项资产                                   |
| prepaid_and_receivable_taxes                                                                     | 预缴及应收税项                                 |
| non_current_deferred_income                                                                      | 递延收入(非流动)                               |
| current_deferred_income                                                                          | 递延收入(流动)                                 |
| equity_of_the_joint_venture_company                                                              | 合营公司权益                                   |
| other_items_of_current_assets                                                                    | 流动资产其他项目                               |
| non_current_financial_leasing_liabilities                                                        | 融资租赁负债(非流动)                           |
| other_reserves                                                                                   | 其他储备                                       |
| current_financial_assets_recognized_at_fair_value_through_profit_or_loss                         | 按公平值入损益金融资产-流动                    |
| non_current_financial_assets_recognized_at_fair_value_through_profit_or_loss                     | 按公平值入损益金融资产-非流动                  |
| non_current_assets_other_items                                                                   | 非流动资产其他项目                             |
| current_assets_derivative_financial_instruments                                                  | 衍生金融工具-流动资产                          |
| current_liabilities_derivative_financial_instruments                                             | 衍生金融工具-流动负债                          |
| non_current_assets_derivative_financial_instruments                                              | 衍生金融工具-非流动资产                        |
| non_current_liabilities_derivative_financial_instruments                                         | 衍生金融工具-非流动负债                        |
| advance_receipts                                                                                 | 预收款项                                       |
| non_current_liabilities_and_other_items                                                          | 非流动负债其他项目                             |
| shareholders_equity                                                                              | 股东权益                                       |
| goodwill                                                                                         | 商誉                                           |
| other_current_liabilities_projects                                                               | 流动负债其他项目                               |
| other_non_current_liabilities                                                                    | 其他非流动负债                                 |
| current_assets                                                                                   | 流动资产合计                                   |
| current_liabilities                                                                              | 流动负债合计                                   |
| net_current_assets                                                                               | 净流动资产                                     |
| total_assets                                                                                     | 总资产                                         |
| total_liabilities                                                                                | 总负债                                         |
| bank_loans_and_overdrafts                                                                        | 银行贷款及透支                                 |
| long_term_bank_loans                                                                             | 长期银行贷款                                   |
| fixed_assets                                                                                     | 固定资产                                       |
| total_equity                                                                                     | 总权益                                         |
| equity                                                                                           | 股本                                           |
| non_current_assets                                                                               | 非流动资产合计                                 |
| non_current_liabilities                                                                          | 非流动负债合计                                 |
| minority_interest                                                                                | 少数股东权益                                   |
| accumulated_losses_retained_profits                                                              | 保留溢利(累计亏损)                             |
| cash_and_equivalents                                                                             | 现金及等价物                                   |
| other_items_related_to_shareholder_equity                                                        | 股东权益其他项目                               |
| current_provision                                                                                | 拨备（流动）                                   |
| non_current_provision                                                                            | 拨备（非流动）                                 |
| accounts_receivable                                                                              | 应收帐款                                       |
| accounts_payable                                                                                 | 应付帐款                                       |
| long_term_payable                                                                                | 长期应付款                                     |
| translation_reserve                                                                              | 汇兑储备                                       |
| intangible_assets                                                                                | 无形资产                                       |
| other_non_current_assets                                                                         | 其他非流动资产                                 |
| land_use_right                                                                                   | 土地使用权                                     |
| property_factory_and_equipment                                                                   | 物业厂房及设备                                 |
| construction_in_progress                                                                         | 在建工程                                       |
| short_term_deposits                                                                              | 短期存款                                       |
| prepayments_deposits_and_other_receivables                                                       | 预付款按金及其他应收款                         |
| inventory                                                                                        | 存货                                           |
| other_investments                                                                                | 其他投资                                       |
| other_payables_and_accrued_expenses                                                              | 其他应付款及应计费用                           |
| due_from_related_parties                                                                         | 应收关联方款项                                 |
| current_accounts_payable_to_related_parties                                                      | 应付关连方款项(流动)                           |
| notes_payable                                                                                    | 应付票据                                       |
| reserve                                                                                          | 储备                                           |
| equity_of_joint_venture_companies                                                                | 联营公司权益                                   |
| total_assets_minus_current_liabilities                                                           | 总资产减流动负债                               |
| advance_payment                                                                                  | 预付款项                                       |
| current_fixed_deposit                                                                            | 定期存款(流动)                                 |
| mortgaged_deposits                                                                               | 已抵押存款                                     |
| retirement_benefit_responsibility                                                                | 退休福利责任                                   |
| investment_property                                                                              | 投资物业                                       |
| non_current_other_loans                                                                          | 其他贷款(非流动)                               |
| net_assets                                                                                       | 净资产                                         |
| non_current_accounts_payable_to_related_parties                                                  | 应付关联方款项(非流动)                         |
| other_current_assets                                                                             | 其他流动资产                                   |
| convertible_notes_and_bonds                                                                      | 可转换票据及债券                               |
| non_current_mortgaged_deposits                                                                   | 已抵押存款 (非流动)                            |
| long_term_receivables                                                                            | 长期应收款                                     |
| current_other_loans                                                                              | 其他贷款(流动)                                 |
| non_current_fixed_deposit                                                                        | 定期存款(非流动)                               |
| short_term_loans                                                                                 | 短期借款                                       |
| total_equity_and_non_current_liabilities                                                         | 总权益及非流动负债                             |
| capital_reserve                                                                                  | 资本公积                                       |
| other_current_liabilities                                                                        | 其他流动负债                                   |
| short_term_investment                                                                            | 短期投资                                       |
| undistributed_profit                                                                             | 未分配利润                                     |
| real_estate_investment                                                                           | 投资性房地产                                   |
| long_term_investment                                                                             | 长期投资                                       |
| non_current_prepaid_rent                                                                         | 预付租金(非流动)                               |
| developing_and_unsold_properties                                                                 | 发展中及待售物业                               |
| funds_deposited_with_peers_and_other_financial_institutions                                      | 存放于同业及其他金融机构的款项                 |
| bill_receivable                                                                                  | 应收票据                                       |
| equity_premium                                                                                   | 股本溢价                                       |
| payroll_payable                                                                                  | 应付职工薪酬                                   |
| adjustment_items_for_current_liabilities                                                         | 流动负债调整项目                               |
| issuing_bonds                                                                                    | 发行债券                                       |
| shareholder_equity_adjustment_project                                                            | 股东权益调整项目                               |
| dividend_payable                                                                                 | 应付股利                                       |
| customer_deposit                                                                                 | 客户存款                                       |
| accrued_staff_costs                                                                              | 长期应付职工薪酬                               |
| adjustment_items_for_non_current_liabilities                                                     | 非流动负债调整项目                             |
| non_current_asset_adjustment_items                                                               | 非流动资产调整项目                             |
| current_asset_adjustment_project                                                                 | 流动资产调整项目                               |
| accounts_receivable_from_contracted_engineering_clients                                          | 应收合约工程客户款项                           |
| equity_of_subsidiary_companies                                                                   | 附属公司权益                                   |
| portfolio_investment                                                                             | 证券投资                                       |
| other_rights_and_interests                                                                       | 其他权益                                       |
| other_equity_instruments                                                                         | 其他权益工具                                   |
| proposed_dividend_payout                                                                         | 拟派股息                                       |
| interest_receivable                                                                              | 应收利息                                       |
| current_prepaid_rent                                                                             | 预付租金(流动)                                 |
| perpetual_subordinated_capital_securities                                                        | 永续次级资本证券                               |
| accumulation_fund                                                                                | 公积金                                         |
| impairment_intangible_assets                                                                     | 开发支出                                       |
| total_assets_minus_total_liabilities                                                             | 总资产减总负债                                 |
| asset_suspension_liability                                                                       | 资产停用负债                                   |
| non_current_investment_contract_liabilities                                                      | 投资合约负债-非流动负债                        |
| current_investment_contract_liabilities                                                          | 投资合同负债-流动负债                          |
| revaluation_reserve                                                                              | 重估储备                                       |
| liabilities_for_other_items                                                                      | 负债其他项目                                   |
| foreign_currency_statement_conversion_reserve                                                    | 外币报表折算储备                               |
| deposit_funds_from_the_central_bank                                                              | 存放中央银行款项                               |
| issued_debt_instruments                                                                          | 已发行债务工具                                 |
| buy_back_security_proceeds                                                                       | 卖出回购金融资产款                             |
| accounts_receivable_from_contract_customers                                                      | 应收合约客户款项                               |
| jointly_controlling_entity_equity                                                                | 共同控制实体权益                               |
| funding_borrowed_current                                                                         | 拆入资金-流动                                  |
| asset_adjustment_project                                                                         | 资产调整项目                                   |
| debt_adjustment_project                                                                          | 负债调整项目                                   |
| contract_liabilities                                                                             | 合同负债                                       |
| use_right_assets                                                                                 | 使用权资产                                     |
| current_financial_liabilities_at_fair_value_through_profit_or_loss                               | 按公平值入损益金融负债-流动                    |
| current_other_financial_assets                                                                   | 其他金融资产(流动)                             |
| current_accounts_receivable_loans                                                                | 应收贷款(流动)                                 |
| contract_assets                                                                                  | 合同资产                                       |
| financial_assets_recognized_at_fair_value_in_other_comprehensive_income                          | 按公平值计入其他全面收益的金融资产             |
| non_current_other_financial_assets                                                               | 其他金融资产(非流动)                           |
| debt_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income               | 按公平值计入其他全面收益的债务工具投资         |
| non_trading_equity_instrument_investments_recognized_at_fair_value_in_other_comprehensive_income | 按公平值计入其他全面收益的非交易性权益工具投资 |
| held_for_sale_liabilities                                                                        | 持有待售负债                                   |
| holding_assets_for_sale                                                                          | 持有待售资产                                   |
| treasury_stocks                                                                                  | 减:库存股                                      |
| current_other_financial_liabilities                                                              | 其他金融负债(流动)                             |
| non_current_other_financial_liabilities                                                          | 其他金融负债(非流动)                           |
| transfer_reinsurance_contract_assets                                                             | 分出再保险合同资产                             |
| financial_assets_measured_at_amortized_cost                                                      | 以摊余成本计量的金融资产                       |
| statutory_reserve                                                                                | 法定储备                                       |
| insurance_contract_liability                                                                     | 保险合同负债                                   |
| financial_liabilities_recognized_at_fair_value_through_profit_or_loss                            | 以公平值计入损益金融负债                       |
| non_current_funding_borrowed                                                                     | 拆入资金-非流动                                |
| other_comprehensive_income                                                                       | 其他综合收益                                   |
| insurance_contract_assets                                                                        | 保险合同资产                                   |
| estimated_liabilities                                                                            | 预计负债                                       |
| debt_investment                                                                                  | 债权投资                                       |
| lend_capital                                                                                     | 拆出资金                                       |
| insurance_and_other_receivables                                                                  | 保险及其他应收款项                             |
| dealing_with_subordinated_debt                                                                   | 应付次级债                                     |
| disburse_reinsurance_contract_liabilities                                                        | 分出再保险合同负债                             |
| fixed_deposits                                                                                   | 定期存款                                       |
| other_receivables                                                                                | 其他应收款                                     |
| non_current_liability_due_one_year                                                               | 一年内到期的非流动负债                         |
| other_equity_investment                                                                          | 其他权益工具投资                               |
| surplus_reserve                                                                                  | 盈余公积                                       |
| financial_receivable                                                                             | 应收款项融资                                   |
| non_current_asset_due_one_year                                                                   | 一年内到期的非流动资产                         |
| derivative_financial_liabilities                                                                 | 衍生金融负债                                   |
| special_asset_projects                                                                           | 资产特殊项目                                   |
| sell_repurchased_securities                                                                      | 卖出回购证券                                   |
| interest_payable                                                                                 | 应付利息                                       |
| negative_goodwill                                                                                | 负商誉                                         |
| goodwill_and_intangible_assets                                                                   | 商誉及无形资产                                 |
| share_capital_and_premium                                                                        | 股本及溢价                                     |
| available_for_sale_financial_assets_current                                                      | 可供出售金融资产(流动)                         |
| available_for_sale_financial_assets_non_current                                                  | 可供出售金融资产(非流动)                       |
| other_assets_projects                                                                            | 资产其他项目                                   |
| borrowing_capital                                                                                | 借入资本                                       |
| unfinished_claims_provision_for_non_current_liabilities                                          | 未决赔款准备-非流动负债                        |
| pending_claims_reserve_current_liabilities                                                       | 未决赔款准备-流动负债                          |
| unfired_liability_reserve                                                                        | 未到期责任准备金                               |
| unfired_risk_reserve                                                                             | 未到期风险准备金                               |
| insurance_accounts_payable_and_current_liabilities                                               | 保险应付账款-流动负债                          |
| customer_advance_payment                                                                         | 客户垫款                                       |
| flow_of_insurance_and_other_receivables                                                          | 保险及其他应收款项-流动                        |
| dividends_receivable                                                                             | 应收股利                                       |
| insurance_and_other_non_current_receivables                                                      | 保险及其他应收款项-非流动                      |
| statutory_deposit                                                                                | 法定存款                                       |
| other_debt_investments                                                                           | 其他债权投资                                   |
| available_for_sale_financial_assets                                                              | 可供出售金融资产                               |
| general_reserve                                                                                  | 一般风险准备                                   |
| equity_adjustment_project                                                                        | 所有者权益调整项目                             |
| equity_and_liabilities_special_project                                                           | 负债和权益特殊项目                             |
| equity_and_liabilities_adjustment_project                                                        | 负债和权益调整项目                             |
| financial_assets_recognized_in_profit_or_loss_at_fair_value                                      | 按公平值入损益金融资产                         |
| resale_financial_assets                                                                          | 买入返售金融资产                               |
| investment_in_joint_ventures_and_associates                                                      | 于联营企业和合营企业的投资                     |
| current_income_tax_liabilities                                                                   | 当期所得税负债                                 |

<br/>

###### 现金流量表 {#cash_flow_statement_nonchinese_nonfinance}

| 字段                                                           | 释义、备注                                     |
| -------------------------------------------------------------- | ---------------------------------------------- |
| deposit_change                                                 | 存款减少(增加)                                 |
| cash_paid_to_acquire_investment                                | 投资支付现金                                   |
| purchase_fixed_assets                                          | 购买固定资产                                   |
| cash_paid_for_intangible_assets_and_other_assets               | 购建无形资产及其他资产                         |
| depreciation                                                   | 折旧                                           |
| issuing_stock                                                  | 发行股份                                       |
| received_investment_interest                                   | 已收利息—投资                                  |
| other_financing_business_items                                 | 融资业务其他项目                               |
| received_investment_dividend                                   | 已收股息—投资                                  |
| paid_financing_interest                                        | 已付利息(融资)                                 |
| paid_financing_dividend                                        | 已付股息(融资)                                 |
| exchange_rate_impact                                           | 汇率影响                                       |
| cash_received_from_disposal_of_investment                      | 收回投资所得现金                               |
| financial_expense                                              | 财务费用                                       |
| net_cash_from_financing_business                               | 融资业务现金净额                               |
| other_operation_adjustment_items                               | 经营调整其他项目                               |
| begin_period_cash                                              | 期初现金                                       |
| issuance_fee_and_expense_for_redeeming_security                | 发行费用及赎回证券支出                         |
| paid_hk_profits_tax                                            | 已缴香港利得税                                 |
| profit_before_tax_cashflow                                     | 除税前溢利(业务利润)                           |
| sell_fixed_assets                                              | 出售固定资产                                   |
| investment_profit                                              | 投资损（益）                                   |
| operating_profit_before_working_capital_change                 | 营运资金变动前经营溢利                         |
| repay_loan                                                     | 偿还借款                                       |
| interest_income_adjustment                                     | 利息(收入)-调整                                |
| accts_payable_and_accrued_expense_change                       | 应付帐款及应计费用增加(减少)                   |
| accts_receivable_and_prepayment_change                         | 应收帐款及预付款(增加)减少                     |
| net_cash                                                       | 现金净额                                       |
| inventory_change                                               | 存货(增加)减少                                 |
| paid_cn_income_tax                                             | 已缴中国所得税                                 |
| net_cash_from_operation_business                               | 经营业务现金净额                               |
| cash_from_operation                                            | 经营产生现金                                   |
| end_period_cash                                                | 期末现金                                       |
| net_cash_from_investment_business                              | 投资业务现金净额                               |
| exchange_profit                                                | 汇兑损（益）                                   |
| interest_expense_adjustment                                    | 利息支出—调整                                  |
| inventory_impairment_reversal                                  | 存货减值（回拨）                               |
| other_operation_business_items                                 | 经营业务其他项目                               |
| newly_added_loan                                               | 新增借款                                       |
| received_operation_interest                                    | 已收利息—经营                                  |
| paid_operation_interest                                        | 已付利息—经营                                  |
| other_paid_income_tax                                          | 其他已缴所得税                                 |
| accts_receivable_change                                        | 应收贷款(增)减                                 |
| prepayment_change                                              | 预付款项(增)减                                 |
| other_investment_business_items                                | 投资业务其他项目                               |
| other_impairment_and_provision_cashflow                        | 其他减值与拨备                                 |
| attributable_profit_to_subcompany                              | 应占附属公司（盈）亏                           |
| acquisition_of_subcompany                                      | 收购附属公司                                   |
| absorb_investment_income                                       | 吸收投资所得                                   |
| selling_property_machine_and_device_profit                     | 出售物业、机器及设备损（益）                   |
| accts_receivable_trade_impairment_reversal                     | 应收贸易账款减值（回拨）                       |
| bad_debts_provision_reversal                                   | 呆坏账拨备（回拨）                             |
| other_fair_value_change                                        | 其他公平值变动                                 |
| dividend_income_adjustment                                     | 股息（收入）-调整                              |
| selling_subcompany_interests_profit                            | 出售附属公司权益损（益）                       |
| profit_from_selling_other_assets                               | 出售其他资产损（益）                           |
| sell_subsidiary_company                                        | 出售附属公司                                   |
| intangible_assets_amortization                                 | 无形资产摊销                                   |
| selling_intangible_and_other_assets                            | 出售无形资产及其他资产                         |
| adjustment_items_for_operation_business                        | 经营业务调整项目                               |
| adjustment_items_for_working_capital_change                    | 营运资金变动调整项目                           |
| adjustment_items_for_period_changes                            | 期间变动调整项目                               |
| unrealized_exchange_profit                                     | 未实现汇兑损（益）                             |
| profit_from_financial_assets_with_fair_value_change            | 按公平值计入损益的金融资产(增)减               |
| restricted_cash_change                                         | 受限制现金(增)减                               |
| adjustment_items_effecting_net_cash                            | 影响现金净额调整项目                           |
| other_depreciation_and_amortization                            | 其他折旧及摊销                                 |
| accts_payable_from_related_party_change                        | 应付关联方款项增加(减少)                       |
| develop_property_change                                        | 发展中物业（增）减                             |
| accts_receivable_from_related_party_change                     | 应收关联方款项(增加)减少                       |
| investment_property_change_cashflow                            | 投资物业公平值（增）减                         |
| mortgage_bank_deposit_financing_change                         | 已抵押银行存款(增)减-融资                      |
| adjustment_items_for_investment_business                       | 投资业务调整项目                               |
| other_period_change_items                                      | 期间变动其他项目                               |
| derivative_financial_instruments_change_cashflow               | 衍生金融工具公平值（增）减                     |
| selling_joint_venture_profit                                   | 出售联营公司损（益）                           |
| cash_and_bank_surplus                                          | 现金及银行结余                                 |
| adjustment_items_for_financing_business                        | 融资业务调整项目                               |
| adjustment_items_for_operation_adjustment                      | 经营调整调整项目                               |
| received_operation_dividend                                    | 已收股息-经营                                  |
| deferred_income_amortization                                   | 递延收入摊销                                   |
| issuing_bond                                                   | 发行债券                                       |
| issuing_stock_bond                                             | 发行股份债券                                   |
| property_machine_and_device_impairment_reversal                | 物业、厂房及设备减值（回拨）                   |
| bank_deposits                                                  | 银行存款                                       |
| derivative_financial_instruments_increase                      | 衍生金融工具（增）                             |
| advance_from_customers_increase                                | 预收款项增（减）                               |
| goodwill_profit_impairment                                     | 商誉减值亏损                                   |
| selling_available_for_sale_investment_profit                   | 出售可供出售投资损（益）                       |
| financing_customer_advance_accts_change                        | 融资客户垫款(增)减                             |
| cash_equivalent_surplus                                        | 现金及现金等值项目结余                         |
| net_cash_before_financing                                      | 融资前现金净额                                 |
| other_working_capital_change_items                             | 营运资本变动其他项目                           |
| profit_from_financial_liabilities_with_fair_value_change       | 按公平值计入损益的金融负债增（减）             |
| purchase_resale_financial_assets_change                        | 买入返售金融资产(增)减                         |
| available_for_investment_impairment_reversal                   | 可供出售投资减值（回拨）                       |
| bank_loan_and_advance_change                                   | 银行—发放贷款及垫款（增）减                    |
| profit_from_bank_financial_assets_with_fair_value              | 银行—按公平值计入损益的金融资产(增)减          |
| paid_operation_dividend                                        | 己付股息-经营                                  |
| insurance_contract_liabilities_change                          | 保险合同负债增（减）                           |
| depreciation_of_fixed_oil_gas_and_productive_biological_assets | 固定资产折旧、油气资产折耗、生产性生物资产折旧 |
| amortization_or_depreciation_of_use_right_assets               | 使用权资产摊销/折旧                            |
| amortization_or_depreciation_of_investment_property            | 投资性房地产折旧/摊销                          |
| repay_lease_liabilities                                        | 偿还租赁负债                                   |
| other_cash_from_operation_items                                | 经营产生现金其他项目                           |
| other_effecting_net_cash_items                                 | 影响现金净额其他项目                           |
| bank_borrowings_from_central_banks_change                      | 银行—向中央银行借款增(减)                      |
| shares_reduction                                               | 股本减少                                       |
| accts_receivable_insurance_change                              | 保险业务应收款(增)减                           |
| accts_payable_reinsurance_change                               | 应付分保账款增（减）                           |
| taxation_cashflow                                              | 税项                                           |
| financing_costs_and_investment_return                          | 融资费用及投资回报                             |
| cash_before_financing_for_other_items                          | 融资前现金其他项目                             |
| interest_payment_cash_balance                                  | 支付利息-现金结存                              |
| bank_deposits_change                                           | 银行—银行存款（增）减                          |

#### 范例 {#rqdata-API-get_pit_financials_ex_hk-example}

- 获取 00001.XHKG 2023 年各报告期所有记录

```python
[In]
get_pit_financials_ex(fields=['turnover','begin_period_cash'], start_quarter='2023q1', end_quarter='2023q4',order_book_ids=['00001.XHKG'],statements='all',market='hk')
[Out]
                  info_date turnover      fiscal_year standard             if_adjusted   rice_create_tm       begin_period_cash
order_book_id quarter
00001.XHKG    2023q2 2023-08-03 1.333770e+11 2023-12-31 非中国会计准则_非金融非保险公司 0 2025-04-22 17:31:22     1.380850e+11
               2023q2 2024-08-15 1.333770e+11 2023-12-31 非中国会计准则_非金融非保险公司 1 2025-04-22 17:31:22     1.380850e+11
               2023q4 2024-03-21 2.755750e+11 2023-12-31 非中国会计准则_非金融非保险公司 0 2025-04-22 17:31:22     1.380850e+11
               2023q4 2025-03-20 2.755750e+11 2023-12-31 非中国会计准则_非金融非保险公司 1 2025-04-22 17:31:22     1.380850e+11

```

- 获取 00001.XHKG 2023 年查询日期为 20240321 的记录

```python
[In]
get_pit_financials_ex(fields=['turnover','begin_period_cash'], start_quarter='2023q1', end_quarter='2023q4',order_book_ids=['00001.XHKG'],statements='all',date = 20240321,market='hk')
[Out]
                  info_date turnover      fiscal_year standard             if_adjusted   rice_create_tm        begin_period_cash
order_book_id quarter
00001.XHKG    2023q2 2023-08-03 1.333770e+11 2023-12-31 非中国会计准则_非金融非保险公司 0 2025-04-22 17:31:22      1.380850e+11
               2023q4 2024-03-21 2.755750e+11 2023-12-31 非中国会计准则_非金融非保险公司 0 2025-04-22 17:31:22      1.380850e+11

```

- 获取股票列表 2024q3-2024q4 各报告期最新一次记录

```python
[In]
get_pit_financials_ex(fields=['intangible_assets','revenue'], start_quarter='2024q3', end_quarter='2024q4',order_book_ids=['00038.XHKG','00763.XHKG'],market='hk')
[Out]
                  info_date intangible_assets fiscal_year standard if_adjusted revenue       rice_create_tm
order_book_id quarter
00038.XHKG    2024q3 2024-10-29 7.361137e+08      2024-12-31 中国会计准则       0  1.165857e+10   2025-04-22 17:46:09
               2024q4 2025-03-27 7.233467e+08      2024-12-31 中国会计准则       0  1.273195e+10   2025-04-22 17:46:09
00763.XHKG    2024q3 2024-10-21 8.270417e+09      2024-12-31 中国会计准则       0  9.822684e+10   2025-04-22 22:02:35
               2024q4 2025-02-28 7.634037e+09      2024-12-31 中国会计准则       0  1.293439e+11   2025-04-22 22:02:35

```

### hk.get_detailed_financial_items - 查询财务细分项目(point-in-time 形式) {#rqdata-API-hk_get_detailed_financial_items}

```python
rqdatac.hk.get_detailed_financial_items(order_book_ids, fields, start_quarter, end_quarter, date=None, statements='latest', market='hk')
```

以 point-in-time 方式获取港股财务细分项目数据，支持利润表、资产负债表和现金流量表字段查询。

::: tip 注意事项

请先单独安装 rqdatac_hk，导入后使用

:::

#### 参数 {#rqdata-API-hk_get_detailed_financial_items-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                  |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list ，该参数必填                                                                                         |
| fields         | _list_                                                         | **必填参数**，需要返回的财务字段。支持的字段仅限<b>利润表、资产负债表、现金流量表三大表字段</b>，具体字段请看[get_pit_financials_ex](#rqdata-API-financials_hk)介绍。 |
| start_quarter  | _str_                                                          | **必填参数**，财报回溯查询的起始报告期，例如'2015q2'代表 2015 年半年报， 该参数必填 。                                                                                |
| end_quarter    | _str_                                                          | **必填参数**，财报回溯查询的截止报告期，例如'2015q4'代表 2015 年年报，该参数必填。                                                                                    |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询日期，默认查询日期为当前最新日期                                                                                                                                  |
| statements     | _str_                                                          | 基于查询日期，返回某一个报告期的所有记录或最新一条记录，设置 statements 为 all 时返回所有记录，statements 等于 latest 时返回最新的一条记录，默认为 latest.            |
| market         | _str_                                                          | 市场，仅限'hk'香港市场                                                                                                                                                |

#### 返回 {#rqdata-API-hk_get_detailed_financial_items-return}

_pandas DataFrame_

| 固定字段     | 类型               | 说明                                                                                                                                                                                                |
| ------------ | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| quarter      | _str_              | 报告期                                                                                                                                                                                              |
| info_date    | _pandas.Timestamp_ | 公告发布日                                                                                                                                                                                          |
| field        | _list_             | 需要返回的财务字段。需要返回的财务字段。支持的字段仅限<b>利润表、资产负债表、现金流量表三大表字段</b>，具体字段请看[get_pit_financials_ex](#rqdata-API-financials_hk)介绍。                         |
| if_adjusted  | _int_              | 是否为非当期财报数据, 0 代表当期，1 代表非当期（比如 18 年的财报会披露本期和上年同期的数值，17 年年报的财务数值在 18 年年报中披露的记录则为非当期， 17 年年报的财务数值在 17 年年报中披露则为当期。 |
| fiscal_year  | _pandas.Timestamp_ | 财政年度                                                                                                                                                                                            |
| standard     | _str_              | 会计准则，中国会计准则、非中国会计准则\_金融公司、非中国会计准则\_保险公司、非中国会计准则\_非金融非保险公司                                                                                        |
| relationship | _int_              | 运算符号，0 表示其中项不参与计算，1 表示正号，-1 表示负号<br/>资产负债表都是按照正值， relationship 均为 1，利润表和现金流量表区分正负值                                                            |
| subject      | _str_              | fields 下面所有细分项目名称（实际出现在财务报表中的名称）                                                                                                                                           |
| amount       | _float_            | 未做港币汇率转换的原始值（实际出现在财务报表中的原始值）                                                                                                                                            |
| currency     | _str_              | 货币单位                                                                                                                                                                                            |

#### 范例 {#rqdata-API-hk_get_detailed_financial_items-example}

- 获取 02318.XHKG 2023q1-2023q2 fields 下所有细分项目的最新一次记录

```python
[In]
import rqdatac
import rqdatac_hk
rqdatac.init()
rqdatac.hk.get_detailed_financial_items(order_book_ids=['02318.XHKG'],start_quarter='2023q1', end_quarter='2023q2',fields=['other_operating_expense_items'],market='hk')
[Out]
                  info_date fiscal_year field relationship amount currency subject standard if_adjusted
order_book_id quarter
02318.XHKG    2023q1 2024-04-23 2023-12-31 other_operating_expense_items 1.0 -4.600000e+07 人民币元 提取保费准备金 非中国会计准则_保险公司 1
               2023q1 2024-04-23 2023-12-31 other_operating_expense_items 1.0 -2.634700e+10 人民币元 银行业务利息支出 非中国会计准则_保险公司 1
               2023q1 2024-04-23 2023-12-31 other_operating_expense_items 1.0 -1.894000e+09 人民币元 非保险业务手续费及佣金支出 非中国会计准则_保险公司 1
               2023q2 2024-08-22 2023-12-31 other_operating_expense_items 1.0 -1.440000e+08 人民币元 提取保费准备金 非中国会计准则_保险公司 1
               2023q2 2024-08-22 2023-12-31 other_operating_expense_items 1.0 -5.329500e+10 人民币元 银行业务利息支出 非中国会计准则_保险公司 1
               2023q2 2024-08-22 2023-12-31 other_operating_expense_items 1.0 -4.368000e+09 人民币元 非保险业务手续费及佣金支出 非中国会计准则_保险公司 1
```

## 港股因子数据 {#rqdata-API-factors_hk}

### get_factor - 获取因子值 {#rqdata-API-get_factor_hk}

```python
get_factor(order_book_ids, factor, start_date=None, end_date=None, universe=None, expect_df=True, market='cn')
```

获取港股因子值数据，默认返回指定因子上一个交易日的值。例如支持三大报表基础会计科目，也支持财务衍生指标因子。

#### 参数 {#rqdata-API-get_factor_hk-params}

| 参数                | 类型                                                           | 说明                                                                                            |
| ------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| order_book_ids      | _str_ or _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                |
| factor              | _str_ or _str list_                                            | **必填参数**，因子名称，见下方，也可查询 get_all_factor_names(market='hk') 得到所有有效因子字段 |
| start_date          | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期                                                    |
| end_date            | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填                                                    |
| ~~universe~~ 已废弃 | _str_                                                          | 指定因子计算时的股票域，米筐所有公共因子均在全市场范围计算，此参数保留为 None 即可              |
| expect_df           | _boolean_                                                      | 默认返回 pandas dataframe。如果调为 False，则返回 原有的数据结构                                |
| market              | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                             |

#### 返回 {#rqdata-API-get_factor_hk-return}

_pandas DataFrame_

<br/>

##### 三大报表基础会计科目 {#basic_accounting_fields}

<br/>

此处均以中国会计准则作为基准，将来源各异的财务数据归一至中国会计准则框架下。目前仅提供以下字段最近 9 期的 TTM 数据，并以 \_ttm_n 后缀的方式在原有基础字段上进行拓展（对于来自利润表和现金流量表的数据 TTM 为滚动加和，来自资产负债表的数据 TTM 为滚动求平均）。
| 字段 | 中文名  
|-----|-----|
| profit_before_tax | 利润总额 |
| operating_revenue | 营业收入 |  
| net_profit | 净利润|
| net_profit_parent_company | 归属于母公司所有者的净利润|
| intangible_asset_amortization | 无形资产摊销|
| basic_earnings_per_share | 每股基本|
| fully_diluted_earnings_per_share | 每股摊薄盈利|
| financing_interest_income | 利息收入（财务费用）|
| financing_interest_expense | 利息支出（财务费用）|
| exchange_rate_change_effect | 汇率变动对现金的影响|
| cash_equivalent_increase | 现金及现金等价物净增加额（来源现金流量表主表）|
| begin_period_cash_equivalent | 期初现金及现金等价物余额|
| end_period_cash_equivalent | 期末现金及现金等价物余额|
| cash_flow_from_operating_activities| 经营活动产生的现金流量净额|
| cash_flow_from_investing_activities| 投资活动产生的现金流量净额|
| cash_flow_from_financing_activities| 筹资活动产生的现金流量净额|
| total_assets | 总资产|
| accts_payable | 应付账款|
| paid_in_capital | 实收资本|
| cash_equivalent | 货币现金|
| deferred_income_tax_assets | 递延所得税资产|
| equity_parent_company | 归属于母公司所有者权益合计|

<br/>

##### 财务衍生指标因子{#financial_indicators}

<br/>

###### 估值有关指标 {#financial_indicators-value}

| 字段                               | 中文名           | 说明                                                                            | 公式                                                            |
| ---------------------------------- | ---------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| hk_share_market_val                | 港股市值         | 港股市值 = 已上市港股股数 \* 港股未复权收盘价 此处股本采用 PIT 处理方式         | total_hk \* close                                               |
| hk_share_market_val_in_circulation | 港股流通市值     | 港股流通市值 = 可在港股交易的股数 \* 港股未复权收盘价 此处股本采用 PIT 处理方式 | total_hk1 \* close                                              |
| hk_total_market_val                | 港股总市值       | 总市值 = 总股本 \* 港股未复权收盘价 此处股本采用 PIT 处理方式                   | total \* close                                                  |
| pe_ratio_ttm                       | 市盈率ttm        | 总市值/归母公司净利润ttm                                                        | hk_total_market_val/ net_profit_parent_company_ttm_0            |
| pb_ratio_ttm                       | 市净率 ttm       | 总市值 / 归属母公司股东权益合计 ttm                                             | hk_total_market_val/ equity_parent_company_ttm_0                |
| ps_ratio_ttm                       | 市销率 ttm       | 总市值 / 营利收入 ttm                                                           | hk_total_market_val / operating_revenue_ttm_0                   |
| pcf_ratio_ttm                      | 市现率\_经营 ttm | 总市值 / 经营活动产生的现金流量净额 ttm                                         | hk_total_market_val / cash_flow_from_operating_activities_ttm_0 |
| dividend_yield_ttm                 | 股息率 ttm       | 过去12个月中包含的除权除息日的派现(含税10派X元)(人民币)之和/10 / 未复权收盘价                                | dividend_ttm / close_price                                      |

###### 经营衍生指标 {#financial_indicators-operation}

| 字段                 | 中文名           | 说明                                                                                              | 公式                                                                                               |
| -------------------- | ---------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| ebit_ttm             | 息税前利润 ttm   | 利润总额 ttm + 利息支出(财务费用) ttm - 利息收入(财务费用) ttm                                    | profit_before_tax_ttm_0 + financing_interest_expense_ttm_0 - financing_interest_income_ttm_0       |
| return_on_equity_ttm | 净资产收益率 ttm | 归属母公司净利润 ttm \* 2 / (归属母公司股东权益合计 ttm + 上期报表披露归属母公司股东权益合计 ttm) | net_profit_parent_company_ttm_0 \* 2 / (equity_parent_company_ttm_0 + equity_parent_company_ttm_1) |
| return_on_asset_ttm  | 总资产报酬率 ttm | 息税前利润 ttm / 总资产 ttm                                                                       | ebit_ttm / total_assets_ttm_0                                                                      |

#### 范例 {#rqdata-API-get_factor_hk-example}

- 获取单支港股市值数据

```python
[In]
get_factor('00020.XHKG',['hk_share_market_val','hk_share_market_val_in_circulation','hk_total_market_val'], 20250804,20250810,market='hk')
[Out]

                              hk_share_market_val	hk_share_market_val_in_circulation	hk_total_market_val
order_book_id	date
00020.XHKG	2025-08-04	6.187846e+10	6.089601e+10	6.187846e+10
               2025-08-05	6.226520e+10	6.127661e+10	6.226520e+10
               2025-08-06	6.342542e+10	6.241841e+10	6.342542e+10
               2025-08-07	6.342542e+10	6.241841e+10	6.342542e+10
               2025-08-08	6.265194e+10	6.165721e+10	6.265194e+10

```

- 获取多支港股市值数据

```python
[In]
get_factor(['00020.XHKG','03750.XHKG'],['hk_share_market_val','hk_share_market_val_in_circulation','hk_total_market_val'], 20250804,20250805,market='hk')
[Out]

                              hk_share_market_val	hk_share_market_val_in_circulation	hk_total_market_val
order_book_id	date
00020.XHKG	2025-08-04	6.187846e+10	6.089601e+10	6.187846e+10
          2025-08-05	6.226520e+10	6.127661e+10	6.226520e+10
03750.XHKG	2025-08-04	6.507905e+10	6.507905e+10	1.903056e+12
          2025-08-05	6.423710e+10	6.423710e+10	1.878436e+12


```

### get_all_factor_names - 获取因子字段列表 {#rqdata-API-get_all_factor_names_hk}

```python
get_all_factor_names(type=None, market='cn')
```

获取港股因子字段列表。目前仅支持市值和流通市值相关因子字段。

#### 参数 {#rqdata-API-get_all_factor_names_hk-params}

| 参数   | 类型  | 说明                                                                |
| ------ | ----- | ------------------------------------------------------------------- |
| type   | _str_ | 默认返回所有因子<br/>'eod_indicator'：估值有关指标                  |
| market | _str_ | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_all_factor_names_hk-return}

_list_

#### 范例 {#rqdata-API-get_all_factor_names_hk-example}

- 获取市值和流通市值因子

```python
[In]
get_all_factor_names(type='eod_indicator',market='hk')
[Out]
['hk_share_market_val', 'hk_share_market_val_in_circulation','hk_total_market_val']

```

## 港股公告相关 {#rqdata-API-announcement_hk}

### hk.get_announcement - 获取港股公告数据 {#rqdata-API-hk_get-announcement}

```python
rqdatac.hk.get_announcement(order_book_ids, start_date=None, end_date=None, fields=None, market='hk')
```

获取港股公告数据，支持按时间范围和字段查询。

::: tip 注意事项

请先单独安装 rqdatac_hk，导入后使用

:::

#### 参数 {#rqdata-API-hk_get-announcement-params}

| 参数           | 类型                                                           | 说明                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。注：如使用开始日期，则必填结束日期         |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。注：若使用结束日期，则开始日期必填         |
| fields         | _list_                                                         | 可选字段见下方返回，若不指定，则默认获取所有字段     |
| market         | _str_                                                          | 市场，仅限'hk'香港市场                               |

#### 返回 {#rqdata-API-hk_get-announcement-return}

_pandas DataFrame_

| 字段              | 类型               | 说明                                                                                                                                                                  |
| ----------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids    | _str_              | 合约代码                                                                                                                                                              |
| info_date         | _pandas.Timestamp_ | 发布日期                                                                                                                                                              |
| meida             | _str_              | 媒体出处                                                                                                                                                              |
| title             | _str_              | 标题                                                                                                                                                                  |
| language          | _str_              | 语言                                                                                                                                                                  |
| file_type         | _str_              | 文件格式                                                                                                                                                              |
| announcement_link | _str_              | 公告链接                                                                                                                                                              |
| first_category    | _str_              | 一级英文公告分类，中英文公告分类映射，可点此<a href="https://www.ricequant.com/vendor/rqdata/category_mapping.xlsx" target="_blank">中英文映射表</a >下载查看，下同。 |
| second_category   | _str_              | 二级英文公告分类                                                                                                                                                      |
| third_category    | _str_              | 三级英文公告分类                                                                                                                                                      |

#### 范例 {#rqdata-API-hk_get-announcement-example}

- 获取一个合约某个时间段内的公司公告数据

```python
[In]
import rqdatac
import rqdatac_hk
rqdatac.hk.get_announcement(order_book_ids=['00638.XHKG'],start_date=20251127,end_date=20251129,market='hk')
[Out]
                              media	title	language	file_type	announcement_link	first_category	second_category	third_category	rice_create_tm
order_book_id	info_date
00638.XHKG	2025-11-28	香港交易所	广和通(00638)公告及通告 - [海外监管公告-董事会/监事会决议]海外监管公告 - 第...	繁体中文	PDF	https://www1.hkexnews.hk/listedco/listconews/s...	Announcements and Notices	Miscellaneous	Overseas Regulatory Announcement - Board/Super...	2025-12-05 09:42:48
          2025-11-28	香港交易所	广和通(00638)公告及通告 - [海外监管公告-董事会/监事会决议]海外监管公告 - 第...	繁体中文	PDF	https://www1.hkexnews.hk/listedco/listconews/s...	Announcements and Notices	Miscellaneous	Overseas Regulatory Announcement - Board/Super...	2025-12-05 09:42:48
          2025-11-28	香港交易所	广和通(00638)公告及通告 - [海外监管公告-其他]海外监管公告 - 关于开展外汇套期...	繁体中文	PDF	https://www1.hkexnews.hk/listedco/listconews/s...	Announcements and Notices	Miscellaneous	Overseas Regulatory Announcement - Other	2025-12-05 09:42:48
...	...	...
          2025-11-28	香港交易所	FIBOCOM(00638)Announcements and Notices - [Ter...	英文	PDF	None	Announcements and Notices	Corporate Positions and Committees/Corporate C...	Terms of Reference of the Remuneration Committee	2025-12-05 09:42:48
          2025-11-28	香港交易所	FIBOCOM(00638)Announcements and Notices - [Ter...	英文	PDF	None	Announcements and Notices	Corporate Positions and Committees/Corporate C...	Terms of Reference of the Nomination Committee	2025-12-05 09:42:48
          2025-11-28	香港交易所	FIBOCOM(00638)Announcements and Notices - [Ter...	英文	PDF	None	Announcements and Notices	Corporate Positions and Committees/Corporate C...	Terms of Reference of Other Board Committees	2025-12-05 09:42:48
```

## 港股南向数据 {#rqdata-API-connect_hk}


### hk.get_stock_connect - 获取港股通持股信息 {#rqdata-API-get_stock_connect_hk}

```python
hk.get_stock_connect(order_book_ids=None,start_date=None,end_date=None,channel='total',fields=None,market='hk')
```

获取港股通（南向）标的在一段时间内的持股数据。

::: tip 注意事项

港股通汇总数据（港交所披露）T 日数据于 T+1 日 06:00 更新； 数据提供范围为 2017-03-17 至今 <br />
沪、深港股通数据（沪深交易所披露）T 日数据于 T+1 日 18:00 更新；沪港通数据提供范围为 2024-08-16 至今，深港通为 2016-12-05 至今

:::

#### 参数 {#rqdata-API-get_stock_connect_hk-params}

| 参数   | 类型                                                           | 说明                                                                |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| order_book_ids   | _str OR str list_                           | 可输入 order_book_id , order_book_id list <br /> 传入单个标的时，查询该标的对应渠道的持股数据 <br /> **不传则返回指定 channel 下全部港股通标的持股数据**           |
| start_date      | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_                | 开始日期 |
| end_date         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，start_date ,end_date 不传参数时默认返回最近三个月的数据                 |
| channel         | _str_ | 港股通交易渠道，默认为 **total** <br /> sh - 返回沪港通全部标的**单渠道**持股数据 <br /> sz - 返回深港通全部标的**单渠道**持股数据 <br /> total - 返回沪 、 深港通全部标的**两地合计**的持股数据 <br /> all - 返回沪、深、两地合计的**全渠道**持股数据                                  |
| fields          | _str OR str list_ | 默认为所有字段。见下方列表                                  |
| market          | _str_ | 市场，仅限'hk'香港市场                                  |


#### 返回 {#rqdata-API-get_stock_connect_hk-return}

_pandas DataFrame_

| 字段                     | 类型        | 说明                     |
| ----------------- | ------------------ | -------------------------------------- |
| channel                 | _str_        | sh：沪港通（单渠道）<br /> sz：深港通（单渠道）<br /> total：沪 + 深 两地合计       |
| shares_holding          | _float_      | 持股量（股）                             |
| holding_ratio           | _float_      | 持股比例                               |
| adjusted_holding_ratio  | _float_      | 调整后持股比例                             |

#### 范例 {#rqdata-API-get_stock_connect_hk-example}

- 获取某天港股通汇总数据：

```python
[In]hk.get_stock_connect(order_book_ids=None,start_date=20260519,end_date=20260519,channel='total')
[Out]
                      channel	adjusted_holding_ratio	holding_ratio	shares_holding
order_book_id	date				
00001.XHKG	2026-05-19	total	2.3050	2.30	8.828159e+07
00002.XHKG	2026-05-19	total	1.9348	1.93	4.888118e+07
00003.XHKG	2026-05-19	total	3.1018	3.09	5.787973e+08
00004.XHKG	2026-05-19	total	0.1658	0.15	5.066950e+06
00005.XHKG	2026-05-19	total	8.9842	8.97	1.543811e+09
...	...	...	...	...	...
09990.XHKG	2026-05-19	total	5.6368	5.63	4.528400e+07
09992.XHKG	2026-05-19	total	24.6593	24.65	3.306922e+08
09993.XHKG	2026-05-19	total	7.0623	7.05	2.856860e+08
09995.XHKG	2026-05-19	total	51.6349	51.63	1.077006e+08
09996.XHKG	2026-05-19	total	10.9664	10.96	7.370110e+07

933 rows × 4 columns

```
- 获取某天沪港通数据：

```python
[In]hk.get_stock_connect(order_book_ids=None,start_date=20260519,end_date=20260519,channel='sh')
[Out]
                      channel	adjusted_holding_ratio	holding_ratio	shares_holding
order_book_id	date				
00001.XHKG	2026-05-18	sh	1.3800	None	5.285610e+07
00002.XHKG	2026-05-18	sh	1.1504	None	2.906519e+07
00003.XHKG	2026-05-18	sh	2.2159	None	4.134810e+08
00004.XHKG	2026-05-18	sh	0.1493	None	4.564000e+06
00005.XHKG	2026-05-18	sh	8.4171	None	1.446355e+09
...	...	...	...	...	...
09990.XHKG	2026-05-18	sh	1.4235	None	1.143600e+07
09992.XHKG	2026-05-18	sh	15.1362	None	2.029836e+08
09993.XHKG	2026-05-18	sh	1.4107	None	5.706600e+07
09995.XHKG	2026-05-18	sh	24.8895	None	5.191485e+07
09996.XHKG	2026-05-18	sh	6.9058	None	4.641100e+07

845 rows × 4 columns

```

- 获取某合约全渠道的南向持股数据：

```python
[In]hk.get_stock_connect(order_book_ids='00001.XHKG',start_date=20260518,end_date=20260518,channel='all')
[Out]
                      channel	adjusted_holding_ratio	holding_ratio	shares_holding
order_book_id	date				
00001.XHKG	2026-05-18	sh	    1.3800	NaN	52856102.0
            2026-05-18	sz	    0.9263	NaN	35477488.0
            2026-05-18	total	2.3063	2.3	88333590.0

```
