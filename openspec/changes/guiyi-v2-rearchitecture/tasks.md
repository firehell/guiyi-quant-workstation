# 归一量化 V2 · 开发计划

2026-11-25 更新。需求见 [proposal.md](proposal.md)，架构与复用边界见 [design.md](design.md)，验收依 specs/ 下六份规格。P0–P7 保留原始批次及已提交证据；新开发会话从下方目标模式范围接手。

**目标。** 先打通“冻结物理合约 → 牛哇决策 → RQAlpha 历史账户 → 隔离 PG → 现有 PC 工作台”，再扩三策略六周期和 VeighNa 单账户仿真。沿用 Python、quant-core、既有 API、PostgreSQL、Redis、Vue、launchd；外部引擎各自锁定依赖。

## 当前判断与批次依赖

| 批次 | 前置 | 可独立验收的交付 |
|---|---|---|
| P0 现役合同与消费者 | 本文与当前 Git 基线 | 按现役条款和 reader/writer 列出保留、替换、退役、受保护资产 |
| P1 两项引擎试验 | P0 核实相应输入 | RQAlpha 可复核的往返成交；VeighNa 在 M4 原生导入和离线回调。两项独立判定 |
| P2 Market/Core | P0；外部引擎可先用 fixture | 同一因果输入、既有公式和可复现决策 |
| P3 历史切片 | P1 历史通过，P2 通过 | 一个品种、趋势、5m，从 MDS 到隔离 PG 和只读 API |
| P4 工作台与盘后更新 | P3 | 可点击切片、三策略六周期、盘后发布；增量按实测需要 |
| P5 共享模拟执行 | P2、P1 前向离线能力；可与 P4 分开 | 从一个品种到共享预算，离线验证所有权、去重、退出和对账 |
| P6 本机容量及现场分项 | P4、P5 对应部分 | 四组容量实测；获准的 MD/TD 与实际仿真读回单列 |
| P7 切换和退役 | 对应验收、合同变更与授权 | 读入口切换、旧生产者停写、限定资产清理与保护对象读回 |

**共用限制。** 唯一 MDS/Session 历史权威、物理合约、Decimal 边界、auto_order=false。研究与模拟账户各有身份；缺开仓参数时仅离线可运行。正式 PG/数据湖、柜台、通知、main/tag 与 Runtime 各守原授权。本计划入库不改变现役状态。

**审查焦点。** P2 的晚确认和周线前缀；P3 的换月和未成交 CLEAR；P4 的发布并发与跨页；P5 的未知提交、部分成交和保证金竞争；P7 的原始证据与独立账户误删。

## Codex 调度建议

- 任务车道：Lane 3，V2 隔离开发；收益、时序、并发及账户恢复按高风险边界验收。
- 执行入口：Codex App 目标模式。
- 推荐模型：GPT-6.2 Sol。推理强度：中（本次 owner 指定）。
- 会话：新开 V2 开发会话。高风险改动另开独立 Review。
- Plan：Plan-then-execute。文末目标明确批准本节范围时按已批准计划执行；实质变化单独决定。
- 工作区：从最新 develop 创建本任务独立 branch/worktree，最终集成 develop。按远端规则使用 PR 或可核查的集成提交。
- 人工 Gate：仅将明确批准的离线范围交给 Goal。独立 Review 和验证通过后允许自动 task → develop；main/tag、Runtime、正式数据与柜台动作另行授权。确认远端包含改动后，只清理本任务干净 worktree 和已合并分支。


## 目标模式开发范围

本轮交付是一个可独立集成的离线版本。进入开发前核对当前 HEAD、现场记录的日期和各批已存在的测试，优先补真实缺口。以下计划由 owner 在新会话发送文末目标时批准。单纯提交本文件只更新设计。关键语义或真实权限发生变化时，停受影响部分，其他已批准工作继续。

