# 苏冰开发持续模型

`/research/subing-decision` 区分“持续模型”和“历史回放”。持续模型只读取既有 completed ObservationStream，不新增 Market 订阅、Alert Scope、通知、正式 Runtime 或 Broker 操作，始终 `auto_order=false`。历史回放原结果和理论后续开盘执行身份保留。

## 已确认的账户与时间语义

首版只允许焦煤模型账户，独立初始资金10万元。记录实际启动时刻，历史与启动前完成观察只预热；不恢复历史持仓或追补历史动作。

执行身份 `next_completed_1m_close_slip1_actual_knowledge_v1` 使用实际处理时刻作为知识边界。意图只能在知识边界之后的完成1m收盘加不利1tick撮合，继续检查成交量、OHLC、涨跌停、费用、保证金和原保护退出。Fill分别记录决策源Bar、成交源Bar、实际获知/处理时刻和物理合约。日终和下一开盘复核沿用统一候选；开盘价只在首根1m完成后可知，不在开盘价回填成交。

`guiyi_quant.subing_account.AccountEngine` 是批量与增量共用的撮合/账户实现。统一需求、机会窗口、跨日毛浮盈和退出义务仍来自原候选。页面不计算交易规则。旧批量入口保持原约束和身份。

## 持久化与恢复

独立本机PostgreSQL数据库 `guiyi_subing_development` 保存运行身份、不可变事件及可重建状态；隔离测试只用 `guiyi_subing_development_test`。不迁移或写既有生产业务表。每批完成观察的原输入、Session、执行事实、实际获知时刻、模型决策和成交一起提交，事件hash链、期望sequence及单worker advisory lock约束重复/并发。事件不可UPDATE/DELETE/TRUNCATE，运行identity不可改写。

重启从不可变身份和逐事件输入重建全部指标/账户，比较当次决策、Fill和状态hash，再核对最终投影；代码、预热来源、原行情、Session或输入身份不一致则拒绝恢复。提交结果不明先读回，不盲重试。处理失败后的内存对象不能继续使用，必须停止并从已提交事件重建。

完成1m/30m/60m均核对权威Session的下一预期端点；同端点的高周期先处理。缺口或游标过期停止，不假装连续。新交易日通过MDS加载前一完整日线；缺失不沿用旧方向。保证金、昨结算与涨跌停执行约束必须属于当日、同物理合约，且在处理时刻已可知。手续费使用下述独立模型费用口径。

账户已开始后事实中断，保留最后可信估值、固定止损/EMA及已知部分保护义务，暂停新增和撮合，明确要求人工复核，不静默恢复。换月保留旧仓和义务、暂停该品种新增，不用新主力价格退出旧仓，不自动移仓。当前只订阅既有主力流，旧合约处置仍需后续明确方案。

## 操作入口

项目根目录，Python入口使用 `PYTHONPATH=.:services/quant-api:packages/quant-core`：

```sh
# 显式建立隔离开发数据库和项目私有连接文件，不在HTTP请求中建表
services/quant-api/.venv/bin/python scripts/dev/subing_model_setup.py
# 通过既有MDS准备完整物理前缀，显式新目录，读Canonical/Catalog
services/quant-api/.venv/bin/python scripts/research/subing_model_prepare.py --through YYYY-MM-DD --out EXPLICIT_NEW_DIRECTORY
# 首次启动前只读检查；已启动时拒绝重复创建
services/quant-api/.venv/bin/python -m app.subing_model.worker --check-start --prepared EXPLICIT_DIRECTORY
# 首次指定实际启动时刻；--once只处理一轮，供读回/恢复验收
services/quant-api/.venv/bin/python -m app.subing_model.worker --start --prepared EXPLICIT_DIRECTORY --once
# 以后恢复同一run，不重置账户
services/quant-api/.venv/bin/python -m app.subing_model.worker
```

`.run/subing-model-active.json` 保存唯一开发run指针，心跳只表示进程状态；连接文件权限0600，不提交、不打印。原前台入口本身不安装launchd或自动重启；已授权的自动托管见下节。手工前台模式用Ctrl-C停止，保留数据库和指针；不能删除指针来绕过恢复失败。

