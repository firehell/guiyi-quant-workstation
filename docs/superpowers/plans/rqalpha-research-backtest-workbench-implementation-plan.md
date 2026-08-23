# RQAlpha Research Backtest Workbench Implementation Plan

更新时间：2026-08-23

状态：Implementation plan，等待 Codex 执行。

## 1. 目标

基于已批准的 `docs/RQALPHA_RESEARCH_BACKTEST.md`，实现一个 local-only、research-only 的 RQAlpha Plus Web 回测入口。

目标：

```
Web 配置
→ 固定注册策略
→ 本机 runner 执行 RQAlpha
→ 保存结果
→ Web 查看摘要和报告
```

不建设正式回测体系，不接入 Candidate/OOS/Runtime。

## 2. 开发原则

- 个人单机维护，优先简单可靠。
- 不创建微服务、队列、数据库表。
- 不恢复旧 Strategy/Signal/worker 体系。
- 不修改 Canonical 数据链路。
- 不连接 PostgreSQL、Redis、Alert、Execution Review、Runtime。
- 所有结果标记 research_only。

## 3. 实施阶段

## Phase 1: Contract 与目录

目标：建立最小代码边界。

实现：

- 增加 backtest local app 模块。
- 定义 registry JSON schema。
- 定义 run request、run state、result JSON。
- 增加 fake runner 测试基础。

验收：

- registry 可加载。
- 非法策略路径、disabled strategy、非法参数会失败。
- 不新增数据库 migration。

## Phase 2: Runner 与 Artifact

目标：能够安全启动一次 RQAlpha。

实现：

- 固定 runner 入口。
- 使用官方 file strategy 执行方式。
- shell=False。
- 固定 Bundle path 配置。
- 强制关闭 auto update、AMS 等外部副作用。
- 写入独立 run directory。

保存：

```
runs/<run_id>/
├── run.json
├── strategy.py
├── strategy_params.json
├── result.json
├── result.pkl
├── equity.png
├── report/
└── logs/
```

验收：

- fake runner 完成完整状态流转。
- 失败任务保留日志。
- Bundle 不发生写入。

## Phase 3: Local API

目标：提供本机调用能力。

实现：

接口：

```
GET  /api/v1/backtests/health
GET  /api/v1/backtests/strategies
POST /api/v1/backtests/runs
GET  /api/v1/backtests/runs
GET  /api/v1/backtests/runs/{id}
GET  /api/v1/backtests/runs/{id}/artifacts/{kind}
```

约束：

- 只监听 localhost。
- 不挂载公网 API。
- 同时最多一个任务。
- 不排队、不重试。

验收：

- 第二个运行请求正确返回 busy。
- artifact 下载只能访问 allowlist。

## Phase 4: Web 页面

目标：提供最小可用 UI。

实现：

页面：

```
/backtests
```

包含：

- 策略选择。
- 参数表单。
- 日期和资金配置。
- 最近运行列表。
- 运行详情。
- summary 指标。
- 米筐收益图。
- 报告下载。

不实现：

- 参数优化。
- 多策略比较。
- 成交持仓分析页面。
- Dashboard。

## Phase 5: Validation

测试：

- Backend unit tests。
- Registry validation tests。
- Runner fake E2E。
- Web unit tests。
- Browser smoke。
- secret scan。
- diff check。

真实 RQAlpha smoke 单独执行：

- 只读确认 Bundle。
- 使用短周期测试策略。
- 检查结果目录。
- 检查无项目副作用。

## 4. 禁止范围

禁止：

- 用户上传 Python。
- 在线编辑策略。
- 任意文件路径执行。
- shell command 注入。
- 自动下载 Bundle。
- 修改 Canonical。
- 接入通知。
- 接入实盘。
- 自动晋升策略。

## 5. Codex 验收输出要求

完成后输出：

- 修改文件列表。
- 测试结果。
- 本机配置要求。
- 未完成项。
- 风险说明。
- 是否触及 main/tag/runtime。

不得声明正式回测系统完成，只能声明 research backtest workbench 完成。