# 牛哇 v3.2.82 策略复刻资料包

本目录集中保存牛哇 v3.2.82 的公开页面观察、指标与策略反推、股票逐值对照、期货迁移摘要和截图证据。用途仅限归一量化的研究、复算和产品设计，不构成交易建议。

## 当前范围

当前主线只复刻公开可验证、适用于个人期货量化的部分：

- 趋势黄蓝带，BUILD / HOLD / CLEAR / FLAT；
- S 跑、D1-D6、4/7/11 周期与杯柄；
- HHV / LLV 震荡通道及目标价、吸筹价；
- MA35 / MA45 主升浪与 J 风险；
- 主力控盘、照妖镜、涨跌动能与 ATR20 / Close；
- 13 格综合决策、方向/确定性评分、仓位区间和第一行动原则；
- 页面参考口径与 causal-research 口径的身份隔离。

牛哇六种私有服务端选股公式、私有排名/推荐服务和 AI 自然语言诊股逐字复刻均为 `UNKNOWN / OUT_OF_SCOPE`。本目录中的历史黑盒观察不能被解释为这些私有公式已经复刻。

手册和报告中的公式、案例与研究结果保留冻结基线；手册工程边界已校订，历史证据不作为当前开发计划。当前实现、Release与待验收以代码、active OpenSpec和`STATUS.md`为准。

## 阅读入口

- [2026-09-09 新版功能差异与后续任务](../newow-current-review.md)（App/Web 分别记录，不覆盖旧公式基线）

- [归一量化｜牛哇策略复刻手册（Markdown 源稿）](REPLICATION_MANUAL.md)
- [归一量化｜牛哇策略复刻手册（A4 PDF）](../../../output/pdf/newow-v3.2.82-futures-replication-manual.pdf)
- [完整策略与指标报告](REPORT.md)
- [页面一致性结果](evidence/core-page-parity-results.json)
- [综合决策可达性](evidence/composite-reachability.json)
- [AI 模板与周日矩阵证据](evidence/ai-template-evidence.json)
- [期货迁移摘要](evidence/futures-validation-summary.json)
- [OOS / 成本压力矩阵](evidence/oos-cost-stress-matrix.json)
- [来源登记](evidence/source-registry.json)
- [本地完整证据清单](evidence/full-local-evidence-manifest.json)
- [Owner 外部素材索引](evidence/external-reference-index.json)

## 冻结来源与复算索引

长期产品合同见[Newow OpenSpec](../../../openspec/specs/newow-product-reference-trading/spec.md)，阶段与待验收只见
[STATUS](../../../STATUS.md)。旧设计/实施过程从Git history追溯，不再作为公式或发布授权源。

初始owner材料包括真实详情页/指标弹层、D1–D3说明、v3.6杯柄说明截图、录屏和原始指南；
[外部素材索引](evidence/external-reference-index.json)只保留类型、哈希、用途和来源说明，二进制原件不进入 Git。
这些截图可以支持视觉观察，但未公开的数学公式必须维持clean-room身份；个股与指数证据均保留。

以下相对路径属于[完整本地manifest](evidence/full-local-evidence-manifest.json)登记的逻辑根
`newow-strategy-detail-research/v3.2.82-gap-closure`，不是本仓库缺失文件的下载入口：

| 证据组 | manifest原件/重放入口 | 权限边界 |
|---|---|---|
| M-SOURCE | `sources/stock-detail-v3.2.82.html`、`sources/strategy-calc-v3.2.82.js` | 公开页面控制流/计算源码 |
| M-CORE | `analysis/core-parity-inputs.json`、`analysis/core-page-parity-results.json`、`analysis/multi-period-page-facts.json` | 27点冻结输入/结果/多周期事实 |
| M-REPLAY | `analysis/collect_exact_page_cases.mjs`、`analysis/verify_exact_page_cases.py`、`analysis/verify_core_page_parity.py`、`analysis/kline-source-index.json` | 逐点采集和重放链 |
| M-COMPOSITE | `analysis/composite-reachability.json`、`analysis/verify_composite_reachability.py` | 13格可达性与不可达分支 |
| M-AI | `analysis/ai-template-evidence.json`、`analysis/extract_ai_template_evidence.py` | 周日16组合与历史模板来源，不证明AI逐字复刻 |
| M-OPTIMIZER | `analysis/page-optimizer-oracle.json`、`analysis/build_page_optimizer_oracle.mjs`、`sources/page-cases/600519-SH/day.json` | 五窗口oracle，不代替browser-final/tie golden |
| M-FUTURES | `futures/newow-futures-evidence-20260904.json`、`futures/normalized-research-snapshot.json`、`futures/oos-cost-stress-matrix.json` | 期货研究，不证明页面乐观参考交易或账户收益 |

2026-09-05历史登记核验为133项（captured96、derived37），missing/mismatch/unsafe均0；
source registry为96项（86 GET、10 POST），SHA-256为
`0b9e841c9d6af50acfc9adb924f90d4eb161e127db641198301b74a45c1e7dab`。
本次文档迁移没有重新读取完整本地原件或执行重放；133项字节核验不能冒充新的27/27公式测试。
原页面目标/吸筹昨收和owner语义、浏览器最终K线/DOM/tie、六组合oracle、诊断token及AI copy仍须各自原件支持；
现有受控wrapper和测试只证明如实降级，不补齐这些缺口。

## 截图矩阵

截图按 3 个指数、6 只个股和 week/day/60min 三个周期采集，共 27 张。

