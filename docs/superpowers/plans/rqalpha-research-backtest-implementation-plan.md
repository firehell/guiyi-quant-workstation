# RQAlpha Research Backtest Workbench Implementation Plan

更新时间：2026-08-23

状态：Implementation plan，尚未授权实现

关联设计：`docs/RQALPHA_RESEARCH_BACKTEST.md`

## 1. Implementation Goal

实现一个个人本地研究工具：

```text
quant-web 本机页面
→ local backtest API
→ 一次性 RQAlpha runner
→ 米筐本地 Bundle
→ 保存研究结果
```

目标不是建设通用回测平台，而是解决：

- 不需要手敲 rqalpha 命令；
- 通过 Web 配置一次回测；
- 保存配置和结果；
- 方便后续人工研究。

## 2. Hard Boundary

必须保持：

- research_only；
- 不进入 Canonical Parquet；
- 不进入 MarketDataService；
- 不进入 PostgreSQL/Redis；
- 不接 Alert/Notification；
- 不接 Runtime；
- 不接 Execution Review；
- 不接订单路径；
- 不恢复旧 Strategy HTTP/worker/queue。

禁止：

- 用户上传 Python 策略；
- Web 在线执行代码；
- 任意本机路径执行；
- 任意 shell 参数；
- 自动下载或更新米筐数据；
- 自动晋升策略。

## 3. Development Phases

## Phase 1: Local Backtest Contract

范围：

- 新增 backtest 模块目录；
- 定义 registry schema；
- 定义 run.json/result.json；
- 定义 API DTO；
- 定义 artifact store 接口。

验收：

- schema 可校验；
- fake run 可以生成完整结果目录；
- 不依赖 RQAlpha 环境。

## Phase 2: Strategy Registry

实现：

- Git 跟踪 JSON 注册表；
- enabled strategy 校验；
- entry_file 路径限制；
- 参数 schema 校验。

验收：

- disabled 策略不可运行；
- 非注册参数拒绝；
- 路径逃逸拒绝。

## Phase 3: RQAlpha Runner

实现：

- 固定 runner 入口；
- 使用官方 run_file；
- 固定 config 覆盖；
- Bundle 路径 probe；
- result/report 输出。

必须验证：

- data_bundle_path 只读可用；
- auto_update_bundle=false；
- 不触发外部下载；
- 不连接项目 DB/Redis。

## Phase 4: Local API

实现最小接口：

- GET /health
- GET /strategies
- POST /runs
- GET /runs
- GET /runs/{id}
- GET /runs/{id}/artifacts/{kind}

实现：

- 单任务锁；
- 后台 subprocess；
- 超时处理；
- 状态更新。

不实现：

- queue；
- retry；
- cancel；
- scheduler。

## Phase 5: Web Surface

实现：

- /backtests 页面；
- 策略选择；
- 参数表单；
- 最近运行列表；
- 结果详情。

展示：

- summary；
- equity.png；
- 配置；
- 日志；
- report 下载。

不实现：

- 复杂交易分析页；
- 参数优化页；
- 结果排名。

## Phase 6: Testing

自动化覆盖：

- registry validation；
- API contract；
- path safety；
- single-run lock；
- fake runner E2E；
- Web smoke。

真实本机 smoke 单独执行：

- probe RQAlpha 环境；
- probe Bundle；
- 运行短窗口示例策略；
- 检查结果。

真实 smoke 不代表策略有效性，不进入 OOS 或晋升。

## 4. Recommended Codex Execution Order

1. 先实现 registry + contract + fake runner；
2. 再实现 local API；
3. 再实现 Web；
4. 最后接真实 RQAlpha；
5. 最后做本机 smoke。

不要一开始直接接 RQAlpha，避免环境问题和业务代码耦合。

## 5. Review Checklist

Codex 完成后重点检查：

- 是否创建了新的微服务或队列；
- 是否修改 Canonical/MarketDataService；
- 是否把 research result 描述成正式 evidence；
- 是否扩大 API 到公网；
- 是否允许任意 Python 执行；
- 是否保存了足够复现信息；
- 是否保持单用户精简架构。

## 6. Completion Gate

完成后只能声明：

- 允许本机研究使用；
- 允许保存和查看 RQAlpha 回测结果。

不能声明：

- 策略有效；
- 可交易；
- OOS 通过；
- Candidate 晋升；
- Runtime 可用。
