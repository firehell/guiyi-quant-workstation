# PT2612 / 2025-12-19 周线修复授权包

状态：**已按单独授权执行一次，批次成功并已只读回读**。执行结果见
[`pt2612-apply-result.json`](pt2612-apply-result.json) 与
[`pt2612-postapply-readback.json`](pt2612-postapply-readback.json)。此授权已消费，
不覆盖随后发现的 2025-12-26 缺口；后续范围见
[`pt2612-remaining-repair-approval.md`](pt2612-remaining-repair-approval.md)。
证据由当前任务分支的
`data contract-warmup` 原生 planner 生成；[精确计划](pt2612-weekly-repair-plan.json)
和[写入前读回](pt2612-before-readback.json)已保存。计划连续两次只读生成相同哈希。

## 当前事实

- 品种 `pt`，物理合约 `PT2612`，上市起点 `2025-12-15`；本批次只到
  `2025-12-19`，只涉及 `1d` 与 `1w` 的 2025 年 12 月物理合约分区。
- 现役 D1 分区有 13 根 Bar，覆盖 2025-12-15～31，目标周的 5 个交易日
  均存在，Parquet SHA-256 为
  `4a3662400a4c5196c1225ef9c9c44fc0c3716df0d04f4f1995d8aeebbc499798`。
  读回无 `PRICE_UNAVAILABLE` 日。
- 同合约 W1 的 2025 年 12 月活动分区不存在；默认 PT 三策略都因
  `REPLAY_ENDPOINTS_MISSING` 在 `2025-12-19` 阻断。该缺口是内部周次，
  不能用前周快照或另一合约替代。
- Planner 把同周 5 根 D1 列为重新获取的伴随输入，以便将权威周线与 D1
  核对；计划中的 D1 `missing_bar_count=5` 表示**拟获取范围**，不表示现有
  D1 已缺 5 根。

## 拟授权的唯一批次

| 维度 | 精确范围 |
| --- | --- |
| 环境 | 本机生产 Market Catalog 与既有 Canonical 根；使用本任务分支的现有维护入口 |
| 命令 | `data contract-warmup --symbol pt --contract PT2612 --through 2025-12-19 --frequency 1w --expected-plan-sha256 b73956d81b95f4a43f3186e5ece968e92438ab4d04adf73896141fa5cc76f11b --apply` |
| 外部来源 | RQData，最多 2 次请求：D1 2025-12-15～19 的 5 根与 W1 2025-12-19 的 1 根 |
| 写入目标 | 仅 `contract/pt/PT2612/1d/2025-12` 与 `contract/pt/PT2612/1w/2025-12` 的新不可变 Canonical candidate 和对应 Catalog 活动分区注册 |
| 预算 | 2 个直接目标、最多 2 次 provider 请求、0 个派生目标；无自动重试、无跨周/跨合约/跨周期扩围 |

执行前须重读现场 D1/W1 活动分区、维护锁与精确计划；只有哈希仍为上述值且
现有 D1 校验和不变时才进入 `--apply`。维护实现先取得独占 lease，获取 D1/W1，
验证同周数值与完成端点，再发布不可变候选，并在一次 Catalog 事务中激活两目标。
任何来源冲突、质量失败、计划变化或维护锁占用均停止，不拆成单独 W1 发布。

## 读回与失败恢复

成功条件：命令返回 `passed`、`applied=2`、`blocked=0`、`failed=0`、
`provider_requests<=2`；活动 D1 内容仍与写入前 13 根一致，W1 恰有该周完成 Bar，
MDS physical 与 actual-dominant 读回同一数据身份。随后用最新候选代码复验 PT
趋势、震荡、主升浪的**无固定 `as_of` 默认首载**：快照、主图、四个适用副图、
参考交易、收益和比较器逐项记录；合法预热仍单列，不计策略 READY。
另复验 PT D1 三策略身份与结果无回归。此批次不包含发布、Runtime 或消费者切换。

若 provider/校验阶段失败且未提交 Catalog，先只读确认活动分区仍与写入前一致；
不可见的孤立不可变 candidate 不自行删除。若提交结果不明，停止所有写入，
只读核对两活动分区与 MDS 后再决定；**不盲目重试**。若已提交但验收失败，
保留写入前 D1 文件及校验和作为恢复锚点，另拟精确 Catalog 恢复计划并取得授权，
不自动回滚或删除数据。

实际执行调用相同原生 `contract_warmup` 方法并使用上述计划哈希，省略 CLI
可选的首页投影失效钩子，未删除授权范围外的生产投影文件；维护锁、输入校验
和原子 Catalog 激活仍由该方法执行。
