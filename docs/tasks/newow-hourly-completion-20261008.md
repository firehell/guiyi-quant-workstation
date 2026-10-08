# 牛哇60m功能补齐

用户交办：补齐现有趋势/震荡/双策略60m、PP正式范围，并发布上线。分钟主升浪、持续更新、reference worker保持关闭。当前执行在codex/newow-hourly-completion隔离工作区，起点c0668866d，须在集成前承接最新develop/v1.12.1。

## 已实现（尚未集成或发布）

- capability v31承认60品种PP；原截止2026-09-24T07:00:00.000001Z保持。
- opt-in综合决策读W1/D1/60m，每周期独立quality policy，同一历史as_of，小时readiness与第一行动原则已接入；分钟MAIN_RISE不调用。
- 60m当前Close参与Canonical跨周期目标/吸筹显示；日周路径维持背景。小时事实、计龄、来源、状态卡与原权重展示已补。
- AI v2六组合及60m采纳，小时起点2026-04-01，稳定排序与样本门禁保持。

## 验证与剩余证据

最终相关后端378 passed/1既有skip，新增范围及截止/隔离/缺失/取消定向177 passed；Newow前端389 passed，vue-tsc、Vite production build与bundle topology通过；OpenSpec10通过，uv offline lock通过，Ruff/diff检查通过。实际命令原件在本工作区outputs/newow-hourly-20261008与任务临时日志。

宿主受限环境无法bind临时8011 API，也无法访问配置中的本地网络代理。公开源下载和临时只读API启动的首次自动审批均超时未执行；工具允许的一次复核重试也均自动审批超时，HOST_APPROVAL_BLOCKED，未执行相应动作。不能绕过宿主控制。旧公开原始HTML/JS临时文件已不存在；既有oracle仅含四组合评分，六组合原源码补验尚未完成。

未完成：三周期震荡状态卡27格原式补齐与逐值证据（当前仍明确保留日周名称、小时事实单列）；真实60品种API矩阵、Chrome验收、develop集成及main/tag/Release/Runtime切换。不能将本次代码或测试声明为发布完成。

## 独立Review

对c0668866d..c86fb6bcd的独立Review确认两项P2展示问题：小时事实错误沿用日线颜色、同分推荐与显示序号不一致。各自RED后修正，保留score-only稳定显示排序，推荐按交易数破同分；修后9项定向/389项Newow前端通过。仍保留原源码、27格与真实验收风险。

当前仅提交到独立任务分支；未集成develop，未push或创建main/tag/Release，未切换Runtime。运行版本继续v1.12.1。公开源码下载、候选API启动各两次自动审批超时；Git提交独立审批通过。唯一下一步是恢复宿主审批流程后继续原源码/真实API和Chrome验收，再完成剩余实现及发布切换。
