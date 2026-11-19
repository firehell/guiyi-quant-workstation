# 快期模拟执行合同

唯一现役模拟执行提供方为 `TQKQ`，单个主账户。旧 SimNow 保持停用，账户、原始记录和账本保留，不能复制为快期基线。真实资金账户不在本合同范围。

## 来源与身份

策略复用 [HTDY 固定一手规则](HTDY_SIMNOW_V1.md) 的 `huotian_dayou_original_v0` 及交易范围内品种的 completed 60m 输入。RQData/MDS 是信号、精确物理合约及 Session 权威；天勤只提供执行盘口、模拟委托/成交和远端账户事实，不进入 Canonical 或策略计算。

执行版本 `htdy_tqkq_opponent_reprice180_v1`，风险版本 `htdy_tqkq_actual_equity_margin70_v1`，账户 journal 身份 `TQKQ:<账户指纹>:htdy_tqkq_v1`。独立 `services/tq-executor` 环境锁定 `tqsdk==3.10.4`，显式安装系统 SOCKS 代理所需的 `python-socks[asyncio]` 并随依赖锁固定；版本不符拒绝连接。远端与本地订单身份、原始快照 hash、策略信号和运行 commit 各自保留。

## 16 品种范围与原账户收敛

唯一新增交易范围为 `shared_sixteen_products_v1`，由 `guiyi_quant.trading_universe.TRADING_PRODUCTS` 统一定义：
JM、LC、RB、SA、FG、MA、EC、V、PR、TA、UR、SH、SC、CJ、OI、I，与苏冰共享 Paper 组合相同。
它只收敛快期策略计算和订单许可，不修改行情中心 operational 60 品种、Alert Scope 或通知。

既有账户通过版本化 `TqKqTradingScopeV1` 命令追加范围变更，原初始基线、命令、提交凭证和成交身份不改写。
范围外立即禁止新增开仓，撤销已证明归属的未决开仓，并将原物理持仓目标归零；范围内持仓继续原策略管理。
平仓沿用现有盘口、Session、今昨仓、确定性订单与原生对账链路。闭市、缺事实或结果不明时保留退出义务，
不得伪造成交、清账重建或重新发送已有 claim。重启与恢复不能重新放开范围外开仓。

监控分别报告 `FLATTEN_PENDING` 与 `ACTIVE`；只有范围外持仓、委托和预约均结清并有新鲜原生对账后才为 ACTIVE。
过渡期继续保留必要的范围外物理合约输入以完成平仓；结清后这些品种不再进行策略计算，历史账本仍可完整重放。

## 账户与风险

首次完整读取资金、持仓、委托及成交，必须无持仓和活动委托才建立实际权益基线；历史终态委托/成交作为独立 baseline 保留，不重置远端。已有本地账本重启则先对账及恢复权威输入，允许继续管理已证明归属的持仓。外部委托、成交或持仓漂移阻断。

每品种净持仓 -1/0/+1 手，不加仓；反向先平后开；SHFE/INE 按实际今昨仓选择平仓 offset。单手没有整数意义上的部分成交；非一手回报及最小开仓量大于一手都拒绝，不向上取整。180 秒撤单追价必须等原撤单及成交/持仓对账完成；反向、暂停及收盘前 60 秒的开仓撤单不等待 180 秒。

总保证金占用包含远端已用、冻结及本地未被远端覆盖的预约，不能超过实际权益 70%；资金检查另计费用预约。开仓保证金来自账户 `pre_insert_order` 的单手原始结果；每次清除 SDK 临时缓存并校验精确合约/方向，不使用 SDK 舍入保证金率或不可信 fallback。价格和账户数值内部使用 Decimal/tick，页面固定两位小数。

公开 TqSdk Trade 没有逐笔手续费：逐笔 fee 保持未知，账户 commission 展示远端实际汇总。没有现金流连续性证明时，不计算策略净收益或收益率，不把未知填零。

## 发送、恢复与控制

唯一进程用账户排他锁持续 `wait_update()`。先原子持久化订单意图与确定性 native order ID，再提交；SUBMIT/CANCEL 各自最多一次 claim。排队、远端受理、成交及撤单分别确认，结果不明不会重复发送。乱序回报最多等待 10 秒，不会因重启重置期限；成交事实先保留，对账未完成不释放容量。

SDK 内部同步查询产生的通知也必须即时检查；最终账户快照、claim 前及 SDK 发送前均检查连续性，发现重连或跨日即停止旧目标并进入恢复。已有 claim 不删除、不重发。