| 次序 | 开发与复用 | 验收和边界 |
|---|---|---|
| 1 · P6 定位 | 运行下文 summarize.py 复算 440 个历史热批；记录目标 M4、固定输入和源码身份。用独立临时 PG 分段量测四类事件，区分代表性时段与六周期合成峰值 | 分开汇总排队、计算、锁与写入，核对计时起止一致；对比“局部优化现有事务”和“隔离观察流”的成本，一次只改有证据的热点 |
| 2 · P6 修复与恢复 | 沿现有宿主修复；计算和展示复用既有类型，账户仍由单写者确定预算。仅在测量支持时修改状态布局和交接；隔离库可演练升级、失败回滚和重启 | 按设计的故障矩阵验证同一输入、动作、原因、意图、成交、预留及重放等价。原四组各自达到 p95 ≤5 秒、p99 ≤10 秒，报告最慢批、回报、积压、I/O、内存及 swap。旧证据原样保留，新运行另存。实际盘中持续积压与柜台延迟单列现场验收 |
| 3 · P3/P4 研究验证，可与定位独立开展 | 使用已有授权冻结样本核对 Session、分钟标签、可用时间、主力、费用、结算、无量/涨跌停、换月和日周边界。必要时修隔离适配与状态展示 | 固定输入逐笔可复算；FU 缺当时可知 rank1 时保持试验；日周跨时段及跨主力段沿现有阻断。缺外部导出时保留缺项，不生成替代行情或正式结果 |
| 4 · Workspace 隔离联调 | 复用现有 Vue 主图、P4 固定 run 读面和 P5 只读交易投影。用隔离数据查报价/收线、信号原因、逐笔、委托与成交，显式标明来源/时间/状态 | 单品种能从图上定位当时快照及对应研究或账户记录。账号读回不全显示未核实，快期与苏冰原入口可用。页面刷新不下载、不回测、不发单；在隔离预览验证 Web 更新和并发回测时宿主身份、回报连续 |
| 5 · 独立 Review 与 develop 集成 | 对并发、恢复、决策时钟和数据/账户写入边界做独立 Review。按受影响范围运行回归、构建、OpenSpec 与 secret 检查 | 对照受测 SHA，核实远端 develop 包含提交再清理。不得用其他机器代替 M4 验收；缺 M4/私有样本时，已验证且能独立集成的部分可按边界集成，未过门槛的优化不得作为达标版本集成或宣告 P6 完成 |

后续现场按现有 P6/P7 顺序：独立 CTP MD 收包重连 → TD 只读四段完整对账 → 明确获准的模拟报撤 → 单品种切读 → 旧消费者退役。每步记录事实。真实写入、main/tag 与 Runtime promotion 保留各自授权。新增数据商、购买 Plus、行情 Tick 替换现有 1m、快期文件写入正式账本和重做全部 Web 超出本轮离线开发范围。

## 初始批次的代码定位

| 现有文件或目录（仓库根相对路径） | 复用与修改边界 |
|---|---|
| `services/quant-api/app/market_data/market_data_service.py`、同目录 `live_recovery.py` | MarketDataService 已负责 Catalog、真实主力与连续性校验；只增必需的 Session-aware 适配 |
| `packages/quant-core/guiyi_quant/newow/engine.py`、同目录 `fusion_reference.py`、`research_backtest.py` | 复用策略状态与融合公式；计划新增同目录 `decision_adapter.py`。查清旧研究入口消费者后才退役 |
| `services/quant-api/app/reference_trading/`、`services/quant-api/app/api/market_newow.py`、同目录 `newow_reference_parts.py` | 旧 Reference 查询/快照绑定；拟新增 `services/quant-api/app/api/newow_backtests.py` 和 `services/quant-api/app/services/newow_backtest_results.py` |
| `services/quant-api/alembic/` | P3 对实际 migration head 生成隔离迁移。先对表的历史语义做兼容性核对，不猜 revision 编号 |
| `services/quant-api/app/simnow_infrastructure_readiness.py`、同目录 `simnow_takeover_window.py`；`tests/unit/simnow_execution/`、`tests/unit/simnow_supervisor/` | 已有账户与恢复验证素材；拟用隔离的 `services/newow-vnpy/` 承载新宿主。复用兼容部分，不接管旧宿主 |
| `apps/quant-web/src/components/market/detail/newow/NewowReferencePartsPanel.vue`、`apps/quant-web/src/composables/useNewowReferenceParts.ts` | 对照旧请求、错误、游标与图表定位；新面板与旧入口按批切换 |
| `deploy/README.md`、`deploy/launchd/` | 现役绑定与恢复入口；P7 前只读核对 |
| 拟新增 `services/newow-rqalpha/runner.py` | 引擎独立环境。输入冻结清单，输出不可变 run/trade/equity；API 进程不安装 RQAlpha/CTP SDK |

