# Newow 分层贡献研究：独立审查修正

状态：`NORMATIVE_AMENDMENT_PENDING_APPROVAL`

日期：2026-08-31

关联：Issue #259 / Draft PR #260

基线文档：`docs/tasks/2026-08-31-newow-layered-contribution-research-design.md`

> 本文是 Lane 3 设计审查修正。若与基线文档存在冲突，以本文为准。本文不授权策略实现、历史结果生成、真实写入、通知、发布或 Runtime promotion。

## 1. R1/R2 必须锚定最后一根已完成 15m Bar

现行 `subing_strategy_v1` 的正式 Action 可能在 5 分钟确认边界形成，而该时刻所在的 15 分钟 Bar 尚未完成。R1/R2 不得把形成中的 15 分钟 Bar 用于 EMA21、ATR、偏离、偏度或峰度计算。

对每个 parent Action 定义：

```text
feature_bar_end = max(
    bar_end
    where frequency = 15m
      and physical_contract = parent.physical_contract
      and bar_end <= parent.confirmed_at
      and bar is completed
)
```

约束：

1. `feature_bar_end` 是 R1/R2 唯一特征锚点；
2. parent `confirmed_at` 之后才结束的 15 分钟 Bar 一律不可见；
3. child 接受/拒绝仍在 parent `confirmed_at` 同时完成，不得等待下一根 15 分钟 Bar 后追认；
4. 找不到同物理合约完成锚点、窗口不足、数据非有限或时间不单调时，child 为 `FEATURE_BAR_UNAVAILABLE`；
5. unavailable 不影响 R0 正式 Action、Episode、Event 或 Alert；
6. prefix 测试必须覆盖“5m 确认发生在 15m Bar 内部”的样例，并证明追加该 15m Bar 的剩余数据不会改变既有 child 决策。

### 1.1 R1 修正规则

令 `k` 为 `feature_bar_end` 对应的完成 15m Bar：

```text
DeviationATR_i = (close_i - EMA21_i) / ATR14_i
```

多头：

```text
min(DeviationATR_(k-8)..DeviationATR_(k-1)) <= -1.0
DeviationATR_k > DeviationATR_(k-1)
DeviationATR_k - prior_min >= 0.25
```

空头对称：

```text
max(DeviationATR_(k-8)..DeviationATR_(k-1)) >= +1.0
DeviationATR_k < DeviationATR_(k-1)
prior_max - DeviationATR_k >= 0.25
```

不得把 parent Action 所在的未完成 15 分钟 Bar 当作 `k`。

### 1.2 R2 修正规则

R2 的 60 个对数收益窗口同样以 `k` 结束，并要求 `k-1` 与 `k` 都是同一物理合约段的完成 15 分钟 Bar：

多头：

```text
Skew60_(k-1) <= -0.50
ExcessKurtosis60_(k-1) >= 1.00
abs(Skew60_k) < abs(Skew60_(k-1))
```

空头对称：

```text
Skew60_(k-1) >= +0.50
ExcessKurtosis60_(k-1) >= 1.00
abs(Skew60_k) < abs(Skew60_(k-1))
```

追加 `parent.confirmed_at` 之后的数据不得修改 R2 的接受/拒绝结果。

## 2. T2 退出计算与 reason precedence 固定

T2 对 completed D1 Bar `t` 的固定处理顺序为：

```text
1. 在 open 应用上一完成 Bar 已确认且有下一同物理合约 Bar 的 pending Action
2. 使用 trail_(t-1) 判断当前 close 是否 breach
3. 判断当前 completed D1 是否形成 EMA21 opposite cross
4. 根据稳定优先级生成至多一个 exit Action
5. 退出 Action 在下一根同物理合约 D1 open 生效
6. 完成退出判断后，才使用当前 high/low/ATR 更新 trail_t
```

同一 Bar 多条件同时满足时，reason precedence 固定为：

```text
CONTRACT_SEGMENT_END
> EMA21_OPPOSITE_CROSS
> ATR_TRAIL_BREACH
```

补充约束：

- `CONTRACT_SEGMENT_END` 不允许虚构跨合约成交价；若不存在下一根同物理合约 D1 open，`close_effective_at` 和 reference exit price 为 unavailable，该 Episode 不进入完整 reference-change 统计；
- 第一根 effective-entry D1 没有 `trail_(t-1)`，不能用同一 Bar 新生成的 trail 退出；
- 当前 Bar 的新高/新低只能影响 `trail_t`，不能反向改变当前 Bar 是否退出；
- batch 与 incremental 输出必须在 exit reason、confirmed time、effective time、trail before/after 上逐字段一致。

## 3. T3 V1 不输出未定义的“衰竭/出货”标签

基线文档列出的 `EXHAUSTION_RISK` 缺少冻结公式，且手册没有提供可复算的 proprietary 定义。T3 V1 的允许标签收敛为：

```text
EXPANSION_CONFIRMED
LOW_PARTICIPATION
STAGE_UNAVAILABLE
```

其中：

- `EXPANSION_CONFIRMED`：`ER20 >= 0.35`、`VolumeRatio20 >= 1.20`、`OIDelta5 > 0` 全部成立；
- `LOW_PARTICIPATION`：特征全部可用，但至少一个 Gate 未通过；
- `STAGE_UNAVAILABLE`：窗口、成交量、持仓量、物理段、时间或有限性任一不满足。

禁止在 T3 V1 中输出或暗示：

```text
主力吸筹
主力洗盘
主力拉高
主力出货
EXHAUSTION_RISK
```

后续若研究衰竭或出货，必须新建 candidate/version，并在查看 OOS 前单独冻结公式和 Gate。

## 4. 新增强制验收样例

实现前必须将以下 fixtures 写入任务验收：

1. parent Action 在 15m Bar 中途由 5m 确认，R1/R2 只能读取上一根 completed 15m；
2. 追加当前 15m Bar 剩余 5m/1m 数据后，旧 child 决策不漂移；
3. EMA21 opposite cross 与 ATR trail breach 同 Bar 发生，只输出 `EMA21_OPPOSITE_CROSS`；
4. 物理合约段结束但没有下一同合约 open，不生成伪 exit fill；
5. 当前 D1 同时创新高并跌破旧 trail，只允许旧 trail 决定当前退出，新高只更新未使用的 `trail_t`；
6. T3 缺失 OI 时必须 `STAGE_UNAVAILABLE`，不得降级为只看量价；
7. T3 输出中不得出现吸筹、洗盘、拉高、出货或衰竭标签。

## 5. Gate 结论

在本文与基线设计共同获得人工批准前：

```text
DESIGN_REVIEW_PENDING
IMPLEMENTATION_BLOCKED
```

即使文档 PR 获准合入 `develop`，也只代表研究合同被接受，不代表任何候选公式、历史表现、盈利能力、正式策略、Alert 或 Runtime 获得批准。
