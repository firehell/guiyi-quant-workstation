# 当前状态

文档整理：2026-09-13；最新现场记录截至 `2026-09-13 16:53:56 CST`。
正式 Release 与现役 Runtime 为 `v1.10.8@82860ee3f5f63c49397ab11b0d0ab60c601376b9`。
六服务切换、即时服务和页面验收已通过；自然 Live、盘后、后续增量及首次自然周检仍待验收，
不声明 `RUNTIME_READY`。本文件保留当前身份、已证明事实、尚缺证据和已接受规划；
逐次操作和旧候选过程从 Git history、tag、PR 与原 evidence 追溯，历史授权不授权重跑。
稳定产品面见 `PROJECT_SOURCE.md`，长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

## 当前阶段

| 项目 | 阶段 | 说明 |
|---|---|---|
| 正式 Release | `RELEASED` | `v1.10.8@82860ee3f`，PR #364 合入 main，tree `6df9ebdce`、annotated tag object `b1a52b239` 与 GitHub Release 已读回 |
| 现役 Runtime | v1.10.8 `RUNTIME_PROMOTED / IMMEDIATE_ACCEPTANCE_PASSED`，未声明 `RUNTIME_READY` | 六服务均绑定 `v1.10.8@82860ee3f`；API/Web 200、单 API worker、Live/Alert fresh heartbeat；after-market 等待自然运行，既有 degraded/failed health 事实保留 |
| v1.10.8 Runtime 准备 | `COMPLETED / PROMOTION_GATE_CLOSED` | 独立 immutable Runtime/recovery roots、身份/失败恢复校验、fresh 正式只读 preflight、一次切换与即时读回均通过；未恢复或重试 |
| Weekly audit | `ENABLED / CURRENT_WEEK_READBACK_PASSED / NATURAL_RUN_PENDING` | exact v1.10.8 root 已 loaded、周六 09:00、当前 idle、runs 0 / not_run；840/840 endpoint 与 120/120 周线归属核对通过；首次自然及全历史周检待验 |
| 中断盘后收尾 | 9 月 9 日与 9 月 11 日均 `COMPLETED` | 两次运行分别按独立意图收尾并读回；9 月 11 日为 schema-v5 terminal，旧 writer 已停止 |
| 盘后生命周期修复 | `COMPLETED / RELEASED / RUNTIME_PROMOTED` | `8f2b051fd` 已进入现役 v1.10.8 Runtime；仅自然盘后及后续交易日增量验收未完成 |
| 牛哇加载一致性 | `COMPLETED / RELEASED` | `fef307732` 随 v1.10.6 发布；相关 unit、九组合及完整浏览器矩阵重验通过 |
| 本轮稳定版 | v1.10.8 `RELEASED / DEPLOYMENT_PREPARED / RUNTIME_PROMOTED / IMMEDIATE_ACCEPTANCE_PASSED` | 候选、Review、Release、六服务 promotion 与修复版页面即时验收已收口；自然业务验收仍独立待完成 |
| 其他品种历史 | 元数据已完成；物理历史未盘点 | 不阻塞盘后稳定版，除非发现共享完整性问题 |
| 牛哇新版综合解释 | `RESEARCH_EVIDENCE_COMPLETE` / `IMPLEMENTATION_PENDING` | 规则差异已确认，未批准新合同 |
| 后续交付路线 | 规划已接受，未据此关闭任何 Gate | 先盘后稳定，再牛哇日周六组合；随后 Web 体验与 60m 数据准备并行，最后独立开放 60m |

## 首页市场、消息与分钟行情（开发验收）

2026-09-13 首页改进候选 `056958632` 已完成 `CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE`，
允许集成 develop。市场/消息分区、自由看盘入口、SVG 状态图标、详情返回缓存与位置恢复、固定 operational
60 品种 completed 1m 只读报价及历史消息分页已实现。分钟报价和已完成 D1/W1 指标分别标识；
换主力接受后端确认的新 owner，缺同合约昨收不借旧合约涨跌；日周未同向不表述为账户空仓。
独立复核发现的普通 quote 误触发 overview 刷新、缓存分页恢复、换主力显示和刷新/续页竞态均已关闭。
组合后端测试 227 passed；Web 555 passed / 1 原有可选 golden skip；首页 fixture E2E 25 passed；
最后分页修复另经 13 项定向测试与 build/typecheck 验证。OpenSpec 9 passed、secret scan 0 findings。
命令与验证边界见 `TESTING.md`。本地预览验收不构成 main/tag 发布或 Runtime promotion，
自然开市 completed 1m 与通知收件继续按各自证据验收。

