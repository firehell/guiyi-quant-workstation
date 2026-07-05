# Current Task

## Task ID

`DATA-001-rqdata-source-slimdown`

## 任务名称

数据源瘦身：移除旧天勤 / 交易练习者数据并收敛 RQData 主链路。

## 背景

当前 V1 active 数据主链路必须收敛为：

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL 元数据和质量状态
```

TqSdk / 天勤、交易练习者数据不再作为当前 active 数据入口。TqSdk 只保留为未来备用候选；如 RQData 后续出现问题，再单独设计重新引入。

## 本轮目标

- 删除或隔离旧 TqSdk / 天勤下载数据、交易练习者数据、TqSdk 临时下载数据。
- 默认正式读取只使用 `source = rqdata / local_parquet`、`data_role = primary`、`quality_status != failed`。
- 严格研究口径可要求 `quality_status = passed`。
- 统一层只保留 schema 标准化、字段校验、时间字段规范、quality_status、manifest/checksum、数据角色过滤。
- 更新代码、测试、文档和任务状态，避免后续 Agent 把 TqSdk 或交易练习者当成当前 V1 数据链路。

## 允许修改范围

- `tasks/current.md`
- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `README.md`
- `.env.example`
- `docs/DATA_CENTER.md`
- `docs/ROADMAP.md`
- `docs/NEXT_STEPS.md`
- `docs/PROJECT_INVENTORY.md`
- `docs/RQDATA_ONLY_ARCHITECTURE.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `services/quant-api/pyproject.toml`
- `services/quant-api/uv.lock`
- `services/quant-api/app/data_sources/`
- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/services/trader_future_importer.py`
- `services/quant-api/app/services/tqsdk_ingest/`
- `services/quant-api/app/schemas/backtest.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/app/backtest/service.py`
- `services/quant-api/app/cli.py`
- `services/quant-api/tests/`
- `scripts/tqsdk_*.py`
- `apps/quant-web/src/types/`
- `apps/quant-web/src/pages/backtest/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- Old data files under `data/raw/tqsdk/`, `data/raw/trader_Future_data/`, `data/parquet/**provider=tqsdk*/`, `data/parquet/**provider=trader_future_data*/`, `data/tmp/tqsdk*`, `data/manifests/tqsdk_*`, `data/reports/tqsdk_*`

## 禁止修改范围

- 不修改数据库 migration。
- 不写入数据库。
- 不运行 RQData 下载。
- 不删除历史回测报告。
- 不修改策略交易行为。
- 不接实盘 / 模拟盘 / CTP / TqSdk 交易接口。
- 不写入 `.env`、账号、密码、Token、API Key、license、交易密钥。
- 不删除 RQData / primary 数据目录。

## 执行模式

- 当前执行实现。
- 数据读取行为改动按 TDD 执行。
- 删除数据前记录清单和体积。
- 触发 Gate 必须暂停。

## 任务步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 测试命令 | 测试结果 | 风险记录 |
|---|---|---|---|---|---|---|---|
| 0 | done | low | 分支初始化与任务记录 | `tasks/current.md` | `git status --short`; `git branch --show-current`; `du -sh ...` | passed | 已从 `main` 创建 `codex/data-001-rqdata-slimdown`；删除前记录旧目录体积 |
| 1 | done | medium | 数据读取测试先行 | `services/quant-api/tests/` | targeted pytest | passed | 已覆盖默认读取排除 TqSdk / trader、非 primary role 拒绝 |
| 2 | done | medium | 后端数据源收敛 | data source / reader / schemas / service | targeted pytest | passed | 历史字段枚举保留兼容，新建回测/信号/读取不开放 active 入口 |
| 3 | done | high | 删除旧数据和旧入口 | `data/`, `scripts/tqsdk_*`, inactive services | `find data ...` | passed | 已删除 tracked TqSdk manifest/report/tmp 和 inactive 服务脚本；data 查找无残留 |
| 4 | done | medium | 前端与文档收敛 | Web types/pages, docs | `pnpm build` | passed | Web 只展示 primary；文档改为 removed / future backup 口径 |
| 5 | done | medium | 最终验证 | tests/docs/status | full pytest, ruff, build | passed | `ruff`、targeted pytest、full pytest、前端 build 均通过 |

