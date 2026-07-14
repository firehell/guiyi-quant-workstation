# 测试与验证入口

更新时间：2026-07-14

## 文档任务必跑

```bash
git status --short --branch
git diff --check
git diff --stat
git diff --name-only
```

状态词扫描：

```bash
rg -n "2020|2023|82/90|8 partial|metadata_gap|READY|PARTIAL|PENDING|阿里云|腾讯云|JM2609|report_id=14|Stage 9|五个交易日" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs tasks --glob '*.md'
```

敏感信息扫描：

```bash
rg -n -i "password|passwd|token|secret|webhook|api[_-]?key|authorization|cookie" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs/gpt docs/*.md tasks --glob '*.md'
```

说明：上述扫描会命中文档中的安全规则、环境变量名和脱敏说明。验收时需确认没有真实密钥值、真实 webhook URL、账号或 cookie。

## 后端常用验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests
```

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

Alembic：

```bash
cd services/quant-api
uv run python -m alembic current
uv run python -m alembic heads
```

## 前端常用验证

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
```

## 数据与回测只读验证

数据层 final audit 只读运行示例：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir data/reports/data_layer_final_audit_manual
```

回测 trust audit：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

## Gate 说明

- 文档验证通过不等于代码测试通过。
- 单元测试通过不等于真实运行 Gate 通过。
- Stage 9-B2 historical replay single-send smoke 不等于 live-confirmed smoke。
- `report_id=14` trust audit passed 不等于策略盈利、稳定或可实盘。
- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 不等于 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。

