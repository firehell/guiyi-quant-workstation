# 首批六品种 W1 默认首载验收（2026-09-18）

只读候选预览代码 `614e73a42c38bb00f7b488feca53d44fb2f6ff69`，浏览器
`127.0.0.1:5174`，候选 API `127.0.0.1:8010`，读取既有 Canonical 与 Catalog。
18 次页面导航均未提供固定 `as_of`；15 个可解析快照共同截止
`2026-09-18T07:00:00.000001Z`。逐项快照、响应身份及浏览器状态见
[`acceptance-matrix.json`](acceptance-matrix.json)，原始读回见
[`snapshot-matrix.json`](snapshot-matrix.json)、
[`section-matrix.json`](section-matrix.json)、
[`browser-settled.txt`](browser-settled.txt) 和
[`chart-identity.json`](chart-identity.json)。BU 趋势的独立重测见
[`bu-trend-recheck.json`](bu-trend-recheck.json)。

| 品种 | 趋势 | 震荡 | 主升浪 | 最近图表物理合约 | 说明 |
| --- | --- | --- | --- | --- | --- |
| AU | 页面可读 | 页面可读 | 页面可读 | AU2610 | 主图、副图、参考交易及收益可读 |
| RB | 页面可读 | 页面可读 | 页面可读 | RB2701 | 震荡首次分区读取出现快照代际冲突；同一截止重读八分区及浏览器首载通过，首次异常保留 |
| CU | 页面可读 | 页面可读 | 页面可读 | CU2610 | 主图、副图、参考交易及收益可读 |
| BU | 页面可读 | 页面可读 | 页面可读 | BU2610 | 趋势首轮浏览器等待超时，单独默认首载重测通过 |
| PD | MACD 预热 | MACD 预热 | MACD 预热 | PD2610 | 主图与参考交易可读；MACD 为 `warming`，不记策略 READY |
| PT | 数据阻断 | 数据阻断 | 数据阻断 | — | `PT2612` 在 `2025-12-19` 缺同合约 W1 历史 Bar 端点；页面明确提示，未回退或造价 |

震荡比较器在当前物理合约区段不足 20 根 Bar 时显示不可用；趋势和主升浪
比较器明确显示不适用。该状态未计作比较器 READY。页面当前主力上下文在这次
只读读回中为 `unknown`，顶部独立报价显示不可用；图表的历史物理合约身份仍由
每根 Bar 提供，不以历史合约冒充当前主力。

站内 AU → CU → PD 连续切换后，最终 URL、标题、主图和周截止均属于 PD；
旧品种响应未回填。真实 AU 周线以 `chart_limit=20` 读取第二页：20 + 9 根 Bar、
无重叠、相同 `as_of` 和 snapshot token；参考交易 `history_limit=5` 第二页也保留
相同截止及 token。浏览器默认图表一次读取 190 根以内，未出现“加载更早”按钮，
分页的真实数据验证因此通过 API 完成。

结论：18/18 默认入口已经实际观察；12/18 页面主要分区可读，3/18 合法预热，
3/18 因内部数据缺口阻断。此处不证明 18/18 READY，不证明 41/123、正式发布、
Runtime 或自然新周验收。修复 PT 的数据缺口须另行核准精确数据写入批次。

## 2026-09-18 首个 PT 精确批次后的补充读回

`PT2612 / 2025-12-15～19 / D1+W1` 已按单独授权执行，2 个目标全部提交；
D1 原 SHA 和 13 根 Bar 不变，W1 的 2025-12-19 Bar 与 MDS 周质量通过。
PT 三策略真实默认首载随即显示**下一缺口 2025-12-26**，因此上表的
PT 三项仍为数据阻断，不能升级为页面通过。PT D1 三策略默认页面主图保持
`ready`。剩余前缀的只读范围与新授权 Gate 见
[`pt2612-remaining-repair-approval.md`](pt2612-remaining-repair-approval.md)。

## 2026-09-18 PT2612 剩余前缀批次与复验

用户已对上述第二批 20 个 D1/W1 活动月目标一次性授权。执行前重算计划
`843bb24f1979e3e399eafc6c71c3136260440a3fd4c8b3a832f4b4c98f6883fe`，
核对 20 个活动状态、路径、行数及原文件 SHA 均未变化。原生
`contract_warmup` 在维护锁下按该哈希一次执行，结果 `passed`、
`applied=20`、`provider_requests=20`、`blocked=0`、`failed=0`；未启用首页
投影失效钩子，未重试。参见
[`pt2612-remaining-apply-result.json`](pt2612-remaining-apply-result.json)。

只读回读确认 10 个 D1 月分区 SHA 与写入前逐一相同；10 个 W1 月分区均
有活动文件，合计 39 根完整周 Bar（原有 2 根，补齐 37 根），从
`2025-12-19` 延续到 `2026-09-18`。同一范围重新规划的直接目标为 0。
逐分区路径、SHA、行数和交易日见
[`pt2612-remaining-postapply-readback.json`](pt2612-remaining-postapply-readback.json)。

隔离候选代码 `067190c6847c1cf95f6c31af1ed633427d34a65d`；无固定
`as_of` 的 PT 趋势、震荡、主升浪默认快照都返回 HTTP 200，周截止一致为
`2026-09-18T07:00:00.000001Z`，`freshness=current`，当前主力上下文仍为
`unknown`，没有从历史合约推断当前主力。三策略主图、参考交易/收益均返回
`ready`；主图与各面板使用相同截止及请求传入的快照 token。三策略 MACD
均为合法 `warming`；震荡比较器因当前物理合约区段 Bar 数不足为
`NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS`，另外两策略比较器不适用。
`explanation` 路由尚未开放，返回 `NEWOW_SECTION_NOT_OPEN`，不计通过。
完整响应身份和状态见
[`pt2612-remaining-postapply-snapshots.json`](pt2612-remaining-postapply-snapshots.json)、
[`pt2612-remaining-postapply-sections.json`](pt2612-remaining-postapply-sections.json)。

真实浏览器三页默认入口未传 `as_of`；三页主图均 `ready`、辅助资源均
`warming`，一致显示上述周截止与“当前主力不可判定”。参考交易区可读，
趋势显示 2 笔已完成、1 笔换月中断，震荡显示 1 笔换月中断；零已完成
交易的两页收益显示 `—`，没有伪装成 0%。参见
[`pt2612-remaining-browser-readback.json`](pt2612-remaining-browser-readback.json)。
PT D1 的 10 个月活动文件 SHA 未变，三策略 D1 默认主图均 HTTP 200 / `ready`；
见 [`pt2612-remaining-d1-regression.json`](pt2612-remaining-d1-regression.json)。

**修正前文阶段结论：**首批六品种 18/18 默认入口均已观察，18/18
主图及参考交易页面可读；PD 三页与 PT 三页的 MACD 合法预热，
不能记作全策略 READY。PT 的三项原数据阻断已解除。此项仍是隔离
候选页面验收，不代表 W1 正式开放、41/123 验收、发布或 Runtime。