上表保留起草 P0 时的路径设想；实际已落地的文件以 P2–P5 各节及当前源码为准。各批先用最小用例暴露缺口，再做最小实现、定向回归和独立提交。

## P0 · 先查清谁仍使用旧链

- [ ] 读取 STATUS.md、AGENTS.md、docs/DEVELOPMENT.md、PROJECT_SOURCE.md、DECISIONS.md、TESTING.md；比对 develop/main、PR #670/#671、当前相关 Issue/PR、task contract 与运行证据日期。
- [ ] 执行 `git status --short --branch`、`git worktree list`、`git log -1 --oneline`。用 `rg -n 'ReferenceTrade|forward_observation|dual_fusion|main_rise' packages services apps openspec/specs` 定位消费者，补查通知、旧消息定位、launchd、恢复引用和账户持锁者。
- [ ] 根据 active requirement 原名列出保留、修改或退役条款，绑定首个生效批次；重点核对 product-retirement 的 60 品种规则、旧观察原件、快期/苏冰独立账户及现有 SimNow writer。无法确认模拟账户所有者时标为阻断，不读凭据。
- [ ] 输出精确文件、首切片数据资格、待批准成交及风险口径、现场所需权限，提交 P1 Plan。不得先改 active spec 或 STATUS。P0 收敛后只阻断有歧义的分支。

## P1 · 分开验证历史引擎与盘中引擎

- [ ] **历史可行性。** 隔离环境锁定 RQAlpha、Python、所需 mod。用冻结物理合约 1m、Session 和历史参数接入有界数据代理。在禁用外部读取时仍能运行；留输入摘要、引擎版本和实际撮合配置。
- [ ] **可复算账目。** 离线样例设 1 手、乘数 10、买 100、卖 103、开平费各 2、无滑点，预期毛利 30、净利 26，初始权益 1000 最终 1026。另测空头、平今单独费率、跨日结算、限价无成交、晚确认分钟。上述数值仅为测试数据。引擎默认时序不符时报告第一笔分歧，不复制自研撮合器。
- [ ] **M4 可行性。** 在目标 Mac 的隔离环境锁定 vnpy、vnpy_ctp、vnpy_portfoliostrategy；记录系统、架构、SDK 与原生加载结果。先离线初始化、注入回调，不读取生产账号。能导入、能订阅、能对账、能获得真实仿真回报分项判定。CTP 失败时保留已验证的单一实时源，历史分支独立推进。
- [ ] 拟建 `services/newow-rqalpha/tests/test_minute_execution.py`、`services/newow-vnpy/tests/test_gateway_fixture.py`。在各自 env 及服务目录运行 `python -m pytest -q tests`；交付版本锁、数据资格、逐笔手算及未验证能力。

## P2 · 一次实现策略决策，两个适配器各自持有状态

- [x] `app.market_data.newow.v2_completed` 将现有 MDS 历史结果、completed journal 和已发布 D1/W1 映射为同一 `CompletedInput`。Session 校验保留夜盘、午休、短 H1 与完整周边界。D1/W1 前向输入绑定首次观察回执和原始 Bar 摘要；迟到、断档、修订及原件冲突按水位拒绝推进。
- [x] `guiyi_quant.newow.decision_adapter.step_completed(state, input, execution_context)` 复用现役趋势与 TrueUp，各推进一次后计算独立融合。解释保留 CLEAR→BUILD 的来源顺序及 Hint 引用，执行候选只表达融合净变化。只有同物理合约已核实的仓位与显式选定策略能获得候选资格。
- [x] P3 使用 `iter_historical_inputs` 和 `iter_historical_segments` 消费已封存的 MDS 结果。新主力单独预热，允许其历史前缀与上一主力重叠。生命周期证据若参与动作资格，调用端须提供截至该 Bar 已证明的前缀；日周价格质量断点开启新计算段。P3 用 `next_executable_minute` 查严格后继的合法开盘。
- [x] P5 使用 `consume_completed` 提议成对提交的行情水位与策略状态。Canonical 预热结束后保留同 owner 的 Core 状态，使用独立前向水位。配置校验保留 60/16 正式规格和 70/20 隔离上限，退出中品种计入名额，物理订阅独立计数。持久化、对账与执行仍在 P5。
- [x] 定向验证覆盖六周期、逐条与分批、检查点恢复、未来日周数据、换月及两档 fixture 容量。运行 `test_v2_completed_market.py`、`test_v2_completed_decision.py` 和现有聚合、Session、公式、参考回放回归。设置 `GUIYI_P2_FROZEN_FU` 指向已存在的 P0/P1-A FU2603 冻结目录，可复验已核验 SHA-256 的 5m 动作。P6 单列端到端时延及现场测试。