## 牛哇周线 60 品种准备（小批次现场证据）

2026-09-13 owner 单次批准的 PT 周线 calibration batch 已严格按冻结 plan hash 串行执行一次：PT2608
14/14 target、PT2610 18/18 target 均 passed，blocked/failed 均为 0；两者写后重规划均为 0 target / 0 bar /
0 provider request。RQData `bytes_used` 整批增加 5,109,123 bytes，未触发异常流量停止线。本次写入意图已消费，
不授权重试或扩大范围。PT 写后依赖 readiness 为 `audited / complete=true`，6 项依赖均 `DATA_READY`。

随后只读 PT 三策略周线 matrix 中趋势、震荡主图 READY；当时主升浪主图和参考层仍因内部
`NEWOW_PRODUCT_PAIRING_CONFLICT` 失败。已确认这不是行情缺口：PT2610 共 41 根周线，从上市首根即为黄带且没有
真实 BUILD 转换，第 40 根首次转蓝并产生 CLEAR。owner 已批准采用“显式初始无入场 CLEAR”合同；本地 develop
`db23dfc9b` 已集成
`INITIAL_CLEAR_NO_ENTRY`、reader lifecycle evidence、零交易投影、v2 API/Web 合同及“清仓（无入场）”展示，
离线 Core/API/Web/E2E/OpenSpec 验证与独立 Review 修正已完成。固定 PT 截点的本次 v2 生产只读验收因宿主凭据
权限 Gate 未执行，仍为 `EXTERNAL_GATE_PENDING`；不得以旧 matrix 或本地 fixture 替代。全 60 品种审计仍为
incomplete，未运行 180 主组合矩阵，不得声明周线 60 品种完成。紧凑旧证据见
[周线 60 品种 readiness 摘要](outputs/newow-weekly-60-20260913/readiness-summary.json)。

## v1.10.8 Release（已发布；Runtime 已切换）

- 已审冻结候选 `6c724f730238c54a30b69d0930d5dcbdc61921e3` 与发布 tree
  `6df9ebdce760d7d5d67f83e47e613cf8b0d71e3c` 一致；最终 Review 为 0 Critical / 0 Important / 0 Minor。
- PR #364 于 `2026-09-12T16:18:01Z` 合入 main；main 与 annotated `v1.10.8` peeled commit 均为
  `82860ee3f5f63c49397ab11b0d0ab60c601376b9`，tag object 为
  `b1a52b23932665abe46e98bf9e7e5b07a664fece`。GitHub Release 于 `2026-09-12T16:19:25Z` 发布，
  non-draft、non-prerelease、target `main`，见 [v1.10.8 Release](https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.8)。
- 该 Release 本身不等于 Runtime promotion；后续已按独立一次意图完成 exact v1.10.8 六服务切换和即时读回，
  详见下方 promotion 小节。自然运行验收仍是独立 Gate。

## 运行与恢复目录