当日执行事实采集使用 `scripts/research/subing_model_facts.py --contract JMxxxx --day YYYY-MM-DD --out EXPLICIT_NEW_DIRECTORY`，上限6次逻辑provider调用、无自动retry；失败保留attempt。采集身份 `rqdata_current_constraints_model_fee_v2`：交易参数不传日期走当前接口并校验实际返回日期，昨结算与涨跌停取current_snapshot静态字段，用权威Session整日包络绑定交易日，拒绝异合约、旧交易日、未来时间或非法价格。不读取快照last/OHLC生成策略输入或Fill。成功资产须以绝对路径及SHA256显式登记在 `.run/subing-model-facts-index.json`，形如 `{ "YYYY-MM-DD": { "path": "/absolute/path/jm.json", "sha256": "..." } }`。没有登记且校验通过的执行约束和可用费用口径就不撮合。请求不会触发provider下载。

owner于2026-11-05确认：当日手续费缺失可沿用前一交易日。独立费用身份 `current_complete_else_previous_trading_day_v1` 优先使用完整当日手续费；任一手续费字段缺失时，只取同一物理合约、Catalog权威前一交易日完整的手续费类型及开/平/平今四字段整组替换，不混用、不搜索更早日期。当前保证金和价格约束不回退。前日仍缺失或当前输入非法就失败；日历须完整覆盖前日到目标日，不能把缺失的交易日误当休市。费用假设保留原来源日期、原参数及目标日期，进入输入hash与不可变事件；不得把它称为已知当日费率，既有事实不回写。页面分别展示“显式登记待消费”和“最后已提交输入”的成本口径，模型净损益受沿用费率偏差影响。原撮合时序/滑点身份保持，费用假设单独版本化。

只读 `GET /api/v1/subing-model/status` 返回独立开发投影与新鲜心跳；无active时NOT_STARTED，读取失败503，心跳过期明确停止。API不创建run，不驱动模型。开发Web代理与API须指向同一工作区。

## 14品种观察与归一化候选

固定集合 `jm lc rb sa fg ma ec v pr ta ur sh sc cj`。除JM外只观察，不生成模型账户、手数、收益或组合结果。

本轮归一化研究取截至准备日的最近120根已完成30m ATR14中位数，与JM中位数相除；近轴/极端MACD/止损缓冲分别按原JM的4/17/13乘该比值。它是单次固定尺度研究，未调优，未做tick取整，未平衡乘数、保证金或账户风险，不能直接执行。该快照不随实时行情自动修改参数；其他品种需owner确认候选及逐品种验证后才可启用。完整物理前缀或执行事实不足必须显示不足；已见数据不构成OOS证据。

正式页面可以只读展示既有开发模型：私有 `~/Library/Application Support/GuiyiQuant/subing-development-read.json`
仅登记 `model_root`（已有开发 `.run` 的绝对路径）与 `results_root`（已登记回放目录的绝对路径），文件权限0600。
路径须无链接、无父级跳转且真实存在；配置存在但非法时明确失败，不猜测其他目录。此绑定仅供两个GET接口读取，
不改变worker根、run、账户或任何研究身份，也不创建/重启worker。模型查询采用只读事务和5秒语句超时。
未登记时仍使用开发预览原有来源；正式展示继续标为开发模型，不构成策略或运行阶段晋升。

## 自动准备与持续托管（2026-11-06）

owner已交办持续自动更新。`app.subing_model_service` 托管原run，不创建新账户、不晋升候选，仍为开发模型且
`auto_order=false`。只使用稳定主开发目录及已登记的read source；不以聊天临时树或发布候选作为模型运行根。
安装前 `--check` 校验原39个模型依赖hash及完整不可变事件重放；唯一worker仍使用原PostgreSQL advisory lock。
通过 `scripts/ops/macos/install-subing-model.py --root /Volumes/扩展盘/guiyi-quant-workstation --install`
显式安装独立launchd label `com.guiyi.quant-subing-development-model`。RunAtLoad/KeepAlive，失败后至少60秒再启动；
进程退出后从已提交事件重建，不继续使用失败内存对象。日志只输出脱敏状态码，不发送通知。

