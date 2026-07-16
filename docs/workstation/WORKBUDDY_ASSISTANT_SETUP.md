# WorkBuddy Assistant / 企业微信远程 Smoke 设置

更新时间：2026-07-16

本文定义 WorkBuddy Assistant 在 Mac mini / 企业微信远程入口中的最小无害 Smoke。目标是确认助理能定位正确仓库并通过 WorkBuddy facade bootstrap 独立 TASK worktree，而不是在 `main`、助理固定目录、数据目录、`.env` 或生产目录写代码。

## 1. 前置条件

1. Mac mini 已开机。
2. WorkBuddy Assistant 已运行。
3. 使用 WorkBuddy 默认权限；不要为 Smoke 额外申请 Full Disk Access、生产目录权限、数据目录权限或凭据读取权限。
4. 助理固定目录只是 WorkBuddy 的运行/会话目录，不是项目 worktree，不得在其中保存业务代码、TASK 产物、diff、日志或数据样本。
5. 手机 / 企业微信只发送固定命令和 Issue 编号，不上传完整 TASK、完整 diff、完整 log、数据文件或凭据。

## 2. 固定仓库定位

WorkBuddy Assistant 收到任何远程命令后，必须先定位项目仓库：

```text
/Volumes/扩展盘/guiyi-quant-workstation
```

定位后先返回只读环境信息：

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
```

要求：

- `git rev-parse --show-toplevel` 必须等于 `/Volumes/扩展盘/guiyi-quant-workstation`。
- 如果当前目录是 WorkBuddy Assistant 固定目录，必须先切换到项目仓库再执行仓库命令。
- 如果仓库路径不存在、不可读或不是 Git repository，立即停止。

## 3. Bootstrap 独立 worktree

远程执行不得在 `main` 上写代码。WorkBuddy Assistant 只能在定位正确仓库后调用：

```bash
scripts/ai/workbuddy_task.sh bootstrap --issue N --json
```

其中 `N` 是数字 Issue 编号，不带自由 shell、不拼接额外命令。

Bootstrap 预期：

- 解析 Issue / TASK / PR。
- 创建或定位 TASK 专用 worktree。
- 后续 Plan / Dev / Test / Review / Result 只在 TASK worktree 执行。
- 不在 `main` worktree 修改 tracked files。
- 不在 WorkBuddy Assistant 固定目录写业务文件。

## 4. 禁止访问和写入边界

Smoke 期间：

- `main` 只能只读定位，不作为写入 worktree。简写规则：main 只能只读定位。
- `data/**` 不得读取样本、复制、上传或写入。
- `.env`、`.env.*`、token、webhook、cookie、license、账号和密码不得读取、打印、上传或写入。
- 生产目录、部署目录、真实通知和真实交易相关目录不得作为工作目录或写入目标。
- 不允许自动 push、merge、deploy、close Issue、删除 branch 或删除 worktree。

## 5. 手机 / 企业微信只读 Smoke 命令

手机或企业微信只发送：

```text
STATUS #<DEMO_ISSUE>
ANALYZE #<DEMO_ISSUE>
```

禁止发送：

- 完整 TASK 正文；
- 完整 diff；
- 完整 log；
- 数据文件或截图中的敏感路径；
- `.env`、凭据、webhook、token、cookie 或 license；
- 任意 shell 命令。

## 6. 预期返回字段

WorkBuddy Assistant 对 `STATUS` / `ANALYZE` 必须返回脱敏摘要：

| 字段 | 要求 |
|---|---|
| repo root | `/Volumes/扩展盘/guiyi-quant-workstation` |
| current branch | 当前 Git branch |
| Issue / TASK / PR | 与 GitHub 一致；缺失时写 `NOT_FOUND` 并停止 |
| worktree | TASK worktree 路径；未创建时写 `NOT_CREATED` |
| current Gate | 当前 Gate / stage |
| result/log path | `.ai/results/<TASK_ID>/...` 路径，不粘贴完整日志 |
| file changes | 是否有文件变更；只返回 summary |

## 7. 失败处理

任一条件失败必须立即停止。简写规则：失败立即停止。

- 找不到 `/Volumes/扩展盘/guiyi-quant-workstation`。
- 当前目录不是项目仓库。
- Issue 编号不是数字。
- Issue / TASK / PR 与 GitHub 不一致。
- bootstrap 未能创建或定位独立 TASK worktree。
- 检测到将要在 `main`、WorkBuddy Assistant 固定目录、`data/**`、`.env*` 或生产目录写入。
- 命令不是固定 `STATUS #N`、`ANALYZE #N` 或受控 `workbuddy_task.sh` 子命令。

失败返回必须包含：

```text
Issue:
TASK:
PR:
stage:
Gate:
tests:
risks:
next_action:
```

不得自动 retry，不得 fallback 到其他仓库或目录。
