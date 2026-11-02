# 60 品种市场状态学习

目标：日线、30m、60m在完成Bar收盘时识别上涨／下跌／震荡。固定`subing_dynamic_range_v2`为基线；
不同周期独立分类。研究结果不自动晋升现役策略、Alert、Runtime或交易。

## 当前交付边界

已实现第一阶段数据准备、独立参考标签、90个盲审片段及复核导入工具。**训练尚未启动**，标签尚未经owner复核。
后续逻辑回归、梯度提升树、TCN、三随机种子复验、板块留出、模型评价与候选页面/实时接入均须继续实施；
不可把本阶段参考标签或v2输出说成学习模型的结果。

60m已接入同一共享v2算法及自由看盘只读API；日线、30m参数与算法不变。这是新增周期支持，不是模型训练升级。

## 数据合同

- 固定`operational_products.txt`的60品种，按`product_sectors.csv`记录板块。
- 审计请求从`max(active_history_floor, product_window_start)`至显式`--through`，不取现存mapping最小最大值来缩短请求。
  更早的同物理合约历史仅用于完整生命周期预热，不作为无主力映射的可训练主力样本。
- 只读事务与Catalog/MDS权威入口；逐owner、逐周期核验物理来源hash、Session端点逐项相等、coverage、主力归属。
  文件元数据有记录不等于实际读取成功。缺口不修复、不下载、不拼接其他合约或跨频替代。
- 片段读完、逐根计算完并成功序列化后才写入研究文件、合并盲审样本池；中途失败的片段无可用残留。
- 各品种结束复查来源与映射；记录每个片段证据和本地导出hash。启动即固定代码hash，结束不一致则不生成最终包。
- `coverage.json`保留180路状态及失败片段。`VERIFIED`仅指该请求窗口的数据核验，不证明分类准确率。
  PARTIAL/UNAVAILABLE不伪装完整；导出按物理segment隔离，后续训练不得跨缺口拼接64根序列。

## 标签和盲审

`price_path_20_40_v1`使用截至当时的20/40根原始close OLS：两窗口回归斜率和净位移同向，
各自R²≥0.4、abs(净位移)/当根共享ATR14≥2，才标上涨或下跌；两窗口R²≤0.2标震荡；其余DISPUTED。
少于40根、ATR不可用或非法价格为UNKNOWN。常价窗口R²记0。标签独立于EMA方向、ER及v2状态，属于参考标准。

按全体权威交易日统一封存末20%。开发区前80%划分3折扩展验证；64根输入序列必须全部属于同一分区。
JM 2026-07-13至2026-10-30为已见案例，相关输入窗口标CASE_REGRESSION，不能计入未见测试或盲审候选。
不足64根标INELIGIBLE，跨开发/测试边界标PURGED_BOUNDARY。

每周期30片段：8上涨、8下跌、7震荡、7争议。哈希确定性抽样，优先板块/品种分散，
同周期同品种最多3个，样本窗口不重叠。不足配额明确报告，不放宽到封存区凑数。
浏览器只包含64根OHLC、身份与时点，隐藏reference/baseline/features/未来数据；独立review-key用于导入核对。
人工可选择不确定、添加说明并导出部分复核；导入报告不自动冻结标签或允许训练。

## 运行

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_learning.py --through 2026-10-30 --output output/regime-learning-run
python3 scripts/research/regime_review.py serve --directory output/regime-learning-run --port 5176
python3 scripts/research/regime_review.py summarize --directory output/regime-learning-run --answers /absolute/path/review.json --output output/review-summary.json
```

输出目录必须新建；只对最终`WAIT_LABEL_REVIEW`或`REVIEW_SAMPLES_INSUFFICIENT`状态提供盲审。
本地服务仅监听127.0.0.1且仅返回盲审HTML，不暴露来源快照、参考答案或训练行文件。
复核绑定dataset_id、label_version和sample_id，不接受其他数据包的答案；输出不覆盖既有复核。
停机或异常期间的AUDITING/ABORTED输出不可训练，不是最终数据快照。

## 验证

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/subing_range tests/unit/subing_trend services/quant-api/tests/test_dynamic_range.py
```

覆盖因果标签、未来扰动、三周期同算法、样本盲化/配额/测试隔离、已见案例排除、段失败隔离、
映射末端缺失、代码漂移、部分人工复核和身份拒绝。现有前缀、逐根和重启测试继续适用。
实图可用性和真实数据覆盖另以本次运行结果核对，不用fixture代替。
