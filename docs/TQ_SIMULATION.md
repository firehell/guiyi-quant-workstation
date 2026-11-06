# 快期模拟执行合同

唯一现役模拟执行提供方为 `TQKQ`，单个主账户。旧 SimNow 保持停用，账户、原始记录和账本保留，不能复制为快期基线。真实资金账户不在本合同范围。

## 来源与身份

策略复用 [HTDY 固定一手规则](HTDY_SIMNOW_V1.md) 的 `huotian_dayou_original_v0` 及 operational 品种的 completed 60m 输入。RQData/MDS 是信号、精确物理合约及 Session 权威；天勤只提供执行盘口、模拟委托/成交和远端账户事实，不进入 Canonical 或策略计算。

执行版本 `htdy_tqkq_opponent_reprice180_v1`，风险版本 `htdy_tqkq_actual_equity_margin70_v1`，账户 journal 身份 `TQKQ:<账户指纹>:htdy_tqkq_v1`。独立 `services/tq-executor` 环境锁定 `tqsdk==3.10.4`，显式安装系统 SOCKS 代理所需的 `python-socks[asyncio]` 并随依赖锁固定；版本不符拒绝连接。远端与本地订单身份、原始快照 hash、策略信号和运行 commit 各自保留。

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
