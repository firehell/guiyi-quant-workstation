# 产品与产品组 API

产品和产品组是多数业务命令的定位对象。产品命令使用 `product_id_or_name`，产品组命令使用 `product_group_id_or_name`。

## `get product-list`

获取当前 workspace 下的产品列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `fields` | string[]/string | 否 | CLI 返回字段；默认 `id`、`name`、`start_date`、`label` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `raw` | boolean | 否 | 为 `true` 时保留服务端原始字段 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.products[]` 为产品列表，`data.total` 为服务端产品数量。支持 `format:"ndjson"`。

示例：

```powershell
rqamsc get product-list --payload '{"fields":["id","name","start_date"],"limit":20,"format":"ndjson"}'
```

## `get product`

获取单个产品详情。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |

返回：`data` 为产品详情，字段见[产品字段](#产品字段)。

示例：

```powershell
rqamsc get product --payload '{"product_id_or_name":"demo"}'
```

## `insert product`

创建产品。payload 顶层直接传产品字段；也支持把产品字段放在顶层 `product` 对象中。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 产品名称 |
| `data_source` | string | 是 | 数据来源，取值见[产品字段](#产品字段) |
| `investment_category` | string | 是 | 投资类型；默认 `equity`，取值见[产品字段](#产品字段) |
| `strategy_category` | string | 是 | 策略类型；默认 `stock_long`，取值见[产品字段](#产品字段) |
| `benchmark` | object | 是 | 基准配置；默认沪深300，具体字段见[产品字段](#产品字段) |
| `calendar` | string | 是 | 日历类型；默认 `exchange`，取值见[产品字段](#产品字段) |
| `unit_policy` | string/null | 条件必填 | `trade` 和 `trade_and_valuation_report` 产品必填；取值见[产品字段](#产品字段) |
| `start_date` | string/date | 是 | 产品开始日期；默认可用 `2020-01-01` |
| `report_name` | string | 否 | 对外报告名称；模板建议同 `name` |
| `full_name` | string | 否 | 产品全名；模板建议同 `name` |
| `trading_start_date` | string/date | 否 | 产品开始交易日期；不传时服务端默认同 `start_date` |
| `accounts` | object[] | 否 | 账户配置；模板建议一个 `stock` 账户，具体字段见[产品字段](#产品字段) |
| `fee_settings` | object | 否 | 费率配置；模板建议各项费率为 `0`，具体字段见[产品字段](#产品字段) |
| 其他产品字段 | mixed | 否 | 见[产品字段](#产品字段) |

返回：`data` 为服务端创建结果。

默认模板：

下面的文档模板用于让 agent 或用户快速生成创建产品的 payload 草稿。如果需要查看当前 CLI runtime schema，可运行：

```powershell
rqamsc schema get --payload '{"command":"insert product"}'
```

默认值模板如下；这些字段不是创建产品时必须手工填写的字段，但如果需要显式控制默认口径，可以按这个模板展开到 payload 中：

```json
{
  "name": "demo",
  "report_name": "demo",
  "full_name": "demo",
  "start_date": "2020-01-01",
  "trading_start_date": "2020-01-01",
  "data_source": "trade_and_valuation_report",
  "investment_category": "equity",
  "strategy_category": "stock_long",
  "benchmark": {
    "type": "index",
    "id": "000300.XSHG"
  },
  "unit_policy": "manual",
  "calendar": "exchange",
  "accounts": [
    {
      "name": "stock",
      "is_custodian": false,
      "account_number": "RQ0000000001",
      "broker": "ricequant"
    }
  ],
  "fee_settings": {
    "management_fee": 0,
    "custodian_fee": 0,
    "operation_fee": 0,
    "sales_and_service_fee": 0,
    "performance_pay": 0
  }
}
```

创建默认值口径：

- 产品业务默认值：上面的模板给出创建产品时的推荐口径，包括 `investment_category`、`strategy_category`、`benchmark`、`calendar`、`accounts` 和 `fee_settings`。
- 命名和起始日默认值：模板中 `report_name` 和 `full_name` 可与 `name` 保持一致；`start_date` 和 `trading_start_date` 可使用 `2020-01-01`。
- `valuation_start_point` 已弃用，创建产品时不要传；服务端会按数据源和初始估值表场景自行处理。
- 产品定义默认值：参考 `rqams-definition` 中 `Product` 的默认字段，例如 `realtime_period_type=daytime`、`label=paper`、`description=""`，以及若干可选字段默认为 `null`。
- 服务端上下文字段：`user_id`、`workspace_id`、`id`、`create_time` 通常由服务端根据登录态、当前 workspace 或创建流程写入。

示例：

```powershell
rqamsc insert product --payload '{"name":"demo","report_name":"demo","full_name":"demo","data_source":"trade_and_valuation_report","investment_category":"equity","strategy_category":"stock_long","benchmark":{"type":"index","id":"000300.XSHG"},"calendar":"exchange","unit_policy":"manual","start_date":"2020-01-01","trading_start_date":"2020-01-01"}'
```

## `update product`

更新产品字段。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `update_fields` | object | 是 | 要更新的产品字段 |

返回：`data` 为更新结果。

示例：

```powershell
rqamsc update product --payload '{"product_id_or_name":"demo","update_fields":{"description":"updated"}}'
```

## `delete product`

删除产品。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |

返回：`data` 为删除结果。

## 产品字段

字段结构参考 `rqams-definition` 的 `Product`、`ProductAccount`、`ProductBenchmark`、`ValuationSettings` 和 `ExchangeRateSettings`。创建产品时，`user_id`、`workspace_id`、`id`、`create_time` 通常由服务端生成或按当前登录态补齐，不建议在创建 payload 中手工传入。

| 字段 | 类型 | 创建时 | 返回 | 默认值/说明 |
| --- | --- | --- | --- | --- |
| `id` | string | 不传 | 是 | 产品 ID，服务端生成 |
| `name` | string | 必填 | 是 | 产品名称；CLI 模板为 `demo` |
| `data_source` | string | 必填 | 是 | 数据来源；默认可用 `trade_and_valuation_report`。取值：`trade`<br>`valuation_report`<br>`trade_and_valuation_report` |
| `investment_category` | string | 必填 | 是 | 投资类型；默认 `equity`。取值：`equity` 权益类<br>`fixed_income` 固收类<br>`derivatives` 商品及金融衍生品类<br>`hybrid` 混合类<br>`cash_management` 现金管理类<br>`stock` 股票型<br>`bond` 债券型<br>`commodity` 商品型<br>`money_market` 货币市场型<br>`other` 另类投资类<br>`fof` FOF<br>`insurance` 保险资管 |
| `strategy_category` | string | 必填 | 是 | 策略类型；默认 `stock_long`。取值：`index_enhanced` 指数增强<br>`equity_market_neutral` 市场中性<br>`stock_long` 股票多头<br>`commodity_trading_advisor` CTA<br>`mixed` 混合策略<br>`long_short_stock` 股票多空<br>`stock_leverage_neutral` 股票杠杆中性<br>`stock_leverage_long_short` 股票杠杆多空<br>`unconventionality` 其他 |
| `benchmark` | object | 必填 | 是 | 基准配置；默认 `{"type":"index","id":"000300.XSHG"}` |
| `benchmark.type` | string | 必填 | 是 | 基准类型。取值：`index`<br>`customized_index` |
| `benchmark.id` | string | 必填 | 是 | 当 `benchmark.type=index` 时为指数 order book id，例如 `000300.XSHG`；当 `benchmark.type=customized_index` 时为自定义基准 ID |
| `calendar` | string | 必填 | 是 | 产品日历；默认 `exchange`。取值：`exchange` 交易所日历<br>`natural` 自然日 |
| `unit_policy` | string/null | 条件必填 | 是 | `trade` 和 `trade_and_valuation_report` 产品必填。取值：`auto_prev_unit_net_value` 自动份额：按前一日净值申赎<br>`manual` 手工修改份额 |
| `start_date` | string/date | 条件必填 | 是 | 产品开始日期；无初始估值表时必填，默认可用 `2020-01-01` |
| `full_name` | string/null | 可选 | 是 | 产品全名；模板建议同 `name` |
| `report_name` | string | 可选 | 是 | 对外报告名称；模板建议同 `name` |
| `trading_start_date` | string/date | 可选 | 是 | 产品开始交易日期；不传时服务端默认同 `start_date` |
| `valuation_start_point` | string/date/null | 不传 | 可能 | 已弃用；创建 payload 不要传，服务端按数据源和初始估值表场景自行处理 |
| `accounts[]` | array | 可选 | 是 | 账户配置；服务端允许缺省为空数组，模板建议包含一个 `stock` 账户 |
| `accounts[].name` | string | 可选 | 是 | 账户名称，例如 `stock` |
| `accounts[].is_custodian` | boolean | 可选 | 是 | 是否托管账户 |
| `accounts[].account_number` | string | 可选 | 是 | 资金账号 |
| `accounts[].broker` | string | 可选 | 是 | 交易通道。取值：`caitong` 财通证券通道<br>`changjiang` 长江证券通道<br>`cicc` 中金财富通道<br>`cicc_returns_swap` 中金收益互换通道<br>`citic` 中信证券通道<br>`citic_construction` 中建投通道<br>`citic_returns_swap` 中信收益互换通道<br>`donghai` 东海通道<br>`everbright` 光大证券通道<br>`galaxy` 银河证券通道<br>`guolian` 国联证券通道<br>`guosen` 国信证券通道<br>`guotou` 国投证券通道<br>`guotaijunan` 国泰君安证券通道<br>`haitong` 海通证券通道<br>`hengtai` 恒泰通道<br>`huatai` 华泰证券通道<br>`kingstar` 金仕达通道<br>`minsheng` 民生期货通道<br>`ricequant` RQ通道<br>`rqfof` RQ-FOF通道<br>`sealand` 国海证券通道<br>`tianfeng` 天风证券通道<br>`wukuang` 五矿证券通道<br>`zheshang` 浙商证券通道<br>`zhongtai` 中泰通道 |
| `fee_settings` | object | 可选 | 是 | 费率配置；服务端允许缺省为空对象，模板建议各项费率为 `0` |
| `fee_settings.management_fee` | number | 可选 | 是 | 管理费 |
| `fee_settings.custodian_fee` | number | 可选 | 是 | 托管费 |
| `fee_settings.sales_and_service_fee` | number | 可选 | 是 | 销售服务费 |
| `fee_settings.operation_fee` | number | 可选 | 是 | 运营费 |
| `fee_settings.performance_pay` | number | 可选 | 是 | 业绩报酬；默认 `0` |
| `realtime_period_type` | string | 可选 | 是 | 实时估值时间类型；产品定义默认 `daytime`。取值：`daytime` 仅白天 09:30 - 15:00<br>`valuation_day` 估值表日 21:00 - 15:00 (+1) |
| `valuation_settings` | object/null | 可选 | 是 | 资产估值方式配置；默认 `null` |
| `valuation_settings.etf` | string/null | 可选 | 是 | ETF 估值依据。取值：`close` 当日收盘价<br>`iopv` 当日净值（IOPV） |
| `valuation_settings.fut_opt` | string/null | 可选 | 是 | 期货/期权估值依据。取值：`close` 当日收盘价<br>`settlement` 当日结算价 |
| `valuation_settings.acc_net_value` | string/null | 可选 | 是 | 累计净值估值方式。取值：`last_unit_net_value` T-1 日累计净值 + T 日单位净值 - T-1 日单位净值 + T 日产品单位份额分红<br>`acc_unit_dividend` T 日单位净值 + 产品起始日至今累计单位份额分红 |
| `exchange_rate_settings` | object/null | 可选 | 是 | 估值汇率配置；默认 `null` |
| `exchange_rate_settings.HKD` | string/null | 可选 | 是 | 港币汇率来源。取值：`sh` 沪港通中间价<br>`sz` 深港通中间价 |
| `label` | string | 可选 | 是 | 产品标签；产品定义默认 `paper`。取值：`live` 实盘<br>`paper` 模拟<br>`paper_trading` 模拟交易 |
| `auto_equity` | boolean/null | 可选 | 是 | 是否自动权益；默认 `null` |
| `auto_overwrite` | boolean/null | 可选 | 是 | 是否用估值表自动覆盖头寸；默认 `null` |
| `create_time` | string/datetime | 不传 | 是 | 创建时间，服务端生成 |
| `manager` | string/null | 可选 | 是 | 管理人；默认 `null` |
| `invest_advisor` | string/null | 可选 | 是 | 投资顾问；默认 `null` |
| `invest_manager` | string/null | 可选 | 是 | 投资经理；默认 `null` |
| `operating_expenses_md` | string/null | 可选 | 是 | 运营费用说明 Markdown；默认 `null` |
| `maturity_date` | string/date/null | 可选 | 是 | 到期日；默认 `null` |
| `closing_date` | string/date/null | 不传 | 是 | 封账日；通常由封账接口维护 |
| `fund_code` | string/null | 可选 | 是 | 基金代码；默认 `null` |
| `description` | string | 可选 | 是 | 描述；产品定义默认空字符串 |
| `product_state` | string | 不传 | 是 | 产品状态，服务端生成。取值：`normal`<br>`terminated` |
| `user_id` | string/int | 不传 | 是 | 创建者用户 ID，服务端按登录态写入 |
| `workspace_id` | string | 不传 | 是 | 所属 workspace ID，服务端按当前 workspace 写入 |

常用指数基准 ID：`000300.XSHG` 沪深300、`000905.XSHG` 中证500、`000510.XSHG` 中证A500、`000906.XSHG` 中证800、`000852.XSHG` 中证1000、`932000.INDX` 中证2000、`899050.BJSE` 北证50、`930930.INDX` 中证港股通综合指数。自定义基准请使用 `customized_index` 和对应自定义基准 ID。

## `get product-group-list`

获取当前 workspace 下的产品组列表。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `fields` | string[]/string | 否 | CLI 返回字段；默认 `id`、`name`、`start_date`、`label` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `raw` | boolean | 否 | 为 `true` 时保留服务端原始字段 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.product_groups[]` 为产品组列表，`data.total` 为服务端产品组数量。支持 `format:"ndjson"`。

