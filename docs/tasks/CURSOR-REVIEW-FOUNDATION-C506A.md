# CURSOR-REVIEW-FOUNDATION-C506A

更新时间：2026-07-19

对应手册任务：`C5-06A`（原 `E5-06` 可提前部分）

## 结论

状态：`COMPLETED / CURSOR_REVIEW_FOUNDATION_PREPARED`

落地 Review 正式上下文通用能力：类型/纯函数、面板、四态 fixture、deep-link 单测、报告 API 可选只读透传与 gap 报告。不依赖真实新 candidate/OOS/WF report id，不写 DB，不改 report14，不在前端算策略。

不得宣称 `STRATEGY_REVIEW_CLOSED_LOOP_READY`。

## 产物

| 路径 | 作用 |
|---|---|
| `apps/quant-web/src/types/reviewFoundation.ts` | 上下文类型 |
| `apps/quant-web/src/utils/reviewFoundation.ts` | build/parse 纯函数 |
| `apps/quant-web/src/components/review/ReviewFoundationPanel.vue` | 通用面板 |
| `apps/quant-web/tests/fixtures/reviewFoundation/*.json` | 四态 fixture |
| `apps/quant-web/tests/reviewFoundation.test.ts` | foundation 单测 |
| `apps/quant-web/tests/reviewDeepLink.test.ts` | deep-link 单测 |
| `services/quant-api/app/schemas/backtest.py` / `api/backtests.py` | 可选透传字段 |
| `services/quant-api/tests/test_review_foundation_c506a.py` | 透传回归 |
| `data/reports/strategy_review/cursor_review_foundation_gap.md` | Gap 矩阵 |

## 验证

```bash
cd apps/quant-web && node --test tests/reviewFoundation.test.ts tests/reviewDeepLink.test.ts
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_review_foundation_c506a.py
```

结果（2026-07-19）：前端 **9 passed**；后端 **4 passed**。

## 边界

- fixture `report_id=null`，无未来正式 report id
- API 透传缺键 → `null`，不伪造
- Codex X5-06B 再用真实报告闭环

## 下一入口

手册 `C6-07A`。
