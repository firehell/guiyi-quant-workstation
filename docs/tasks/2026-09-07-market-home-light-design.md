# Market 首页白色桌面设计

日期：2026-09-07。规格基线：`7f58896c5aed763c5e106da194fa6adc80536157`。
用户已确认白色首页效果，并授权：设计 → implementation plan → 独立 Review/修正 → 文档提交 develop → 独立 worktree 实现。本文件是实现规格，不是上线声明。

## 1. 目标与视觉来源

在现有 `/market` 内完成 60 品种桌面首页：白底、橙色激活、浅色圆角涨跌标签、圆形周期图标、全宽表格、点击表头排序。去掉搜索栏、独立排序/筛选工具栏、常驻观察侧栏和重复汇总卡片；不提供底部我的/选股/消息导航。

批准的生成图：[白色首页效果图](fixtures/market-home/light-approved.png)。它只约束布局和外观；图中价格、目标价、状态、排序样本和运行数据均为设计示例。用户提供的局部截图约束涨跌/目标价的浅色圆角背景以及图标间距；当前牛哇在线浏览器采集超时，不声明当前原站完整一致性。

本轮白色首页要求优先于 [Newow 桌面视觉规格](2026-09-07-newow-desktop-visual-interaction.md) 的首页公共 Shell 深色方向；后者的详情页与工程任务不在本次范围内。首页局部样式不得改变详情页、图表主题或全局指标颜色。

## 2. 权威数据与必要校正

仅消费既有三个 bulk GET：overview、Runtime health、current Alert Events。板块及 active/participant 数量读取 overview，浏览器不另写品种分类表、不硬编码 60、不逐品种请求、不生成行情或策略。严格遵循 [Market Home authority](../../openspec/specs/market-home-overview/spec.md)。

| 效果图内容 | 正式页面处理 |
|---|---|
| 目标参考价蓝/橙标签及数值 | 当前 overview 禁止策略 target，且无合规 bulk 来源；本轮该列固定 `—`，表头解释“尚未接入同身份目标参考价”，不可排序，不添加伪造 target 字段。蓝/橙数值接入为独立业务合同任务，本轮不能宣称完成。 |
| 日增仓整数 | `oi_change_1d` 实为相对变化率；表头改为 `1d 增仓率`，百分比展示且文字中性色；不暗示增仓等于看多。 |
| 每个品种一行、60 行齐全 | API items 只含参与当前快照者。显示“可用 n / 总数 N”，明确过期/缺失数量；不可为缺失品种猜名称、价格或创建占位事实行。 |
| 日周红橙绿蓝 | 保持 generic completed EMA21 trend 含义；红上行、绿下行、蓝中性、灰不足。橙色勾表示日周同向，搭配红/绿小方向箭头；不改为牛哇 BUILD/HOLD/CLEAR。 |
| 展示的非实时价格 | 仍为最近完整交易日收盘。保留 data_as_of 和非实时提示；缓存失败与服务端 stale/degraded 均保留现有灰态保护。 |

## 3. 页面结构

- **HOME-01 顶部**：白色品牌条，市场当前页、牛哇/火天大有/苏冰预警的品种选择菜单、更多中的自由看盘，以及刷新。点击视角先从当前 overview items 选品种，明确选择后通过既有 route serializer 跳转；不自行猜默认主力。无可用品种时明确不可用。普通表格行点击仍固定 Newow 趋势 `actual_dominant + 1d`；苏冰视角为 `15m`。
- **HOME-02 板块**：`全部 N` 加现有 taxonomy 的有数据板块。数量取 sector.active_count，不用筛选后的 items 伪装总量；筛选只影响本地 rows。选中态 `aria-pressed=true`，再次点击已选板块回到全部。板块无 participant 时显示空列表与真实缺失说明。恢复了已不存在的板块时回到全部。
- **HOME-03 图例**：单行紧凑图例。保持既有 MarketStateIcon 单一实现；页面局部将 legend 视觉压缩到 28px，不改变其他消费者默认尺寸和语义。
- **HOME-04 主体**：标题、真实参与数/快照日期、研究观察展开按钮；下方直接表格，不另设排序控制行。默认观察收起，点击展开复用现有 immutable Event 列表；保持空、不可用、cached stale 三种区别和原 Event 跳转。
- **HOME-05 表格**：品种（名称/代码）、板块中文、最新收盘、1d 涨跌幅、目标参考价、量比、1d 增仓率、1d、1w、同向、详情箭头。5d 字段仍由 API 提供但退出本轮桌面主表；不删 API/内核能力。数据日期与观察状态从重复行列收敛到真实状态区/观察面板。
- **HOME-06 状态**：常驻紧凑“非实时行情·截至日期·可用 n/N”；Runtime、Event 异常/缓存过期保持可见，详细状态可展开。不能把 unknown 或 aggregate ok 美化为全部健康。刷新仍调用三资源 refreshAll，无生产写入。