## `get product-group`

获取单个产品组详情。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_group_id_or_name` | string | 是 | 产品组 ID/名称 |

返回：`data` 为产品组详情，字段见[产品组字段](#产品组字段)。

## `update product-group`

更新产品组字段。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_group_id_or_name` | string | 是 | 产品组 ID/名称 |
| `update_fields` | object | 是 | 要更新的产品组字段 |

返回：`data` 为更新结果。

## `delete product-group`

删除产品组。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_group_id_or_name` | string | 是 | 产品组 ID/名称 |

返回：`data` 为删除结果。

## 产品组字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 产品组 ID |
| `name` | string | 产品组名称 |
| `report_name` | string | 对外报告名称 |
| `products[]` | array | 产品组内产品列表 |
| `product_ids[]` | array | 产品 ID 列表 |
| `product_weights` | object | 产品权重 |
| `is_agg_by_weights` | boolean | 是否按权重聚合 |
| `benchmark` | object | 产品组基准 |
| `label` | string | 产品组标签 |
| `start_date` | string/date | 估值起始日 |
| `trading_start_date` | string/date | 交易起始日 |
| `realtime_period_type` | string | 实时估值时间类型 |
| `strategy_category` | string[] | 策略类型列表 |
| `rebalance_frequency` | string/null | 再平衡频率 |
| `create_time` | string/datetime | 创建时间 |
| `maturity_date` | string/date/null | 到期日 |
| `description` | string | 产品组描述 |
| `accessible` | boolean | 是否可访问 |
| `accessible_err_msg[]` | array | 访问异常信息 |
| `user_id` | string/int | 创建者用户 ID |
| `workspace_id` | string | 所属 workspace ID |
