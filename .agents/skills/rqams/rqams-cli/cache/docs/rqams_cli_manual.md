# rqams-cli 使用手册

本文档是 `rqamsc` 的完整使用手册入口，统一维护安装方式、通用调用协议、输出格式、命令发现、业务文档导航和高频示例。详细业务说明、payload 字段、返回结构和示例维护在 `docs/commands/` 目录。

## npm 安装

推荐通过 npm 安装主包。主包会通过 optional dependencies 拉取当前平台对应的 Go 二进制包。

```powershell
npm install -g @ricequant2026/rqams-cli
rqamsc --version
rqamsc schema list
```

如果安装后提示缺少平台包，通常是 optional dependencies 被禁用，可以显式开启后重新安装：

```powershell
npm install -g @ricequant2026/rqams-cli --include=optional
```

## 通用调用

所有业务命令都通过 `--payload` 传入 JSON object：

```powershell
rqamsc auth --payload '{"base_url":"https://www.ricequant.com","username":"...","password":"..."}'
rqamsc <verb> <resource> --payload '{"field":"value"}'
```

payload 支持三种来源：

| 形式 | 示例 |
| --- | --- |
| inline JSON | `--payload '{"product_id_or_name":"..."}'` |
| 文件 | `--payload @payload.json` |
| 标准输入 | `--payload -` |

## 认证与 Workspace

首次安装后推荐先运行交互式配置：

```powershell
rqamsc setup
```

CLI 会提示输入 AMS 服务地址、用户名、密码，并在登录成功后列出可用 workspace 供选择。也可以继续使用 `auth` 和 `use workspace` 分步配置。运行 `auth` 会登录 RQAMS，并默认把密码和返回的 session 保存到本地配置。后续命令会复用该登录态；session 过期时，CLI 会用本地保存的密码自动重新登录并刷新 session。`username` 如果是 11 位中国大陆手机号，CLI 会自动补 `+86` 后登录并保存；已经包含区号、邮箱或普通用户名会保持原样：

```powershell
rqamsc auth --payload '{"base_url":"https://www.ricequant.com","username":"...","password":"..."}'
rqamsc get workspace-list --payload '{}'
rqamsc use workspace --payload '{"workspace_name_or_id":"default"}'
rqamsc get current-workspace --payload '{}'
```

单账号单 workspace 可以直接使用默认配置。单账号多 workspace 或多账号多 workspace 并行使用时，建议用 profile 隔离本地登录态和 workspace：

```powershell
rqamsc auth --payload '{"profile":"acct-a-w1","base_url":"https://www.ricequant.com","username":"...","password":"..."}'
rqamsc use workspace --payload '{"profile":"acct-a-w1","workspace_name_or_id":"workspace-a"}'
rqamsc get product-list --payload '{"profile":"acct-a-w1"}'
```

业务命令可以在 payload 顶层传 `profile`，共享同一个配置文件但使用互相隔离的 session 和 workspace。

## JSON Envelope

默认成功输出：

```json
{
  "ok": true,
  "command": "get product-list",
  "data": {},
  "metadata": {}
}
```

失败输出：

```json
{
  "ok": false,
  "command": "get product-list",
  "error": {
    "code": "runtime_error",
    "message": "..."
  }
}
```

常见 `error.code`：

| code | 说明 |
| --- | --- |
| `invalid_arguments` | 命令参数格式错误 |
| `invalid_payload` | payload 不是合法 JSON object，或字段类型不符合要求 |
| `config_error` | 本地配置、登录态或 workspace 配置错误 |
| `http_error` | 服务端请求错误 |
| `runtime_error` | 认证、网络、服务端业务或本地处理错误 |

## NDJSON

明确支持的列表命令可以在 payload 中传 `format:"ndjson"`：

```powershell
rqamsc get product-list --payload '{"fields":["id","name"],"format":"ndjson"}'
```

成功时每行输出一条 JSON 记录；失败时仍输出 JSON envelope，便于脚本和 Agent 统一识别错误。

## Schema

运行时 schema 是机器可读契约：

```powershell
rqamsc schema list
rqamsc schema get --payload '{"command":"get product-list"}'
```

`schema list` 返回当前 CLI 支持的命令和能力标记。`schema get` 返回单个命令的 payload guidance、字段级 `parameters`、`returns` 和示例。

## Agent 使用建议

列表查询时优先限制字段和数量：

