# 甲醇长期执行数据研究补缺

本任务只修改新的研究副本；未写Canonical、Catalog、生产数据库、Runtime或账户。

## 已完成事实

- 原MA执行SQLite复制到 `MA/evidence/execution.sqlite`；原件SHA256为 `fdb845dc7658e1263265984f95bd6533394080a6ca1ad6d58dc4e852087ca140`，独立检查原件保持，原316005行已有报价逐字段及source保持。
- 13个精确旧合约交易日共4365根1m已补齐，其中MA2610/2026-09-28为225根，其他12日各345根。每个交易日先fresh只读MDS，均返回明确DATASET_OR_PARTITION_MISSING后才进行一次RQData查询。
- 每个raw parquet SHA、合约、全部Calendar/Session精确端点、OHLCV合法性以及原件与SQLite逐数值相等已核验；remaining_gap_days=0、missing_expected_minutes=0。
- 独立扫描发现原MA2611整个参数项缺失，即使原execution-errors=[]。已补该合约规格及2026-09-28至2026-10-19共11交易日的fee/双向margin/结算/涨跌停，4次业务查询；原missing-before与各类raw原件保留。旧facts已有内容不覆盖。
- 全14个spans的required字段一次扫描另发现MA2701/2026-10-26的commission_type、open_commission、close_commission、close_commission_today四项原为None，已在TA矩阵结束后的串行空档单次读回并仅补这四项，原None行与raw读回均保留。最终全14spans所有required字段非空、有限和数值边界全部通过。

## 资源与失败记录

数据worker严格串行，384MiB警戒、512MiB终止；当前实际峰值422346752 bytes，约402.78MiB，未触终止。13次分钟价格业务请求，MA2611参数4次业务请求，MA2701精确单日费用1次业务请求；每个SDK进程还查询quota并可能含初始化流量。实际quota起点约535.6MB，末次分钟报价请求前499.5MB，不把1.12MB行数据估计当作SDK总额度消耗；每次请求保留128MiB。

首次MA2305默认沙箱只读数据库连接失败，api_calls_for_prices=0、没有request_started。失败日志原样保留，宿主批准后使用独立attempt2成功；不是重发未知provider请求。MA2611参数首次因PYTHONPATH缺根目录在导入阶段失败，尚未创建attempt或连接SDK；修正后独立监控日志保留并成功。

## 验证入口

```sh
python -m unittest discover -s output/htdy-optimization-20261031/ma_data -p test_prepare.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 services/quant-api/.venv/bin/python output/htdy-optimization-20261031/ma_data/supervise.py --name verify-MA-final services/quant-api/.venv/bin/python output/htdy-optimization-20261031/ma_data/verify.py --raw
```

`test_prepare.py` 已实际运行，3 tests OK。最终 `verify.py --raw` 已实际通过：13日4365根raw SHA/端点/OHLCV/SQLite逐值一致，14spans全部required字段非空且有限，日期齐备，原件SHA及原316005行全部保持。最终raw核验worker137379840 bytes（约131.02MiB），exit0。读取parquet时宿主禁止sysctl缓存探测产生Arrow警告，但实际核验完成，不影响数据读取。

最终数据状态：完整研究执行事实已准备，交回研究引擎执行全窗口MA基线与固定候选；数据补缺完成不等于回放完成或策略通过。
