# Newow 白色详情页 V2 设计规范

日期：2026-09-07；代码基线 `7ba649ad1b79e3fda765f49e30a1b8d7e208810a`。
用户已批准 V2 视觉，并授权设计文档 → 实施计划 → 独立 Review/修正 → 文档提交 develop → 独立 worktree 开发。本规范描述批准的实现目标，不声明产品已完成或上线。

## 1. 来源、范围与优先级

批准图：[主页面](fixtures/newow-detail-light/page-approved.png)、[解释弹窗](fixtures/newow-detail-light/dialog-approved.png)。生成图只约束结构、颜色和交互方向，数值、曲线、坐标和标记位置是示例，不能用作行情、公式或收益 golden。

本次 Chrome 只读观察：牛哇首页标题 v3.3.02；`stock_detail.html?code=600519.SH&period=day&strategy=huanglantai` 的贵州茅台个股详情标题 v3.2.64。实际观察了综合决策原位展开/收起、指标解读居中白色弹窗及遮罩、“知道了”关闭、页面向下滚动的逐笔参考记录。首页版本不代表详情版本；本次图像在会话工具结果中，未作为原站 PNG 原件入库。另参考仓库 `docs/research/newow-v3.2.82/screenshots/600519-SH-day-trend.png`；不把历史派生截图当作此次原站原件。

本规范替代旧 [交互设计](2026-09-07-newow-desktop-visual-interaction.md) 与 [工程规格](2026-09-07-newow-desktop-engineering-spec.md) 中的深色、右栏、底部解释 tab 和参考宽表方向。其他已核实的数据身份、时间、MACD 接入、单一副图和未知证据边界继续适用；冲突以本规范为准。旧文档中不属于本次图形实现的更广泛原站 parity 目标不得被宣布完成。

实现范围为 `/market/chart?view=newow` 的三策略 × `1w/1d/60m`；共享 Shell 只通过显式 light/Newow 变体复用，保持 HTDY、SuBing、Free 和旧 trend 行为。首页不改。无新页面、搜索栏、移动底部导航、订单、账户或通知功能。

## 2. 信息布局

**DL-01 白色全宽 Shell。** 顶部归一量化、市场、牛哇、火天大有、苏冰预警、更多（自由看盘）。导航保留当前合法品种和既有视角频率偏好；不新增选择结果未知的快捷品种。全部品种使用既有产品目录和 route serializer，换品种清理不兼容合约与历史焦点；不额外加载首页三个 bulk 资源以画快捷栏。收盘报价仍使用既有 quote authority，不拿 Newow 当前频率或 hover 值填充不可用报价。

**DL-02 图上方摘要。** 移除常驻右栏与重复技术介绍。默认两行：策略状态圆标/信息入口、目标/吸筹参考价、展开详情；最近主动作、当前参考交易、参考浮动、状态截至。只显示已核实资源；空缺为 `—` 并标注未读取/不可用/证据不足。初次仅 chart + 默认 MACD；reference 区进入视口时按需读取，explanation 仅用户展开或点击时读取。不能为摘要自动触发 comparator 重型计算。

**DL-03 折叠。** 原生 button `aria-expanded/aria-controls`，默认收起；展开在摘要下方原位出现已存在的综合解释及来源，推移图表，收起恢复紧凑布局。隐藏长 ID、公式和来源只改变默认密度，仍可在详情内查询。切品种/策略/周期重置展开、弹窗与历史选中，不泄漏旧身份。

**DL-04 图标解释。** 彩色状态图标、摘要信息图标、图例/Hint/指标解读入口打开单个居中白色弹窗。状态映射 BUILD 红三角、HOLD 橙勾、CLEAR 绿倒三角、FLAT 蓝叉、UNAVAILABLE 灰问号；状态取最新 chart frame 且标注该 Bar 的时间，不从最近 Action 推断 HOLD，也不能把历史窗口末帧冒充截至最新快照。当前事实与所选历史标记分别标注。

