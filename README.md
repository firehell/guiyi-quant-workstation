# 归一量化工作站

本地、单用户的国内期货量化研究工作站：治理数据、查看 K 线、研究策略、回测与复盘、观察信号。它不提供无人值守自动实盘或自动下单。

## 快速导航

| 用途 | 文件 |
|---|---|
| 工程执行规则 | `AGENTS.md` |
| 当前状态与未关闭 Gate | `STATUS.md` |
| 项目定位与边界 | `PROJECT_SOURCE.md` |
| 长期决策 | `DECISIONS.md` |
| 测试入口 | `TESTING.md` |
| 数据、架构、回测、信号、指标 | `docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/INDICATOR_KERNEL.md` |

接手时先读 `AGENTS.md` 和 `STATUS.md`，再按任务读取对应 deep canonical 或受控任务合同。

## 主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

正式 active 数据仅限 `rqdata/local_parquet + primary + quality_status != failed`；严格研究默认 `quality_status=passed`。

## 本地启动

```bash
cp .env.example .env
./scripts/dev-up.sh
```

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000/docs
```

## 安全边界

- 密钥只存在于本机环境；禁止写入仓库。`scripts/engineering/check-secrets.sh` 默认 fail-closed。
- 不自动 push、merge、deploy 或下单。
- 真实数据、数据库、Runtime 或企业微信写入必须通过业务专用、hash-bound、scope-bound Gate；Issue 不能代替代码层验证。
- 信号和企业微信仅供研究观察，不是交易指令，也不自动下单。
