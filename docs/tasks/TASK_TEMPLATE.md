# TASK 标准任务单模板（21 字段）

> 配套：`STATE_MACHINE_TICKET.md`（10 状态机）、`TASK_MATRIX.md`（18 类任务）。
> 用法：复制本模板，替换 `{{ }}` 占位符；状态流转按状态机规则推进；参与角色按 `TASK_MATRIX.md` 选取。
> 所有 Prompt（第 15–17 节）由后端开发负责人产出，安全专家过护栏。
> **WorkBuddy 只填模板、出 Prompt、维护状态，不自行写仓库代码、不 push / merge / deploy。**

---

```markdown
# TASK-{{日期}}-{{编号}}：{{任务名称}}

## 1. 任务状态
{{ IDEA / REQUIREMENT_READY / PLAN_READY / APPROVED_DEV / CODING / TESTING / DELIVERY_READY / CLOSED / FAILED / REPLAN }}

## 2. 任务类型
{{ 普通功能开发 / 数据模块开发 / 实时行情监听 / 多周期聚合 / 策略开发 / 策略研究与验证 / 企业微信告警 / Dashboard / 回测模块 / 数据质量检查 / Mac mini 部署 / AI 工作流优化 / 三工具协作优化 / GitHub 版本管理 / 安全权限 / 测试体系 / 交互视觉规范 / 阶段交付复盘 }}
参照：TASK_MATRIX.md

## 3. 参与角色
- 必须：{{ PM, PO, ... }}（按 TASK_MATRIX 必须列）
- 可选：{{ ... }}
- 不需要：{{ ... }}

## 4. 背景
{{ 为什么做、来源想法、关联历史任务 / Stage }}

## 5. 目标
{{ 可量化 / 可验收的产出 }}

## 6. 不做事项
{{ Non-goals：明确不做的范围，尤其是"不自动交易 / 不自动 push"等 }}

## 7. 涉及模块
{{ 代码模块 / 接口 / 文件，如 services/quant-api/app/signal/* }}

## 8. 产品需求
{{ PRD：场景 / 边界 / 验收目标 }}

## 9. 量化业务规则
{{ 交易时段 / 夜盘 / 节假日 / 主力合约 / 切换 / 手续费 / 滑点 / 乘数 / 保证金 }}

## 10. 数据影响
{{ RQData 使用 / 1m 基础 / 聚合 / 归档 / 缺失重复 bar / active Gate / 是否真实写入（dry-run 默认） }}

## 11. 技术方案
{{ 架构方案 / 模块边界 / 接口契约 / 数据流·策略流·信号流·告警流 }}

## 12. 交互视觉要求
{{ 信息架构 / 消息格式 / 状态颜色（红涨绿跌）/ 展示规范 }}（页面 / 告警类必填）

## 13. 安全权限要求
{{ 不碰 .env/token/webhook / 不删数据 / 不自动 push-merge-deploy / dry-run 默认 / 脱敏 }}（外部 / 凭证类必填）

## 14. 开发步骤
1. {{ step }}
2. {{ step }}
（每步标注是否需用户显式授权）

## 15. Codex Plan Prompt
```
{{ 只读 plan 提示词：分析仓库、产出方案，不修改代码 }}
```

## 16. Codex Dev Prompt
```
{{ 开发提示词：按方案实现，默认 dry-run，明确测试点 }}
```

## 17. CodeBuddy 执行 Prompt
```
{{ 本地执行入口提示词：调 Codex CLI 开发 / 跑测试，声明不 push / 不 merge }}
```

## 18. 测试清单
- [ ] {{ 单元测试 }}
- [ ] {{ 集成测试 }}
- [ ] {{ 回归测试 }}
- [ ] {{ 烟测 }}
- [ ] {{ 专项：数据聚合正确性 / 信号准确性 / 企业微信重复漏发误发 / Mac mini 稳定性 }}

## 19. 验收标准
{{ 明确 pass / block 条件；引用 PRD 验收目标 }}

## 20. 风险点
{{ 重绘 / 未来函数 / 过拟合 / 夜盘跨日 / active 未分层 / 凭证泄露 / 越权发送 / 自动部署 }}

## 21. 交付记录
- 状态流转：{{ IDEA → ... → CLOSED }}
- 测试结论：{{ pass / block }}
- 交付报告：{{ 链接 / 摘要 }}
- 合并前检查：{{ git diff --check / 测试通过 / 无敏感泄露 }}
- 用户 review：{{ 待 / 已 merge / 已 deploy }}
- 下一阶段建议：{{ ... }}
```

---

## 使用说明

- 本模板与 `ROLE_SPEC.md`、`TASK_MATRIX.md`、`STATE_MACHINE_TICKET.md` 三者配套：矩阵定"谁出场"，状态机定"怎么流转"，模板定"写什么"。
- 任务编号统一 `GQ-YYYYMMDD-NNN`（或 `TASK-YYYYMMDD-NNN`），由 PM 在 IDEA 状态分配，不重复、不跳号。
- **状态门控铁律**：Plan Prompt 在 `PLAN_READY` 启用（只读）；Dev / Exec Prompt 在 `APPROVED_DEV` 才启用。
- 所有"真实写入 / 发送 / 部署 / 回滚"动作默认需用户显式授权；模板第 13、14、20 节必须显式声明。
