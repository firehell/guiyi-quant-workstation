# Newow 牛哇版本 · 日线趋势详情页 V1 Spec

日期：2026-09-01  
状态：`DESIGN_REVIEWED / IMPLEMENTATION_NOT_STARTED / IMPLEMENTATION_PLAN_REWRITE_REQUIRED`  
任务来源：用户提供的牛哇详情页截图、首页 D1/D2/D3 截图、v3.6 更新说明、详情页录屏与《牛哇盯盘：AI 可视化盯盘实战指南》  

> 本文是 Newow V1 唯一有效设计源，完整覆盖此前 `docs/tasks/2026-09-01-newow-trend-v1-design.md` 的旧内容。此前 Implementation Plan 与本 Spec 冲突的部分全部失效，在重写前不得执行。

## 1. 最终产品定义

第一版只交付一个产品：

> **牛哇版本 · 趋势策略 · 日线详情页。**

它的目标不是先扫描 active60、发送通知或证明收益，而是先把牛哇趋势策略本身和牛哇详情页的主图体验复原正确。

用户使用链路：

```text
进入期货品种详情
→ 在“当前版本 / 牛哇版本”之间切换
→ 牛哇版本固定进入“趋势策略 · 日K”
→ 查看黄蓝趋势带、建仓/清仓标记、D1/D2/D3、杯柄与成交量
→ 点击标记查看牛哇式指标解读
→ 用户自行判断是否值得参与
```

归一量化只向 Newow 提供：

```text
actual_dominant
真实物理合约段
Canonical completed D1 OHLCV
open_interest（可用时）
trading_day / Session / Calendar
主力换月边界
```

Newow 不消费或继承任何已退役策略、HTDY、现有趋势观察、Alert、Episode、Context 或前端指标结果。

## 2. 产品价值

V1 的价值不是“替用户交易”，而是：

1. 用牛哇自己的趋势视觉，把一段日线行情快速压缩成“建仓、持有、清仓、空仓”四种状态；
2. 在主趋势正式转弱前，用 D1/D2/D3 提前显示不同级别的顶部风险；
3. 在趋势整理中识别杯柄，辅助用户判断是否处于高质量突破准备阶段；
4. 让用户在一个页面内看到趋势状态、历史切换、风险标记、杯柄结构和成交量，而不必在多个副图之间切换；
5. 先证明“页面行为与牛哇足够接近、用户能快速复核”，再讨论全市场扫描、Shadow 或提醒。

## 3. 参考权威与不确定项规则

### 3.1 参考权威顺序

```text
1. 用户提供的牛哇真实页面录屏
2. 用户提供的牛哇真实页面截图
3. 《牛哇盯盘》中的真实页面截图
4. 牛哇页面与手册中的明确文字说明
5. 本文明确标注的 clean-room 推导
6. 无证据：不实现
```

### 3.2 参考集合

V1 当前参考集合包括：

- 牛哇详情页完整纵向录屏：顶部信息、策略 Tab、主图、建仓/清仓标记、成交量、底部指标 Tab、指标解读弹层、历史列表与首页返回；
- 牛哇详情页截图：顶部品种信息、日K选择、趋势策略选中状态；
- `主力控盘 · 指标解读`、`主力动态 · 指标解读`、`涨跌动能 · 指标解读`三张弹层截图；
- 首页 `D1/D2/D3` 逃顶说明截图；
- v3.6 杯柄引擎更新说明截图；
- 手册中的黄蓝四状态、建仓/清仓、杯柄与主图案例。

### 3.3 不确定项处理

任何尚未被参考资料支持的内容不得通过下列方式补齐：

```text
不得用已退役策略或当前版本逻辑补齐
不得用“常见指标”静默替换
不得根据历史收益调参
不得为了视觉更好自行增加功能
不得把 clean-room 推导描述成牛哇私有公式
```

本文已经选择的 clean-room 公式必须带独立版本身份，并通过牛哇历史截图做视觉校准；若后续真实页面证明不一致，发布新公式版本，不改写旧结果。

## 4. V1 范围

### 4.1 包含

```text
当前版本 / 牛哇版本入口切换
牛哇风格的日线趋势详情页外壳
期货品种与 actual-dominant 信息区
日K主图
牛哇黄蓝趋势带
建仓 / 清仓历史标记
当前“建仓 / 持有 / 清仓 / 空仓”状态
D1 / D2 / D3 逃顶标记与说明弹层
杯柄形成、就绪、突破、失效的主图覆盖层
成交量柱
主力换月分界
牛哇式指标解读弹层
同一品种的历史信号列表入口
```

