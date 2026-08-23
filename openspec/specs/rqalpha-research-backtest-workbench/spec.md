# rqalpha-research-backtest-workbench Specification

## Purpose

定义一个与归一量化正式事实链隔离的 local-only、research-only RQAlpha Plus Web
回测工作台。它只运行 Git 跟踪且注册表启用的本机策略，只读外部米筐 Bundle，并只向
独立文件系统目录写入研究 artifact。本规范不表示 sidecar 已加载、已 release、已进入
Runtime 或已通过真实 RQAlpha smoke，也不定义未来基于 Canonical/MarketDataService 的正式
Candidate/OOS 回测体系。

## Requirements

### Requirement: 外部本机研究定位
工作台 SHALL 是 `quant-web -> 127.0.0.1:8011 local app -> 一次性 runner ->
外部 Bundle/独立 artifacts` 的本机工具。Local app MUST NOT 挂载到 `app.main`，MUST NOT
进入主 API proxy、FRPC/FRPS/Nginx、launchd 或 production Runtime，且 MUST NOT 创建 worker、
queue、scheduler、migration 或新的 persistence Application Domain。

所有 health、strategy 与 run 对外投影 MUST 持续标记 `research_only=true`、
`formal_evidence=false`、`promotion_eligible=false`。仓库中存在代码、自动化测试或本规范
MUST NOT 被解读为本机服务已加载、release、Runtime-ready、策略有效、可交易或可晋升。

#### Scenario: 主 API 保持无回测入口
- **WHEN** 主 FastAPI 应用或公网反向代理被启动
- **THEN** 其中不存在 RQAlpha 工作台路由，也不能启动本机 runner

#### Scenario: 研究运行不形成正式 evidence
- **WHEN** 一次 run 成功产生 summary、equity、trade count 与 report
- **THEN** 它仍只是外部 RQAlpha 研究 artifact，不进入 Candidate/OOS、正式 lineage 或晋升链

### Requirement: Git 外本机配置
Local app SHALL 只通过以下 Git 外变量取得运行配置：

- `GUIYI_BACKTEST_PYTHON_EXECUTABLE`：外部 Python 解释器绝对路径；
- `GUIYI_BACKTEST_BUNDLE_PATH`：只读 Bundle 绝对路径；
- `GUIYI_BACKTEST_RUNS_ROOT`：独立 run 根绝对路径；
- `GUIYI_BACKTEST_TIMEOUT_SECONDS`：正数秒，缺省为 `3600`；
- `GUIYI_BACKTEST_CORS_ORIGINS`：逗号分隔、去重且显式带端口的
  `http://localhost|127.0.0.1:<port>` origin；
- `VITE_BACKTEST_API_BASE_URL`：只允许精确的
  `http://localhost:8011/api/v1/backtests` 或
  `http://127.0.0.1:8011/api/v1/backtests`。

路径 MUST 在 resolve 后仍为绝对路径，Bundle 与 runs root MUST NOT 相同或互相包含。
模板 MUST 只保留占位值，MUST NOT 包含凭据或本机真实路径。

#### Scenario: 配置缺失或越界
- **WHEN** 必需路径不是绝对路径、Bundle 与 runs root 重叠、timeout 非正数或 CORS 包含非 loopback origin
- **THEN** Local app 以脱敏的 `BACKTEST_LOCAL_UNAVAILABLE` 形式 fail-closed，且不创建 run

### Requirement: 六路由与安全 HTTP 合同
独立 app SHALL 只在 `/api/v1/backtests` 下提供六个路由：

```text
GET  /health
GET  /strategies
POST /runs
GET  /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/artifacts/{kind}
```

`POST /runs` 成功 MUST 返回 HTTP 202；`GET /runs` 的 `limit` MUST 默认为 `20`且只
允许 `1..100`。Health 在 ready 或 degraded 时均 SHALL 返回 HTTP 200，并显式投影
`busy`、runner 版本/可用性、Bundle/runs-root/registry 可用性与单一脱敏错误。
所有未预期异常 MUST 收敛为稳定错误码，MUST NOT 返回 stack trace、license、环境变量、
路径细节或底层异常文本。

