## econ.get_reserve_ratio - 获取存款准备金率 {#rqdata-API-econ-get_reserve_ratio}

```
econ.get_reserve_ratio(reserve_type,start_date,end_date,date_type, market='cn')
```

获取存款准备金率数据，支持按信息公布日期范围查询不同类别机构的存款准备金率。例如可获取大型金融机构（major）和其他金融机构（other）的存款准备金率数据。

#### 参数 {#rqdata-API-econ-get_reserve_ratio-param}

| 参数         | 类型                                                           | 说明                                                                                                    |
|-----|-----|-----|
| reserve_type | _str_ or _str list_                                            | 目前有大型金融机构（'major'） 和 其他金融机构（'other'）两种分类。<br/>默认为 all，即所有类别都会返回。 |
| start_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年的查询当日（基准为信息公布日）。                                                    |
| end_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为查询当日。                                                                              |
| market     | _str_                                                          | 默认是中国内地市场('cn')  |

#### 返回 {#rqdata-API-econ-get_reserve_ratio-return}

_pandas dataframe_

| 字段           | 类型                 | 说明                 |
|-----|-----|-----|
| reserve_type   | _str_               | 存款准备金类别       |
| info_date      | _pandas.Timestamp_   | 消息公布日期         |
| effective_date | _pandas.Timestamp_   | 存款准备金率生效日期 |
| ratio_floor    | _float_             | 存款准备金下限       |
| ratio_ceiling  | _float_             | 存款准备金上限       |

#### 范例 {#rqdata-API-econ-get_reserve_ratio-example}

```python
[In]
econ.get_reserve_ratio(reserve_type='major',start_date='20170101',end_date='20181017')

[Out]

            reserve_type 	                effective_date 	ratio_ceiling 	ratio_floor
info_date
2018-10-07 	major_financial_institution 	2018-10-15 	 	15.0 	        15.0
2018-04-17 	major_financial_institution 	2018-04-25 	 	16.0 	        16.0

```

## econ.get_money_supply - 获取货币供应量 {#rqdata-API-econ-get_money_supply}

```
econ.get_money_supply(start_date,end_date, market='cn')
```

获取货币供应量数据，支持按信息公布日期范围查询市场现金流通量、狭义货币和广义货币数据。例如可获取 M0、M1、M2 及其同比数据。

#### 参数 {#rqdata-API-econ-get_money_supply-param}

| 参数       | 类型                                                           | 说明                                                 |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为去年的查询当日（基准为信息公布日）。 |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为查询当日。                           |
| market     | _str_                                                          | 默认是中国内地市场('cn')  |

#### 返回 {#rqdata-API-econ-get_money_supply-return}

_pandas dataframe_

| 字段           | 类型                 | 说明                   |
|-----|-----|-----|
| info_date      | _pandas.Timestamp_   | 消息公布日期           |
| effective_date | _pandas.Timestamp_   | 货币供应量生效日期     |
| m0             | _float_             | 市场现金流通量(百万元) |
| m1             | _float_             | 狭义货币(百万元)       |
| m2             | _float_             | 广义货币(百万元)       |
| m0_growth_yoy  | _float_             | 市场现金流通量同比     |
| m1_growth_yoy  | _float_             | 狭义货币同比           |
| m2_growth_yoy  | _float_             | 广义货币同比           |

#### 范例 {#rqdata-API-econ-get_money_supply-example}

```python
[In]
econ.get_money_supply(start_date='20180801',end_date='20181017')

[Out]

 	          effective_date 	m2 	     m1 	    m0    m2_growth_yoy  m1_growth_yoy 	m0_growth_yoy
info_date
2018-09-21 	2018-08-31 	178867043.0 	53832464.0 	6977539.0 	0.082 	  0.039 	    0.033
2018-08-16 	2018-07-31 	177619611.0 	53662429.0 	6953059.0 	0.085 	  0.051 	    0.036

```

