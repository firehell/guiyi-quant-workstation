# V1 Live Runtime Closure Acceptance

更新时间：2026-07-10

## 结论

JM-only 实时观察闭环的代码、单元/集成测试、默认关闭开关和监督模板已实现。真实数据写入、真实通知、长期运行和腾讯云验收尚未执行，因此当前只能标记为：

```text
CODE_COMPLETE_EXTERNAL_GATES_PENDING
```

不得标记为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY` 或 `FULL_UNIVERSE_READY`。

## 状态矩阵

| 子系统 | 代码与测试 | 单次真实 smoke | 长期运行 | 当前结论 |
|---|---|---|---|---|
| runtime health | 已完成 | 不涉及写入 | 未恢复全部受监督服务 | code ready |
| 交易时钟/scheduler | 已完成 | 未执行 | 未执行 | default-off |
| 1m ingest | 既有实现+回归 | 未执行 | 未执行 | gated |
| 5m/15m/30m/60m/1d/1w | 已完成 | 未执行 | 未执行 | gated |
| after-market archive | 已完成 | 未执行 | 未执行 | gated |
| live signal event | 已完成 | 未执行 | 未执行 | gated |
| notification worker | 已完成 | 未执行 live event send | 未执行 | gated |
| launchd/日志轮转 | 模板/语法完成 | 未加载 | 未执行 | config only |
| 腾讯云 | 验收脚本完成 | 未执行 | 未执行 | external gate |
| 全品种 | 既有 Gate 测试完成 | 不适用 | 未扩 realtime | 82/90 |

历史 Stage 9-B2 的一次企业微信成功发送是 historical replay smoke，不是 live event smoke，也不是 worker/scheduler 长期能力证据。

## 关键实现

- `TradingSessionClock`：DCE 夜盘跨自然日、午休、周末/节假日、收盘 grace、周最后交易日。
- `runtime_scheduler`：单 APScheduler、Redis singleton lock、`max_instances=1`、coalesce、misfire grace、heartbeat。
- `LiveMultiTfAggregationService`：session-window 分桶，confirmed 日/周线，partial/missing 只给 warning。
- `AfterMarketArchiveService`：`archive:<product>:<contract>:<trading_day>` 幂等任务号，RQData after-market direct 为主，live rows 只作 reference。
- `LiveSignalEventService`：严格 actual-contract/passed/confirmed/5m/15m Gate；same bar 幂等，revision 追加 changed event。
- `NotificationDispatchService`：只选 live-confirmed event，历史 replay 自动排除；独立 queue/worker 才读取 webhook。
- runtime health：每个期望 queue worker coverage、scheduler heartbeat、checkpoint freshness、archive task、notification retry。

## 默认关闭与安全边界

`.env.example` 中四个写/发送开关全部为 false。dry-run 不打开 DB/Redis/RQData，也不写 parquet 或 signal/notification。

不新增写操作 HTTP API，不增加远程发送按钮，不实现订单、账户或自动下单。

## 已执行命令

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant

bash -n scripts/*.sh
for f in deploy/launchd/*.plist.template; do plutil -lint "$f"; done
git diff --check
```

结果：backend `361 passed`；frontend Node `27 passed`；frontend production build 通过；其余全部通过。Vite 仍报告既有单 chunk 大于 500 kB 的非阻断 warning。

## 后续真实 Gate 顺序

1. T1-ops：仅恢复 API/Web/backtest/signal worker，验证每 queue worker coverage、kill 自动恢复及严格 health。
2. T3-real：临时只开 `GUIYI_LIVE_RUNTIME_ENABLED`，人工执行 JM 单次真实写入、全周期聚合和一次重启恢复。
3. T4-real：单独开启 archive flag，完成一个已收盘交易日归档；重复运行不得重复资产。
4. T5-real：单独开启 live event flag，验证 same bar 幂等和 revision changed event；仍不发送。
5. T6-real：最后开启 autosend，单条 live-confirmed event 发送；验证 3 次上限与脱敏。
6. T7：5 个交易日长稳与故障注入；随后执行腾讯云真实域名验收。
7. T8：historical active 90/90 后，再逐批扩 actual-contract realtime allow-list。

每一步只解除本步开关，不允许一次性开启全部功能。

## 长稳验收清单

- 覆盖至少 5 个交易日和至少一个夜盘。
- scheduler/worker kill 后 launchd 恢复。
- Mac 重启后 checkpoint 续跑。
- 断网、Redis/PostgreSQL 短暂失败、RQData 异常后无漏 bar、重复 event 或重复提醒。
- runtime health 无假绿，stale/failed/retry due 可见。
- 日/周线只在合法收盘条件后 confirmed。
- live DB 未登记为 historical active。

## 腾讯云验收命令

```bash
PUBLIC_BASE_URL=https://<domain> ./scripts/public-healthcheck.sh
BASIC_AUTH_USER=<user> BASIC_AUTH_PASS=<pass> \
PUBLIC_BASE_URL=https://<domain> ./scripts/public-healthcheck.sh
```

必须同时验证：HTTP→HTTPS、未认证 401、认证 Web/API 200、WS 101、5432/6379/8000/5173/18000/18080 公网关闭、FRPS control port 限制来源和重启恢复。

## 尚未通过的最终标准

- `JM_RUNTIME_READY`：需 T1–T7 真实 Gate 全通过。
- `FULL_UNIVERSE_READY`：需 historical active 90/90 且 realtime actual-contract entry periods 逐品种通过。
- `LONG_RUNNING_READY`：需 5 个交易日长稳和真实公网 smoke 均通过。
