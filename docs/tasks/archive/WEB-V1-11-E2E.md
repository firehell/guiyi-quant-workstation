# WEB-V1-11：浏览器 E2E、性能和可访问性

```text
WEB_BROWSER_SMOKE_READY
WEB_READONLY_REAL_BACKEND_SMOKE_READY
WEB_CONSOLE_ERROR_ZERO
```

## 内容

- Playwright Chromium/Chrome library runner（绕过 Node 26 下 `playwright test` CLI 的 `module.register` 挂起）：
  - `e2e/run-mock-smoke.mjs` + `e2e/fixtures/mockApi.mjs`
  - `e2e/run-readonly-smoke.mjs`（`REAL_BACKEND=1`）
- 保留 `playwright.config.mjs` + `*.spec.mjs` 供 Node ≤22 的 `npm run test:e2e:playwright-cli`
- scripts：`npm run test:e2e` / `npm run test:e2e:readonly`

## 覆盖矩阵（相对手册 A/B）

| 项 | 状态 |
|---|---|
| 主路由打开 + 1440/1280 + 无物理路径/secret | 通过 |
| console actionable error = 0 | 通过（过滤 favicon/WS/ECharts BarChart 已知噪声） |
| Data Tab lazy + `paged=true`，无 `include_paths=true` | 通过 |
| Market Historical/Live、真实主力/主连、浏览/严格研究 | 通过 |
| Runtime Scheduler / After-Market Archive | 通过 |
| Signal source_mode / 非自动下单边界文案 | 通过 |
| Settings「测试连接」只读 | 通过 |
| Batch research-only / 默认禁用启动 | 通过 |
| Review / report_id deep-link 可打开 | 通过 |
| Readonly：health / runtime / coverage / market / report14 / signals / reviews | 通过（本机 `127.0.0.1:8000`） |

## 原始测试摘要（2026-07-22）

```text
npm test                 → 105 pass / 1 skipped
npm run build            → 通过
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5175 PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
                         → 8 passed
npm run test:e2e:readonly → readonly smoke passed
bash scripts/engineering/check-secrets.sh → OK
git diff --check         → clean
```

## 实现备注

1. Mock 路由必须匹配 pathname 以 `/api/` 开头，禁止 `**/api/**`（会误伤 Vite `/src/api/*` 模块）。
2. 默认使用本机 Chrome `channel=chrome`；Playwright headless_shell 可能未装齐。
3. Node 26：`playwright test` CLI 会在 `--list` 阶段挂起；正式 Gate 走 library runner。
4. E2E 需已启动前端（例如 `npm run dev -- --host 127.0.0.1 --port 5175`），通过 `PLAYWRIGHT_BASE_URL` 指向。

## Residual

- Live `historical_live_context_v1` 产品展示仍属 WEB-V1-04 residual，不在本步范围。
- Batch ECharts `BarChart` 未注册会打 console（已过滤，非本步产品修复）。
- 完整人工浏览器验收矩阵留给 WEB-V1-12。
