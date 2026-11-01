# 火天大有优化研究复算入口

仅离线研究；价格/信号原件不修改，费用和执行身份继承2026-10-31 PTA研究。Features为已完成60m的逐步事实，TA/MA每owner输入proof必须匹配原冻结捕获；`original`信号不由此重算。牛哇对照是历史逐步重建而非真实前向Event。

根目录执行，数据/回放worker必须串行：

```sh
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python output/htdy-ta-60m-70pct-20261031/supervise.py --name features-NEW services/quant-api/.venv/bin/python output/htdy-optimization-20261031/features.py TA
services/quant-api/.venv/bin/python output/htdy-optimization-20261031/matrix.py TA
services/quant-api/.venv/bin/python output/htdy-optimization-20261031/matrix.py MA output/htdy-optimization-20261031/ma_data
services/quant-api/.venv/bin/python output/htdy-optimization-20261031/summarize.py
services/quant-api/.venv/bin/python output/htdy-optimization-20261031/compare.py
services/quant-api/.venv/bin/python -m pytest -q output/htdy-optimization-20261031/test_experiment.py output/htdy-optimization-20261031/test_review.py
```

Features已有输出会拒绝覆盖；矩阵跳过已有完整目录，单run拒绝已有目录或SQLite检查点，禁止无意追加或自动续跑。要复算请在新研究目录运行并保留旧结果。`matrix.py`只运行固定20情景/品种，不执行组合筛选；`compare.py`固定gate，任何组合须先满足两档滑点条件。

ATR用同owner TR20简单平均，入场Fill前最新可知值冻结；后续60m收盘穿线才建平仓意图。风险或震荡退出后，必须等相反HTDY方向才能解锁；同Bar不新开，跨物理合约不继承方向锁。趋势BLUE是核心趋势带方向，不把空仓解释为做空。趋势过滤只拒绝新开，反向退出仍执行。

牛哇双融合同时CLEAR/BUILD：先平旧，再在原Bar后180秒以内按原执行规则尝试新建，超时取消本次重建机会；不让参考价当成交价。此规则是研究执行适配，不改变公开页面同Bar参考算术。

大行情、曲线SQLite及逐笔结果只保存在研究output；提交精确研究脚本和测试，不提交凭据或原件数据。