## P3 · 一个真实合约、趋势、5m，跑通历史切片

- [ ] 选有完整冻结证据且含可核验一开一平的物理合约。分别记录 bar_end、历史可用时点、信号及最早合格成交分钟。缺费率/结算或价格资格时记录阻断；不在主连价格生成成交。
  FU2603 的 2026-01-05 实际 Canonical 输入已走完试验链路。正式系列仍为
  `RANK1_AS_KNOWN_UNPROVEN`，前一交易日缺六个在册 FU 合约的日线证据，Catalog 排名亦为事后录入。
- [x] 隔离 PostgreSQL 已建 run/trade/equity 与成功版本指针。`GET /api/v1/newow/backtests/latest`
  按品种、策略、周期和研究配置查摘要，`/{run_id}/trades` 与 `/{run_id}/equity` 读取固定成功 run。
  API 无结果时返回空状态；失败保留旧成功指针；正式与试验系列各自独立。
- [x] 使用 `test_v2_backtest_results.py`、RQAlpha 原生用例和真实 FU2603 冻结输入验收决策、时序、费用、
  权益、查询与分页。跨月首版明确阻断，既有带仓结算与无入场 CLEAR 保留验证。
- [x] 在真实隔离 PostgreSQL 验证迁移、提交前不可见、事务回滚、重试、乱序发布、固定 run 分页与现役研究回归。
  P4 可用已核验试验系列联调，资格完整的正式结果仍依赖上一项证据。

## P4 · 打开工作台，接盘后更新，再扩矩阵

- [x] develop 隔离预览接入现有牛哇主图和历史回测面板。重放真实 FU2603 冻结试验，读回 8 笔成交和结算权益。正式资格失败、切换、输入切片及固定 run 翻页覆盖，旧参考、消息和独立账户入口保留。
- [x] 隔离盘后消费者复用 Canonical 持久化成功凭证与 P3 原子发布。覆盖同日修订与冲突、重复凭证、事务回滚、已知未提交恢复和已发布旧页可读。仍采用全量重算，无增量检查点。
- [x] 三策略六周期冻结与预热通过隔离回归，四个分钟周期经原生 RQAlpha 执行。日线和周线在现有同 Session 执行模型下显式阻断跨时段成交。覆盖夜盘、短 H1 和因果修订。正式仍为 60，隔离市场容量上限为 70。
- [x] 隔离 PostgreSQL、PC 真实回测路由、受影响 Web/API 和 OpenSpec 验证通过。FU2603 正式资格仍为 `RANK1_AS_KNOWN_UNPROVEN`，未补写正式数据。自然盘后启用、正式行情主图与历史跨月执行不属于本次隔离验收。

## P5 · 一个仿真账户，先离线证明只会发一次

