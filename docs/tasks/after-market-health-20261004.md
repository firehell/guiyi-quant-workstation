# 盘后增量问题修复

owner 交办：修复已定位盘后问题，目标 health 健康。基线 develop `542a5444b`，执行树
`.worktrees/fix-after-market-health`；不重试旧未知提交或禁重试源请求，不改交易阶段/Scope/通知受众。

已确认9/30原盘后主任务 passed；随后非交易日 skipped。跨版本未接续 success 造成 missed；
9/30旧版消费者检查 D1 180/W1 123 均 incomplete/budget_exhausted。现版已有600/1200秒预算和
consumer_only，但确定的缺口失败未复用，且部分 planner 结果被错误整体拒绝。

实现：独立有来源身份的 historical evidence、当前异常优先的 health、跨完整安装的旧 writer OS guard、
审计内确定失败复用及合法未生成 planner 结果保留。规范见 DATA_CENTER 与 historical-data-maintenance。

归档源原字节于另一清理任务移动至
`/Volumes/扩展盘/guiyi-quant-evidence/develop-cleanup-20261004-203824/release-v1.11.0-20260930/retired-v1.10.39/after-market-status.json`。
原 SHA `6ed66b566012bc795ca8c677ab270077abf5f9a9315a218f06066ecf233d988a`，
原 commit `653e736f5952146a2ea401634d32a605e7b9a0d5`，9/30 success；显式导入 dry-run ready，未 apply。

验证：history/current health/consumer/ProductService/launchd 组合280 passed；after-market/promotion/authority
相关159 passed；Web build通过；ruff通过、OpenSpec10通过、secret0、diff通过。测试使用隔离fixture，
不替代自然盘后或生产数据验收。独立Review发现的真实异常匹配、失败后跳过、未来日期、幂等及交接竞态
均已修正并继续复核。最终Review、真实恢复与运行结果尚待补充。

现场只读AU2612 D1 expected213/actual3/missing210，首缺2025-11-18；W1亦缺物理prefix。
一次完整有界旧候选审计进行中，只可用于缺口取证，不能证明新缓存修复性能；候选只读小范围重验另记。
生产恢复按现成 weekly recovery 精确逐合约1w（同合同D1+W1闭包）准备/预算/锁/单次执行/独立读回，
已有A2611禁重试与AL2302/15m未知结果保持各自边界，不扩大到P9七频campaign。
