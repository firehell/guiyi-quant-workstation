# GPT Project Sources

更新时间：2026-07-14

本目录保留浏览器 GPT 临时审查包、历史交换说明和 manifest。当前唯一 GPT 项目同步入口已经迁到根目录 `project_sources/`；仓库 canonical 仍是根目录 summary 文件和 `docs/` deep canonical 文件。

## 推荐读取顺序

1. `../../project_sources/00-INDEX.md`
2. `PROJECT_SOURCE_MANIFEST.md`
3. `../../PROJECT_SOURCE.md`
4. `../../STATUS.md`
5. `../../CODEX_TASKS.md`

## 当前结论

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

不要使用旧聊天或旧 `docs/gpt` 摘要覆盖当前事实。若本目录和 `PROJECT_SOURCE.md`、`STATUS.md`、`docs/DATA_CENTER.md` 冲突，以 canonical 文件为准。

## 文件说明

- `CURRENT_STATE.md`：给 GPT 的当前状态速览。
- `NEXT_STEPS.md`：下一步任务和上传建议。
- `PROJECT_SNAPSHOT.md`：当前架构/功能快照。
- `DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`：数据阶段收口审查包。
- `../../project_sources/`：新的精简 GPT Project Sources。
- `PROJECT_SOURCE_MANIFEST.md`：推荐上传文件清单与敏感信息检查状态。

## 敏感信息规则

本目录不得包含真实 webhook、token、password、cookie、license、账号或连接串。允许出现环境变量名和安全规则说明。
