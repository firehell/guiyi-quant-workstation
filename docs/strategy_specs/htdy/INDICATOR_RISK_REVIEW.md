# 火天大有 HTDY 指标风险审查

生成时间：2026-07-12

## 1. 审查结论

`huotian_dayou_original_v0` 只能作为 `observation_only` 指标。

P0 结论：

- 原始公式包含 `XMA(XMA(H,25),25)`、`XMA(XMA(L,25),25)`、`XMA(XMA(C-REF(C,1),6),6)`。
- `XMA` 属居中/偏移移动平均，会读取当前 bar 之后的数据，历史结果会随未来 bar 变化而重绘。
- `ZK1/ZD1/ZD2`、黄K/白K、三连 `买多信号/卖空信号`、`VAR23`、`回调买`、`XG`、`XG2` 均直接或间接依赖 `XMA`。
- 通达信里的 `买多预警` / `卖空预警` 在归一量化中只能解释为观察字段，不得写入 `strategy_signals` / `signal_events`；允许进入独立、显式承认重绘的 HTDY 观察提醒链路。

本阶段允许：

- tracked docs 归档完整公式。
- 写 observation-only 公式拆解、策略骨架和风险测试。
- 保留当前 Web 人工观察层。

本阶段禁止：

- 接入 `packages/quant-core/guiyi_quant/strategies/` 正式策略。
- 接入 backtest runner、PostgreSQL 报告、`strategy_signals`、`signal_events`。
- 接入 historical scanner、正式 live evaluator 或通用 SignalEvent 企业微信通知。
- 将任何原始 XMA 派生结果标记为 `validated`。

## 2. 风险分类表

| 指标 / 条件 | 分类 | 未来函数 | 重绘 | 是否可回测/预警 | 说明 |
|---|---|---:|---:|---:|---|
| `XMA` | `forbidden_for_backtest_signal` | 是 | 是 | 仅专用实时观察 | 居中/偏移窗口读取未来 bar |
| `ZK1/ZD1/ZD2` | `forbidden_for_backtest_signal` | 是 | 是 | 仅专用实时观察 | 双层 XMA 高低通道派生 |
| `黄K/白K` | `observation_only` | 是 | 是 | 仅专用实时观察 | 条件依赖 `ZD1/ZK1` |
| `买多信号/卖空信号` | `observation_only` | 是 | 是 | 仅专用实时预警 | 三连条件继承黄K/白K风险 |
| `VAR23` | `forbidden_for_backtest_signal` | 是 | 是 | 否 | 双层 XMA 处理涨跌幅 |
| `回调买` | `observation_only` | 是 | 是 | 否 | 依赖 `VAR23` |
| `XG` | `observation_only` | 是 | 是 | 否 | 依赖 `ZD1` 和 `回调买` |
| `DDX` | `candidate_after_rewrite` | 否 | 否 | 否 | 只用当前 OHLCV，但需 confirmed-bar 审查 |
| `V2/V5/V10/V20` | `candidate_after_rewrite` | 否 | 否 | 否 | 基于 `DDX` 的 SMA 链，需定义 `FROMOPEN` |
| `CURRBARSCOUNT` | `observation_only` | 否 | 否 | 否 | 图表末端语义，不等同 live/回测语义 |
| `XG2` | `observation_only` | 是 | 是 | 否 | 依赖 `ZK1`，并混入 `CURRBARSCOUNT` 语义 |
| `REF/MA/EMA/SMA/LLV/COUNT/CROSS` | `candidate_after_rewrite` | 否 | 否 | 否 | 单独看可后向，但不得自动升级整个公式 |

## 3. P0 风险

### P0-1：XMA 未来函数

通道线和 `VAR23` 都使用双层 `XMA`。在完整序列上计算时，当前 bar 的输出会读取未来 bar；如果未来尾部变化，历史位置的 `ZK1/ZD1/VAR23` 可能改变。

影响：

- 历史信号会随回测终点变化。
- 三连黄K/白K可能事后出现或消失。
- `XG/XG2` 不能作为可信入场证据。

### P0-2：预警字段不能直接映射归一量化提醒

公式中的：

```text
买多预警:买多信号,NODRAW,COLORYELLOW;
卖空预警:卖空信号,NODRAW,COLORWHITE;
```

在通达信里是提示输出；在归一量化里不能等价于正式 `signal_events`。本次决策只允许进入独立 `htdy_observation_alerts` 与专用企业微信观察提醒：JM 当前实际主力、confirmed/passed 15m、首次观察后不撤回/更正、同 bar revision 不重复，并始终显示未来函数与重绘警告。正式信号、回测或交易仍必须使用另行验证的非未来函数版本。

### P0-3：CURRBARSCOUNT 不是稳定回测字段

`CURRBARSCOUNT=1` 表达图表最后一根 K 线语义。历史批量回测、live evaluator 和不同显示窗口会对“最后一根”产生不同解释，不能直接写入策略。

## 4. P1 风险

- `FROMOPEN` 在期货多周期、夜盘和非日内周期中语义不稳定，PoC 前需要定义。
- `CAPITAL=0` 分支适合期货研究，但需记录该假设，不能把 A 股分支混入期货策略。
- 当前 Web 观察层已实现部分 HTDY 视觉逻辑，但完整公式里的黄K/白K精确定义和 `XG/XG2` 尚未对齐。

## 5. P2 后续优化

- 已设计 `huotian_dayou_strict_v1`，使用 `double_trailing_ema` 替代 `XMA`，并记录与原始版差异。
- 固定 JM 样本做 Golden Sample，覆盖未来尾部扰动、逐 bar / 批量一致性、warm-up 和无效输入。
- 如果 strict 版本通过，另开策略版本和信号事件 Plan，不覆盖 `huotian_dayou_original_v0`。

## 5.1 Strict V1 审查结论

`huotian_dayou_strict_v1` 的指标层仍定义为 `strict_research_candidate`：

- 已移除原始 `XMA(XMA(...))`，改为 trailing double EMA。
- `XG2`、`DY/DY2`、`DDX/V2/V5/V10/V20` 暂不进入 strict v1 输出。
- 第 5 步只允许进入 `offline_backtest_candidate_eval`，用于输出 candidate events 和候选分布证据。
- 即使离线候选评估完成，也不得直接接入正式策略、可信回测报告、`signal_events`、live evaluator 或企业微信；这些仍属于后续独立 Gate。

## 6. 验收标准

当前阶段通过标准：

- 三份 HTDY spec 文件齐全。
- 原始公式明确进入 docs。
- 风险审查明确 `observation_only`。
- 最小测试覆盖风险分类。
- 禁止链路无 diff：策略、live evaluator、signal、data、`.env` 不被修改。
- strict v1 若进入本阶段交付，必须额外覆盖 future-tail 不重绘、append consistency、warm-up/NaN 和非法输入。

第 4 步已完成真实 JM 256 根样本、Python/Web 数值、strict prefix/future-tail 自动验收，并通过用户提供的 `JM8 焦煤主连 15分钟` 通达信截图完成外部视觉 oracle，状态为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。未提供通达信数值导出，因此不声明逐点数值 oracle pass；该状态仍不等于可信指标定级。

第 5 步已新增只读离线候选评估：`strategy_code=huotian_dayou_strict`、`strategy_version=v0.1.0-offline`、`candidate_policy=strict_v1_15m_offline_v0`。该评估只产出 candidate events，不产出可信 PnL 或正式报告。
