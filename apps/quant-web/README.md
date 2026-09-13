# Quant Web

Vue 3 + TypeScript 的 Market Web，公开页面为 `/market` 与 `/market/chart`。

- 首页：completed D1/W1 市场概览、Runtime 状态与当前 Alert Events，共三项资源读取。
- 详情：Newow、HTDY、苏冰、Free 四视角，共享品种、行情身份、周期与历史定位。
- Newow：趋势、震荡、主升浪的 typed 策略状态、BUILD/CLEAR、Hint、参考历史及解释。
  当前代码支持日/周/60m；分阶段开放规划不等于已经收窄 API，实际验收范围见
  [STATUS.md](../../STATUS.md)。
- 苏冰：Event-backed `S↑/S↓` 与独立的“历史重算·乐观参考”；HTDY 保留 retrospective
  overlay、Scope/Runtime 只读事实和不可变 Event；Free 提供通用行情与指标。
- 通用 Overlay 只有 `none | htdy`；Newow 使用独立 Workspace 图层。通用指标包括 EMA、MACD、Range。

Web 消费后端策略和参考交易结果，不自行计算策略动作；建仓/清仓标记与参考收益不表示模拟或真实
持仓、订单、成交和账户收益。四层事实边界见 [PROJECT_SOURCE.md](../../PROJECT_SOURCE.md)，
依赖与旧链接兼容见 [ARCHITECTURE.md](../../docs/ARCHITECTURE.md)。

验证命令统一见 [TESTING.md](../../TESTING.md)。Web 测试只证明代码与交互，
不证明 Runtime、自然事件或通知送达。