### 4.2 明确不包含

```text
牛哇震荡策略
牛哇主升浪策略
牛哇 AI 分析
综合决策、策略打分、仓位建议
周线 / 60m / 15m / 5m / 1m
主力照妖镜副图
涨跌动能副图
主力控盘副图
策略收益率曲线
目标价、吸筹价和对应点阵
吸筹 / 洗盘 / 拉高 / 出货副图算法
其他命名形态
首页选股、热门板块与逃顶榜
active60 扫描
Shadow、PushPlus、Alert 或 Runtime
仓位、订单、保证金、账户和实际盈亏
```

其中 D1/D2/D3 所需的 `VAR4` 只作为内部计算输入，不绘制“涨跌动能”副图。

## 5. 产品身份

```text
display_name       = 牛哇趋势策略
product_view       = newow
strategy_code      = newow_trend_v1
formula_version    = newow_trend_band_cleanroom_v1
profile_id         = newow_trend_d1_v1
series_kind        = actual_dominant
frequency          = 1d
bar_policy         = completed_only
live_capable       = false
alert_capable      = false
auto_order         = false
```

杯柄身份：

```text
setup_code         = newow_cup_handle_v1
setup_profile      = newow_cup_handle_d1_v1
```

逃顶身份：

```text
indicator_code     = newow_escape_d123_v1
var4_formula       = newow_var4_cleanroom_v1
```

## 6. 页面架构

### 6.1 页面隔离

采用同一品种入口下的两个独立详情实现：

```text
MarketDetailShell
├── CurrentDetailView   # 当前页面保持原样
└── NewowTrendDetailView
```

两者只共享：

```text
product
contract
series identity
visible time range
返回目标
```

两者不共享：

```text
指标配置
趋势状态
标记
Tooltip
图层开关
策略说明
```

不得继续把 Newow 作为现有 `chart.vue` 中的一组复杂 overlay 条件堆叠。路由外壳负责选择子页面，Newow 使用独立组件树。

### 6.2 路由

推荐：

```text
/market/chart?symbol=RB&view=current
/market/chart?symbol=RB&view=newow
```

切换时保留：

```text
symbol
actual contract
visible from/to
```

Newow V1 强制：

```text
series_kind = actual_dominant
frequency   = 1d
strategy    = trend
```

若 URL 请求其他周期，页面显示“牛哇趋势 V1 仅支持日K”，不静默回退或跨频读取。

## 7. UI 与交互合同

### 7.1 总体原则

- 移动端优先，布局、圆角、留白、彩色标签、弹层结构、按钮层级参考牛哇真实页面；
- 桌面端只允许响应式扩宽，不重新组织信息层级；
- 不支持的功能直接省略，不渲染无法点击的假按钮；
- included flow 的交互必须与参考一致，未知细节进入视觉 Review，不由开发者自由发挥。

### 7.2 顶部栏

包含：

```text
返回
日K周期胶囊
收藏
历史
```

行为：

- 返回：回到进入详情前的页面；
- 日K：V1 只显示日K，不开放其他周期；
- 收藏：复用现有本地偏好或已有收藏能力，不新增服务端表；
- 历史：打开当前品种的 Newow 历史标记列表，只包含建仓、清仓、D1/D2/D3、杯柄就绪/突破/失效。

### 7.3 版本切换

在详情外壳增加：

```text
当前版本 | 牛哇版本
```

这不是牛哇原生控件，而是归一量化的产品入口。切换后主体完全由相应子页面接管。

### 7.4 品种信息区

参考牛哇详情头部，适配期货字段：

```text
品种中文名
当前实际主力合约
最新 completed D1 日期
收盘价
涨跌值 / 涨跌幅
最高 / 最低 / 开盘
成交量
持仓量（可用时）
“主力”身份标签
```

股票特有的市值、换手率不展示，也不自行映射成其他字段。

### 7.5 策略导航

V1 只渲染一个可用策略 Chip：

```text
趋势策略
```

使用牛哇参考中的橙色选中样式。`震荡策略 / 主升浪 / AI分析` 不渲染，避免出现无实现入口。

### 7.6 主图区

顺序固定：

```text
日K主图
成交量
主图图例 + 指标解读
```

不渲染底部三个副图 Tab 和收益曲线。

