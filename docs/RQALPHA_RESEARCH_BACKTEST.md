# RQAlpha 研究型 Web 回测工作台设计

更新时间：2026-08-23
状态：设计已收敛，尚未授权实现、真实 RQAlpha 运行或本机服务加载

## 1. Review 结论

本项目是本地、单用户、个人维护的国内期货研究工作站。回测工作台第一版只需要解决：

```text
选择已注册的 RQAlpha 原生策略
→ 在 Web 填写少量受控参数
→ 使用现有米筐 Bundle 运行一次回测
→ 保存并查看米筐结果
```

上一版方案方向正确，但包含明显的个人项目过度设计：独立新服务目录、过多 API、重复结果格式、完整 artifact 哈希、Bundle 递归指纹、交互式权益/成交/持仓页面、启动恢复协议、launchd、完整 RQAlpha 参数镜像和多份 canonical 更新。

最终设计删除这些内容，只保留一个本机 sidecar API、一个单次 runner、一个 JSON 注册表、一个结果目录和一个 Web 页面。

单独的 loopback sidecar **不是过度设计**。当前主 API 可能经 FRPC/Nginx 暴露；把“启动本机 Python 策略进程”的接口挂到主 API，会形成远程代码执行面。sidecar 是避免该风险的最小隔离边界，但它仍复用现有 `services/quant-api` 代码库，不创建微服务仓库、队列、数据库或第二套业务平台。

## 2. 产品定位

RQAlpha 工作台是一个 **local-only、research-only 的外部回测工具**：

- 只运行 Git 跟踪、固定注册的 RQAlpha Plus 原生策略；
- 只读米筐本地 Bundle；
- 只把结果写入独立研究 artifact 目录；
- 结果不进入归一量化 Canonical、Market Catalog、Redis、Alert、Execution Review、Runtime、Candidate/OOS 或晋升链；
- RQAlpha 内部产生的 Order/Trade 只是模拟回测事实，不连接账户、不提交真实订单；
- 不向 owner 或三位朋友发送通知；
- `auto_order=false` 对任何真实订单路径继续有效。

第一版不适配苏冰、N Structure、JDJ、HTDY 或主力照妖镜，不建立 Strategy Adapter，也不校验现有 Research 与 RQAlpha 策略的公式一致性。

## 3. 第一版范围

### 3.1 包含

- 固定策略注册表；
- 本机 Web 新建回测；
- 单任务后台执行；
- 最近运行记录；
- 运行状态、摘要指标、米筐收益图；
- 原始 report、pickle 和日志下载；
- 失败、超时和中断状态；
- fake runner 自动化测试；
- 一次受控的本机真实 RQAlpha smoke。

### 3.2 不包含

- 策略上传、在线代码编辑或任意本机文件选择；
- 参数扫描、优化器、批量任务或队列；
- 多策略组合、Walk-forward、正式 OOS 或 Candidate 晋升；
- 结果比较页、交互式成交/持仓分析页；
- PostgreSQL、Redis、migration 或新的 Application Domain 表；
- 自动下载、更新或删除米筐 Bundle；
- 自动清理历史结果；
- 任务取消、重试或断点续跑；
- launchd 常驻服务；
- 公网访问；
- 通知、模拟盘、实盘或订单接口。

## 4. 精简架构

```text
本机浏览器中的 quant-web
        │
        │ http://127.0.0.1:8011
        ▼
services/quant-api 内的 backtest local app
        │
        │ 固定解释器 + 固定 runner + shell=False
        ▼
一次性 RQAlpha runner 子进程
        │
        ├── 只读米筐 Bundle
        └── 只写独立 run 目录
```

约束：

- Local app 不挂载到 `app.main`；
- 只监听 `127.0.0.1`；
- 不进入 FRPC、FRPS、Nginx 或 production Runtime；
- 不创建新的仓库级 service/package；
- runner 默认使用配置的绝对 Python 路径；若当前解释器通过 probe，也允许复用当前解释器；
- 不硬编码 Python 版本，实际支持范围由本机架构和已安装 RQSDK probe 决定。

推荐代码边界：

```text
services/quant-api/app/backtest/
├── local_app.py
├── api.py
├── registry.py
├── service.py
├── artifact_store.py
├── runner_entry.py
├── strategy_params.py
└── strategies/
    ├── registry.json
    └── example_future_smoke_v1.py
```