弹窗包含标题、品种/物理合约/策略/周期/时间、简短状态解释、已有事实，以及展开来源；不使用未经证实的自然语言诊股。历史 Action/Hint 弹窗只用它自身的 chart 事实，不调用当前 explanation 冒充历史理由。关闭按钮、“知道了”、Esc、遮罩可关闭；打开聚焦、Tab 焦点限制、关闭恢复触发点和页面滚动位置；切身份关闭时不聚焦卸载节点。可使用原生 dialog 和局部样式，无新依赖。解释空/错误/证据不足仍可阅读，错误不伪装为成功。

**DL-05 主图与副图。** 全宽 K 线、成交量、单一辅助 pane。同一 Lightweight Charts 实例或现有等价同步 primitive 共享时间索引、缩放和十字线。主图价格坐标独立；成交量来自同 chart Bar，不添加成交量 MA。默认 MACD，点击照妖镜/涨跌动能/主力控盘替换一个副图，再点已选项不关闭。杯柄留在独立说明/图层入口且保留既有适用性，不成为第五个副图。

趋势 A/B 使用服务器原值和状态绘制段内黄蓝带；震荡 upper/lower，主升浪 MA35/MA45。缺值、无效、warm-up 和物理 Segment 边界必须断开，不能用平滑线跨越。参考标记保留精确 ID、同 Bar 次序；隐藏冗长 Hint 叠层，改为可点击说明入口，不删除事实或混同主动作。保留加载更早、回到最新、精确定位和 resize/dispose。全屏通过浏览器标准全屏接口，仅作用于图表区域。

照妖镜/动能/控盘仍使用已核验 API 序列与显示口径，不凭图片反转符号或拼接类别。未确认原站 render profile 保持说明，不假称全部副图原站一致。

**DL-06 参考交易。** 副图下为参考交易标题、短口径说明、统计区间。逐笔 card/list item，随整页纵向滚动；不采用分页路由、不限制最近三笔、不建固定低高度内滚动宽表。服务端 cursor 继续“加载更多”，禁止无限预取全部历史。初次区块进入视口自动加载一次，加载失败显示显式重试；隐藏/出现不重复请求已读取资源。

每笔显示物理合约、建仓/清仓日期和参考价、状态、定位、详情。OPEN 只显示参考浮动与估值日期；CLOSED 只显示已清仓收益；ROLLOVER_INTERRUPTED 和 DATA_CONFLICT（如果协议支持）按既有能力呈现且不能伪装清仓收益。期初已有、closed-only 服务端统计、筛选和窗口读取能力保留，详细身份与 Hint 在展开区。统计窗口独立于 viewport，筛选不改统计。精确定位可能请求显示窗口，禁止邻近日期兜底。

**DL-07 比较器。** 保留现有独立比较器能力，通过参考交易区的“页面比较说明”入口按需打开解释弹窗；不恢复底部 tab、不增加默认收益曲线。不与 ReferenceTrade 统计共用收益字段，明确样本末理论平仓和证据状态。

## 3. 数据边界与 MACD 显示扩展

现有 `useNewowProduct` 保持唯一 section loader，generation/Abort、snapshot 兼容、cursor、LRU 和有界执行不变；UI 新请求由合法 identity 驱动。reference/explanation 未请求时不制造假摘要。target/absorb 仅在 explanation 返回合法值、status/evidence 允许且与当前 chart 请求身份及快照兼容时显示；若缺严格兼容证明就显示不可用。参考浮动只显示服务端值，不在前端按价格计算。

MACD 是明确的最小只读 API 增量：在既有 `section=auxiliary` 增加 `component=macd`，不新增路由、不改策略身份、Action/ReferenceTrade ID 或收益。复用 `indicators/macd.py::macd_series`，参数 fast=12、slow=26、signal=9、ema_seed_policy=sma_window、histogram_scale=2、round_digits=6，保留原 MACD_VERSION 与 parameters_hash，display_adapter_version=`guiyi_newow_macd_display_v1`。

