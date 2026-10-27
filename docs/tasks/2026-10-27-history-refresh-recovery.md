# 历史参考资产刷新恢复

Owner批准从RB日线切入恢复既有历史参考资产更新，包含必要发布/正式整组切换，保持单发布树。
不补造观察、不下载行情、不补建缺失苏冰资产、不补发通知；Scope/公式/Broker/auto_order=false不变。

## 已确认事实和实现

RB趋势D1历史revision f0a513dafb5d463787966b1d234fb2c4/seq22完成到10/26 07:00Z；
10/27请求的新输入比旧资产多1根，原2572输入指纹及Calendar/Session旧前缀全部一致。
20:02 43条pending/REBUILD_REQUIRED；规划时增至48：36条compact60m与12条融合D1，均冻结advance/无resume。
逐checkpoint对比证明紧凑input_count/hash/query范围/来源证明变化以及融合source_dependencies变化，不能放宽为追加。
现有每tick单路、30秒间隔、advance拒绝后等待游标回绕才rebuild，造成续作延迟；不把pending当成未知提交。

公共HistoricalRefresh仅在原生advance明确blocked/REBUILD_REQUIRED、completed_bars=0、无batch/resume，
且committed回调数0时，同一工作单元转换为原endpoint/source_token/manifest hash的rebuild。
先持久化安全pending，再冻结新rebuild并落盘；取消/源漂移/原子写未知均保留原恢复边界。
两段共享1800秒（苏冰沿既有预算）的整体取消截止和原batch_limit，不增加单批提交量。
同一通路处理旧pending；非零effect拒绝转换。原source_identity/compact来源证明和旧revision保留。
现有Runtime报告增加安全刷新进度字段，不逐轮日志、不记录异常原文。

## 验证和交付进度

新增回归先红：2failed/1passed，确认旧实现只advance、不立即rebuild。
定向组合初轮113passed/2 PostgreSQL fixture skipped/8failed；其中6项为转换后让行分支，2项隔离日志目录缺失。
修复让行并补隔离目录后，仅原8项补跑全部passed；新增提交回调反证及安全诊断后仅transition6项passed。
Ruff通过。独立Review无Confirmed Issue；生产需冻结路由/端点，Catalog锁复用原生components scope。
未运行无关全量检查。当前尚未发布、切换或执行本任务生产历史刷新；以后续实际结果更新。