### 7.7 指标解读弹层

采用牛哇参考样式：

```text
半透明遮罩
白色大圆角卡片
居中标题
彩色重点说明
规则列表
底部“知道了”按钮
```

V1 提供三个解读页：

```text
趋势策略 · 指标解读
D1/D2/D3 · 指标解读
杯柄形态 · 指标解读
```

### 7.8 标记点击

点击任一主图标记时打开详情卡：

```text
标记名称
日期
信号Bar OHLCV
状态变化
触发条件逐项结果
公式版本
说明
```

不得显示自动下单、仓位或收益承诺。

### 7.9 十字线与缩放

复用现有 KlineChart 的平移、缩放和十字线能力；十字线附加显示：

```text
当日黄蓝状态
当日建仓/清仓标记
当日D1/D2/D3
当日杯柄状态
```

## 8. 主图图层

### 8.1 V1 图层顺序

从底到顶：

```text
1. K线与网格
2. 黄蓝趋势带
3. 成交量
4. 杯柄轮廓与柄部区间
5. 建仓 / 清仓标记
6. D1 / D2 / D3 标记
7. 十字线与选中态
8. 主力换月分界
```

### 8.2 不实现的牛哇图层

录屏中可见但 V1 不实现：

```text
目标价水平线
吸筹价水平线
红绿点阵
主力动态副图
涨跌动能副图
主力控盘副图
收益率曲线
```

没有公式证据的图层不得用相似指标占位。

## 9. 数据合同与期货适配

输入对象：

```text
NewowDailyBar
├── product
├── physical_contract
├── segment_id
├── trading_day
├── bar_end
├── open
├── high
├── low
├── close
├── volume
├── open_interest optional
├── source_identity
└── completed = true
```

硬边界：

1. 只通过 `MarketDataService` 读取；
2. `actual_dominant` 只由 `MainContractMap` 拼接，Newow 不自判主力；
3. 趋势状态、VAR4、MA120、杯柄和历史收益标记均不得跨真实物理合约段；
4. 同一物理合约成为 rank1 前的日线可用于纯数值 warm-up，但正式标记不得早于 rank1 segment start；
5. 换月时旧趋势状态终止，新合约重新 warm-up，不把换月跳空解释成建仓、清仓、D1/D2/D3 或杯柄突破；
6. 夜盘与白盘由 Canonical `trading_day` 合成一根权威日线；
7. 突破使用 `close`，不以 settlement 替代；
8. OI 缺失不影响黄蓝带和 D1/D2/D3，杯柄量能仍使用 volume；页面明确显示 OI unavailable。

## 10. 计算流水线

唯一逐 Bar 入口：

```python
NewowTrendD1Engine.step(completed_d1_bar)
```

顺序固定：

```text
1. 校验数据和同合约身份
2. 更新黄蓝趋势带数值
3. 生成建仓 / 清仓状态切换
4. 更新 MA120、VAR4、30日振幅和 D1/D2/D3
5. 更新杯柄候选及其状态
6. 冻结该Bar主图 Snapshot
7. 生成当日新增不可变 Marker Event
```

Historical 与后续盘后增量必须调用同一个 `step`，不得维护两套公式。

## 11. 黄蓝趋势带 V1

### 11.1 公式定位

牛哇公开确认了黄蓝四状态语义，但未公开完整公式。V1 使用此前详情页中出现的 `HHJSJDB / HHJSJDC` 线索建立独立 clean-room 公式：

```text
newow_trend_band_cleanroom_v1
```

它是可替换的复原版本，不宣称等于牛哇私有实现。

### 11.2 公式

典型价格：

```text
P_t = (3 × Close_t + Open_t + High_t + Low_t) / 6
```

20期线性加权趋势线：

```text
B_t = (20P_t + 19P_t-1 + ... + 1P_t-19) / 210
```

5期信号线：

```text
C_t = SMA(B_t, 5)
```

状态：

```text
B_t >= C_t  → YELLOW
B_t <  C_t  → BLUE
warm-up不足 → UNAVAILABLE
```

V1 不引入第三种中性颜色，因为牛哇主图明确使用黄/蓝二态。

### 11.3 状态语义

```text
BLUE → YELLOW = BUILD / 建仓
YELLOW → YELLOW = HOLD / 持有
YELLOW → BLUE = CLEAR / 清仓
BLUE → BLUE = EMPTY / 空仓
```

