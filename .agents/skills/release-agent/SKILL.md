---
name: release-agent
description: Use when the user asks to publish a Guiyi Quant release, deploy its local services, or assess and clean release and development worktrees.
---

# 归一量化发布智能体

将“发布”视为一次受控的 release 编排，不把合入、tag、服务切换或只读 health 混称为发布完成或 `RUNTIME_READY`。

## 输入与预检

从交办目标和现场解析精确版本、release candidate、目标工作站与操作范围；不要求 owner 预先提供实施后
才确定的 commit。服务清单以现有部署合同、activation marker 和任务目标为准；不得把未启用的可选模板
变成 required service。若关键对象仍无法唯一确定，先报告缺口，不猜测。

读取 `AGENTS.md`、`STATUS.md`、`docs/DEVELOPMENT.md`、`TESTING.md`、`deploy/README.md`；只读核对候选 ref、
worktree/dirty state、现役 root/commit、已有 tag/Release 和 Runtime Gate。

## 发布流程

1. 在候选上定位版本事实源，只记录当前 evidence 支持的 release 事实，不预写 Runtime 或自然 evidence；
   运行与变动匹配的测试及适用工程检查。
   交办目标按 `AGENTS.md` 跨会话持续有效，恢复前核对身份与已完成项。
2. 交办目标包含发布时，在候选验证通过后连续完成 `main` merge、annotated tag 与 GitHub Release；
   只要求候选的任务停在已验证候选。记录 tag、peeled commit、Release target 和版本身份的一致性。
3. 交办目标包含上线或运行切换时，按 `deploy/README.md` 验证现役消费者、候选兼容性和实际 required service，
   再完成 render-only、preflight 与 Runtime switch。仅要求发布时不推导运行切换；发布与切换仍分别留证。
4. 失败处置先证明兼容性：canonical 要求安全 rollback 时，预先解析并校验精确 rollback root；无法证明安全
   rollback 或现行合同未允许替代处置时，报告缺口并停止，不构造虚假回退。任务内恢复须证明兼容、安全且
   不扩大目标；未明确重试次数时只尝试一次。失败或结果不明先停止并只读核对，查明后仅按已证明安全的
   幂等与恢复边界继续，不补发、不改 Scope。
5. 发布后只可报告 `RELEASED`。首根自然 completed Live Bar、必要 heartbeat、连续状态读回及受影响的自然
   业务 evidence 未完成前，`RUNTIME_READY` 保持未证实；历史 evidence 不冒充新版本 evidence。

## 按影响验收

纯文档运行引用与 diff 检查，按影响选择工程测试、OpenSpec 或 secret scan，不机械重跑自然行情；数据、身份、兼容性、
状态、通知或拓扑变化保留对应定向、readback 与自然 Gate。API/DOM/fixture、render-only、preflight、health
和历史 evidence 各自只证明声明范围，不能互相替代。

## Worktree 保留与删除

普通 task worktree 在交办目标的收尾范围内，且已合并、干净、未被服务引用、不承担 rollback 时可直接清理；
先逐个核对 path、ref、dirty state、合并关系和服务引用。恢复使用 Git history。

现役服务 root、仍承担回退职责的 root、带用户修改的 worktree 和仓库外真实数据不进入普通清理范围；
任务确实要求删除时先确认引用、影响和恢复办法。绝不为数量目标清理 main/develop、现役 Runtime 或安全 rollback。

## 交付

简述版本/commit 身份、实际验证和发布/Runtime/清理结果，披露未完成 Gate 与风险；不强制固定段落或结论口号。
