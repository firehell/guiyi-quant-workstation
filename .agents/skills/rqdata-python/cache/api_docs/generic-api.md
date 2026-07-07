## 行情、交易日及合约信息 {#rqdata-API-contract}

### all_instruments - 获取所有合约基础信息 {#rqdata-API-all_instruments}

```python
all_instruments(type=None, date=None, market='cn')
```

获取指定市场的所有合约基础信息，支持按合约类型和日期筛选。例如可查询股票、ETF、LOF 等合约类型，也支持按指定日期筛选可交易合约。

#### 参数 {#rqdata-API-all_instruments-params}

| 参数   | 类型                                                           | 说明                                                                |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| type   | _str_                                                          | 需要查询合约类型，例如：type='CS'代表股票。默认是所有类型           |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定日期，筛选指定日期可交易的合约                                  |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

##### 其中 type 参数传入的合约类型和对应的解释如下：

| 合约类型    | 说明                                                              |
| ----------- | ----------------------------------------------------------------- |
| CS          | Common Stock, 即股票                                              |
| ETF         | Exchange Traded Fund, 即交易所交易基金                            |
| LOF         | Listed Open-Ended Fund，即上市型开放式基金 （以下分级基金已并入） |
| INDX        | Index, 即指数                                                     |
| Future      | Futures，即期货，包含股指、国债和商品期货                         |
| Spot        | Spot，即现货，目前包括上海黄金交易所现货合约                      |
| Option      | 期权，包括目前国内已上市的全部期权合约                            |
| Convertible | 沪深两市场内有交易的可转债合约                                    |
| Repo        | 沪深两市交易所交易的回购合约                                      |
| REITs       | 不动产投资信托基金                                                |
| FUND        | 除了ETF、LOF、REITs 之外的基金                                    |

#### 返回 {#rqdata-API-all_instruments-return}

_pandas DataFrame_ - 所有合约的基本信息。

