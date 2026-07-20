# Codex Profiles

本文说明归一量化工作站的 Codex CLI profile 模板、安装方式和权限边界。

## 目标

模型名称集中维护在仓库模板中，不散落在 WorkBuddy Prompt、CodeBuddy 脚本或 TASK 正文里。

模板位置：

```text
config/codex/profiles/
```

当前模板：

| Profile | Model | Reasoning |
|---|---|---|
| `guiyi-fast` | 见模板文件 | `low` |
| `guiyi-standard` | 见模板文件 | `medium` |
| `guiyi-deep` | 见模板文件 | `high` |
| `guiyi-critical` | 见模板文件 | `xhigh` |

## 权限边界

Profile 只配置模型与推理参数。

Profile 不配置：

- sandbox 模式。
- approval policy。
- production 权限。
- push、merge、deploy 权限。
- 数据库写入权限。
- 交易执行权限。
- 任何认证配置。

阶段权限仍由 `scripts/ai/route_task.sh` / `scripts/ai/lib/route_task.py` 和后续 dispatch 显式决定。当前路由策略见 `docs/workstation/ROUTING_POLICY.md`。

## 安装

默认安装目标：

```bash
${CODEX_HOME:-$HOME/.codex}
```

预演安装，不写文件：

```bash
scripts/ai/install_codex_profiles.sh --dry-run
```

正式安装或更新：

```bash
scripts/ai/install_codex_profiles.sh --backup-and-install
```

验证模板和已安装文件一致：

```bash
scripts/ai/install_codex_profiles.sh --verify
```

脚本默认拒绝覆盖同名文件。使用 `--backup-and-install` 时，会先生成带时间戳的备份文件，再安装仓库模板。

## 临时目录验证

开发和测试时必须使用临时 `CODEX_HOME`：

```bash
tmp_home="$(mktemp -d)"
CODEX_HOME="$tmp_home" scripts/ai/install_codex_profiles.sh
CODEX_HOME="$tmp_home" scripts/ai/install_codex_profiles.sh --verify
```

不要在自动测试中写入真实 `~/.codex`。

## 与路由器的关系

`route_task` 只输出 profile 名称和阶段权限建议，不安装 profile，也不调用模型。

示例：

```bash
scripts/ai/route_task.sh docs/tasks/<TASK_ID>.md plan --json
```

输出中的 `profile` 可作为 Codex CLI 的 `--profile` 名称；实际执行时仍必须显式传入对应阶段的 sandbox 和 approval 选项。