- 现役 Runtime 只保留 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.8-r1`；该 root 为非 symlink、detached、
  tracked clean，绑定 exact `82860ee3f5f63c49397ab11b0d0ab60c601376b9` / tree
  `6df9ebdce760d7d5d67f83e47e613cf8b0d71e3c`。独立 Python env、前端依赖与 dist、frozen/offline 安装、
  build、相关隔离测试 463 passed 及 render-only 均已验证；这些是部署准备证据，不证明自然业务验收。
- owner 于 2026-09-13 明确要求发布 worktree 只保留最新在用根；未被服务引用、同为 v1.10.8 的
  `guiyi-quant-recovery-v1.10.8-r1` 已随本次收敛移除。其历史失败恢复合同 5/5 passed 仍只作为历史证据；
  如后续需要 compatible recovery，须从 exact annotated tag 重新建立独立 detached root 并重新完成当时 Gate，
  不能把已删除根或旧验证当作当前可用恢复能力。
- 最新记录中现役 root 尚无 after-market terminal status 文件，没有可用于 `compatible-recovery-proof`
  的现场 SHA；实际恢复必须重新绑定届时状态与独立一次意图，不重用旧 terminal SHA。
- 9 月 13 日已按精确范围移除过时任务/运行树；本次收敛后只保留主 develop 与上述现役 Runtime。
  临时开发 worktree 清单以 Git 当前读回为准。旧 v1.10.5/v1.10.7 Runtime、v1.10.7 recovery 及 v1.10.8
  recovery 均已删除，不再列为可用恢复路径。旧 `.run/after-market-status.json` 不能从 Git 恢复；已审终态摘要
  与 SHA 保留在下文。

## v1.10.8 Runtime promotion 与即时验收（已完成；自然验收未完成）

- owner 批准的单次切换先运行 fresh 正式只读 preflight，返回 `passed / non_trading_interval`；随后严格按
  Market Runtime（after-market、Live）→ base（API、Web、log-rotate）→ Alert Runtime → weekly audit 的纠正顺序
  执行。四步均成功，统一进程 exit 0，未发生漂移、结果不明、恢复或重试。
- `2026-09-13 09:00:49 CST` 独立读回确认 API、Web、after-market、Live、Alert、weekly 六个 installed/loaded label
  均精确绑定 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.8-r1` 与 commit
  `82860ee3f5f63c49397ab11b0d0ab60c601376b9`；该 root 仍 detached、tracked clean。API 与 Web 均返回 200，
  API 报告 version `1.10.8`，正式 API worker 精确为 1。
- Live 与 Alert 进程均有切换后的新鲜 heartbeat；Live enabled、operational 60、当前休市 60、尚无自然 `last_bar_at`。
  after-market 已 loaded、当前等待自然运行，expected trading day 为 2026-09-11、`current_run=null`。weekly 已迁移至
  exact v1.10.8，loaded 但 idle，`runs=0`、`last exit=(never exited)`、状态 `not_run`，仍为周六 09:00 且无
  RunAtLoad/KeepAlive；本次没有手工执行周检。
- Runtime public health 仍为 `degraded`，聚合 status/overall 仍为 failed：保留既有 Alert 历史 transport failure 与
  SuBing `evaluation_failed` 事实，未 acknowledgment、清除或伪装为健康。weekly `not_run` 不是 required service；
  即时切换成功不等于 `RUNTIME_READY`。
- 真实浏览器读回：Market Home 为 60/60、as-of 2026-09-11、expired 0、missing 0；SuBing A/豆一页面解析
  A2611，历史参考请求精确为单前缀 `GET /api/v1/market/a/subing/reference` 并返回 200，已保存的 S↓ AlertEvent
  可读，16 笔 closed 与 1 笔 open 参考交易可见；控制台 0 error / 0 warning。旧双前缀 404 已由 active Runtime 关闭。
- 本次未写行情/metadata/Scope，未发送手工通知，未执行 weekly audit，未重跑 D/E/F。自然 completed Live Bar、
  自然 after-market、其后的增量/MDS 读回及首次自然 weekly audit 继续作为互相独立的现场 Gate。

## Scope 与既有自然证据

| 项目 | 最近已记录事实 |
|---|---|
| Database | 最近生产 readback 为 Alembic `20260903_0045` |
| Market Scope | `operational_products.txt` 的 60 个品种 |
| Alert Scope | `2026-09-13T02:22:46Z` 按 owner 本轮明确意图新增 59 品种 × 60m 并逐项及全量读回：HTDY `jm × 5m/15m`，其余 59 品种各 `60m`，共 60 品种/61 对；苏冰保持 60 品种 × 15m，两 Rule enabled。没有发送通知；Scope 启用不证明输入完整性或自然预警成功 |
| 最近自然 After-market | v1.10.3 于 2026-09-08 18:05:05–19:05:52 自然运行，passed、attempts=1、60 品种。状态随后带入旧 Runtime，SHA `cece65929ba734c37cf91ee47af1b0d23b5dc3dd413c9d703888f669428347d5`；不证明任何后续版本的自然成功 |

