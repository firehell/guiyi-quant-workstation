# Unified Reference Trading P5：只读查询与页面接入开发计划

日期：2026-09-23。owner 已要求设计 P5 并安排新的 Sol medium 任务实施。
核对基线：develop `b7a080926962816c5ab2aff34357a69a7ce236b6`，主工作树开始时干净。
P3/P4 已集成的完成状态见 `STATUS.md`；本计划不重做 P0–P4，也不授权生产迁移/bootstrap、worker、Runtime、通知或发布。

**Goal:** 牛哇与苏冰参考交易通过持久化结果查询；刷新、分页和统计不再回放完整策略，页面既有信号、质量边界和指标展示不丢失。
**Architecture:** 接续现有六表与 P4 historical service，增加只读 query/API、必要的物化展示数据、公共前端查询状态；策略窗口统计保持独立政策。
**Tech Stack:** 现有 Python/Decimal、SQLAlchemy/PostgreSQL、FastAPI、Vue/TypeScript。
**Spec:** `openspec/specs/reference-trading/spec.md`、`docs/superpowers/specs/2026-09-19-unified-reference-trading-design.md` §11。

实施方式：在新任务独立 worktree 开发，先同步最新 develop；采用 executing-plans，涉及查询时序/仓储更改做独立 Review。
若工具从项目默认分支创建 worktree，先核对干净状态并合入 origin/develop，确认 P4 提交已包含再写代码。

## 1. 当前事实和必须补齐的差异

1. `app/reference_trading/repository.py` 已有 snapshot、read_actions/read_trades/read_marks、cutoff 和动作观察时间过滤；不可另造第二套身份解析。
2. 当前 read_actions 会加载批次的 projected_action_pks，再取完整动作；read_trades 会加载交易所有版本并在 Python 分组，且逐交易读取 mark。
   这是已有内部读法，不符合 HTTP 大历史分页的资源目标。P5 必须增加有界数据库查询，避免全量 `.all()` 和 N+1。
3. `app/reference_trading/service.py` 的苏冰 driver 丢弃 `_indicator`，且 SAME_DIRECTION 不生成交易动作；不能把已存 actions 当成完整旧 signals/indicators。
4. 苏冰旧 reference 响应还承载 D1 quality_chart_bars、coverage_intervals、quality_interruptions，页面主图依赖这些字段。
5. 牛哇 reference section 与其他 section 共享输入身份/快照检查，不能孤立换 endpoint 导致图表和交易错位。
6. 0047 仍未执行生产迁移/构建；新 reader 必须处理 schema/data 未就绪，不能因为代码发布就默认替换正式读取。

## 2. 冻结范围与默认决策

- 本次读取 `historical_replay` 的牛哇三策略、苏冰四周期；实际开放继续受当前 product capability 控制。
- forward/HTDY 不在 P5 启用；请求不支持的模式明确返回 MODE_NOT_AVAILABLE，不以空交易假装正常。
- `stream.enabled` 是持续计算开关，不是阅读权限。已发布历史 revision 即使 enabled=false 也应可读。
- 只读取 active 或仍有效的历史 snapshot；candidate 永不可见。invalid 立即拒绝；superseded 是否可读遵守已有仓储合同。
- 不新增账户、收益合并、订单、通知或后台定时任务；不扩大任何品种周期的生产范围。
- 允许修补 P4 输出以物化 P5 必需展示字段，允许有界 SQL 查询改进；不改公式、价格、配对、收益或历史身份。
- 保持六表，优先使用版本化批次 source_evidence 的展示 envelope；若必须改 schema，先说明具体证据和取舍，不静默增加迁移。

## 3. 查询合同

新增以下 GET，统一 `/api/v1/reference-trading` 前缀：

| 路径 | 输入 | 输出与行为 |
|---|---|---|
| `/capabilities` | 无 | 代码支持、页面开放、可读模式分开；不扫描行情、不访问 provider |
| `/streams` | strategy/product/frequency/mode | 有界列举与精确版本身份；不随机选择多个版本中“最新”的流 |
| `/streams/{id}/trades` | since/through/cutoff、limit、cursor、snapshot | 倒序稳定 keyset 分页，首屏返回 snapshot 与可选同快照 summary |
| `/streams/{id}/signals` | 同上及可见窗口 | 完整已保存展示信号；不能用交易动作遗漏 SAME_DIRECTION |
| `/streams/{id}/summary` | 固定窗口、snapshot | 全窗口统计，独立于分页，不调用策略回放 |

limit 1..200，默认 50；symbols、frequency、重复/未知参数和无时区 cutoff 严格验证。
`since/through` 使用交易日，不以 UTC 日期截断。默认窗口沿策略现合同，不统一改成相同天数。
新接口只接收服务端登记且 capability 相符的 stream；无版本参数的解析使用当前已接受产品 identity，歧义返回明确错误。

