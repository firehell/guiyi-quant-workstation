# 回测中心 · RQAlpha Plus 历史研究工作台

## Why

从策略中心选定一个公式版本后，用户需要能用已下载的米筐数据运行回测，查清一笔成交的来由，并用相同条件比较参数和样本外表现。已有牛哇试验提供了单品种撮合、费用对账和按 Run 查询结果的基础，尚不能承担这条完整流程。

## What Changes

- 由 RQAlpha Plus 读取自有数据，执行事件、委托、撮合、费用、持仓、结算与原生分析。归一维护策略适配、配置快照、任务历史、结果查询与验证。中心只保存复算所需的数据身份及研究产物。
- 建设五个用户入口：工作台、配置、任务、结果分析、参数实验与验证。第一条接入路径选牛哇趋势；其余五个目录项的资格逐项说明。
- 将现有 V2 提案所说的“独立研究域维护数据”具体落实为 Plus 自有数据与读取方式。在本中心新 Run 的范围内，数据更新仍归米筐工具；归一不建设研究行情仓库，也不接 Market 归档触发器。

## Capabilities

新增提案能力 `backtest-center`。策略目录和公式仍归各自领域，模拟账户独立运行。既有隔离试验保留来源、只读入口和原研究口径。本次仅提交设计，B1–B4 的实施与验收见[任务表](tasks.md)。

## Impact

实施将涉及独立引擎环境、研究结果存储、工作站研究 API 和桌面 Web。现有 P3/P4 的输入、系列身份与读面在迁移前按原合同维护。历史数据中心、生产库、Runtime、Broker 和策略晋升均在本次变更范围之外。

[设计与复用边界](design.md) · [可验收需求](specs/backtest-center/spec.md) · [V2 研究合同](../guiyi-v2-rearchitecture/specs/guiyi-v2-research/spec.md) · [Market 边界](../guiyi-v2-market-foundation/design.md) · [策略中心](../../specs/strategy-center/spec.md)