本轮 Scope 证据为 `/private/tmp/guiyi-alert-fixes-20260913/scope-plan.json`、`scope-apply.json`；计划 SHA-256
`a8c2c5758461e89697e2375dff3a89b120bae5e86b5a2f3db53fca901841c6e3`，59 项一次执行成功并读回，未改变
JM 原周期、苏冰 Scope、Rule/audience、行情或 Runtime。该次执行意图已消费，不授权新会话重做。

2026-09-13 开盘前修正现为 `REVIEW_COMPLETE / LOCAL_INTEGRATED`：实现候选
`8803bdaa046b261e2a4eb675bc418dcb7d30a55f` 已把 HTDY actual-dominant 完整性校验限定在日内频率，
苏冰继续只验证当前物理合约生命周期；D1/W1 只读 Canonical，不触碰 Live/Recovery。canonical Event 已提交但
rule-status 登记失败时不会发送，重复触发按 typed skip 处理，不清除既有 rule/global failure；零实际评价也不再
冒充成功。真实 SQLite/Catalog/Parquet/MDS fixture 已覆盖旧 owner 缺口拒绝及补齐后的固定 HTDY `buy`；周一
集成回归已由 Catalog Session authority 独立推导 endpoint，并贯通 provider adapter、`recover_product`、隔离
Redis/聚合与 MarketRead，覆盖 60 个冻结身份及 45 个夜盘目标。Sol high 独立复审为 0 Critical / 0 Important，
其受影响组为 282 passed / 1 isolated-Redis skip；本地完整后端为 3523 passed / 16 skipped / 31 deselected。
当前生产 Scope 只读复核仍为 HTDY 60 品种/61 对、苏冰 60 品种/60 对；本轮未改变现役 Runtime，也不授权重做
Scope、恢复、补数或发送。周日 10:24 CST 的最近可用只读证据仍无 9 月 14 日冻结 Live snapshot；未重试、未改
配置、未执行恢复或发送。release、Runtime promotion、首次自然 completed Bar、Event/transport 与健康读回
继续作为互相独立的外部 Gate。

## 周检有界读回证据

9 月 12 日在 v1.10.7 阶段启用周检并完成本周只读核对；现役服务身份见上方 v1.10.8 promotion 记录。
operational 60 品种、2026-09-07 至 2026-09-11、continuous + actual_dominant、七周期有界读回
840/840 通过；continuous W1 对 continuous D1、actual_dominant W1 对周末 rank1 物理合约完整周 D1，
120/120 归属核对通过，OHLCV/turnover/open_interest 精确一致。范围内缺失/不一致 0、provider 请求 0、
data/metadata 写入 0，maintenance lease 已释放。

证据：`/private/tmp/guiyi-aftermkt-recovery-20260911/weekly-enable-and-current-week-verification.json`，
SHA-256 `10cb5deccd5878edfca3e979610a2e95a401fe2377c5ea1198bdc8570b2b2250`。
初始 raw probe 的 3 项已由正确归属的读回取代，不表示修复过数据。本周有界核对不证明全历史或自然调度；
weekly 仍为可选服务，不参与 required operational health。临时 evidence 再用前须核对存在和完整性。

## 已关闭恢复与工程修复

两次旧盘后运行均已按各自单次意图行政收尾，不能把 `interrupted` 当成功：

- 2026-09-09 运行：60 品种 45,362 个已提交 Catalog 指针严格读取通过；中断日 audit 720 项缺口按有效子集
  检查后 closeout ready。apply 后 schema v4、`current_run=null`、`last_run=interrupted`，终态 SHA-256
  `ee5ccb1f377d4b7ac0812cd09779f00e65295387a07dabd9466872da83ae8a4b`，零 provider/行情写入。
- 2026-09-11 运行（D）：终态 schema v5、`current_run=null`、`last_run=interrupted`，SHA-256
  `98c09006fee9624b0cef0f50e01c11b4d59e5ac8e6bdb57e76e7ba47e6566d08`；旧 writer 已停止，旧状态文件现已随
  退役运行树移除。该 SHA 是历史证据，不是新 Runtime 恢复输入。
