# 估值表 API

估值表按产品管理，用于上传、查询、下载和删除产品每日估值表文件或估值表 JSON 数据。

产品统一使用 `product_id_or_name` 定位。该字段可以传产品 ID 或产品名称，CLI 会解析后请求产品接口。

## `get valuation-report-list`

获取产品估值表列表。该命令返回估值表 metadata 摘要，不返回完整估值表持仓明细。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |
| `fields` | string[]/string | 否 | CLI 返回字段列表，例如 `valuation_report_id`、`file_name`、`date` |
| `limit` | integer | 否 | CLI 返回条数上限 |
| `format` | string | 否 | `json` 或 `ndjson` |

返回：`data.valuation_reports[]` 为估值表 metadata 摘要，支持 `format:"ndjson"`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `valuation_report_id` | string | 估值表 ID，用于下载源文件 |
| `date` | string/date | 估值表日期 |
| `file_name` | string | 源文件名 |
| `source` | string | 来源，当前服务端枚举为 `manual`、`open_api`、`client_upload` |

示例：

```powershell
rqamsc get valuation-report-list --payload '{"product_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31"}'
rqamsc get valuation-report-list --payload '{"product_id_or_name":"demo","fields":["valuation_report_id","file_name","date"],"limit":20,"format":"ndjson"}'
```

## `insert valuation-report`

插入估值表。推荐使用 `file_paths` 上传 `.xls`/`.xlsx` 文件；也可以使用 `valuation_reports` 直接传 JSON 估值表对象。

如果该操作用于修正对账差异，执行前必须先和用户核对产品、估值日期、来源文件或 JSON 摘要、是否覆盖已有估值表，以及对当日持仓、现金和净值的预期影响。使用 `replace_dates` 覆盖已有估值表前必须得到明确确认。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `file_paths` | string[] | 否 | 本地 `.xls`/`.xlsx` 文件路径，或包含估值表文件的目录 |
| `valuation_reports` | object[]/object | 否 | JSON 估值表对象 |
| `replace_dates` | string[]/string | 否 | 允许覆盖的估值表日期 |

`file_paths` 和 `valuation_reports` 至少提供一个。文件上传时 CLI 会过滤非 `.xls`/`.xlsx` 文件；JSON 插入时 CLI 会逐条提交 `valuation_reports`，并把来源标记为 `open_api`。

JSON 估值表构建要点：