每日在JM权威Session首次开盘1分钟后自动准备当日执行事实，复用原RQData采集器及费率合同。
首次1–5分钟、5–20分钟、20分钟后分别只有一个持久slot，每日最多3个attempt、每个最多6次逻辑调用；
晚启动只使用当前slot，不追补早先slot。闭市不采集；启动前写intent，失败或UNKNOWN不重跑原attempt。
成功资产以绝对路径和SHA登记原facts index；重启仅可恢复已完整保存的成功资产登记，不再请求provider。
准备尚未完成时暂停消费，既有撮合、费用、保证金、价格与实际获知时间约束不放宽。

新增恢复语义身份 `canonical_indicator_catchup_no_execution_v1`：停机缺口只在整日收盘且Canonical完整可读时，
按统一MDS核对物理合约、rank1、完整日历/Session、四周期完整端点和source读前后稳定，并与原warmup、bootstrap
及不可变事件的全部重叠OHLCV逐值比较。冲突、缺失、换月或未知继续明确保护，不拼接、替代或改旧事件。
先恢复已结束旧source_day的尾部，再进入新交易日；不因最新交易日尚未收盘而阻塞可恢复的旧日。
Historical输入以独立恢复事件及来源proof追加，更新指标和观察时间，不伪装Live、不写ObservationStream、
不经过AccountEngine.step、不生成过去决策/成交/费用或估值。知识时间在读取完成后获取。

只有完全空仓、无pending、退出/减仓义务、pullback、日内风险禁入或latched保护的原模型，才清除过期入场窗口，
登记新的reset_after，等待后续新的completed观察产生新信号；持仓、义务或latched保护保持，不静默恢复。
原资金、收益、Fill、决策历史和最后可信估值原样保留，因此指标最新不表示账户估值也被历史补算。
原策略公式与参数不变，该恢复语义单独版本化并纳入不可变事件outcome及restart parity。

该事件需由新监督器的版本化adapter重放；停止托管可用launchctl bootout，但不能删恢复事件、重置run或用旧
前台worker绕过adapter。源码发生不兼容改变继续fail-closed，必须前向修复/兼容原事件，不能改原identity的hash。

### 已批准的原件冲突恢复

owner已批准“保留全部原件、追加数据冲突标记，再从后续新信号恢复观察”。启用时必须显式使用安装参数
`--allow-canonical-conflict-rebaseline`，写入绑定原run的私有策略配置；无该配置仍严格拒绝重叠输入冲突。
恢复身份 `canonical_rebaseline_after_conflict_no_execution_v1` 记录每个冲突Bar的原hash、新Canonical hash、
周期、端点及差异字段。先验证完整冲突清单，再只重建受影响品种的指标状态；原warmup、旧事件、历史决策、
账户与收益不回写。重放仍逐频核对旧前缀及冲突证明，不能用任意覆盖清单解除保护。
完整原run/事件与私有登记在实施前另行保全，恢复事件以新增sequence提交，资金与Fill不得变化。
该模型仍是原开发候选；仅完全空仓且无义务时等待未来新信号，持仓或latched保护不解除。

### 盘中进程重启边界

`completed_backlog_indicator_only_resume_v1` 在每次进程启动后的首批事件登记实际恢复floor，即使没有积压也执行。
floor之前的已完成Bar只进入原bootstrap指标路径，不进入账户撮合；旧持仓、pending与保护义务继续锁定，不能
在历史Bar或重启后的第一根Bar补执行旧pending。完全空仓且无义务时清过期窗口，并解除旧执行Bar的连续性锚，
保留最后可信估值、现金、历史记录，只允许floor后的新信号/新Bar按原执行引擎处理。恢复边界及结果纳入
不可变事件与restart parity；不得把后台进程重启当作清仓、取消旧义务或重新开户。
