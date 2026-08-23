# 日进斗金 JM 1m Shared Strategy Kernel Review

日期：2026-08-23

## Review 结论

对 `docs/superpowers/specs/2026-08-23-jdj-jm-1m-shared-strategy-kernel-design.md` 与 `docs/superpowers/plans/2026-08-23-jdj-jm-1m-shared-strategy-kernel.md` 做完整架构审查。

结论：方向正确，但正式实现前需要修正以下边界。

## 必须修正项

### 1. 不应在第一阶段迁移整个 N Structure Research 实现

原计划容易让 Codex 误解为：

```
app/research/n_structure
        ↓
app/strategy_kernel/n_structure
```

整体迁移。

修正：

只抽取被 JDJ 依赖的纯因果计算：

- N snapshot reducer；
- swing pivot reducer；
- segment evaluation；
- immutable policy/value objects。

保留：

- candidate validation；
- research report；
- robustness；
- CLI；
- HTTP projection。

原因：Strategy Kernel 是交易语义层，不是 Research 重命名目录。

---

### 2. Strategy Kernel 不应直接依赖 CanonicalBar 命名

当前 Spec 中多处使用 `CanonicalBar`。

修正：

Kernel 接受最小 bar protocol/value object，而由 adapter 转换：

```
MarketDataService CanonicalBar
          |
          v
JdjMarketBar
          |
          v
Strategy Kernel
```

原因：未来 RQAlpha Bundle bar 与 Historical Replay bar 可能不是同一类型。

Kernel 应定义交易需要的数据合同，而不是绑定存储实现。

---

### 3. RQAlpha dominant schedule 需要明确版本身份

原设计只描述：

```
MainContractMap
→ dominant_schedule.json
```

修正增加：

```
dominant_schedule_version
mapping_source
created_at
trading_day_range
```

原因：回测复算必须知道当时使用哪份主力映射。

仍保持：

- 不包含 OHLCV；
- 不替代 RQAlpha Bundle 数据。

---

### 4. 首次实现不要同时完成 Market 主图和 RQAlpha Adapter

原 Plan 顺序容易导致范围过大。

调整实现优先级：

```
Phase 1
Shared Kernel + parity

Phase 2
JDJ execution replay

Phase 3
Market overlay

Phase 4
RQAlpha adapter
```

原因：

如果 Phase 1/2 的交易生命周期错误，主图和回测都会复制错误。

---

### 5. 风控参数需要区分 policy 和 profile

修正：

作者交易规则：

```
minimum_reward_risk
max_daily_loss
profit_add_rule
```

属于 strategy policy。

焦煤适配：

```
contract_multiplier
margin
risk_fraction
stop_buffer_ticks
```

属于 profile/instrument adaptation。

禁止以后通过品种调参修改交易理念。

---

### 6. 加仓状态需要增加 episode 概念

当前描述有：

```
max_add_count
```

但不足以防止重复加仓。

补充：

每一次 Entry 创建：

```
TradeEpisode
```

包含：

- episode_id；
- setup；
- initial_entry；
- add_count；
- partial_profit_taken；
- stop_state。

所有加仓必须属于同一 episode。

---

## 保留不变项

以下设计确认正确：

- JDJ 三个 Candidate 作为 Entry 来源；
- strict-before 因果约束；
- actual_dominant physical contract segment；
- 不跨合约传播状态；
- 不建设 StrategyBase 平台；
- 不自动优化参数；
- 不自动晋升 Candidate；
- RQAlpha 仅 research-only；
- 不接 Runtime/Alert/订单。

## 对 Implementation Plan 的调整要求

Codex 执行前应追加：

1. Task 0：完成 dependency direction review。
2. Task 1：只抽取 pure kernel，不整体迁移 research。
3. Task 2：增加 JDJ golden parity fixtures。
4. Task 3：先完成 execution replay，再接 Web/RQAlpha。

## 最终判断

状态：

允许继续实现，但必须按本 Review 修正 Plan 后执行。