MDS私有通道每请求最多处理4品种自然信号及4份恢复证明，保留每品种latest合并与该Bar真实首次接收时间；队列缺口继续由原状态机阻断并恢复，不补旧开仓。READY仅轮转处理已有owner的blocked品种，完整账户恢复先处理持仓、缺证明品种继续blocked，不拼接过时证明。20秒期限、超时永久废弃该通道及请求ID关联保持。

版本化命令 `tqkq_observed_signal_v1` 分别保存原Signal.observed_at与实际处理at，避免跨批账户Readback推进时钟后回退；旧Signal及历史账本重放规则不改。同一发送身份不得因重试生成新订单，首次持久hold原字节/原因保留。停止时先新鲜完整对账；确认全部订单reconciled、无未决成交及原生活动委托后，可以不依赖已故障的信号通道退出，不清仓。

收盘尾根使用独立 `tqkq_closed_signal_record_only_v1`：仅当真实首次自然接收发生在该品种权威 Session 末端后60秒内、精确末根 completed Bar、rank1/冻结订阅/物理前缀一致且不属于恢复数据时，保存原 Signal 并推进连续性。该命令不更新 owner、方向目标、待执行信号、订单或预约，也不产生交易 effects；错误 owner/连续性仍明确阻断。其他品种继续按各自 Session 处理。下次开盘不得把尾根变成补开目标；原 V1 Signal 与账本重放保持原语义。

局部品种恢复只处理 blocked 集合中、且权威证明物理合约与既有 owner 一致的品种，显式传入恢复 products；没有交集时不触发账户同步或局部恢复。日盘缺少当前实时事实保持保护，不让夜盘证明误触发日盘恢复。

断线/重启先进入恢复；不以空状态代替必要事实。恢复批次旧信号丢弃，开仓只接受恢复后新 completed Bar；暂停期间的开仓目标消费后不能恢复补单。跨日缺少必要事实继续暂停。私有 MDS 通道按请求 ID 关联，超时后不可复用，防止迟到响应变成新信号。

从未接收策略输入且无任何订单、成交、预约或 claim 的账户，可用 `tqkq_never_active_resume_v1` 在首次 poll 前完成空账户恢复；必须新鲜完整读回且远端无持仓、委托、成交或冻结资金，不绕过持久 hold。保留原权益基线、启用时间及全部审计，只接受恢复时点之后的新 completed Bar。曾有活动或含历史终态 baseline 时继续走原权威恢复。

本地入口：正式树的 `services/tq-executor/.venv/bin/python -m guiyi_quant.tq_simulation.cli`。

- `credentials --replace`：本机隐藏录入框，存独立 Keychain 项目，明文不写文件或日志。
- `configure --root /精确正式树 --tag vX.Y.Z`：核验 annotated tag、commit、clean tree 和正式 API binding；默认为 observe。
- `probe`：先完成 install；使用与 launchd 相同的稳定入口、HOME 工作目录和最小环境，只读连接、当前全品种映射、初次接管或已有账户对账；生成最长 300 秒的启动证明，不发送订单。
- `install`、`start --trade`：将发布脚本原子安装到 AppSupport，probe/start/worker 均在 SDK 之前验证其与 exact-tag 源码逐字一致，再安装唯一 `com.guiyi.quant-tqkq-simulation`，通过新鲜预检后启用。失败进程不自动重启或重发。
- `status`、`pause`、`stop`：暂停禁止新开仓并管理既有义务；停止撤销已证明归属的未决委托后退出，不自动清仓。未知发送状态不能视为成功停止。

不可解释的发送结果、账本冲突或外部操作会留下持久 hold；直接再次 start 不解除。须查清原始委托、成交和账户事实，再按对应恢复语义处理，不能删账本重建。

owner 明确批准的已成交手动平昨仓，可使用 `reconcile-manual-closes --evidence-dir /绝对私有目录 --approval-source 审批来源` 先演练，再加 `--apply` 正式对账。仅允许 Worker 原生停止、control=stop、同版配置核验及账户锁内操作；不发送或撤销订单。逐一核对原始前后快照、手动意图、原生订单和成交，以及新鲜完整账户事实，只接纳精确物理合约的反向一手 CLOSE，原生时间与价格保持原样。任一笔、残余持仓或未知成交不符，整批拒绝。

`tqkq_manual_close_reconciliation_v1` 用单一不可变命令原子追加手动 Order 和 TqKqFill，保留原基线、历史命令及 SUBMIT/CANCEL claims；手动记录使用独立 human 来源，不伪造策略信号或程序发送凭证。证据文件摘要决定幂等身份，重复执行读回原命令；重启从已验证 audit 重建手动 native 映射。逐笔手续费继续未知。提交结果不明时先读取原 receipt 核对，不能盲重写。成功入账保持 RECOVERY_REQUIRED，需新鲜原生账户与权威行情恢复，恢复后新 completed Bar 才能开仓。