不新增 `services/rqalpha-runner`、worker、dispatcher 或 scheduler。

## 5. 固定策略注册表

注册表使用一个 Git 跟踪的 JSON 文件，不引入 YAML、数据库或管理页面。

最小字段：

```json
{
  "schema_version": 1,
  "strategies": [
    {
      "id": "example_future_smoke_v1",
      "name": "期货回测链路示例",
      "description": "只用于验证本机 RQAlpha 回测链路",
      "enabled": true,
      "entry_file": "example_future_smoke_v1.py",
      "supported_frequencies": ["1d", "1m"],
      "defaults": {
        "future_cash": "1000000",
        "matching_type": "current_bar",
        "margin_multiplier": "1",
        "futures_commission_multiplier": "1",
        "slippage_model": "PriceRatioSlippage",
        "slippage": "0"
      },
      "parameters": []
    }
  ]
}
```

加载时必须验证：

- `id` 唯一；
- `entry_file` 是策略目录内的相对 `.py` 文件；
- resolve 后不得逃逸策略根目录；
- disabled 策略不能运行；
- frequency、matching type、参数类型、范围和默认值合法；
- HTTP 请求不得增加注册表未声明的参数。

策略参数通过一个运行目录内的 JSON 文件传递，策略只经 `strategy_params.py` 读取；不使用 `run_code`，不拼接 Python 源码。

## 6. Web 可配置项

第一版不镜像 RQAlpha 全量配置，只暴露真正影响期货回测结果的最小集合：

- 策略；
- 开始日期；
- 结束日期；
- frequency：`1d | 1m`；
- 期货初始资金；
- matching type：按 frequency 限制；
- margin multiplier；
- futures commission multiplier；
- slippage model：`PriceRatioSlippage | TickSizeSlippage`；
- slippage；
- 注册表声明的策略参数。

第一版不支持 tick、股票账户、混合账户、Benchmark、自定义手续费表、管理费、初始化仓位或原始 JSON 配置编辑器。

以下配置由 runner 强制设置，Web 不得覆盖：

```text
base.data_bundle_path = configured absolute bundle path
base.auto_update_bundle = false
base.rqdatac_uri = disabled
mod.sys_simulation.signal = false
mod.sys_analyser.record = true
mod.sys_analyser.output_file = <run_dir>/result.pkl
mod.sys_analyser.report_save_path = <run_dir>/report
mod.sys_analyser.plot = true
mod.sys_analyser.plot_save_file = <run_dir>/equity.png
mod.sys_progress.show = false
mod.ams.enabled = false
incremental backtest = disabled / not enabled
```

RQAlpha 调用固定使用官方 `run_file(strategy_file_path, config)` 入口。显式 config 优先于策略内 config，便于强制本地数据路径和关闭外部副作用。

## 7. 数据路径

用户提供的米筐目录为：

```text
/Volumes/扩展盘/.rqalpha-plus
```

RQAlpha 默认 Bundle 通常位于其下的 `bundle` 目录。实现前必须只读 probe 实际目录，候选默认值为：

```text
/Volumes/扩展盘/.rqalpha-plus/bundle
```

不得根据目录名直接猜测成功，也不得运行 `rqsdk update-data`、`download-data`、自动更新或任何删除命令。

结果根推荐：

```text
/Volumes/扩展盘/guiyi-rqalpha-backtests/runs
```

Bundle 与结果根必须互不包含。

## 8. 执行模型

### 8.1 单任务，无队列

- `POST /runs` 启动一个后台子进程并立即返回 `run_id`；
- 同一时间最多一个 run；
- 已有 run 时返回 HTTP 409；
- 不排队、不自动重试、不并行；
- 使用固定最大运行时间，超时后终止子进程。

### 8.2 状态

第一版只保留：

```text
running
succeeded
failed
timed_out
interrupted
```

不引入 `created / starting / queued / partial_success / cancelling / retrying`。

### 8.3 最小锁与恢复

- 使用结果根下单一 `active.lock`；
- 创建 run 时原子取得锁；
- 锁只保存 `run_id + pid + started_at`；
- Local app 重启后，若原 run 标为 running 且 PID 已不存在，则标记 `interrupted` 并释放锁；
- 不实现 runner hash、命令行身份验证、复杂进程接管或恢复执行。

## 9. 最小结果合同

每次运行只保存：

