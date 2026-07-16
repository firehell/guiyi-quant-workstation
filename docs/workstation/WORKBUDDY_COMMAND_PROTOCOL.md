# WorkBuddy Command Protocol

更新时间：2026-07-16

WorkBuddy 只能调用：

```bash
scripts/ai/workbuddy_task.sh <command> ...
```

## 固定命令

| 命令 | 作用 | 关键限制 |
|---|---|---|
| `analyze` | 只做 Issue/TASK 解析和 route | 不写入 |
| `bootstrap` | 调既有 Issue bootstrap | 不写 main |
| `plan` | dispatcher plan | 只读 |
| `approve` | 绑定用户审批 | 必须 `--confirm-user-approval` |
| `dev` | dispatcher dev | 不绕过 approval |
| `test` | dispatcher test | 不自动修复 |
| `review` | dispatcher review | 只读 |
| `result` | dispatcher result | 只汇总 |
| `delivery` | 生成交付输入 | 不宣称通过 |
| `status` | 只读状态 | 不改变状态 |
| `cancel` | 取消后续生命周期 | 不 reset、不删除文件 |
| `sync-pr` | 同步脱敏 PR 摘要 | 必须 `--confirm-github-write` |
| `record-external-review` | 记录真实外部 review | 不 approve、不 dismiss、不 merge |

## 示例

```bash
scripts/ai/workbuddy_task.sh analyze --issue #24
scripts/ai/workbuddy_task.sh plan --issue #24
scripts/ai/workbuddy_task.sh approve --issue #24 --confirm-user-approval
scripts/ai/workbuddy_task.sh dev --issue #24
scripts/ai/workbuddy_task.sh test --issue #24
scripts/ai/workbuddy_task.sh review --issue #24
scripts/ai/workbuddy_task.sh result --issue #24
scripts/ai/workbuddy_task.sh delivery --task DEMO-20260715-004-github-native-v3-final-acceptance
scripts/ai/workbuddy_task.sh sync-pr --task DEMO-20260715-004-github-native-v3-final-acceptance --pr 25 --confirm-github-write
```

## 不允许

- 任意 shell 参数；
- `eval`；
- 裸调 Codex；
- 直调 `codex_plan.sh` / `codex_dev.sh`；
- 一条命令自动串联多个 stage；
- 未确认 GitHub 写入。
