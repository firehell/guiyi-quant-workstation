# JM日线阶段D：独立验证范围与证据

结论：阶段D工程一致性验证通过，OOS和参数稳定性证据不足，阶段D整体验收仍为PARTIAL；不得晋升至持续Paper。验证程序与证据允许集成develop。

本轮只做离线独立验证，不改策略、风险、成交或账户政策，不启用Paper/Runtime，不下载或修复数据。冻结基线为阶段C数值提交`f36dd1dd3f1e546cb62639ebb319c2bc8ae98006`与`phase-c-002.json`；研究合同沿用[设计](subing-jm-daily-v1-design-20261022.md)及[阶段C](subing-jm-daily-v1-phase-c-20261022.md)。

## 执行前冻结的范围

已查看边界：2026-10-22（北京时间交易日口径）。此前阶段A已审计919日，B/C已查看489日及逐笔结果；不能把旧历史重新切分称为未见OOS。既有489日（2024-10-14～2026-10-19）仅用于下列确定性验证，未追加新行情窗口或隐藏筛选。

- 通过MDS重新核验相同Bar和执行快照身份；所有数值代码字节SHA保持与C一致。
- 对7个合约的完整物理日线前缀（包括预热）检查1/21/34/35根、半程和全程边界；仅改变这些边界之后的OHLC，过去EMA和交叉须不变；重新计算的489日信号与冻结输入逐值相同。
- 对主连续账户及7个独立owner检查首事件、半程、结束及首次进入每种仓位/意图/换月状态的前缀；用较短输入重新创建账户，结果与原批处理到该时点一致。
- 另按相同顺序逐事件处理，在上述边界重复投递并经JSON往返checkpoint恢复，比较恢复前后完整checkpoint、恢复后再次重复投递，并继续后续输入；内部风险/去重状态及最终输出一致。该比较验证批量调用、增量投递和恢复，不声称存在第二套独立策略内核。
- 逐笔模拟Fill绑定物理合约完成1分钟Bar，执行开始严格晚于意图、方向性1 tick、整数1手、非零量及涨跌停约束；核心账户输出须等于C基准。旧合约换月中断保持，不拼接独立账户。
- 检查器须通过负向测试：批次未来长度污染账户输出、未来日线污染过去信号、伪造成交价格或同刻成交均应失败。构造反例只证明检查行为，不冒充真实历史结果。

本轮不调EMA21、12点保护、2%风险或5%日亏参数，不搜索最佳组合。阶段C成本扰动只能证明费用/滑点敏感性，不能当作EMA、止损或风险参数稳定性证据；参数稳定性仍为`NOT_ESTABLISHED_NO_PARAMETER_SEARCH`。模型不具备对全部历史交易盈利能力作晋升判断的充分证据。

## 未见样本的合同

只有交易日严格晚于2026-10-22的已完成新样本才可能标为`FUTURE_ELIGIBLE_NOT_VALIDATED`，该标签不等于已经通过OOS。需要另行核验新的日线/15分钟/物理1分钟与逐日执行事实，冻结数据和政策身份，在查看绩效前确定研究起点、末端和评价口径；不设置收益导向的可选终点，不以少量交易阈值自动判赢。

新样本保留当前固定规则、成本与换月中断合同。不能自动恢复原中断账户；若另起未来研究账户，须明确其独立初始100000元与起点，不能接入旧收益。跨owner再次中断仍报告null/未平持仓，不能用新合约清算旧仓。缺少权威事实则不模拟成交。通过OOS也不自动进入Paper。

本轮不创建定时采集、后台监控或自动订单；自然未来行情尚未发生不是人工审批待办，也不能由回填旧数据制造未见证据。全历史执行事实缺口、换月退出缺口和样本稀少限制保持。

## 实际验收

范围/检查器先冻结于`f6270fb2262e93913fa8470c5cac275429138f59`，独立Review修正后的最终检查器提交为`a76fe585afdf0315f8ed5d85ad82176563bb23ed`。数值策略、MDS适配器、C成本脚本及私有配置读取器四份字节SHA仍与C002完全一致。

最终证据：`output/subing-jm-daily-v1-20261022/phase-d-002.json`，文件SHA256为`98348af4b3048d90ad8014aac92ae601f58bdd0ca9129baface8d9c0fae16be1`，内容result_hash为`bdefa8e30514ce9dfc7360133f1f44e670c8d2268e7c9c27b4c626962911e3b7`。001保留，但未包含修正后的内部状态恢复检查，不作为最终恢复验收证据。

