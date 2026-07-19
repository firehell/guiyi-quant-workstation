# CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A

更新时间：2026-07-19

对应手册任务：`C6-07A`（原 `F6-07` 可提前部分）

## 结论

状态：`COMPLETED / CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED`

落地 Market/Runtime 只读观察契约：类型/纯函数、面板、四态 fixture、live targets 路径脱敏、前后端定向测试与 gap 报告。未启动 runtime、未调 RQData、未写 DB、未建订阅、未发企业微信。

不得宣称 `JM_LIVE_ARCHIVE_OBSERVATION_READY`。

## 产物

| 路径 | 作用 |
|---|---|
| `apps/quant-web/src/types/marketRuntimeObservation.ts` | 观察上下文字段 |
| `apps/quant-web/src/utils/marketRuntimeObservation.ts` | build / 敏感字段检查 |
| `apps/quant-web/src/components/market/MarketRuntimeObservationPanel.vue` | 只读面板 |
| `apps/quant-web/tests/fixtures/marketRuntime/*.json` | 四态 fixture |
| `apps/quant-web/tests/marketRuntimeObservation.test.ts` | 前端单测 |
| `services/quant-api/app/services/live_target_contracts.py` | file_path strip + sanitize |
| `services/quant-api/tests/test_market_runtime_foundation_c607a.py` | 后端回归 |
| `data/reports/market_runtime/cursor_market_runtime_foundation_gap.md` | Gap + Codex 清单 |

## 验证

```bash
cd apps/quant-web && node --test tests/marketRuntimeObservation.test.ts
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_runtime_foundation_c607a.py
```

结果（2026-07-19）：前端 **7 passed**；后端 **3 passed**。

## 边界

- historical/live 不静默混合；degraded ≠ healthy
- confirmed / partial 分列；same-bar 不合并
- API 不返回物理路径

## 下一入口

手册 `C-HANDOFF`。