- [x] `services/newow-vnpy` 接入 P2 completed 输入及 VeighNa 原生事件、请求和开平转换。一个账户写入者，正式规格 60/16，隔离上限 70/20。按交易所、品种、部署排序仲裁同批增仓。缺账户、风险参数或已有仓估值时禁增风险。
- [x] 隔离 PG 原子保存水位、决策、检查点、意图和预留。以当时已知的账户、成交和失效前缀计算决策。持久化单次领取后才向 fixture 分派。未知不重发，回报按原生身份去重，平仓发送前复核实际可平与今昨仓。
- [x] 退出进入 DRAINING，保留旧物理合约义务与受限的显式减仓入口。新启动重取资金、持仓、活动单和当日成交的完整读回。Web 后续使用隔离只读 `GET /api/v1/newow/trading/` 投影。
- [x] 在 M4 锁定环境及一次性 PostgreSQL 16 运行 `python -m pytest -q tests`，53 项通过。原 `simnow_execution`、`test_native_portfolio.py`、`test_subing_model_api.py` 加新 GET 投影共 196 项通过。离线边界、命令和 P6 待验项见 [宿主 README](../../../services/newow-vnpy/README.md)。

## P6 · M4 容量和现场分项

- [x] 2026-11-24 在同一台 Mac16,10（Apple M4、16 GiB、1 TB 外置 SSD）完成 60/16 与 70/20 的独跑及单项回测并发四组。固定源码 `d373064d71a591c42c380dc927e816f793a5dbb7`，P5 隔离 PostgreSQL 16 离线复验 53 项通过。每组 110 个热批，覆盖 45 分钟代表性逻辑时段和另行标注的 20 个六周期合成同步峰值。预热排除，p95/p99 按排序最近秩计算。
- [ ] 四组均未通过 p95 ≤ 5 秒、p99 ≤ 10 秒。合成峰值四组均为 20/20 超过 60 秒，代表性回放各端点均在 60 秒内处理完，停流后离线回报队列排空。持续自然 M1 积压、真实行情到达延迟、历史读次数和 Web 或 Research 更新前后的 Trading 身份尚未验证。P5 逐组核对输入、决策持久化、单次 fixture 委托和成交去重通过。
- [ ] P1-B/P5 的 ARM64 SDK 原生导入、离线网关初始化及注入回报已验证。独立 CTP MD 权限、实际订阅及收包未执行。SimNow TD 只读登录、无结算写入、资金/持仓/活动单/当日成交四段读回与对账未执行。实际向 SimNow 发送受控模拟委托、原生报单关联及柜台回报未执行。现场验收须明确环境、时段、最大手数、品种和退出政策。证书信任链严格验证仍待验。

| 组别 | p95 秒 | p99 秒 | 最慢批次 秒 | 代表性端点最慢 秒 | Trading 峰值 RSS MiB | 超一分钟峰值 |
|---|---:|---:|---:|---:|---:|---:|
| 60/16 独跑 | 67.72 | 69.91 | 72.04 | 28.88 | 264.98 | 20/20 |
| 60/16 并发 P4 回测 | 67.79 | 70.75 | 71.73 | 29.27 | 264.02 | 20/20 |
| 70/20 独跑 | 93.53 | 115.51 | 123.21 | 39.52 | 367.06 | 20/20 |
| 70/20 并发 P4 回测 | 116.22 | 123.52 | 131.39 | 48.95 | 372.53 | 20/20 |

两个并发组各调用一次 P4 FU2603 冻结回测，均只与一个同步峰值重叠。RQAlpha 分别用时 7.51/7.56 秒，峰值 RSS 175.56/172.55 MiB，各复现 8 笔成交、4.923 元费用及 9,765.077 元权益。独跑也超限。70/20 并发组尾延迟更高，但单次回测的实际重叠范围不足以量化因果影响，且各组宿主 I/O 和 swap 活动不同。

