# Market Radar Freshness Watermark Spec

## 1. 背景

v1.6.1 已解决 Market K 线页面在收盘后 Canonical 接管前的 intraday 展示空窗，但 Market Radar 首页仍存在盘后数据发布时间差问题。

当前 Radar 使用交易日 watermark 判断数据完整性：

- target trading day 已进入当天收盘状态；
- Canonical 日线尚未完成盘后更新；
- 所有品种被判定 stale；
- 首页出现 0/60，无法继续观察。

本任务解决的是 freshness 语义错误，不改变数据事实来源。

## 2. 目标

建立 Radar 的 freshness watermark 模型：

```
target_as_of
    ↓
市场理论最新交易日

data_as_of
    ↓
Radar 实际计算使用的 Canonical 日期

freshness_state
    ↓
current
pending_after_market
degraded
```

## 3. 设计原则

必须保持：

- Canonical Parquet 是正式历史事实；
- MarketDataService 是历史读取唯一入口；
- Redis Live 不进入 Radar 指标计算；
- 不生成临时日线；
- 不修改 Data Foundation、Catalog、MainContractMap。

Radar 仍然是 Canonical Research Snapshot。

## 4. 行为定义

### 正常盘中

```
target_as_of = data_as_of
freshness_state = current
```

### 收盘后盘后任务未完成

```
target_as_of = 2026-08-20
data_as_of   = 2026-08-19
freshness_state = pending_after_market
```

展示完整 2026-08-19 Radar，不标记全部 stale。

### 真实数据异常

```
data_as_of = 2026-08-19
jm latest = 2026-08-18
```

只标记 jm stale。

## 5. Backend Contract

MarketRadarSnapshot 增加：

```text
target_as_of
data_as_of
freshness_state
freshness_message
```

保留：

```text
items
attention
sector_summary
stale
unavailable
```

## 6. Freshness Resolution

计算流程：

1. 获取 target_as_of；
2. 找到最近完整 Canonical 日线 snapshot；
3. 使用该 snapshot 计算 Radar；
4. 比较 target_as_of 与 data_as_of；
5. 生成 freshness_state。

禁止：

- 使用 Redis Live 修补日线；
- 混合两个交易日数据；
- 为 freshness 建立第二套数据状态表。

## 7. Web 展示

首页摘要区域需要展示：

当前数据日期：

```
data_as_of
```

目标交易日：

```
target_as_of
```

状态：

- 当前完整
- 盘后更新待完成
- 数据异常

## 8. 验收标准

必须满足：

- 收盘后 Canonical 未更新：首页仍显示完整 Radar；
- 不出现 0/60；
- 显示 pending_after_market；
- Canonical 更新后自动恢复 current；
- 单品种缺失只影响单品种；
- 周末/非交易日无错误 pending；
- 不改变 K 线 post_close 行为；
- 不改变 Live Observation 边界。
