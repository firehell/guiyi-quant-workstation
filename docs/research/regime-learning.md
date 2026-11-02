# 60 品种市场状态学习

目标：日线、30m、60m在完成Bar收盘时识别上涨／下跌／震荡。固定`subing_dynamic_range_v2`为基线；
不同周期独立分类。研究结果不自动晋升现役策略、Alert、Runtime或交易。

## 当前交付边界

已完成数据准备、114份静态复核和4段100个逐根判断，并完成**开发区模型训练比较**：
9组v2参数；逻辑回归/梯度提升树/TCN各1配置、三周期三折；分钟TCN三种子和三个板块留出。
**本轮研究已结束（owner于2026-11-02确认保留v2）。** 研究结论仍为改善证据不足，弱参考拟合改善不能冒充人工判断准确率改善。
不继续训练、调参或新增人工标注；原复核、模型权重和报告保留。
封存测试、最终全开发训练、候选看盘与Live观察尚未进入；没有切换active因子或Runtime。
完整结果与限制见`output/regime-model-development-20261102/report.md`。

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

## 人工标签校准（2026-11-02）

判断目标是当前周期最后一根完成Bar的状态，不是下一段涨跌概率。owner确认：

- 短暂横盘先保留趋势，直到结构失效或持续盘整得到确认。
- 棉花/纯碱沿均线持续推进，支撑原方向的高低点结构没有破坏，仍为上涨/下跌。
- 白银即使可能继续上涨，右侧连续横向整理、缺少方向推进时也可以是震荡。
- “没达到趋势阈值”不等于震荡；信息不足保持不确定，不强制归入三类。

这些是人工复核口径，尚不是已验证的数值阈值。均线仅辅助人工识别；不把EMA21方向或v2输出作为
新的监督真值。原 `price_path_20_40_v1` 保持独立弱参考，原90份人工答案及备注保留，不代替owner改标签。
后续需说明均线辅助可能带来的标注偏好，不能把与v2同源的一致性当作独立准确率。

开发诊断（同一90份，均非OOS；12份人工不确定单列）：

| 规则 | 一致 | 明确冲突 | 自动未决 | 人工不确定 |
|---|---:|---:|---:|---:|
| 原20/40价格路径参考 | 55 | 5 | 18 | 12 |
| 短窗试验 | 46 | 17 | 15 | 12 |
| 结构保持候选v2 | 40 | 26 | 12 | 12 |

后两者淘汰，不能扩标或训练。条件覆盖不同，不用上述计数直接宣传准确率；显示中的因子v2不是表内结构候选v2。
`regime_structural_labels.py` 和 `regime_label_diagnosis.py` 仅保留可复算失败实验，不接入应用。
原结构候选v1有直接反转缺陷，其结果不作为有效比较。

下一轮用 `regime_calibration.py` 从固定输入快照抽取24张新开发片段，每周期8张，按原弱参考四类各2张。
哈希抽样并分散品种/板块；排除原90张及本轮相互重叠的同品种日历窗口（跨周期也排除）。
按开发分区、同物理segment的64根窗口抽取，不使用封存区计算或评价。
共享EMA21从完整物理前缀预热，仅作为人工视觉辅助；页面隐藏参考分类、v2状态、未来K线。
抽样是语义校准而非总体准确率估计，也不替代未来封存测试。新复核身份和浏览器保存键与原90份分开。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_calibration.py --dataset output/regime-learning-20261102-final --output output/regime-calibration-20261102-final
python3 scripts/research/regime_review.py serve --directory output/regime-calibration-20261102-final --port 5177
python3 scripts/research/regime_review.py summarize --directory output/regime-calibration-20261102-final --answers /absolute/path/new-review.json --output output/new-review-summary.json
```

完成条件：新片段人工复核后，对明确的分歧有可解释处理，自动标签规则另行版本化并完成因果性验证。
本轮尚未得到可用于大规模训练的标签规则；不凭自动规则与自身标签一致来完成此Gate，不根据封存测试调参。

### 两轮复核后的固定规则试验

第二轮24/24已导入，人工7上涨/6下跌/11震荡；原参考明确18份全部一致，6份未决为5震荡/1上涨。
两轮共114份（12人工不确定），原参考73一致/5冲突/24未决，仍非OOS。

`regime_path_candidate.py` 的 `path_progress_plateau_v1` 固定试验保留20/40弱参考，
新增12根范围重叠与低位移的连续3根盘整确认，以及仅在DISPUTED时使用8/20同向连续2根确认。
`regime_path_experiment.py` 在计算前记录协议、回答与依赖hash，验证两轮各自及合并计数，使用同物理前缀。

实跑只改善原90中的1张BU日线（合计74/5/23），新增24无改善，114个端点没有触发盘整分支。
抽样主力开发前缀20264根含未决的切换次数2132→2736（+28.33%），不是全市场误切换率。
逐轮计数不劣的初筛通过不代表规则成立；结论为改善证据不足，不用于扩标、训练或active替换。
报告：`output/regime-path-experiment-20261102-final/report.md`；当前无需新增人工复核。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_path_experiment.py --output output/regime-path-experiment-new-run
```