## econ.get_factors - 获取宏观因子数据 {#rqdata-API-econ-get_factors}

```
econ.get_factors(factors, start_date, end_date, market='cn')
```

获取宏观因子数据，支持按因子名称和时间范围查询指定宏观指标。例如可获取工业品出厂价格指数 PPI 当月同比等宏观因子数据。

#### 参数 {#rqdata-API-econ-get_factors-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| factors    | _str_      | **必填参数**，宏观因子名称，<a href="https://assets.ricequant.com/vendor/rqdata/econ_get_factors.xlsx" target="_blank">点击下载</a > |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，起始日期                                                                                                               |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，截止日期                                                                                                               |
| market     | _str_                                                          | 默认是中国内地市场('cn')  |

#### 返回 {#rqdata-API-econ-get_factors-return}

_pandas dataframe_

| 字段       | 类型               | 说明         |
|-----|-----|-----|
| info_date  | _str_             | 因子发布日期 |
| start_date | _pandas.Timestamp_ | 起始日期     |
| end_date   | _pandas.Timestamp_ | 截止日期     |
| value      | _float_           | 指标数据     |

#### 范例 {#rqdata-API-econ-get_factors-example}

- 获取工业品出厂价格指数 PPI*当月同比*(上年同月=100)在 2017-08-01 到 2018-08-01 数据。

```python
[In]econ.get_factors( factors='工业品出厂价格指数PPI_当月同比_(上年同月=100)', start_date='20170801', end_date='20180801')
[Out]
                    start_date	end_date	value
factor	info_date
工业品出厂价格指数PPI_当月同比_(上年同月=100)
2017-08-09 09:30:00	2017-06-30	2017-07-31	105.5000
2017-09-09 09:30:00	2017-07-31	2017-08-31	106.3000
2017-10-16 09:30:00	2017-08-31	2017-09-30	106.9000
2017-11-09 09:30:00	2017-09-30	2017-10-31	106.9000
2017-12-09 09:30:00	2017-10-31	2017-11-30	105.8000
 ...
```

## econ.get_fixing_repo_rate -获取回购定盘利率 {#rqdata-API-econ-get_fixing_repo_rate}

```python
econ.get_fixing_repo_rate(start_date, end_date, fields)
```
获取一段时间内的回购定盘利率，数据为2004年至今，fileds可选FR001,FR007,FR014,FDR001,FDR007,FDR014

#### 参数 {#rqdata-API-econ-get_fixing_repo_rate-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_| 开始日期                                                                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据                                                                                                            |
| fields     | _str_ or _str_list_                                                | 标准期限，默认返回全部。可选字段FR001,FR007,FR014,FDR001,FDR007,FDR014 |


:::  tip 回购定盘利率品种说明

FDR001、FDR007和FDR014为银银间回购定盘利率品种, 对应含义为 隔夜回购/7天回购/14天回购利率

:::

#### 返回 {#rqdata-API-econ-get_fixing_repo_rate-return}

_pandas dataframe_, index为info_date, columns为品种名称

#### 范例{#rqdata-API-econ-get_fixing_repo_rate-example}

- 获取2025-03-11到2025-03-13之间的回购定盘利率
```python
[In] rqdatac.econ.get_fixing_repo_rate(20250311,20250313)
[Out]
	        FR001	FR007	FR014	FDR001	FDR007	FDR014
date						
2025-03-11	0.0179	0.0183	0.0193	0.0178	0.0182	0.0190
2025-03-12	0.0178	0.0183	0.0193	0.0177	0.0181	0.0186
2025-03-13	0.0178	0.0182	0.0192	0.0178	0.0181	0.0185

```

## econ.get_us_treasury_yield -获取美国国债利率 {#rqdata-API-econ-get_us_treasury_yield}

```python
econ.get_us_treasury_yield(start_date=None, end_date=None, tenor=None)
```
获取美国市场国债利率

