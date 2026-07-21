# WEB-V1-03：行情状态机与 URL 收口

```text
WEB_MARKET_STATE_MACHINE_READY
WEB_MARKET_LINEAGE_FAIL_CLOSED
```

## 目标

行情列表与 K 线工作台的状态切换、URL deep-link、Research fail-closed、错误脱敏与 loading 竞态防护。

## 变更摘要

| 区域 | 内容 |
|---|---|
| `market/index.vue` | 明确「查看 K 线」按钮；搜索/交易所带标签；主连文案改为「研究连续序列/回测上下文」 |
| `market/chart.vue` | `syncQuery` 完整保存 symbol/contract/period/contract_view/access_mode/profile_id/data_mode 及 deep-link；Historical/Live 切换清不兼容状态；Research 缺 Profile fail-closed；`toSafeApiError` 脱敏 |
| `utils/marketChartQuery.ts` | 纯函数：route query 构建、Research Profile 校验、EMA 技术观察文案、质量 failed 文案 |
| `tests/marketStateMachine.test.ts` | route query / fail-closed / 错误脱敏 |

## 状态转换表

| 当前状态 | 触发 | 下一状态 | 清理/守卫 |
|---|---|---|---|
| historical + browser | 切 Live | live + browser | 清 profile/access research、清 bars/lineage/indicators、coverage 重置；不支持 period 回退分钟周期 |
| live | 切 historical | historical + browser | 清 live 质量态；dateRange 重置 |
| historical + browser | 切 research | historical + research | 无 profile → fail-closed，不请求 bars/coverage |
| historical + research | 选 profile | historical + research + profile | 重新 load coverage/bars |
| 任意 | loading 中 | — | 禁用 mode/period/profile/刷新等会产生竞争请求的控件 |
| bars merge | lineage_token 冲突 | 错误态 | `BarMergeConflictError` fail-closed，拒绝覆盖 |
| EMA 指标 | lineage 与 bars 不一致 | 错误态 | 清空 mainIndicatorSeries，提示 reload |

## Gate 验收

### WEB_MARKET_STATE_MACHINE_READY

- [ ] 列表页单击「查看 K 线」可跳转 chart，URL 含 symbol/contract/period
- [ ] chart `syncQuery` 保留 report_id/trade_no/time 等 deep-link
- [ ] Historical ↔ Live 切换后旧 lineage/bars 不残留
- [ ] loading 期间 mode/period/profile/刷新不可重复触发请求
- [ ] `npm test` 中 `marketStateMachine.test.ts` 通过

### WEB_MARKET_LINEAGE_FAIL_CLOSED

- [ ] merge bars 时 lineage_token 不一致拒绝覆盖
- [ ] EMA/MACD 与 bars lineage 不一致时报错并清空序列
- [ ] 质量 failed 文案不含 `file_path` 或绝对路径

## 测试

```bash
cd apps/quant-web && npm test && npm run build
```