- E metadata source snapshot `8586532f98bceb2c525ffafeb9dedf4b0286bb13d4d58cd83414e88bc36a0e65`；
  plan `52fead349311021e27338e59de3c4c9062189b811a23efa30f2a76bb9e1f7fcf` 一次 apply 新增 9 月 14 日
  P60 Session 225 行。读回确认 9 月 11/14 日均 60 品种/225 Session，重规划 equal no-op；
  Calendar/rank1/Canonical/provider 写入为 0。
- F daily plan `3e56bbe9ee2adb705904e524a7dee5ce307b424b3b50172b0e949f98ebdad1e1`：960 applied、
  0 failed/blocked、480 provider requests，无重试。MDS 写后读回 840/840 最终分区、487138 Bar 与 endpoint
  hash 通过；含七周期 9 月 9–11 日增量及 W1 所需 D1 companion，不证明全历史审计。D/E/F 不重跑。

| 已集成修复 | 固定提交与验收范围 |
|---|---|
| Canonical 批量边界、同族同月来源先于派生、Newow 冲突失效 | `17718f126`；后端 3248 passed，Mypy 154 文件；正式规范已同步。旧 change 已完成，不是待实施提案 |
| 盘后生命周期与错误判断 | `8f2b051fd`；后端 3259 passed，工程 81 passed，独立 Review 通过；自然验收归工作 5 |
| closeout Alert heartbeat 与共享停止态 authority | `baef0d92b`、`bf48284cf`、`83de0c403`；最终 Review 绑定 `47c918596` / tree `e9abc7dba`，无 P0–P3；不放宽 promotion |
| Session 替换窗口上下界 | 双边界修复后后端 3377 passed / 16 skipped / 31 deselected；不把代码测试解释为修复生产事实 |
| Newow 加载与浏览器一致性 | `fef307732`、`20dcc4f29`、`972162b80`；九组合 fixture、历史分页与定位已验；不证明全品种生产数据 |
| 单 API worker | `044972b82201afe6dc9ee5a532040d748b862bac`；五组新进程黄金固定截点请求通过，health 2078 次 p95 12.9 ms、行情 722 次 p95 91.4 ms，无超时/错误；[冻结证据](outputs/newow-single-worker-20260911/acceptance.json)不外推全品种或双 worker 性能 |
| 周检状态归属 | `838a7e649`；定向 43 passed，相关 368 passed，隔离 PostgreSQL 2 passed，独立 Review 无 P0–P3 |
| 苏冰历史参考双 API 前缀 | `5879452c1`；随 v1.10.8 发布并进入 Runtime，单前缀 API 200 与即时浏览器验收已关闭旧 404 |

这些修复均已进入现役 v1.10.8；表中测试只归属各自提交，不是本轮文档整理重新执行的测试。
历史过程可从整理前 `d5b6c64ef` 的 `STATUS.md`、对应提交/PR/tag 与原 evidence 追溯。

## 已证明事实（不得重新打开，也不得扩大解释）

1. **苏冰本次自然推送已闭环**，归属 exact `v1.10.5@cdd72d750`。补齐 AO2701/OI2701 后，2026-09-09 自然生成 Event #143–#146；#146 PT2610 14:00 买入与 `last_provider_accepted_at` 匹配，owner 确认该条微信收件。该确认不声明另外三条或 Topic 其他成员送达，也不替代现版本自然盘后验收。旧 `last_failure_at=2026-09-09T03:30:05.449850Z` 保留，不得手工清除来制造通过。更早的 v1.9.15 G11/G12 闭环见 Issue #307，只归属当时版本。
2. **黄金牛哇固定历史截点本地预览已完成**。截点 `2026-09-08T07:00:00.000001Z`，候选 `e79e82f42`；九组合主图/副图/解释/参考统计/历史定位在 API8010/Web5174 真实浏览器通过。周线默认本周未完成保留；震荡周线 AU2610 比较器明确不足 20 根。这不是当前时点或全品种生产验收。目标/吸筹 previous-close、原页面时序、期货 owner/segment 仍为 `EVIDENCE_REQUIRED`。
3. **Calendar/Session 元数据恢复已完成**：黄金五合约夜盘/Session 缺口关闭；其余 59 品种在 `a53389cc5` 后 Calendar/Session 剩余唯一缺口为 0。这不证明分钟历史或九组合页面已恢复。
4. **统一详情页、Canonical P1、captured 身份解析已随 v1.10.5 发布；后续架构与显示修复已随 v1.10.6 发布**。详情页 owner 视觉接受只证明对应版本范围；fixture 不证明生产数据。Canonical 后续每批写入仍须独立单次意图。

