# SimNow 全品种持续宿主与自动恢复

Owner交办前两步：共用账户/写入者/信号队列/资金预留，以及安全凭据、自动启动、Session/跨日/断线/重启恢复。
本轮不完成首笔开仓预算（第三步），不因此启用新增开仓或改正式Runtime。默认observe，只做原生读取和本地事实记录。
现有一次性工具作为有界验收入口保留；所有执行继续复用账户reducer、Host/Adapter/Journal及真实费用证明。

## 设计约束

- operational集合冻结；一个账户文件锁在任何账户写入之前取得；一个CTP交易连接串行查询，禁止60份脚本。
- shared MarketBridge读取同一RQData/Canonical/Catalog/Redis入口；一个pubsub订阅全部60m通道。
- 唯一持久信号队列以账户、source/product/bar身份和payload hash冻结；以首次观察时刻、品种、source排序。
  账户命令commit在queue ack之前；重启未处理/停机旧事件标记过期，恢复不补历史开仓；已commit的命令不可重复执行。
- Mode observe不创建订单/成交/资金预留、不确认结算、不接入有副作用的Adapter。
  manage仅允许已知账本义务的平仓/撤单；新增OPEN由默认deny的opening gate拒绝，第三步才接首笔预算。
- 复用账户70%/每品种一手/无止损规则，值继续Decimal。来源年龄<=8，quote receipt后3秒，原生字段及query scope保持。
- 账户故障阻断全账户；单品种输入/metadata缺失单列阻断，不能毒化其他合格品种。未解释外部仓/单/成交阻断。
- 每次新连接、进程重启、原生交易日变化先读资金/持仓/委托/成交，再恢复；不重新initialize既有账本。
  有仓跨日按原生今昨仓及margin重核，旧已reconciled事实保留；跨日费用/现金流不证明时净收益断开。
- Supervisor只能对已知新连接做有界退避，不重发任何claimed/unknown订单。SDK失败与输入变化/缺失分开处理。
- 自动时间计划来自权威Calendar/Session：开盘前120秒可登录准备，开盘后只接新的completed 60m。
  午休/正常闭市不制造故障、不清仓、不丢已正常接收的有效意图；真正断线恢复不补旧信号。
- macOS Keychain通过本机TTY一次提供凭据，程序直接调用Security.framework；不写密码参数/文件/日志/模型上下文。
- 单独可选LaunchAgent，默认render-only/observe，配置及数据根显式、私有且身份绑定；不改十服务/全局配置。
  只在安全设置完成后可安装observe；账户写入、订单能力与正式release/Runtime分别验收。

## 模块与接口

1. `guiyi_quant.simnow_execution.credentials`：`Credentials(user,password,account_id)`（repr脱敏），
   `CredentialStore(backend=None).save(user,password)` / `.load(account_id)` / `.delete(account_id)`；
   固定Keychain service，账户为环境/Broker/User SHA。`scripts/broker/simnow_credentials.py`本机TTY配置，不输出秘密。
2. `settings.py`：`ContinuousSettings`字段schema/account_id/state_root/project_root/sdk_python/api_env/mode/enabled；
   `load_settings(Path)->ContinuousSettings`验证0600 owner及显式目录/身份，拒绝未知字段及本轮开放新仓的模式。
3. `app.simnow_portfolio_market`：共享现有单品种MarketBridge权威resolver，统一pubsub。
   `PortfolioMarket(products)` / `.activate(now)` / `.poll(now,after)->tuple[Signal,...]` /
   `.authority(product,day,now,contract=None)` / `.recovery(state,now)` / `.plan(now)->SessionPlan` / `.close()`。
   `SessionPlan`含 `trading_day:date|None, active:bool, connect_allowed:bool,next_open_at:datetime|None`，由正式Calendar/Session产生。
