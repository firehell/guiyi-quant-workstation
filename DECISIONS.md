# 架构决策记录

更新时间：2026-07-14

## 当前有效决策

| 决策 | 当前结论 | 影响 |
|---|---|---|
| 产品边界 | 本地、单用户、国内期货研究工作站 | 不做 SaaS、多用户、自动交易 |
| 数据主链路 | RQData / local standard parquet -> DuckDB -> PostgreSQL -> Web/回测/信号 | active 入口只允许 `rqdata` / `local_parquet` + `primary` + `quality_status != failed` |
| 严格研究入口 | 默认 `quality_status=passed` | warning 必须显式 opt-in 或阻断 |
| 派生周期 | 5m/15m/30m/60m/1d 默认从 passed 1m 本地聚合 | 不把 RQData direct 多分钟作为新正式主链路 |
| 数据最终状态 | 当前为 `DATA_LAYER_PARTIAL` | `DATA-PART-TARGET-CLOSURE` 仅是先前数据部分目标收口 |
| 指标内核 | EMA validated；MACD/ATR draft；火天大有 observation-only | XMA/火天大有不得进入回测、live evaluator、`signal_events` 或提醒链路 |
| 回测口径 | vn.py CTA + 自定义 adapter/runner/result converter/trust audit | `next_bar_open`、成本、乘数、tick、lineage 必须可追溯 |
| 信号提醒 | 企业微信只做观察提醒 | 不自动下单，不生成订单草稿 |
| live 数据 | live tables 与 historical active 分层 | live 不自动登记为可信 historical active |
| 运行部署 | 本地 Mac / Docker / launchd；公网只读入口为腾讯云 Nginx + FRP 模板 | 配置通过不等于真实远端验收通过 |
| 工作站协作 | Browser GPT 做规划/审查，Codex 做仓库执行，Cursor/Git 做人工 checkpoint | GPT Sources 必须来自仓库文件，不靠聊天复述 |

## 当前重要取舍

- `DATA_LAYER_PARTIAL` 优先于乐观 ready 叙述；未完成 Gate 必须保留。
- 历史验收文档保持历史数字，不改写成当前状态。
- `docs/gpt/project_sources/` 是浏览器 GPT 投喂包，不替代 canonical 文档。
- 文档任务中若发现代码/数据不一致，只记录后续任务，不顺手修代码或写数据。
- 所有敏感凭据只允许通过本机环境或受控系统配置，不写入仓库。

## 后续需决策

- `metadata_gap=1853` 的 manifest/DB 对齐策略。
- pre-2020 周线 34 品种是补数据、N/A 还是 RQData 下限说明。
- actual contract 缺口是补 bars、N/A 还是等待 mapping 修复。
- `research_only` schema/API 语义是否拆分。
- Web trust audit 专项展示和公共 chunk 拆包优先级。

