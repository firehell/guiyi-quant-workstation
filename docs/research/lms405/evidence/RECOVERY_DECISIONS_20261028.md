# 锁定后的恢复决策识别：第二轮

结论：**识别出若干局部必要条件和明确反例，仍不足以开发原版确定性恢复分支。** 不把条件集合当充分许可，不从缺后续记录输出HOLD。只读行情与本地研究交付，不改变原版信号公式、核心动作语义、active、Runtime或lms-inspired-v1。

## 四类决策及可排除解释

规则机器表沿用[rule-identification.csv](rule-identification.csv)新增R01–R08，补decision_class、condition_relation、sufficiency和counter_source_ids；每条保留日期/版本、支持与反例、未知和实现位置。[本轮复读记录](recovery-source-review-20261028.csv)记录当前页检查范围，旧author-control批次不改。

|类别|已知局部条件/事实|条件关系与充分性|排除的解释|仍缺证据|
|---|---|---|---|---|
|继续锁定|F05无暇手动处理；F06人不在错过V+后等机会|人为等待为明确观察，非市场判据；充分性未知|未动作必然等于无信号；用延迟重写信号公式|手动处理究竟确认、下单或配置；连续账户状态|
|恢复原趋势|F07转强再解锁；SH17:24风险可控并跟随空头趋势至破坏|当次必要条件，未恢复转强/趋势/风控公式；充分性未知|触及节点必然解锁；不能解锁立即反手|原周期、Bar、区域有效性及人工处理、实际解锁腿|
|转向抓M|F09当次OI2609明确有M才可做空；F03当时SH2509不支持该环境连续抓M|当次配置许可与M为必要条件；保护信号不充分|发现反向保护信号自动等于获准抓M；2025配置覆盖2026|M确认、配置演进、持仓与时序；不能仅按点位替代|
|退出后回补|E41短线后惯性出现再回补的概念；F09半仓回补属于5.0|仅相关概念，4.0.5具体充分许可未知；空仓身份是研究接口约束|把平反腿解锁与退出后重新进入合并；移植5.0比例|已退出/空仓的完整事实、方向、惯性公式与版本|

F01称锁定后需要作者建立新分水岭，证明存在人工建模环节，不能证明所有解锁必须先重建。F10→F11是上午解锁后下午再锁的作者自述；F11未逐项指名，不能声称F10全部品种均再次锁定。F12明确FG/SA再次锁、解释短期反复锁解锁为盘整，未给“短期”阈值。以上是相关或必要条件，不是足以机械切换的总规则。

JM2609五月的顺序要分开：原空向趋势暂停→短线抓多向M→M失败/结束后的保护→恢复空向。这与F09菜油从原多向保护后转为空向抓M不是同一恢复目的。F08当前正文的方向措辞冲突保留，不用这段话制造精确订单路径。

## 烧碱连续记录与截图身份

- 27日10:13 WRozNbg3en原图现场放大：SH701多20/空20，开均1490.1/1720、持均1490.1/1554；多腿今仓水印遮挡，截图时间和账户未知。正文强调做好锁定。
- 10:18 WRozPmaK10明确4.0.5、日低1475后先锁。不能把“先锁”解释为恰在10:18首次锁定，因为10:13发布图已经双持，且截图本身并无拍摄时刻。
- 15:16 U03当前已编辑正文称烧碱锁定后解锁一批；图3现场放大仅列SH701空20、开均1720/持均1554，未列多仍是UNKNOWN，不填零。混合系统日志不能逐图强绑定同账户4.0.5。
- 17:24 WRoCCdf0i5说风险可控可解锁再博弈，跟随空头趋势；这是条件意向/事后说明，不是带时刻动作回执。
- 22:12 WRoEvasxQR现场原图又见SH701多20/空20，开均1492/1720、持均1492/1499。与早盘多腿1490.1不同，不能称一条多腿全天未变化。仍不能排除多次平开、重新锁定、账户/过滤差异或编辑换图。

这些图均为持仓表，不是带周期与OHLC时间轴的信号图。原样SH701保留，不仅凭缩写补成权威合约身份。实际动作时刻不明时留空；最多保存作者“27日日盘已解锁”的报告范围（当前文本自述，非已核实事件区间），不以10:18/15:16发布时间造动作边界。现有图片哈希仍只证明本地附件一致，不证明历史不可变。

