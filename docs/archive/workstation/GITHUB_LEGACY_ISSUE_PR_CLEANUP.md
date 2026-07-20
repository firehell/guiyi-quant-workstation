# GitHub Legacy Issue / PR Cleanup Suggestions

更新时间：2026-07-20

> **只建议，不自动关闭。** 由用户在 GitHub 上手动处理。

## 背景

工作站控制面已精简为 GitHub + GPT + Codex。旧 WorkBuddy Demo、控制面修复 Issue / Draft PR 若仍 open，建议归档或关闭并注明 superseded。

## 建议处理清单（人工）

| 类型 | 建议动作 | 备注 |
|---|---|---|
| WorkBuddy Demo Issue / Draft PR（如历史 #27 / #28） | Close with comment: superseded by `WORKSTATION_SIMPLIFIED` | 不阻塞业务 |
| 控制面修复类已合并 Issue | Close if still open；链接本精简 PR | 代码已不在 dispatcher 路径 |
| 仍引用 `dispatch_task.sh` / `workbuddy_task.sh` 的 open Issue | 编辑描述指向 `docs/DEVELOPMENT.md` + `scripts/engineering/*` | 或 close as obsolete |
| Labels：`workbuddy` / `dispatcher` / L0L1L2 | 可保留历史；新 Issue 不再强制 | 可选清理 |

## 关闭评论模板

```text
Superseded by workstation simplification (WS-SIMPLIFY).
Formal entrypoints: scripts/engineering/* and docs/DEVELOPMENT.md.
WorkBuddy/dispatcher are no longer part of the active architecture.
No automatic merge/deploy was performed.
```

## 不做

- 不自动 `gh issue close`
- 不自动 merge PR
- 不删除 GitHub 历史评论
