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

## 阅读入口

- [完整策略与指标报告](REPORT.md)
- [页面一致性结果](evidence/core-page-parity-results.json)
- [综合决策可达性](evidence/composite-reachability.json)
- [AI 模板与周日矩阵证据](evidence/ai-template-evidence.json)
- [期货迁移摘要](evidence/futures-validation-summary.json)
- [OOS / 成本压力矩阵](evidence/oos-cost-stress-matrix.json)
- [来源登记](evidence/source-registry.json)
- [本地完整证据清单](evidence/full-local-evidence-manifest.json)

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

若仓库将设为公开，还应由仓库所有者确认第三方页面截图的公开分发权限。

## 目录结构

```text
newow-v3.2.82/
├── README.md
├── REPORT.md
├── screenshots/
│   ├── 27 个标的/周期页面截图
│   └── context/
└── evidence/
    ├── 页面一致性与决策证据
    ├── 期货/OOS 摘要
    ├── 来源登记
    └── 本地完整证据 manifest
```
