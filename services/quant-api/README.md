# Quant API

FastAPI 后端提供统一行情读取、只读策略/参考交易、Alert 与 Runtime 状态。

- `/api/v1/market/*`：Canonical/Live bars、dominants、首页概览、Newow 分区响应与苏冰历史参考。
- `/api/alerts/*`：HTDY 与 SuBing 两种 observation Rule、symbol × frequency Scope、immutable Event。
  Scope mutation 和首次 SuBing activation 仍须对应明确授权。
- `/api/runtime/*`：只读 Runtime 状态。
- `/api/v1/research/new-subing/*`：独立新苏冰策略固定历史结果、规则与分页模型记录，只读。
- CLI：`guiyi data ...` 与 `guiyi runtime ...`；数据维护、恢复及真实操作合同见
  [DATA_CENTER.md](../../docs/DATA_CENTER.md) 和 [部署合同](../../deploy/README.md)。

行情通过 `MarketDataService` 统一读取；指标/策略与参考投影复用 `packages/quant-core`。
Newow、苏冰历史参考与 AlertEvent 分别保留身份，不创建账户、订单或成交。
退役产品入口不恢复，完整边界见 [PROJECT_SOURCE.md](../../PROJECT_SOURCE.md) 和
[ARCHITECTURE.md](../../docs/ARCHITECTURE.md)。

验证命令统一见 [TESTING.md](../../TESTING.md)。隔离测试不授权生产 PostgreSQL、Redis、
Canonical、Scope、通知或 Runtime mutation；当前运行事实只看 [STATUS.md](../../STATUS.md)。

## 回测中心

桌面入口为 `/backtests`，研究 API 为 `/api/v1/backtests`。牛哇趋势可在
已审阅成本窗口内按 FU2603 或 FU2604 单一物理合约提交 5m 信号、1m 执行的试验。
执行延迟参数为 0–3 分钟，
从同 Session 首个严格后继的 1m 开盘起算。配置页列出策略接入资格，
P3/P4 从原 Newow 试验面读取。

正式工作台 API 从当前用户的 `~/Library/Application Support/GuiyiQuant/workstation-api.json` 加载回测引擎配置。文件权限为 `0600`，许可证只传给原生回测子进程。该文件也可配置 `GUIYI_SIMULATION_READER_DSN`，供模拟中心读取账户登记和已有柜台记录。开发环境可继续显式设置相应环境变量。

回测配置如下：

- `GUIYI_BACKTEST_STORE` 是独立 SQLite 文件，默认
  `~/.local/state/guiyi/backtest-center/research.sqlite3`。
- `GUIYI_BACKTEST_PLUS_PYTHON` 指向安装了 RQAlpha Plus 4.5.0 的独立 Python
  绝对路径。执行时核验 Plus、RQAlpha 和米筐数据模块的配套版本。
- `GUIYI_BACKTEST_PLUS_BUNDLE` 指向已下载的米筐数据根或其 `bundle` 子目录。
  本机使用 `/Volumes/扩展盘/.rqalpha-plus/bundle`。
- `GUIYI_BACKTEST_PLUS_COST_PROFILE` 指向已经审计的本地 RQData 逐日成本文件。
  原文件覆盖 FU2603 的 2025-12-22 至 2026-01-23。相邻合约版本保留该区间，
  另覆盖 FU2603 的 2026-02-05 至 02-27 和 FU2604 的 2026-02-12 至 03-02。
  Run 保存文件、交易参数和适用结算边界的身份。
- `RQSDK_LICENSE` 由现有安全环境提供。执行器只允许米筐官方期货授权校验，
  且只把固定诊断码返回给工作台。
- 非 Git 安装通过 `GUIYI_BACKTEST_CODE_REVISION` 指定构建提交。Git 工作区
  读取当前提交，两边的执行器均验证实际载入的策略源码摘要。

执行队列由 API 进程监管，原生引擎在独立进程运行。关闭或重启后从持久化状态
核对已提交结果。要再次尝试已结束的配置，在任务详情选择重跑。原输入修订
必须可复算才能重跑已固化的 Run。历史 Run 有已认证的原生检查点时，
可从详情选择「延长回测」。`POST /api/v1/backtests/runs/{run_id}/extend`
只接受新结束日和请求键。新 Run 从已结算边界恢复原生账户和策略状态，只执行之后的
完整交易日，并报告实际新增交易日和引擎分钟数。历史前缀和合约元数据仍会重新核验。
旧 Run 支持查询。无检查点的旧 Run 可先按当前已核验配置全量创建新 Run。
增量请求失败后可以重新从同一来源发起延长。移交只读研究档案无需续跑密钥，
恢复执行环境时应使用原本机私有检查点密钥。

旧月带仓到期时，Run 停在原生交割平仓前并标记 `ROLLOVER_INTERRUPTED`。
详情可读取旧月自己的结算价估值。当时可知的 rank1 证据缺失时，主力选约保持停用。
任务明细从 `/api/v1/backtests/runs/{run_id}/events` 读取阶段记录，失败任务仍可查阅。
逐笔图窗使用同一 Run 归档数据与原生成交身份。无法核验图窗时，保留已归档的交易明细。
实验、OOS 和 Walk-forward 通过 `/api/v1/backtests/experiments/{experiment_id}/evidence`
读回成员 Run 与证据。评价日需匹配冻结的日期、原生结算时钟和结算权益。

逐日成本来自 RQData `futures.get_trading_parameters`。1 月 5 日起使用新的
开仓及平昨费率。1 月 15 日结算按下一交易日生效的 10% 一般持仓保证金计算，
日内仍为 9%。适配器将这些参数交给 Plus 原生费用及账户模块。仅有无日期的
bundle 费率时，入口报 `PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE`。

2 月接入窗口按上期所施行细则、节前保证金调整和节后交易恢复条件处理结算边界。
[燃料油期货业务细则](https://www.shfe.cn/regulation/exchangerules/productrules/202512/t20251231_829966.html)
· [保证金调整](https://www.shfe.com.cn/publicnotice/notice/202602/t20260203_830354.html)
· [春节期间交易安排](https://www.shfe.com.cn/publicnotice/notice/202602/t20260209_830421.html)