跨交易日首次导入须显式提供 `--historical-native-approval /绝对私有审批文件`，不自动降级原 V1。
`tqkq_historical_manual_close_reconciliation_v1` 分别保存不可变 dispatch 原生快照的历史观察时间、历史成交事实、当前入账时间及新鲜当前账户读回。
审批文件精确绑定账户摘要、手动凭证摘要、原生事件 rowid/原字节摘要、前后交易日、观测空窗起点及 owner 确认“无其他交易、出入金、重置”的来源和接收时间；此人为确认不表述为 SDK 已观测连续。
历史原生委托/成交必须恰好覆盖本批，当前新交易日必须完整且委托/成交为空，历史及当前残余持仓必须精确相同；历史快照须覆盖原账本时钟。
仅该批订单可由历史原件确认；当前成交列表保持原样。两类命令共用证据幂等身份，原生原行与审批原字节须在账户事务内复验。
原权益基线、旧账本和 claims 保留，无发送副作用；成功后仍 RECOVERY_REQUIRED，再以新鲜 Recover 恢复原策略。

## 监控与发布

TqKq 的固定 WebSocket 传输策略为 `tqkq_direct_websocket_transport_v1`：
仅 `free-api.shinnytech.com` 和 `otg-sim.shinnytech.com` 加入本 SDK 进程的 `no_proxy`，
并物化原有代理配置，避免 macOS 因新增 bypass 变量而丢弃其他 SDK 请求的系统代理回退。
`NO_PROXY` 使用标准域后缀匹配；启用交易前还须校验 SDK 实际 MD/TD 为这两个 HTTPS/WSS 服务的443端口。
Market/RQData helper 显式使用修改前环境，不继承 SDK bypass；关闭或初始化失败恢复原进程代理变量。
不修改系统代理、SDK安装源码、TLS校验或ping超时；未知endpoint阻止启用。
连接通知只向既有私有dispatch journal保存固定通知码、md/td分类与接收时间，不保存URL或通知原文。
MD及TD断线仍保持原完整恢复、逐品种前缀、新completed信号及账户对账Gate。

只读 `/api/simulation/monitor/{overview,records,records/{id}}` 读取私有原子投影，不导入 SDK、不登录、不提供交易操作。账户、持仓、信号、风控、委托、成交及阻断原因独立于页面参考交易。过期读回不能显示已核验，过期进程心跳撤销页面上的开仓状态。

账户数据与 Keychain 均在正式源码树之外；配置和 launchd 引用保留精确源码树，解除引用之前禁止清理。标准服务和模拟 worker 的代码必须同一正式树。发布、服务启用、策略新信号、模拟委托提交及模拟成交确认分别以现场事实验收；不制造测试成交来补证。

锁定 SDK 3.10.4 的首次连接在 19:00–19:30 维护窗口断开时，会终止连接任务并抛出普通异常。
`tqkq_sdk_maintenance_reconnect_v1` 仅接纳该 SDK 精确 `_run` 代码帧、已验证端点、首次连接标志、
维护分支与原格式共同证明的异常。立即禁止发送并进入 Disconnect；全部本地订单已对账、无未决成交、
所有 claim 均关联已对账订单且预约已释放时，保留维护事件并关闭旧 SDK，19:31 后单次冷建。
旧快照、行情 facts 与同批信号废弃，重新完整账户读回及权威恢复后才处理后续新信号。
关闭未知、重建失败或未决发送继续持久阻断，不复用旧实例、不循环登录、不自动解除历史 hold。

## 实时处理预算与恢复

私有行情协议 `tq_market_state_v2` 只传品种恢复视图，不传账户审计历史；发送、响应共享20秒截止，
等待期间驱动唯一SDK实例。期间发生连续性异常，先消费并废弃本批响应，再进入原恢复流程，
不将旧响应用于下一请求。权威Session交易日变化也触发账户恢复，不依赖SDK必有交易日字段。

LocalStore缓存仅服务同一SQLite连接已验证的提交状态，使用事务内data_version及本连接变更计数
识别失效；启动和恢复仍保留完整历史校验。休市无可执行候选、盘中无有效执行输入时不写空Tick；
平仓后无持仓的rolling状态允许独立清理Tick。报价/Session输入错误保留固定细分原因码。
先同步账户再采集执行报价。实际insert_order之前仍检查账户、Session、Instrument和Quote最早截止。
本地确定未调用SDK发送时，记录版本化local_not_sent证据并终止该提案，保留原claim。
重启先核对该证据、claim和原生委托成交，再完成中断的本地终止。平仓义务可在新鲜输入下生成新提案。
发送结果不明仍持久保护。缓存不授权放宽任何TTL或对账门禁。
