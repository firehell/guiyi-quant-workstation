# 日线 60 品种修复收尾

用户在本任务中明确授权 GitHub `firehell/guiyi-quant-workstation` 的 PR/develop 集成，以及 PT2612、SS2611 限定 D1 生产补齐。此前两项自动审批拒绝已由该授权解除；没有扩大到 main/tag/release 或 Runtime promotion。

## 结果

- 目标完成日：2026-09-17，策略 cutoff `2026-09-17T07:00:00.000001+00:00`。
- 首页日线报价 **60/60**，过期 0、报价不可用 0；60 品种目标 D1 历史窗口无未知缺口。
- PT2612 从 1 根补至 **186/186**；SS2611 从 1 根补至 **205/205**。新增 389 个真实日线端点，未补造价格，既有目标日 Bar 保留。
- 三套日线策略 chart/reference 综合覆盖 **60/60，360/360 READY**。核验方式为：补数前完整 360 项矩阵，加上补数后 BZ/EB/PG/PT/SS 的 30 项复验；只改变 PT/SS 两个合约的 D1 数据，Newow 代码未变，其余结果沿用本轮同 cutoff 基线。没有冒充补数后重新跑过全部 360 项。
- PT/SS × 趋势/震荡/主升浪，共 **6/6 真实新页面首载通过**：图表 ready、参考统计摘要可见，未刷新重试、未使用 fixture。截图及执行脚本见 `approved-001/`。

本次没有修改任何 Newow 策略公式。BZ/EB/PG 的权威来源缺价仍保留为计算边界；W1/60m 未开放，周线历史也不属于本次补数范围。

## 生产批次

- 干净执行副本：`.worktrees/market-home-quality-recovery`，detached `b3d161b2c`。
- prepared SHA256：`cc26e7d5f2e7ca844363bb43312ace1aa81da63f97a370dc31fc6271fb025480`。
- 计划与原只读清单逐端点比对：PT 185、SS 204，合计 389，无额外日期、合约或频率。
- PT：10 个请求、10 个分区 applied；SS：11 个请求、11 个分区 applied。
- 总计 **21 请求、21 分区，failed=0、retries=0、outcome_unknown=false**。
- 原始 provider 响应、journal、单元结果与 batch receipt 保留在本地 `approved-001/apply-001/`。Git 收录精确计划、invocation 与 batch-result；原始响应未批量发布到远端。
- Catalog commit 是单分区可见点，旧文件保留；没有删除、回滚或重试。若未来需恢复，必须先只读核对并取得新的恢复授权，不自动重放已完成批次。
- prepare 曾因输出目录不存在而无法保存（`OUTPUT_ROOT_UNSAFE`），当时 provider/数据写入未开始；建立指定目录后完成计划，实际 apply 仅执行一次。

## 代码与验证

PR：[ #373](https://github.com/firehell/guiyi-quant-workstation/pull/373)，base=develop。

最新上游 `d87dbca8f` 的 Alert/runtime health 改动已并入候选；候选源码 `cf291fb52abb75d733e6281f40aec001bd2c7ee0` 无冲突。独立审查确认首页修复与原已审版本一致，无合并回归，允许集成 develop。

合并后实际命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  ../../services/quant-api/.venv/bin/python -m pytest \
  services/quant-api/tests/data_foundation/test_market_home_overview.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/test_market_home_api.py \
  services/quant-api/tests/test_market_home_projection_api.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py \
  -q --tb=short -p no:cacheprovider
```

结果 **234 passed**。原修复完整相关模块 1749 passed / 59 skipped、前端 624 passed / 1 skipped、首页 E2E 31 passed、build/OpenSpec/Ruff/secret scan 通过。基线既有 11 项 mypy Optional 错误未新增。

本次完成代码/测试/独立 Review、受控补数和相关业务复验；不宣称已发布首页新代码或 `RUNTIME_READY`。正式首页采用新质量口径仍需后续 release/Runtime Gate；本轮授权未包含它们。