snapshot 绑定 stream/revision/seq、cutoff、完整统计窗口、统计政策版本及数据依赖身份；cursor 另绑定资源类型、排序键和窗口。
采用严格、长度受限的结构化 opaque 编码；编码不是权限机制，所有字段及资源归属服务端验证。
不使用进程内 token 表，否则重启会丢快照；不因分页而读取当前最新 seq。
若需要防篡改签名，必须复用已有合适机制，不能擅自增加生产凭据；严格验证合法快照比仅信任签名更重要。

Decimal 原样序列化为字符串；不得转 float 后回写。交易 ID 保留策略公开原 ID及 stream namespace。
响应元信息包含 computed_through、实际 coverage、revision/seq、模式、freshness 与统计政策。
expected_through 只能从权威完成条件证明；现阶段无法证明时返回 null/unknown，不能用墙钟推断 READY。
截至过去的查询不得看到未来 exit/mark；保留仓储已有 forward 双时间过滤规则，但不开放 forward 产品。

错误：参数错误 422；未知 stream 404；snapshot/cursor 冲突 409；schema/依赖不可用 503。
NOT_BUILT、WARMING、PARTIAL、STALE_INVALID 是明确产品状态；READY 且无交易才返回正常空列表。
错误只暴露稳定 code 与安全上下文，不返回 SQL、内部路径、连接信息或 stack trace。

## 4. 查询实现与统计

新增 `app/reference_trading/query.py`，只组合 reader/repository，不 import build/advance、provider、Alert transport。
新增 repository 只读方法支持按 stream/product/window 查询；保持旧内部方法测试语义，不破坏 P4。
每次组合响应使用同一 fresh REPEATABLE READ / READ ONLY Session；复用 `app/db/readonly.py`，不能在已开事务上嵌套使用。
分页使用 SQL keyset + limit+1，SQL 选择 snapshot/cutoff 下正确行版本；批量选择 latest eligible mark，避免逐笔 SELECT。
summary 可以扫描匹配窗口的持久化结果，但须有界内存、超时/取消，不拉取无关 stream 或全部行情。
优先复用已有 Newow/SuBing 统计纯函数；若需流式 accumulator，严格对照原 Decimal 顺序与舍入，不用 SQL float 或改变计算顺序造细微差异。
期初 OPEN/跨窗口 CLOSED/中断归属按各策略现合同，不把 window membership 写入固定交易身份。

## 5. 展示字段补齐：不伪造兼容响应

采用 typed `presentation_v1` envelope 随 P4 批次一同写入现有 source_evidence，参与 payload hash：

- 策略原始信号及 ID、同向信号、动作关联、指标展示点、必要的 Hint/质量说明；每项带交易日、Bar、segment 和公式身份。
- 指标点来自本来就在执行的历史 kernel，不在 GET 重算；同向信号只存展示，不新增交易动作或改变计算进度。
- 大批次限制展示条数与字节数，按现有批次切分；查询只读窗口相关批次，限制解码内存。
- 已发布旧 revision 缺 envelope 返回 PRESENTATION_NOT_MATERIALIZED；隔离环境用既有 rebuild 生成新 revision。
  不在 GET 补写；生产已有结果的重建列入后续明确批次，不纳入本次开发默认权限。

K线价格仍从 MDS 的有界 chart 读取提供，不把 presentation envelope 变成第二套行情 authority。
苏冰 D1 quality_chart_bars 从现有质量分段读取逻辑提取有界只读 presentation reader，保留非正价/PRICE_UNAVAILABLE 合同；
不要调用完整 `SubingReferenceService.query()` 来获取它们，否则又偷偷算了一遍交易。
同一视图 chart、indicators、signals 与 trades 必须校验共同 cutoff/输入身份；未对齐时展示明确状态，不混合绘制。
牛哇旧 reference section 的 snapshot token 与新 snapshot 建立明确关联和校验，不把两个 token 当同一字符串随意互换。

## 6. 旧入口与页面迁移

生产 reader 默认维持既有模式；提供显式开发/部署配置选择 `legacy` 或 `persisted`，配置变化不在本次正式执行。
这是一次迁移开关，不是自动 fallback：persisted 模式缺 schema/data 就明确不可用，绝不悄悄回放。
legacy 模式保留当前线上行为；候选验收全部在 persisted 模式。后续生产切换成功后再删除 legacy 分支，不宣称本次已完成生产替换。
新统一 GET 本身始终只读持久化，无 legacy 回放路径。

