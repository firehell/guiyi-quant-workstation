## 可转债行情数据说明 {#rqdata-API-convertible-overview}

可获取可转债合约的日行情、分钟行情、tick 行情数据，具体调用方式请参考 [API-get_price](generic-api.md#rqdata-API-get_price).

## 可转债基础信息，历史日行情、分钟线 {#rqdata-API-convertible-basic}

### convertible.all_instruments - 获取所有可转债合约 {#rqdata-API-convertible-all_instruments}

```python
convertible.all_instruments(date=None, market='cn')
```

获取所有可转债合约的基础信息，传入日期时可筛选该日上市状态的合约列表。例如可获取债券全称、上市日、到期日等基础信息，也包括转股起始日、转股截止日和对应股票代码等数据。

#### 参数 {#rqdata-API-convertible-all_instruments-params}

| 参数           | 类型                | 说明                                                                         |
|-----|-----|-----|
| date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定日期，筛选指定日期可交易的合约 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；                                                                    |

#### 返回 {#rqdata-API-convertible-all_instruments-return}

_pandas DataFrame_

| 字段                              | 类型       | 说明                                                                                                |
|-----|-----|-----|
| order_book_id                     | _str_      | 可转债合约代码                                                                                      |
| full_name                         | _str_      | 债券全称                                                                                            |
| symbol                            | _str_      | 债券简称                                                                                            |
| call_protection                   | _integer_  | 强赎保护期（月计），即此段时间不可强制赎回                                                          |
| issue_price                       | _float_    | 发行价格                                                                                            |
| total_issue_size                  | _float_    | 发行总规模                                                                                          |
| listed_date                       | _pandas.Timestamp_ | 上市日                                                                                              |
| de_listed_date                    | _datetime_ | 债券摘牌日                                                                                          |
| stop_trading_date                 | _datetime_ | 停止交易日                                                                                          |
| value_date                        | _pandas.Timestamp_ | 起息日                                                                                              |
| maturity_date                     | _pandas.Timestamp_ | 到期日(初期公告披露的日期)                                                                          |
| early_maturity_date               | _pandas.Timestamp_ | 实际到期日                                                                                          |
| par_value                         | _float_    | 面值                                                                                                |
| coupon_rate                       | _float_    | 发行票面利率                                                                                        |
| coupon_frequency                  | _float_    | 付息频率                                                                                            |
| compensation_rate                 | _float_    | 到期补偿利率                                                                                        |
| conversion_start_date             | _pandas.Timestamp_ | 转换期起始日                                                                                        |
| conversion_end_date               | _pandas.Timestamp_ | 转换期截止日                                                                                        |
| redemption_price                  | _float_    | 到期赎回价格                                                                                        |
| stock_code                        | _str_      | 对应股票的 order_book_id                                                                            |
| exchange                          | _str_      | 交易所                                                                                              |
| coupon_method                     | _str_      | 债券计息方式                                                                                        |
| trade_type                        | _str_      | 交易方式                                                                                            |
| bond_type                         | _str_      | 债券分类<br/>eb 可交换债券<br/>cb 可转换债券<br/>separately_traded 就是上交所和深交所公布的可分离债 |
| issue_method                      | _str_      | 发行方式                                                                                            |
| list_announcement_date            | _pandas.Timestamp_ | 上市公告书发布日                                                                                    |
| pref_allocation_registration_date | _pandas.Timestamp_ | 老股东优先配售股权登记日                                                                            |
| pref_allocation_payment_end_date  | _pandas.Timestamp_ | 老股东优先配售缴款日                                                                                |

#### 范例 {#rqdata-API-convertible-all_instruments-example-params}

- 获取所有可转债基础信息：

```python
[In]convertible.all_instruments()
[Out]
  order_book_id  symbol  full_name  exchange  bond_type  trade_type  value_date  maturity_date  par_value  coupon_rate  ...  coupon_method    total_issue_size
0  100001.XSHG  南化转债  南宁化工股份有限公司可转换公司债券  XSHG  convertible  clean_price  1998-08-03  2003-08-03  100.0  1.00  ...  stepup_rate    1.500000e+08
1  100009.XSHG  机场转债  上海国际机场股份有限公司可转换公司债券  XSHG  convertible  clean_price  2000-02-25  2005-02-25  100.0  0.80  ...  fixed_rate    1.350000e+09
2  100016.XSHG  民生转债  中国民生银行股份有限公司可转换公司债券  XSHG  convertible  clean_price  2003-02-27  2008-02-27  100.0  1.50  ...  fixed_rate    4.000000e+09
...
```

### convertible.instruments - 获取可转债合约基础信息 {#rqdata-API-convertible-instruments}

```python
convertible.instruments(order_book_ids, market='cn')
```

获取指定可转债合约的基础信息。例如可获取债券全称、上市日、到期日、转股起始日等数据，也支持获取不同付息期的票息率以及赎回、回售条款数据。

#### 参数 {#rqdata-API-convertible-instruments-params}

| 参数           | 类型                | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_ | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；                                                                    |

#### 返回 {#rqdata-API-convertible-instruments-return}

一个 instrument 对象，或一个 instrument list

##### 可转债 Instrument 对象

| 字段                              | 类型       | 说明                                                                                                |
|-----|-----|-----|
| order_book_id                     | _str_      | 可转债合约代码                                                                                      |
| full_name                         | _str_      | 债券全称                                                                                            |
| symbol                            | _str_      | 债券简称                                                                                            |
| call_protection                   | _integer_  | 强赎保护期（月计），即此段时间不可强制赎回                                                          |
| issue_price                       | _float_    | 发行价格                                                                                            |
| total_issue_size                  | _float_    | 发行总规模                                                                                          |
| listed_date                       | _pandas.Timestamp_ | 上市日                                                                                              |
| de_listed_date                    | _pandas.Timestamp_ | 债券摘牌日                                                                                          |
| stop_trading_date                 | _pandas.Timestamp_ | 停止交易日                                                                                          |
| value_date                        | _pandas.Timestamp_ | 起息日                                                                                              |
| maturity_date                     | _pandas.Timestamp_ | 到期日(初期公告披露的日期)                                                                          |
| early_maturity_date               | _pandas.Timestamp_ | 实际到期日                                                                                          |
| par_value                         | _float_    | 面值                                                                                                |
| coupon_rate                       | _float_    | 发行票面利率                                                                                        |
| coupon_frequency                  | _float_    | 付息频率                                                                                            |
| compensation_rate                 | _float_    | 到期补偿利率                                                                                        |
| conversion_start_date             | _pandas.Timestamp_ | 转换期起始日                                                                                        |
| conversion_end_date               | _pandas.Timestamp_ | 转换期截止日                                                                                        |
| redemption_price                  | _float_    | 到期赎回价格                                                                                        |
| stock_code                        | _str_      | 对应股票的 order_book_id                                                                            |
| exchange                          | _str_      | 交易所                                                                                              |
| coupon_method                     | _str_      | 债券计息方式                                                                                        |
| trade_type                        | _str_      | 交易方式                                                                                            |
| bond_type                         | _str_      | 债券分类<br/>eb 可交换债券<br/>cb 可转换债券<br/>separately_traded 就是上交所和深交所公布的可分离债 |
| issue_method                      | _str_      | 发行方式                                                                                            |
| list_announcement_date            | _pandas.Timestamp_ | 上市公告书发布日                                                                                    |
| pref_allocation_registration_date | _pandas.Timestamp_ | 老股东优先配售股权登记日                                                                            |
| pref_allocation_payment_end_date  | _pandas.Timestamp_ | 老股东优先配售缴款日                                                                                |

##### 转债 Instrument 对象也支持如下方法：

- 获取转债不同付息期的票息率：

```
convertible.instruments(order_book_ids).coupon_rate_table()
```

- 获取转债的赎回和回售条款：

```python
convertible.instruments(order_book_ids).option(option_type=None)
```

其中参数 option*type 可以支持输入 \_int* 类型 1~7 ，代表含义参考下表。默认返回全部类型
| option_type 值 | 说明 |
|-----|-----|
| 1 | 到期赎回权 |
| 2 | 发行人赎回权 |
| 3 | 有条件回售权 |
| 4 | 附加回售权 |
| 5 | 无条件回售权 |
| 6 | 时点回售权 |
| 7 | 价格修正权 |

option() 方法返回结构为 _pandas DataFrame_，字段说明如下：

| 字段                | 类型       | 说明         |
|-----|-----|-----|
| option_type         | _int_      | 权利类型     |
| start_date          | _datetime_ | 起止日期     |
| end_date            | _datetime_ | 结束日期     |
| level               | _float_    | 触发比例     |
| window_days         | _int_      | 触发天数     |
| reach_days          | _int_      | 满足天数     |
| frequency           | _int_      | 类型         |
| payment_year        | _int_      | 计息年度序列 |
| if_include_interest | _bool_     | 是否包含利息 |
| price               | _float_    | 价格         |
| remark              | _str_      | 备注         |

#### 范例 {#rqdata-API-convertible-instruments-example-params}

- 获取 110074.XSHE 的基础信息：

```python
[In]convertible.instruments("110074.XSHG")
[Out]
    Instrument(
    order_book_id='110074.XSHG',
    symbol='精达转债',
    full_name='铜陵精达特种电磁线股份有限公司公开发行可转换公司债券',
    exchange='XSHG',
    bond_type='cb',
    trade_type='dirty_price',
    value_date=datetime.datetime(2020, 8, 19, 0, 0),
    listed_date=datetime.datetime(2020, 9, 21, 0, 0),
    maturity_date=datetime.datetime(2026, 8, 19, 0, 0),
    early_maturity_date=None,
    par_value=100.0,
    coupon_rate=0.004,
    coupon_frequency=1,
    coupon_method='stepup_rate',
    compensation_rate=0.1,
    total_issue_size=787000000.0,
    de_listed_date=datetime.datetime(2026, 8, 19, 0, 0),
    stock_code='600577.XSHG',
    conversion_start_date=datetime.datetime(2021, 2, 25, 0, 0),
    conversion_end_date=datetime.datetime(2026, 8, 18, 0, 0),
    redemption_price=112.0,
    stop_trading_date=None,
    issue_price=100.0,
    issue_method='上网定价,老股东优先配售',
    list_announcement_date=datetime.datetime(2020, 9, 17, 0, 0),
    pref_allocation_registration_date=datetime.datetime(2020, 8, 18, 0, 0),
    pref_allocation_payment_end_date=datetime.datetime(2020, 8, 19, 0, 0),
    call_protection=6.0
    )
```

- 获取 110030.XSHG 格力转债的票息率

```python
[In]convertible.instruments("110030.XSHG").coupon_rate_table()
[Out]
     coupon_rate
start_date end_date
2014-12-25 2015-12-24 0.6
2015-12-25 2016-12-24 0.8
2016-12-25 2017-12-24 1.0
2017-12-25 2018-12-24 1.5
2018-12-25 2019-12-24 6.0

```

- 获取 110058.XSHG 赎回和回售条款

```python
[In]convertible.instruments('110058.XSHG').option()
[Out]
option_type start_date end_date payment_year level window_days reach_days frequency price if_include_interest remark
0 1 NaT NaT NaN NaN NaN NaN NaN 110.0 True (1)到期赎回条款\r\n 在本次发行的可转换公司债券期满后5个交易日内,公司...
1 2 2019-10-22 2025-04-15 1.0 1.30 30.0 15.0 随时 100.4 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
2 2 2019-10-22 2025-04-15 2.0 1.30 30.0 15.0 随时 100.6 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
3 2 2019-10-22 2025-04-15 3.0 1.30 30.0 15.0 随时 101.0 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
4 2 2019-10-22 2025-04-15 4.0 1.30 30.0 15.0 随时 101.5 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
5 2 2019-10-22 2025-04-15 5.0 1.30 30.0 15.0 随时 101.8 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
6 2 2019-10-22 2025-04-15 6.0 1.30 30.0 15.0 随时 102.0 True (2)有条件赎回条款\r\n 在本次发行的可转换公司债券转股期内,当下述两种情...
7 3 2023-04-16 2025-04-16 5.0 0.70 30.0 30.0 每计息年度1次 101.8 True (1)有条件回售条款\r\n 在本次发行的可转换公司债券最后两个计息年度,如果...
8 3 2023-04-16 2025-04-16 6.0 0.70 30.0 30.0 每计息年度1次 102.0 True (1)有条件回售条款\r\n 在本次发行的可转换公司债券最后两个计息年度,如果...
9 4 NaT NaT NaN NaN NaN NaN NaN NaN NaN (2)附加回售条款\r\n 若公司本次发行的可转换公司债券募集资金投资项目的实...
10 7 2019-04-16 2025-04-16 NaN 0.85 30.0 15.0 随时 NaN NaN NaN

```


### convertible.get_conversion_price - 获取可转债转股价信息 {#rqdata-API-convertible-get_conversion_price}

```python
convertible.get_conversion_price(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债合约在一段时期内的转股价变动数据，信息来源为交易所的可转债转股统计公告。例如可查询 110013.XSHG 在 2011-01-21 和 2011-07-04 公告对应的转股价变动数据。

#### 参数 {#rqdata-API-convertible-get_conversion_price-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为初始的信息发布日                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期                                                     |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_conversion_price-return}

_pandas DataFrame_

| 字段 | 类型 | 说明 |
|-----|-----|-----|
| info_date | _pandas.Timestamp_ | 交易所信息发布日期 |
| conversion_price | _float_ | 本次转股价 |
| effective_date | _pandas.Timestamp_ | 转股价截止日期 |

#### 范例 {#rqdata-API-convertible-get_conversion_price-example-params}

- 获取 110013.XSHG 的截止某日的转股价变动情况：

```python
[In]convertible.get_conversion_price('110013.XSHG',end_date=20110704)
[Out]
                         conversion_price  effective_date
order_book_id  info_date
110013.XSHG  2011-01-21  7.29              2011-01-25
              2011-07-04  7.27              2011-07-04

```

### convertible.get_conversion_info - 获取可转债转股导致的规模变动情况 {#rqdata-API-convertible-get_conversion_info}

```python
convertible.get_conversion_info(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债合约在一段时期内因转股导致的规模变动数据。例如可获取累计转股金额、累计转股数、剩余未转股金额等数据，也包括本期转股金额、本期转股股数和本次转股价。

#### 参数 {#rqdata-API-convertible-get_conversion_info-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为初始的信息发布日                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期                                                     |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_conversion_info-return}

_pandas DataFrame_

| 字段                   | 类型       | 说明                                                           |
|-----|-----|-----|
| info_date              | _pandas.Timestamp_ | 信息发布日                                                     |
| total_amount_converted | _integer_  | 累计转债已经转为股票的金额（元），累计每次转股金额             |
| total_shares_converted | _float_    | 累计转股数                                                     |
| remaining_amount       | _integer_  | 尚未转股的转债金额（元）                                       |
| amount_converted       | _integer_  | 本期转债已转为股票的金额（元）, 近似本期转股价与转股数乘积取值 |
| shares_converted       | _integer_  | 本期转股股数                                                   |
| end_date               | _pandas.Timestamp_ | 截止日期                                                       |
| conversion_price       | _float_    | 本次转股价                                                     |

#### 范例 {#rqdata-API-convertible-get_conversion_info-example}

- 获取 110044.XSHG 的转股规模变动情况：

```python
[In]convertible.get_conversion_info('110044.XSHG')
[Out]
                          amount_converted  conversion_price  end_date  remaining_amount  shares_converted  total_amount_converted  total_shares_converted
order_book_id  info_date
110044.XSHG  2019-01-04  455562.48                     6.91  2019-01-03  7.995444e+08             65928.0    4.555625e+05           65928.0
              2019-01-07  683792.87                     6.91  2019-01-04  7.988606e+08             98957.0    1.139355e+06           164885.0
              2019-01-08  86068043.98                     6.91  2019-01-07  7.127926e+08             12455578.0  8.720740e+07           12620463.0
              2019-01-09  38735269.53                     6.91  2019-01-08  6.740573e+08             5605683.0  1.259427e+08           18226146.0
              2019-01-10  70718653.68                     6.91  2019-01-09  6.033387e+08             10234248.0  1.966613e+08           28460394.0
...
```

### convertible.get_call_info - 获取可转债强赎信息 {#rqdata-API-convertible-get_call_info}

```python
convertible.get_call_info(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债合约在一段时期内的强制赎回信息，支持按转债代码和时间范围查询。

#### 参数 {#rqdata-API-convertible-get_call_info-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为初始的信息发布日                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期                                                     |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_call_info-return}

_pandas DataFrame_

| 字段              | 类型       | 说明                                      |
|-----|-----|-----|
| info_date         | _pandas.Timestamp_ | 信息发布日                                |
| exercise_price    | _float_    | 行权价格                                  |
| interest_included | _integer_  | 0 对应不包含，1 对应包含。Null 对应不明确 |
| interest_amount   | _float_    | 应计利息                                  |
| exercise_date     | _pandas.Timestamp_ | 行权日                                    |
| call_amount       | _integer_  | 赎回债券票面金额                          |
| record_date       | _pandas.Timestamp_ | 理论登记日，不跳过假日                    |

#### 范例 {#rqdata-API-convertible-get_call_info-example}

- 获取 110020.XSHG 的强赎情况

```python
[In]convertible.get_call_info('110020.XSHG')
[Out]

                          call_amount  exercise_date  exercise_price  interest_amount  interest_included  record_date
order_book_id  info_date
110020.XSHG   2015-01-22    8111000.0      2015-03-11     104.0                1.6                     1    2015-03-10


```

### convertible.get_put_info - 获取可转债回售信息 {#rqdata-API-convertible-get_put_info}

```python
convertible.get_put_info(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债合约在一段时期内的持有人回售信息，支持按转债代码和时间范围查询。

#### 参数 {#rqdata-API-convertible-get_put_info-params}

| 参数           | 类型                                                           | 说明                                                                         |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。 |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为初始的信息发布日                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期                                                     |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_put_info-return}

_pandas DataFrame_

| 字段                  | 类型       | 说明                                      |
|-----|-----|-----|
| info_date             | _pandas.Timestamp_ | 信息发布日                                |
| exercise_price        | _float_    | 行权价格                                  |
| interest_included     | _integer_  | 0 对应不包含，1 对应包含。Null 对应不明确 |
| interest_amount       | _float_    | 应计利息                                  |
| enrollment_start_date | _pandas.Timestamp_ | 回售登记开始日期                          |
| enrollment_end_date   | _pandas.Timestamp_ | 回售登记结束日期                          |
| payment_date          | _pandas.Timestamp_ | 资金到账日                                |
| put_amount            | _integer_  | 回售债券票面金额                          |
| put_code              | _str_      | 回售代码                                  |

#### 范例 {#rqdata-API-convertible-get_put_info-example}

- 获取 132002.XSHG 的回售情况：

```python
[In]convertible.get_put_info('132002.XSHG')
[Out]
                         enrollment_end_date  enrollment_start_date  exercise_price  interest_amount  interest_included  payment_date  put_amount    put_code
order_book_id  info_date
132002.XSHG  2018-06-25            2018-07-06    2018-07-02                      107.0  0.08                           1      2018-07-11  1.154681e+09  182187
              2018-07-16            2018-07-20    2018-07-16                      107.0  0.12                           1      2018-07-25  5.166000e+06  182152
              2018-07-24            2018-08-03    2018-07-30                      107.0  0.16                           1      2018-08-08  6.792000e+06  182153
...
```

### convertible.get_cash_flow - 获取可转债的现金流 {#rqdata-API-convertible-get_cash_flow}

```python
convertible.get_cash_flow(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债合约的现金流数据，支持按时间范围查询兑付日对应的数据。

#### 参数 {#rqdata-API-convertible-get_cash_flow-params}

| 参数           | 类型                                                           | 说明                                       |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                              | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list。           |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为初始的兑付日               |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认则返回开始日期后续所有兑付日 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_cash_flow-return}

- 返回*DataFrame*

| 字段                    | 类型       | 说明                 |
|-----|-----|-----|
| payment_date            | _pandas.Timestamp_ | 理论兑付日           |
| payment_date_act        | _pandas.Timestamp_ | 实际兑付日           |
| record_date             | _pandas.Timestamp_ | 债券登记日           |
| interest_payment_pretax | _float_    | 每百元面额付息(税前) |
| interest_payment        | _float_    | 每百元面额付息       |
| principal_payment       | _float_    | 每百元面额兑付现金   |
| cash_flow_pretax        | _float_    | 税前现金流           |
| cash_flow               | _float_    | 税后现金流           |

#### 范例 {#rqdata-API-convertible-get_cash_flow-example}

- 获取 110032.XSHG 的现金流情况：

```python
[In]convertible.get_cash_flow('110032.XSHG')
[Out]


                                record_date cash_flow_pretax principal_payment interest_payment_pretax   payment_date_act cash_flow interest_payment
order_book_id payment_date
110032.XSHG     2017-01-04       2017-01-03 0.200             0.0                 0.200                   2017-01-10     0.1600     0.1600
                2018-01-04       2018-01-03 0.500             0.0                 0.500                   2018-01-10     0.4000     0.4000
                2019-01-04       2019-01-03 1.000             0.0                 1.000                   2019-01-10     0.8000     0.8000
                2019-03-20       2019-03-19 100.304             100.0             0.304                   2019-03-26     100.2432 0.2432
```

### convertible.is_suspended - 判断可转债是否全天停牌 {#rqdata-API-convertible-is_suspended}

```python
convertible.is_suspended(order_book_ids,start_date=None,end_date=None)
```

获取可转债在一段时间内是否全天停牌的数据，支持单只或多只可转债查询。

#### 参数 {#rqdata-API-convertible-is_suspended-params}

| 参数           | 类型                                                     | 说明                                                     |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                        | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list                             |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为转债上市日期                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前日期，如果转债已经退市，则为退市日期 |

#### 返回 {#rqdata-API-convertible-is_suspended-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-convertible-is_suspended-example}

- 获取国轩转债从 2020 年 5 月 1 日至 2020 年 5 月 30 日的停牌情况：

```python
[In]convertible.is_suspended('128086.XSHE',20200501,20200530)
[Out]
         128086.XSHE
2020-05-06 False
2020-05-07 False
2020-05-08 False
2020-05-11 False
2020-05-12 False
2020-05-13 False
2020-05-14 False
2020-05-15 False
2020-05-18 False
2020-05-19 False
2020-05-20 True
2020-05-21 True
2020-05-22 True
2020-05-25 True
2020-05-26 True
2020-05-27 True
2020-05-28 True
2020-05-29 False
```

### convertible.get_instrument_industry - 获取转债所属行业分类信息 {#rqdata-API-convertible-get_instrument_industry}

```python
convertible.get_instrument_industry(order_book_ids,source='citics',level=1,date=None, market='cn')
```

获取指定日期可转债所属的行业分类数据，转债行业分类即为对应正股上市公司行业分类。例如分类标准可选 `citics`、`citics_2019`、`gildata`，也支持一级、二级、三级分类数据。

#### 参数 {#rqdata-API-convertible-get_instrument_industry-params}

| 参数           | 类型                                                     | 说明                                                                                                                              |
|-----|-----|-----|
| order_book_ids | _str_ OR _str list_                                      | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list                                                                                                  |
| source         | _str_                                                    | 指定行业分标准，默认为 citics；<br /> `citics`- 中信 2010 行业分类， `citics_2019` - 中信 2019 行业分类, `gildata` - 聚源行业分类 |
| level          | _int_                                                    | 行业分类级别，共三级，默认返回一级分类。参数 0,1,2,3 一一对应，其中 0 返回三级分类完整情况                                        |
| date           | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 行业分类指定查询日期，默认为当前最新，获取转债对应正股指定日期行业分类                                                            |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_instrument_industry-return}

| 字段                 | 类型  | 说明             |
|-----|-----|-----|
| first_industry_code  | _int_ | 一级行业分类代码 |
| first_industry_name  | _str_ | 一级行业分类名称 |
| second_industry_code | _int_ | 二级行业分类代码 |
| second_industry_name | _str_ | 二级行业分类名称 |
| third_industry_code  | _int_ | 三级行业分类代码 |
| third_industry_name  | _str_ | 三级行业分类名称 |

#### 范例 {#rqdata-API-convertible-get_instrument_industry-example}

- 获取当前转债所对应的中信一级行业分类

```python
[In]
convertible.get_instrument_industry('113029.XSHG')
[Out]
first_industry_code first_industry_name
order_book_id
113029.XSHG 27  电力设备
```

- 获取当前转债组所对应的中信行业的全部分类：

```python
[In]
convertible.get_instrument_industry(['125069.XSHE','113029.XSHG'],source='citics',level=0)
[Out]
    first_industry_code first_industry_name second_industry_code    second_industry_name    third_industry_code third_industry_name
order_book_id
125069.XSHE 42  房地产 4210    房地产开发管理 421020  商业地产
113029.XSHG 27  电力设备    2730    新能源设备   273010  风电
```

### convertible.get_industry - 获取指定行业分类下的转债列表 {#rqdata-API-convertible-get_industry}

```python
convertible.get_industry(industry,source='citics',date=None, market='cn')
```

获取指定行业分类下的可转债列表，支持通过行业名称、行业指数代码或行业代号查询。例如分类标准可选 `citics`、`citics_2019`、`gildata`，也可按指定日期筛选仍处于上市状态的转债列表。

#### 参数 {#rqdata-API-convertible-get_industry-params}

| 参数     | 类型                                                     | 说明                                                                                                                              |
|-----|-----|-----|
| industry | _str_                                                    | **必填参数**，对应行业分类名称                                                                                                    |
| source   | _str_                                                    | 指定行业分标准，默认为 citics；<br /> `citics`- 中信 2010 行业分类， `citics_2019` - 中信 2019 行业分类, `gildata` - 聚源行业分类 |
| date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 行业分类指定查询日期。<br />默认返回该行业所有转债列表；指定日期返回指定行业分类下该日期仍在上市状态下的转债列表；                |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_industry-return}

_list_

#### 范例 {#rqdata-API-convertible-get_industry-example}

- 获取指定行业分类、日期上市状态可转债 id 列表

```python
[In]
convertible.get_industry(industry='电气设备',source='citics_2019',date='2020-01-26')
[Out]
['113505.XSHG',
 '113546.XSHG',
 '113549.XSHG',
 '123014.XSHE',
 '123030.XSHE',
 '123034.XSHE',
 '128018.XSHE',
 '128042.XSHE',
 '128089.XSHE']
```

### convertible.get_accrued_interest_eod - 获取可转债日终应计利息 {#rqdata-API-convertible-get_accrued_interest_eod}

```python
convertible.get_accrued_interest_eod(order_book_ids,start_date=None,end_date=None)
```

获取可转债日终应计利息数据，应计利息从转债起息日起算，支持按时间范围查询。

#### 参数 {#rqdata-API-convertible-get_accrued_interest_eod-params}

| 参数           | 类型                                                     | 说明                                                                  |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                        | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询起始日期                                                          |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询截止日期，start_date ,end_date 不传参数时默认返回最近三个月的数据 |

#### 返回 {#rqdata-API-convertible-get_accrued_interest_eod-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-convertible-get_accrued_interest_eod-example}

- 获取指定可转债的应计利息数据

```python
[In]
convertible.get_accrued_interest_eod('110072.XSHG','20200805','20201101')
[Out]

            110072.XSHG
date
2020-08-18 0.000000
2020-08-19 0.000548
2020-08-20 0.001096
2020-08-21 0.001644
2020-08-22 0.002192
... ...
2020-10-28 0.038904
2020-10-29 0.039452
2020-10-30 0.040000
2020-10-31 0.040548
2020-11-01 0.041096

```

### convertible.get_call_announcement - 获取可转债赎回提示性公告数据 {#rqdata-API-convertible-get_call_announcement}

```python
convertible.get_call_announcement(order_book_ids,start_date=None,end_date=None, market='cn')
```

获取可转债赎回提示性公告数据，包含赎回和不赎回信息，支持按时间范围查询。

#### 参数 {#rqdata-API-convertible-get_call_announcement-params}

| 参数           | 类型                                                     | 说明                                                          |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                        | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list                                  |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询起始日期                                                  |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询截止日期，start_date ,end_date 不传参数时默认返回所有数据 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_call_announcement-return}

| 字段                  | 类型       | 说明                                             |
|-----|-----|-----|
| info_date             | _pandas.Timestamp_ | 公告日                                           |
| first_info_date       | _pandas.Timestamp_ | 首次发布赎回公告日                               |
| if_call               | _bool_     | 是否赎回                                         |
| if_issuer call        | _bool_     | 是否发行人赎回 (True-发行人赎回，False-到期赎回) |
| call_price            | _float_    | 赎回价格(扣税,元/张)                             |
| call_price_before_tax | _float_    | 赎回价格(含税,元/张)                             |
| stop_exe_start_date   | _pandas.Timestamp_ | 触发不行权区间起始日                             |
| stop_exe_end_date     | _pandas.Timestamp_ | 触发不行权区间截止日                             |
| update_time           | _pandas.Timestamp_ | 数据入库时间                                     |

#### 范例 {#rqdata-API-convertible-get_call_announcement-example}

- 获取指定可转债 id 赎回提示性公告数据

```python
[In]
convertible.get_call_announcement('113541.XSHG')
[Out]
                                    update_time   call_price  if_call  first_info_date  stop_exe_start_date call_price_before_tax stop_exe_end_date
order_book_id   info_date
113541.XSHG 2021-11-23  2021-11-22 17:09:26         NaN     False            NaT          2021-11-23                   NaN        2022-05-22
                2022-06-14  2022-06-14 00:00:00     100.746 True     2022-05-24                 NaT               100.932               NaT
```

### convertible.get_close_price - 获取可转债全价净价数据 {#rqdata-API-convertible-get_close_price}

```python
convertible.get_close_price(order_book_ids,start_date=None,end_date=None,fields=None, market='cn')
```

获取可转债收盘价的全价和净价数据，支持按时间范围查询。例如可获取 clean_price 和 dirty_price 数据。

#### 参数 {#rqdata-API-convertible-get_close_price-params}

| 参数           | 类型                                                     | 说明                                                                  |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                        | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询起始日期                                                          |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询截止日期，start_date ,end_date 不传参数时默认返回最近三个月的数据 |
| fields         | _str OR str list_                                        | 查询字段，可选字段见下方返回，默认返回所有字段                        |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_close_price-return}

| 字段        | 类型       | 说明                 |
|-----|-----|-----|
| datetime    | _pandas.Timestamp_ | 交易日期             |
| clean_price | _float_    | 可转债当日收盘价净价 |
| dirty_price | _float_    | 可转债当日收盘价全价 |

#### 范例 {#rqdata-API-convertible-get_close_price-example}

- 获取指定可转债 id 赎回提示性公告数据

```python
[In]
convertible.get_close_price(['132020.XSHG','132026.XSHG'],start_date='2024-04-30', end_date='2024-04-30')
[Out]

                             clean_price  dirty_price
order_book_id date
132020.XSHG     2024-04-30   110.673   111.207247
132026.XSHG     2024-04-30   125.525   125.616507
```

## 可转债衍生数据 {#rqdata-API-convertible-derive}

### convertible.get_indicators - 获取可转债衍生指标 {#rqdata-API-convertible-get_indicators}

```python
convertible.get_indicators(order_book_ids,start_date=None, end_date=None,fields=None)
```

获取可转债衍生指标数据，支持按时间范围查询多类指标。例如可获取转股系数、转股价值、转股溢价率等转股相关指标，也包括到期收益率、回售收益率以及隐含波动率、delta、gamma、vega 等指标。

#### 参数 {#rqdata-API-convertible-get_indicators-params}

| 参数           | 类型                                                     | 说明                     |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                        | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list           |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询开始日期             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 查询结束日期，start_date ,end_date 不传参数时默认返回最近3个月的数据             |
| fields         | _str OR str list_                                        | 查询字段，可选字段见下方返回，默认返回所有字段 |

#### 返回 {#rqdata-API-convertible-get_indicators-return}

| 字段                                  | 类型    | 说明                 | 计算备注                                |
|-----|-----|-----|-----|
| conversion_coefficient                | _float_ | 转股系数             | 转股系数=100/转股价                                                                                                                                                                                                                                                                                                              |
| conversion_value                      | _float_ | 转股价值             | 转股价值=正股收盘价*转股系数                                                                                                                                                                                                                                                                                                    |
| conversion_premium                    | _float_ | 转股溢价率           | 转股溢价率=(转债收盘全价/转股价值-1)*100%                                                                                                                                                                                                                                                                                       |
| yield_to_maturity                     | _float_ | 税后到期收益率       | 当日至到期日之间产生的税后未来现金流（到期本金为到期赎回价<sup>[1]</sup>）贴现为转债当前收盘全价的贴现收益率（若该转债在当日已发布强赎公告，则该指标取值为空）                                                                                                                                                                   |
| yield_to_maturity_pretax              | _float_ | 税前到期收益率       | 当日至到期日之间产生的税前未来现金流（到期本金为到期赎回价<sup>[1]</sup>）贴现为转债当前收盘全价的贴现收益率（若该转债在当日已发布强赎公告，则该指标取值为空）                                                                                                                                                                   |
| yield_to_put                          | _float_ | 税后回售收益率       | 当日至预测回售日<sup>[2]</sup>之间产生的税后未来现金流贴现为转债当前收盘全价的贴现收益率（若该转债没有回售条款，则该指标取值为空）                                                                                                                                                                                               |
| yield_to_put_pretax                   | _float_ | 税前回售收益率       | 当日至预测回售日<sup>[2]</sup>之间产生的税前未来现金流贴现为转债当前收盘全价的贴现收益率（若该转债没有回售条款，则该指标取值为空）                                                                                                                                                                                               |
| double_low_factor                     | _float_ | 双低指标             | 双低指标=转债收盘全价+转股溢价率*100                                                                                                                                                                                                                                                                                            |
| call_trigger_price                    | _float_ | 赎回触发价           | 赎回触发价=当期转股价*130%（无数据代表没有强赎条款）                                                                                                                                                                                                                                                                            |
| put_trigger_price                     | _float_ | 回售触发价           | 回售触发价=当期转股价*70%（无数据代表没有回售条款）                                                                                                                                                                                                                                                                             |
| conversion_price_reset_trigger_price  | _float_ | 下修触发价           | 下修转股价触发价=当期转股价*下修触发水平（无数据代表没有下修条款）                                                                                                                                                                                                                                                              |
| turnover_rate                         | _float_ | 换手率               | 换手率=转债当日成交额/转债剩余市值                                                                                                                                                                                                                                                                                               |
| remaining_size                        | _float_ | 剩余规模（元）       | 剩余规模=未转股的转债数量*转债面值                                                                                                                                                                                                                                                                                              |
| convertible_market_cap_ratio          | _float_ | 转债市值占比         | 转债剩余市值=转债剩余规模/面值*现价<br>转债占比=转债剩余市值/正股总市值                                                                                                                                                                                                                                                         |
| pb_ratio                              | _float_ | 市净率               | 当前正股总市值 / 归属母公司股东权益合计 mrq                                                                                                                                                                                                                                                                                      |
| put_qualified_days                    | _float_ | 回售已满足天数       | 根据回售条款指定时间区间，统计收盘价低于回售触发价的交易日数量                                                                                                                                                                                                                                                                   |
| call_qualified_days                   | _float_ | 赎回已满足天数       | 根据赎回条款指定时间区间，统计正股收盘价高于赎回触发价的交易日数量                                                                                                                                                                                                                                                               |
| conversion_price_reset_qualified_days | _float_ | 转股价下修已满足天数 | 根据下修条款指定时间区间，统计正股收盘价低于下修触发价的交易日数量                                                                                                                                                                                                                                                               |
| put_status                            | _float_ | 回售条款满足状态     | 根据回售条款，查看收盘价低于回售触发价的交易日数量是否达到回售条件，如还未进入回售期或没有回售条款状态标为 0，如进入回售期但还没有满足回售条件的状态为 1，如满足回售条件的状态为 2                                                                                                                                               |
| call_status                           | _float_ | 强赎条款满足状态     | 根据强赎条款，查看收盘价高于赎回触发价的交易日数量是否达到强赎条件，如还未进入转股期或没有强赎条款状态为 0，如进入转股期但还没有满足赎回条件的状态为 1，如满足赎回条件但还未发强赎公告的状态标为 2，如发布了强赎公告的状态为 3                                                                                                   |
| conversion_price_reset_status         | _float_ | 下修条款满足状态     | 根据转股价下修条款，查看收盘价低于下修触发价的交易日数量是否达到下修条件，如还未满足下修条件或没有下修条款状态标为 0，满足下修条件状态为 1                                                                                                                                                                                       |
| pure_bond_value_1                     | _float_ | 纯债价值             | $P = \sum_{t=1}^{n} \frac{I}{(1+R)^{t}} + \frac{P_0}{(1+R)^{t}}$<br>式中 P：债券的价格；$P_0$：债券面值；I：每年利息；R：市场利率或投资者要求的必要报酬率；n:付息总期数;<br>其中 R 选取相同评级的中债企业债即期收益率作为折现率                                                                                                  |
| pure_bond_value_premium_1             | _float_ | 纯债溢价率           | （转债收盘全价 / 纯债价值 -1）*100%                                                                                                                                                                                                                                                                                             |
| iv                                    | _float_ | 隐含波动率           | 基于 BS 模型使用布伦特方法计算隐含波动率，涉及如下参数：<br>行权价：以可转债最新转股价为行权价<br>标的价格：以当日正股收盘价（不复权）为标的价格<br>待偿期：以当日至转债到期日为待偿期<br>期权价：以可转债收盘价减去纯债价值再除以转股比例为期权价<br>无风险利率：以一年期国债利率为无风险利率<br>股息率：以滚动四季度股息率估计 |
| delta                                 | _float_ | delta                | 转债价格对正股股价的敏感度                                                                                                                                                                                                                                                                                                       |
| theta                                 | _float_ | theta                | 转债价格对时间的偏导                                                                                                                                                                                                                                                                                                             |
| gamma                                 | _float_ | gamma                | 转债价格对正股股价的二阶导                                                                                                                                                                                                                                                                                                       |
| vega                                  | _float_ | vega                 | 转债价格对隐含波动率的偏导                                                                                                                                                                                                                                                                                                       |
| pure_bond_value_premium               | _float_ | deprecate            |                                                                                                                                                                                                                                                                                                                                  |
| pure_bond_value_premium_pretax        | _float_ | deprecate            |                                                                                                                                                                                                                                                                                                                                  |
| pure_bond_value                       | _float_ | deprecate            |                                                                                                                                                                                                                                                                                                                                  |
| pure_bond_value_pretax                | _float_ | deprecate            |                                                                                                                                                                                                                                                                                                                                  |

- [1]到期赎回价：对于没有到期赎回价的转债，将其到期赎回价填为本金加最后一期利息
- [2]预计回售日：对于还没有进入回售期的转债，预测回售日期 = 回售期开始日期 + 回售触发自然日天数（基于 window_days 推算）+ 回售资金到账所需时间（假设为 30 自然日）
对于已经进入回售期的转债，预测回售日期=计算日+ 回售触发自然日天数（基于 window_days 推算）+ 回售资金到账所需时间（假设为 30 自然日）

#### 范例 {#rqdata-API-convertible-get_indicators-example}

- 获取指定日期可转债列表衍生指标数据

```python
[In]
convertible.get_indicators(['110031.XSHG','110033.XSHG'],start_date=20200803, end_date=20200803)
[Out]
  call_qualified_days call_status call_trigger_price conversion_coefficient conversion_premium conversion_price_reset_qualified_days conversion_price_reset_status conversion_price_reset_trigger_price conversion_value convertible_market_cap_ratio ... pure_bond_value_pretax put_qualified_days put_status put_trigger_price remaining_size turnover_rate yield_to_maturity yield_to_maturity_pretax yield_to_put yield_to_put_pretax
order_book_id date
110031.XSHG 2020-08-03 0 1 28.028 4.638219 0.323528 20 1 19.404 85.204082 0.070301 ... 104.444003 0 1 15.092 2.398829e+09 0.007542 -0.074144 -0.059667 -0.127928 -0.126791
110033.XSHG 2020-08-03 0 1 9.347 13.908206 0.153650 7 0 6.471 98.470097 0.092509 ... 105.106132 0 1 5.033 1.211731e+09 0.005133 -0.036681 -0.024483 -0.447469 -0.440123
```

### convertible.get_credit_rating - 获取可转债债项评级数据 {#rqdata-API-convertible-get_credit_rating}

```python
convertible.get_credit_rating(order_book_ids, start_date=None, end_date=None, institutions=None, market='cn')
```
获取可转债债项评级数据，支持按时间范围和评级机构筛选。例如评级机构可选联合信用评级有限公司、联合资信评估股份有限公司、中诚信国际信用评级有限责任公司等。

#### 参数 {#rqdata-API-convertible-get_credit_rating-params}

| 参数           | 类型              | 说明                       |
|-----|-----|-----|
| order_book_ids | _str OR str list_ | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list             |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_             | 查询起始日期               |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_             | 查询截止日期，start_date ,end_date 不传参数时默认返回所有数据|
| institutions   | _str_             | 默认返回所有评级机构。可选项见下方表格 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

##### 参数字段说明 {#rqdata-API-convertible-get_credit_rating-params-desc} <tips />

| institutions 可选项             |
|-----|
| 上海新世纪资信评估投资服务有限公司 |
| 上海资信有限公司                   |
| 东方金诚国际信用评估有限公司       |
| 中债资信评估有限责任公司          |
| 中国诚信信用管理股份有限公司       |
| 中证鹏元资信评估股份有限公司       |
| 中诚信国际信用评级有限责任公司     |
| 中诚信证评数据科技有限公司         |
| 云南省资信评估事务所               |
| 大公国际资信评估有限公司          |
| 大普信用评级股份有限公司           |
| 安融信用评级有限公司               |
| 惠誉博华信用评级有限公司           |
| 惠誉国际信用评级有限公司           |
| 标准普尔评级公司                   |
| 标普信用评级(中国)有限公司         |
| 福建省资信评级委员会               |
| 穆迪评级公司                       |
| 联合信用评级有限公司               |
| 联合资信评估股份有限公司           |
| 远东资信评估有限公司               |

#### 返回 {#rqdata-API-convertible-get_credit_rating-return}

| 字段           | 类型         | 说明           |
|-----|-----|-----|
| order_book_ids | _str_          | 可转债合约代码 |
| credit_date    | _pandas.Timestamp_     | 债项评级日期   |
| info_date      | _pandas.Timestamp_     | 公告发布日期   |
| info_source    | _str_ | 信息来源       |
| institution    | _str_          | 债项评级机构   |
| credit         | _str_          | 债项评级 （信用评级中：SPC 标识为标普信用评级，pi 为主动评级，u 为主动评级，sf 为结构融资产品的评级）      |
| rice_create_tm | _pandas.Timestamp_     | 米筐入库时间   |

#### 范例 {#rqdata-API-convertible-get_credit_rating-example}

- 获取指定可转债 id 债项评级数据

```python
[In]
convertible.get_credit_rating('110031.XSHG')
[Out]
                            info_date info_source                                             institution          credit    rice_create_tm
order_book_id credit_date
110031.XSHG     2014-08-21 2015-06-10 6-10 资信评级机构为本次发行可转换公司债券出具的资信评级报告 联合信用评级有限公司    AAA   2023-12-11 07:00:18
                2015-07-31 2015-08-04 航天信息2014年可转换公司债券跟踪评级分析报告             联合信用评级有限公司     AAA   2023-12-11 07:00:18
                2016-05-17 2016-05-18 航天信息：可转换公司债券2016年跟踪评级报告                 联合信用评级有限公司     AAA   2023-12-11 07:00:18
                2017-05-17 2017-05-19 航天信息：关于“航信转债”跟踪信用评级结果的公告             联合信用评级有限公司    AAA   2023-12-11 07:00:18
                2018-04-26 2018-04-27 航天信息可转换公司债券2018年跟踪评级报告                 联合信用评级有限公司    AAA   2023-12-11 07:00:18
                2019-05-24 2019-05-28 航天信息可转换公司债券2019年跟踪评级报告                 联合信用评级有限公司    AAA   2023-12-11 07:00:18
                2020-06-05 2020-06-10 航天信息：可转换公司债券2020年跟踪评级报告                 联合信用评级有限公司    AAA   2023-12-11 07:00:18
                2021-05-25 2022-02-10 航天信息股份有限公司公开发行可转换公司债券2021年跟踪评级报告 联合资信评估股份有限公司 AAA   2023-12-11 07:00:18
```

### convertible.get_std_discount - 获取可转债标准劵折算率 {#rqdata-API-convertible-get_std_discount}

```python
convertible.get_std_discount(order_book_ids, start_date=None, end_date=None, market='cn')
```

获取可转债标准券折算率数据，支持按转债代码和时间范围查询。

#### 参数 {#rqdata-API-convertible-get_std_discount-params}

| 参数           | 类型                                                           | 说明                       |
|-----|-----|-----|
| order_book_ids | _str OR str list_                                              | **必填参数**，可转债合约代码，可传入 order_book_id, order_book_id list             |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为当前交易日 |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为当前交易日 |
| market   | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；           |

#### 返回 {#rqdata-API-convertible-get_std_discount-return}

| 字段            | 类型    | 说明                                           |
|-----|-----|-----|
| discount_factor | _float_ | 标准券折算率(每百元面值折算成标准券所乘的系数) |

#### 范例 {#rqdata-API-convertible-get_std_discount-example}

- 获取指定可转债 id 的标准劵折算率

```python
[In]
convertible.get_std_discount('110059.XSHG', start_date=20240615, end_date=20240621)
[Out]
                                discount_factor
order_book_id     date
110059.XSHG       2024-06-17     0.73
                  2024-06-18     0.73
                  2024-06-19     0.73
                  2024-06-20     0.73
                  2024-06-21     0.73
```
