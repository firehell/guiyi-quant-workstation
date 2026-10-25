# SimNow 一次性账户只读核验 v1

本工具为 owner 交办的 HTDY 60m SimNow 接入准备提供独立账户读取，不挂接策略、API、Alert、调度或 Runtime。
它不是生产账本或自动执行适配器，不修改 `auto_order=false`。

## 环境与入口

`scripts/broker/simnow_readonly.py` 只支持已验证的 macOS ARM64、`openctp-ctp==6.7.7.1`。
使用独立 Python 环境，不向服务端项目添加原生交易 SDK 依赖。凭据只由本机 TTY 和隐藏密码输入提供，
不能关闭回显时直接停止；不接受命令行参数、管道、聊天记录提取或日志加载密码。

```sh
/path/to/isolated/python -I scripts/broker/simnow_readonly.py --environment api-test
# 第一套模拟环境只读验收（仅在其服务时段运行，无订单权限）
/path/to/isolated/python -I scripts/broker/simnow_readonly.py --environment first
```

只支持官网当次核实的两个固定SimNow环境，BrokerID均为 `9999`：

- `api-test`（默认）：`tcp://182.254.243.31:40001`，结果身份 `SIMNOW_API_TEST`，历史副本。
- `first`（显式选择）：`tcp://182.254.243.31:30001`，结果身份 `SIMNOW_FIRST`，第一套环境原生读回。

不接受任意前置地址或其他账户环境。断线/失败不切换环境、不重发；环境身份绑定报告及账号摘要。
默认 AppID/认证码沿用官网测试设置，不关闭终端认证。Mac SDK 登录四参数 ABI 已由前序实际登录验证；
该 ABI 与 Linux 两参数形态不同。更换平台、SDK需要重新验证。选择first只允许其只读验收，不能据地址改变晋升执行能力。

api-test的账户/资金/持仓按官网说明来自第一套环境上一交易日副本。两个环境的交易日均以实际登录和各行回报为准，
api-test不能标记为第一套环境当日账户验收。first必须实际完成自身登录与两轮查询才能确认读回；
资金调整也必须以目标环境原生读回确认，不通过修改本地JSON实现。所有环境仍不具备执行资格。

## 读取合同

只允许六种请求：`ReqAuthenticate`、`ReqUserLogin`、`ReqQryTradingAccount`、
`ReqQryInvestorPosition`、`ReqQryOrder`、`ReqQryTrade`。不调用结算确认、密码修改、下单、撤单、转账，
不订阅行情、不写 Redis、Canonical、Catalog 或 PostgreSQL，不创建持续后台服务。

认证/登录各尝试一次。请求只有 SDK 返回0才标为受理；仍需对应成功响应才算认证/登录完成。
返回账号身份必须与本次输入一致。断线、异常、未受理、服务端拒绝均停止，不自动重连登录或重发。

登录后按资金(CNY)、持仓、委托、成交顺序读取两轮；每条查询前至少间隔1.1秒，每次只保持一条未完成查询。
身份、请求ID、回报类型、交易日、字段、数字及重复记录逐条校验；必须收到最后回报才标为完整。
持仓、委托或成交完整返回零条才算零；资金必须恰好一条。未完成不得当作空仓或查无记录。

资金与价格按原生SDK double返回的十进制字符串转 `Decimal` 并以字符串保存，不额外进行浮点运算；
不宣称恢复了柜台浮点传输前的更高精度。保留多/空/净、投机/套保、今/昨、冻结和交易所维度，
不把对锁或超过一手的真实账户强行压入 HTDY -1/0/+1 模型。

两轮完整返回的规范化内容逐值比较，均保存原生字段白名单、起止时间和完整状态。相同结果为
`READ_ONLY_COMPLETE`，变化为 `SNAPSHOT_CHANGED`；后者保留实际两份事实，不能取较有利一轮冒充通过。
CTP 查询不是事务快照；两轮相等只证明有界稳定，不排除窗口间不可见变化。

`account_empty_observed` 只在两轮相同、持仓及冻结均零、无未完成/未知委托，且资金中的占用保证金/冻结保证金/冻结手续费均零时为true；
有保证金但无仓、有冻结资金但无挂单时另列 `inventory_warnings`，不报空账户；
历史成交和终态委托保留，不因此判为当前有仓。它不是执行准入：`execution_eligible=false`，
`ledger_reconciled=false`、`atomic_snapshot=false` 始终保持。尚未存在本程序订单账本，无法证明经济归属或完成账本对账。

## 输出、安全及失败恢复

输出只位于仓库 `output/simnow-readonly/snapshot-<北京时间>.json`，新文件exclusive创建、权限0600。
不输出密码、原始回报对象、异常文本、投资者代码或AccountID；账号以环境+BrokerID+UserID的摘要关联，
摘要仅是身份标签，不声称可以抵抗对短账号的穷举。允许保存的交易记录仍属于本地私人账户数据，不提交Git。
屏幕只显示结果与文件位置；原生SDK日志关闭，回调异常仅保留阶段及异常类型。

查询等待每条15秒、登录等待25秒；这不是整个进程或原生 `Init/Release` 的硬截止。
遇到原生阻塞可由用户结束该一次性进程，不产生任何交易写入；重新运行是新的显式核验，不覆写旧文件，
不后台重试。取消、断线和部分结果不代表账户清空；下一次必须重新登录并从第一轮完整读取。

## 验证

离线入口见 [TESTING](../TESTING.md#simnow-一次性账户只读核验)。fixture只证明协议处理，
真实账户验收必须由用户隐藏输入后实际运行，并独立读回完整结果。测试环境、第一套环境、正式适配器、
账本对账、风险规则和交易启用是分别验收的事项。


## 资金重置生效验收

官网申请成功只证明已受理，不能标为余额已变更。owner提供的本次回执明确目标10万元、生效交易日20261027；
不按“次日”自行推算为20261026，不重复提交重置。原始截图、失败提交及原账户快照保留本地。

```sh
/path/to/isolated/python -I scripts/broker/simnow_readonly.py --environment first \
  --expected-balance 100000 --not-before-trading-day 20261027
```

两个验收参数必须成对，且只允许first；数值/日期格式在读凭据之前校验。核验字段独立于查询完成状态，
只有第一套登录和两轮完整稳定原生读回、交易日至少回执生效日、两轮CNY权益及可用均等于目标、
无持仓/冻结/未完成或未知委托时，`funding_reset_acceptance.passed=true`。API测试副本、旧交易日、
部分/变化或哈希不符、目标余额未观察到均保持未通过。生效日是柜台交易日，不简单等于自然日白天。

本检查仅为本次初始空账户资金基线验收，不用于已有策略成交后的日常净值校验。历史手续费和收益仍按原生事实保存，
不据新余额改写旧记录；即使验收通过，`execution_eligible=false`、`ledger_reconciled=false`仍保持。

验收只证明生效日之后实际读回符合目标状态，不单独证明余额变化必然归因于某一笔重置申请。
