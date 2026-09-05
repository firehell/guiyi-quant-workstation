# 牛哇 v3.2.82 策略与指标复刻总结

> 仓库分发说明：这是 2026-09-04 研究现场的报告副本。当前项目范围已经将六种私有服务端选股公式明确设为 `UNKNOWN / OUT_OF_SCOPE`，不再继续反推；报告中与“继续采集第二截面”相关的历史下一步不代表当前计划。原始网页、逐 Bar 输入和 RQData/Canonical 原文未随 GitHub 资料包分发，详见 [README](README.md#github-分发边界)。

状态：`PARTIAL / REAL_OOS_REPLAY_BUNDLE_PENDING / REAL_WEEKLY_OOS_GATE_PENDING / FINAL_REVIEW_BLOCKED`
证据日期：2026-09-04
用途：只读研究观察，不是交易指令。

## 结论

牛哇的主体不是单一“神奇指标”，而是一个分层决策框架：

```text
黄蓝趋势带定市场阶段
  -> HHV/LLV 震荡通道定吸筹与拉高节奏
  -> 周线定方向，日线定阶段，60 分定节奏
  -> D1-D6、11 周期、主升浪、副图解释风险
  -> 13 格综合决策输出仓位区间和等待/风险 token
  -> 选股只缩小候选池，返回详情页核对
```

归一已把公开可证的公式实现为独立 Quant Core，并通过只读 API 与 typed Web 展示。页面一致身份与可信因果研究身份已强制隔离。

未完成的不是一个被隐藏的已知公式，而是三类证据 Gate：私有服务端选股公式缺少第二个独立截面；现有 18 个 passed OOS 单元需要把 Canonical Bar 输入与重放脚本一起冻结；周线 OOS 缺少能区分“周 K 波动范围”与“下一开盘执行日涨跌停”的可信合同。

## 怎么采集的

| 证据 | 采集方法 | 完整性校验 | 用于反推 |
|---|---|---|---|
| 首页、详情页、共享策略 JS、选股页 | 公开匿名 GET，不带 Cookie/Token | URL、字节数、SHA-256 | 版本、指标说明、参数窗口、决策控制流 |
| 3 指数 + 6 股票的 week/day/60min | 页面自身发起的匿名 `GET /api/kline` | 27 个独立响应文件和唯一 hash，离线逐值重算 | HHV10/LLV10、趋势/主升浪状态、综合决策输入输出 |
| 6 股当日多周期信号 | 公开匿名 `GET /api/batch` | 原始响应 SHA-256 | `signal_weekly/daily/60min` 到综合决策的桥接 |
| 6 个技术选股策略 | 复刻前端请求体，只读分页 POST 拉完当日截面 | 每页原始响应、行数、代码集和 hash | 证伪“策略名等于当根信号”，但不猜私有公式 |
| rb/sc/m 期货 | 先前授权的只读 Catalog/MainContractMap/Canonical 运行，未调 RQData 下载 | 原始、归一、OOS 三层快照及 SHA-256 manifest | actual-dominant owner、换月、成本、tick、limit、OOS |

2026-09-04 再次检查浏览器控制时，tab inventory 能看到 v3.2.82，但内置页与 Chrome 页的读取都在 30 秒超时。所以本报告只使用已冻结的原始响应、页源码和截图，不把“能看到标签页”写成“可交互采集”。

## Observed UI facts

页面可直接观察到黄/蓝趋势带、S 跑与 D 系列 marker、HHV10/LLV10 目标/吸筹通道、三周期状态、综合决策、确定度、波动率与第一行动文案。这些都是观察事实，不等于对私有服务端选股公式的证明。

上证指数周线：

![上证指数周线趋势页](screenshots/000001-SH-week-trend.png)

宁德时代日线：

![宁德时代日线趋势页](screenshots/300750-SZ-day-trend.png)

招商银行 60 分：

![招商银行 60 分趋势页](screenshots/600036-SH-60min-trend.png)

## Manual claims

2026 手册提出“趋势定方向、震荡定节奏、周线大于日线大于 60 分”的操盘思路，并将 S 跑、主升浪和选股用作辅助。手册是 7 月版方向性证据，不覆盖 9 月页面实测，也不单独作为精确公式权威。

## Implementation hypotheses

下列每项都是基于页源码、原始响应与页面输出的可执行反推；能逐值重放的标为 page-parity，无法从公开面唯一确定的保持 clean-room 或 UNKNOWN。

### 1. 趋势黄蓝带

观察：页面用黄/蓝带表达可参与与应回避阶段，带状态和 BUILD/CLEAR 事件是后续组合逻辑的主干。

反推与实现：保留 `newow_trend_band_page_v2`。递归状态只在同物理合约 segment 内延续，换月重置；Web 只消费 API bands/markers，不复制公式。

### 2. S 跑、D1-D6 与 11 周期

观察：S 跑的解释对应逃顶/减仓风险系统，D1-D3 是风险解释，D4-D6 是建仓阶段标记；11 周期辅助表达结构转折。

实现身份：`newow_escape_d123_page_v2`、`newow_buy_d456_page_v1`、`newow_magic11_page_v1`。所有 marker 保留 bar_end、physical contract、segment 和 formula identity，禁止从未完成 Bar 生成正式事实。

### 3. 震荡策略与目标/吸筹价

公式主体：

```text
target_N[t] = HHV(high, N)
absorb_N[t] = LLV(low, N)
默认 N = 10
```

页面再依据周、日趋势信号和当前视图选择日或周通道，并以昨收 `[0.5, 2]` 倍 clamp；周线视图还有优先使用当前周线 HHV/LLV 的 v3.2.11 覆盖。实现为 `newow_target_absorb_hhv_llv10_page_v1` 与新身份 `newow_target_absorb_display_selection_page_v2`。

页面参数比较固定窗口 10/20/24/30/52，使用同 Bar close、零成本、收益相加和期末强平。这个版本只为 page-parity，`trustworthy_for_research=false`。可信版只允许 completed Bar 产生意图、下一根 Open 成交、显式费用/tick/limit，并且不在样本末伪造平仓。

### 4. 主升浪

公开页面核心是 MA35/MA45、J 风险与 D/11 周期结合，而不是一个独立“主升浪分数”。实现保留 `newow_main_rise_ma35_ma45_page_v1` 和 `newow_main_rise_j_reduce_page_v1`，同样按 owner segment 重置。

### 5. 综合决策

思路是“趋势定基调，震荡定节奏，大周期约束小周期”。页面有 13 个决策键，输出行动 token、仓位区间、确定性和风险 token。

页面源码的控制流先命中“周线空头”，后才检查“周空日多 warning”，所以 `warning-bullish/warning-bearish/warning-neutral` 三个矩阵键不可达。归一保留原缺陷的 `newow_composite_decision_page_v3_2_82`，另建 `newow_composite_decision_cleanroom_v1` 修正，禁止覆盖原身份。

确定性是趋势 30 + 震荡 30 + 一致性 20 + 方向 20；冲突时上限 60，中性时上限 85。日线 ATR20/Close 只调整风险解释，不修改决策矩阵。

### 6. 选股与杯柄

公开页能证明选股策略 ID、请求合同、返回字段与当日集合，但不能唯一确定私有服务端算法。因此 6 个 page-exact 策略保持 `UNKNOWN`。归一只实现三个强制 `page_parity=false` 的 clean-room candidate：趋势建仓、主升浪建仓、杯柄 READY/BREAKOUT。

## Parity results

- 标的：上证、深证、创业板 3 指数；格力电器、比亚迪、宁德时代、招商银行、贵州茅台、桐昆股份 6 只不同风格股票。
- 周期：week/day/60min，共 27 个精确页面点。
- 结果：通道目标/吸筹、多周期展示选择、五窗口排名、综合决策/仓位/方向、确定度四项、波动率/分档、第一行动 level/rule 共 16 个可比子项全部 27/27，`mismatch=0`。
- 参数比较器：不再只使用单一 601 根日线样本；现在对 27 个页面响应分别重放 10/20/24/30/52 五窗口，逐单元比较排名、收益、回撤、交易数、胜率和期末持仓状态。
- AI 自然语言文案和 diagnostic token 在页面没有稳定的 machine-readable 对照合同，各记 `unavailable=27`；前者只保存 hash，后者明确是 clean-room，不写成精确页面公式。

## Futures migration results

### 真实数据链

| 品种 | 经济组 | 1d Bars | 1w Bars | 60m Bars | 权威分段/换月 |
|---|---|---:|---:|---:|---:|
| rb | 黑色 | 484 | 101 | 3,362 | 7 / 6 |
| sc | 能化 | 484 | 101 | 5,246 | 25 / 24 |
| m | 农产品 | 484 | 101 | 3,362 | 7 / 6 |

9/9 series 通过。SC2302 权威段为 2023-01-03…2023-01-04：D1 有 2 根，60m 有 16 根，W1 有 0 根；W1 首根于 2023-01-06 结束且 owner 已为 SC2303。这是“全局 MainContractMap 权威分段”与“某周期实际拥有 Bar 的 owner 子集”不能强制相等的真实反例。

### 27 个 OOS 单元

27 = rb/sc/m × 1d/1w/60m × trend/oscillation/main_rise。18 个 passed 单元各有 baseline、双手续费和双滑点三个压力场景；9 个 blocked 周线单元只有 fail-closed reason，没有伪造场景结果。公式参数固定，没有 OOS 反向调参。

- 18 个日线/60 分单元 passed。
- 9 个周线单元 blocked，公开错误是 `NEWOW_WEEKLY_EXECUTION_LIMIT_CONTRACT_INSUFFICIENT`。
- 阻塞原因：周 K OHLC 覆盖整周，但 next-open 锁板判定应使用下一执行交易日的 limit；用周首或周末任一天 limit 同时去包住整周 OHLC 都会造成真实反例。
- 这 9 个不能通过宽松校验、删除 limit 或借用日线结果来“补齐”。

当前 18 个 passed 结果的数值可读，但冻结包还缺完整 Canonical Bar 输入和无数据库重放脚本，因此只能说“运行结果存在”，不能说“第三方可从冻结包独立复算”。这一点在新的只读 Canonical 快照未获授权前保持 Gate。

已完成单元的基准收益中既有正值也有明显负值；例如 sc 1d 震荡为正，而多数 trend 与多个震荡单元为负。本结果用于验证因果、成本和换月合同，不支持“盈利策略”或“可晋升候选”结论。

## Repository facts

- Quant Core 是唯一公式入口；API 负责调用和严格 Decimal/Literal 序列化；Web 只投影 typed facts。
- `ActualDominantResearchSegmentLoader` 分别读取 1d/1w/60m，对每根 Bar 以全局权威分段审核 owner，不跨周期推断。
- 页面线和 clean-room 线在 formula identity、类型、UI 说明上都隔离。
- 没有新增 Alert、Runtime、Scope、通知、订单、数据库表或 Canonical 写入路径。

## Rejected / Unknown

- `REJECTED`：页面同 Bar close、零成本、期末强平的参数排名直接晋升可信策略。
- `REJECTED`：照妖镜重绘输入进入正式信号或 OOS。
- `UNKNOWN`：`trend_build/mainrise_build/cup_handle/daily_buy/weekly_buy/oscillation_build` 的私有服务端 page-exact 公式。
- `UNKNOWN`：账号、自选、订阅、分享等私有状态行为。
- 边界外：扩建 A 股基本面/CANSLIM/大师选股平台。

## 证据索引

- 详细采集底稿：`report-source.md`
- 页面原始证据：`sources/`
- 离线验证器与派生快照：`analysis/`
- 27 张指数/个股截图：`screenshots/`
- 真实期货、成本和 OOS 快照：`futures/`
- 全包 SHA-256 清单：`evidence-manifest.json`

## Risks

当前最大风险不是指标数学未实现，而是把部分 OOS 或单日选股截面过度解读为可信盈利结论。

唯一最小下一步：授权一次只读 Catalog/Canonical 快照，冻结 9 条输入序列并完成 18 个 passed OOS 单元的无数据库独立重放。
