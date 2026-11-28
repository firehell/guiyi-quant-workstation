# 统计与 AI 研究中心隔离验证

验证对象为 Apple Silicon 上的 CPython 3.13.9。独立环境锁定 QuantStats 0.0.81、VeighNa 4.5.0、Polars 2.2.0 和 Statsmodels 0.15.0。VeighNa Alpha 的数据集入口会导入 Statsmodels，验证环境显式安装它。应用 API 与行情进程继续使用各自的依赖环境。

## 复验

从仓库根目录运行。将 `research_release_store` 指向回测中心 `backtest-center/v0.1.0` 对应的本地已验收存档库。以下两个变量都指向本机研究用路径。

```sh
export research_validation_dir=/private/tmp/guiyi-stat-research-01
mkdir -p "$research_validation_dir"
UV_PROJECT_ENVIRONMENT="$research_validation_dir/locked" \
  uv sync --locked --project services/research-worker

PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -B scripts/research/export_research_backtest.py \
  "$research_release_store" a39fae9c070d46188f0abdf55358c75f \
  > "$research_validation_dir/fu2603-publication.json"

MPLCONFIGDIR="$research_validation_dir/mpl" \
  "$research_validation_dir/locked/bin/python" -B services/research-worker/verify_settlement.py \
  "$research_validation_dir/fu2603-publication.json" \
  --expected-publication-sha256 f6f7e5ee866a83f6c9d850191aacbb5b6b5ff48b15df39f84813fec524bff456

PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -B scripts/research/verify_research_feature_source.py \
  output/regime-learning-20261102-final/fu-60m.jsonl.gz fu FU2603 2025-12-22 2026-01-23

POLARS_MAX_THREADS=2 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  "$research_validation_dir/locked/bin/python" -B services/research-worker/verify_alpha.py \
  output/regime-learning-20261102-final/fu-60m.jsonl.gz \
  --contract FU2603 --since 2025-12-22 --through 2026-01-23

POLARS_MAX_THREADS=2 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  "$research_validation_dir/locked/bin/python" -B services/research-worker/benchmark_alpha.py \
  data/universe/operational_products.txt output/regime-learning-20261102-final \
  --since 2026-10-12 --through 2026-10-30
```

## 2026-11-28 实测

回测存档来自 Backtest Center `87dad0899a58e5af951366af77a4d8173c952881`，Run 为 `a39fae9c070d46188f0abdf55358c75f`，物理合约 FU2603，RQAlpha Plus 4.5.0，资格为 TRIAL。14 个评价交易日为 2026-01-06 至 2026-01-23。原生摘要使用 23 个交易日，包含 9 个权益恒定的预热日。以固定期初资金 CNY 100,000、外部现金流 0、年化 252 交易日复算。14 天逐日权益与原生结算最大绝对差为 CNY 0.00000000007。

| 指标 | Plus 原生摘要（23 日） | 手算／QuantStats（23 日） | 手算／QuantStats（14 日） |
| --- | ---: | ---: | ---: |
| 最终日结权益（CNY） | 100,520.3375 | 100,520.3375 | 100,520.3375 |
| 累计净收益 | 0.5203375% | 0.5203375% | 0.5203375% |
| 2026 年 1 月净收益 | — | 0.5203375% | 0.5203375% |
| 最大回撤幅度 | 0.8309157% | 0.8309157% | 0.8309157% |
| 最大回撤段持续交易日 | — | 6，未恢复 | 6，未恢复 |
| 复合年化收益 | 5.8510868% | 5.8510868% | 9.7920478% |
| Sharpe（无风险利率 0） | — | 1.002513 | 1.267748 |
| Sortino（无风险利率 0） | — | 1.765573 | 2.263005 |
| Calmar | — | 7.041733 | 11.784646 |
| 日胜率 | — | 30.434783% | 50.000000% |

逐笔 78 笔已平、26 笔盈利，逐笔胜率 33.333333%。唯一未平仓的结算浮亏为 CNY 210，开仓费用 CNY 1.317，二者计入期末权益。回撤持续期使用交易日索引，日胜率含零收益日的分母。破损摘要、缺日、现金流未知、不可识别的收益输入均会拒绝。对于没有原生摘要字段的指标，以独立手算和 QuantStats 对照为验收依据。

同一物理合约在 2025-12-22 至 2026-01-23 的 159 根已完成 60m Bar，与当前 MDS 逐根核对 OHLC 和交易日一致。VeighNa Alpha 的 `AlphaDataset.add_feature(result=...)` 原值接收三个已有特征，`set_label` 分别接收 159 条原行情状态标签和 90 条外建观察标签。后者取同一交易日内第 1 根未来完成 Bar Close 到第 3 根 Close 的变动。推断表只投影特征白名单，`ts_delay` 逐段核对。此处只验证数据接口，默认因子报告的 `1D` 和全样本过滤未接入。

57 品种选用 2026-10-12 至 2026-10-30 的冻结窗口，共 6,045 条有效样本，多次输入指纹一致，无失败成员。常规两次运行耗时 25.0 和 26.7 秒，主进程及子进程各自峰值 RSS 均约 187–192 MiB。任务使用单个 Alpha 子进程、两个 Polars 线程和单线程 BLAS。

每组 8 次同窗口只读 MDS 查询，批量任务并行时中位数从 35.37 ms 升至 44.96 ms。样本只测单机历史读面。正式工作站 API 当时未运行，因此盘中行情、模拟与工作台并行性能仍需验收。
