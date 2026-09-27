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
4. 默认向前修复，不常驻保留回滚工作树。失败或结果不明先停止相关 mutation 并只读核对；在最新发布树的修复分支处理问题，测试后创建新补丁版本并绑定新的运行 commit，不移动已发布 tag、不将 dirty 源码冒充原版本。安装器自身的原子失败恢复机制仍保留；必要时可从 Git history 重建精确版本，但不留下常驻旧树。不得盲目重试、补发或改变 Scope。
5. 发布后只可报告 `RELEASED`。首根自然 completed Live Bar、必要 heartbeat、连续状态读回及受影响的自然
   业务 evidence 未完成前，`RUNTIME_READY` 保持未证实；历史 evidence 不冒充新版本 evidence。

## 按影响验收

纯文档运行引用与 diff 检查，按影响选择工程测试、OpenSpec 或 secret scan，不机械重跑自然行情；数据、身份、兼容性、
状态、通知或拓扑变化保留对应定向、readback 与自然 Gate。API/DOM/fixture、render-only、preflight、health
和历史 evidence 各自只证明声明范围，不能互相替代。

## 发布树位置与清理

owner于2026-09-27指定：所有发布工作树与正式运行源码统一在扩展盘，按对应版本命名。默认路径为
`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-vX.Y.Z`，使用本仓库linked worktree，让Codex的Linked Worktrees可见。
最新发布树兼作正式服务源码根，不另建Application Support中的runtime-vX.Y.Z克隆；安全配置、共享launcher和日志仍使用既有Git外目录。
外接卷launchd访问必须通过宿主权限和真实启动/读回验证；不因路径约定绕过宿主安全。使用既有`GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1`安装选项并验证所有required服务。

发布后只保留最新发布树，不保留回滚树。创建新树、构建、render/preflight、切换及健康读回完成后，才删除旧树；
仅发布尚未切换时，不能删除仍被服务引用的旧树，继续完成交办的切换或明确记录待切换。
删除前逐树检查精确路径、版本、dirty/untracked、已集成状态、配置/loaded服务及进程引用；有用户修改或引用则停止该树清理。
保留必要运行JSON和日志证据文件，不保留整棵旧源码；不删除tag/Release历史，不触碰develop/main、普通任务树、行情、DB、Scope或安全配置。
应用管理的worktree用Codex archive工具；普通Git worktree用非force的`git worktree remove`；独立旧clone仅在精确清单和引用复核通过后清理。
后续修复默认复用最新发布树的版本修复分支，发布新版本后改为新版本名称；正式运行始终绑定已验证commit，修复过程与运行身份分开验证。

## 交付

简述版本/commit 身份、实际验证和发布/Runtime/清理结果，披露未完成 Gate 与风险；不强制固定段落或结论口号。
