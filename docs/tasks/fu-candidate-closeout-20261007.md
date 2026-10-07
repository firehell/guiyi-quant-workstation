# FU 燃料油历史候选收尾工作记录

2026-10-08：`CANDIDATE_CLOSED / REVIEW_COMPLETE`，12/12，允许集成develop。
数据、12项候选、API、唯一Chrome19场49原图、数值/视觉、精确退出与最终独审已实际通过。
历史候选58/60、正式分钟范围45/60；FU仍属P7-01，原13/21分母不变，剩余PP、SS。

## 冻结范围与旧失败

冻结代码 `083bcb9876f840482cfe34efbfde29c51a726f01`。FU 已有 singleton 准入，本轮没有生产源码修改。窗口2023-01-01至2026-09-24，as_of 为 `2026-09-24T07:00:00.000001+00:00`；21个物理 owner、84个维护单元。权威上市日2004-08-25。1m仅作为聚合源，分钟验收范围为5m/15m/30m/60m×趋势/震荡/双策略。

旧证据 `outputs/fu-minute-closeout-20260928` 保存4个完成单元、1个失败单元、79个未尝试单元。4个完成单元均为FU2305：5m为NO_GAP，15m/30m/60m各读回8个派生目标，均无外部价格请求。失败边界为FU2309/5m维护中FU2309/1m/2022-09来源发布，原attempt PENDING、retry=false，无result和provider raw。旧失败根因保持UNKNOWN，不用本次响应解释原始失败。

旧五频完整after inventory存在：351→391个文件，40个新增，391个旧文件的558976根Bar保持。该旧inventory不是七频Catalog快照，不证明旧D1/W1状态。现有前像1203个文件全部纳入本轮保护；旧边界与当前之间的变更来源保持UNKNOWN。

旧路径审查第一次因把混合命名的旧文件假定为统一 `part.{hash}.parquet` 而失败，原脚本和日志保留。修正只使用封存明确路径、fresh精确路径/hash，及限定五个FU2611/2026-09 key的冻结旧hash路径；逐SHA和旧Bar字段证明，未glob猜最新版。该准备失败不计为新的数据维护attempt。

## 单次来源诊断与规范化

FU2309/1m/2022-09单次诊断真实外部价格调用1次，完整响应7125行封存。按 `rqdata-turnover-truncate-18-v1` 仅将成交额超过18位的小数向零截断，实际3行变化；整数、OHLC、volume、OI、交易日与端点保持，原生scratch证明通过。None及数值NaN缺失语义保持，present非有限或负值仍拒绝。

当前诊断可以证明本次响应与18位规则的兼容性，不能证明已丢失的旧失败raw逐值相同。诊断raw只在首个FU2309/5m单元内按物理合约、原生交易日请求窗口、完整端点、plan/preimage/proof和SHA精确绑定复用一次。后续请求没有缓存替代。

## 宿主中断、归档恢复与新尾部执行

原forward父计划SHA `09214b67b0db1fe0c67a08afcb934865db2857efd4d8a070f6d2c3db2a857de6`。原forward完成73个单元，最后为FU2606/5m；宿主会话中断后进程已不存在，原campaign没有complete或stopped终态。FU2606/15m只有plan、quota-before与PENDING attempt，没有quota-locked/result/readback。原attempt保持未知，不将宿主中断写成原生维护失败，也不重跑原campaign。

另一个清理线程误将进行中的FU worktree移入 `.ai/worktree-cleanup-20261007-233713/fu-candidate-closeout`。根代理恢复原branch与原路径，1086个任务文件逐SHA相同，临时项目配置亦精确恢复；`worktree-archive-restoration.json` 保存证明。首次恢复复制产生嵌套目录的准备错误另有精确清理记录，原证据保留。归档字节恢复本身不证明未知单元未写入。

唯一只读结算核验73个连续完成前缀、FU2606/15m完整native计划与当前七频Catalog/files。实际 `interrupted-readonly-settlement.json` 为 `READONLY_SETTLEMENT_NO_WRITE_PROVEN`：当前状态与封存前像完全相等、完整native plan相等、维护锁0。原未知attempt不改写。

新tail使用独立计划、runner、attempt和证据目录，只执行剩余11个单元，不重新消费诊断缓存。原73个单元与tail11个单元按实际来源目录绑定，source raw不复制，旧未知同名证据保留在原目录。最终84个单元为77 READBACK_VERIFIED、7 NO_GAP；188个native来源请求对应187个forward外部请求、1个诊断缓存复用，另计已实际发生的1次诊断外部请求，总实际外部价格调用188次，未重复计数。派生目标762个，成交额规范化3行。

## 已通过的数据证据

当前1203→2067个文件，864个新增、86个合法扩展、0删除；1117个active文件保持，扩展中的105959根旧Bar逐字段保持。587个D1/W1文件及Catalog保持。

| 周期 | 独立完整前缀Bar | 物理合约月 |
|---|---:|---:|
| 5m | 328149 | 251 |
| 15m | 109383 | 251 |
| 30m | 57092 | 251 |
| 60m | 33347 | 251 |

合计527971根，21个物理owner、20个候选区段边界。按物理Session `(start,end]` 与Decimal200核对完整字段、端点和生命周期月份，绑定实际封存来源、规范化与旧Bar保留证明。