## 尚缺证据

| 缺口 | 类型 | 当前证据边界 |
|---|---|---|
| v1.10.8 自然运行验收 | 现场验收 | 六服务 promotion、即时服务及页面验收已通过；仍缺第一根自然 completed Live Bar、自然 after-market 与后续增量/MDS 读回。不得用 v1.10.3 成功记录、旧状态字节或即时 heartbeat 代替。 |
| Weekly audit 自然/全历史验收 | 现场验收 | 服务已在 v1.10.8 enabled/loaded，本周有界读回通过；当前 runs 0 / not_run，未执行全历史 audit，也未观察首次周六 09:00 自然调度。raw probe 的 3 项已由正确归属读回取代，不表示修复过数据。 |
| 其他品种物理历史与页面可用性 | 数据缺口 | 元数据不得再列为待修。须按品种/周期/面板区分元数据缺失、物理历史缺失、质量异常、正常样本不足和原站证据不足。 |
| 牛哇新版综合解释 | 新版需求 | 同输入已确认新版五项/`R0–R4`/`MM1–MM4`/计龄与当前 v3.2.59 四项/13 格合同 3/3 不一致；总分含未展示 `certExtra`。详见 [当前复核](docs/research/newow-current-review.md) N09。震荡 60 分钟图表差异为 `KNOWN_DIFFERENCE_ACCEPTED`。 |

## 本轮稳定版边界（冻结）

近期里程碑是：交付一个盘后结果可信、失败可诊断、部署可验收的稳定版本。工作 1–5 服务该里程碑；工作 6、7 不是同一任务，不要求完成后才能发布。

**分层 Gate**

- v1.10.8 候选与发布 Gate：冻结候选、最终 Review、main merge、annotated tag 与 GitHub Release 已完成；该 Gate 已关闭。
- v1.10.8 Runtime promotion Gate：独立 immutable Runtime/recovery roots、身份/失败恢复校验、fresh 正式只读
  preflight、六服务单次切换与即时读回均已完成，未恢复或重试；该 Gate 已关闭。
- Weekly audit enable/current-week Gate：v1.10.8 服务启用与本周有界读回已完成；首次自然调度和全历史 audit 仍待验，
  不得用本周读回代替。
- 稳定版运行验收 Gate：active v1.10.8 已关闭 SuBing 历史参考 404；仍须取得自然 completed Live Bar、自然盘后与
  后续增量/MDS 证据。此 Gate 未完成时保留待验收，不声明 `RUNTIME_READY`，也不倒置为发布前真实运行要求。

**本轮不阻塞（已披露限制）**

- 牛哇新版评分、`certExtra`、收益曲线、盘中确认时钟、Newow 真实推送。
- 其他品种全部历史补齐、真实全品种九组合矩阵。
- 已接受的原站差异，包括震荡 60 分钟同根重建。
- 正常空仓、未完成周线、样本不足；不得改成“有结果”。
- BU/BZ D1/W1 异常；HTDY 61 对 Scope 已启用，但自然预警与输入完整性修复须分别验收。
- 原件缺口继续 `EVIDENCE_REQUIRED`：诊断 token、六组合评分/排序、AI 逐字 copy、目标/吸筹权威昨收与期货 owner parity、比较器 browser-final/tie golden。
- 旧苏冰 failure 时间戳、Topic 其他成员送达人数。

## 已接受的后续交付规划（2026-09-11）

owner 已要求将本轮讨论的规划与执行规则纳入 develop。本节记录交付顺序、范围与出口，
不是新的完成证据、Lane 3 实现批准或真实操作授权。执行规则见 [开发流程](docs/DEVELOPMENT.md)，
产品边界见 [稳定产品面](PROJECT_SOURCE.md)，数据语义继续以 [数据合同](docs/DATA_CENTER.md) 为准。
现有七项工作继续作为任务对应，不另建平行台账；阶段不是固定版本号，可按独立交付单元拆分版本。