#### 参数 {#rqdata-API-econ-get_us_treasury_yield-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_| 开始日期                                                                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |结束日期，不传入 start_date, end_date 则默认返回最近三个月的数据                                                                                                            |
| tenor     | _str_                                                 | 	标准期限，默认返回全部。例如，'1M' - 1 个月，'1Y' - 1 年 |



#### 返回 {#rqdata-API-econ-get_us_treasury_yield-return}

_pandas DataFrame_

| 返回   | 类型               | 说明                                                                                                                                   |
|-----|-----|-----|
| date   | _pandas.Timestamp_ | 日期                                                                                                                                   |
| us_treasury_yield | _float_           | '1M'：1 个月 <br/>'3M'：3 个月 <br/>'6M'：6 个月 <br/>'1M'：1 年 <br/> '2Y'：2 年 <br/>'3Y'：3 年 <br/>'5Y'：5 年 <br/>'7Y'：7 年 <br/> '10Y'：10 年 <br/>'20Y'：20 年 <br/>'30Y'：30 年|
#### 范例{#rqdata-API-econ-get_us_treasury_yield-example}

- 获取2026-03-16到2026-06-12之间的美国国债利率
```python
[In] rqdatac.econ.get_us_treasury_yield(start_date=None, end_date=None, tenor=["3M", "2Y", "10Y", "30Y"]) 
[Out]
	        3M 2Y 10Y 30Y
date						
2026-03-16 0.0372 0.0368 0.0423 0.0486
2026-03-17 0.0372 0.0368 0.0420 0.0485
2026-03-18 0.0373 0.0376 0.0426 0.0488
2026-03-19 0.0373 0.0379 0.0425 0.0483
2026-03-20 0.0374 0.0388 0.0439 0.0496
... ... ... ... ...
2026-06-08 0.0380 0.0415 0.0456 0.0503
2026-06-09 0.0379 0.0413 0.0453 0.0501
2026-06-10 0.0379 0.0413 0.0455 0.0503
2026-06-11 0.0378 0.0405 0.0445 0.0495
2026-06-12 0.0378 0.0409 0.0448 0.0497
```

## econ.get_index -获取宏观指数数据 {#rqdata-API-econ-get_index}

```
econ.get_index(names, start_date, end_date)
```

获取宏观指数数据，支持按指数名称和时间范围查询指定宏观指数行情。

支持的指数列表如下

|names|  起始日期|
|---------- | ---------- | 
|费城半导体指数|1994-05-04|
|海岬型运费指数|1999-04-30|
|成品油运输指数|2001-12-27|
|波罗的海干散货指数|1988-10-19|
|巴拿马型运费指数|1998-12-31|
|菜篮子产品批发价格指数|2005-09-27|
|农副指数|2009-02-11|
|农产品批发价格总指数|2005-09-27|
|原油运输指数|2001-12-27|
|超灵便型船运价指数|2006-10-31|
|大宗商品价格|2009-02-10|
|建材指数|2010-07-17|
|能源指数|2009-02-11|
|物流景气指数|2013-09-01|
|手机出货量:当月值|2012-01-01|


#### 参数 {#rqdata-API-econ-get_index-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| names    | _str_      | **必填参数**，宏观指数名称|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，起始日期                                                                                                               |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，截止日期                                                                                                               |


#### 返回 {#rqdata-API-econ-get_index-return}

_pandas dataframe_

| 字段       | 类型               | 说明         |
|-----|-----|-----|
| start_date | _pandas.Timestamp_ | 起始日期     |
| end_date   | _pandas.Timestamp_ | 截止日期     |
| value      | _float_           | 指数数据     |

#### 范例 {#rqdata-API-econ-get_index-example}

