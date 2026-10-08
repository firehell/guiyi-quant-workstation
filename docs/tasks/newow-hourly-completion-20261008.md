# 牛哇60m功能补齐

用户交办：补齐现有趋势/震荡/双策略60m、PP正式范围，并发布上线。分钟主升浪、持续更新、reference worker保持关闭。当前执行在codex/newow-hourly-completion隔离工作区，起点c0668866d，须在集成前承接最新develop/v1.12.1。

## 已实现

- capability v31承认60品种PP；原截止2026-09-24T07:00:00.000001Z保持。
- opt-in综合决策读W1/D1/60m，每周期独立quality policy，同一历史as_of，小时readiness与第一行动原则已接入；分钟MAIN_RISE不调用。
- 60m当前Close参与Canonical跨周期目标/吸筹显示；日周路径维持背景。小时事实、计龄、来源、状态卡与原权重展示已补。
- AI v2六组合及60m采纳，小时起点2026-04-01，稳定排序与样本门禁保持。

## 验证与剩余证据

相关后端375 passed/1既有skip，新增范围及截止/隔离/缺失/取消定向177 passed；Newow前端387 passed，vue-tsc、Vite production build与bundle topology通过；OpenSpec10通过，uv offline lock通过，Ruff/diff检查通过。实际命令原件在本工作区outputs/newow-hourly-20261008与任务临时日志。

宿主受限环境无法bind临时8011 API，也无法访问配置中的本地网络代理。公开源下载和临时只读API启动的首次自动审批均超时未执行；工具允许的一次复核重试仍待结果。不能绕过宿主控制。旧公开原始HTML/JS临时文件已不存在；既有oracle仅含四组合评分，六组合原源码补验尚未完成。

未完成：三周期震荡状态卡27格原式补齐与逐值证据（当前仍明确保留日周名称、小时事实单列）；真实60品种API矩阵、Chrome验收、独立最终Review、develop集成及main/tag/Release/Runtime切换。不能将本次代码或测试声明为发布完成。
