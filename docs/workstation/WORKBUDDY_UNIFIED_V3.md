# WorkBuddy Unified V3

更新时间：2026-07-16

## 定位

WorkBuddy Unified V3 是归一量化工作站的上班/远程统一协调入口。

它负责：

- 产品需求澄清；
- 最少必要专家参与；
- 文件和文档处理；
- QA 清单；
- 视觉验收；
- 交付摘要；
- 固定命令入口转发。

它不负责：

- 维护第二套任务状态；
- 直接成为代码 writer；
- 自由 shell；
- 裸调 Codex；
- 自动 retry；
- push / merge / deploy / close；
- 生产写入；
- 自动交易或实盘委托。

## 事实源

| 层级 | 事实源 |
|---|---|
| 项目事实 | GitHub `main` canonical docs |
| 执行契约 | `docs/tasks/<TASK_ID>.md` |
| 生命周期 | GitHub Issue |
| 交付容器 | Draft PR / PR |
| 本地证据 | `.ai/results/<TASK_ID>/` |

WorkBuddy 对话、memory、截图和交付摘要不是状态源。它们只能引用事实源。

## 角色

| 工具 | 角色 |
|---|---|
| GPT + GitHub | 代码和事实分析、架构设计、Issue/TASK/Draft PR、External Review |
| WorkBuddy | 远程协调、PM、QA、视觉验收、交付摘要 |
| Codex | 核心和复杂开发 writer |
| Copilot | 明确 R3/L1、单模块、最多 5 文件的小修改 |
| CodeBuddy | compatibility-only；旧任务回退入口，Demo 通过后 deprecated |
| 用户 | Plan、merge、deploy、生产写入最终批准 |

Codex writer lock 仍使用 `codex`。不新增 `workbuddy` writer。

## 最小命令

WorkBuddy 只能通过白名单 facade 触发受控脚本：

```bash
scripts/ai/workbuddy_task.sh <command> ...
```

固定命令见 [`WORKBUDDY_COMMAND_PROTOCOL.md`](WORKBUDDY_COMMAND_PROTOCOL.md)。

## 何时升级给 Codex

以下情况必须升级给 Codex：

- 核心代码；
- 数据链路；
- 策略 / 回测 / 风控；
- 数据库；
- worker / scheduler / runtime；
- 跨模块改动；
- R0/R1/R2 风险；
- Copilot 条件不满足。

## 返回格式

每次 WorkBuddy 回复必须包含：

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

视觉验收只使用 `PASS` / `FAIL` / `NOT_VERIFIED`，并拆分 blocking 与 non-blocking。