- 获取建材指数, 菜篮子产品批发价格指数, 农副指数在 2026-06-15 到 2026-06-18 的数据。
```python
[In]econ.get_index(["建材指数", "菜篮子产品批发价格指数", "农副指数"], 20260615, 20260618)
[Out]
                           value
name         date      
农副指数      2026-06-15    980.00
             2026-06-16    977.00
             2026-06-17    977.00
             2026-06-18    975.00
建材指数      2026-06-15    916.00
             2026-06-16    915.00
             2026-06-17    914.00
             2026-06-18    909.00
菜篮子产品批发价格指数  
             2026-06-15    113.12
             2026-06-16    112.76
             2026-06-17    112.66
             2026-06-18    112.57
```

## econ.get_oil_price -获取中国汽柴油历史调价信息 {#rqdata-API-econ-get_oil_price}

```python
econ.get_oil_price(start_date=None, end_date=None)
```
获取中国汽柴油历史调价信息

#### 参数 {#rqdata-API-econ-get_oil_price-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_| 开始日期，默认为 end_date 往前三个月。                                                                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |结束日期，默认为查询当日。若该日不是调价日，则返回该日之前最近一次调价后的价格。                                                                                                            |

#### 返回 {#rqdata-API-econ-get_oil_price-return}

_pandas DataFrame_

| 返回   | 类型               | 说明                                                                                                                                   |
|-----|-----|-----|
| date   | _pandas.Timestamp_ | 调价日期                                                                                                                                   |
| gasoline  | _float_           | 全国汽油价格，单位元/吨。|
| diesel  | _float_           | 全国柴油价格，单位元/吨。|
#### 范例{#rqdata-API-econ-get_oil_price-example}

- 获取2026-01-01到2026-02-10之间的汽柴油调价历史
```python
[In] rqdatac.econ.get_oil_price(start_date=2026-01-01, end_date=2026-02-10) 
[Out]
	        gasoline diesel
date						
2026-01-21 7670 6685
2026-02-04 7875 6880
```

## econ.get_gold_reserves -获取黄金储备数据 {#rqdata-API-econ-get_gold_reserves}

```python
econ.get_gold_reserves(start_date=None, end_date=None, market='cn')
```
获取中国黄金储备数据

#### 参数 {#rqdata-API-econ-get_gold_reserves-param}

| 参数       | 类型       | 说明                                                                                                                                 |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_| 开始日期，默认为 end_date 往前一年；最早不早于 2015-06-01。                                                                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |结束日期，默认为查询当日所在月份。                                                                                                            |
| market   | _str_ |市场，目前仅支持中国内地市场 cn。                                                                                                            |
#### 返回 {#rqdata-API-econ-get_gold_reserves-return}

_pandas DataFrame_

| 返回   | 类型               | 说明                                                                                                                                   |
|-----|-----|-----|
| date   | _pandas.Timestamp_ |月度日期，作为返回表的索引。查询区间内每个月都会出现。                                                                                                                                   |
| value  | _float_           | 黄金储备，单位为亿美元。没有该月接口数据时为空值。|

#### 范例{#rqdata-API-econ-get_gold_reserves-example}

- 获取2026-01-01到2026-04-30之间的中国黄金储备月度数据
```python
[In] rqdatac.econ.get_gold_reserves(start_date=2026-01-01, end_date=2026-04-30, market="cn") 
[Out]
	        value
date						
2026-01-01 3695.82
2026-02-01 3875.88
2026-03-01 3427.63
2026-04-01 3441.72
```

## econ.get_interbank_pledged_repo_rate - 获取银行间质押式回购加权利率 {#rqdata-API-econ-get_interbank_pledged_repo_rate}

```python
econ.get_interbank_pledged_repo_rate(start_date=None,end_date=None,fields=None,market='cn')
```
获取银行间质押式回购加权利率，例如 `DR001`、`DR007` 等。

#### 参数 {#rqdata-API-econ-get_interbank_pledged_repo_rate-param}

| 参数       | 类型       | 说明                                                                                                              |
|-----|-----|-----|
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，不传时默认取最近三个月的数据。  |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |结束日期                            |
| fields     | _str or str list_                                               |默认返回全部。可选字段'DR001', 'DR007', 'DR014', 'DR021', 'DR1M','DR4M'     |
| market     | _str_                                                           |市场，目前仅支持中国内地市场 cn。                            |
#### 返回 {#rqdata-API-econ-get_interbank_pledged_repo_rate-return}

