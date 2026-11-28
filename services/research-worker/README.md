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

## 工作台部署与回查

工作站安装同一组件提交的 API 与 Web 后，使用 `/research/statistics`。应用部署时使用对应 Alembic revision `20261128_0058`，为研究进程执行上方锁定安装命令。源码运行默认从 `services/research-worker` 找到脚本和锁。安装 wheel 的部署可将 `GUIYI_RESEARCH_WORKER_ROOT` 和 `GUIYI_RESEARCH_WORKER_PYTHON` 指向同一受验的 worker 目录与环境。样本 Parquet 默认保存在 `~/.local/state/guiyi/statistics-research`，可由 `GUIYI_RESEARCH_ARTIFACT_ROOT` 指定本地研究目录。PostgreSQL 索引与样本文件须一起备份。

从工作台选择已发布 Run 后运行分析。点击月份定位日结算，点击方向与时段单元定位闭合交易，原始 Run 链接进入原逐笔回放。跨 Run 对照分别列出样本和收益，差异字段标明不可比原因。因子与事件使用显式物理合约窗口、已完成 Bar 和研究用价格标签。带有确认条件的样本显示确认后才可知的时点。由已发布结果重跑时，先验证原 Parquet 和输入摘要，再用留存样本复算。

一次计算最多 30 秒，输入上限 8 MiB，同一工作台只接纳一个运行中的计算任务。取消请求保留占用直至工作进程退出。异常退出后，过期任务在只读接口显示失败，新任务受理时核对并清理该任务未提交的文件。已提交和已核验的结果保留原始身份。

## V0.2 高级研究

- 同步横截面接收 3 至 8 个不同品种的已发布因子结果。特征定义、周期、交易日、决策与标签时钟须一致。报告完整截面的 Rank IC 和固定相对秩分位收益，并列出缺成员、不一致和无秩差的排除项。因子并列共用平均秩。未来收益相同的截面仍计入分位收益。
- 事件稳健检验按最早确认锚点保留互不重叠的观察窗口，统计每个交易日的确认组与对照组均值差。HAC 区间和 p 值要求冻结日历中的有效样本日连续。月度 BH 校正以冻结窗口中的月份为检验族，缺项占位按 p=1 计入校正分母。
- Optuna 5.1.0 在固定种子与预算下生成 0–3 分钟的已注册执行延迟候选。用户按需提交给原 Backtest Center。每折先用训练结算排序，选定后才创建测试 Run。计划与源 Run、回测库、配置和快照摘要绑定，训练测试窗口先通过原生配置校验。模型训练以独立预测问题为前提。

隔离实测使用 FU2603、RB2605、RU2605 从 2025-12-22 至 2026-01-23 的已完成 5m 行情，形成 1,356 个有效 Rank IC 截面和 23 个日汇总。FU2603 的突破样本剔除 16 个重叠事件并保留 69 个。14 个有效配对交易日存在日历间断，HAC 区间返回缺项。两折真实 Plus 实验运行 4 个训练 Run 与 2 个测试 Run，全部成功。两折最后训练估值均为 15:30，先于预先固定的 17:00 选择截止。样本资格为 TRIAL。
