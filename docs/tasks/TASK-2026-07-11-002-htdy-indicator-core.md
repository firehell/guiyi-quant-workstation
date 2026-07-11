# TASK-2026-07-11-002：火天大有指标与策略规范

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002-htdy-indicator-core |
| GitHub Issue | #10 |
| Branch | codex/htdy-indicator-core |
| Worktree | /Volumes/扩展盘/guiyi-parallel/htdy-core |
| Status | DELIVERY_READY |
| 公式输入路径 | `private_sources/htdy/`（用户提供的通达信公式，gitignore） |

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

策略研究与验证 / 指标规范

## 3. 参与角色

- 必须：策略研究员、量化架构师、安全专家
- 不需要：前端、live runtime、企业微信

## 4. 背景

用户将提供「火天大有」通达信公式。仓库内尚无 HTDY 实现。需对照 `tdx_xma_bands` 风险审查模板，产出 observation-only 规范，**不接** vn.py 主链、信号扫描、企业微信。

## 5. 目标

1. 整理 `docs/strategy_specs/htdy/INDICATOR_SPEC.md`（参数、IO、公式逐步解释）
2. 编写 `INDICATOR_RISK_REVIEW.md`（lookahead、未来函数、过拟合、期货适配）
3. 编写 `STRATEGY_SPEC.md` 骨架（入场/出场/止损/过滤/周期），标记 `observation-only`
4. 可选：`experiments/htdy_indicator/` PoC（strictly backward-looking 改写优先）

## 6. 不做事项

- 不接入 `packages/quant-core/guiyi_quant/strategies/` 正式策略
- 不接入 PostgreSQL 报告、信号扫描、企业微信、vn.py Runner 主路径
- 不自动交易、不 live 提醒
- 不提交 `private_sources/` 内用户私有公式到 git（若含敏感内容）

## 7. 涉及模块

**允许修改**：

- `docs/strategy_specs/htdy/`
- `experiments/htdy_indicator/`
- `services/quant-api/tests/test_htdy_indicator_risk.py`
- `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
- `tasks/current.md`
- `.ai/results/TASK-2026-07-11-002-htdy-indicator-core/`

**禁止修改**：

- `packages/quant-core/guiyi_quant/strategies/`
- `services/quant-api/app/` 信号/扫描/通知业务
- `apps/`、`data/`、`.env`

## 8. 产品需求

- 规范足够让外部审查（ChatGPT）判断能否进入 Stage 7.5 向后看改写
- 明确与 V1-B 苏冰主线的关系：并行研究，不替换

## 9. 量化业务规则

- 期货：注明合约乘数、夜盘、主力/actual 合约假设
- 任何 XMA/偏移均线必须标注 lookahead 风险

## 10. 数据影响

- 无 RQData 写入；PoC 仅用本地实验数据或 synthetic bars

## 11. 技术方案

1. 读取 `private_sources/htdy/` 用户公式
2. 参照 `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
3. 若 PoC：参照 `experiments/rqalpha_tdx_xma_bands/xma_core.py` 结构
4. 风险测试：未来函数/重绘检测 stub

## 12. 交互视觉要求

无 Web 变更（后续 Web overlay 属会话 C）

## 13. 安全权限要求

- 不提交 API Key；private_sources 已在 .gitignore

## 14. 开发步骤

1. 确认 `private_sources/htdy/` 有公式文件（用户放入）
2. Plan：公式解析与风险框架
3. Dev：编写三份 spec + 可选 PoC/测试
4. 标注 `observation-only`

## 15. Codex Plan Prompt

```
只读 Plan。必读 AGENTS.md、docs/strategy_specs/tdx_xma_bands/、private_sources/htdy/（若存在）。
任务：火天大有指标规范与风险审查。不得接入正式策略或信号链路。
输出：公式拆解计划、风险清单、Spec 目录结构、PoC 是否必要。
```

## 16. Codex Dev Prompt

```
按已批准 Plan 编写 docs/strategy_specs/htdy/ 三份文档。
可选 experiments/htdy_indicator/ 与 test_htdy_indicator_risk.py。
标记 observation-only。禁止改 packages/quant-core 正式策略。
```

## 17. CodeBuddy 执行 Prompt

```
worktree: /Volumes/扩展盘/guiyi-parallel/htdy-core
branch: codex/htdy-indicator-core
启动前确认 private_sources/htdy/ 有公式。不 push/merge/deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
uv run --project services/quant-api pytest services/quant-api/tests/test_htdy_indicator_risk.py -q
git diff --check
```

- [ ] 三份 spec 文件存在且互相引用一致
- [ ] 风险审查含 lookahead/未来函数章节
- [ ] 可选 pytest passed

## 19. 验收标准

- `docs/strategy_specs/htdy/` 三文件齐全
- 文档明确 `observation-only`
- 未修改正式策略与信号扫描

## 20. 风险点

- 通达信 XMA 类未来函数直接进入回测
- 用户公式误入 git 提交

## 21. 交付记录

- 合并目标：main（在 data-audit 之后、jm-live-gate 之前）
