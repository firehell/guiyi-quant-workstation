# 前五项修复：develop 集成与真实只读验收

日期：2026-09-17。代码已集成并推送；60 品种维护审计通过，候选首页真实验收未通过。

## 代码与范围

修复提交 `b958ac759` 与最新 develop `c9e0297a0` 在隔离工作树合并，合并代码为
`abd3b4d2a5da9b047ca47521411c60f8d47db49f`，无文本冲突。该版本已经快进集成并推送 develop。
原主工作树暂存文件保持不变；其他任务的 STATUS.md 和 outputs 修改未纳入本任务。

本次只进行开发集成、测试、真实 Catalog/Canonical/Redis/HTTP 只读检查和本地证据输出。
没有 provider 下载、生产数据写入、通知重发、main/tag/release 或 Runtime 切换。

## 合并版本验证

- API：data_foundation、Alert、runtime_health、market_read_service、Newow，3572 passed、60 skipped、3 deselected。
- 其中两个 localhost socket 测试随后单独运行，2 passed。
- 一个 Newow P4 性能基线未重跑：前轮已在原主工作树复现 NEWOW_COVERAGE_IDENTITY_CONFLICT，独立跟踪；不能宣称全量测试无例外通过。
- Web：npm test -- --run，622 passed、1 skipped；npm run build 通过。
- Ruff、四个核心模块 mypy、git diff --check 通过。
- 合并交互独立 Review：无 Confirmed Issue，补充 355 tests passed，允许集成 develop。

主要实际测试命令：

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest \
  services/quant-api/tests/data_foundation services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_runtime_health.py services/quant-api/tests/test_market_read_service.py \
  services/quant-api/tests/newow -q --tb=short \
  -k 'not test_product_socket_http and not test_p4_representative_cold_warm_and_pressure_baseline'
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest \
  services/quant-api/tests/newow/test_product_socket_http.py -q --tb=short
(cd apps/quant-web && npm test -- --run && npm run build)
```

任务工作树通过主工作树的 services/quant-api/.venv 运行以上 Python 命令。

## 固定窗口真实读取

代码 abd3b4d2a，以 2026-09-16 为 target_as_of，60 品种目标日 rank1 的同物理合约，
D1 最多 300 根、W1 最多 80 根，共 120 项查询，116 项成功、4 项失败：

| 品种/合约 | 周期 | 结果 |
| --- | --- | --- |
| BZ / BZ2610 | D1 | DATASET_OR_PARTITION_MISSING |
| BZ / BZ2610 | W1 | DATASET_OR_PARTITION_MISSING |
| EB / EB2610 | D1 | PRICE_UNAVAILABLE |
| PG / PG2610 | D1 | DATASET_OR_PARTITION_MISSING |

普通首页 snapshot 返回 MARKET_HOME_DATA_INTEGRITY_ERROR。这不是 Newow quality-aware 页面验收；
EB 来源价格不可用不能按缺数直接补造。成功查询也不代表满足每个指标的 warm-up 根数或所有历史窗口完整。

原始证据：[candidate-readback.json](../../../outputs/first-five-integration-20260917/candidate-readback.json)。

## 运行版本只读回读

当前六个服务仍绑定 v1.10.10-r1 工作树、commit b49e2499de654092b48e60e181102c02e16ce89f。
HTTP health 正常，2026-09-16 盘后任务 completed。Alert 存在 notification_transport_failed，
连续发送失败计数为 2；本轮没有重试或确认该失败。
新代码读旧 Runtime heartbeat 时，Live/Alert coverage_state 均为 unverified，符合兼容边界。
这不证明新版本 Runtime 的逐项进度或自然业务闭环已完成。

原始证据：[runtime-readback.json](../../../outputs/first-five-integration-20260917/runtime-readback.json)。

## 全历史审计

使用现有 run_weekly_audit / HistoricalDataManager.audit，operational 60 品种，
maintenance lease 和只读事务；provider 调用被禁用，只写本地报告。
2026-09-17 12:42–13:07 完成，status=passed，60/60，through=2026-09-16，
finding_count=0，provider_requests=0，data_writes=0。

审计通过与首页失败并不矛盾：HistoricalDataManager._desired_months 对物理合约的 required
端点来自 rank1 映射日；已存在的 warm-up 分区参与物理/lifecycle 检查，但不会因此要求
补齐所有主力前历史。首页 query_physical_bars_as_of 通过严格分页读取更长同合约前缀，
且普通价格消费者拒绝 PRICE_UNAVAILABLE。BZ/PG 的具体缺失端点或分区包络仍需定向
诊断，不能仅凭错误码就生成下载批次；EB 需保持已有来源质量事实。
因此本次“全历史”指现有维护合同定义的全历史范围，不能证明所有消费窗口可用。

证据：[audit-preflight.json](../../../outputs/first-five-integration-20260917/audit-preflight.json)、
[historical-audit.json](../../../outputs/first-five-integration-20260917/historical-audit.json)。

该审计能核对现有文件、Catalog、覆盖和物理一致性，不能追溯证明旧数据导入时已经丢弃的原始 provider 合约身份。

## 结论与后续边界

代码满足 develop 集成条件；数据验收尚未通过，不能据此发布或 promotion。
下一步先定位 BZ/PG 失败的精确窗口，并确定 EB 普通首页的不可用状态处理范围；任何真实下载、Canonical/DB 写入、发布和 Runtime 切换需独立明确授权。
