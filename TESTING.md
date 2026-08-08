# 测试与验证入口

更新时间：2026-08-08

所有数据写入测试必须使用 `tmp_path`、临时 Canonical 根和隔离数据库。禁止将测试 URL
指向 Runtime/生产数据库。

## 后端

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests packages/quant-core/guiyi_quant

MYPYPATH=services/quant-api \
uv run --project services/quant-api mypy --explicit-package-bases --ignore-missing-imports \
  services/quant-api/app/market_data \
  services/quant-api/app/guiyi_cli \
  services/quant-api/app/api/market.py \
  services/quant-api/app/models/data_center.py \
  services/quant-api/app/models/data_core.py
```

数据基础定向套件：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/data_foundation
```

C2.5 Candidate target 的 focused fixture 测试（只使用临时 root 和 SQLite；不读取
`GUIYI_CANDIDATE_DATABASE_URL` 的真实值）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_foundation/test_composition.py \
  services/quant-api/tests/data_foundation/test_cli.py \
  services/quant-api/tests/data_foundation/test_infrastructure.py \
  services/quant-api/tests/data_foundation/test_maintenance.py
```

该组覆盖 Candidate fresh/extend metadata、root containment、环境变量只作为不回显的连接来源、
historical provider Calendar/Session facts，以及 direct `1w` 的 full-ISO-week/provider-weekly 对齐；
不是 Gate A，也不连接真实 RQData、Candidate DB 或 Canonical。

## Alembic

无数据库写入的 SQL 生成检查：

```bash
cd services/quant-api
PYTHONPATH=. uv run alembic upgrade 20260808_0035:20260808_0036 --sql
```

实际 migration 测试只在专用可丢弃 PostgreSQL 中运行：

```bash
GUIYI_ISOLATED_MIGRATION_DATABASE_URL='postgresql+psycopg://...' \
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/alembic
```

`20260808_0036` 不可逆；不在本地无害测试中执行 downgrade。

## 前端

```bash
npm --prefix apps/quant-web test
npm --prefix apps/quant-web run build
```

## CLI 无写入 smoke

```bash
uv run --project services/quant-api guiyi data update --universe active --through 2026-08-07
uv run --project services/quant-api guiyi data bootstrap --universe active --through 2026-08-07
uv run --project services/quant-api guiyi data audit --universe active
```

前两条不带 `--apply` 时只输出结构化计划，不初始化 RQData 客户端，不写 PostgreSQL/Parquet。
`audit` 不调用 RQData，但会只读当前配置的 Catalog/Canonical；对正式环境执行时仍应明确目标。

## 最终检查

```bash
git diff --check
git status --short
```

另做旧数据语言的 active-reference 扫描。Alembic 历史和 OpenSpec archive 可保留历史名称；
active 代码、前端与 canonical 文档不得依赖它们。

C2.5 还需确认已删除的一次性 operator 没有 active source reference：

```bash
rg -n -i 'gate_a_operator|candidate_rqdata_operator|candidate[_-]gate[_-]a' \
  services/quant-api/app services/quant-api/tests apps/quant-web docs \
  STATUS.md PROJECT_SOURCE.md DECISIONS.md \
  --glob '!**/alembic/**' --glob '!openspec/changes/archive/**'
```
