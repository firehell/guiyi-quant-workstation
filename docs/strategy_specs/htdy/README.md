# 火天大有（HTDY）策略研究索引

更新时间：2026-08-08

## 当前定位

HTDY 保留指标公式、策略规则与 observation-only 研究语义。
一次性 RISK/GOLDEN/OFFLINE 验收文档与旧正式回测、OOS、S6 packet 已从工作树删除，只能从 Git history 追溯，不能作为当前兼容入口或授权。

未来如需重建回测，必须新建任务并重新定义策略版本、数据身份、撮合、成本、OOS 与验收合同；
不得复用旧 report id、task id、packet、receipt、配置或页面/API。

## 保留文档

- [`INDICATOR_SPEC.md`](INDICATOR_SPEC.md)：original 指标公式与输入定义。
- [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md)：通用策略规则与研究语义。
- [`STRICT_V1_SPEC.md`](STRICT_V1_SPEC.md)：独立 causal strict 版本，不把 original 最终形态回填为历史首次出现。
- [`../../INDICATOR_KERNEL.md`](../../INDICATOR_KERNEL.md)：公共指标注册表、能力矩阵与 realtime
  first-seen 白名单（盘中 realtime 应用路径已退役）。

## Original 与 strict 边界

- original 使用 centered/XMA 风格定义，存在未来依赖与重绘风险，普通能力只能
  `observation_only`。
- original 的唯一例外是 canonical 指标合同冻结的 JM、RQData rank=1 actual dominant、
  confirmed `15m` realtime first-seen observation policy（当前无盘中应用路径）。
- strict 独立定义 causal 规则，不把 original 的居中窗口语义回填为「历史首次出现」。

盘中 Live / signal worker / Review Web 当前均已卸；Market 工作台可展示 HTDY 相关指标叠加供人工观察。