_pandas DataFrame_

| 返回   | 类型               | 说明                     |
|-----|-----|-----|
| DR001  | _float_           |隔夜回购加权平均利率        |
| DR007  | _float_           |7天期回购加权平均利率       |
| DR014  | _float_           |14天期回购加权平均利率      |
| DR021  | _float_           |21天期回购加权平均利率      |
| DR1M   | _float_           |1个月期回购加权平均利率     |
| DR4M   | _float_           |4个月期回购加权平均利率      |

#### 范例{#rqdata-API-econ-get_interbank_pledged_repo_rate-example}

- 获取 2026-06-10 到 2026-06-17 之间的 DR001、DR007
```python
[In] rqdatac.econ.get_interbank_pledged_repo_rate(start_date=20260610,end_date=20260617,fields=['DR001','DR007'],market='cn')
[Out]
             DR001	DR007
date		
2026-06-10	0.013939	0.014152
2026-06-11	0.014046	0.014435
2026-06-12	0.014162	0.014551
2026-06-15	0.014356	0.014671
2026-06-16	0.014360	0.014856
2026-06-17	0.014246	0.014645

```

## econ.get_cny_reference_rate -获取人民币参考汇率{#rqdata-API-econ-get_cny_reference_rate}

```python
econ.get_cny_reference_rate(start_date, end_date, fields)
```
获取人民币参考汇率中间价数据

#### 参数 {#rqdata-API-econ-get_cny_reference_rate-parameters}
| 参数       | 类型       | 说明                                                                                                                                 |
| ---------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_| **必填参数**，开始日期                                                                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ |**必填参数**，结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据     |
| fields   | _str_ |默认返回全部，可选货币对见下述表格                                                                                                           |

可选货币对：
|currency_pair     | 说明      |
| ---------- | ----------|	
|100JPY/CNY	|100日元/人民币|
|AUD/CNY	|澳元/人民币|
|CAD/CNY	|加元/人民币|
|CHF/CNY	|瑞士法郎/人民币|
|CNY/AED	|人民币/阿联酋迪拉姆|
|CNY/DKK	|人民币/丹麦克朗|
|CNY/HUF	|人民币/匈牙利福林|
|CNY/KRW	|人民币/韩元|
|CNY/MOP	|人民币/澳门元|
|CNY/MXN	|人民币/墨西哥比索|
|CNY/MYR	|人民币/马来西亚林吉特|
|CNY/NOK	|人民币/挪威克朗|
|CNY/PLN	|人民币/波兰兹罗提|
|CNY/RUB	|人民币/俄罗斯卢布|
|CNY/SAR	|人民币/沙特里亚尔|
|CNY/SEK	|人民币/瑞典克朗|
|CNY/THB	|人民币/泰铢|
|CNY/TRY	|人民币/土耳其里拉|
|CNY/ZAR	|人民币/南非兰特|
|EUR/CNY	|欧元/人民币|
|GBP/CNY	|英镑/人民币|
|HKD/CNY	|港元/人民币|
|NZD/CNY	|新西兰元/人民币|
|SGD/CNY	|新加坡元/人民币|
|USD/CNY	|美元/人民币|
 

#### 返回 {#rqdata-API-econ-get_cny_reference_rate-return}

_pd.DataFrame_,index为date, columns为货币对

#### 范例 {#rqdata-API-econ-get_cny_reference_rate-example}

```python
[In] econ.get_cny_reference_rate('2023-01-01', '2023-01-03', 'USD/CNY')
[Out]
currency_pair	USD/CNY
date	
2023-01-03	6.9475
2023-01-04	6.9131
2023-01-05	6.8926
2023-01-06	6.8912
2023-01-09	6.8265
2023-01-10	6.7611
```
