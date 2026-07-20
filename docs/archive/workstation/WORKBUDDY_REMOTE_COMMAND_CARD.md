# WorkBuddy 手机 / 企业微信远程命令卡

更新时间：2026-07-16

用途：给手机或企业微信端发送最小固定命令，验证 WorkBuddy Assistant 能定位仓库、解析 Issue，并准备 TASK worktree。手机端不发送完整 TASK、diff、log、数据或凭据。

## 只读 Smoke

将 `<DEMO_ISSUE>` 替换为数字 Issue 编号：

```text
STATUS #<DEMO_ISSUE>
ANALYZE #<DEMO_ISSUE>
```

这两个命令必须是只读 Smoke：

- 不进入 Dev。
- 不修改 `main`。
- 不写 WorkBuddy Assistant 固定目录。
- 不读取或上传 `data/**`、`.env*`、凭据、生产目录。
- 不要求用户复制完整文件。

## Bootstrap 命令

如果只读 Smoke 返回 Issue / TASK / PR 一致，并且用户确认继续，WorkBuddy Assistant 才能在仓库根目录调用：

```bash
scripts/ai/workbuddy_task.sh bootstrap --issue N --json
```

要求：

- 先定位仓库：`/Volumes/扩展盘/guiyi-quant-workstation`。
- `N` 必须是数字 Issue 编号。简写规则：N 必须是数字 Issue 编号。
- bootstrap 只负责创建或定位独立 TASK worktree。
- 后续执行只在 TASK worktree 中进行。
- 任一失败立即停止。

## 预期返回

每次 `STATUS` / `ANALYZE` 返回必须包含：

```text
repo root:
current branch:
Issue:
TASK:
PR:
worktree:
current Gate:
result/log path:
file changes:
```

字段要求：

- `repo root` 必须是 `/Volumes/扩展盘/guiyi-quant-workstation`。
- `Issue / TASK / PR` 必须与 GitHub 一致；未知则写 `NOT_FOUND`。
- `worktree` 必须是 TASK worktree；未知则写 `NOT_CREATED`。
- `result/log path` 只返回路径，不粘贴完整日志。
- `file changes` 只返回是否有变更和 summary，不粘贴完整 diff。

## 禁止发送

手机 / 企业微信不要发送：

- 完整 TASK；
- 完整 diff；
- 完整 log；
- 数据文件；
- `.env`、token、webhook、cookie、license、账号或密码；
- 任意 shell；
- push / merge / deploy / close 指令；
- 自动交易、下单或真实通知指令。

## 快速判定

通过条件：

- 找到正确仓库。
- 不在 `main` 修改。
- 不在 WorkBuddy Assistant 固定目录写业务文件。
- 返回与 GitHub 一致。
- 不要求复制完整文件。

失败条件：

- 仓库路径不对。
- Issue 编号不是数字。
- Issue / TASK / PR 不一致。
- 未创建或未定位 TASK worktree。
- 尝试写 `main`、`data/**`、`.env*`、生产目录或助理固定目录。
- 尝试自由 shell 或自动 retry。