| 标的 | 周线 | 日线 | 60 分钟 |
|---|---|---|---|
| 上证指数 | [week](screenshots/000001-SH-week-trend.png) | [day](screenshots/000001-SH-day-trend.png) | [60min](screenshots/000001-SH-60min-trend.png) |
| 深证成指 | [week](screenshots/399001-SZ-week-trend.png) | [day](screenshots/399001-SZ-day-trend.png) | [60min](screenshots/399001-SZ-60min-trend.png) |
| 创业板指 | [week](screenshots/399006-SZ-week-trend.png) | [day](screenshots/399006-SZ-day-trend.png) | [60min](screenshots/399006-SZ-60min-trend.png) |
| 格力电器 | [week](screenshots/000651-SZ-week-trend.png) | [day](screenshots/000651-SZ-day-trend.png) | [60min](screenshots/000651-SZ-60min-trend.png) |
| 比亚迪 | [week](screenshots/002594-SZ-week-trend.png) | [day](screenshots/002594-SZ-day-trend.png) | [60min](screenshots/002594-SZ-60min-trend.png) |
| 宁德时代 | [week](screenshots/300750-SZ-week-trend.png) | [day](screenshots/300750-SZ-day-trend.png) | [60min](screenshots/300750-SZ-60min-trend.png) |
| 招商银行 | [week](screenshots/600036-SH-week-trend.png) | [day](screenshots/600036-SH-day-trend.png) | [60min](screenshots/600036-SH-60min-trend.png) |
| 贵州茅台 | [week](screenshots/600519-SH-week-trend.png) | [day](screenshots/600519-SH-day-trend.png) | [60min](screenshots/600519-SH-60min-trend.png) |
| 桐昆股份 | [week](screenshots/601233-SH-week-trend.png) | [day](screenshots/601233-SH-day-trend.png) | [60min](screenshots/601233-SH-60min-trend.png) |

另有 [匿名首页](screenshots/context/home-anonymous.png) 和 [桐昆股份日线采集现场](screenshots/context/stock-601233-trend-day.png) 两张上下文截图。

## 证据结论

- 27 个页面点、18 类 feature 已进入离线比较。
- 16 个可机器比较的子项均为 `27/27 matched`，`mismatch=0`。
- AI 自然语言文案和 clean-room diagnostic token 没有页面机器合同，保持 unavailable/非 page-exact。
- rb/sc/m × 1d/1w/60m 的 9 条真实期货序列已验证。
- 27 个 OOS 单元中 18 个日线/60 分钟单元有结果；9 个周线单元因执行事实不足而 fail-closed。
- 页面一致性结果不得冒充因果研究、模拟账户或真实账户收益。

## 可信期货验证合同

历史任务文档中仍有效的研究边界收敛为以下长期合同：

- 1d、1w、60m 必须分别通过 `MarketDataService` 读取 completed `actual_dominant`，每根 Bar 必须唯一匹配全局 `MainContractMap` owner；不得跨周期推断 owner 或回退 continuous。
- 严格研究必须绑定带来源与生效区间的 Decimal 费用、multiplier、tick、slippage 及逐成交 Bar 涨跌停事实；缺失、重叠或持仓期间 multiplier 变化都 fail-closed。
- 固定公式 Walk-forward 只用训练前缀做 causal warm-up，测试窗口空仓开始，不搜索参数；换月、拒绝成交、样本末意图和未平仓必须显式排除或记录。
- 当前只能声明 `IMPLEMENTED / EVIDENCE_PARTIAL`：9/9 序列通过，18 个 D1/60m OOS 单元有结果，9 个 W1 单元因 `NEWOW_WEEKLY_EXECUTION_LIMIT_CONTRACT_INSUFFICIENT` 阻断；完整 Canonical 输入与无数据库独立重放包仍缺失。

具体公式、对照数值与历史反例见[REPORT](REPORT.md)和
[REPLICATION_MANUAL](REPLICATION_MANUAL.md)；当前产品、Release、Runtime 与待验收仍只看
`PROJECT_SOURCE.md`、active OpenSpec 和 `STATUS.md`。

## GitHub 分发边界

本目录是从完整本地证据包整理出的 GitHub 安全版。为避免重新分发第三方完整网页/脚本以及 RQData/Canonical 行情原文，以下内容没有进入仓库：

- 牛哇完整 HTML、JavaScript 和原始接口响应；
- 股票/指数逐 Bar 原始输入；
- RQData 原始手续费、tick、涨跌停和 Canonical Bar 快照；
- 原始牛哇 PDF 手册。

`full-local-evidence-manifest.json` 保留这些本地原件的相对路径、字节数和 SHA-256，但不能在本仓库内执行完整 manifest verify。完整 manifest 文件自身的 SHA-256 为：

```text
279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f
```

## Owner 截图分发决定

2026-09-04，仓库 Owner 明确选择方案 A，批准
`docs/research/newow-v3.2.82/screenshots/**` 中现有截图继续保留在当前公开 GitHub
仓库：

```text
DISTRIBUTION_STATUS = DISTRIBUTION_APPROVED_BY_OWNER
NEWOW_SCREENSHOT_POLICY = RETAIN
```

该状态只记录 Owner 的仓库分发选择，不构成法律意见，也不扩大对第三方内容的
权利声明。它不覆盖牛哇完整 HTML、JavaScript、原始接口响应、股票/指数逐 Bar
输入或 RQData/Canonical 原始事实；这些内容仍不得进入 GitHub-safe dossier。

## 目录结构

```text
newow-v3.2.82/
├── README.md
├── REPORT.md
├── REPLICATION_MANUAL.md
├── screenshots/
│   ├── 27 个标的/周期页面截图
│   └── context/
└── evidence/
    ├── 页面一致性与决策证据
    ├── 期货/OOS 摘要
    ├── Owner 外部素材哈希索引
    ├── 来源登记
    └── 本地完整证据 manifest
```
