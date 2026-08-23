# Main Force Mirror Diagnostic Phase A Implementation Plan

Date: 2026-08-23

## Lane

Lane 3 research protocol design.

执行模式：Sol / 高推理 / Plan-first。

本计划只定义研究执行边界，不授权公式修改或生产操作。

## Objective

完成主力照妖镜 V2/V3 只读诊断，确认下一步研究方向。

## Work packages

## 1. Repository alignment

阅读并确认：

- STATUS.md
- PROJECT_SOURCE.md
- AGENTS.md
- DECISIONS.md
- main_force_mirror_v2 policy/service/tests

确认：

- V2 不修改；
- 当前 training probe 不替代 canonical Gate。

## 2. Diagnostic dataset contract

建立只读 artifact：

输入：

- confirmed 60m bars；
- existing V2 observation；
- existing training report。

输出：

- versioned report；
- JSON summary；
- validation metadata。

禁止写入：

- DB；
- Canonical；
- Redis；
- Runtime。

## 3. Label audit implementation

实现：

- adverse/favorable first touch；
- long/short/both/neither 分类；
- overlapping horizon 检查；
- side sample 去重统计。

验收：

报告能够解释当前 AUC 衡量的对象。

## 4. Sequence forensic

分析：

- pressure build；
- peak；
- decay；
- liquidation；
- turnover。

输出事实，不输出策略。

验收：

可以回答 V2 caution 是否形成稳定 episode。

## 5. Score-latch audit

针对 JM 和 active matrix：

输出：

- high score 数量；
- latch 触发漏斗；
- conflict；
- suppression 原因。

验收：

解释 score>=70 与 latched caution 差异。

## 6. Fixed ceiling probe

仅研究：

- 当前线性模型上限；
- 固定非线性模型是否提供信息增量。

约束：

- 不搜索参数；
- 不选择 winner；
- 不替换模型。

## 7. Member feasibility

设计未来数据接口验证：

- 数据覆盖；
- causal 时间边界；
- contract identity；
- T-1 snapshot。

不实施会员模型。

## Acceptance criteria

通过条件：

1. 所有结果可追溯到固定 artifact；
2. 不修改 V2；
3. 不产生交易结论；
4. 明确 STOP 或 ALLOW_PHASE_FREEZE_DESIGN。

## Risk controls

禁止：

- 调阈值；
- 调公式；
- JM 专项拟合；
- 使用 2026-08-18 前数据作为新 OOS；
- 接入 Alert/Runtime。

## Integration

研究文档和只读工具：

- task branch -> develop

不得：

- main；
- tag；
- Runtime promotion。
