# TASK-MARKET-RADAR-FRESHNESS-WATERMARK

## Task

修复 Market Radar 在盘后 Canonical 更新窗口内错误显示 0/60 stale 的问题。

## Lane

Lane 2：常规工程。

原因：

- 修改已有 Market Web/API；
- 不改变 Runtime、Canonical、Live、通知或数据写入边界。

## 目标

实现 Radar Freshness Watermark：

- 区分 target_as_of 与 data_as_of；
- 支持 pending_after_market 状态；
- 保持最近完整 Canonical Radar 可展示。

## 修改范围

允许：

- MarketRadarSnapshot contract；
- Radar service freshness resolution；
- Market API schema；
- Web summary/freshness 展示；
- 相关测试。

禁止：

- 读取 Redis Live 计算临时日线；
- 修改 Canonical 写入流程；
- 修改八表 Catalog；
- 修改 MarketDataService 合同；
- 修改 after-market updater 行为；
- 引入新的持久化状态表。

## 推荐实现步骤

### Task 1

扩展 Radar domain contract。

验收：

- API 可以表达 target/data/freshness。

### Task 2

调整 Radar snapshot resolution。

验收：

- Canonical 落后一交易日时，不进入全量 stale；
- pending_after_market 可识别。

### Task 3

调整 Web 展示。

验收：

- 用户可以区分数据日期和目标日期；
- 不再显示误导性的 0/60。

### Task 4

补充测试。

必须覆盖：

- 收盘后 Canonical 未更新；
- Canonical 已更新；
- 单品种真实缺失；
- 周末/非交易日；
- API/Web regression。

## 完成标准

完成后只能说明：

"Market Radar 在盘后 Canonical 更新窗口内保持可观察，并正确表达 freshness 状态。"

不得声明：

- 策略有效；
- 数据实时；
- Live 已进入 Radar；
- Runtime promotion 完成。
