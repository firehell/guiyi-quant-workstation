# 报告 API

报告下载命令只把文件保存到本地路径，stdout 返回保存结果，不输出文件内容。

产品和产品组统一使用 `product_like_id_or_name` 定位。该字段可以传产品 ID、产品名称、产品组 ID 或产品组名称，CLI 会解析后请求对应接口。

## `get weekly-net-value-report`

下载产品或产品组周净值报告。

Payload:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `product_like_id_or_name` | string | 是 | 产品或产品组 ID/名称 |
| `save_path` | string | 是 | 保存目录或保存文件路径 |
| `file_name` | string | 否 | 保存文件名；不传时由 CLI 按资源 ID 生成 |
| `start_date` | string/date | 否 | 起始日期 |
| `end_date` | string/date | 否 | 结束日期 |

返回：`data.path` 为保存后的本地文件路径，`data.content_type` 和 `data.bytes` 分别为响应内容类型和写入字节数。

示例：

```powershell
rqamsc get weekly-net-value-report --payload '{"product_like_id_or_name":"demo","start_date":"2026-01-01","end_date":"2026-01-31","save_path":"D:/tmp/reports","file_name":"weekly.xlsx"}'
```