输入为现有 Newow reader 的 completed、as_of 内同物理生命周期 replay prefix，按物理段独立计算后投影到合法显示 Bar。缺前缀就 warming/unavailable，禁止访问 provider 补数据。改变 viewport 不得改变同快照重叠 Bar 的值。新增 Python schema/serializer/enum、TS discriminated union/guard、fixture 同步；每点 dif/dea/histogram 的 value/ready/valid/reason/time 保留，零值正常显示，缺值不变零。只读显示，repainting=false、formal_signal_eligible=false、page_parity=false，不伪称牛哇 MACD 公式。

旧组件响应保持兼容，旧服务端不支持时清楚显示 MACD 不可用，不偷偷回落客户端算法或其他指标。缓存预算和 snapshot proof 不降低；新增适配版本/参数纳入 MACD 缓存身份。真实数据/策略/正式信号无变更，故为 Lane 2 显示适配；若必须改动内核公式或输入 authority，则停止该变更而不是扩大范围。

## 4. 视觉与可访问性

Newow 局部 token：白 `#FFFFFF`，正文 `#20242B`，次级 `#667085`，分隔 `#EBEDF0`，网格低对比，橙 `#FF6B2C`，涨 `#FF403A`，跌 `#22B95D`，蓝 `#365AF5`。浅色标签分别使用约 10% 的底色、7px 圆角、独立不透明文字；不降低父节点 opacity。主操作焦点可见；状态有形状和文字，不只靠颜色。金额字符串保留原值，有限 Number 只用于绘图坐标。数字使用 tabular-nums。

桌面 1280×800、1440×900、1920×1080、2560×1440 全宽，无居中 max-width、无页面横向溢出。chart 价格区至少 280px，volume 至少64px，辅助至少112px，页面可向下延伸；不得强塞首屏。保留390px基本访问与44px触控目标，不另设计移动产品。弹窗宽 min(480px, viewport-32px)，长内容内部可滚，标题/关闭可访问。

## 5. 验收与交付

| AC | 验收 |
|---|---|
| AC01 | Newow 白色全宽，图上摘要可折叠，无右栏/底部研究 tab/参考宽表；其他视角不退化。 |
| AC02 | 图标、键盘、Esc/遮罩/关闭、焦点恢复；历史与当前解释身份不混用。 |
| AC03 | reference 首次可见只请求一次，逐笔滚动、cursor、筛选/统计窗、精确定位、缺失/失败/过期仍正确。 |
| AC04 | 同 Bar/Segment/时间索引的 K 线、volume、单副图；切换/重复点击/全屏/resize/释放；缺值不连线。 |
| AC05 | MACD 内核同前缀 golden、warm-up/零值、物理段重置、viewport不改值、旧响应兼容、无 provider/写入。 |
| AC06 | target/absorb/状态/参考浮动保持真实 authority、snapshot/evidence 与时间；不可用不填示例。 |
| AC07 | 九组合、四桌面尺寸及390兼容，真实浏览器截图目视复核；生成图不作为数值或像素 golden。 |
| AC08 | 定向测试、Web unit/build、相关 E2E、MACD 后端定向、工程/OpenSpec/secret/diff、独立 Review 通过。 |

命令入口为 `TESTING.md`。文档先独立 Review/修正后 commit/push develop，之后从精确 docs commit 创建 `codex/newow-detail-light` worktree。实现按任务提交、Review 并以 Git history 记录，不建立重复治理资产。普通 Lane 2 可集成 develop；main/tag/release、Runtime、DB/Redis/Canonical/RQData、真实通知均不在范围。回滚仅 revert 本任务提交。外部页面原件不足、真实工作站性能和既有证据 Gate 不由视觉验收关闭。
