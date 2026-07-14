# CODEX_HANDOFF.md

更新时间：2026-07-14

## 1. 接手结论

当前仓库路径：

```text
/Volumes/扩展盘/guiyi-quant-workstation
```

当前事实源更新任务：`PROJECT-FACT-SOURCES-GPT-SOURCES-CLOSURE`。

本轮只允许文档事实源与 GPT Project Sources 收口，不开发新功能，不写 DB/Parquet/manifest/checksum，不触碰 `.env` 或运行配置。

当前数据层最终状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不代表当前数据层最终封板完成。

## 2. 必读顺序

1. `AGENTS.md`
2. `PROJECT_SOURCE.md`
3. `STATUS.md`
4. `CODEX_TASKS.md`
5. `tasks/current.md`
6. `project_sources/00-INDEX.md`
7. `docs/DATA_CENTER.md`
8. `docs/ARCHITECTURE.md`
9. `docs/BACKTEST_ENGINE.md`
10. `docs/SIGNAL_EVENTS.md`

## 3. 当前可信事实

Phase 3 DB 口径：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |

关键边界：

- 105 条 `quality_warning` 保持 warning，不升级为 passed。
- 当前不能宣称“全品种周线从上市以来完整”。
- Stage 9-B2 historical replay single-send smoke 不等于 live-confirmed 或长期发送能力。
- `report_id=14` trust audit passed 不代表策略盈利、稳定或可实盘。

## 4. active 数据硬约束

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 Gate 默认使用 `quality_status=passed`。禁止 validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据进入默认 Market、Backtest、Signal。

## 5. 运行与安全

- PostgreSQL / Redis 只允许本地或受控环境；凭据只走环境变量。
- 企业微信 webhook 只允许从 `QYWX_WEBHOOK_URL` 环境变量读取。
- 不打印或提交 webhook、token、password、license、cookie、证书私钥或账号。
- 不自动下单，不接实盘账户，不新增交易 gateway。
- 不运行 live scheduler 或企业微信批量发送，除非另有明确任务和人工授权。

## 6. 下一步

按优先级另开任务：

1. manifest / DB 对齐专项 Plan。
2. pre-2020 周线 34 品种缺口专项 Plan。
3. JM T3-real 单次 live 写入 Gate。
4. 真实公网安全 smoke。
5. OOS / walk-forward 全窗口验证。

以上涉及数据写入、runtime、scheduler、外部服务或回测口径的任务默认先 Plan。

## 7. 最小验证

文档任务：

```bash
git status --short --branch
git diff --check
git diff --stat
git diff --name-only
```

后端回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests
uv run --project services/quant-api ruff check services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

前端回归：

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
```

回测 trust audit：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id 14 --format markdown
```
