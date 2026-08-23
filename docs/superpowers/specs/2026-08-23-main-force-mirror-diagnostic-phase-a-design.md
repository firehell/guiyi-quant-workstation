# Main Force Mirror Diagnostic Phase A Design

Date: 2026-08-23

## 1. Goal

对主力照妖镜 V2/V3 研究结果进行只读诊断，不替换 V2，不修改公式，不接入 Runtime。

本阶段目标不是寻找更复杂模型，而是回答：

1. 当前指标是否真正识别压力衰竭/追涨风险；
2. 当前弱效果来自标签、样本单位、特征还是模型形式；
3. 是否值得继续投入会员数据建设。

## 2. Current conclusion

现有 mfm_v3_readonly_training_probe 结论：REJECT_MODEL_REPLACEMENT。

冻结结论：

- V2 保持不变；
- 当前模型只能作为压力背景研究；
- 不作为进出场依据；
- 不作为 Alert、Runtime 或候选晋升输入。

## 3. Scope

允许：

- 只读研究脚本；
- report artifact；
- 标签审计；
- sequence forensic；
- 固定模型比较。

禁止：

- 修改 main_force_mirror_v2 公式；
- 调整 70 阈值；
- 产品专项调参；
- PnL、盈利或交易有效性结论；
- Runtime、Alert、DB、Canonical 写入。

## 4. Phase A workstreams

### A. Sequence forensic

围绕真实 caution 语义分析：

- pressure peak；
- pressure decay；
- liquidation；
- opposite build；
- accumulated pressure transition。

输出事实：

- episode 数量；
- 事件持续时间；
- state transition 分布；
- strict-prior causal window。

不输出策略结论。

### B. Label audit

审计当前 adverse excursion 标签：

- long-only adverse；
- short-only adverse；
- both；
- neither；
- horizon overlap；
- side sample duplication。

补充 first-touch episode 标签：

- adverse first；
- favorable first；
- ambiguous；
- timeout。

### C. Current score audit

解释 score 与 latch 差异：

- high score unique bars；
- long/short 分离；
- conflict；
- armed/disarmed；
- latch suppression。

禁止通过降低阈值解决。

### D. Feature ceiling probe

仅用于研究上限，不进入生产：

比较固定协议：

- ridge logistic；
- 固定浅层非线性模型；
- 不做参数搜索。

重点验证：模型不足还是信息不足。

### E. Member data feasibility

会员数据只作为未来增量研究：

- T-1 immutable snapshot；
- 日级 context；
- 60m trigger。

禁止把同日会员数据复制成独立样本。

## 5. Validation principles

- episode 优先于 Bar sample；
- 时间切分固定；
- 已使用至 2026-08-18 的数据不得重新命名为新 OOS；
- 保留 prospective shadow 边界。

## 6. Stop conditions

满足以下任一条件时停止继续复杂化：

- sequence 无稳定信息；
- strict-prior 特征无增量；
- 固定非线性模型无明显提升；
- member data 无增量价值。

## 7. Final Gate

Phase A 只允许产生：

- STOP
- ALLOW_PHASE_FREEZE_DESIGN

不得产生 PROMOTE、KEEP、WINNER 或交易结论。
