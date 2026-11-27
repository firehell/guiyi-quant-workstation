# Strategy Center 任务拆分

本变更当前交付目标为完整架构设计和可审查的能力合同；本提交不实施代码、数据库、配置或 Runtime 变更。

## A. 现状盘点与边界

- [x] A1. 对照 PROJECT_SOURCE、ARCHITECTURE、DECISIONS、STATUS 和现行领域合同，确认六个保留策略身份。
- [x] A2. 区分正式策略、Alert、通用指标、L.M.S 研究模式和已退役策略。
- [x] A3. 明确 Newow、HTDY/TQKQ、SuBing 三个领域的公式、状态、结果和账户所有权。
- [x] A4. 明确 Newow Dual Fusion 是组合策略身份，不是第四套基础公式。

## B. 目标架构与合同

- [x] B1. 定义静态 Strategy Catalog 与策略类型。
- [x] B2. 区分 Formula、Profile、Policy、Binding、Deployment、Run 和 Evidence 身份。
- [x] B3. 定义领域只读 Adapter 与运行/结果投影。
- [x] B4. 定义能力、配置、授权、Runtime 和 Evidence 的独立状态维度。
- [x] B5. 定义计算共享、领域状态串行、账户串行和有界查询约束。
- [x] B6. 定义只读 API、Web 结构和部分失败行为。
- [x] B7. 定义人工晋升、退役和历史证据保留边界。

## C. 后续实现（不属于本次提交）

- [ ] C1. 实现六个策略身份的静态目录及合同测试。
- [ ] C2. 实现 Profile/Policy/Capability 的只读引用解析。
- [ ] C3. 实现 Newow 只读适配，验证趋势、震荡、主升浪和 Dual Fusion 结果来源。
- [ ] C4. 实现 HTDY/TQKQ 只读适配，验证账户级顺序和原生回报引用。
- [ ] C5. 实现 SuBing Portfolio 只读适配，验证单一共享 Run/Journal。
- [ ] C6. 实现只读 Strategy API 和按领域分组的 Web 工作台。
- [ ] C7. 验证领域部分不可用、状态过期、超时、缺失证据和权限不匹配。
- [ ] C8. 对照冻结输入进行多策略共享计算和并发性能测试；未经证据不得调整现有 Worker/队列。
- [ ] C9. 完成独立 Review、受影响测试和后续 active delta；不由本设计提交自动授权 Runtime 变更。

## 验收边界

- 本次仅要求 A/B 完成；C 全部保持未完成。
- OpenSpec change 保持候选设计，不同步 active specs，不更新 STATUS、PROJECT_SOURCE 或 ARCHITECTURE。
- 代码存在、目录登记、Web 显示和历史测试都不能证明 Runtime 已启用或自然业务已验收。
