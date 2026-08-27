# 归一量化工作站

本地优先、单用户的国内期货研究工作站。行情事实链为 RQData → Canonical Parquet → 八表 Catalog + MainContractMap → MarketDataService；Web、指标、研究和 Alert 都在该边界内工作。

## 快速导航

- [当前状态](STATUS.md)：release、Runtime、evidence 与 pending Gate。
- [稳定产品边界](PROJECT_SOURCE.md)：SuBing、HTDY、Alert 与研究边界。
- [工程规则](AGENTS.md) 与 [验证命令](TESTING.md)。
- [系统架构](docs/ARCHITECTURE.md) 与 [数据合同](docs/DATA_CENTER.md)。

## 当前产品面

SuBing 是一个由 Daily Context、Current Signal State、Formal Event 组成的产品工作区。HTDY 支持 operational universe 的七个正式周期及 symbol × frequency Scope。主图选择仅为：无、苏冰、火天大有。SuBing Candidate Validation 是内部研究；RQAlpha 与 Execution Review 已退役。

## 本地开发

```bash
uv sync --project services/quant-api --locked
uv run --project services/quant-api guiyi --help
pnpm --dir apps/quant-web install --frozen-lockfile
pnpm --dir apps/quant-web build
```

统一 CLI 的 Research 子命令为 `subing-calibration`、`subing-lifecycle`。真实数据、生产 DB、Runtime、Scope、通知与 release/tag 均需独立明确授权。