## Gates

| Gate | 触发条件 | 暂停时必须报告 |
|---|---|---|
| Gate 0 | 仍在 `main` 且准备改文件 | 当前分支、工作区状态、建议分支 |
| Gate 1 | 工作区出现非本轮未提交改动 | 改动文件、是否相关、继续风险 |
| Gate 2 | 需要 migration、数据库写入、RQData 下载、真实凭据读取、实盘/模拟盘接口 | 触发原因、拟修改文件、风险和确认问题 |
| Gate 3 | 准备删除 RQData / primary 数据或历史回测报告 | 当前完成情况、拟删除路径、风险和确认问题 |
| Gate 4 | 测试、ruff、前端 build 失败 | 失败命令、错误摘要、拟修文件或下一步 |

## 验收标准

- [x] 当前分支不是 `main`。
- [x] TqSdk / 天勤旧数据和交易练习者旧数据已从当前 active 数据目录移除。
- [x] TqSdk 临时下载、manifest、audit report 已清理。
- [x] RQData / primary 数据目录保留。
- [x] 默认正式读取只使用 `rqdata / local_parquet`、`primary`、`quality_status != failed`。
- [x] 新建回测 / 信号 / 市场查询不再接受 `validation`、`legacy_reference` 作为 active 数据入口。
- [x] 文档不再把 TqSdk 旧数据写成当前 validation source，不再把交易练习者写成当前 legacy_reference 入口。
- [x] 未修改 migration，未写数据库，未运行 RQData 下载，未写敏感信息。

## 测试命令

```bash
git status --short
git branch --show-current
uv run --project services/quant-api ruff check .
uv run --project services/quant-api pytest -q services/quant-api/tests/test_data_sources.py services/quant-api/tests/test_market_data_reader.py services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_data_center_api.py services/quant-api/tests/test_backtest_task_api.py services/quant-api/tests/test_backtest_service_runner.py
uv run --project services/quant-api pytest -q
cd apps/quant-web && pnpm build
find data -path '*tqsdk*' -o -path '*trader*' -o -path '*Future*'
```

## 本轮测试结果

- `git status --short`：有本轮 DATA-001 修改和大量旧 TqSdk tracked data 删除。
- `git branch --show-current`：`codex/data-001-rqdata-slimdown`。
- 删除前体积记录：`data/raw/tqsdk` 817M；`data/raw/trader_Future_data` 1.0G；`data/parquet/canonical/bars/provider=tqsdk` 711M；`data/parquet/canonical/bars/provider=trader_future_data` 2.4M；`data/parquet/market/provider=trader_future_data` 433M；`data/tmp/tqsdk_downloads` 1.5G。
- `uv run --project services/quant-api ruff check .`：passed。
- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_data_sources.py services/quant-api/tests/test_market_data_reader.py services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_data_center_api.py services/quant-api/tests/test_backtest_task_api.py services/quant-api/tests/test_backtest_service_runner.py services/quant-api/tests/test_backtest_vnpy_schema.py services/quant-api/tests/test_signal_scanner_api.py`：35 passed。
- `uv run --project services/quant-api pytest -q`：183 passed。
- `cd apps/quant-web && pnpm build`：passed；Vite 仍提示既有 `BaseChart` chunk 超 500 kB。
- `find data -path '*tqsdk*' -o -path '*trader*' -o -path '*Future*'`：无输出。

## 完成后输出要求

```markdown
## 本轮目标
## 修改摘要
## 变更文件
## 删除数据
## 当前项目状态摘要
## 运行命令
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
## 是否建议更新 PROJECT_SNAPSHOT.md / CURRENT_STATE.md
```
