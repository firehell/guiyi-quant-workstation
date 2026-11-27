# 苏冰16品种共享 Paper 模型

唯一现役模型是16品种共享资金组合。`/research/subing-decision` 的持续模型、历史回放是同一组合的两种视图。
独立 JM 开发模型及新建14品种组合的入口已退役；旧run、不可变事件、研究结果和历史身份保留，不把它们合并为新组合的资金或持仓。
本模型只读取既有 completed ObservationStream，不新增 Market 订阅、Alert Scope、通知或 Broker 订单，始终 `auto_order=false`。
快期账户仍独立使用 HTDY 60m；两者只共用品种范围，不共用资金、仓位、成交或信号策略。

## 范围、资金与时序

`guiyi_quant.trading_universe.TRADING_PRODUCTS` 是唯一现役范围，顺序为
JM、LC、RB、SA、FG、MA、EC、V、PR、TA、UR、SH、SC、CJ、OI、I。
政策身份沿用 `subing_portfolio_one_lot_v2`，100万元共享初始资金、每品种最多一手、单笔预算5000元、
组合日亏预算20000元、保证金上限70%；同刻先处理退出，再按固定品种顺序分配新增风险。
14 品种旧身份仅供原件审计。

记录真实启动时刻。启动前历史和完成观察只用于指标预热，不恢复历史持仓或补开旧信号。
新实时账本 `subing_portfolio_minute_journal_v2` 使用 `strict_after_pending_and_current_facts_capture_v1`：
成交Bar必须严格晚于原意图的实际知识时点与当前执行事实captured_at两者；较晚才获知的当日约束不能回填此前收盘价。
事件保存执行事实的canonical内容 `payload_sha256`、捕获时间和费用来源；旧v1事件按原身份重放，不回写。
实际知识边界之后的下一合规 completed 1m 收盘使用不利1 tick撮合；分别保留决策Bar、成交Bar、
实际确认/处理时刻和物理合约。检查成交量、OHLC、涨跌停、手续费、保证金及保护退出；不回填开盘价成交。

1m、30m、60m按权威Session核对下一预期端点，同端点先60m、30m再1m。
新交易日使用MDS完整前一交易日的物理指标前缀，不跨品种、跨合约、跨周期替代。
缺口、过期游标、原件冲突、换月或执行事实不足时停止相应提交，保留账目及退出义务，不重置账户。
旧物理合约持仓不能按新主力价格退出或自动搬仓。跨日仍持仓但没有当日可信事实/mark时，保留旧估值时间并暂停组合新增风险，保护退出继续；空仓品种不因此阻断其他品种。

## 持久化与恢复

继续使用本机独立 `guiyi_subing_development` 数据库的既有ModelStore，不迁移其他生产业务表。
run identity、政策、原输入、当时执行事实、真实知识时间、决定、模拟成交、状态及hash链一起保存。
事件不可UPDATE/DELETE/TRUNCATE，运行identity不可改写；sequence、进程排他锁和单worker advisory lock防止并发写入。
重启从原 run 完整重放并逐事件核验投影。提交结果不明时先读回，失败的内存对象停止消费。
运行代码的源码哈希必须与旧 run 身份逐项匹配。策略退役涉及共享源码路径和哈希清单，进行中的 run 继续使用原精确发布副本。
新源码接管前需单独验证从原事件重放及账目一致性，并按既有账本身份合同处理。

私有运行状态独立于发布树：`~/Library/Application Support/GuiyiQuant/subing-paper`。
其中数据库连接权限0600，active指针、心跳和逐品种facts登记随原run保留；发布切换不移动或重置原账本。
旧JM的启动器、托管器和 `/api/v1/subing-model/status` 返回明确退役状态，不再消费旧账户。

## 当日执行事实

首次创建前，16品种必须全部通过精确rank1、Session、完整物理预热和当前执行事实检查。
其中无夜盘品种在新交易日尚无合法快照时，组合保持NOT_STARTED/等待事实，不能以旧日事实或虚构余额启动。
启动后缺事实仍保护原run，不因单次采集失败创建新run。

复用 `scripts/research/subing_model_facts.py` 的 `rqdata_current_constraints_model_fee_v2` 采集器。
参数不传日期读取当前有效分支并核对交易日；昨结算和涨跌停只取同物理合约当前快照的静态字段，
用权威Session包络验证来源，不用快照last/OHLC生成策略输入或成交。
每品种/交易日最多三个持久slot、每attempt最多六次逻辑provider调用；UNKNOWN/失败attempt不重跑。
成功资产以绝对路径和SHA登记逐品种facts index，登记可恢复但不重复provider请求。

费用身份保持 `current_complete_else_previous_trading_day_v1`：优先完整当日手续费；不足时仅取同物理合约、
权威前一交易日完整开/平/平今四字段整组替换，不混用、不搜索更早日期。当前保证金及价格约束不能回退。
费用假设及真实来源日期进入不可变输入，不能称为已知当日费率，既有事实不回写。

## 托管、检查与只读页面

正式exact-tag代码安装唯一 `com.guiyi.quant-subing-paper`，旧 `com.guiyi.quant-subing-development-model` 停用。
持续托管按权威日历/Session准备下一交易日，读取既有完成流，单owner管理原共享run；
闭市等待与输入不足不表示业务已就绪。心跳、run推进和自然业务分别验证。

```sh
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  scripts/ops/macos/install-subing-paper.py --root /absolute/exact-release-root
# 首次安装时显式传已有私有数据库连接文件；不打印连接内容
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  scripts/ops/macos/install-subing-paper.py --root /absolute/exact-release-root \
  --database-url-file /absolute/private/database.url --install
```

`GET /api/v1/subing-portfolio/status` 和 `/history` 只读快照，不在HTTP中建表、创建run、捕获行情或驱动模型。
无 active 且无启动心跳时显示 NOT_STARTED，未知权益显示未知。首次建账前，缺日历、主力映射、正式观察前缀或当日执行事实时，由同一进程在原门槛内等待。正式观察前缀缺失时先等待原件，避免消耗执行事实采集次数。心跳陈旧时显示 STALE_OR_STOPPED，保留最近可读的启动状态码和心跳时间。读取失败返回 503。
历史回放使用独立登记和原政策身份，不把回顾性执行事实作为持续模型当时可知的事实。
历史 API 只展示经核验的 16 品种结果。登记仍指向有效的 14 品种结果时，页面显示“暂无已登记组合回放”，原件供审计。

旧 JM 和 14 品种的模拟证据按原身份供审计。16 品种的 OOS、自然成交、跨日与长期运行各需自己的证据。
实际启动、自然信号/成交和待验事项只记录在 `STATUS.md`。

## 16 品种组合历史回放

在仓库根目录显式指定已冻结的 16 品种执行事实和新输出路径。命令经 MarketDataService
只读核对同物理合约的行情、交易时段与证据，随后生成带输入和源码哈希的回放原件。

```sh
PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python \
  -m scripts.research.subing_portfolio_replay --facts-dir /absolute/frozen/facts --output /absolute/new/result.json
```

工作台读取独立登记的结果和 SHA。缺少任一品种的必要事实时保留缺口。
