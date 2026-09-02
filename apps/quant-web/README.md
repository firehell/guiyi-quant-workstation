# Quant Web

Vue 3 + TypeScript 的 Market Web，仅包含 `/market` 与 `/market/chart`。

- Market 首页：Runtime 状态与按后端 taxonomy 分组的品种目录。
- 图表页：Canonical/Live K 线、成交量、OI、通用 EMA/MACD、Range Detector、HTDY retrospective overlay、HTDY Scope/Event。
- Overlay 仅 `none | htdy`；旧偏好值读取时归一为 `none`。
- 不计算策略，不显示建仓、清仓、持仓或全历史策略效果。

```bash
pnpm test
pnpm build
pnpm test:e2e
```

Web 测试只证明前端代码与交互，不证明 Runtime、自然事件或通知送达。