## 4. 排序、偏好与操作

可排序表头为收盘、1d 涨跌幅、量比、1d 增仓率。首次点击降序，再次升序，再次默认顺序；切另一列从降序开始。默认顺序保持服务端 items 次序。同值按 symbol 稳定升序；null/非有限值在两个方向都排末尾。排序只作用于已筛选数据，不原地修改输入，不额外请求。

表头以原生 button 承载操作，th 设置 `aria-sort=none/ascending/descending`。Enter/Space 操作排序，不触发行跳转。表格行 Enter 进入既有详情。hover 为浅橙行底和左侧细橙条，focus-visible 必须可见且不能被表头或滚动裁掉。目标参考价无数据时没有可点击排序暗示。

沿用既有 localStorage key；向 version 1 加可选 `sortDirection`，缺省按原 sort 降序解释，新增 close sort。写回只存合法字段；旧缺省/无效 JSON、字段类型非法、安全 storage 失败都回落默认。保留原 detailFrequency/compactDensity 字段供兼容，不新增密度切换 UI。新用户 focusRailCollapsed 默认为 true；已有偏好仍可恢复。返回首页保留板块及排序；显示偏好不改变 API 参数或策略身份。

## 5. 视觉工程约束

局部前缀 `--gy-home-*`，根背景 `#FFFFFF`，正文 `#20242B`，次级 `#667085`，分隔 `#EBEDF0`，表头 `#F8F9FB`。选中/强调 `#FF6B2C`；hover `#FFF6F0`。涨 `#FF403A`，跌 `#22B95D`，涨/跌软底 `rgba(255,64,58,.10)` / `rgba(34,185,93,.10)`。文字不随父容器 opacity 变淡。图标维持原状态映射，首页蓝圆可局部使用 `#365AF5`，不改变图表标记。

数字 tabular-nums；现有 numeric close 原值不再固定截成两位小数，格式化最多保留现有 Number 可表达的小数精度，不新增金额计算。涨跌幅/增仓率展示带符号两位百分数，null 为 `—`，0 为 `0.00%`。标签圆角 7px，padding 3px 10px；图标 28px，方向 micro 24px，充分对齐。

桌面验收为 1280×800、1440×900、1920×1080 和 2560×1440；撑满可用宽度，不限制居中 max-width。header/板块/图例紧凑，剩余自然显示列表，60行纵向滚动，表头保持可见；不强塞一屏、不裁掉页尾。初始截图用真实浏览器渲染的受控 60 品种 fixture，与生成图按布局/色彩比较而不是拿生成图做像素 golden。

既有 390px 列表兼容和键盘流程不得退化；只做必要兼容，不另设计移动产品。Home 外 route 仍使用原 padding/theme，不借首页修改扩展到详情 Shell。

## 6. 验收与集成

| AC | 可核验结果 |
|---|---|
| AC01 | 首页白底全宽；无搜索/独立排序条/常驻侧栏/底部导航；其他 route 不改主题。 |
| AC02 | 板块数量来自服务端；筛选/排序不新增 GET；当前不存在的板块偏好安全恢复。 |
| AC03 | 表头三态排序、空值末尾、同值稳定、输入不变、键盘与 aria-sort 正确。 |
| AC04 | 价格方向色、百分比软底和状态圆可见；OI 以率展示；目标列无假数字/排序/额外调用。 |
| AC05 | 三资源 GET、typed unavailable、stale 灰态、真实计数/时间、空与不可用 Event 均保留。 |
| AC06 | 行点击和各顶部选择菜单保持 exact view/symbol/frequency，Event 跳转不改语义。 |
| AC07 | 四个桌面尺寸无页面级横向溢出；60 行可滚动、表头可见；390px 可访问。 |
| AC08 | 定向/完整 Web unit、build、首页及必要详情 E2E、文档/OpenSpec/secret/diff 检查和独立 Review 通过。 |

本轮允许 Lane 2 代码集成 develop；不授权 main/tag/release、Runtime switch、生产 API smoke、RQData、DB/Redis/Canonical 或通知。验收只用隔离 route fixture。回滚通过 Git revert 本任务提交，不覆盖用户修改，不复制备份树。实现完成后独立 Review；未完成目标价接入和原站交互 evidence 应报告为边界，不包装成完整 page parity。