```powershell
rqamsc get product-list --payload '{"fields":["id","name","start_date","label"],"limit":20,"format":"ndjson"}'
rqamsc get valuation-report-list --payload '{"product_id_or_name":"...","fields":["valuation_report_id","file_name","date"],"limit":20,"format":"ndjson"}'
```

已知 ID 时优先传 `*_id`。只有在不知道 ID 时再使用 `*_id_or_name`，避免同名资源导致解析歧义。

## 文件命令

上传统一推荐使用 `file_paths`，即使只有一个文件也传数组：

```powershell
rqamsc insert settlement-trade --payload '{"product_id_or_name":"...","account_name":"stock","file_paths":["D:/tmp/settlement.csv"]}'
rqamsc insert valuation-report --payload '{"product_id_or_name":"...","file_paths":["D:/tmp/valuation.xlsx"]}'
```

下载使用 `save_path`，返回保存路径，不直接把文件内容打印到 stdout：

```powershell
rqamsc get valuation-report-file --payload '{"product_id_or_name":"...","valuation_report_id":"...","save_path":"D:/tmp/reports","file_name":"valuation.xlsx"}'
rqamsc get weekly-net-value-report --payload '{"product_like_id_or_name":"...","save_path":"D:/tmp/reports","file_name":"weekly.xlsx"}'
```

## 命令发现

```powershell
rqamsc --help
rqamsc --version
rqamsc schema list
rqamsc schema get --payload '{"command":"get product-list"}'
```

`commands/` 文档用于解释命令语义、业务字段和常用工作流。

## 文档导航

| 业务文档 | 覆盖命令 |
| --- | --- |
| [认证与 Workspace](commands/auth_workspace.md) | `setup`, `auth`, `get workspace-list`, `use workspace`, `get current-workspace` |
| [市场数据](commands/market_data.md) | 交易日历等市场数据查询 |
| [产品与产品组](commands/products.md) | 产品、产品组查询/创建/更新/删除 |
| [权限分享](commands/permissions.md) | 产品和产品组权限查询、分享、修改、删除 |
| [交易流水](commands/trades.md) | 交易流水查询、插入、删除，交割单上传 |
| [头寸](commands/balance.md) | balance、balance series、asset snapshot、重算 |
| [估值表](commands/statements_and_valuation.md) | 估值表上传、下载、删除 |
| [托管事件与份额事件](commands/events.md) | custodian event、unit event |
| [自定义合约](commands/customized.md#get-customized-instrument-list) | 自定义合约查询、创建、更新、删除 |
| [自定义基准](commands/customized_benchmark.md#get-customized-benchmark-list) | 自定义基准查询、创建、更新、删除 |
| [自定义指标](commands/customized_indicator.md#get-customized-indicator) | 自定义指标查询、创建、更新、删除 |
| [指标与分析](commands/analysis.md) | 指标、投资概览、绩效归因、交易分析 |
| [模拟交易](commands/paper_trading.md) | paper trading 创建、信号、更新、删除、重算 |
| [对账](commands/reconciliation.md) | 对账列表、差异、统一更新 |
| [报告](commands/reports.md) | 周净值报告等下载类命令 |

## 高频示例

```powershell
rqamsc get product-list --payload '{"fields":["id","name","start_date","label"],"limit":20,"format":"ndjson"}'
rqamsc get trading-dates --payload '{"type":"exchange","start_date":"2026-01-01","end_date":"2026-01-31"}'
rqamsc get trade-list --payload '{"product_id_or_name":"...","start_date":"2026-01-01","end_date":"2026-01-31","limit":20}'
rqamsc insert valuation-report --payload '{"product_id_or_name":"...","file_paths":["D:/tmp/valuation.xlsx"]}'
rqamsc insert paper-trading --payload '{"template":"equity_long","name":"demo","benchmark":"index,000300.XSHG","start_date":"2026-01-01","init_amount":1000000,"algo":"open"}'
rqamsc get reconciliation-list --payload '{"product_ids_or_names":["..."],"start_date":"2026-01-01","end_date":"2026-01-31"}'
rqamsc get reconciliation-diff --payload '{"product_id_or_name":"...","date":"2026-01-31","fields":["positions","prices","payable","receivable","cash","net_asset"]}'
rqamsc update reconciliation --payload '{"product_id_or_name":"...","date":"2026-01-31","action":"mark","done":true,"description":"checked"}'
```
