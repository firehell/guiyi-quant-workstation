# 60 品种市场状态学习

## 最新状态：第二轮已结束，保留 v2

owner于2026-11-03明确决定“保留 v2，收束本轮研究”。第二轮24段600次逐根判断、原始导出、开发试验及固定配置增量比较全部保留。新增标签虽有局部改善，仍没有稳定胜过v2；本轮不再追加标注、训练、调参或候选晋升。日线支持不足，封存测试未开启，未训练新的人工标签TCN，也未切换因子、Alert或Runtime。以下阶段记录为历史过程，不构成继续执行授权。


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

## 第二轮：趋势延续与结束（2026-11-02重新交办）

第一轮闭环与结论保留；owner授权新一轮研究，v2仍为固定对照，不替换正式消费者。

1. 当前：4个已见开发片段逐根语义校准，EMA10/21/60均由同物理segment前缀预热；每段25个判断。选项为上涨/下跌延续、上涨/下跌警惕、已结束/无趋势、不确定。首个状态不推断之前转折。页面只隐藏未来，不构成服务端盲化。
2. 等待owner导出后，检查警惕、结束及恢复的边界；不把不确定强制分类。再按固定抽样规则选择未看过的开发片段，隔离既有复核窗口，验证语义稳定性。封存测试暂不开启。
3. 冻结新标签定义后，比较可解释规则、树模型与因果TCN，方向与健康度分别评价。保留第一轮时间/物理合约隔离、等权、配置预算和三种子约束。
4. 同时评价趋势碎片、错误退出、结束延迟和延迟期间ATR归一化反向运动；交易回撤需另行定义执行规则，不由状态直接推算。冻结候选后才做未见比较、页面对照和完成Bar观察。

当前交付：`scripts/research/regime_trend_review.py`及同名HTML；本地包`output/regime-trend-lifecycle-20261102`。
输入复用已核验开发快照，源hash及卡片逐值核对；不下载、不改Canonical。答案身份独立，保留原答案；导出不自动授权训练。当前停在owner语义复核。

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

### 第二轮语义澄清（2026-11-03）

owner确认：上涨警惕=上涨已经成立，但存在走弱或失败风险；不是上涨尚未确认。原100个判断保留，不重标。答案归档于`output/regime-trend-owner-20261103-eb733ddf`。下一批固定CF/SA 30m、CU/M 60m、RB/A日线，共6段；开发区按固定哈希选择，与此前114个显示窗口不重叠，不使用模型输出筛样，不作为封存测试。待owner完成新片段语义验证后才讨论标签映射和训练。

AG日线未找到满足64根全主力归属、均线预热与旧卡片排除要求的窗口，生成停止且未输出；只调整抽样品种为A日线，不放宽质量要求。

### 第二轮逐根归因（2026-11-03）

`regime_lifecycle_diagnose.py`重放物理segment前缀，对照两批250个开发判断。输入hash、卡片OHLC及全扫描v2(2,3)一致性断言通过。9组有界确认/中性退出配置及3组EMA60方向保持诊断规则不构成晋升候选。v2一致179/250；(1,3)为188/250但错误保留由19增至22；慢线保持174/250，错误保留33。均为已见相关片段，不能当作OOS或交易结果。

豆粕21个上涨判断中，v2为20个震荡、1个下跌；4个无趋势判断一致。第61根owner判结束时EMA10>EMA21>EMA60仍成立，需确认持续盘整与结构失效的退出语义，不擅自推导阈值。对照页`output/regime-lifecycle-diagnosis-20261103/index.html`分别截至48/60/61根，不展示各自未来。暂停依赖该语义的标签与训练，等待owner说明；v2及Runtime不变。

owner随后确认豆粕第61根结束依据为“连续盘整已足够久，上涨不再推进”。这允许均线多头排列仍在时结束方向状态；不要求先破均线/结构。具体持续根数、推进幅度和波动归一化阈值未指定，不能从该单例认定所有横盘都应结束。下一项为停滞退出的有界开发诊断，需同时检查原有CF/SA趋势中整理和AG盘整案例，不覆盖原答案、不将新试验当OOS。

### 标签覆盖检查与补充批次（2026-11-03）

暂停继续针对250个已见判断调参：60m缺少down_continue，down_warning仅1条路径；日线上涨两种状态均只有EC单路径。`output/regime-lifecycle-diagnosis-20261103/label-support.json`保留按周期/状态的Bar与独立路径计数。当前数据不能支持每周期五状态的稳定训练/留出验证。

下一批`output/regime-trend-support-20261103-final`共8段：I/P30m，CF/SA/RB/A60m，M/Y日线。CF/SA60m只用最初可见第40根及更早EMA筛下跌背景，不使用未来判断或owner标签；不保证owner会标下跌。其余固定品种、哈希选窗。排除原90+24及两批逐根卡片的全部显示窗口，全部在开发区；该批为有偏的标签覆盖补充，不是封存测试。生成命令：`PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python scripts/research/regime_trend_fresh.py --batch support --output <new-directory>`。