`independent-root-raw-source-review.json`、`independent-root-preservation-review.json`、`independent-root-data-review.json` 已实际通过。`independent-data-overall-review.json` 为 `REVIEW_COMPLETE_ALLOW_FU_CANDIDATE_ASSET_BUILD`，只允许继续串行构建候选资产，不代表资产或页面已验收。

## 候选资产与产品验收

12项原生构建串行完成，计划与apply各一次实际exit0；8基础与4融合保存态均READY、disabled、activation_generation=0。
每周期资产输入在数值Bar外增加20个合约边界点。fresh保存态manifest、revision、seq与原生计划一致；
4项融合的8条真实 `input_manifest.source_dependencies` 伙伴边与对应基础资产revision/seq/digest/snapshot精确匹配。
8基础availability各FULL、21个VALID区段；summary中的complete_window_proven=false保持，不推导日周FULL。

原生只读预检通过。API12组合、152矩阵GET全部HTTP200，另1次初始身份GET；
实际完成于2026-10-07T16:22:28.462318Z后，才启动Chrome。
首Chrome命令因URL未引用的zsh glob在CLI执行前被拦截，未启动浏览器或采集，准备失败记录保留；
修正引用后的唯一Chromeopen实际exit0，再执行唯一capture实际exit0。
19场49新原图全部封存，await原生index实际exit0后才启动audit与独立numeric，各一次实际exit0。
18个交易展示场景及取消/超时/409恢复通过，独立核对21118笔CLOSED与21154个SVG点，
完整数组、参考价格、稳定身份、排序分页、累计收益与完整曲线一致。
49张原PNG实际逐图视觉审查通过，视觉报告SHA
`0887d6a460aaf4bdd434d516a4377bf578affe3143f07cd6be9ebd6b022d6388`。
原生 `NUMERICAL_PASS_VISUAL_PENDING` 与采集原件不改，由独立视觉及最终审查补充结论。

W1实际46/120 Bar预热、历史20区段预热不足；趋势/震荡/双策略CLOSED为7/1/9。
密集标签、tooltip覆盖与较早分钟副图短段/右侧空白等视口限制保留，不从截图推完整覆盖或执行事实。
OPEN及换月中断浮动不计CLOSED收益；页面为零手续费/零滑点参考，不证明因果/OOS或模型账户收益。

## 精确退出、验证与交付边界

任务项目 `.npmrc` 临时设置 `offline=true`，仅使用已缓存CLI0.1.22，未改用户/global配置。
完整transport及60/65/110门禁保持，未重启capture或重采。
Chromeclose实际exit0，13bytes配置按exact SHA删除；API62190/Web62210经argv/cwd/端口双重身份核验后SIGTERM退出。
最终只读exitreadback实际exit0：两PID退出、8012/5178无listener、维护锁granted/waiting均0，
仅fresh12保存态identity/revision/seq及disabled/generation0保持，source_prefix_revalidated=false，不重扫源。

实际验证使用冻结worktree的PYTHONPATH和主仓库quant-api venv Python；下表为本轮命令入口，完整输出均在证据根。

| 实际命令入口 | 结果 |
|---|---|
| `data_readback_once.py` | exit0；七周期快照、source-v2与四频原生聚合通过 |
| `independent_raw_source.py`、`independent_root_preservation.py`、`independent_root_full_prefix.py` | 各一次exit0；raw、保留与527971 Bar复算通过 |
| `build_assets_once.py` | exit0；12项plan/apply全部exit0 |
| `final_asset_readback.py`、`coverage_expected.py` | 各exit0；12保存态、8基础FULL/21VALID |
| `python -m scripts.newow_candidate_tools preflight --execute-get`、`api/readback.py --execute` | exit0；预检与12/152 GET通过 |
| `capture_once.py --session fu-candidate` | 唯一exit0；19场49原图 |
| `python -m scripts.newow_candidate_tools index`、`audit`、`independent_numeric.py --root acceptance` | 各一次exit0；完整数值/SVG与恢复通过 |
| `stop_preview_exact.py --apply`、专属Chromeclose、`task_offline_cli.py remove`、`targeted_exit_readback.py` | 各exit0；资源/config精确退出 |

定向guard准备测试通过；继承的ZN fixture错误、tail source月份去重预算准备失败、旧路径准备失败及其修正证据均保留。
仅补跑受影响单项/纯函数验证，不重跑已过的整套API/Web或其他品种，不重用失败/未知生产attempt。
本轮没有生产源码、公式、收益口径或正式消费者范围改动，Git交付仅STATUS、本记录和roadmap实际FU行。

最终独审 `recovery/independent-final-closeout-review.json` 为 `REVIEW_COMPLETE_CANDIDATE_CLOSED`，SHA
`beb906e909e10c26762d921c2dd9001dd9867e5ceeb1f3f3e04a9608163fe3e0`。
page_parity=true、executable=false；正式Scope、Release、Runtime、通知、交易与auto_order=false保持。
回滚文档不撤销已通过质量的Canonical行情事实，不改原失败/未知证据；本次不发布main/tag或提升Runtime。

本轮证据根：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/fu-candidate-closeout/outputs/fu-candidate-closeout-20261007/`。
旧证据根：`/Volumes/扩展盘/guiyi-quant-workstation/outputs/fu-minute-closeout-20260928/`。
唯一下一步：按剩余队列安排PP、SS的独立收尾；本轮只交付FU，不继续其他品种。