蓝色在 V1 中表示空仓/风险阶段，不表示建立期货空单。

### 11.4 主图绘制

数据层返回 `B` 和 `C`。前端：

- 以 B/C 之间的区域绘制粗阶梯带；
- 当前区间为 YELLOW 时使用牛哇黄色；
- 当前区间为 BLUE 时使用牛哇深蓝色；
- 当 B/C 距离小于屏幕可见厚度时，仅做像素层最小厚度处理，不改变价格数据；
- 色带只在完成日线后变化。

### 11.5 视觉校准 Gate

实现阶段必须从录屏和后续牛哇截图建立不少于 10 个历史窗口，逐项比较：

```text
转黄日期
转蓝日期
色带相对K线的位置
色带连续性
建仓/清仓位置
```

若关键转折无法达到可接受一致性，不通过 Review；不得通过优化历史收益选择参数。

## 12. 建仓、持有、清仓、空仓

### 12.1 标记

蓝变黄的完成日线生成：

```text
NEWOW_BUILD_MARKER
UI：建仓 / 建仓价:{signal_close}
```

黄变蓝的完成日线生成：

```text
NEWOW_CLEAR_MARKER
UI：清仓 / {signal_close}({reference_change_pct:+.2f}%)
```

持有和空仓只表达当前状态，不逐日生成标记。

### 12.2 参考变化

```text
reference_change_pct =
(clear_signal_close / last_build_signal_close - 1) × 100
```

该值只用于复刻牛哇历史图上的区间变化展示，必须标记为：

```text
策略信号参考变化
非真实成交
未计手续费、滑点、涨跌停和换月
```

### 12.3 事件不可变

Marker Event 生成后不修改。后续数据不得改写：

```text
event_id
bar_end
state_before
state_after
signal_close
formula_version
```

## 13. D1 / D2 / D3 逃顶模块

### 13.1 内部 VAR4

用户提供的截图确认 VAR4 使用 95、93、90 三个高位阈值，但未展示公式。V1 使用与该阈值语义一致的 clean-room 随机强度值：

```text
RSV9_t =
100 × (Close_t - LLV(Low, 9))
    / (HHV(High, 9) - LLV(Low, 9))
```

若分母为0，则 RSV9 沿用上一有限值；首个值为50。

中国式平滑：

```text
VAR4_t = SMA_CN(RSV9, 3, 1)
VAR4_t = (RSV9_t + 2 × VAR4_t-1) / 3
```

初始值使用首个有限 RSV9。

交叉定义：

```text
cross_down(x, level) = x_t-1 >= level AND x_t < level
```

### 13.2 MA120 与辅助量

```text
MA120_t = SMA(Close, 120)
```

30日振幅：

```text
Amplitude30_t =
(HHV(High, 30) - LLV(Low, 30)) / LLV(Low, 30)
```

MA120 10日标准化斜率：

```text
MA120Slope10_t =
OLS_Slope(MA120[t-9:t]) / MA120_t
```

走平：

```text
abs(MA120Slope10_t) <= 0.0005
```

向下：

```text
MA120Slope10_t < -0.0005
```

以上阈值属于 V1 clean-room 解释，后续牛哇真实页面若提供精确定义，创建新公式版本。

### 13.3 D1：★S逃命

截图含义：高位急转，最强烈逃顶警示。

V1：

```text
cross_down(VAR4, 95)
AND Close_t > MA120_t
AND (Close_t - MA120_t) / MA120_t >= 0.30
```

输出：

```text
code     = NEWOW_ESCAPE_D1
label    = ★S逃命
color    = red
severity = CRITICAL
```

### 13.4 D2：★S逃

截图含义：中期见顶回落。

V1：

```text
cross_down(VAR4, 93)
AND Amplitude30_t > 0.10
AND abs(MA120Slope10_t) <= 0.0005
```

输出：

```text
code     = NEWOW_ESCAPE_D2
label    = ★S逃
color    = green
severity = WARNING
```

### 13.5 D3：★S跑

截图含义：跌破半年线，加速下跌。

V1：

```text
Close_t < MA120_t
AND MA120Slope10_t < -0.0005
AND cross_down(VAR4, 90)
```

输出：

```text
code     = NEWOW_ESCAPE_D3
label    = ★S跑
color    = blue
severity = BEAR_CONFIRMATION
```

### 13.6 同Bar冲突

计算层保留所有命中的信号。主图同一根 Bar 只显示一个主标签，优先级：

