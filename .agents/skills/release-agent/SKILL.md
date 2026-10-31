---
name: release-agent
description: Use when the user asks to publish a Guiyi Quant release, deploy its local services, or assess and clean release and development worktrees.
---

# 归一量化发布与运行

按 [AGENTS.md](../../../AGENTS.md) 的目标连续交付，默认向前修复；不设候选冻结、版本收尾或逐阶段批准。

## 实施

- 从任务与 [STATUS.md](../../../STATUS.md) 确定目标工作站、待发布代码与实际启用服务；只读取本次相关的
  [开发规则](../../../docs/DEVELOPMENT.md)、[测试入口](../../../TESTING.md)和[部署合同](../../../deploy/README.md)。
  快速核对工作区、运行 root/commit 与已有完成项，保留其他修改，不重复执行。
- 必要测试与自审通过后，按目标连续集成、发布、构建、切换与现场确认；高风险变化追加针对性独立 Review。
  现有工具要求的应用编号、annotated tag 和精确 commit 由 Codex 处理，不要求 owner 预先指定，不生成另一套候选材料。
  只交办编码、发布或只读时不推导额外运行操作。
- 普通发布确认新代码、受影响功能和必要服务实际生效即可交付，不机械等待所有自然行情、推送或盘后场景。
  本任务明确要求的自然闭环仍须实际发生；未发生项如实注明，不能拿 health、fixture 或旧记录冒充。
- 有问题在当前代码向前修复再发布，不维护旧版兼容矩阵或常驻回滚树，不移动旧 tag、不在运行树临时改源码冒充原版本。
  结果未知先只读查清，保留安装器原子失败恢复、锁、幂等与禁重试条件，不补发、不擅改 Scope。

## 清理与交付

旧发布树先查实际运行与恢复引用，无引用且必要证据保全后 non-force 清理；已有历史索引复用，
只有实际恢复依赖需要时才封存，不固定串联 closeout/seal/cleanup。精确路径与检查入口见
[发布工作树存储](../../../deploy/README.md#发布工作树存储)，不动用户修改、其他任务、数据、账本或安全配置。

一次简短说明关键改动、实际验证、发布/运行是否发生及剩余问题；引用已有工具结果，不重复制作报告或收尾材料。
