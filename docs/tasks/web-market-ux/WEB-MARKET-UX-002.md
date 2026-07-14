# WEB-MARKET-UX-002：1d 重复 K 只读诊断

生成时间：2026-07-14

状态：`READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND`

## 目标

在 `WEB-MARKET-UX-001 GATE_PASSED` 后，只读诊断 Web 品种行情页 `JM 1d` 是否存在重复 K，并定位重复最早出现层。

## 边界

本任务只读：

- 不修改代码。
- 不写 DB、Parquet、manifest、checksum 或 quality status。
- 不调用 RQData 下载。
- 不修复根因。

本次使用当前 worktree 本地服务：

- API：`http://127.0.0.1:8010`
- Web：`http://127.0.0.1:5174`

说明：默认 `8000/5173` 被 `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` 常驻 runtime 占用并自动重启，因此 A01/A02 当前 worktree smoke 使用替代端口。

## 分层取证

### 1. API 层

Web 实际切换 `1d` 时使用主连请求：

```text
GET /api/v1/market/bars?symbol=jm&contract=jm.MAIN&period=1d&provider=rqdata&data_role=primary&quote_mode=false&allow_continuous=true&start=2013-03-22&end=2026-07-10&tail=true&limit=10000
```

结果：

| case | response_count | unique_time | unique_trading_day | unique_chart_key | duplicate_samples | quality |
|---|---:|---:|---:|---:|---|---|
| `jm.MAIN 1d` | 3231 | 3231 | 3231 | 3231 | none | `unchecked`, `cross_file_conflicts=0` |
| `JM2609 1d quote_mode` | 76 | 76 | 76 | 76 | none | `warning`, `cross_file_conflicts=10` |

样本：

| case | first | last |
|---|---|---|
| `jm.MAIN 1d` | `2013-03-22T00:00:00 / trading_day=2013-03-22 / close=1237` | `2026-07-10T00:00:00 / trading_day=2026-07-10 / close=1257.5` |
| `JM2609 1d quote_mode` | `2026-04-01T15:00:00 / trading_day=2026-04-01 / close=1252` | `2026-07-07T15:00:00 / trading_day=2026-07-07 / close=1273` |

结论：

- API response 层未发现重复 `time`、重复 `trading_day` 或重复 daily chart key。
- Web 实际 `1d` 图表使用的 `jm.MAIN 1d` 无 cross-file conflict。
- 真实合约 `JM2609 1d quote_mode=true` 返回去重后的 76 根 K，但 quality 明确提示 `cross_file_conflicts=10`，属于历史事实冲突 warning，不应静默当作普通 passed。

`JM2609 1d quote_mode=true` conflict 样本：

| dedupe_key | conflicting_fields | file_count |
|---|---|---:|
| `2026-04-20` | `open, low, volume` | 2 |
| `2026-04-27` | `open, low, volume` | 2 |
| `2026-05-11` | `open, low, volume` | 2 |
| `2026-05-18` | `open, volume` | 2 |
| `2026-05-25` | `open, low, volume` | 2 |
| `2026-06-01` | `open, low, volume` | 2 |
| `2026-06-08` | `open, high, volume` | 2 |
| `2026-06-15` | `open, volume` | 2 |
| `2026-06-29` | `open, low, volume` | 2 |
| `2026-07-06` | `open, low, volume` | 2 |

### 2. Web normalize 层

使用现有 helper：

```ts
dedupeBarsByPeriod(bars, '1d')
chartLookupKeyForBar(bar, '1d')
```

结果：

| case | input_count | dedupe_count | duplicate_chart_key |
|---|---:|---:|---|
| `jm.MAIN 1d` | 3231 | 3231 | none |
| `JM2609 1d quote_mode` | 76 | 76 | none |

结论：Web normalize 层未引入或发现重复。

### 3. Web merge 层

使用现有 helper：

```ts
mergeBarsByPeriod(bars, bars, '1d')
```

结果：

| case | merge_self_count |
|---|---:|
| `jm.MAIN 1d` | 3231 |
| `JM2609 1d quote_mode` | 76 |

结论：Web merge helper 按 daily chart key 合并后仍唯一，未复现 merge 引入重复。

### 4. 图表层

Playwright 页面：

```text
http://127.0.0.1:5174/market/chart?symbol=jm&contract=JM2609&period=1d
```

页面证据：

- 右侧显示 `K线数量 3,231`。
- 周期/质量显示 `1d / passed`。
- hover strip 示例：`2026-07-10 开1,286.00 高1,290.00 低1,249.50 收1,257.50 量804,703 持仓454,057 EMA21 1,286.20`。
- Network：`bars jm.MAIN 1d`、EMA21 indicators、MACD 均返回 `200`。
- Console：`0 errors / 0 warnings`。

截图：

```text
output/playwright/web-market-ux/WEB-MARKET-UX-002/current-1d-chart.png
```

## 结论

```text
WEB-MARKET-UX-002 READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND
```

本轮只读诊断没有在 Web 实际 `1d` 图表链路复现重复 K：

- `jm.MAIN 1d` API response 无重复。
- Web normalize 无重复。
- Web merge 无重复。
- 图表层显示 `K线数量 3,231`，Network 200，console 0 warning/error。

但真实合约 `JM2609 1d quote_mode=true` 存在 `cross_file_conflicts=10` 的只读 warning。该 warning 表示历史事实源中同一 daily key 有跨文件 OHLCV 冲突样本，只是 API response 已按 daily key 输出为唯一 K。

## A03 判断

当前不建议直接进入前端 A03 修复，因为 Web 实际 `jm.MAIN 1d` 图表重复 K 未复现。

如果后续要处理 `JM2609 1d quote_mode=true` 的 10 个 cross-file conflicts，A03 必须先 `REPLAN` 为数据事实冲突只读审查或数据侧修复任务；不得在 Web 层用静默去重掩盖。

若后续重新发现重复 K，需要先补充至少一项复现输入：

- 具体 URL query。
- 截图中的重复日期或重复 K 所在区间。
- Network response 对应 request URL。
- 是否使用默认 `8000/5173` 常驻 runtime，或当前 worktree `8010/5174`。

在获得 Web 图表重复复现样本前，前端 A03 最小修复范围为 `none / wait for reproducible evidence`。