1. 每个 `valuation_reports[]` 元素表示一个估值日的一张估值表。
2. 顶层至少提供 `date`、`total_equity`、`units`、`unit_net_value` 和 `positions`；`acc_unit_net_value` 表示累计单位净值，可按产品净值口径提供。
3. `unit_net_value` 通常等于 `total_equity / units`；`acc_unit_net_value` 没有分红调整需求时可省略。
4. 无持仓时传 `positions:[]`；有现金时可用 `order_book_id:"CNY"`、`asset_class:"current_deposit"`、`direction:"long"` 表示活期存款，其他现金类科目按[资产类型](trades.md#资产类型)填写。
5. 非现金持仓需要提供 `quantity`、`cost_price`、`market_value`，建议同时提供 `cost`；债券、期货等资产按实际估值需要补充 `fair_value`、`accrued_interest`、`sterilisation_market_value` 等字段。
6. 如需覆盖已有日期，需要在 payload 顶层传 `replace_dates`，并包含对应估值日期。
7. 如果用 JSON 估值表驱动产品估值，申购、赎回、分红等托管事件不会仅凭估值表自动还原；需要同步导入对应[托管事件](events.md#insert-custodian-event)，才能获得准确的当日收益率数据。

`valuation_reports[]` 单条记录：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `date` | string/date | 是 | 估值表日期 |
| `total_equity` | number | 是 | 净资产 |
| `units` | number | 是 | 份额 |
| `unit_net_value` | number | 是 | 单位净值 |
| `positions` | object[] | 是 | 持仓明细 |
| `acc_unit_net_value` | number/null | 否 | 累计净值 |

`positions[]` 单条记录：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `order_book_id` | string | 是 | 合约 ID |
| `symbol` | string | 是 | 合约名称 |
| `asset_class` | string | 是 | 资产类型 |
| `direction` | string | 是 | 持仓方向，例如 `long`、`short` |
| `market_value` | number | 是 | 市值，以本币计 |
| `quantity` | number | 否 | 持仓数量；现金类资产可不填，其余资产需要提供 |
| `cost_price` | number | 否 | 单位成本；现金类资产可不填，其余资产需要提供 |
| `cost` | number | 否 | 持仓成本 |
| `fair_value` | number | 否 | 公允价值/全价，以人民币计 |
| `fair_value_setl_ccy` | number | 否 | 交易所结算币种下的公允价值，例如港币 |
| `accrued_interest` | number | 否 | 应计利息 |
| `sterilisation_market_value` | number | 否 | 期货类资产需要提供的平衡项市值 |

返回：`data[]` 为上传或插入结果。文件上传结果包含 `file` 和 `result`；单个文件上传失败时包含 `file` 和 `err_msg`。

示例：

```powershell
rqamsc insert valuation-report --payload '{"product_id_or_name":"demo","file_paths":["D:/tmp/valuation.xlsx"]}'
rqamsc insert valuation-report --payload '{"product_id_or_name":"demo","replace_dates":["2026-01-31"],"valuation_reports":[{"date":"2026-01-31","total_equity":1000000,"units":1000000,"unit_net_value":1,"positions":[]}]}'
rqamsc insert valuation-report --payload '{"product_id_or_name":"demo","replace_dates":["2026-01-31"],"valuation_reports":[{"date":"2026-01-31","total_equity":1000000,"units":1000000,"unit_net_value":1,"acc_unit_net_value":1,"positions":[{"order_book_id":"CNY","symbol":"活期存款","asset_class":"current_deposit","direction":"long","market_value":500000},{"order_book_id":"000001.XSHE","symbol":"平安银行","asset_class":"stock","direction":"long","quantity":10000,"cost_price":10,"cost":100000,"market_value":500000,"fair_value":50}]}]}'
```

## `delete valuation-report`

按日期删除产品估值表。服务端会同时删除估值表数据和对应的源文件 metadata。

删除估值表会影响对账、估值和净值结果。用于修正对账差异时，执行前必须先让用户确认删除日期和后续补数方案。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `dates` | string[]/string | 是 | 要删除的估值表日期 |

返回：`data` 为服务端删除结果，包含影响记录数。

示例：

```powershell
rqamsc delete valuation-report --payload '{"product_id_or_name":"demo","dates":["2026-01-31"]}'
```

## `get valuation-report-file`

下载估值表源文件。传 `valuation_report_id` 时下载单个文件；不传 `valuation_report_id` 时，CLI 会先执行估值表列表查询，再按列表中的 `valuation_report_id` 和 `file_name` 批量下载。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_id_or_name` | string | 是 | 产品 ID/名称 |
| `save_path` | string | 是 | 保存目录或保存文件路径 |
| `valuation_report_id` | string | 否 | 估值表 ID；传入时下载单个文件 |
| `file_name` | string | 否 | 单文件下载时的保存文件名 |
| `start_date` | string/date | 否 | 批量下载前列表查询的起始日期 |
| `end_date` | string/date | 否 | 批量下载前列表查询的结束日期 |
| `fields` | string[]/string | 否 | 批量下载前列表查询的字段；需要包含 `valuation_report_id` 和 `file_name` |
| `limit` | integer | 否 | 批量下载文件数量上限 |

返回：单文件下载返回 `data.path`、`data.content_type` 和 `data.bytes`；批量下载返回 `data.successful[]` 和 `data.failed[]`。文件内容不会写到 stdout。

示例：

```powershell
rqamsc get valuation-report-file --payload '{"product_id_or_name":"demo","valuation_report_id":"...","save_path":"D:/tmp/reports","file_name":"valuation.xlsx"}'
rqamsc get valuation-report-file --payload '{"product_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31","limit":20,"save_path":"D:/tmp/reports"}'
```
