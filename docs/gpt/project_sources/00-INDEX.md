# GPT Project Sources Index

更新时间：2026-07-14

事实来源：`PROJECT_SOURCE.md`、`STATUS.md`、`CODEX_TASKS.md`、`docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/CODEX_HANDOFF.md`

当前 commit：`ec7a698e414c7d957e171f11c6aa9a6575de7e1d`

## 总体状态

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口，不等于数据层最终封板完成。

## 推荐读取顺序

1. `01-PROJECT-SOURCE.md`
2. `02-CURRENT-STATUS.md`
3. `04-DATA-LAYER.md`
4. `07-BACKTEST.md`
5. `08-SIGNAL-NOTIFICATION.md`
6. `09-LIVE-RUNTIME-DEPLOYMENT.md`
7. `13-NEXT-STEPS.md`

## 文件用途

| 文件 | 用途 |
|---|---|
| `01-PROJECT-SOURCE.md` | 项目定位、边界、主链路 |
| `02-CURRENT-STATUS.md` | 当前完成度与不可宣称状态 |
| `03-ARCHITECTURE.md` | 系统架构和分层 |
| `04-DATA-LAYER.md` | 数据层口径、Phase 3 指标和阻塞项 |
| `05-INDICATOR-STRATEGY-KERNEL.md` | 指标/策略内核状态 |
| `06-WEB.md` | Web 页面与功能状态 |
| `07-BACKTEST.md` | 回测链路和 trust audit 边界 |
| `08-SIGNAL-NOTIFICATION.md` | 信号事件和企业微信边界 |
| `09-LIVE-RUNTIME-DEPLOYMENT.md` | live runtime、launchd、公网部署状态 |
| `10-WORKSTATION-WORKFLOW.md` | WorkBuddy/CodeBuddy/Codex/Cursor 协作 |
| `11-DECISIONS.md` | 架构决策摘要 |
| `12-TESTING-AND-GATES.md` | 测试和 Gate 命令 |
| `13-NEXT-STEPS.md` | 下一步任务 |

## 当前最重要阻塞项

- `metadata_gap=1853` manifest / DB 对齐。
- pre-2020 周线仍有 34 个品种缺口或需 N/A 口径确认。
- actual contract 缺口仍需专项处理。
- T3-real 单次 live 写入 Gate 未通过。
- `JM_RUNTIME_READY` / `LONG_RUNNING_READY` 未达成。
- 真实公网 TLS / Basic Auth / 端口封闭 / 重启恢复 smoke 未完成。
- OOS / walk-forward 未完成。
- 企业微信 historical replay smoke 不等于 live-confirmed 或长期发送验收。

## 代码完成 vs 真实 Gate

| 事项 | 当前状态 |
|---|---|
| 数据中心与读取边界 | 代码具备；最终数据层仍 `DATA_LAYER_PARTIAL` |
| 回测 trust audit | `report_id=14` passed；不代表盈利或实盘 |
| Signal / WeCom | preview、send-once、retry 框架具备；长期发送 Gate pending |
| live runtime | 代码/模板具备；T3-real 和长稳 pending |
| 公网部署 | 模板具备；远端 smoke pending |

