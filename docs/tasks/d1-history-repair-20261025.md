# 10/25 D1历史75条修复

状态：COMPLETED。Owner明确交办修复前次审计的75条D1历史资产；不新增功能，不改变公式、Scope、交易阶段或通知政策。

## 范围与旧结果

正式使用exact `v1.16.1 / bc2c43dab2a8ce67038ca3998e74ac6b4a16b3c9 / gen25` 原生入口。
目标75个disabled `historical_replay/1d` 身份：AL/PG/PS/PX/SI/ZN各趋势、震荡、主升浪共18条基础历史，以及57条融合历史；完整窗口保持各自原since，目标为10/23 15:00 CST。

初次状态645 CURRENT/57 LAGGING/18 REBUILD_REQUIRED；75个异常全部D1，其中18个正式历史入口503、57个末端停10/16–10/21。74个旧控制=55融合来源快照冲突、18基础coverage失败、ZN融合pending；PX融合没有控制。六品种192个实际历史owner的D1物理前缀已独立通过，因此不将这些旧阻断归为正常短K线暖机。

独立旧结果核查：18个融合candidate的native plan/hash/token、连续seq/hash链、seed绑定、最后receipt/checkpoint/resume一致，94个已提交批次没有token后的额外提交；父revision明确invalid，三基础依赖快照已变化。ZN旧advance为REBUILD_REQUIRED首写前返回，没有该计划的batch/seed/candidate。没有发现未知提交；禁止复用这些旧计划或旧resume。

## 单次执行与保护

封印计划SHA256 `72215ff7c68dd40c67773c25772e2f9c2089c4361c3786887ba16eb1fb750d31`；执行器独审及30项离线测试通过，身份tuple/list比较、停驻前恢复余量和控制精确读回均在生产操作前补强。

`attempt001` 正常park Reference原PID6210，获得deployment、after-market和refresh-control锁；冻结完整控制原文字节以及18组全行保护摘要。18条基础先原生fresh rebuild并独立验收，再为57融合生成绑定新基础的fresh native plan/hash并重建。每条新revision都有另一进程的完整来源manifest、checkpoint hash和正式HTTP保存指标验收，75/75均到10/23 15:00 CST。没有自动重试、旧plan/resume重放或失败attempt覆盖。

保护范围为4个App表、全部forward身份的8类表、75目标全部旧revision的batch/action/trade/mark经济记录、其他历史stream/revision元数据，共18组；以及所有保留日source/completed journal原文、identity index和Live/Alert/Reference游标。前后摘要完全一致。历史revision生命周期由原生重建转换，不能把它说成所有revision元数据保持不变。

成功且逐条独立验收后，仅解决对应74项旧控制，原文和旧候选仍保留，控制写回与预期精确相等。15:17:39 CST恢复同PID6210/gen25 active，既有刷新和通知线程继续运行；未切换版本或其他服务。

## 最终独立读回

- 15:19:27 CST独立Review：75个新active revision、来源digest、checkpoint SHA与逐条HTTP证明一致；18个旧candidate及94批提交头保持，旧经济事实/非目标元数据保护通过。
- 正式启用720路对应历史端点均CURRENT，D1由165/240追至240/240；H1/W1各240端点保持。非目标645的CURRENT仍只是端点级投影，不冒称已重新逐值验完全部来源；本次75另有完整来源验收。
- 74控制精确解决，当前控制队列0；Rule2/Event3921/policy1/delivery10954全行摘要保持；journal/index/cursors不变，无补发或ACK改写。
- 15:18:59 CST运行读回：六常驻原PID均active，十binding仍exact v1.16.1/gen25；pending Capture0、全部保留journal消费者积压0、PG维护holders/长查询0，deployment/after-market锁空闲。
- Forward仍676 READY/44 OBSERVATION_LAGGING、global degraded保留。旧2565+611原件缺失、正常暖机、后置苏冰全量历史，以及下一自然采集/H1/Event/18:05增量分别保留，不以历史重算制造自然验收。

本次provider请求、Canonical写入、forward写入、通知均0；仅目标历史原生重建及对应控制收尾。

## 实际验证

正式树Python、隔离日志目录和PYTHONPATH运行：

```sh
GUIYI_LOG_DIR=/tmp/guiyi-d1-repair-test-logs PYTHONPATH=.worktrees/release-v1.16.1/services/quant-api:.worktrees/release-v1.16.1/packages/quant-core .worktrees/release-v1.16.1/services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider output/d1-history-repair-20261025/test_repair_operator.py .worktrees/release-v1.16.1/services/quant-api/tests/reference_trading/test_historical_planning.py .worktrees/release-v1.16.1/services/quant-api/tests/reference_trading/test_historical_refresh.py .worktrees/release-v1.16.1/services/quant-api/tests/reference_trading/test_refresh_plan_codec.py .worktrees/release-v1.16.1/services/quant-api/tests/reference_trading/test_historical_service_read_interrupt.py .worktrees/release-v1.16.1/services/quant-api/tests/reference_trading/test_newow_fusion_historical.py --tb=short
# 首轮144 passed/2 skipped（含初版维护测试）；补强后维护执行器单独30 passed，与首轮存在重叠，不相加为独立总数。
```

旧结果、执行器及实际结果均独立Review通过；75个来源/checkpoint/正式HTTP实际读回通过。未修改产品代码，不需要新release或Runtime promotion。

证据目录：`output/d1-history-repair-20261025/`，关键文件为 `inspection-001.json`、`review-old-outcomes.json`、`EXECUTOR-REVIEW-FINAL.md`、`maintenance-plan-001.json`、`attempt001/completed.json`、`attempt001/protected-verified.json`、75份`independent-verified.json`、`final-review-readback-001.json`、`runtime-final-001.json`。旧原文和失败诊断不删除。

下一步：按既有自然日程验收10/26新分钟、实时计算及18:05盘后增量，不新增后台监控或通知。