```text
D1 > D2 > D3
```

点击主标签的详情弹层列出该 Bar 全部命中项。

### 13.7 解读弹层

D1/D2/D3 弹层文案和颜色与用户提供的首页截图保持一致，不重新改写成项目术语。

## 14. 杯柄 Setup V1

### 14.1 定位

杯柄是牛哇趋势策略中的唯一命名形态。它不会决定黄蓝状态，只为趋势主图增加一种高质量整理结构。

状态：

```text
NONE
FORMING
READY
BREAKOUT
WEAKENED
INVALIDATED
EXPIRED
```

### 14.2 锚点

看涨骨架：

```text
L：左杯口高点
B：杯底
R：右杯口高点
H：柄部低点
P：柄部/杯口突破位
```

严格顺序：

```text
tL < tB < tR < tH <= tP
```

看跌杯柄使用方向归一化后的镜像骨架。V1 可以展示看跌杯柄风险，但不据此生成期货空单动作。

### 14.3 专用因果拐点

不建设通用 Pattern Engine。`cup_handle.py` 内部使用专用 `CupPivotTracker`：

```text
reversal_atr = 1.25
min_leg_bars = 3
```

上涨腿持续跟踪最高 high；completed close 从极值反转至少 `1.25 × ATR14_at_extreme` 后，才确认此前高点。下降腿镜像。

每个点必须同时记录：

```text
pivot_at
confirmed_at
```

图形可以画回 pivot_at，但 FORMING/READY/BREAKOUT 状态不得早于 confirmed_at。

### 14.4 V1 硬条件

前置趋势：

```text
左杯口前20—60根D1中：
上涨幅度 >= 10%
OR 推动幅度 >= 4 × ATR14
```

看跌镜像。

杯体：

```text
25 <= cup_bars <= 90
10% <= cup_depth_pct <= 50%
cup_depth_atr >= 3.0
rim_gap_pct <= 5%
rim_gap_atr <= 1.5
```

柄部：

```text
5 <= handle_bars <= 15
handle_depth_pct <= 15%
handle_retrace <= right_leg_advance / 3
柄部极值必须位于杯体上半部
```

量能：

```text
median(handle_volume) <= 0.80 × median(right_leg_volume)
median(handle_volume) <= 0.90 × median(previous_20_volume)
```

突破：

```text
Close_t > P + 0.10 × ATR14_t
breakout_volume >= 1.20 × median(previous_20_volume)
breakout_volume >= 1.50 × median(handle_volume)
```

看跌镜像。

### 14.5 U形纯度与 v3.6 过滤

必须实现 v3.6 更新说明中的四类过滤：

1. **V形底扣分**：最低25%深度区域停留少于3根D1时扣15分；只有单根尖底时不得进入 READY；
2. **左高前趋势确认**：前置趋势不满足则拒绝；
3. **柄部长短收紧**：少于5根或超过15根拒绝；
4. **浅杯过滤**：杯深低于10%拒绝；
5. **宽幅震荡过滤**：杯体中轴完整往返超过3次，或左右腿时间比例不在0.5—2.0，降低质量；严重时拒绝；
6. **下跌反弹过滤**：看涨杯柄前置趋势不足或左杯口仍位于明确下降结构中，拒绝。

### 14.6 100分评分

```text
前置趋势                  15
杯体时长、深度与杯口       25
U形纯度                   20
柄部质量                  20
成交量结构                20
总分                     100
```

门槛：

```text
FORMING  >= 65 且杯体硬条件通过
READY    >= 80 且柄部与缩量硬条件通过
BREAKOUT >= 85 且实体突破与放量硬条件通过
```

页面必须展示分项和扣分原因。牛哇 v3.6 的“真杯柄99分过线”只作为评分引擎存在的参考，不把99设置为本项目门槛。

### 14.7 候选冻结

- FORMING 可以随新 Bar 演化；
- 进入 READY 后冻结 `candidate_id / L / B / R / H / P / score_breakdown / confirmed_at`；
- 后续突破、减弱、失效通过新状态和新事件表达，不重写 READY；
- 每个同物理合约段同一锚点组合只保留一个候选。

### 14.8 主图绘制

只绘制：

```text
L / B / R 锚点
杯体轮廓
柄部半透明区间
P 突破线
状态胶囊
分数与量能状态
```

不绘制目标收益区或自动止损区。

## 15. 统一输出模型