稳定 HTTP 错误码 SHALL 精确为：`BACKTEST_LOCAL_UNAVAILABLE`、`RUNNER_UNAVAILABLE`、
`BUNDLE_UNAVAILABLE`、`REGISTRY_INVALID`、`STRATEGY_NOT_FOUND`、
`INVALID_BACKTEST_REQUEST`、`BACKTEST_ALREADY_RUNNING`、`BACKTEST_RUN_NOT_FOUND`、
`BACKTEST_ARTIFACT_NOT_FOUND`。Local/runner/Bundle/registry unavailable MUST 映射为 HTTP 503，strategy/run/
artifact not found MUST 映射为 HTTP 404，invalid request MUST 映射为 HTTP 422，busy MUST 映射为
HTTP 409。请求携带 Origin 时必须与精确 allowlist 一致；无 Origin 的本机 CLI 读写 MAY 通过
同一 Host/JSON 边界。

#### Scenario: 忙状态仍可观察
- **WHEN** 存在活跃 run 且其余依赖可读
- **THEN** health 返回 `degraded + busy=true`，列表、详情、artifact 与轮询仍可读，新建 run 返回 HTTP 409

#### Scenario: 非 JSON mutation
- **WHEN** 任一 mutation 请求不是 `application/json`、Host 不是 loopback，或请求携带了不在精确 allowlist 的 Origin
- **THEN** 请求在调用 service 之前被拒绝且不产生副作用

### Requirement: 精确 DTO 与 Decimal 边界
Run request SHALL 只允许 `strategy_id`、ISO `start_date/end_date`、`frequency=1d|1m`、
`future_cash`、`matching_type=current_bar|next_bar`、`margin_multiplier`、
`futures_commission_multiplier`、`slippage_model=PriceRatioSlippage|TickSizeSlippage`、
`slippage` 和注册表声明的 `parameters`。`1d` MUST 只使用 `current_bar`；`1m` MAY 使用
`current_bar|next_bar`。资金与保证金倍数 MUST 大于零，佣金倍数与滑点 MUST 大于等于零。

所有金融/交易数值在 request、`run.json`、`result.json` 与 HTTP JSON 边界 MUST 保持 Decimal
字符串，不得用浮点数重算 RQAlpha 的 PnL、费用、撮合或净值。注册参数类型 SHALL
只有 `integer|decimal|boolean|enum`，并且必须通过已声明的默认值、范围或枚举选项校验。

Strategy DTO SHALL 只暴露 id/name/description、supported frequencies、defaults、typed parameter
descriptors 与三个研究标记，MUST NOT 暴露策略绝对路径。Run DTO SHALL 包含 run id、
策略 id/name/相对 entry/SHA-256、repository commit、Bundle path、RQAlpha/RQSDK/Python 版本、
requested/effective config、effective parameters、状态、开始/结束时间、exit code、failure code 与
三个研究标记。Detail DTO SHALL 额外包含 optional result 与最近 stdout/stderr tail；result
SHALL 只投影固定 summary allowlist `total_returns|annualized_returns|max_drawdown|sharpe|sortino|
volatility|total_value|cash`、`{date, unit_net_value}` equity、字符串 trade count
和 artifact availability。

#### Scenario: 非注册参数或 JSON number
- **WHEN** 请求包含未声明参数、超出范围的参数、额外字段或用 JSON number 传递金融数值
- **THEN** 系统返回 `INVALID_BACKTEST_REQUEST` 且不创建 run

### Requirement: 固定注册策略与不可扩大的执行面
工作台 SHALL 只列出并运行 Git 跟踪 JSON 注册表中 `enabled=true` 的策略。Strategy id
MUST 唯一，entry file MUST 是策略根内的相对 `.py` 文件，resolve 后的路径和 symlink
MUST NOT 逃逸策略根。工作台 MUST NOT 接受上传、在线代码、任意策略/文件路径、
shell 文本、原始 RQAlpha config 或未注册参数。策略参数 SHALL 只经 run 目录内
`strategy_params.json` 和固定 `GUIYI_BACKTEST_STRATEGY_PARAMS_FILE` 边界传递。

#### Scenario: disabled 或路径逃逸策略
- **WHEN** 请求指向 disabled、未注册、路径逃逸或 symlink 逃逸策略
- **THEN** 系统在启动子进程前 fail-closed

### Requirement: 全跨实例单任务状态机
Run 状态 SHALL 精确为 `running|succeeded|failed|timed_out|interrupted`；不存在
queued、retrying、cancelling 或 partial-success 状态，也不提供 queue、retry、cancel 或断点续跑。
终态 failure code SHALL 只使用 `RUNNER_UNAVAILABLE|STRATEGY_EXECUTION_FAILED|RUN_TIMED_OUT|
RUN_INTERRUPTED|RESULT_INCOMPLETE`；成功 run 必须完整产生必需 result/analyser artifacts。
一次启动 MUST 原子创建 `active.lock`，其内容精确为 `run_id`、`pid`、`started_at`。
Runs root 级串行化、exclusive creation 与 monitor ownership MUST 使同一 runs root 的多线程/多 Local
app 实例共同遵守“最多一个 running”。