28日15:22新增[WRoLeVhPQ1](../../lms-source-archive/02-持仓记录/2026-10-28/WRoLeVhPQ1.md)称4.0.5当日不能第一时间切换抓M，敞口下降；原因未知。它是28日事后材料，不能用于证明27日具体解锁触发。

## 价格差异重新核对

固定SH2701、交易日2026-10-26至27、1m，统一MDS物理窗口完整读取690根。同一read-only事务中调用已有`resolved_session_windows_for_trading_day`，夜盘由权威is_night标志分类；Bar按(start,end]唯一归属且trading_day一致。没有另造Session resolver或换合约/周期。JSON保存每个窗口与所有极值Bar结束时间：[scoped market](sh2701-scoped-market-20261028.json)。

|明确比较范围|Bar数|本地高 / 低|高点Bar结束（上海）|低点Bar结束（上海）|
|---|---:|---|---|---|
|2026-10-26 完整交易日|345|1593 / 1511|10-23 22:20|10-26 14:54,10-26 15:00|
|2026-10-26 权威夜盘|120|1593 / 1556|10-23 22:20|10-23 21:06,10-23 21:07|
|2026-10-26 权威日盘|225|1585 / 1511|10-26 09:03|10-26 14:54,10-26 15:00|
|2026-10-27 完整交易日|345|1524 / 1477|10-27 10:47|10-27 14:47|
|2026-10-27 权威夜盘|120|1516 / 1481|10-26 21:01|10-26 22:59|
|2026-10-27 权威日盘|225|1524 / 1477|10-27 10:47|10-27 14:47|
|2026-10-27 27日10:18前已完成Bar|195|1516 / 1478|10-26 21:01|10-27 09:14,10-27 09:15,10-27 09:16|

26日交易日夜盘正确锚定前一交易日23日晚，不是25日晚；27日夜盘是26日晚。27日发布分钟秒数未知，严格采用bar_end < 10:18，不含本分钟；本地10:15–10:30为休市，因此发布前末根是10:15。1m仅观察粒度，不是作者策略周期。

**1475差异未解释且不能逐值验收。** 作者在27日10:18自述日低1475；本地发布前完整交易日路径低1478，差+3；完整27日交易日低1477在14:47，差+2，而且该极值晚于帖子，不能拿来解释上午已知事实。夜盘低1481也不能补出1475。单纯把本地白天换成包含夜盘的交易日不能消除差异。作者图没有可辨认报价窗口/行情供应商/月份和信号Bar，不能确认其“日内”与本地是同一比较对象。

**1512差异仍为未解释的范围问题。** 26日17:33 WRotf7lKhl转述日低1512，既有引用链包含10:37前文，原转述数字具体截点未证明。完整26日和日盘低1511均在14:54/15:00。不能默认转述1512是收盘全日极值，也不能随意选更早窗口凑相等；夜盘低1556同样不能解释。保留-1历史对照，并注明比较对象尚未确认。

旧白天报告及指纹冻结不覆盖；本轮扩展窗口表达后也没有证实两源逐Bar一致。价格差异限制价格/信号验收，不阻断来源文字条件研究。不下载、不修改正式数据，不移动窗口拟合。

## 新案例与结果表达

[新casebook](recovery-condition-casebook-20261028.json)、[新结果](recovery-condition-results-20261028.json)沿用v0.1输入合同。`condition_roles`仅为结果解释元数据，完整区分AUTHOR_NECESSARY与RESEARCH_VALIDATION；不进入核心判定。允许AUTHOR_REPORTED_CONTEXT，但本轮不靠叙述当作已核实市场条件。旧casebook无此字段时输出保持原样。

- RU转强恢复多向、OI抓M空向、SH恢复空向、通用退出后回补共4项INDETERMINATE；未将缺条件自动变成HOLD。
- OI当次配置许可是来源局部明确事实，在研究阅读时间填true；M确认、信号与实际持仓仍未知，不让总括未知掩盖已知许可。
- 2025 SH2509连续抓M情景NOT_PERMITTED来自作者明确披露该环境配置不支持，**不是因未观察到动作而推导负例**；不评价预测是否正确，不覆盖2026版本。
- 继续锁定没有新增交易动作；F05/F06等待只进入观察/规则表。解锁腿不明时，全部单位动作仍标解释情景，数量1不是作者截图20手。通用回补示例的SH2701只是物理身份占位场景，来源不证明其方向/版本，version_405=null。E41惯性概念保存在source_context并标RELATED_CONCEPT_NOT_A_ROUTE_GATE，不进入必要条件路线。
- 合格信号样本0，作者匹配率null，fill/performance=null，executable=false。重放输入动作、拒绝配置反例或合成测试通过均不计为预测成功。