旧苏冰 API 和牛哇 reference section 在 persisted 模式中是 DTO 薄适配；原图表、auxiliary、解释、预警保持合同。
Vue 新增公共 reference API/types/composable；按身份与 snapshot 做 Abort/generation 防竞态；禁止各策略再次独立实现分页状态。
优先复用现有 panel 的策略字段展示，提取公共状态/分页逻辑；不为“统一”抹平价格、方向、Hint 或质量差异。
明确显示“历史参考·已保存”、计算截止、统计窗口、零费用零滑点；不得显示盘中已启用或交易已成交。
刷新重新获取 snapshot；loadMore 固定旧 snapshot；遇 409 清理旧页并提示刷新，不能拼接重复或混代数据。
无主动作但有初始化诊断/同向信号时仍保留解释；未构建不显示零收益成功。

## 7. 开发步骤与文件

### P5.1 合同、兼容清单和物化展示补齐

- 修改 `openspec/specs/reference-trading/spec.md`，记录本计划 GET/状态/快照/迁移合同。
- 新建 `app/reference_trading/presentation.py` typed envelope；修改 P4 service/inputs 的必要展示输出。
- 增加 `tests/reference_trading/test_presentation.py`：同向信号、反手关联、指标预热、D1缺价、旧批次缺字段、字节预算、重启/重建一致。
- 对照旧苏冰四周期与牛哇三策略 fixture，逐字段列清信息来源；未保存字段不能用空数组填充冒充兼容。

### P5.2 有界查询、版本选择和统计

- 新建 query.py；扩展 repository/contracts 的只读方法，不修改已有写事务语义。
- 新增 test_query.py、test_query_postgresql.py、test_summary.py。
- 验证倒序 keyset、跨页无重复、旧 seq 查询 OPEN、过去 cutoff、期初交易、中断、并发发布/失效、多 stream 版本歧义。
- 专用 PG 证明查询 read-only、SQL limit/keyset、mark 批量读取；资源测试不能仅用 3 条 fixture 冒充大历史验证。

### P5.3 HTTP 与旧接口薄适配

- 新建 `app/api/reference_trading.py`、`app/schemas/reference_trading.py` 与 composition 只读装配。
- 修改实际 router 注册、苏冰 reference API、牛哇 reference section；隔离 preview 同样按明确配置启用新 reader。
- 新增 test_api.py、test_legacy_compatibility.py；GET 中将 replay/build/advance/provider/send 注入为 raising spies，确保零调用。
- 验证缺 0047、NOT_BUILT、disabled 但已发布可读、candidate 不可见、错误脱敏、重复参数、混用 token 与不同周期 cursor。

### P5.4 Web 接入和图表一致性

- 新建 `src/api/referenceTrading.ts`、`src/types/referenceTrading.ts`、`src/composables/useReferenceTrading.ts`。
- 修改 `useSubingReference.ts`、`useNewowProduct.ts`、相关 workspace/panel，以薄适配或公共 composable 接入，保留策略差异。
- 增加 Web 定向测试，覆盖切策略/品种/周期竞态、刷新/翻页、列表与统计同快照、未构建/滞后、D1质量Bar与指标不丢失。
- 浏览器使用隔离数据库 + 真实临时 Canonical/MDS/P4 build 验证持久化查询；另加 UI 错误 fixture，但不以 route mock 代替真实接线。

### P5.5 回归、审查与集成

- 先跑新 query/API/presentation/Web 测试，再跑 P0–P4、Newow/SuBing reference、D1质量和现有 API/Web 相关回归。
- PG 只按 TESTING.md 专用可销毁数据库规则；缺依赖标待验，不用生产连接，不读取 `.env`。
- 跑实际 Web typecheck/build、Ruff/必要类型检查、OpenSpec、secret scan、diff check；从仓库脚本读取真实命令。
- 独立 Review 聚焦 snapshot 时间泄漏、SQL资源、统计 parity、缺展示字段与线上默认行为；修复 Confirmed Issue。
- commit/push 并条件满足时集成 develop；更新 STATUS 区分 P5 工程完成与生产切换/P6 worker 未执行。

## 8. 最终验收与交付

必须同时满足：

1. 新 GET 与 persisted 旧入口不回放策略、不生成写入、不触发通知；刷新/翻页行为有 raising spy 证明。
2. P4 构建结果经 API/Web 展示，信号/指标/质量信息保留，交易与旧口径逐字段一致。
3. snapshot/cutoff/revision/stream 身份正确，过去查询不泄漏未来 exit，统计不随分页变化。
4. SQL 分页有界，无逐交易 mark N+1；summary 有资源边界；大样本测量与小 fixture 都提供。
5. 缺 schema、缺 presentation、未构建、数据不足与真零交易明确区分；线上默认未切换。
6. 独立 Review 通过、必要真实隔离 PG 与浏览器接线验证通过，develop 集成证据明确。

最终报告列出实际命令/结果、提交、兼容范围、剩余生产 migration/bootstrap/reader switch Gate；
不得宣布已上线或盘中持续记录。P6/P7/P9 不是本任务自动扩展范围。