```text
旧盘后安全收尾
→ 冻结并交付盘后稳定版
→ 牛哇日周六组合可用版
→ Web 体验小步优化 ∥ 60m 受控数据准备
→ 60m 独立开放
```

| 阶段 | 目标与前置 | 范围与出口 | 不得搭车 |
|---|---|---|---|
| 前置收尾 | 对应工作 2；按最新现场证据处理旧事故 | 原运行有证据归类，受控收尾后独立读回和部署预检；剩余阻塞单独界定，不能把 interrupted 当 passed | 不借收尾补行情、改 Scope 或切换 Runtime |
| 第一阶段：盘后稳定版 | 对应工作 3、5；工作 4 按已接受范围参与 | v1.10.8 已发布并完成六服务 promotion 与即时页面验收，weekly-audit 已迁移到现役 v1.10.8；首次自然/全历史周检及新版本自然运行仍为独立 Gate | 不追加牛哇日周开放、新版评分或 60m 大规模补数 |
| 第二阶段：牛哇日周版 | 稳定交付恢复后，工作 6 优先服务日周；复用工作 4 的正确性修复 | 趋势、震荡、主升浪 × 1d/1w 六组合，在明确品种、历史窗口和面板范围内完成数据、计算、页面及维护接续验收 | 不开放 Newow 60m，不新增简化评分、公式或推送 |
| 第三阶段：Web 体验与 60m 数据准备 | 日周版交付并稳定后，两条互不依赖的支线 | Web 每次改善一个具体使用问题；60m 按去重物理合约/窗口分批准备，每批有读回、缺口与后续维护结论 | 不把补数完成作为纯 Web 版本前置，不边下载边默认开放 60m |
| 第四阶段：60m 独立开放 | 声明范围内数据及持续维护已就绪，产品任务合同另行审定 | 三个 60m 组合及拟开放跨周期面板分别完成输入、计算、页面和时间因果验收，再独立发布/部署 | 不同时升级公式、参考交易模型、新版评分或通知能力 |

### 盘后稳定版出口

每日增量负责有基线、有边界的最新数据维护；每周检查负责 operational 全历史只读审计；
发现后的修复按明确范围另行处理。复用既有入口、maintenance lock、质量校验和原子发布，不重建更新系统。
周检不下载、不自动修复、不通知；锁忙如实报告，不能把 skipped 当 passed。日常成功不证明全历史完整。

工程出口：在精确基线复现问题并保留故障注入回归，覆盖日历未知、正常追加、缺失续传、
新主力相关维护、普通异常、部分提交、提交结果未知与进程中断；候选 diff 冻结、必要检查和独立 Review 通过。
运行出口：发布与 Runtime promotion 分别获准后，取得新版本自然盘后及后续增量的实际证据，
确认 MDS 和现有页面读到更新结果、周检入口真实执行且结果可解释。尚未自然发生的场景保留待验收，
不拿旧版本成功、fixture、只读 closeout ready 或旧状态字节替代；运行出口不是要求未发布版本先在生产运行。

### 牛哇日周版范围与验收

先固定支持品种、主图窗口、独立参考统计窗口、物理合约预热需求及面板清单，再按使用优先级分批恢复。
沿用既有 readiness/MDS，按“品种/物理合约 → 日周窗口 → 缺口与原因 → 处理 → 读回 → 页面”记录，
不新建数据表或第二套缺口事实。先核实权威元数据与 rank1 分段，补所需 D1/预热，再验同源完整 W1。
既有元数据恢复及黄金固定截点只按原范围复用，不从头重做，也不扩大为当前全品种生产验收。

日常增量不自动补齐物理合约完整生命周期预热；当前主力恢复之后，仍须明确换主力后的预热检查、
不足披露和受控补齐流程。正常样本不足、未完成周线和原站证据不足不靠造数、缩窗或跨频回退解决。

