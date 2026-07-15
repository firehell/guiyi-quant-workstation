# GPT Project Sources Index

更新时间：2026-07-14

本目录是浏览器 GPT 的唯一项目同步入口。`docs/gpt/` 仅保留临时审查包、manifest 和历史交换说明；长期项目事实、当前状态、路线、决策、测试入口和模块边界统一从本目录读取。

事实来源：`PROJECT_SOURCE.md`、`STATUS.md`、`CODEX_TASKS.md`、`TESTING.md`、`DECISIONS.md`、`docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/CODEX_HANDOFF.md`

当前基线 commit：`570dc66524e490f1b00e96802b65772bb41a77ee`

最近一次文档入口审计：2026-07-14

## 总体状态

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口，不等于数据层最终封板完成。

## 推荐读取顺序

1. `01-PROJECT_SOURCE.md`
2. `02-CURRENT_STATUS.md`
3. `03-V1_ROADMAP.md`
4. `04-ARCHITECTURE.md`
5. `06-NEXT_STEPS.md`
6. `modules/DATA_CENTER.md`
7. `modules/BACKTEST_ENGINE.md`
8. `modules/SIGNAL_EVENTS.md`
9. `modules/LIVE_RUNTIME.md`

## 文件用途

| 文件 | 用途 |
|---|---|
| `00-INDEX.md` | GPT 阅读入口、上传组合、文档职责和冲突优先级 |
| `01-PROJECT_SOURCE.md` | 项目定位、V1 边界、主链路和不可突破原则 |
| `02-CURRENT_STATUS.md` | 当前完成度、未完成 Gate、不可宣称状态 |
| `03-V1_ROADMAP.md` | V1 / V1-B 路线、阶段边界和当前 Gate |
| `04-ARCHITECTURE.md` | 稳定系统架构和依赖方向 |
| `05-DECISIONS.md` | 已确认架构决策摘要 |
| `06-NEXT_STEPS.md` | 下一步任务和优先顺序 |
| `07-TESTING.md` | 测试入口和 Gate 命令 |
| `modules/DATA_CENTER.md` | 数据层口径、Phase 3 指标和阻塞项 |
| `modules/INDICATOR_KERNEL.md` | 指标/策略内核状态 |
| `modules/BACKTEST_ENGINE.md` | 回测链路和 trust audit 边界 |
| `modules/SIGNAL_EVENTS.md` | 信号事件和企业微信边界 |
| `modules/LIVE_RUNTIME.md` | live runtime、launchd、公网部署状态 |
| `modules/WEB.md` | Web 页面与功能状态 |
| `modules/WORKSTATION_WORKFLOW.md` | WorkBuddy/CodeBuddy/Codex/Cursor 协作 |

## 推荐上传组合

完整同步：

- `project_sources/*.md`
- `project_sources/modules/*.md`

专项审查：

- 数据：追加 `docs/DATA_CENTER.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`
- 回测：追加 `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- 信号/企业微信：追加 `docs/SIGNAL_EVENTS.md`、`docs/STAGE9_WECHAT_DELIVERY.md`
- live/runtime：追加 `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- 工作站协作：追加 `docs/workstation/`、`docs/workflows/`

## 冲突优先级

1. 当前代码与可重复测试结果。
2. 根目录 canonical：`PROJECT_SOURCE.md`、`STATUS.md`、`DECISIONS.md`、`CODEX_TASKS.md`、`TESTING.md`。
3. `docs/` deep canonical：数据、架构、回测、信号、交接文档。
4. 本目录摘要。
5. `docs/gpt/` 临时审查包、旧 Prompt、历史快照。

如果高优先级事实冲突，不要拼接结论；应列为人工确认项。

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

## 生成清单命令

```bash
git ls-files 'project_sources/*.md' 'project_sources/modules/*.md' | sort
```
