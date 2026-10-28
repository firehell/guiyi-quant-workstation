# 夜盘 Inbox 接收吞吐与休市覆盖修正

Owner 要求先开发验证，**不发布、不切换、不重启服务**。基线 develop `00537c2cd`；正式服务保持
v1.16.31/gen37。本轮不改公式、Scope、通知、生产配置、生产原件或交易记录。

## 定位与修改

21:35 的只读检查中，21:30 输入仍有约 100 条 Inbox 待算、271 条原件未消费，BLOCKED/UNKNOWN 为零。
阶段诊断显示接收/恢复关联约一秒一次，纯计算约五毫秒；不是公式计算本身占用主要时间。
旧实现每条原件接收均重验全部 2618 条恢复闭环，包括没有任何策略目标的 1m 原件。

接收现在先计算保守容量上界：历史已恢复投递仍计作未完成，上界足够就不需要释放历史容量；
只有上界不足、需要回收恢复容量时才在原有 PG 全局容量锁内完整重验闭环。没有新增未完成路由的
原件无需该容量读取。所有原件和冻结路由仍先持久化再 ACK；重复投递、未知提交、队头顺序、
health 和恢复验证合同保持。无跨事务缓存或永久跳过验证。

Alert 仅对同代际、健康 Live 已完整验证产品/相位集合的 CLOSED 分钟路由豁免 unverified 降级，
保留全部明细。D1/W1 Canonical 未验证、TRADING/BREAK/UNKNOWN、滞后、真实失败和旧未决失败不豁免。

## 实际验证

锁定解释器、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=services/quant-api:packages/quant-core`：

- `pytest -q --tb=short -p no:cacheprovider services/quant-api/tests/reference_trading`：1215 passed，115 skipped。
- `test_inbox.py/test_inbox_recovery.py -m isolated_postgresql`：真实隔离 PG 4 passed，含跨日并发容量及不可变约束。
- `test_handover_consumers.py/test_alert_runtime.py/test_runtime_health.py`：233 passed。
- 两个修改模块定向 Mypy、Ruff、`git diff --check`、OpenSpec strict 12 项及 secret scan 0 通过。
- 独立并发/恢复 Review 通过；没有未解决 Confirmed Issue。

同一真实冻结历史装载隔离 PG：2618 条完整恢复链均严格验证，45 条无目标 1m 与 45 条有目标 5m
按 journal 顺序接收，均 `duplicate=false`。原件、hash、目标数量、路由及投递身份 90/90 逐值一致。

| 单条接收 | 基线平均 / p95 | 候选平均 / p95 |
|---|---:|---:|
| 1m 无目标 | 959.93 / 1079.56 ms | 4.20 / 5.39 ms |
| 5m 有目标 | 950.93 / 1071.71 ms | 10.72 / 17.23 ms |

私有证据 `output/reference-inbox-intake-20261028/comparison-45.json`，
SHA256 `ccfd54561db1ec6258fc5f988dbe414341e23a48d63e710b8897a515af116b1c`。
这是隔离接收性能结果，不等于生产端到端或 30 分钟行情验收。算法与计算内核未修改。
一次性测试容器 `guiyi-inbox-isolated-20261028`（15490）已正常停止并移除；无后台压测或新增自动化。

## 交付边界

代码与测试完成、独立 Review 通过，允许集成 develop。按本轮要求不更新发布版本、不创建 tag/Release、
不切换或重启正式服务、不新增自动化。现役 v1.16.31 仍运行旧接收路径；上线后的积压持续下降、
下一 5 分钟边界前完成、SOURCE_BUSY 实际解除和 HTDY 自然新信号/参考交易须在后续切换后独立验收。