每个 public operation MUST 先对 stale lock 进行 fail-closed reconcile：如果 monitor 仍持有 ownership 或
PID 仍存活，必须保持 busy 且不接管/结束该进程；仅当 PID 已不存在、lock/run identity
一致且 run 仍为 `running` 时，才将其原子转为 `interrupted + RUN_INTERRUPTED`并释放锁。
损坏、不可读或 identity 不一致的 lock/run MUST 保持锁并 fail-closed。Terminal record MUST
在释放匹配锁之前写入；不能证明已终止的子进程必须保持锁以防止重叠运行。

#### Scenario: 两个 Local app 同时启动
- **WHEN** 两个实例针对同一 runs root 同时提交 run
- **THEN** 只有一个实例可取得 monitor ownership，另一个返回 `BACKTEST_ALREADY_RUNNING`且不保留重叠子进程

#### Scenario: 子进程超时
- **WHEN** 已拥有的 runner 超过配置 timeout
- **THEN** 服务只终止该次启动所有的进程组，在宽限后必要时 kill，最终记录 `timed_out + RUN_TIMED_OUT`

### Requirement: 固定 runner 边界与强制配置
Runner SHALL 使用配置的绝对 Python 可执行文件、固定 `runner_entry.py`、固定 argv/cwd、
`shell=False` 和新进程组。子进程环境 SHALL 只继承运行所需的最小 allowlist，MUST NOT
继承 DB、Redis、RQData/RQDATAC、PushPlus、token、password、license 或其他项目凭据；stdout/stderr
MUST 在写盘前脱敏。

Runner entry MUST 经官方 `rqalpha.run_file(strategy_file_path, config)` 执行策略，且 MUST 二次
校验以下不可覆盖配置：

```text
base.data_bundle_path = configured absolute bundle path
base.auto_update_bundle = false
base.rqdatac_uri = disabled
base.accounts = FUTURE only
mod.sys_simulation.enabled = true
mod.sys_simulation.signal = false
mod.sys_transaction_cost.enabled = true
mod.sys_analyser.enabled = true
mod.sys_analyser.record = true
mod.sys_analyser.output_file = <run>/result.pkl
mod.sys_analyser.report_save_path = <run>/report
mod.sys_analyser.plot = true
mod.sys_analyser.plot_save_file = <run>/equity.png
mod.sys_progress.enabled = true
mod.sys_progress.show = false
mod.ams.enabled = false
mod.incremental.enabled = false
```

`strategy.py`、`strategy_params.json`、`run.json` 与 run root MUST 经打开的 descriptor 绑定且禁止
symlink/identity 替换；必需 analyser 输出不完整时，即使子进程 exit 0 也 MUST 转为
`failed + RESULT_INCOMPLETE`。

#### Scenario: 试图弱化安全配置
- **WHEN** 运行配置尝试启用 auto-update、rqdatac URI、signal、AMS、incremental、progress 展示或改写 analyser 路径
- **THEN** runner entry 在导入或运行策略前拒绝该配置

### Requirement: 固定 artifact 与结果投影
每个 run 的持久路径 SHALL 只包含合同文件：

