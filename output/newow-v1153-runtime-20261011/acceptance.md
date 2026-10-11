# v1.15.3 Runtime切换验收

目标：正式副本切换至v1.15.3@c28438d3d7ad6d6c66272027996f4a25e2facdfe。
结果：gen16单次apply成功，独立只读第二轮回读通过。API8000版本1.15.3、Web5173 HTTP200。
十bindings/plists精确一致；六常驻current ready/fresh、四calendar enabled-idle；Scope/history/journal保护通过。

验证：精确候选 pytest（8个Newow/Reference/runtime模块）210 passed；四代controller pytest171 passed；
Web pnpm build（含typecheck/topology）通过；9组跨版本810步状态/动作/身份及810 subplot prefix一致；
secret_scan.py STATUS.md output/newow-v1153-runtime-20261011 --json finding_count0；git diff --check通过。
具体控制器测试、计划和独立Review同目录。未修改发布tag或候选源码。

gen13 HTTP启动检查失败、gen14 owner读取时序失败、gen15全六同时ready等待失败均保留原unknown记录；
原attempt不重试。新代次先证明原PID退出、完整保护前像与休市窗口后执行。
gen16切换成功后的主/独立首轮只读readback均HEALTHY_CYCLE_TIMEOUT，保留失败记录。
独立30秒285轮诊断出现7轮全六ready，无错误；随后顺序原合同30秒官方readback通过。
这些启动/读回证据不表示自然业务验收完成。

现役overall health仍degraded（既有盘后failure、weekly missed、Alert degraded，log-rotate自然身份unknown）。
60品种休市；自然completed bar、策略事件、收件人送达PENDING；不声明RUNTIME_READY。
未扩大Scope、通知、资产激活或账户执行；auto_order=false。
旧v1.15.1精确清理计划两次一致且无引用，non-force worktree remove完成，可从原annotatedtag重建。
下一最小步骤：交易时段按现有合同读取自然业务证据，不新建监控或补发事件。
