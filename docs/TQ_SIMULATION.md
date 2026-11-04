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

断线/重启先进入恢复；不以空状态代替必要事实。恢复批次旧信号丢弃，开仓只接受恢复后新 completed Bar；暂停期间的开仓目标消费后不能恢复补单。跨日缺少必要事实继续暂停。私有 MDS 通道按请求 ID 关联，超时后不可复用，防止迟到响应变成新信号。

本地入口：正式树的 `services/tq-executor/.venv/bin/python -m guiyi_quant.tq_simulation.cli`。

- `credentials --replace`：本机隐藏录入框，存独立 Keychain 项目，明文不写文件或日志。
- `configure --root /精确正式树 --tag vX.Y.Z`：核验 annotated tag、commit、clean tree 和正式 API binding；默认为 observe。
- `probe`：使用与 launchd 相同的最小环境，只读连接、当前全品种映射、初次接管或已有账户对账；生成最长 300 秒的启动证明，不发送订单。
- `install`、`start --trade`：安装唯一 `com.guiyi.quant-tqkq-simulation`，通过新鲜预检后启用。失败进程不自动重启或重发。
- `status`、`pause`、`stop`：暂停禁止新开仓并管理既有义务；停止撤销已证明归属的未决委托后退出，不自动清仓。未知发送状态不能视为成功停止。

不可解释的发送结果、账本冲突或外部操作会留下持久 hold；直接再次 start 不解除。须查清原始委托、成交和账户事实，再按对应恢复语义处理，不能删账本重建。

## 监控与发布

只读 `/api/simulation/monitor/{overview,records,records/{id}}` 读取私有原子投影，不导入 SDK、不登录、不提供交易操作。账户、持仓、信号、风控、委托、成交及阻断原因独立于页面参考交易。过期读回不能显示已核验，过期进程心跳撤销页面上的开仓状态。

账户数据与 Keychain 均在正式源码树之外；配置和 launchd 引用保留精确源码树，解除引用之前禁止清理。标准服务和模拟 worker 的代码必须同一正式树。发布、服务启用、策略新信号、模拟委托提交及模拟成交确认分别以现场事实验收；不制造测试成交来补证。
