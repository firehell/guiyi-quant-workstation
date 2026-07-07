## 现货行情数据说明 {#rqdata-API-spot-overview}

可获取上海黄金现货交易所上市的现货，包含黄金、铂金、白银等的日行情、分钟行情、tick 行情数据，具体调用方式请参考: [API-get_price](generic-api.md#rqdata-API-get_price).

## get_spot_benchmark_price - 获取现货早午盘价 {#rqdata-API-get_spot_benchmark_price}

```python
get_price_change_rate(order_book_ids, start_date='20130104', end_date='20140104', expect_df=True)
```

获取上海黄金交易所现货基准价数据，支持按合约和时间范围查询早盘价、午盘价。例如可获取 AU9999.SGEX、AG9999.SGEX 等现货合约的基准价数据。

#### 参数 {#spot-API-get_spot_benchmark_price-params}

| 参数           | 类型                                                           | 说明                                                                                                  |
| -------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| order_book_ids | _str_ or _str list_                                            | **必填参数**，合约代码，可输入 order_book_id, order_book_id list。比如 'AU9999.SGEX'或者'AG9999.SGEX' |
| start_date     | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 开始日期，默认为近 3 个月                                                                             |
| end_date       | _int, str, datetime.date, datetime.datetime, pandas.Timestamp_ | 结束日期，默认为近 3 个月                                                                             |

#### 返回 {#spot-API-get_spot_benchmark_price-return}

_pandas DataFrame_

| 返回           | 类型               | 说明     |
| -------------- | ---------------   | -------- |
| order_book_ids | _str_             | 合约代码 |
| date           | _pandas.Timestamp_ | 日期     |
| morning        | _float_           | 早盘价格 |
| noon           | _float_           | 午盘价格 |

#### 范例 {#spot-API-get_spot_benchmark_price-example}


```python
[In]
rqdatac.get_spot_benchmark_price('AU9999.SGEX',20230501,20230508)
[Out]
                          morning    noon
order_book_id date
AU9999.SGEX   2023-05-04   453.77  453.24
              2023-05-05   455.84  455.57
```
