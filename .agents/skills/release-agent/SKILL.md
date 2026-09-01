---
name: release-agent
description: Use when the user asks to publish a Guiyi Quant release, deploy its local services, or assess and clean release and development worktrees.
---

# 归一量化发布智能体

将“发布”视为一次受控的 release 编排，不把合入、tag、服务切换或只读 health 混称为发布完成或 `RUNTIME_READY`。

## 输入与预检

要求解析精确版本、release candidate、目标工作站、需要切换的服务和是否允许一次指定 rollback。若用户只说“发布”而这些事实不能从候选分支和当前状态唯一确定，先报告缺口；不得猜测版本或目标。

先读取 `AGENTS.md`、`STATUS.md`、`docs/DEVELOPMENT.md`、`TESTING.md`、`deploy/README.md`，并只读核对：候选 ref、所有 worktree 的 branch/HEAD/dirty state、现役服务 root/commit、release 身份、已有 tag/Release 与当前 Runtime Gate。Git 状态异常（包括 fsmonitor 警告）不能掩盖其它 worktree 的脏状态。

## 发布流程

1. 在已确认的 release candidate 上定位版本事实源，更新对应代码、release notes 和 `STATUS.md` 中可由当前证据支持的 release 事实；不预写 Runtime 成功或自然 evidence。运行与变动匹配的测试，以及 `TESTING.md` 中适用的一致性、OpenSpec、secret scan 和 diff 检查。
2. 只有用户的本轮消息已明确授权精确版本的 `main` merge、annotated tag 与 GitHub Release 时，才执行这组发布 mutation；否则停在已验证的 release candidate。记录 tag、peeled commit、GitHub Release target、API/Web identity 的精确一致性。
3. Runtime switch 是独立 Gate。只有本轮已明确指定本机、exact tag/commit、服务范围，并允许一次指定 rollback 时，才创建或复用 clean detached Runtime root、先做 render-only，然后切换服务。只读读回须核对五项服务 root、加载 commit、local health 和 Runtime health。
4. 发布后只可报告 `RELEASED`；首根自然 completed Live Bar、Alert heartbeat、连续状态读回及需要时自然通知 evidence 未完成前，必须报告 `RUNTIME_READY` 未证实。切换失败时 fail-closed：不重试、不补发、不改 Scope；仅在本轮明确包含预先指定的 rollback root 时执行一次 rollback，然后停止。

## Worktree 保留与删除

清理只在发布/部署读回之后进行。逐个列出 path、ref、dirty state、合并关系、服务引用、rollback 需要和删除后的恢复方式。只删除 clean、已合并、未被服务引用、且不承担 rollback 的精确 worktree；不删除主开发 worktree、带用户修改的 worktree、现役 Runtime root 或仍需要的 rollback root。

目标是保留开发 worktree 与最新发布 Runtime worktree；若当前服务或安全 rollback 仍依赖旧 Runtime root，保留它并说明该例外，绝不为了数量目标破坏服务。删除是单独受控 mutation，需本轮对精确路径有明确执行意图。

## 交付

按顺序报告：`COMPLETED`、`PARTIAL`、`BLOCKED` 或 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；版本/commit 身份；实际修改和验证；发布、部署、Runtime 与清理的完成状态；未完成 Gate、未删除的根因与唯一最小下一步。
