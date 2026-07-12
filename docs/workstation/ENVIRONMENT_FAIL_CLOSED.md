# 工作站环境 Fail-Closed 检查

## 目标

工作站 TASK 执行前必须先确认环境变量、挂载点、worktree、分支和基础命令可用。检查只验证“是否存在”，不输出 `.env` 内容、数据库连接串、token、license 或 webhook。

## TASK 字段

在 `## 0. 元信息` 中声明：

```markdown
| Required Env | `DATABASE_URL`, `POSTGRES_PASSWORD` |
| Required Mounts | `/Volumes/扩展盘` |
```

未声明时保持兼容，不因为业务凭据缺失阻断历史 TASK。声明后缺失即失败。

## 环境检查

```bash
scripts/env/check_task_env.sh --task <TASK_ID> --stage plan --json
```

常用参数：

- `--quiet`：只返回退出码。
- `--output .ai/results/<TASK_ID>/env_check.json`：写入脱敏 JSON。
- `--worktree <path>`：覆盖 TASK 中的 Worktree。

失败规则：

- `Required Env` 缺失即失败，只输出变量名。
- `Required Mounts` 必须已存在且是挂载点；脚本不会 `mkdir`。
- `plan/dev/fix/review` 会检查 `codex`，基础检查会检查 `git`、`python3` 和仓库所需包管理器。
- worktree 或 branch 与 TASK 不一致即失败。

`dispatch_task.sh` 会在真实执行子命令前自动调用该检查；`route` 和 `--dry-run` 不阻断。

## Worktree Env Bootstrap

默认 dry-run：

```bash
export GUIYI_ENV_SOURCE=/absolute/path/to/safe/project.env
scripts/env/bootstrap_worktree_env.sh --worktree <worktree>
```

实际创建符号链接：

```bash
scripts/env/bootstrap_worktree_env.sh --worktree <worktree> --apply
```

安全规则：

- 不把生产 `.env` 复制进仓库。
- 源文件不存在时失败。
- 目标 `.env` 已存在时默认拒绝。
- `--replace-link` 只允许替换已有符号链接，不覆盖普通文件。
- 不打印文件内容。
- `APP_ENV=production` 的进程环境必须显式 `--confirm-production`，脚本不会自动解锁生产配置。

## 示例配置

`configs/env/worktree.env.example` 只提供键名和占位符。真实文件应放在仓库外，并通过 `GUIYI_ENV_SOURCE` 指向。

## 禁止行为

- 禁止自动创建 `data/raw/`、`data/parquet/`、`data/processed/` 或外置盘根目录。
- 禁止把凭据写入 `.ai/results/`。
- 禁止在 `DATABASE_URL` 缺失时静默切换在线 API snapshot，除非 TASK 明确允许并在结果中记录。