已检查8卡长度/均线完整性、旧窗口不重叠、测试截止日隔离、CF/SA初始筛选、200个答案结构和动态分页；JavaScript语法与diff检查通过。早期临时包`regime-trend-support-20261103`未向owner展示，不接收其答案；使用final包身份。当前等待owner完成8段复核。尚无新模型训练、候选晋升或Runtime变化。

### 补充8段已导入（2026-11-03）

owner导出身份校验通过，8/8段200/200判断，归档`output/regime-trend-support-owner-20261103-fd5b06cf`，summary包含逐段切换及三批联合覆盖。累计18段450判断：30m6段、60m7段、日线5段。60m下跌延续新增33个判断、3条路径，覆盖缺口已补；日线上涨延续仍仅EC的7个判断、1条路径，不能声称完成支持。

CF60m虽在初始下行均线背景筛选，owner25次均判无趋势；Y日线同为25次无趋势，保留为反例，不改标签迎合覆盖。当前不继续机械追加刷题；可先做分钟周期的小样本探索，严格以整段/品种隔离，不能随机拆Bar或声称未见/OOS。五状态标签稀疏，神经网络效果仍未证实。日线上涨结束/延续泛化证据不足，候选晋升保持关闭。

### 分钟周期人工标签先导实验（2026-11-03）

`regime_owner_pilot.py`准备13个分钟片段325个标签，按同周期完整卡片的时间顺序扩展：训练片段结束必须严格早于验证片段首根输入，训练中缺少三类方向或少于2个片段时跳过。6段不满足，7段可评估。方向用固定逻辑回归/梯度提升树各一配置(seed17)，警惕另用二分类逻辑回归；预处理只fit训练、品种等权，无品种身份/绝对价格特征。隔离环境串行CPU2线程，不装服务环境。

开发对照结果：30m可评2段50判断，v2一致28，逻辑回归12，树12；60m可评5段125判断，v2一致105，逻辑回归69，树82。树的错误保留趋势分别7/28（v2为5/10）。没有入围模型，不运行三种子复验或神经网络。全部是已被研究观察的开发片段；时间隔离不能使其成为未见OOS。没有训练最终模型或切换因子。证据`output/regime-owner-pilot-20261103/{data,report}.json`，含hash、逐片段结果、缺失覆盖与固定配置。

数据身份、OHLC、前缀特征、未来扰动、价格缩放不变性、整窗严格时间边界、预测长度检查通过。下一批6段`output/regime-trend-plateau-20261103`针对整理边界，固定CF/SA/P30m和CF/SA/RB60m，初始可见14根ER<=0.3且输入始于2025-07-01之后，排除此前所有显示窗口；无未来答案筛选。该批是有偏开发补充，不用于总体准确率，等待owner复核。

### 整理边界批次已导入（2026-11-03）

6段150次判断全部完成，身份校验通过，原答案归档`output/regime-trend-plateau-owner-20261103-f9616891`。新增85次有方向（其中49次警惕）、65次无趋势；累计24段600次相关判断。CF30m警惕后恢复下跌延续，P30m警惕后结束，CF60m从无趋势到上涨警惕再延续；SA60m仅1根下跌警惕，其余无趋势，RB60m短暂上涨警惕后结束。保留全部转换，不做多数平滑或强制改标签。

本批针对低效率初始背景抽样，不能代表全市场类别比例或宣称未见OOS。尚未并入训练；下一项优先固定已有实验配置，检查补充前后按时间完整片段验证，不根据本批答案反复调参或马上再刷题。v2不变。

### 固定配置标签增量比较（2026-11-03）

使用同一19个分钟卡片475个标签，控制组只允许旧批训练，增量组允许时间更早的plateau卡片；两组验证卡、时间隔离及模型配置相同。13段可评（30m5段125判断、60m8段200判断），6段训练支持不足跳过。原实验控制预测逐值复现。

30m一致数：v2 87，逻辑回归62→76，树66→78；60m：v2 162，逻辑回归120→127，树139→144。按品种等权三类宏F1：30m v2 .44293，逻辑回归 .33158→.38298，树 .33183→.34757；60m v2 .56622，逻辑回归 .41356→.43701，树 .47429→.51159。这里仍是开发卡片上的统计，非封存测试或显著改善。错误保留趋势：30m v2 5、增量逻辑16/树7；60m v2 24、增量逻辑56/树27。没有达到替换基线依据，不入围三种子/最终模型或页面切换。

复算脚本`regime_owner_increment_report.py`；产物`output/regime-owner-increment-20261103/{control,augmented,comparison.json}`。准备命令使用`regime_owner_pilot.py prepare --include-plateau`，control train追加`--exclude-plateau-training`，augmented train不追加；同一data.json。串行CPU2线程、原隔离环境；报告保留脚本及输入hash。独立Review核验相同数据/跳过集合、唯一训练差异、严格整窗时间隔离、训练内标准化、控制预测复现及结果重算通过。

收束前判断：新增标签在本次开发对照有改善，但仍不及v2；不能据此断言神经网络无效，本轮人工标签尚未训练新TCN。不再自动追加题目或根据这批结果继续扫参。等待owner决定继续扩大人工标签学习研究，还是保留v2并收束这一轮；在owner决定前不把研究标为结束，现役因子不变。