```text
runs/<run_id>/
├── run.json
├── strategy.py
├── strategy_params.json
├── result.json
├── result.pkl
├── equity.png
├── report/
├── stdout.log
└── stderr.log
```

### 9.1 `run.json`

一个文件合并保存请求、实际配置、状态和最小 lineage，并通过临时文件 + 原子替换更新：

- `run_id`；
- `research_only=true`；
- `formal_evidence=false`；
- `promotion_eligible=false`；
- strategy id/name/SHA-256；
- repository commit；
- Bundle 绝对路径；
- RQAlpha/RQSDK/Python 版本；
- requested/effective config；
- started/finished time；
- status、exit code、failure code。

不做：

- Bundle 递归 metadata fingerprint；
- 每个 artifact 的 SHA 清单；
- registry/runner hash；
- Git dirty 文件清单；
- receipt、签名或审批包。

策略快照和 strategy SHA 已足以满足方案 A 的个人研究追溯。Bundle 数据身份只记录米筐能够直接提供的版本/元数据；取不到时明确为 `unknown`，不得伪装成 Canonical identity。

### 9.2 `result.json`

runner 只投影 Web 需要的：

- summary 指标；
- equity 序列；
- trade count；
- artifact 可用性。

交易相关数值在 JSON 边界转成十进制字符串；工作台不重新计算 RQAlpha 的 PnL、费用或撮合结果。

成交、持仓和账户明细第一版只通过米筐 `report/` 下载，不建设专门页面和分页 API。`result.pkl` 仅下载，不由 Local app 反序列化。

## 10. Local API

统一前缀：`/api/v1/backtests`

仅保留六个 endpoint：

```text
GET  /health
GET  /strategies
POST /runs
GET  /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/artifacts/{kind}
```

`GET /runs/{run_id}` 同时返回状态、summary、equity、最近日志尾部和允许下载的 artifact 列表。

artifact `kind` 使用固定枚举，例如：

```text
report_zip
result_pickle
equity_png
stdout_log
stderr_log
run_json
```

不得接受任意路径。

稳定错误码只保留：

```text
BACKTEST_LOCAL_UNAVAILABLE
RUNNER_UNAVAILABLE
BUNDLE_UNAVAILABLE
REGISTRY_INVALID
STRATEGY_NOT_FOUND
INVALID_BACKTEST_REQUEST
BACKTEST_ALREADY_RUNNING
BACKTEST_RUN_NOT_FOUND
BACKTEST_ARTIFACT_NOT_FOUND
```

## 11. Web

现有 quant-web 增加一个本机能力页：`/backtests`。

页面只包含：

1. 新建回测表单；
2. 最近运行列表；
3. 单次运行详情。

详情展示：

- 状态和耗时；
- 少量 summary 指标卡；
- RQAlpha 生成的 `equity.png`；
- 请求配置与实际配置；
- stdout/stderr 尾部；
- report、pickle、PNG 和日志下载。

第一版不建设交互式权益图、成交表、持仓表、账户表、对比页或自定义 Dashboard。

Web 通过 `http://127.0.0.1:8011` 探测 local app：

- health 成功时显示菜单；
- 不可用时隐藏菜单或显示“仅本机可用”；
- Local app 只允许明确配置的本地 Web origin；
- 公网 Web origin 不在 CORS allowlist，因此不能启动本机回测。

## 12. 安全和副作用边界

必须保留的安全措施：

- 固定策略注册表；
- 不上传、不粘贴、不选择任意策略路径；
- Python executable 是 Git 外配置的绝对路径；
- subprocess 使用参数数组，`shell=False`；
- 策略、Bundle、结果和 artifact 路径均 resolve 后检查允许根；
- runner 只接收最小环境变量，不继承数据库、Redis、PushPlus 或其他项目凭据；
- Local app 只绑定 loopback；
- 不挂载到主 API；
- 不调用 RQData 更新、Canonical writer、PostgreSQL、Redis、Alert、Execution Review、Runtime 或 PushPlus；
- 强制关闭 auto bundle update、AMS、incremental 和 signal mode；
- 错误响应不返回 stack trace、license 或完整环境变量。

固定注册表是受信任代码清单，不是 Python 沙箱。第一版不建设容器、虚拟机、Seccomp、多用户权限或远程认证。

## 13. 失败处理