主图、同周期主动作/状态、选定副图与参考记录按各自输入独立验收。完整综合解释存在 60m 依赖，
日周版暂缓开放并说明原因；不得仅隐藏 60m 按钮，仍由解释请求隐式读取全部周期，
也不得删除 60m 输入后沿用原总分或创造日周简化评分。后续实现须同步任务合同、相关 OpenSpec、
API/页面入口与旧链接/周期偏好处理；本次仅记录目标，不声称现有 API 已拒绝 60m。
收窄仅作用于 Newow 本版开放范围，不删除通用分钟链路或改变 HTDY/SuBing/Free 及其持续授权。

页面正确性随日周版验收：切换品种/策略/周期后旧响应不能回写，面板不得混用身份/快照；
缺数据、预热不足、无主动作、证据不足和未开放分别表达；分页、缩放、参考定位不改变统计窗口；
未来完成的周线不进入历史当时结果。六组合须在声明范围内逐项可核对，不以单品种偶然出图作为完成。

### Web 与 60m 支线出口

Web 优化信息层级、布局、可读性、图表操作、加载体验和移动端适配，每个任务围绕一个使用问题；
不顺带改公式、统计窗口或数据来源。已确认的显示正确性问题不能拖到这一阶段才处理。

60m 先盘点已有 1m；同物理合约/窗口去重，有完整源数据先派生，只对缺失部分安排受控下载。
顺序为“1m 盘点 → 分批补缺 → 同合约 60m 派生 → MDS 读回 → 策略输入验证 → 维护接续”，
不另接 60m 来源，不把下载进程结束当数据就绪。开始前固定品种/合约/历史窗口、资源预算和维护互斥边界，
每批明确完成项、剩余缺口、来源质量问题和代码问题；失败按既有合同停止，不无限重试或自动扩范围。
生产补数、旧事故收尾和 Runtime 切换串行，不抢占自然盘后维护；不新增后台补数平台。

60m 开放另验三策略的预热、Session 聚合、换主力、最新 completed Bar、参考记录、分页与错误状态。
恢复完整综合解释时，各周期须携带 bar_end/as_of，只用当时已完成输入，不用后来完成的周线回填历史 60m。
工作 7 新版综合解释仍为独立候选，不因日周/60m 恢复而自动获得实现批准。

## 七项工作对应

| 编号 | 工作 | 当前出口 |
|---|---|---|
| 1 | 状态和范围收敛 | 当前身份、证据与任务统一在本文件；旧过程从 Git 追溯 |
| 2 | 旧盘后安全收尾 | 两次中断和 D/E/F 已关闭，不重跑；见“已关闭恢复与工程修复” |
| 3 | 盘后生命周期与错误判断 | 代码、验证、Review、发布与 promotion 已完成；自然验收归工作 5 |
| 4 | 牛哇加载和显示一致性 | 既有公式下请求/分页/九组合 fixture 已关闭；生产历史仍独立验收 |
| 5 | 范围固定的稳定版本 | v1.10.8 发布、切换和即时验收完成；自然 Live、盘后、后续增量及自然/全历史周检待验 |
| 6 | 其他品种可用性与补数 | 先冻结日周品种/窗口/面板和预热需求，再出可用性清单；每批真实操作独立授权 |
| 7 | 牛哇新版综合解释 | 先批准来源版本、计龄、五项、总分和 `certExtra` 新合同；保持 Plan-only，不改主动作/参考交易/通知 |

工作 6/7 不阻塞无共享完整性问题的盘后稳定版。收益曲线、嵌套路径、盘中确认与 Newow 推送仍为独立后续需求，
见[当前复核](docs/research/newow-current-review.md) N03/N10/N11/N12；本次不扩展。

## 仍待人工裁决

1. **现役生产归因**：工作 3 已在隔离基线关闭可证明缺陷，但未把它们追溯宣称为 v1.10.5 现场事故的唯一根因。
证据不足的条目保持待裁决。临时 evidence 路径再次使用前须检查存在与完整性。

## 唯一下一步

等待并验证 exact v1.10.8 的第一根自然 completed Live Bar；随后按自然时序分别验收 after-market 与后续增量/MDS。
首次自然 weekly audit 保持独立 Gate。当前休市不手工制造 Bar、不手工执行盘后或周检；data、Scope、notification
及 D/E/F 均不重跑。

本文件不构成元数据/行情修复、发布或 Runtime promotion 批准。