```text
runs/<run_id>/
|-- run.json
|-- strategy.py
|-- strategy_params.json
|-- result.json
|-- result.pkl
|-- equity.png
|-- report/
|-- stdout.log
`-- stderr.log
```

`run.json` 与 `result.json` MUST 通过同一 runs-root 内的临时文件原子替换。
`result.pkl` MUST 只提供下载，Local app MUST NOT 反序列化它。`report_zip` MUST 在请求时
写入 OS anonymous temp，并在 response 结束后关闭/删除，MUST NOT 持久化到 run root。

Artifact kind SHALL 只允许 `report_zip|result_pickle|equity_png|stdout_log|stderr_log|run_json`，
不得将任意路径或文件名解释为 artifact。所有 run、log、artifact 与 report 子树读取
MUST 使用 no-follow/打开后 identity 边界；日志 tail MUST 最多 `200` 行且编码后最多
`65536` bytes。

#### Scenario: 请求非枚举 artifact kind
- **WHEN** HTTP 路径中的 kind 不在固定枚举
- **THEN** 请求以 `INVALID_BACKTEST_REQUEST` 在 service 之前被拒绝，并且不产生任意 artifact 路径

#### Scenario: 已登记 artifact 缺失或路径被替换
- **WHEN** 请求固定 kind 但对象缺失，或任一路径经 symlink 重定向
- **THEN** 系统返回 `BACKTEST_ARTIFACT_NOT_FOUND`并不读取 allowlist 外内容

### Requirement: 本机 Web 能力与远程 fail-closed
`/backtests` SHALL 只在浏览器 hostname 精确为 `localhost|127.0.0.1` 时探测精确
loopback sidecar URL。本机 sidecar 不可用时，菜单 SHALL 仍可见，页面 SHALL 提供本机配置/
启动/重试指引但不提供 mutation。仅有 `degraded + busy=true` 且其余依赖可读时，
页面 MAY 继续显示策略、运行列表/详情与轮询，但 MUST 禁用新建。

页面 SHALL 只包含受控新建表单、最近 run 列表和单 run 详情，并展示状态/耗时、
failure/exit code、固定 summary、服务端产生的 `equity.png`、requested/effective config、
stdout/stderr tail 与六种 allowlisted 下载。Running 详情 SHALL 以 `2000 ms` 非重叠轮询；
terminal、replacement、route 离开或 component unmount MUST 停止旧轮询，延迟响应 MUST NOT
覆盖更新的选择或 capability。

在 LAN、公网、别名、IPv6 loopback 或任何其他 hostname 上，Web MUST 隐藏菜单、直达页
fail-closed、发出零次 loopback 请求且不提供提交或 artifact 能力。

#### Scenario: 公网 Web 访问回测直达路由
- **WHEN** 浏览器在非 `localhost|127.0.0.1` hostname 打开 `/backtests`
- **THEN** 页面显示本机限制并且不请求 `127.0.0.1:8011`，不启动 run

### Requirement: 正式数据、Runtime 与订单零副作用
工作台、Local app、runner、Web 和 tests MUST NOT 读写归一量化 PostgreSQL、Redis、Canonical
Parquet、Market Catalog、MarketDataService、Alert、notification、Execution Review 或 Runtime。
它 MUST NOT 调用 `rqsdk update-data`、`download-data`、RQData writer 或任何 Bundle 更新/删除路径。

RQAlpha 内部 Order/Trade 只是 simulation-only 回测事实；工作台 MUST NOT 连接交易账户、
创建/提交真实订单、启用 AMS/signal mode 或修改项目 `auto_order=false` 边界。

#### Scenario: 策略内部产生模拟订单
- **WHEN** 已注册策略在 RQAlpha simulation 内产生 Order/Trade
- **THEN** 仅 RQAlpha report/result 记录该回测事实，归一量化不创建订单、AlertEvent、Execution Review 或 Runtime 事件

### Requirement: 自动化验证与真实 smoke Gate 分离
普通开发验证 SHALL 使用 fake runner、临时 runs root、factory-created local app 和浏览器
route interception，MUST NOT 启动 `127.0.0.1:8011`、导入本机真实 RQAlpha、访问真实 Bundle
或写入仓库外正式 run 根。

真实 RQAlpha smoke 是独立外部 Gate：执行前 MUST 取得当次、范围明确的单次执行意图，
并且该意图只授权紧随其后的一次精确 smoke 尝试。Smoke MUST 在启动前确认 Bundle
只读，记录关键 Bundle 文件前后 mtime/size，只运行已注册的短窗口示例策略，只写一个
独立研究 run 目录，并核对 report/pickle/PNG/result 完整与 DB/Redis/Canonical/Alert/
notification/Runtime/真实订单零副作用。Smoke 中 MUST NOT 执行 `rqsdk update-data`、
`download-data` 或任何 Bundle mutation。成功或失败都消耗本次意图；重试需要新的单次意图。

#### Scenario: 只通过 fake 自动化
- **WHEN** focused、local-app、full backend/Web/browser 测试均通过
- **THEN** 只能声明仓库行为验证通过，不能声明真实 RQAlpha、Bundle、本机加载、release 或 Runtime-ready 通过

#### Scenario: 无新单次意图的 smoke 或重试
- **WHEN** 操作者未对本次精确本机、Bundle、策略/窗口与结果根给出新的单次执行意图
- **THEN** 必须停在验证命令和只读检查之前，不得启动 sidecar 或真实 runner