## 本轮查询边界与检查点

阶段1已复核SH五个连续节点及必要原图，阶段2依序复读F08、F07、F01/F09、F05/F06、F10–F12、F03，并补读E41。原批次13条控制材料中本轮指定的10条实际复读；F02/F04/F13没有虚称复读。

作者主页已检查可见最新时间流（含置顶重排），日期词2026.10.27返回U03/11:34午盘；“烧碱 解锁”可见U03和23日材料；“SH2701 恢复”暂无；“烧碱 锁定”显示28日15:22原帖及15:38/15:40引用入口。只读根详情15:22，后两条同内容转引未展开，未计新增来源。发现新详情1条，低于全轮30上限；重复访问不计新增。浏览器标签提示曾遮挡页面，Escape后正常恢复，不是网站受限。

相关指定入口和上述有限检索结束后收束；没有声称全网或所有翻页穷尽。F09“昨天”原节点不可变版本、F07转强的后续信号图、F10/F11逐账户腿链以及未读附图仍为明确未查/未恢复入口。300天全面归档未重启，主游标仍21/22日；28日后续独立补充，不改变原27日至1月1日的300天覆盖合同。

## 可复算命令

从仓库根运行，新输出路径必须不存在：

```sh
GUIYI_CANONICAL_DATA_ROOT=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:scripts/research \
services/quant-api/.venv/bin/python scripts/research/lms405_sh_oct_case.py \
 --env-file .env --output /tmp/lms405-recovery-market-new.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research:packages/quant-core \
services/quant-api/.venv/bin/python scripts/research/lms405_public_casebook.py \
 --casebook docs/research/lms405/evidence/recovery-condition-casebook-20261028.json \
 --output /tmp/lms405-recovery-conditions-new.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core:scripts/research \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/lms405
```

## 验证与交付

- LMS定向命令实际结果：**74 passed in 1.51s**。新增时段边界测试先因缺函数失败后通过；角色表达测试先2项失败后通过，最终完整回归通过。核心两腿/strict-before/阅读时间隔离及保护不直接反手的现有回归继续通过。
- 两次真实固定MDS+权威Session只读结果（去读取时间后）完全相同：690根、相同OHLC指纹；该指纹也与前轮OHLC摘要一致。没有修复或替换数据。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research:packages/quant-core services/quant-api/.venv/bin/python /tmp/lms405-recovery-20261028/verify.py`：旧冻结资产/author-control哈希不变、17条复读ID/URL、R01–R08条件及反例引用、新casebook重复计算/保存结果一致、非执行口径、文档链接与两个CLI拒覆盖且原字节未变，均通过。临时脚本用于本轮验收，长期复算使用上节仓库命令。
- `python3 /tmp/lms_archive_validate.py`：113来源、90图片SHA256、900覆盖行，通过。28日1条为定向后续，300日内112条；主续接21/22日未变。
- 时段独立Review无Confirmed Issue；结果与资料增量Review发现E41相关概念误标必要，已从路线移至source_context，并新增回归确认它不在必要条件检查内；修正后全套74通过。
- `services/quant-api/.venv/bin/python -m ruff check scripts/research/lms405_sh_oct_case.py scripts/research/lms405_public_casebook.py services/quant-api/tests/lms405/test_sh_scope.py services/quant-api/tests/lms405/test_recovery_casebook.py`：All checks passed。
- `python3 scripts/engineering/secret_scan.py --json docs/research/lms405 docs/research/lms-source-archive scripts/research/lms405_sh_oct_case.py scripts/research/lms405_public_casebook.py services/quant-api/tests/lms405/test_sh_scope.py services/quant-api/tests/lms405/test_recovery_casebook.py`：0 findings。
- `git -c core.fsmonitor=false diff --check`：通过；未推送、未发布、未切Runtime。

本轮结论：研究交付完成，允许继续规则识别；**不足以实现原版确定性恢复分支**。只本地Git提交，原冻结资产、旧报告及旧casebook不覆盖。

唯一下一步：取得一个F07式“由弱转强”的带周期信号前后图及同账户解锁腿记录，确认作者把何种可观察变化称为“转强”。目前该词仍是恢复原趋势分支的关键不可计算条件。