[复现证据](evidence/p6/environment.json)保留运行身份、固定回测包 SHA-256、精简回测读回、四组逐批样本、进程 RSS/CPU、PG 读计数、宿主 swap/磁盘计数、[测量入口](evidence/p6/bench.py)和[只读复算入口](evidence/p6/summarize.py)。汇总复算用 `python3 -B openspec/changes/guiyi-v2-rearchitecture/evidence/p6/summarize.py`。复跑时沿用 [P5 README 的隔离 PG 与 macOS 沙箱](../../../services/newow-vnpy/README.md#隔离验证)，将 pytest 调用替换为 `<证据目录的绝对路径>/bench.py --market 60 --owners 16 --source <受测提交的源码> --output <全新输出目录>`。70/20 组使用 `--market 70 --owners 20`。并发组增加 `--parallel --packet <P4 冻结包> --research-python <P4 锁定解释器>`。

## P7 · 真实切换与退役

上线前先通过拟启用规模的容量复测，并完成授权范围内的独立 CTP 行情、SimNow 原生对账及模拟委托验证。切换涉及的正式历史结果需补齐 P4 数据资格与适用成交合同，包括 FU2603 的当时可知 rank1 及日周线跨 Session 执行范围。分组件变更需证明 Trading 运行身份与持久投影连续，再按以下步骤核清旧消费者、恢复引用与受保护的原件。

- [ ] 根据此时 HEAD 形成按现役标题匹配的 MODIFIED/REMOVED delta；检查消费者、保留的原件与恢复引用。切换合同须严格校验并独立 Review；产品/架构/决策文档与生效批次同步。
- [ ] main/tag、Runtime promotion、生产 PG/湖写入和删除分别以明确授权为准。dry-run 固定环境、对象、数量/身份、可恢复依据与停止点；先切一个品种读面并核对，才扩范围。读面失败保留最后已核实读取身份；账户结果未知先读回。
- [ ] 核对旧 Worker、旧预警生产者及自研回测零未决义务、零剩余消费者；共用进程仅退役相应职责。删除白名单须与待删对象、删除后差异相同；历史行情、旧观察原件、独立账户与恢复依赖完整。分别报告开发、实际发布、运行身份、实际业务和清理读回。

## 需求—交付核对

| 需求 | 主责批次 | 验收证据 |
|---|---|---|
| M01、M02、S01、S02 | P2、P3 | 单源、Session、可用时点、前缀与快照 |
| M03 | P4、P5、P6 | 70/20、配置原子性、退出中计数及满载样本 |
| R01 | P1、P3 | 引擎真实回放、手算、换月/期末与无成交 |
| R02、R03 | P3、P4 | 隔离 PG、旧指针/游标稳定、全量/增量对照 |
| T01、T02、T03 | P5、P6 | 独占、仲裁、崩溃重放、部分成交和现场读回 |
| W01 | P4、P7 | 只读面板、独立 Tab、旧消息回归 |
| O01、O02 | P6、P7 | M4 采样、组件身份、旧生产者和保护对象读回 |

## 可直接复制的 Codex Goal

```text
/goal 在归一量化最新 develop 上完成牛哇 V2 的离线开发与集成。以 openspec/changes/guiyi-v2-rearchitecture/ 下的 design.md、tasks.md 和六份规格为准。目标是观察行情、策略计算、共享账户执行和 Web 查询能独立维护，新增策略可直接复用数据与决策入口。

我批准 tasks.md「目标模式开发范围」中列明的隔离实现、测试、独立 Review，以及通过后的 task → develop 集成。使用 GPT-6.2 Sol、中推理。先核对 HEAD、工作区、已合入代码和已有验证，按现状续做。从最新 develop 建独立 task worktree，保护其他改动。

先复算 P6 原始基线，对普通报价、只观察收线、可执行候选、柜台回报分段计时。依据实测选最小改动并实现，保留共享预算、幂等、检查点、未知提交不重发及回报恢复语义。用原四组 M4 基准分别验 p95 ≤ 5 秒、p99 ≤ 10 秒；不得改样本、缩负载或弱化断言。继续完成已有冻结样本的历史资格回归、现有 Web 只读联调和故障恢复验证。复用现有模块，未证明需要时不新增框架、数据源或第二套账本。

某一项缺机器、私有样本或许可时，明确记录未验证项，继续其他独立工作。需改变公式、成交/费用/风险合同或真实操作范围时，只暂停相关动作。生产库与数据湖、柜台连接及报撤、真实通知、main/tag、Runtime 均另行授权，保持 auto_order=false。

以代码、原始测量、受影响测试、独立 Review 和远端 develop 的提交为准。按仓库规则集成并核对后，只清理本任务已合并且干净的分支/worktree。交付已完成和阻塞项、四组数据与基线对照、故障恢复结果、集成 SHA，以及仍需现场批准的步骤。
```