输入hash为`3f97123a6160c23e52a1e6ad9a3cd719cb0c8729689d0433f549b82bf1abb626`，facts hash为`62f33cdbd73855a8a73f77db87a60a26231aaba54e3738231c4caa3529eb99a9`，与C相同。002绑定输入文件SHA和5份数值/验证代码SHA，所选Bar身份与C完全一致，原文件前后SHA未变；D1额外读取前后再次核对MDS来源。执行快照仍为回溯采集，确认时刻=Bar完成时刻仍是模型假设；这些检查不证明历史实际数据到达延迟或逐tick成交。

| 合约 | 含预热物理D1数 | 有效D1逐值核对 | 账户前缀/恢复检查点 | 验证Fill数 |
| --- | ---: | ---: | ---: | ---: |
| JM2501 | 222 | 47 | 3 | 0 |
| JM2505 | 221 | 77 | 7 | 2 |
| JM2509 | 210 | 73 | 3 | 0 |
| JM2601 | 214 | 84 | 3 | 0 |
| JM2605 | 222 | 86 | 7 | 2 |
| JM2609 | 223 | 84 | 7 | 2 |
| JM2701 | 179 | 38 | 3 | 0 |

共1491根含预热日线、489根有效日线，42次物理日线前缀检查、35次未来OHLC扰动检查全部通过。独立owner共33个账户检查点；主连续账户另2个，共35个。各检查点均验证短前缀重建、增量结果、完整JSON checkpoint恢复、恢复前重复投递及恢复后重复投递；每一类各35次。不是每个历史时点穷举。

有成交的JM2505/JM2605/JM2609均覆盖空仓、待开仓、已持仓、待清仓、清仓后空仓；其余4个owner只有真实空仓路径，不虚构持仓或停机。主账户验证空仓与换月中断；仍处理17344事件后停止、0 Fill、整窗收益null。7个独立owner共6笔基准Fill时序/价格/合约检查通过，核心账户输出与C完全相同；不把它们合成连续账户。本轮没有增加新的交易机会或绩效样本。

实际命令（隔离工作区，既有Python环境，无工作区缓存）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python scripts/research/subing_jm_daily_validation.py --project-env '/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env' --phase-a /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-a-003.json --phase-c /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-c-002.json --facts /Volumes/扩展盘/guiyi-quant-workstation/output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json --output /Volumes/扩展盘/guiyi-quant-workstation/output/subing-jm-daily-v1-20261022/phase-d-002.json
```

输出独占创建，重跑须使用新文件名，不能覆盖002。provider调用0、数据写入0、auto_order=false、continuous_paper=false；未改变正式运行副本。

定向测试：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest -p no:cacheprovider services/quant-api/tests/research/test_subing_jm_daily_validation.py services/quant-api/tests/research/test_subing_jm_daily_stress.py services/quant-api/tests/research/test_subing_jm_daily_model.py services/quant-api/tests/research/test_subing_jm_daily_inputs.py services/quant-api/tests/research/test_subing_jm_daily_preflight.py services/quant-api/tests/test_runtime_shared_tools.py services/quant-api/tests/data_foundation/test_closeout_binding.py -q
```

238 passed，含11项本轮测试；Ruff、secret scan及diff格式检查通过。独立Review发现检查器原来只对比恢复后的外部result，可能漏掉内部去重状态或日亏基准丢失。两项负向测试先复现未能检出，再补完整checkpoint对比及恢复后重投检查，两项转绿，238项回归通过。未发现冻结交易模型本身丢状态，不改模型版本；原P2已关闭。最终证据身份和文档独立读回通过，独立11项定向测试通过，无剩余Confirmed Issue，允许集成develop。

## 剩余条件与唯一下一步

`OOS_NOT_PROVEN`、`NOT_ESTABLISHED_NO_PARAMETER_SEARCH`保留；3个不同历史交易不足以判断策略价值。工程因果验证通过不等于经济有效性或完整阶段D通过，也不授权持续Paper。

唯一最小下一步：在查看新样本绩效前冻结未来样本的具体起止和评价口径，待新完成行情及逐日执行事实核验后，进行独立样本验证；不回头把已有历史改称留出段。尚未发生的新样本不伪造为通过，也不新增自动采集或后台任务。