- 扩展盘或 Bundle 不可用：health degraded，禁止启动；
- RQAlpha import/license probe 失败：`RUNNER_UNAVAILABLE`；
- 注册表异常：全部策略不可运行；
- 策略抛错：`failed`，保留脱敏日志；
- 超时：`timed_out`；
- Local app 重启且旧 PID 不存在：`interrupted`；
- 必需的 `result.json`、`run.json` 或 analyser 输出缺失：`failed`；
- 第二个 run：HTTP 409，不排队；
- 页面刷新：按 `run_id` 重新读取状态。

第一版不引入 partial success。必要结果不完整即失败，但已有原始日志仍允许下载。

## 14. 测试与验收

### 14.1 自动化

使用 fake runner 覆盖：

- registry schema、重复 id、disabled、路径逃逸；
- 参数类型、范围、frequency/matching compatibility；
- Web 不可覆盖强制安全配置；
- bundle/result 路径边界；
- `shell=False` 与固定 executable；
- 单任务冲突；
- succeeded/failed/timed_out/interrupted；
- Local app 重启后的最小 stale lock 处理；
- artifact allowlist；
- 日志脱敏；
- Web 表单、轮询、结果展示和 local unavailable；
- 一个 Playwright 本机 fake-runner 主流程；
- 定向 backend/Web tests、Ruff、Mypy、Web build、secret scan 和 `git diff --check`。

不要求为第一版构建通用回测测试框架、全量 schema generator 或第二套 CI 流程。

### 14.2 本机真实 smoke

实现和 Review 通过后，另行取得一次明确执行意图，运行一个短窗口示例策略并核对：

- 实际 Bundle 路径只读可用；
- `auto_update_bundle=false`；
- Bundle 关键文件前后 mtime/size 未变化；
- 只生成一个结果目录；
- report、pickle、PNG 和 `result.json` 完整；
- 没有 DB、Redis、Canonical、Alert、通知、Runtime 或外部订单副作用。

真实 smoke 写入仓库外结果目录，不能由代码合入、测试或既有 Runtime 授权推导。

## 15. Canonical closeout

设计文档提交时不提前修改 canonical。实现行为和测试通过后，只更新确有冲突的长期文件：

- `PROJECT_SOURCE.md`：允许 local-only、research-only RQAlpha workbench；正式 Historical/Candidate 仍只认 Canonical；
- `AGENTS.md`：区分外部研究回测和未来正式验证回测；允许 RQAlpha 内部模拟 Order/Trade，但禁止真实订单；
- `docs/ARCHITECTURE.md`：增加 local Web → local app → runner → Bundle/artifacts 依赖；
- `DECISIONS.md`：记录外部探索引擎不进入正式事实链；
- `TESTING.md`：增加 fake runner 和本机 smoke 命令；
- `.env.example`：只增加无秘密的路径占位。

第一版不要求修改 `docs/DEVELOPMENT.md`、`README.md` 或 `STATUS.md`。只有未来形成明确 release candidate、release 或本机加载状态时，才按对应职责单独更新。

实现 closeout 后，将本设计中的稳定边界收敛进 canonical，并删除本文件；历史设计通过 Git history 追溯，避免长期保留 active task 文档。

## 16. 实施组织

这是一个实现任务，不拆成多套子系统、多个 Issue 或多条并行分支。内部按以下顺序完成：

```text
registry + fake runner
→ artifact store + local app
→ Web
→ integration tests
→ canonical closeout
→ independent Review
→ develop
→ 单独真实 smoke Gate
```

### Codex 调度建议

- 任务车道：Lane 3；原因是撮合、滑点、佣金和保证金配置会改变回测语义
- 执行入口：Codex App
- 推荐模型：Sol
- 推理强度：高
- 会话：新开实现会话；完成后新开独立 Review 会话
- Plan：Plan-only，人工批准后 Plan-then-execute
- 工作区：从执行时最新 `develop` 创建一个 task worktree / branch
- 人工 Gate：Plan 批准、独立 Review、真实 RQAlpha smoke 批准

只需要一个 task branch 和一个 PR。不得发布 `main`、创建 tag、切换 production Runtime、加载 launchd、更新 Bundle 或运行真实策略，除非分别取得相应明确执行意图。

## 17. 最终 Gate

本设计通过个人项目精简 Review：

```text
允许进入 implementation plan
不授权直接实现
不授权真实 RQAlpha 运行
不授权本机服务加载
不授权 release/main/tag/Runtime
```