详细字段注释请参考 [instruments](#rqdata-API-instruments) 返回字段说明

#### 范例 {#rqdata-API-all_instruments-example}

- 获取中国内地市场所有合约的基础信息：

```python
[In]all_instruments()
[Out]
    abbrev_symbol order_book_id  sector_code symbol
0 XJDQ 000400.XSHE   Industrials     许继电气
1 HXN     002582.XSHE   ConsumerStaples 好想你
2 NFGF 300004.XSHE   Industrials     南风股份
3 FLYY 002357.XSHE   Industrials     富临运业
...
```

- 获取中国内地市场所有 LOF 基金的基础信息：

```python
[In]all_instruments(type='LOF')
[Out]
    abbrev_symbol order_book_id product sector_code  symbol
0 CYGA 150303.XSHE null null 华安创业板50A
1 JY500A 150088.XSHE null null 金鹰500A
2 TD500A 150053.XSHE null null 泰达稳健
3 HS500A 150110.XSHE null null 华商500A
4 QSAJ 150235.XSHE null null 鹏华证券A
...
```

- 获取中国内地市场所有期货的基础信息：

```python
[In]all_instruments(type='Future')
[Out]
 abbrev_symbol order_book_id product sector_code symbol
0 MH0610 CF0610 Commodity null 棉花0610
1 LD0209 GN0209 Commodity null 绿豆0209
...
3615 HS1301 IF1301 Index null 沪深1301
...
```

- 获取中国内地市场指定日期可交易的期货的基础信息：

```python
[In]all_instruments(type='Future', date='20160412')
[Out]
 abbrev_symbol order_book_id product symbol
0 HJ0809 AU0809 Commodity 黄金0809
1 MH1301 CF1301 Commodity 棉花1301
...
4226 XC1103 WR1103 Commodity 线材1103
...
```

- 获取中国内地市场场内交易的可转债的基础信息：

```python
[In]all_instruments(type='Convertible')
[Out]
  de_listed_date  exchange  listed_date  market_tplus  order_book_id  round_lot  status  symbol  type
0  2013-01-29  XSHG  2007-03-08  0  126003.XSHG  10  Delisted  07云化债  Convertible
1  2016-09-22  XSHG  2008-10-10  0  126018.XSHG  10  Delisted  08江铜债  Convertible
2  2015-06-02  XSHE  2013-08-19  0  128002.XSHE  10  Delisted  东华转债  Convertible
3  2015-02-26  XSHG  2010-09-10  0  113002.XSHG  10  Delisted  工行转债  Convertible
4  0000-00-00  XSHE  2019-01-21  0  128052.XSHE  10  Active  凯龙转债  Convertible
...
```

### instruments - 获取合约详细信息 {#rqdata-API-instruments}

```python
instruments(order_book_ids, market='cn')
```

获取一个或多个合约最新的详细信息，支持查询单个合约或合约列表。

::: tip 注意事项

目前系统并不支持跨市场的同时调用，传入的 order_book_id list 必须属于同一国家市场，不能混合着中美两个国家市场的 order_book_id。

:::

#### 参数 {#rqdata-API-instruments-params-genericapi}

| 参数           | 类型                | 说明                                                                                                                                                                                                                                                                                                                                                                        |
| -------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ OR _str list_ | **必填参数**，合约代码，可传入 order_book_id, order_book_id list。<br/>中国市场的 order_book_id 通常类似'000001.XSHE'。需要注意，国内股票、ETF、指数合约代码分别应当以'.XSHG'或'.XSHE'结尾，前者代表上证，后者代表深证。<br/>比如查询平安银行这个股票合约，则键入'000001.XSHE'，前面的数字部分为交易所内这个股票的合约代码，后半部分为对应的交易所代码。<br/>期货则无此要求 |
| market         | _str_               | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                                                                                                                                                                                                         |

#### 返回 {#rqdata-API-instruments-return-genericapi}

一个 instrument 对象，或一个 instrument list。

##### 股票，ETF，指数 Instrument 对象

| 字段                                | 类型    | 说明                                                                                                                                                                                                          |
| ----------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_id                       | _str_   | 证券代码，证券的独特的标识符。应以'.XSHG'或'.XSHE'或'.XHKG'结尾。 '.XSHG' - 上证，'.XSHE' - 深证， '.XHKG' - 港股                                                                                             |
| symbol                              | _str_   | 证券的简称，例如'平安银行'                                                                                                                                                                                    |
| abbrev_symbol                       | _str_   | 证券的名称缩写，在中国 A 股就是股票的拼音缩写。例如：'PAYH'就是平安银行股票的证券名缩写                                                                                                                       |
| round_lot                           | _int_   | 一手对应多少股，中国 A 股一手是 100 股                                                                                                                                                                        |
| sector_code                         | _str_   | 板块缩写代码，全球通用标准定义                                                                                                                                                                                |
| sector_code_name                    | _str_   | 以当地语言为标准的板块代码名                                                                                                                                                                                  |
| industry_code                       | _str_   | 国民经济行业分类代码，具体可参考 [Industry](./stock-mod.md#rqdata-API-industry-category)                                                                                                                      |
| industry_name                       | _str_   | 国民经济行业分类名称，具体可参考 [Industry](./stock-mod.md#rqdata-API-industry-category)                                                                                                                      |
| listed_date                         | _str_   | 该证券上市日期                                                                                                                                                                                                |
| issue_price                         | _float_ | 该证券发行价 （元）                                                                                                                                                                                           |
| de_listed_date                      | _str_   | 退市日期                                                                                                                                                                                                      |
| type                                | _str_   | 合约类型，目前支持的类型有: 'CS', 'INDX', 'LOF', 'ETF', 'Future'                                                                                                                                              |
| ~~underlying_order_book_id 已废弃~~ | _str_   | 追踪基准的合约代码。目前仅限'ETF','LOF'                                                                                                                                                                       |
| ~~underlying_name~~ 已废弃          | _str_   | 追踪基准的合约名称。目前仅限'ETF','LOF'                                                                                                                                                                       |
| ~~concept_names~~ 已废弃            | _str_   | 概念股分类，例如：'铁路基建'，'基金重仓'等                                                                                                                                                                    |
| exchange                            | _str_   | 交易所，'XSHE' - 深交所, 'XSHG' - 上交所                                                                                                                                                                      |
| board_type                          | _str_   | 板块类别，'MainBoard' - 主板,'GEM' - 创业板,'SME' - 中小企业板,'KSH' - 科创板                                                                                                                                 |
| status                              | _str_   | 合约状态。'Active' - 正常上市, 'Delisted' - 终止上市, 'TemporarySuspended' - 暂停上市, ~~'PreIPO' - 发行配售期间~~, ~~'FailIPO' - 发行失败~~                                                                  |
| special_type                        | _str_   | 特别处理状态。'Normal' - 正常上市, 'ST' - ST 处理, 'StarST' - \_ST 代表该股票正在接受退市警告, 'PT' - 代表该股票连续 3 年收入为负，将被暂停交易, 'Other' - 其他                                               |
| trading_hours                       | _str_   | 合约最新的交易时间，如需历史数据请使用[get_trading_hours](#rqdata-API-get_trading_hours)                                                                                                                      |
| least_redeem                        | _str_   | 最低申赎份额，仅对 ETF 基金展示                                                                                                                                                                               |
| cross_market                        | _str_   | 沪深港通标识。True-支持，False-不支持。仅对港股生效                                                                                                                                                           |
| least_redeem                        | _str_   | 最低申赎份额，仅对 ETF 基金展示                                                                                                                                                                               |
| market_tplus                        | _str_   | 交易制度，0'表示 T+0，'1'表示 T+1，往后顺推                                                                                                                                                                   |
| purchasedate                        | _str_   | 申购日期                                                                                                                                                                                                      |
| base_date                           | _str_   | 基日，指数专用                                                                                                                                                                                                |
| base_point                          | _str_   | 基点，指数专用                                                                                                                                                                                                |
| fund_type                           | _str_   | 基金类型(ETF专用)<br />债券型 - `Bond`, 股票型 - `Stock`, 混合型 - `Hybrid`, 货币型 - `Money`, 短期理财型 - `ShortBond`, 股票指数 - `StockIndex`, 债券指数 - `BondIndex`, 联接基金 - `Related`, QDII - `QDII` |
| latest_size                         | _float_ | 最新基金规模（单位：元）(ETF专用)                                                                                                                                                                             |

##### 期货 Instrument 对象

| 字段                     | 类型    | 说明                                                                                                                                                                                                 |
| ------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_id            | _str_   | 期货代码，期货的独特的标识符（郑商所期货合约数字部分进行了补齐。例如原有代码'ZC609'补齐之后变为'ZC1609'）。主力连续合约 UnderlyingSymbol+88，例如'IF88' ；指数连续合约命名规则为 UnderlyingSymbol+99 |
| symbol                   | _str_   | 期货的简称，例如'沪深 1005'                                                                                                                                                                          |
| margin_rate              | _float_ | 期货合约的最低保证金率                                                                                                                                                                               |
| round_lot                | _float_ | 期货全部为 1.0                                                                                                                                                                                       |
| listed_date              | _str_   | 期货的上市日期。主力连续合约与指数连续合约都为'0000-00-00'                                                                                                                                           |
| de_listed_date           | _str_   | 期货的退市日期。                                                                                                                                                                                     |
| industry_name            | _str_   | 行业分类名称                                                                                                                                                                                         |
| trading_code             | _str_   | 交易代码                                                                                                                                                                                             |
| market_tplus             | _str_   | 交易制度。'0'表示 T+0，'1'表示 T+1，往后顺推                                                                                                                                                         |
| type                     | _str_   | 合约类型，'Future'                                                                                                                                                                                   |
| contract_multiplier      | _float_ | 合约乘数，例如沪深 300 股指期货的乘数为 300.0                                                                                                                                                        |
| underlying_order_book_id | _str_   | 合约标的代码，目前除股指期货(IH, IF, IC)之外的期货合约，这一字段全部为'null'                                                                                                                         |
| underlying_symbol        | _str_   | 合约标的名称，例如 IF1005 的合约标的名称为'IF'                                                                                                                                                       |
| maturity_date            | _str_   | 期货到期日。主力连续合约与指数连续合约都为'0000-00-00'                                                                                                                                               |
| exchange                 | _str_   | 交易所，'DCE' - 大连商品交易所, 'SHFE' - 上海期货交易所，'CFFEX' - 中国金融期货交易所, 'CZCE'- 郑州商品交易所, 'INE' - 上海国际能源交易中心                                                          |
| trading_hours            | _str_   | 合约最新的交易时间，如需历史数据请使用[get_trading_hours](#rqdata-API-get_trading_hours)                                                                                                             |
| product                  | _str_   | 合约种类，'Commodity'-商品期货，'Index'-股指期货，'Government'-国债期货                                                                                                                              |
| start_delivery_date      | _str_   | 开始交割日                                                                                                                                                                                           |
| end_delivery_date        | _str_   | 结束交割日                                                                                                                                                                                           |

##### 期权 Instrument 对象

| 字段                     | 类型    | 说明                                                                                                                                        |
| ------------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_id            | _str_   | 合约代码，50ETF 期权为数字代码，例如 10000615                                                                                               |
| symbol                   | _str_   | 合约简称                                                                                                                                    |
| round_lot                | _float_ | 最小下单手数，期权全部为 1.0                                                                                                                |
| listed_date              | _str_   | 合约上市日期                                                                                                                                |
| type                     | _str_   | 合约类型，'Option' 代表期权                                                                                                                 |
| contract_multiplier      | _float_ | 合约乘数，50ETF 期权只保存分红调整后的最新数据，变动历史请参考日线数据                                                                      |
| underlying_order_book_id | _str_   | 合约标的代码                                                                                                                                |
| underlying_symbol        | _str_   | 合约所属品种                                                                                                                                |
| maturity_date            | _str_   | 合约到期日                                                                                                                                  |
| exchange                 | _str_   | 交易所，'DCE' - 大连商品交易所, 'SHFE' - 上海期货交易所，'CFFEX' - 中国金融期货交易所, 'CZCE'- 郑州商品交易所, 'INE' - 上海国际能源交易中心 |
| strike_price             | _float_ | 期权行权价，50ETF 期权只保存分红调整后的最新数据，变动历史请参考日线数据                                                                    |
| option_type              | _str_   | 'C' 代表认购，'P'代表认沽                                                                                                                   |
| exercise_type            | _str_   | 'E' 代表欧式期权，'A' 代表美式期权                                                                                                          |
| market_tplus             | _str_   | 交易制度， '0'表示 T+0，'1'表示 T+1，往后顺推                                                                                               |
| product_name             | _str_   | ETF 期权字母简称                                                                                                                            |

##### 现货 Instrument 对象

| 字段           | 类型  | 说明                                                                                     |
| -------------- | ----- | ---------------------------------------------------------------------------------------- |
| order_book_id  | _str_ | 合约代码                                                                                 |
| symbol         | _str_ | 合约简称                                                                                 |
| exchange       | _str_ | 交易所，'SGEX' - 上海黄金期货交易所                                                      |
| listed_date    | _str_ | 合约上市日期                                                                             |
| de_listed_date | _str_ | 退市日期                                                                                 |
| type           | _str_ | 合约类型，'Spot' 代表现货                                                                |
| trading_hours  | _str_ | 合约最新的交易时间，如需历史数据请使用[get_trading_hours](#rqdata-API-get_trading_hours) |
| market_tplus   | _str_ | 交易制度， '0'表示 T+0，'1'表示 T+1，往后顺推                                            |

##### 可转债 Instrument 对象

| 字段           | 类型  | 说明                                          |
| -------------- | ----- | --------------------------------------------- |
| order_book_id  | _str_ | 合约代码                                      |
| symbol         | _str_ | 合约简称                                      |
| exchange       | _str_ | 交易所，'XSHE' - 深交所，'XSHG' - 上交所      |
| listed_date    | _str_ | 合约上市日期                                  |
| de_listed_date | _str_ | 退市日期                                      |
| type           | _str_ | 合约类型，'Convertible' 代表可转债            |
| market_tplus   | _str_ | 交易制度， '0'表示 T+0，'1'表示 T+1，往后顺推 |

##### Instrument 对象也支持如下方法：

- 合约已上市天数。

```
days_from_listed(date=None)
```

默认返回合约上市距离当前日期的天数。date 支持 str,
如果合约首次上市交易，天数为 0；如果合约尚未上市或已经退市，则天数值为-1

- 合约距离到期天数。

```
days_to_expire(date=None)
```

如果策略已经退市，则天数值为-1

- 获取合约最小价格变动单位。

```
tick_size()
```

例如，instruments('IF1608').tick_size()获取的就是股指期货的最小价格变动单位，为 0.2，即“一跳”的水平。

#### 范例 {#rqdata-API-instruments-example}

- 获取单一股票合约的详细信息：

```
In [5]: instruments('000001.XSHE')
Out[5]: Instrument(order_book_id='000001.XSHE', industry_code='J66', market_tplus=1, symbol='平安银行', special_type='Normal', exchange='XSHE', status='Active', type='CS', de_listed_date='0000-00-00', listed_date='1991-04-03', sector_code_name='金融', abbrev_symbol='PAYH', sector_code='Financials', round_lot=100, trading_hours='09:31-11:30,13:01-15:00', board_type='MainBoard', industry_name='货币金融服务', issue_price=40.0, citics_industry_code='40', citics_industry_name='银行')
```

- 获取多个股票合约的详细信息：

```python
[In]instruments(['000001.XSHE', '000024.XSHE'])
[Out]
[Instrument(order_book_id='000001.XSHE', industry_code='J66', market_tplus=1, symbol='平安银行', special_type='Normal', exchange='XSHE', status='Active', type='CS', de_listed_date='0000-00-00', listed_date='1991-04-03', sector_code_name='金融', abbrev_symbol='PAYH', sector_code='Financials', round_lot=100, trading_hours='09:31-11:30,13:01-15:00', board_type='MainBoard', industry_name='货币金融服务',industry_name='银行'),
 Instrument(order_book_id='000024.XSHE', industry_code='K70', market_tplus=1, symbol='招商地产', special_type='Normal', exchange='XSHE', status='Delisted', type='CS', de_listed_date='2015-12-30', listed_date='1993-06-07', sector_code_name='房地产', abbrev_symbol='ZSDC', sector_code='RealEstate', round_lot=100, trading_hours='09:31-11:30,13:01-15:00', board_type='MainBoard', industry_name='房地产业')]
```

- 获取期权合约基础信息

```python
[In]: instruments('10000615')
[Out]
Instrument(listed_date='2016-04-28', exchange='XSHG', underlying_symbol='510050.XSHG', symbol='510050C1612A02050', underlying_order_book_id='510050.XSHG', round_lot=1, de_listed_date='2016-12-28', maturity_date='2016-12-28', option_type='C', exercise_type='E', type='Option', contract_multiplier=10220, strike_price=2.006, order_book_id='10000615', market_tplus=0, trading_hours='09:31-11:30,13:01-15:00')
```

- 获取 000001.XSHE 20160801 该天距离合约上市日天数：

```python
[In]instruments('000001.XSHE').days_from_listed('20160801')
[Out]
9252
```

- 获取期权合约 10000068 20150320 该天距离合约上市日天数：

```python
[In]instruments('10000068').days_from_listed('20150320')
[Out]
3
```

- 获取 IF1608 20160801 该天距离合约到期日天数：

```python
[In]instruments('IF1608').days_to_expire('20160801')
[Out]
18
```

- 获取 ZN2105C20000 20160801 该天距离合约到期日天数：

```python
[In] instruments('ZN2105C20000').days_to_expire('20201225')
[Out]
122
```

### id_convert - 交易所代码转换 {#rqdata-API-id_convert}

```python
id_convert(order_book_ids,to=None)
```

获取交易所、其他平台代码与米筐标准合约代码之间的转换结果，目前仅支持 A 股、期货和期权代码转换。例如支持将 `000001.SZ`、`000001SZ`、`SZ000001` 转换为 `000001.XSHE`。

#### 参数 {#rqdata-API-id_convert-params}

| 参数           | 类型                | 说明                                                                                              |
| -------------- | ------------------- | ------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_ | **必填参数**，合约代码(来自米筐或交易所或其他平台)                                                |
| to             | _str_               | 'normal'：由米筐代码转化为交易所和其他平台的代码<br/>不填：由交易所和其他平台的代码转化为米筐代码 |

#### 返回 {#rqdata-API-id_convert-return}

- 传入一个 order_book_ids，函数会返回一个标准化合约代码字符串。
- 传入一个 order_book_ids 列表，函数会返回一个标准化合约代码字符串 list。

#### 范例 {#rqdata-API-id_convert-example}

- 获取其他平台标准合约代码:

```python
[In]id_convert('000001.XSHE', to='normal')
[Out]
'000001.SZ'
```

- 获取单一股票的米筐标准合约代码:

```python
[In]id_convert('000935.SH')
[Out]
'000935.XSHG'
```

- 获取多个股票的米筐标准合约代码:

```python
[In]id_convert(['000001.SZ', '000935.SH'])
[Out]
['000001.XSHE', '000935.XSHG']
```

- 获取单一期货的米筐标准合约代码:

```python
[In]id_convert('AP810')
[Out]
'AP1810'
```

- 获取单一期货的米筐标准合约代码\_CTP 代码:

```python
[In]id_convert('ZC001.CZCE')
[Out]
'ZC2001'
```

- 获取单一期权的米筐标准合约代码\_CTP 代码:

```python
[In]id_convert('m1901-C-2500')
[Out]
'M1901C2500'
```

- 获取单一期权的米筐标准合约代码\_CTP 代码:

```python
[In]id_convert('SR901C4400')
[Out]
'SR1901C4400'
```

### get_price - 获取合约行情数据 {#rqdata-API-get_price-genericapi}

```python
get_price(order_book_ids, start_date=None, end_date=None, frequency='1d', fields=None, adjust_type='pre', skip_suspended=False, expect_df=True, time_slice=None, market='cn')
```

获取指定合约或合约列表的行情数据，支持周线、日线、分钟线和 tick 数据。例如支持股票、期货、期权、可转债、ETF、常见指数等中国市场合约，也包括上金所现货中的黄金、铂金、白银产品。

::: tip 注意事项

1、 周线数据目前只支持'1w',依据日线数据进行合成，例如股票周线的前复权数据使用前复权日线数据进行合成，股票周线的不复权数据使用不复权的日线数据合成。<br/>
2、如需大量获取分钟或 tick 数据，建议以单只合约为单位，并设置长时段获取以提高效率。<br/>
3、time_slice参数是先获取 start_date、end_date 区间内所有数据再进行切分，请注意流量使用。

:::

#### 参数 {#rqdata-API-get_price-params}

| 参数           | 类型                                                           | 说明                                                                                                                                                                                                                                                                                                                                                                  |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ OR _str list_                                            | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                                                                                                                                                                                                                                                                                      |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                                                                                                                                                                                                                                                                                              |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                                                                                                                                                                                                                                                                                                              |
| frequency      | _str_                                                          | 支持数据的频率。 现在支持**周/日/分钟/tick 级别**，默认为'1d'。<br/> 1m - 分钟线<br/> 1d - 日线 <br/>1w - 周线，只支持'1w' <br/> 日线和分钟可选取不同频率，例如'5m'代表 5 分钟线。                                                                                                                                                                                    |
| fields         | _str_ OR _str list_                                            | 字段名称                                                                                                                                                                                                                                                                                                                                                              |
| adjust_type    | _str_                                                          | 权息修复方案，<b>仅对股票和 ETF 的日线和分钟线有效，tick为不复权</b>，默认为`pre`。<br/>不复权 - `none`，<br/>前复权 - `pre`，后复权 - `post`，<br/>前复权 - `pre_volume`, 后复权 - `post_volume` <br/>两组前后复权方式仅 volume 字段处理不同，其他字段相同。其中'pre'、'post'中的 volume 采用拆分因子调整；'pre_volume'、'post_volume'中的 volume 采用复权因子调整。 |
| skip_suspended | _bool_                                                         | 是否跳过停牌数据。默认为 False，不跳过，用停牌前数据进行补齐。True 则为跳过停牌期。                                                                                                                                                                                                                                                                                   |
| expect_df      | _bool_                                                         | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构,周线数据需设置 expect_df=True                                                                                                                                                                                                                                                                         |
| time_slice     | _str_, _datetime.time_                                         | 开始、结束时间段。默认返回当天所有数据。<br/>支持分钟 / tick 级别的切分，详见下方范例。                                                                                                                                                                                                                                                                               |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                                                                                                                                                                                                   |

#### 返回 {#rqdata-API-get_price-return}

_pandas DataFrame_

##### bar 数据

| 字段                | 类型               | 说明                                                                  |
| ------------------- | ------------------ | --------------------------------------------------------------------- |
| open                | _float_            | 开盘价                                                                |
| close               | _float_            | 收盘价                                                                |
| high                | _float_            | 最高价                                                                |
| low                 | _float_            | 最低价                                                                |
| limit_up            | _float_            | 涨停价                                                                |
| limit_down          | _float_            | 跌停价                                                                |
| total_turnover      | _float_            | 成交额                                                                |
| volume              | _float_            | 成交量                                                                |
| num_trades          | _int_              | 成交笔数 （仅支持股票、ETF、LOF、可转债；提供范围为 2021-06-25 至今） |
| prev_close          | _float_            | 昨日收盘价 （交易所披露的原始昨收价，<b>复权方法对该字段无效</b>）    |
| settlement          | _float_            | 结算价 （仅限期货期权日线数据）                                       |
| prev_settlement     | _float_            | 昨日结算价（仅限期货期权日线数据）                                    |
| open_interest       | _float_            | 累计持仓量（期货期权专用）                                            |
| trading_date        | _pandas.Timestamp_ | 交易日期（仅限期货分钟线数据），对应期货夜盘的情况                    |
| dominant_id         | _str_              | 实际合约的 order_book_id，对应期货 888 系主力连续合约的情况           |
| strike_price        | _float_            | 行权价，仅限期权日线数据                                              |
| contract_multiplier | _float_            | 合约乘数，仅限期权日线数据                                            |
| iopv                | _float_            | 场内基金实时估算净值                                                  |
| day_session_open    | _float_            | 日盘开盘价（仅限期货期权日线数据）                                    |

##### tick 数据

| 字段            | 类型               | 说明                                                                  |
| --------------- | ------------------ | --------------------------------------------------------------------- |
| datetime        | _pandas.Timestamp_ | 交易所时间戳                                                          |
| open            | _float_            | 当日开盘价                                                            |
| high            | _float_            | 当日最高价                                                            |
| low             | _float_            | 当日最低价                                                            |
| last            | _float_            | 最新价                                                                |
| prev_close      | _float_            | 昨日收盘价                                                            |
| total_turnover  | _float_            | 当天累计成交额                                                        |
| volume          | _float_            | 当天累计成交量                                                        |
| num_trades      | _int_              | 成交笔数 （仅支持股票、ETF、LOF、可转债；提供范围为 2021-06-25 至今） |
| limit_up        | _float_            | 涨停价                                                                |
| limit_down      | _float_            | 跌停价                                                                |
| open_interest   | _float_            | 累计持仓量                                                            |
| a1~a5           | _float_            | 卖一至五档报盘价格                                                    |
| a1_v~a5_v       | _float_            | 卖一至五档报盘量                                                      |
| b1~b5           | _float_            | 买一至五档报盘价                                                      |
| b1_v~b5_v       | _float_            | 买一至五档报盘量                                                      |
| change_rate     | _float_            | 涨跌幅                                                                |
| trading_date    | _pandas.Timestamp_ | 交易日期，对应期货夜盘的情况                                          |
| prev_settlement | _float_            | 昨日结算价（仅期货有效）                                              |
| iopv            | _float_            | 场内基金实时估算净值                                                  |

#### 范例 {#rqdata-API-get_price-example-genericapi}

- 获取单一期货 20220512 - 20220513 每个交易日夜盘 23:55 至日盘 09:05 的历史分钟行情（返回*pandas DataFrame*）:

```python
[In] get_price('AG2209', start_date='20220512', end_date='20220513',frequency='1m',time_slice=('23:55', '09:05'))
[Out]
                               volume close trading_date open_interest low total_turnover open high
order_book_id datetime
AG2209      2022-05-11 23:55:00 25.0 4795.0 2022-05-12 37996.0 4794.0 1797975.0 4796.0 4796.0
            2022-05-11 23:56:00 2.0 4795.0 2022-05-12 37996.0 4795.0 143850.0 4795.0 4795.0
            ...
            2022-05-13 09:04:00 81.0 4662.0 2022-05-13 40338.0 4662.0 5665485.0 4664.0 4665.0
            2022-05-13 09:05:00 20.0 4661.0 2022-05-13 40333.0 4660.0 1398405.0 4662.0 4662.0

```

- 获取单一股票 20220512 - 20220513 每个交易日 10:00 - 11:00 的历史分钟行情（返回*pandas DataFrame*）:

```python
[In] get_price('000001.XSHE', start_date='20220512', end_date='20220513',frequency='1m', time_slice=(datetime.time(hour=10, minute=0), datetime.time(hour=11, minute=0)))
[Out]
                                    volume close num_trades low total_turnover open high
order_book_id   datetime
000001.XSHE     2022-05-12 10:00:00 1108700.0 14.39 545.0 14.36 15928007.0 14.36 14.39
                2022-05-12 10:01:00 351300.0 14.40 427.0 14.37 5052195.0 14.39 14.40
                2022-05-12 10:02:00 138400.0 14.39 301.0 14.38 1990834.0 14.38 14.39
                ...
                2022-05-13 10:58:00 481100.0 14.52 309.0 14.52 6990489.0 14.55 14.55
                2022-05-13 10:59:00 230700.0 14.52 190.0 14.51 3348303.0 14.51 14.52
                2022-05-13 11:00:00 227700.0 14.53 210.0 14.51 3306559.0 14.51 14.53

```

- 获取单一股票不复权的历史周线行情（返回*pandas DataFrame*）:

```python
[In] get_price('000001.XSHE',start_date='2015-04-01', end_date='2015-04-12',frequency='1w',adjust_type='none')
[Out]
                       total_turnover low open close volume num_trades high
order_book_id date
000001.XSHE 2015-04-10 2.281686e+10 16.15 16.15 19.8 1.284539e+09 554132.0 19.8

```

- 获取单一股票历史分钟线收盘价（返回*pandas DataFrame*）：

```python
[In]get_price('000001.XSHE', start_date='2015-04-01', end_date='2015-04-12', fields='close',frequency='1m')
[Out]
                                    close
order_book_id  datetime
000001.XSHE  2015-04-01 09:31:00  10.3985
              2015-04-01 09:32:00  10.3721
              2015-04-01 09:33:00  10.3655
```

- 获取单一股票历史 tick 行情（返回*pandas DataFrame*）

```python
[In]get_price('000001.XSHE', start_date='20240105', end_date='20240105', frequency='tick')
[Out]
	trading_date	open	last	high	low	prev_close	volume	total_turnover	limit_up	limit_down	...	a3_v	a4_v	a5_v	b1_v	b2_v	b3_v	b4_v	b5_v	change_rate	num_trades
order_book_id	datetime
000001.XSHE	2024-01-05 09:15:00	2024-01-05	0.0	9.11	0.00	0.00	9.11	0.0	0.000000e+00	10.02	8.2	...	0.0	0.0	0.0	700.0	0.0	0.0	0.0	0.0	0.000000	0.0
            2024-01-05 09:15:09	2024-01-05	0.0	9.11	0.00	0.00	9.11	0.0	0.000000e+00	10.02	8.2	...	0.0	0.0	0.0	21400.0	0.0	0.0	0.0	0.0	0.000000	0.0
            2024-01-05 09:15:18	2024-01-05	0.0	9.11	0.00	0.00	9.11	0.0	0.000000e+00	10.02	8.2	...	0.0	0.0	0.0	12900.0	0.0	0.0	0.0	0.0	0.000000	0.0
...
            2024-01-05 14:59:51	2024-01-05	9.1	9.27	9.44	9.07	9.11	197660716.0	1.838741e+09	10.02	8.2	...	0.0	0.0	0.0	1465500.0	0.0	0.0	0.0	0.0	0.017563	80597.0
            2024-01-05 15:00:00	2024-01-05	9.1	9.27	9.44	9.07	9.11	199162216.0	1.852660e+09	10.02	8.2	...	908900.0	517400.0	426800.0	899000.0	730100.0	427000.0	849600.0	567200.0	0.017563	81020.0


```

- 获取股票列表历史 tick 行情（返回*pandas DataFrame*）

```python
[In]get_price(['000001.XSHE', '000002.XSHE'], start_date='2019-04-01', end_date='2019-04-01',frequency='tick')
[Out]
                                  trading_date   open   last   high    low  prev_close       volume  ...      a5_v       b1_v      b2_v      b3_v      b4_v      b5_v  change_rate
order_book_id datetime                                                                               ...
000002.XSHE   2019-04-01 09:15:00   2019-04-01   0.00  30.72   0.00   0.00       30.72          0.0  ...       0.0     1100.0       0.0       0.0       0.0       0.0     0.000000
              2019-04-01 09:15:09   2019-04-01   0.00  30.72   0.00   0.00       30.72          0.0  ...       0.0   158400.0       0.0       0.0       0.0       0.0     0.000000
              2019-04-01 09:15:18   2019-04-01   0.00  30.72   0.00   0.00       30.72          0.0  ...       0.0   164300.0       0.0       0.0       0.0       0.0     0.000000
···
000001.XSHE   2019-04-01 14:56:33   2019-04-01  12.83  13.19  13.55  12.83       12.82  192947985.0  ...  574800.0   201700.0  605367.0  107200.0  180800.0  254236.0     0.028861
              2019-04-01 14:56:36   2019-04-01  12.83  13.19  13.55  12.83       12.82  192963385.0  ...  574800.0   219000.0  605367.0  106400.0  180800.0  254336.0     0.028861
              2019-04-01 14:56:39   2019-04-01  12.83  13.19  13.55  12.83       12.82  192979885.0  ...  574800.0   236200.0  605367.0  106400.0  180800.0  254236.0     0.028861
···

```

- 获取单一期货合约历史 tick 行情（返回*pandas DataFrame*）:

```python
[In]get_price('IF1608', '20160801', '20160801', 'tick')
[Out]
                               trading_date	open	last	high	low	prev_settlement	prev_close	volume	open_interest	total_turnover	...	a2_v	a3_v	a4_v	a5_v	b1_v	b2_v	b3_v	b4_v	b5_v	change_rate
order_book_id	datetime
IF1608	2016-08-01 09:29:00.100	2016-08-01	3174.0	3174.0	3174.0	3174.0	3184.6	3181.8	61.0	31847.0	5.808420e+07	...	0.0	0.0	0.0	0.0	1.0	0.0	0.0	0.0	0.0	-0.003329
        2016-08-01 09:30:00.100	2016-08-01	3174.0	3174.0	3174.0	3174.0	3184.6	3181.8	69.0	31843.0	6.570954e+07	...	0.0	0.0	0.0	0.0	1.0	0.0	0.0	0.0	0.0	-0.003329
        2016-08-01 09:30:00.600	2016-08-01	3174.0	3176.8	3176.8	3174.0	3184.6	3181.8	73.0	31840.0	6.952392e+07	...	0.0	0.0	0.0	0.0	1.0	0.0	0.0	0.0	0.0	-0.002449
        ...
        2016-08-01 14:59:58.100	2016-08-01	3174.0	3152.0	3183.8	3136.0	3184.6	3181.8	12000.0	32057.0	1.135865e+10	...	0.0	0.0	0.0	0.0	2.0	0.0	0.0	0.0	0.0	-0.010237
        2016-08-01 15:00:00.100	2016-08-01	3174.0	3151.6	3183.8	3136.0	3184.6	3181.8	12001.0	32058.0	1.135960e+10	...	0.0	0.0	0.0	0.0	1.0	0.0	0.0	0.0	0.0	-0.010362

```

- 获取单一股票历史**15 分钟线**行情（返回*pandas DataFrame*）:

```python
[In]get_price('000001.XSHE', start_date='2015-04-01', end_date='2015-04-01', frequency='15m')
[Out]
                                close	volume	open	total_turnover	high	num_trades	low
order_book_id	datetime
000001.XSHE	2015-04-01 09:45:00	8.2796	31861013.76	8.3588	349117578.0	8.4011	9066.0	8.2743
            2015-04-01 10:00:00	8.2426	21605140.80	8.2743	234301545.0	8.2848	7211.0	8.2162
            2015-04-01 10:15:00	8.3060	11539700.64	8.2479	125879392.0	8.3641	4892.0	8.2426
            2015-04-01 10:30:00	8.3007	13186285.92	8.3165	144351328.0	8.3747	3858.0	8.2743
            2015-04-01 10:45:00	8.3641	15435185.76	8.3060	169517893.0	8.3958	3839.0	8.300
...
```

- 获取沪深 300 指数**60 分钟线**行情（返回*pandas DataFrame*）:

```python
[In] get_price("000300.XSHG",start_date=20240105,end_date=20240108,frequency='60m')
[Out]
                               close	volume	open	total_turnover	high	low
order_book_id	datetime
000300.XSHG	2024-01-05 10:30:00	3366.3220	5.057541e+09	3341.3061	7.283712e+10	3372.5444	3330.4795
            2024-01-05 11:30:00	3352.6796	2.560877e+09	3367.0722	3.397981e+10	3370.5144	3352.3108
            2024-01-05 14:00:00	3334.6497	2.095849e+09	3352.6251	3.094104e+10	3354.8987	3333.4234
            2024-01-05 15:00:00	3329.1114	2.925791e+09	3334.4250	4.449369e+10	3342.9536	3313.5542
            2024-01-08 10:30:00	3296.0220	4.753887e+09	3322.6051	7.248326e+10	3333.5160	3295.7113
            2024-01-08 11:30:00	3299.3536	2.234612e+09	3295.4830	3.113254e+10	3304.0278	3285.8166
            2024-01-08 14:00:00	3289.8385	1.790737e+09	3299.0741	2.552842e+10	3300.8893	3286.2625
            2024-01-08 15:00:00	3286.0564	2.963712e+09	3289.6838	4.161742e+10	3303.9224	3283.3421
```

- 50ETF 期权日线数据（可以看到行权价、合约乘数在 50ETF 分红前后发生了变化）

```python
[In] get_price('10000615', start_date='20161125', end_date='20161130', frequency='1d')
[Out]
	                  limit_down	limit_up	strike_price	contract_multiplier	close	day_session_open	prev_close	volume	open	total_turnover	settlement	high	open_interest	prev_settlement	low
order_book_id	date
10000615	2016-11-25	0.15031	0.59969	2.050	10000.0	0.3904	0.3653	0.3627	4037.0	0.3653	14745563.0	0.4010	0.3904	2711.0	0.3750	0.3500
          2016-11-28	0.17390	0.62810	2.050	10000.0	0.4062	0.4055	0.3904	3518.0	0.4055	14495982.0	0.4100	0.4261	2377.0	0.4010	0.3995
          2016-11-29	0.17327	0.62913	2.006	10220.0	0.4333	0.3997	0.4062	3501.0	0.3997	15053302.0	0.4400	0.4510	2016.0	0.4012	0.3843
          2016-11-30	0.20838	0.67162	2.006	10220.0	0.4171	0.4322	0.4333	3121.0	0.4322	13510805.0	0.4171	0.4409	1934.0	0.4400	0.4118

```

- 获取可转债合约日线（返回*pandas DataFrame*）:

```python
[In] get_price("128143.XSHE",start_date=20240105,end_date=20240105,frequency='1d')
[Out]
                        limit_down	limit_up	close	prev_close	volume	open	total_turnover	high	num_trades	low
order_book_id	date
128143.XSHE	2024-01-05	110.0	165.0	137.699	137.5	329249.0	137.55	45220061.82	138.442	7159.0	136.4

```

- 获取回购合约日线（返回*pandas DataFrame*）:

```python
[In] get_price("131801.XSHE",start_date=20190522,end_date=20190522,frequency='1d')
[Out]
                        close	prev_close	volume	open	total_turnover	high	num_trades	low
order_book_id	date
131801.XSHE	2019-05-22	2.21	2.632	3906033.0	2.65	3.906033e+09	2.78	13544.0	1.0

```

### get_auction_info - 获取股票合约盘后数据 {#rqdata-API-get_auction_info}

```python
get_auction_info(order_book_ids, start_date=None, end_date=None, frequency='1d', fields=None, market='cn')
```

获取股票合约盘后固定价格交易数据。例如支持科创板、创业板等股票合约，也支持日线、分钟线和 tick 级别数据。

#### 参数 {#rqdata-API-get_auction_info-params}

| 参数           | 类型                                                           | 说明                                                                                                  |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list，获取 tick 数据时，只支持单个合约    |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                              |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                                              |
| frequency      | _str_                                                          | 数据的频率。 现在支持**日/分钟/tick 级别**的数据，默认为'1d'。只支持'1d','1m','tick',不支持'5d'等频率 |
| fields         | _str_ OR _str list_                                            | 字段名称                                                                                              |
| market         | _str_                                                          | 默认是中国市场('cn')                                                                                  |

#### 返回 {#rqdata-API-get_auction_info-return}

_pandas DataFrame_

| 字段           | 类型    | 说明                    |
| -------------- | ------- | ----------------------- |
| close          | _float_ | 收盘价                  |
| volume         | _float_ | 成交量                  |
| total_turnover | _float_ | 成交额                  |
| bid_vol        | _nt_    | 申买入量(tick 数据专用) |
| ask_vol        | int     | 申卖出量(tick 数据专用) |

#### 范例 {#rqdata-API-get_auction_info-example}

- 获取合约列表盘后日线数据

```python
[In]
get_auction_info(['688012.XSHG','688011.XSHG'],'20190722','20190722','1d')
[Out]
                           close volume total_turnover
order_book_id date
688012.XSHG 2019-07-22 81.03 112858.0 9144883.74
688011.XSHG 2019-07-22 70.17 19350.0 1357789.50
```

- 获取单一合约盘后分钟数据

```python
[In]
get_auction_info('688012.XSHG','20190722','20190722','1m')
[Out]
                       close volume total_turnover
order_book_id datetime
688012.XSHG 2019-07-22 15:06:00 81.03 1400.0 113442.00
            2019-07-22 15:07:00 81.03 600.0 48618.00
...
            2019-07-22 15:29:00 81.03 3241.0 262618.23
            2019-07-22 15:30:00 81.03 1400.0 113442.00
```

- 获取单一合约盘后 tick 数据

```python
[In]
get_auction_info('688012.XSHG','20190722','20190722','tick')
[Out]
                       close volume total_turnover bid_vol ask_vol
datetime
2019-07-22 15:05:00.168 81.03 1000.0 81030.00 18292.0 0.0
2019-07-22 15:05:03.168 81.03 1000.0 81030.00 18292.0 0.0
...
2019-07-22 15:30:50.280 81.03 112858.0 9144883.74 0.0 69339.0
2019-07-22 15:30:56.720 81.03 112858.0 9144883.74 0.0 69339.0
```

### get_ticks - 获取日内 tick 数据（试用版） {#rqdata-API-get_ticks}

```python
get_ticks(order_book_id, start_date=None, end_date=None, expect_df=True, market='cn')
```

获取当日给定合约的 level1 tick 快照行情，不支持历史数据查询。

#### 参数 {#rqdata-API-get_ticks-params}

| 参数           | 类型                                                           | 说明                                                            |
| -------------- | -------------------------------------------------------------- | --------------------------------------------------------------- |
| order_book_ids | _str_                                                          | **必填参数**，合约代码                                          |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，目前只支持查询当日                                    |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，目前只支持查询当日                                    |
| expect_df      | _bool_                                                         | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构 |
| market         | _str_                                                          | 默认是中国市场('cn')                                            |

#### 返回 {#rqdata-API-get-ticks-return}

_pandas DataFrame_

##### tick 数据

| 字段            | 类型               | 说明                                      |
| --------------- | ------------------ | ----------------------------------------- |
| datetime        | _pandas.Timestamp_ | 交易所时间戳                              |
| open            | _float_            | 当日开盘价                                |
| high            | _float_            | 当日最高价                                |
| low             | _float_            | 当日最低价                                |
| last            | _float_            | 最新价                                    |
| prev_close      | _float_            | 昨日收盘价                                |
| total_turnover  | _float_            | 当天累计成交额                            |
| volume          | _float_            | 当天累计成交量                            |
| num_trades      | _int_              | 成交笔数 （仅支持股票、ETF、LOF、可转债） |
| limit_up        | _float_            | 涨停价                                    |
| limit_down      | _float_            | 跌停价                                    |
| open_interest   | _float_            | 累计持仓量                                |
| a1~a5           | _float_            | 卖一至五档报盘价格                        |
| a1_v~a5_v       | _float_            | 卖一至五档报盘量                          |
| b1~b5           | _float_            | 买一至五档报盘价                          |
| b1_v~b5_v       | _float_            | 买一至五档报盘量                          |
| trading_date    | _pandas.Timestamp_ | 交易日期，对应期货夜盘的情况              |
| prev_settlement | _float_            | 昨日结算价（仅期货有效）                  |
| iopv            | _float_            | 场内基金实时估算净值                      |
| prev_iopv       | _float_            | 场内基金前估算净值                        |

#### 范例 {#rqdata-API-get_ticks-example}

- 获取 000001.XSHE 当日 tick 数据

```python
[In]
df=get_ticks('000001.XSHE')
df.head(1)
[Out]
                          open last high low iopv prev_iopv limit_up limit_down prev_close volume ... a1_v a2_v a3_v a4_v a5_v b1_v b2_v b3_v b4_v b5_v
order_book_id datetime
000001.XSHE 2021-07-23 09:15:00 0.0 20.38 0.0 0.0 NaN NaN 22.42 18.34 20.38 0.0 ... 8700.0 11300.0 0.0 0.0 0.0 8700.0 0.0 0.0 0.0 0.0
```

- 获取 ETF 期权 10002725 当日 tick 数据

```python
[In]
get_ticks('10002725',expect_df=False)

[Out]
 update_time open last high low limit_up limit_down prev_settlement prev_close volume ... a1_v a2_v a3_v a4_v a5_v b1_v b2_v b3_v b4_v b5_v
datetime
2021-03-09 09:15:00.020 0 0.0000 0.6547 0.0000 0.0000 1.0124 0.3002 0.6563 0.6547 0.0 ... 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
2021-03-09 09:15:00.530 0 0.0000 0.6547 0.0000 0.0000 1.0124 0.3002 0.6563 0.6547 0.0 ... 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0
2021-03-09 09:15:01.030 0 0.0000 0.6547 0.0000 0.0000 1.0124 0.3002 0.6563 0.6547 0.0 ... 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0

```

### get_live_ticks - 获取日内 tick 数据（支持日内时间切割） {#rqdata-API-get_live_ticks}

```python
get_live_ticks(order_book_ids, start_dt=None, end_dt=None, fields=None, market='cn')
```

获取当前交易日的 level1 tick 快照行情，不支持历史数据。例如支持股票、期货、期权、ETF、常见指数等合约，也包括上金所现货。

::: tip 注意事项

start_dt 和 end_dt 需同时传入或同时不传入，当不传入 start_dt,end_dt 参数时，查询时间在交易日 T 日 7.30 pm 之前，返回 T 日的 tick 数据，查询时点在 7.30pm 之后，返回交易日 T+1 日的 tick 数据

:::

#### 参数 {#rqdata-API-get_live_ticks-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_dt       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始时间，采用自然日时间戳，细化到秒                             |
| end_dt         | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束时间，采用自然日时间戳，细化到秒                             |
| fields         | _str_ or _str list_                                            | 字段名称                                                         |
| market         | _str_                                                          | 默认是中国市场('cn')                                             |

#### 返回 {#rqdata-API-get_live_ticks-return}

_pandas DataFrame_

##### tick 数据

| 字段            | 类型               | 说明                                    |
| --------------- | ------------------ | --------------------------------------- |
| datetime        | _pandas.Timestamp_ | 交易所时间戳                            |
| open            | _float_            | 当日开盘价                              |
| high            | _float_            | 当日最高价                              |
| low             | _float_            | 当日最低价                              |
| last            | _float_            | 最新价                                  |
| prev_close      | _float_            | 昨日收盘价                              |
| total_turnover  | _float_            | 当天累计成交额                          |
| volume          | _float_            | 当天累计成交量                          |
| num_trades      | _int_              | 成交笔数 （仅支持股票、ETF、LOF、可转债 |
| limit_up        | _float_            | 涨停价                                  |
| limit_down      | _float_            | 跌停价                                  |
| open_interest   | _float_            | 累计持仓量                              |
| a1~a5           | _float_            | 卖一至五档报盘价格                      |
| a1_v~a5_v       | _float_            | 卖一至五档报盘量                        |
| b1~b5           | _float_            | 买一至五档报盘价                        |
| b1_v~b5_v       | _float_            | 买一至五档报盘量                        |
| trading_date    | _pandas.Timestamp_ | 交易日期，对应期货夜盘的情况            |
| prev_settlement | _float_            | 昨日结算价（仅期货有效）                |
| iopv            | _float_            | 场内基金实时估算净值                    |
| prev_iopv       | _float_            | 场内基金前估算净值                      |

#### 范例 {#rqdata-API-get_live_ticks-example}

- 获取期权合约 2020 年 3 月 9 日 9 时 40 分 00 秒-2020 年 3 月 9 日 9 时 40 分 02 秒之间的 tick 数据

```python
[In]get_live_ticks(order_book_ids=['10002726'],start_dt='20210309094000',end_dt='20210309094002')

[Out]

                                  trading_date update_time open last high low limit_up limit_down prev_settlement prev_close ... a1_v a2_v a3_v a4_v a5_v b1_v b2_v b3_v b4_v b5_v
order_book_id datetime
10002726 2021-03-09 09:40:00.020 NaT NaT 0.6173 0.6039 0.6173 0.6033 0.9624 0.2502 0.6063 0.6072 ... 10 2 30 10 10 30 10 10 10 10
            2021-03-09 09:40:00.540 NaT NaT 0.6173 0.6039 0.6173 0.6033 0.9624 0.2502 0.6063 0.6072 ... 10 1 22 10 10 20 10 10 10 10
            2021-03-09 09:40:01.030 NaT NaT 0.6173 0.6039 0.6173 0.6033 0.9624 0.2502 0.6063 0.6072 ... 8 20 2 10 10 20 10 10 10 10
            2021-03-09 09:40:01.540 NaT NaT 0.6173 0.6039 0.6173 0.6033 0.9624 0.2502 0.6063 0.6072 ... 10 1 20 2 10 30 10 10 10 10
```

- 获取股票合约当日 2020 年 9 月 18 日 9 时 15 分 00 秒-2020 年 9 月 18 日 9 时 15 分 30 秒之间的 tick 数据

```python
[In]
get_live_ticks(order_book_ids=['000001.XSHE','000006.XSHE'],start_dt='20200918091500',end_dt='20200918091530')
[Out]
                        open last high low iopv prev_iopv limit_up limit_down prev_close volume ... a1_v a2_v a3_v a4_v a5_v b1_v b2_v b3_v b4_v b5_v
order_book_id datetime
000001.XSHE 2020-09-18 09:15:00 0 15.57 0 0 NaN NaN 17.13 14.01 15.57 0 ... 900 0 0 0 0 900 2500 0 0 0
            2020-09-18 09:15:09 0 15.57 0 0 NaN NaN 17.13 14.01 15.57 0 ... 53500 2700 0 0 0 53500 0 0 0 0
            2020-09-18 09:15:18 0 15.57 0 0 NaN NaN 17.13 14.01 15.57 0 ... 53600 2700 0 0 0 53600 0 0 0 0
            2020-09-18 09:15:27 0 15.57 0 0 NaN NaN 17.13 14.01 15.57 0 ... 53500 2800 0 0 0 53500 0 0 0 0
000006.XSHE 2020-09-18 09:15:00 0 5.88 0 0 NaN NaN 6.47 5.29 5.88 0 ... 0 0 0 0 0 0 0 0 0 0
            2020-09-18 09:15:09 0 5.88 0 0 NaN NaN 6.47 5.29 5.88 0 ... 2800 0 0 0 0 2800 9400 0 0 0
            2020-09-18 09:15:18 0 5.88 0 0 NaN NaN 6.47 5.29 5.88 0 ... 2900 0 0 0 0 2900 9300 0 0 0
```

- 获取 000001.XSHG 和 RB2101 合约当日 2020 年 9 月 18 日 9 时 31 分 00 秒-2020 年 9 月 18 日 9 时 31 分 06 秒之间的 open,last ,high 等 tick 字段

```python
[In]
get_live_ticks(order_book_ids=['000001.XSHG','RB2101'],start_dt='20200918093100',end_dt='20200918093106',fields=['open','last','high'])
[Out]

                    open          last           high
order_book_id datetime
000001.XSHG 2020-09-18 09:31:00.790 3270.911 3272.8091 3275.0855
            2020-09-18 09:31:05.060 3270.911 3272.8249 3275.0855
RB2101     2020-09-18 09:31:00.093 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:00.607 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:01.095 3580.000 3604.0000 3611.0000
            2020-09-18 09:31:01.582 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:02.098 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:02.598 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:03.098 3580.000 3604.0000 3611.0000
            2020-09-18 09:31:03.596 3580.000 3604.0000 3611.0000
            2020-09-18 09:31:04.105 3580.000 3604.0000 3611.0000
            2020-09-18 09:31:04.584 3580.000 3604.0000 3611.0000
            2020-09-18 09:31:05.094 3580.000 3605.0000 3611.0000
            2020-09-18 09:31:05.581 3580.000 3604.0000 3611.0000
```

### get_open_auction_info - 获取盘前集合竞价数据 {#rqdata-API-get_open_auction_info}

```python
get_open_auction_info(order_book_ids, start_date=None, end_date=None, fields =None, market='cn')
```

获取盘前集合竞价结束后交易所撮合产生的 level1 快照数据。

#### 参数 {#rqdata-API-get_open_auction_info-params}

| 参数           | 类型                                                           | 说明                                                             |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期。如不指定日期，则默认为取当天                           |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。如不指定日期，则默认为返回所填开始日期当天             |
| fields         | _str_ or _str list_                                            | 字段名称，默认返回全部字段                                       |
| market         | _str_                                                          | 默认是中国市场('cn')                                             |

#### 返回 {#rqdata-API-get_open_auction_info-return}

_pandas DataFrame_

##### tick 数据

| 字段            | 类型               | 说明                         |
| --------------- | ------------------ | ---------------------------- |
| datetime        | _pandas.Timestamp_ | 时间戳                       |
| open            | _float_            | 当日开盘价                   |
| high            | _float_            | 当日最高价                   |
| low             | _float_            | 当日最低价                   |
| last            | _float_            | 最新价                       |
| prev_settlement | _float_            | 昨日结算价                   |
| volume          | _float_            | 成交量                       |
| limit_up        | _float_            | 涨停价                       |
| limit_down      | _float_            | 跌停价                       |
| open_interest   | _float_            | 累计持仓量                   |
| a1~a5           | _float_            | 卖一至五档报盘价格           |
| a1_v~a5_v       | _float_            | 卖一至五档报盘量             |
| b1~b5           | _float_            | 买一至五档报盘价             |
| b1_v~b5_v       | _float_            | 买一至五档报盘量             |
| change_rate     | _float_            | 涨跌幅                       |
| trading_date    | _pandas.Timestamp_ | 交易日期，对应期货夜盘的情况 |
| iopv            | _float_            | 场内基金实时估算净值         |
| prev_iopv       | _float_            | 场内基金前估算净值           |

#### 范例 {#rqdata-API-get_open_auction_info-example}

- 获取单一合约集合竞价数据

```
In []:
get_open_auction_info('000001.XSHE','20190102','20190105')
Out[]:
                                    open   last   high    low  limit_up  ...      b1_v     b2_v      b3_v     b4_v     b5_v
order_book_id datetime                                                   ...
000001.XSHE   2019-01-02 09:25:03   9.39   9.39   9.39   9.39     10.32  ...  183300.0  79600.0   65100.0  67700.0  43700.0
              2019-01-03 09:25:03   9.18   9.18   9.18   9.18     10.11  ...   37230.0  76700.0  157700.0  73400.0  22000.0
              2019-01-04 09:25:03   9.24   9.24   9.24   9.24     10.21  ...   56500.0  34200.0   41600.0  80200.0  42500.0
```

- 获取合约列表集合竞价数据

```python
[In]
get_open_auction_info(['000001.XSHE','000002.XSHE'],'20190102','20190105')
[Out]
                                    open   last   high    low  limit_up  limit_down  ...      a5_v      b1_v     b2_v      b3_v     b4_v     b5_v
order_book_id datetime                                                               ...
000001.XSHE   2019-01-02 09:25:03   9.39   9.39   9.39   9.39     10.32        8.44  ...   17800.0  183300.0  79600.0   65100.0  67700.0  43700.0
              2019-01-03 09:25:03   9.18   9.18   9.18   9.18     10.11        8.27  ...   16200.0   37230.0  76700.0  157700.0  73400.0  22000.0
              2019-01-04 09:25:03   9.24   9.24   9.24   9.24     10.21        8.35  ...  210900.0   56500.0  34200.0   41600.0  80200.0  42500.0
000002.XSHE   2019-01-02 09:25:03  23.83  23.83  23.83  23.83     26.20       21.44  ...    8593.0   35381.0  58700.0    1100.0   4800.0    100.0
              2019-01-03 09:25:03  23.79  23.79  23.79  23.79     26.29       21.51  ...    4708.0    5400.0   2400.0   13100.0  17600.0    700.0
              2019-01-04 09:25:03  23.91  23.91  23.91  23.91     26.48       21.66  ...     400.0    1800.0    200.0    5000.0   3000.0    100.0
```

### current_minute - 获取最近的分钟线数据 {#rqdata-API-current_minute}

```python
current_minute(order_book_ids, skip_suspended=False, fields=None, market='cn')
```

获取给定合约当日最新的 1 分钟 K 线数据，不支持历史数据，当前仅支持股票。

#### 参数 {#rqdata-API-current_minute-params}

| 参数           | 类型                | 说明                                                             |
| -------------- | ------------------- | ---------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_ | **必填参数**，合约代码，可输入 order_book_id, order_book_id list |
| skip_suspended | _boolean_           | 是否跳过停牌，默认不跳过                                         |
| fields         | _list_              | 可挑选返回的字段。默认返回所有                                   |
| market         | _str_               | 默认是中国内地市场('cn')                                         |

#### 返回 {#rqdata-API-current_minute-return}

_pandas DataFrame_

##### 分钟数据

| 字段     | 类型      | 说明                 |
| -------- | --------- | -------------------- |
| open     | _float_   | 此分钟开盘价         |
| high     | _float_   | 此分钟最高价         |
| low      | _float_   | 此分钟最低价         |
| close    | _float_   | 此分钟收盘价         |
| volume   | _integer_ | 此分钟成交量         |
| turnover | _float_   | 此分钟成交额         |
| iopv     | _float_   | 场内基金实时估算净值 |

#### 范例 {#rqdata-API-current_minute-example}

- 获取平安银行和浦发银行最近的分钟数据

```python
[In]
current_minute(["000001.XSHE","600000.XSHG"])
[Out]
                                open	high	low	close	volume	total_turnover	num_trades
order_book_id	datetime
000001.XSHE	2025-11-13 09:59:00	11.66	11.66	11.65	11.66	202300.0	2357739.0	178
600000.XSHG	2025-11-13 09:59:00	11.68	11.68	11.67	11.68	385900.0	4508481.0	156

```

- 获取 A2511 和 10009217 最近的分钟数据

```python
[In]
current_minute(order_book_ids=['A2511','10009217'])
[Out]
                                trading_date	open	high	low	close	volume	total_turnover	open_interest
order_book_id	datetime
A2511	        2025-11-13 10:00:00	20251113	4099.0000	4099.0000	4099.0000	4099.0000	0	0.0	1435.0
10009217	    2025-11-13 10:00:00	20251113	0.7001	0.7007	0.7001	0.7007	3	21021.0	1340.0

```

### get_price_change_rate - 获取历史涨跌幅 {#rqdata-API-get_price_change_rate}

```python
get_price_change_rate(order_book_ids, start_date=None, end_date=None, expect_df=True, market='cn')
```

获取历史涨跌幅数据，目前仅支持股票、期货、指数和可转债，历史涨跌幅基于后复权价格。

#### 参数 {#rqdata-API-get_price_change_rate-params}

| 参数           | 类型                                                           | 说明                                                              |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list  |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                          |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据 |
| expect_df      | _bool_                                                         | 默认返回 pandas dataframe。如果调为 False，则返回原有的数据结构   |
| market         | _str_                                                          | 默认是中国内地市场('cn')                                          |

#### 返回 {#rqdata-API-get_price_change_rate-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-get_price_change_rate-example}

- 获取平安银行以及沪深 300 指数一段时间的涨跌幅情况。

```python
[In]
get_price_change_rate(['000001.XSHE', '000300.XSHG'], '20150801', '20150807')
[Out]
order_book_id 000001.XSHE 000300.XSHG
date
2015-08-03 0.037217 0.003285
2015-08-04 0.003120 0.031056
2015-08-05 -0.020995 -0.020581
2015-08-06 -0.004766 -0.009064
2015-08-07 0.006385 0.019597
```

### current_snapshot - 获取当前行情快照 {#rqdata-API-current_snapshot}

```python
current_snapshot(order_book_ids, market='cn')
```

获取合约当前的 level1 行情快照数据，也支持集合竞价数据。

#### 参数 {#rqdata-API-current_snapshot-params}

| 参数           | 类型             | 说明                                                               |
| -------------- | ---------------- | ------------------------------------------------------------------ |
| order_book_ids | _str or str list_| **必填参数**，合约代码，可传入 order_book_id, order_book_id list。 |
| market         | _str_            | 默认是中国市场('cn')，目前仅支持中国市场                           |

#### 返回 {#rqdata-API-current_snapshot-return}

_Tick 对象 或者一个 Tick list_

| 属性               | 类型               | 注释                                                                    |
| ------------------ | ------------------ | ----------------------------------------------------------------------- |
| datetime           | _pandas.Timestamp_ | 时间戳                                                                  |
| order_book_id      | _string_           | 合约代码                                                                |
| open               | _float_            | 当日开盘价                                                              |
| high               | _float_            | 当日最高价                                                              |
| low                | _float_            | 当日最低价                                                              |
| last               | _float_            | 最新价                                                                  |
| prev_settlement    | _float_            | 昨日结算价                                                              |
| prev_close         | _float_            | 昨日收盘价                                                              |
| volume             | _float_            | 成交量                                                                  |
| total_turnover     | _float_            | 成交额                                                                  |
| limit_up           | _float_            | 涨停价                                                                  |
| limit_down         | _float_            | 跌停价                                                                  |
| open_interest      | _float_            | 累计持仓量                                                              |
| trading_phase_code | _float_            | 停牌标识。T-正常交易、H-临时停牌、P-全天停牌。目前仅支持深交所股票      |
| asks               | _list_             | 卖出报盘价格，asks[0] 代表盘口卖一档报盘价                              |
| ask_vols           | _list_             | 卖出报盘数量，ask_vols[0] 代表盘口卖一档报盘数量                        |
| bids               | _list_             | 买入报盘价格，bids[0] 代表盘口买一档报盘价                              |
| bid_vols           | _list_             | 买入报盘数量，bid_vols[0] 代表盘口买一档报盘数量                        |
| iopv               | _float_            | 场内基金实时估算净值                                                    |
| prev_iopv          | _float_            | 场内基金前估算净值                                                      |
| close              | _float_            | 当日收盘价（现货专用，约 15：30 可取，可以用是否大于 0 判断是否已有值） |
| settlement         | _float_            | 当日结算价（现货专用）                                                  |

#### 范例 {#rqdata-API-current_snapshot-example}

- 获取期权合约 90000337 当前快照数据

```python
[In] current_snapshot('90000337')
[Out]
Tick(ask_vols: [1, 1, 1, 10, 1], asks: [0.5119, 0.517, 0.5206, 0.5207, 0.522], bid_vols: [1, 1, 1, 1, 1], bids: [0.5007, 0.4967, 0.4926, 0.492, 0.4897], datetime: 2021-03-09 15:02:00, high: 0.6316, iopv: nan, last: 0.5118, limit_down: 0.1144, limit_up: 1.128, low: 0.5118, open: 0.6057, open_interest: 266, order_book_id: 90000337, prev_close: 0.6344, prev_iopv: nan, prev_settlement: 0.6212, total_turnover: 160569, trading_phase_code: T, volume: 27)
```

- 获取某一股票当前快照数据

```python
[In] current_snapshot('000001.XSHE')
[Out]
Tick(ask_vols: [25400, 15500, 12300, 39985, 16200], asks: [13.7, 13.71, 13.72, 13.73, 13.74], bid_vols: [1050, 9300, 172301, 691800, 579400], bids: [13.69, 13.68, 13.67, 13.66, 13.65], datetime: 2020-07-24 11:30:00, high: 13.99, iopv: nan, last: 13.69, low: 13.66, open: 13.97, open_interest: None, order_book_id: 000001.XSHE, prev_close: 14.01, prev_iopv: nan, prev_settlement: None, total_turnover: 1199992014, trading_phase_code: T, volume: 86853387)
```

- 获取某一期货当前快照数据

```
In [22]: current_snapshot('RB2010')
Out[22]: Tick(ask_vols: [158, 655, 954, 247, 373], asks: [3775.0, 3776.0, 3777.0, 3778.0, 3779.0], bid_vols: [25, 513, 90, 56, 2214], bids: [3774.0, 3773.0, 3772.0, 3771.0, 3770.0], datetime: 2020-07-24 11:30:00.143000, high: 3805.0, iopv: nan, last: 3774.0, low: 3766.0, open: 3804.0, open_interest: 1360251.0, order_book_id: RB2010, prev_close: 3806.0, prev_iopv: nan, prev_settlement: 3787.0, total_turnover: 29219994570.0, trading_phase_code: None, volume: 772145.0)

```

- 获取多个当前快照数据

```python
[In] current_snapshot(['000001.XSHE','600000.XSHG'])
[Out]
[Tick(ask_vols: [25400, 15500, 12300, 39985, 16200], asks: [13.7, 13.71, 13.72, 13.73, 13.74], bid_vols: [1050, 9300, 172301, 691800, 579400], bids: [13.69, 13.68, 13.67, 13.66, 13.65], datetime: 2020-07-24 11:30:00, high: 13.99, iopv: nan, last: 13.69, low: 13.66, open: 13.97, open_interest: None, order_book_id: 000001.XSHE, prev_close: 14.01, prev_iopv: nan, prev_settlement: None, total_turnover: 1199992014, trading_phase_code: T, volume: 86853387),
 Tick(ask_vols: [251300, 4100, 13300, 344430, 13200], asks: [10.58, 10.59, 10.6, 10.61, 10.62], bid_vols: [1200, 124406, 294800, 136200, 170100], bids: [10.57, 10.56, 10.55, 10.54, 10.53], datetime: 2020-07-24 11:29:59.860000, high: 10.8, iopv: nan, last: 10.57, low: 10.55, open: 10.78, open_interest: None, order_book_id: 600000.XSHG, prev_close: 10.84, prev_iopv: nan, prev_settlement: None, total_turnover: 363418169.0, trading_phase_code: T, volume: 34090105)]
```

### get_trading_dates - 获取交易日列表 {#rqdata-API-get_trading_dates}

```python
get_trading_dates(start_date, end_date, market='cn')
```

获取指定市场在起止日期范围内的交易日列表。

#### 参数 {#rqdata-API-get_trading_dates-params}

| 参数       | 类型                                                           | 说明                                                                |
| ---------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，开始日期                                              |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，结束日期                                              |
| market     | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_trading_dates-return}

_datetime.date list_ - 交易日期列表

#### 范例 {#rqdata-API-get_trading_dates-example}

```python
[In]
get_trading_dates(start_date='20160505', end_date='20160505')
[Out]
[datetime.date(2016, 5, 5)]
```

### get_previous_trading_date - 获取历史某个交易日 {#rqdata-API-get_previous_trading_date}

```python
get_previous_trading_date(date, n=1, market='cn')
```

获取指定日期之前的第 n 个交易日。

#### 参数 {#rqdata-API-get_previous_trading_date-params}

| 参数   | 类型                                                           | 说明                                                                |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，指定日期                                              |
| n      | _int_                                                          | n 代表往前第 n 个交易日。默认为 1，即前一个交易日                   |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_previous_trading_date-return}

_datetime.date_ - 交易日期

#### 范例 {#rqdata-API-get_previous_trading_date-example}

```python
[In]
get_previous_trading_date('20160502',n=1)
[Out]
[datetime.date(2016, 4, 29)]
```

### get_next_trading_date - 获取未来某个交易日 {#rqdata-API-get_next_trading_date}

```python
get_next_trading_date(date, n=1, market='cn')
```

获取指定日期之后的第 n 个交易日。

#### 参数 {#rqdata-API-get_next_trading_date-params}

| 参数   | 类型                                                           | 说明                                                                |
| ------ | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | **必填参数**，指定日期                                              |
| n      | _int_                                                          | n 代表未来第 n 个交易日。默认为 1，即下一个交易日                   |
| market | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#rqdata-API-get_next_trading_date-return}

_datetime.date_ - 交易日期

#### 范例 {#rqdata-API-get_next_trading_date-example}

```python
[In]
get_next_trading_date(date='2016-05-01',n=1)
[Out]
[datetime.date(2016, 5, 3)]
```

### get_latest_trading_date - 获取当前最近一个交易日 {#rqdata-API-get_latest_trading_date}

```python
get_latest_trading_date(market='cn')
```

获取当前最近一个交易日；若当天为交易日则返回当天，若当天为节假日则返回上一个交易日。

#### 参数 {#rqdata-API-get_latest_trading_date-params}

| 参数   | 类型  | 说明                                                                |
| ------ | ----- | ------------------------------------------------------------------- |
| market | _str_ | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场 |

#### 返回 {#qqdata-API-get_latest_trading_date-return}

_datetime.date_ - 交易日期

#### 范例 {#rqdata-API-get_latest_trading_date-example}

```python
[In]
get_latest_trading_date()
[Out]:
datetime.date(2019, 11, 22)
```

### get_trading_hours - 获取合约连续竞价时间段（即将退役） {#rqdata-API-get_trading_hours}

```python
get_trading_hours(order_book_id, date=None, expected_fmt='str', frequency='1m', market='cn')
```

获取合约连续竞价交易时间段数据。例如返回格式可选 `str`、`time`、`datetime`，频率支持 `1m` 和 `tick`。

::: tip 注意事项

该 API 即将退役，可使用 [get_trading_periods](#rqdata-API-get_trading_periods)

:::

#### 参数 {#rqdata-API-get_trading_hours-params}

| 参数          | 类型                                                           | 说明                                                                                                                                                                                               |
| ------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| order_book_id | _str_                                                          | **必填参数**，合约代码                                                                                                                                                                             |
| date          | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 指定日期。使用场景，部分合约的当前和历史的连续竞价交易时间段会有不同                                                                                                                               |
| expected_fmt  | _str_                                                          | 期望返回的数据类型, 默认为 str，可选值为 str, time, datetime<br/>'str' -这个函数会返回字符串<br/>'time' - 这个函数会返回 datetime.time 类型<br/>'datetime' - 这个函数会返回 datetime.datetime 类型 |
| frequency     | _str_                                                          | 频率,默认为 1m, 对应米筐分钟线时间段的起始, 为 tick 时返回交易所给出的交易时间                                                                                                                     |
| market        | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场                                                                                                                                |

#### 返回 {#rqdata-API-get_trading_hours-return}

_string_ - 交易时间

#### 范例 {#rqdata-API-get_trading_hours-example}

- 获取单个合约的交易时间

```
In [20]: get_trading_hours('000001.XSHE')
Out[20]: '09:31-11:30,13:01-15:00'
```

- 获取单个合约的交易时间, 指定返回 datetime.time 类型

```
In [20]: get_trading_hours("000001.XSHE", expected_fmt="time")
[[datetime.time(9, 31), datetime.time(11, 30)],
 [datetime.time(13, 1), datetime.time(15, 0)]]
```

- 获取单个合约在2025-11-13的交易时间, 指定返回 datetime.datetime类型

```
In [20]: get_trading_hours("A2511", date=20251113, expected_fmt="datetime")
[[datetime.datetime(2025, 11, 12, 21, 1),
  datetime.datetime(2025, 11, 12, 23, 0)],
 [datetime.datetime(2025, 11, 13, 9, 1),
  datetime.datetime(2025, 11, 13, 10, 15)],
 [datetime.datetime(2025, 11, 13, 10, 31),
  datetime.datetime(2025, 11, 13, 11, 30)],
 [datetime.datetime(2025, 11, 13, 13, 31),
  datetime.datetime(2025, 11, 13, 15, 0)]]
```

### get_trading_periods - 获取合约连续竞价时间段（新） {#rqdata-API-get_trading_periods}

```python
get_trading_periods(order_book_ids, start_date =None, end_date=None, frequency='1m', market='cn')
```

获取合约连续竞价交易时间段数据，支持按时间范围查询一个或多个合约。例如频率支持 `1m` 和 `tick`。

#### 参数 {#rqdata-API-get_trading_periods-params}

| 参数           | 类型                                                           | 说明                                                                           |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| order_book_ids | _str or list_                                                  | **必填参数**，合约代码，给出单个或多个 order_book_id                           |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                       |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期。不指定 start_date，end_date 默认返回最近三个月的数据                 |
| frequency      | _str_                                                          | 频率,默认为 1m, 对应米筐分钟线时间段的起始, 为 tick 时返回交易所给出的交易时间 |
| market         | _str_                                                          | 默认是中国内地市场('cn') 。可选'cn' - 中国内地市场；'hk' - 香港市场            |

#### 返回 {#rqdata-API-get_trading_periods-return}

_pandas DataFrame_

#### 范例 {#rqdata-API-get_trading_periods-example}

- 获取单个合约一段时间的连续竞价交易时间段

```
In [20]: get_trading_periods('000001.XSHE',20250901,20250910,'1m')
Out[20]:                trading_hours
order_book_id	date
000001.XSHE	2025-09-01	09:31-11:30,13:01-15:00
            2025-09-02	09:31-11:30,13:01-15:00
            2025-09-03	09:31-11:30,13:01-15:00
            2025-09-04	09:31-11:30,13:01-15:00
            2025-09-05	09:31-11:30,13:01-15:00
            2025-09-08	09:31-11:30,13:01-15:00
            2025-09-09	09:31-11:30,13:01-15:00

```

- 获取多个合约一段时间的连续竞价交易时间段

```
In [20]: get_trading_periods(['000001.XSHE','IF2512'],20250901,20250902,'1m')
Out[20]:                trading_hours
order_book_id	date
000001.XSHE	2025-09-01	09:31-11:30,13:01-15:00
            2025-09-02	09:31-11:30,13:01-15:00
IF2512	    2025-09-01	09:31-11:30,13:01-15:00
            2025-09-02	09:31-11:30,13:01-15:00


```

### get_yield_curve - 获取收益率曲线 {#rqdata-API-get_yield_curve}

```python
get_yield_curve(start_date=None, end_date=None, tenor=None, market='cn')
```

获取一段时间内的收益率曲线数据，目前仅支持中国市场。数据为 2002 年至今的中债国债收益率曲线，例如期限可选隔夜（`0S`）、1 个月（`1M`）、1 年（`1Y`）。

#### 参数 {#rqdata-API-get_yield_curve-params}

| 参数       | 类型                                                           | 说明                                                              |
| ---------- | -------------------------------------------------------------- | ----------------------------------------------------------------- |
| start_date | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                          |
| end_date   | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，不传入 start_date ,end_date 则 默认返回最近三个月的数据 |
| tenor      | _str_                                                          | 标准期限，默认返回全部。'0S' - 隔夜，'1M' - 1 个月，'1Y' - 1 年   |
| market     | _str_                                                          | 默认是中国市场('cn')，目前支持中国市场。                          |

#### 返回 {#rqdat-API-get_yield_curve-return}

_pandas DataFrame_ - 查询时间段内无风险收益率曲线

#### 范例 {#rqdata-API-get_yield_curve-example}

-

```python
[In]
get_yield_curve(start_date='20130104', end_date='20140104')

[Out]
                0S      1M      2M      3M      6M      9M      1Y      2Y  \
2013-01-04  0.0196  0.0253  0.0288  0.0279  0.0280  0.0283  0.0292  0.0310
2013-01-05  0.0171  0.0243  0.0286  0.0275  0.0277  0.0281  0.0288  0.0305
2013-01-06  0.0160  0.0238  0.0285  0.0272  0.0273  0.0280  0.0287  0.0304

                3Y      4Y   ...        6Y      7Y      8Y      9Y     10Y  \
2013-01-04  0.0314  0.0318   ...    0.0342  0.0350  0.0353  0.0357  0.0361
2013-01-05  0.0309  0.0316   ...    0.0342  0.0350  0.0352  0.0356  0.0360
2013-01-06  0.0310  0.0315   ...    0.0340  0.0350  0.0352  0.0356  0.0360
...
```

### get_live_minute_price_change_rate - 获取当日分钟累计收益率（股票，指数） {#rqdata-API-get-live-minute-price-change_rate}

```python
rqdatac.get_live_minute_price_change_rate(order_book_ids)
```

获取股票和指数的当日分钟累计收益率数据。

#### 参数 {#rqdata-API-get-live-minute-price-change_rate-params}

| 参数           | 类型          | 说明                                                 |
| -------------- | ------------- | ---------------------------------------------------- |
| order_book_ids | _str or list_ | **必填参数**，合约代码，给出单个或多个 order_book_id |

#### 返回 {#rqdata-API-get-live-minute-price-change_rate-return}

_pandas DataFrame_

| 字段        | 类型    | 说明               |
| ----------- | ------- | ------------------ |
| change_rate | _float_ | 当前分钟累计收益率 |

#### 范例 {#rqdata-API-get-live-minute-price-change_rate-example}

- 获取多个合约当日分钟涨跌幅

```python
[In]
rqdatac.get_live_minute_price_change_rate(['000001.XSHE','600000.XSHG'])
[Out]
order_book_id        000001.XSHE  600000.XSHG
datetime
2022-09-23 09:31:00    -0.002441    -0.002809
2022-09-23 09:32:00    -0.001627    -0.001404
2022-09-23 09:33:00     0.000814    -0.002809
2022-09-23 09:34:00     0.000814    -0.002809
2022-09-23 09:35:00     0.000000    -0.001404
...                          ...          ...
2022-09-23 14:56:00    -0.000814     0.004213
2022-09-23 14:57:00     0.000000     0.004213
2022-09-23 14:58:00     0.000814     0.004213
2022-09-23 14:59:00     0.000814     0.004213
2022-09-23 15:00:00     0.000000     0.005618

[240 rows x 2 columns]
```

### get_future_latest_trading_date - 获取当前最近一个期货交易日 {#rqdata-API-get_future_latest_trading_date}

```python
get_future_latest_trading_date(market='cn')
```

获取当前最近一个期货交易日；夜盘集合竞价开始即视为新的交易日，若当天为节假日则返回下一个交易日。

#### 参数 {#rqdata-API-get_future_latest_trading_date-params}

| 参数   | 类型  | 说明                     |
| ------ | ----- | ------------------------ |
| market | _str_ | 默认是中国内地市场('cn') |

#### 返回 {#rqdata-API-get_future_latest_trading_date-return}

_datetime.date_ - 交易日期

#### 范例 {#rqdata-API-get_future_latest_trading_date-example}

```python
[In]
get_future_latest_trading_date()
[Out]:
datetime.date(2023, 6, 21)
```

### get_vwap - 获取日/分钟级别的 vwap 数据 {#rqdata-API-get_vwap}

```python
rqdatac.get_vwap(order_book_ids, start_date=None, end_date=None, frequency='1d')
```

获取成交量加权平均价格数据，支持历史和实时查询。例如支持股票、期货、期权、ETF、可转债，也支持日级和分钟级数据。

#### 参数 {#rqdata-API-get_vwap-params}

| 参数           | 类型                                                           | 说明                                                                                                        |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| order_book_ids | _str or str list_                                              | **必填参数**，合约代码，可传入 order_book_id, order_book_id list                                            |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期                                                                                                    |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期                                                                                                    |
| frequency      | _str_                                                          | 历史数据的频率。 默认为'1d'。<br/>1m - 分钟级别<br/>1d - 日级别<br/>分钟可选取不同频率，例如'5m'代表 5 分线 |

#### 返回 {#rqdata-API-get_vwap-return}

_Series_ - vwap

#### 范例 {#rqdata-API-get_vwap-example}

获取 000001.XSHE 在 2024-01-01~02-01 的日级别 vwap 数据

```python
[In]
rqdatac.get_vwap('000001.XSHE',20240101,20240201)
[Out]:
order_book_id  date
000001.XSHE    2024-01-02    9.286718
               2024-01-03    9.182990
               2024-01-04    9.112191
               2024-01-05    9.302265
               2024-01-08    9.178084
               2024-01-09    9.140973
               2024-01-10    9.128256
               2024-01-11    9.135580
               2024-01-12    9.203141
               2024-01-15    9.205756
               2024-01-16    9.277993
               2024-01-17    9.314772
               2024-01-18    9.103892
               2024-01-19    9.148154
               2024-01-22    9.174462
               2024-01-23    9.078450
               2024-01-24    9.209698
               2024-01-25    9.422591
               2024-01-26    9.562171
               2024-01-29    9.730338
               2024-01-30    9.594930
               2024-01-31    9.481586
               2024-02-01    9.414571
Name: 000001.XSHE, dtype: float64
```

获取 IF2403 在 2024-02-01 的 1m 级别 vwap 数据

```python
[In]
rqdatac.get_vwap('IF2403',20240201,20240201,'1m')
[Out]
order_book_id  datetime
IF2403         2024-02-01 09:31:00    3201.224586
               2024-02-01 09:32:00    3196.929688
               2024-02-01 09:33:00    3200.511346
               2024-02-01 09:34:00    3201.722967
               2024-02-01 09:35:00    3203.796373
                                         ...
               2024-02-01 14:56:00    3210.391429
               2024-02-01 14:57:00    3209.169421
               2024-02-01 14:58:00    3208.998773
               2024-02-01 14:59:00    3208.252893
               2024-02-01 15:00:00    3207.797403
Name: IF2403, Length: 240, dtype: float64
```

### is_data_ready - 获取数据最近的更新状态 {#rqdata-API-is_data_ready}

```python
rqdatac.is_data_ready(categories=None, expected_date=None, market=None)
```

获取数据最近的更新状态，**目前仅支持查询行情数据**。


#### 参数 {#rqdata-API-is_data_ready-params}

| 参数           | 类型                                                            | 说明                                                                 |
| -------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------|
| categories     | _str or str list_                                              | 数据种类，如 stock_daybar, stock_minbar，可选种类见下方表格。默认返回所有 |
| expected_date  | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 期望日期，默认是当天                                                    |
| market         | _str or str list_                                              | 可选'cn' - 中国内地市场；'hk' - 香港市场，默认返回所有市场。              |

##### 数据种类类型 {#rqdata-API-is_data_ready-type}

| categories            | 说明                |
|-----------------------|---------------------|
| stock_daybar          | 股票日线             |
| stock_minbar          | 股票分钟线           |
| stock_tick            | 股票 tick            |
| exchange_index_daybar | 交易所指数日线       |
| exchange_index_minbar | 交易所指数分钟线     |
| exchange_index_tick   | 交易所指数 tick      |
| etf_daybar            | ETF日线             |
| etf_minbar            | ETF分钟线           |
| etf_tick              | ETF tick            |
| lof_daybar            | LOF日线             |
| lof_minbar            | LOF分钟线           |
| lof_tick              | LOF tick           |
| future_daybar         | 期货日线            |
| future_minbar         | 期货分钟线          |
| future_tick           | 期货 tick           |
| option_daybar         | 期权日线            |
| option_minbar         | 期权分钟线          |
| option_tick           | 期权 tick          |
| convertible_daybar    | 可转债日线           |
| convertible_minbar    | 可转债分钟线         |
| convertible_tick      | 可转债 tick         |
| spot_daybar           | 现货日线           |
| spot_minbar           | 现货分钟线         |
| spot_tick             | 现货 tick         |
| repo_daybar           | 回购日线           |
| repo_minbar           | 回购分钟线         |
| repo_tick             | 回购 tick          |
| reits_daybar          | REITs日线          |
| reits_minbar          | REITs分钟线        |
| reits_tick            | REITs tick         |


#### 返回 {#rqdata-API-is_data_ready-return}

_pandas DataFrame_

| 字段                | 类型               | 说明                                                                                   |
| ------------------- | ------------------ | -------------------------------------------------------------------------------------- |
| market              | _str_              | 市场                                                                                  |
| category            | _str_              | 数据种类                                                                              |
| latest_date         | _pandas.Timestamp_ | 数据最新日期                                                                           |
| update_time         | _pandas.Timestamp_ | 最近一次更新成功时间                                                                    |
| expect_date         | _pandas.Timestamp_ | 期望数据最新日期                                                                        |
| ready               | _bool_             | 是否已更新完毕。True - 已更新；False - 未更新                                            |

#### 范例 {#rqdata-API-is_data_ready-example}

获取所有数据种类最近的更新状态（当前调用时间是2026年6月18日 21:30）

```python
[In]
rqdatac.is_data_ready()
[Out]
                          latest_date	update_time	expected_date	ready
market	category				
cn	convertible_daybar	  2026-06-18	2026-06-18 15:54:16	2026-06-18	True
    convertible_minbar	  2026-06-18	2026-06-18 15:32:08	2026-06-18	True
    convertible_tick	    2026-06-18	2026-06-18 16:43:54	2026-06-18	True
    etf_daybar	          2026-06-18	2026-06-18 15:54:15	2026-06-18	True
    etf_minbar	          2026-06-18	2026-06-18 15:35:06	2026-06-18	True
    etf_tick	            2026-06-18	2026-06-18 16:43:12	2026-06-18	True
    exchange_index_daybar	2026-06-18	2026-06-18 15:54:21	2026-06-18	True
    exchange_index_minbar	2026-06-18	2026-06-18 15:37:42	2026-06-18	True
    exchange_index_tick	  2026-06-18	2026-06-18 16:45:37	2026-06-18	True
... ... ...
    stock_daybar	        2026-06-18	2026-06-18 15:54:15	2026-06-18	True
    stock_minbar	        2026-06-18	2026-06-18 15:34:35	2026-06-18	True
    stock_tick	          2026-06-18	2026-06-18 16:42:14	2026-06-18	True
hk	stock_daybar	        2026-06-18	2026-06-18 18:15:10	2026-06-18	True
    stock_minbar	        2026-06-18	2026-06-18 21:02:24	2026-06-18	True
    stock_tick	          2026-06-18	2026-06-18 21:03:13	2026-06-18	True


```

获取A股和港股tick 2026-06-22 这天数据的更新状态（当前调用时间是2026年6月22日 08:30）

```python
[In]
rqdatac.is_data_ready(categories='stock_tick', expected_date=20260622)
[Out]
                  latest_date	update_time	expected_date	ready
market	category				
cn	stock_tick	2026-06-18	2026-06-18 16:42:14	2026-06-22	False
hk	stock_tick	2026-06-18	2026-06-18 21:03:13	2026-06-22	False
```

获取A股日线和期货分钟 2026-06-18 这天数据的更新状态（当前调用时间是2026年6月22日 08:30）

```python
[In]
rqdatac.is_data_ready(categories=['stock_daybar','future_minbar'], expected_date=20260618)
[Out]
                 latest_date	update_time	expected_date	ready
market	category				
cn	future_minbar	2026-06-18	2026-06-18 16:19:15	2026-06-18	True
    stock_daybar	2026-06-18	2026-06-18 15:54:15	2026-06-18	True
hk	stock_daybar	2026-06-18	2026-06-18 18:15:10	2026-06-18	True
```


## 实时行情推送 {#rqdata-API-websocket}

考虑到实时行情中，用户不太方便通过主动轮询 API 去获取合约最新不间断的实时行情，米筐开发提供了 python sdk 和 websocket 网络接口，用以支持用户获取实时行情推送数据，具体说明如下：

#### Ricequant 实时数据的种类包括

| 资产类别   | 说明                      |
| ---------- | ------------------------- |
| 中国 A 股  | 支持 主板、创业板、科创板 |
| 场内基金   | 包括 ETF、LOF             |
| 可转债     | 沪深市场合约              |
| 中国期货   | 包括股指、国债、商品期货  |
| 中国期权   | 包括 ETF、股指、商品期权  |
| 国债逆回购 | 沪深市场合约              |
| 现货       | 包括黄金、铂金、白银等    |

#### Ricequant 实时数据的频率包括

- 提供 Level1 tick 五档深度行情
- 提供实时的 1 、3、5、15、30、60 等任意频率的分钟行情合成
  （注：30、60 分钟线是按照时间进行切片。例如合约在 10:15-10:30 休市，则 60 分钟线在 11:00 只包含 45 分钟的交易；而 30 分钟线将出现 10:15 的时间戳）

#### A、实时行情推送的适用场景

1、 驱动实盘交易或者模拟交易<br/>
2、 若客户已有实时行情，米筐可以作为备份

#### B、相较于 RQData 请求数据的优点

1、 推送会比拉取型 API 返回实时行情更及时，效率更高<br/>
2、 提供 python sdk 和 websocket 网络接口，用户可以使用任意语言接入，语言中性<br/>
3、 基于 ricequant 的数据能力和 rqdata 的基础设施，数据准确快速，可靠性高

### LiveMarketDataClient - websocket 实时行情推送方案 {#rqdata-API-LiveMarketDataClient}

通过简单的一行代码从 RQData 引入 LiveMarketDataClient ，即可实现实时行情数据的推送。分别提供阻塞和不阻塞的调用方式，具体请参考范例。

#### 范例 {#rqdata-API-LiveMarketDataClient-example}

```python
[In]
import rqdatac
from rqdatac import LiveMarketDataClient


rqdatac.init(username="license", password="邮件中一大串license的key")
client = LiveMarketDataClient()
# 订阅一支tick标的
client.subscribe('tick_000001.XSHE')
# 订阅1分钟行情
client.subscribe('bar_000001.XSHE')
# 订阅多支tick标的
client.subscribe(['tick_000001.XSHE', 'tick_000002.XSHE'])

# 订阅3分钟行情，其它分钟线的命名方法类似，修改后缀即可
# client.subscribe('bar_000001.XSHE_3m')

# 取消订阅tick标的
client.unsubscribe('tick_000002.XSHE')

# 检听行情
# 1. 阻塞的方式
for market in client.listen():
    print(market)


# 2. 不阻塞的方式
def handle_msg(tick_or_bar):
    # 可以自行定义处理
    # queue.push(tick_or_bar)
    print(tick_or_bar)
client.listen(handler=handle_msg) # handler不为None


# [Out]
# {'datetime': 20210913094009000, 'order_book_id': '000001.XSHE', 'prev_close': 20.57, 'num_trades': 12786, 'volume': 13134791.0, 'total_turnover': 267427634, 'trading_phase_code': 'T', 'last': 20.26, 'open': 20.36, 'high': 20.51, 'low': 20.25, 'limit_up': 22.63, 'limit_down': 18.51, 'ask': [20.28, 20.3, 20.31, 20.32, 20.33], 'bid': [20.26, 20.25, 20.24, 20.23, 20.22], 'ask_vol': [37100.0, 33500.0, 13200.0, 16100.0, 3600.0], 'bid_vol': [4400.0, 198000.0, 6800.0, 17700.0, 33600.0], 'trading_date': 20210913, 'channel': 'tick_000001.XSHE', 'action': 'feed'}
# {'datetime': 20210913094012000, 'order_book_id': '000001.XSHE', 'prev_close': 20.57, 'num_trades': 12882, 'volume': 13278591.0, 'total_turnover': 270342631, 'trading_phase_code': 'T', 'last': 20.3, 'open': 20.36, 'high': 20.51, 'low': 20.25, 'limit_up': 22.63, 'limit_down': 18.51, 'ask': [20.3, 20.31, 20.32, 20.33, 20.34], 'bid': [20.28, 20.25, 20.24, 20.23, 20.22], 'ask_vol': [15000.0, 13200.0, 16100.0, 3600.0, 4500.0], 'bid_vol': [4400.0, 150000.0, 6800.0, 18500.0, 33600.0], 'trading_date': 20210913, 'channel': 'tick_000001.XSHE', 'action': 'feed'}
# {'datetime': 20210913094015000, 'order_book_id': '000001.XSHE', 'prev_close': 20.57, 'num_trades': 13014, 'volume': 13402691.0, 'total_turnover': 272859932, 'trading_phase_code': 'T', 'last': 20.26, 'open': 20.36, 'high': 20.51, 'low': 20.25, 'limit_up': 22.63, 'limit_down': 18.51, 'ask': [20.27, 20.29, 20.3, 20.32, 20.33], 'bid': [20.26, 20.25, 20.24, 20.23, 20.22], 'ask_vol': [3200.0, 2300.0, 3700.0, 1500.0, 3600.0], 'bid_vol': [500.0, 112400.0, 8000.0, 17700.0, 33600.0], 'trading_date': 20210913, 'channel': 'tick_000001.XSHE', 'action': 'feed'}
# {'datetime': 20210913094018000, 'order_book_id': '000001.XSHE', 'prev_close': 20.57, 'num_trades': 13110, 'volume': 13499491.0, 'total_turnover': 274820911, 'trading_phase_code': 'T', 'last': 20.28, 'open': 20.36, 'high': 20.51, 'low': 20.25, 'limit_up': 22.63, 'limit_down': 18.51, 'ask': [20.28, 20.29, 20.3, 20.32, 20.33], 'bid': [20.25, 20.24, 20.23, 20.22, 20.21], 'ask_vol': [9100.0, 6100.0, 4800.0, 1500.0, 2600.0], 'bid_vol': [52800.0, 8000.0, 17700.0, 33600.0, 165600.0], 'trading_date': 20210913, 'channel': 'tick_000001.XSHE', 'action': 'feed'}

```