4. `inbox.py`：`SignalInbox(path,account_id,products)`，唯一/幂等/冻结/有界队列，claim不直接授权发送。
5. Host推广scope集合，保持旧单品种调用与原生事实/费用/全账户对账入口。统一Coordinator在一个账户store上处理scope。
6. `supervisor.py`：可注入gateway/market/clock/credential依赖，默认observe；周期状态及退避次数持久化，
   连接会话只在通过完整账户/交易日校验后可用，停止/异常保留义务，绝不隐式打开OPEN。
   `scripts/broker/simnow_supervisor.py --config <private>`单一执行入口。
7. `scripts/ops/macos/simnow-service.py`：纯renderer `render_launch_agent(settings, config_path)->bytes`；
   默认只规划，显式observe安装才写固定Label plist，KeepAlive失败恢复/ThrottleInterval60，无凭据参数。

## 实施顺序及验证

- [x] 账户scope推广、持久inbox、跨品种先后和共享70%预留，重启幂等/重绘/旧队列丢弃测试。
- [x] 共享market入口、SessionPlan与个别品种阻断，Calendar缺失/周五夜盘/午休/日切测试。
- [x] Keychain、私有settings及本机setup、LaunchAgent默认关闭/只读renderer测试，不向实际Keychain写fixture。
- [x] Supervisor组合：同账户唯一writer、observe零订单/零结算、多品种故障隔离、日切持仓与未知订单、断线预算及恢复。
- [x] 定向/扩大回归、真实SDK无网络兼容、secret/diff、独立高风险Review；集成以Git记录为准。
- [ ] 本地只读preflight/凭据配置可用性及自动启动现场分别验收；实际开仓和持续订单能力留待第三步。

## 特别Review点

账户锁不能只锁每品种；队列ack不能早于账户commit；新连接不能重发claimed订单；
单个warming品种不能引发全账户重复Recover吞掉健康信号；observe启动不能因配置模板存在而确认结算/下单。
安全凭据不可出现在argv或异常，停机/日切不重建账本、不把费用未知当零。

## 实际验证与交付边界

最终Python候选29文件聚合SHA256：`167f61b2867692a2b17c3bb0bdbc677ad7d4c5aa428d86e280f574eaed3e2fb4`。
独立Review无未解决Confirmed Issue，允许集成develop；不包含凭据、自然运行或订单启用结论。
修正了单产品恢复吞掉健康目标、OPEN预留门过晚、一次性预算误约束平仓、缓存盘口阻塞其他产品、
离线成交在回调前被旧持仓preview拒绝、Session提前到期、未知错误误重连、cleanup阻断不耐久及Signal时钟倒退。

实际命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider tests/unit/simnow_supervisor tests/unit/simnow_credentials tests/unit/simnow_host tests/unit/simnow_execution tests/unit/htdy_execution services/quant-api/tests/test_simnow_portfolio_market.py services/quant-api/tests/test_simnow_controlled_market.py services/quant-api/tests/test_htdy_execution_signal.py
```

结果344 passed。独立核心回归227 passed，范围不同不相加；改动29个Python文件Ruff check/format通过，
PortfolioMarket定向Mypy通过，secret-scan findings=0，git diff/check通过。
持久隔离SDK从已验证6.7.7.1环境逐文件hash复制，真实Mac SDK无网络smoke 23 tests通过，
`simnow_supervisor.py --observe-only --check`输出 `CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO`。
没有创建API实例或连接柜台。

既有真实AL账户仅用SQLite mode=ro逐条验证318条命令、60产品，账户SQLite前后SHA相同。
当时本地投影0仓/0订单/0成交只证明旧账本，不证明当前柜台空仓或连接状态。
本机私有observe配置已生成且enabled=false，安全凭据本地TTY入口已打开；尚未读取/验证真实Keychain，
未安装或加载LaunchAgent，未确认结算、报撤单或变更正式十服务Runtime。
需本机凭据可用后再验收只读启动；自然跨日/断线、首笔订单与全品种持续新开仓各自待验。
