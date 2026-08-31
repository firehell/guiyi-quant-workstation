# range-detector Specification

## Purpose

定义 `range_detector_lux_v1` 的纯计算、因果可见性和受限 consumer 合同。它是只读显示和
`subing_daily_trend_research` 的策略候选输入，不授予现有策略、Alert、Runtime、数据写入或订单能力。

## Requirements

### Requirement: 固定公式与 completed 输入

Range Detector SHALL 使用 `minimum_range_length=20`、`range_width_atr_multiplier=1.0`、
`range_atr_length=500`、close source、Wilder SMA-seed ATR 与 six-decimal rounding。舍入 MUST 以有限
IEEE 值的 canonical decimal representation 为输入，先把定点或指数形式归一为十进制整数系数与十进制
指数，再执行 decimal half-even；不得使用语言默认的 binary `round`、`toFixed` 或 locale。输入 MUST 是按
严格递增 ISO-8601 时间排列的 completed Bar；无效 OHLC MUST fail-closed 并 reset ATR、候选窗口和 active range。

#### Scenario: 默认参数

- **WHEN** consumer 未覆盖任何参数
- **THEN** Kernel 使用固定 V1 参数且不从其他周期、前值或零值补齐

#### Scenario: 无效 Bar

- **WHEN** high、low 或 close 缺失、非有限或不满足 OHLC 边界
- **THEN** 输出 `invalid_reset`，历史箱体不得跨越该 Bar

#### Scenario: 六位 half-even 舍入与突破边界

- **WHEN** 上下沿落在正或负的六位 decimal tie，或 close 只严格越过舍入后的边界
- **THEN** Python 与 TypeScript MUST 得到同一 half-even 边界和 break；定点/指数 canonical 表示不得改变结果

### Requirement: 回画与因果可见性分离

candidate 确认时 SHALL 设置 `visual_start_at=bar_end[t-L]` 和 `confirmed_at=bar_end[t]`。Web MAY 从
`visual_start_at` 回画箱体；策略 MUST 只从 `confirmed_at` 后，并且只读取前一 Bar 已确认的 intact snapshot。

#### Scenario: 首次确认

- **WHEN** ATR 与 L+1 close warm-up 完整且 candidate 为真
- **THEN** 本 Bar 输出 confirmation，前置历史 Bar 不获得策略可见性

### Requirement: identity、revision 与精确突破

range id MUST 是 `range_detector_lux_v1|source_identity|first_confirmed_at` 的 lowercase SHA-256。重叠
candidate SHALL 保持 range id、递增 revision 并仅自新 `confirmed_at` 起使用 envelope；`close == upper/lower`
MUST 保持 intact，严格越界才形成一次 break。

#### Scenario: overlap revision

- **WHEN** 新 candidate 的 visual start 不晚于上一 detection right
- **THEN** 保留 range identity、扩展 envelope、递增 revision，且不改写此前决策

#### Scenario: 突破边界

- **WHEN** close 等于当前 upper 或 lower
- **THEN** state 保持 intact

### Requirement: 可复算 parity

同一输入前缀的 batch、incremental 和浏览器显示镜像 SHALL 产生同一 range id、边界、revision、confirmation
与 break。future tail 或更晚 prepend 不得改写已有完整 warm-up 的 point 前缀。

#### Scenario: 共享 golden

- **WHEN** Python 或 TypeScript 读取 `range_detector_lux_v1_golden.json` 与舍入边界 golden
- **THEN** 两者验证除 `payload_sha256` 外所有顶层字段的稳定 SHA-256，并匹配 points 与 visual ranges

### Requirement: scoped consumer policy

FormalPolicy SHALL 仅允许 `range_detector_readonly_display` 与 `subing_daily_trend_research`。它 MUST block
formal backtest、generic strategy/live、Alert 与 notification consumer。

#### Scenario: 未授权 consumer

- **WHEN** generic 或 Alert consumer 请求该 policy
- **THEN** `require_formal_policy` fail-closed

### Requirement: retrospective display does not grant strategy visibility

Historical `RangeDetectorVisualRange` SHALL 单独表示 `levels_active_until`，不得把未来结束时间塞入增量
snapshot。Range 的 display backpaint MUST NOT 改写因果 point 或授予历史策略可见性。

#### Scenario: 结束 active levels

- **WHEN** 后续 confirmation、revision 或 invalid reset 终止上一 range
- **THEN** Historical visual range 派生结束时间，而 incremental state 不预填未来时间
