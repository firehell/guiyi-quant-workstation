# PTA／甲醇优化研究：最终独立Review

结论：REVIEW_COMPLETE。允许采用本次离线研究结果、复算脚本和淘汰结论，允许集成 develop；未发现阻塞本次交付的剩余 Confirmed Issue。没有候选满足晋升条件，不授权发布、Runtime、Shadow或账户动作。本Review由独立代理完成，未启动SDK或全量数据／回放worker。

## 已修确认问题

- 初版对spool.Rows使用[-1]会失败，且修改反序列化dict不能持久化；现改为SQL读取最后Fill，退出原因在订单创建时冻结并随原引擎持久化。
- 初版融合同Bar CLEAR→BUILD会覆盖平仓target；现先挂起BUILD、完成旧仓模型Fill后才尝试新开。原Bar后180秒有效期、后续CLEAR和owner变化均约束待开意图，不让页面参考价成为Fill。
- 初版输入身份不完整、残留attempt存在重复累积风险；现绑定执行源码、事实、DB、费率、保证金、实际Tick原件及特征，单run拒绝已有结果／checkpoint的自动重试。
- 初版逐点检查仅为cash＋floating算术；现新增原entry／可信mark独立账本重放，不再将内部恒等式当作独立核算。
- 最后报告编辑一度使build_report.py身份过期；owner执行代理重建study-identity后，本代理实际重算117项源／输入SHA全部一致，40个accepted summary SHA亦全部匹配。未改业务结果来消除不一致。

## 独立实际验证

- 运行新test_experiment.py、独立test_review.py和原TA五个定向测试文件：**60 passed in 0.81s**。包括ATR填价严格前知、不漂移、feature调度优先、趋势拒绝保留原反向平仓链、风险方向锁与同Bar禁新开、融合挂起／撤销BUILD、震荡不镜像空头、checkpoint新字段恢复及输入变化拒绝恢复。早期夹具因并行新增字段缺lock_contract／entry_at而失败，补齐夹具后通过，未降低业务断言。
- 独立verify_review.py标准库核对全部40组：**7,094笔闭合、14,214个Fill**。导出原件SHA、闭合净额、胜负分母、总手续费、Fill严格晚于订单、买卖限价和COMPLETED精确截止全部PASS。
- 读回原entry逐点核算产物：TA20组 **6,327,570点**，MA20组 **6,326,884点**，共 **12,654,454点**。全部equity_margin_fees、fill_limits_timing、closed_wins为PASS。静态复核verify_valuations.py确由原入场Fill和可信mark重建权益／保证金／费用，不依赖日结算basis重复计利。本代理未再次运行这些重型worker；核算worker实际exit0、stop=null。
- 最终源码baseline-final的TA原版1 tick与早期attempt全部Fill、Trade逐行相等，权益／净额／费用／滑点／回撤／未平仓一致；另存baseline-final-verification.json。额外基线复跑不是新增样本，主矩阵仍40组。
- 原月度两组冻结产物与PTA旧两档产物哈希／净额审计由baseline_audit实际PASS。原MA execution.sqlite由本代理重新流式hash，与补价前plan.source_execution_sha256相同。新研究仅写副本，未把补价冒充Canonical修复。
- TA特征6,423行，时间严格递增、(contract,t)唯一；TA及MA的MDS特征逐owner对照原冻结source-proofs。特征source capture身份与最终执行身份分别保留，原始XMA历史重绘不回写既有决策。

## 报告、门槛与建议核对

- report.md的PTA／MA两档收益、交易数、回撤及方向范围与实际summary一致。牛哇三组均只做多，与火天大有long_flat对照；不把双向差异解释为指标优劣，不把两个独立10万元账户收益相加。
- 所有8项单因素gate均为false。TA趋势仅14笔、MA仅11笔且净亏，样本门槛不成立。ATR虽减轻TA大亏／回撤，但净期望下降；震荡辅助退出也未提供所需增量。组合记NOT_RUN_GATE_NOT_MET有依据，无需为得到盈利结果追加调参。
- PTA 1 tick逐笔归因已实际核对：ATR2改善25笔原亏损、28笔原赢转亏、闭合净额少14,190元；ATR3为19／12／少6,670元；震荡退出为22／11／少6,770元，与trade-difference-summary完全相等。
- PTA原版保留研究基线、MA不扩大双向使用，与数据相符。long_flat只是方向对照／后续研究线索，没有被冒称合格候选。所有2023—2026样本仍为已见开发数据，不是独立OOS。
- 没有合格唯一候选，故未创建新前向任务、未启用Shadow。8交易周且30笔闭合仍是未来条件，不能由历史重放或一夜运行制造。

## 实际限制

分钟代理占大部分Fill，盘口／排队／延迟仍为模型假设；固定公开公司费率、保证金情景不是多年个人实际账户条件。重建信号不是历史实时Event或用户收到通知的证明。

矩阵用于新研究目录；已有结果由最终独立验算／receipt确定可信，不能仅凭目录存在判断成功。单run明确拒绝自动重试；需要恢复或复算时必须保留旧attempt并核对输入身份。

本任务没有修改正式公式、Canonical／Catalog、生产DB、Runtime、Broker或通知；其他任务STATUS.md修改保持独立。资源遥测和初期失败attempt保留，不能将修正后的成功表述为从未遇到失败。

最终采用结论：**允许集成 develop；研究候选不晋升。** 最小下一步是按已导出的逐笔差异提出一个有明确失效依据的新假设，而不是继续搜索本轮ATR阈值。
