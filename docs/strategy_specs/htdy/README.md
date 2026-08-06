# 火天大有（HTDY）策略研究索引

更新时间：2026-08-06

## 当前定位

HTDY 保留指标公式、风险语义、golden sample、离线因果评估和 observation-only 研究规则。
旧正式回测、OOS、trusted report/candidate、Review Foundation、S6-08/S6-09/S6-10 packet 与
验收控制面已经退役，只能从 Git history 追溯，不能作为当前兼容入口或授权。

未来如需重建回测，必须新建任务并重新定义策略版本、数据身份、撮合、成本、OOS 与验收合同；
不得复用旧 report id、task id、packet、receipt、配置或页面/API。

## 保留文档

- [`INDICATOR_SPEC.md`](INDICATOR_SPEC.md)：original 指标公式与输入定义。
- [`INDICATOR_RISK_REVIEW.md`](INDICATOR_RISK_REVIEW.md)：未来函数、居中窗口与重绘风险。
- [`GOLDEN_SAMPLE_ACCEPTANCE.md`](GOLDEN_SAMPLE_ACCEPTANCE.md)：当前指标 golden sample 证据。
- [`OFFLINE_CANDIDATE_EVAL.md`](OFFLINE_CANDIDATE_EVAL.md)：只读、零写入的离线因果评估边界。
- [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md)：通用策略规则与研究语义。
- [`STRICT_V1_SPEC.md`](STRICT_V1_SPEC.md)：独立 causal strict 版本，不把 original 最终形态回填为历史首次出现。
- [`../../INDICATOR_KERNEL.md`](../../INDICATOR_KERNEL.md)：公共指标注册表、能力矩阵与 realtime
  first-seen 白名单。

## Original 与 strict 边界

- original 使用 centered/XMA 风格定义，存在未来依赖与重绘风险，普通能力只能
  `observation_only`。
- original 的唯一例外是 canonical 指标合同冻结的 JM、RQData rank=1 actual dominant、
  confirmed `15m` realtime first-seen observation policy。
- first-seen 事件必须保存当时输入、首次观察时间、future dependency 与 repainting snapshot；
  不得用后续最终形态改写。
- strict 是独立 causal 研究版本，只使用当时及过去数据；它不自动获得 active 回测、live、
  通知或交易入口。
- original 与 strict 的 code、version、policy 和证据不可混用。

## 安全字段

HTDY 研究输出必须明确：

```text
observation_only=true
not_trading_instruction=true
future_looking=<explicit>
repainting_accepted=<explicit>
historical_backtest_allowed=false
notification_allowed=false
auto_order=false
```

任何缺失、异常、过期或不一致配置都 fail-closed。repair、replay、backfill、migration 与 EOD
recalculation 不补发历史通知。

## 数据边界

- RQData 是唯一外部行情事实源。
- 正式历史输入来自质量通过的 Canonical；DataGap、identity 漂移或未确认 bar 一律拒绝。
- `continuous` 与 `actual_dominant` 不可互换；actual dominant 必须绑定 MainContractMap rank=1
  有效区间。
- historical canonical 与 live observation 分离；live preview 不能提升为正式历史事实。

## 当前结论

HTDY 文档只支持指标与策略研究、风险审查和 observation-only first-seen 语义，不声明策略盈利、
历史回测资格、OOS 通过、Runtime ready、通知 ready 或交易 ready。旧 X5/R45/S6 历史结论和证据
已从 active repository 删除，恢复只使用 Git history。