### 盘整消融与时点信息缺口

`path_progress_plateau_ablation_v2` 预先固定4组：原候选、去重叠条件、所有标签切换3根确认、二者结合。
114卡一致/冲突/未决依次74/5/23、72/8/22、58/6/38、62/7/33；另12人工不确定。
同20264根前缀切换2736、3387、1437、1608，参考2132。后三组均未通过逐轮计数不劣条件。
确认层对初次确认及所有进入/退出生效，不能仅描述为退出防抖。四组是已见开发消融，非四份OOS验证。

停止在端点标签上继续调参：现有114回答未记录“从哪根开始盘整已确认”，缺少确认延迟的人工口径。
`regime_boundary_review.py/.html` 从同快照构建4个已有AG/RB/SS/EC分歧，完整物理EMA预热，
从40根开始逐根记录25个趋势/震荡/不确定状态，直到64根，允许多次转换；第40根状态按左截断处理。
AG实图在40根已震荡、后有趋势再震荡，故首次range即停止不能定位末端边界。独立身份不改原回答。
页面明确已见开发而非独立测试，答案不能自动扩标或训练。时点记录至多说明本次逐根复核的状态轨迹，
不能冒充未见场景实时能力。导出验证用该模块的validate，不能用普通分类复核的summarize。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_boundary_review.py --output output/regime-boundary-review-new-run
python3 scripts/research/regime_review.py serve --directory output/regime-boundary-review-20261102-final --port 5178
```

证据：`output/regime-path-ablation-20261102/report.md`。状态为等待owner补时点信息，训练未开始。

## 开发区学习实验入口

研究依赖单独安装在`output/regime-ml-env`，不修改正式服务环境；锁定版本见实验目录requirements.lock。
`regime_ml_data.py`只导出开发区，三周期原始输入快照与归属合同不变；同segment64根、统一日期purge。
`regime_ml_core.py`统一划分与品种等权指标，延迟配对不跨segment，漏识别单列。
`regime_ml_train.py`保存当折权重与预处理；`regime_ml_manual.py`只允许严格匹配当折validation indices的人工配对。
`regime_rule_variants.py`使用共享direction_transition做有界参数对照，默认值必须与存档v2逐值相等。
`regime_ml_sector.py`测试农业/化工/有色三个留出；`regime_ml_uncertainty.py`做共同月份块与品种配对重采样。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_ml_data.py --dataset output/regime-learning-20261102-final --output output/regime-ml-data-new
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. output/regime-ml-env/bin/python scripts/research/regime_ml_train.py --cache output/regime-ml-data-new --output output/regime-ml-train-new --seed 17
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. output/regime-ml-env/bin/python -m unittest tests.unit.subing_range.test_ml -v
```

本轮共45次拟合，不能称45组配置。标签仍为独立弱参考，人工只作分条件开发诊断，不替模型补造方向。
三个种子在同36个分钟级逐根点一致数32/34/34，v2为33；不是稳定人工改善，也不是独立测试。
owner已决定保留v2并结束本轮；不继续扩大人工时序标注，不消耗sealed test或晋升候选。
