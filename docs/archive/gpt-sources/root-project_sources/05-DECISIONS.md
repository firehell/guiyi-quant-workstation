# Decisions

更新时间：2026-07-14

事实来源：`DECISIONS.md`

当前状态：current，后续部分仍需决策。

## 当前有效决策

- 产品是本地单用户研究工作站，不是 SaaS 或自动交易系统。
- 数据主链路是 RQData/local parquet -> DuckDB -> PostgreSQL -> Web/回测/信号。
- active 入口只允许 `rqdata` / `local_parquet` + `primary` + `quality_status != failed`。
- 严格研究默认 `quality_status=passed`。
- live 和 historical active 分层，不自动混入可信回测。
- 企业微信只做观察提醒。
- GPT Sources 来自仓库文件，不靠聊天复述。

## 待决策

- `metadata_gap=1853` 处理策略。
- pre-2020 周线 34 品种缺口处理策略。
- actual contract 缺口处理策略。
- `research_only` schema/API 语义拆分。
- Web trust audit 展示优先级。