### 15.1 `NewowTrendDetailResponse`

```text
source_identity
instrument
frequency
visible_range
bars
trend_band
trend_markers
escape_markers
cup_handle_candidates
rollover_seams
legend
formula_descriptions
reference_version
warnings
```

### 15.2 `NewowTrendBandPoint`

```text
bar_end
b_value
c_value
state
state_before
transition optional
```

### 15.3 `NewowMainMarker`

```text
marker_id
marker_type
bar_end
price
label
color_token
priority
related_marker_ids
trigger_facts
formula_version
```

### 15.4 `NewowCupHandleOverlay`

```text
candidate_id
direction
state
left_rim
bottom
right_rim
handle_start
handle_extreme
pivot_price
confirmed_at
first_seen_at
score
score_breakdown
hard_failures
volume_facts
formula_version
```

## 16. API

V1 使用只读接口：

```text
GET /api/v1/market/newow/trend-detail
```

请求：

```text
product
from
through
frequency=1d
series_kind=actual_dominant
```

服务端：

- 通过 MarketDataService 读取；
- 在请求内运行纯计算，或读取按 dataset digest 缓存的有界文件结果；
- 不新增 DB 表、Redis、队列或 Worker；
- 缓存键必须绑定 `source_identity + formula_digest + from + through`；
- HTTP 不写生产数据，不触发外部下载。

Web 不重新计算任何牛哇公式。

## 17. 源码边界

### 17.1 Quant core

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py
├── profile.py
├── trend_band.py
├── escape_d123.py
├── cup_handle.py
└── engine.py
```

不创建：

```text
通用策略插件框架
通用 Pattern Engine
完整 Structure Graph
Phase Lite
Target/Risk
Episode
Order / Position
```

### 17.2 Application

```text
services/quant-api/app/market_data/newow/
├── trend_detail_service.py
├── trend_detail_cache.py
└── trend_detail_query.py
```

### 17.3 API / Web

```text
services/quant-api/app/api/market_newow.py
services/quant-api/app/schemas/market_newow.py

apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/pages/market/NewowTrendDetailView.vue
apps/quant-web/src/components/newow/NewowHeader.vue
apps/quant-web/src/components/newow/NewowTrendChart.vue
apps/quant-web/src/components/newow/NewowIndicatorSheet.vue
apps/quant-web/src/components/newow/NewowSignalHistorySheet.vue
apps/quant-web/src/components/newow/NewowCupHandleSheet.vue
```

现有 `chart.vue` 只增加页面分流，不承载 Newow 业务逻辑。

## 18. 因果与非重绘合同

必须通过：

```text
completed-only
strict-before
prefix invariance
batch/incremental parity
same-physical-contract isolation
rollover reset
first-seen immutability
fail-closed
```

具体要求：

1. 只改变未完成 D1 的 high/low/close/volume，不得影响正式输出；
2. 任意 prefix 运行产生的黄蓝转折、D1/D2/D3、READY/BREAKOUT 与 full-run 对应前缀一致；
3. 杯柄 pivot 可以向左绘制，但状态最早时间必须等于其 `confirmed_at`；
4. 新数据不得移动已冻结 READY 的杯口、杯底、柄部和突破位；
5. 主力切换前后的数据不能组成同一个杯柄；
6. 换月不能生成黄蓝切换收益标记；
7. 同一前缀重复请求必须返回相同 marker_id。

## 19. 视觉 Golden Review

### 19.1 趋势带与标记

至少选择10个牛哇真实历史窗口，包含：

```text
完整蓝→黄→蓝
长时间黄带
长时间蓝带
高频翻色
大幅跳空
主力切换附近
```

逐项记录：

```text
MATCH
MISMATCH
REFERENCE_INSUFFICIENT
```

比较：

```text
转黄日期
转蓝日期
建仓/清仓位置
标签价格
参考变化
色带位置与连续性
```

### 19.2 D1/D2/D3

使用人工构造公式 fixture 和牛哇真实截图双重验证：

- 阈值上方不触发；
- 只在 cross_down 当日触发；
- D1偏离不足30%不触发；
- D2振幅不足10%不触发；
- D2 MA120不走平不触发；
- D3 MA120未向下不触发；
- 同Bar冲突优先级稳定。

### 19.3 杯柄

Gold Set 初始 60—100 个 D1 窗口，覆盖：

```text
真看涨杯柄
真看跌杯柄
V形底
宽幅震荡
下跌反弹
杯深不足10%
柄部过短/过长
柄部过深
柄部不缩量
突破不放量
主力换月附近
```

V1 Gate：

```text
READY precision >= 80%
BREAKOUT precision >= 85%
已确认候选 identity stability = 100%
跨物理合约候选 = 0
```

不以未来收益作为形态标签。

## 20. UI 验收

### 20.1 页面一致性

必须通过手机视口截图对比：

```text
顶部栏结构
品种信息层级
橙色趋势策略Chip
主图占比
黄蓝色带
建仓/清仓卡片
D1/D2/D3图标
指标解读弹层
历史列表弹层
```

颜色使用语义 Token，在视觉 Review 时从参考截图取样后冻结：

```text
newow-yellow
newow-blue
newow-build-border
newow-clear-border
newow-d1-red
newow-d2-green
newow-d3-blue
newow-modal-background
```

### 20.2 交互验收

- 当前版/牛哇版切换不丢品种和时间范围；
- 点击标记正确定位对应 Bar；
- 指标解读弹层可关闭且不改变图表状态；
- 收藏和历史入口可用；
- 横向缩放、拖动、十字线不破坏覆盖层对齐；
- 不出现底部三个副图、目标价、收益曲线或未实现按钮。

## 21. 错误与不可用

页面必须区分：

```text
数据加载失败
日线不足20根：趋势带不可用
日线不足120根：D1/D2/D3不可用
杯柄历史不足：杯柄不可用
actual_dominant映射异常
物理合约数据缺口
```

不得用0、前向填充、其他周期或连续合约静默补齐。

## 22. V1 完成定义

V1 只有同时满足以下条件才算完成：

1. 牛哇版本是独立详情子页面，当前版本无行为变化；
2. 日K黄蓝趋势带、建仓/清仓和当前四状态可用；
3. D1/D2/D3按本文公式产生、显示和解读；
4. 杯柄形成、READY、突破和失效可在主图复核；
5. 底部三个副图、目标价和收益曲线确实未混入；
6. Historical 与逐 Bar 结果一致，prefix 与换月测试通过；
7. 手机视口和桌面视口 visual smoke 通过；
8. 参考窗口中的主要状态变化完成逐项对照；
9. 页面明确为“策略参考”，没有自动交易或实际成交声明。

## 23. 后续而非 V1

只有 V1 主图行为经用户确认后，才依次考虑：

```text
1. 继续校准黄蓝带公式
2. 主力动态 / 涨跌动能 / 主力控盘副图
3. 目标价与吸筹价（取得公式证据后）
4. 牛哇震荡策略
5. 60m / 15m 周期
6. 全市场扫描与提醒
```

## 24. 设计自审结果

本次 Review 发现并修正：

1. **旧设计混入了当前项目指标。** 已删除 EMA/MACD/Phase Lite/Lux Range 作为牛哇 V1 主逻辑的设定；V1 只复用数据底座。
2. **旧设计从详情页过早跳到扫描和提醒。** 已将 active60、Shadow、Alert 全部移出 V1。
3. **旧设计错误扩大了页面范围。** 已冻结为“详情页主图 + 成交量 + 解读弹层”，不做三个副图和收益曲线。
4. **D1/D2/D3只有文字没有可执行定义。** 已冻结 VAR4、振幅、MA120斜率和交叉语义，同时明确其 clean-room 身份。
5. **杯柄与趋势主状态关系不清。** 已固定杯柄是主图 Setup，不决定黄蓝带。
6. **期货换月会伪造趋势与形态。** 已要求所有状态按真实物理合约段隔离。
7. **现有 `chart.vue` 已较复杂。** 已选择独立 Newow 子页面，避免继续堆叠 overlay 分支。
8. **牛哇截图中存在目标价、吸筹价和点阵，但公式不足。** 已明确不实现，不使用替代指标。
9. **蓝色在股票产品中是空仓，不是做空。** V1保持牛哇原语义，不自行增加期货空头建仓。
10. **UI“完全参考”与功能范围可能冲突。** 已明确：included flow 忠实参考，未实现功能直接省略，不渲染假入口。

Review 结论：

```text
SPEC_INTERNAL_REVIEW_PASSED
READY_FOR_IMPLEMENTATION_PLAN_REWRITE
SOURCE_IMPLEMENTATION_NOT_AUTHORIZED_BY_THIS_DOCUMENT
```
