# 首批 41 品种周线 Implementation Plan

> 执行者：一个 Terra medium 主任务，使用 executing-plans 按序推进；共享实现串行收敛，
> 时间、质量和身份改动按仓库要求安排独立 Review。执行记录使用下方复选框。

**Goal:** 交付固定 41 品种的可信完整周快照、三策略和参考交易页面，并完成获授权后的部署与自然更新验收。

**Architecture:** 复用统一 Canonical/Catalog/MDS/reader；Newow 服务层解析完整周并独立表达当前信息。
产品能力明确限制首批 41，维护与只读消费者检查分离，不建立另一套行情、缺口或调度系统。

**Tech Stack:** 现有 Python、SQLAlchemy/PostgreSQL、Parquet、quant-core、Vue/TypeScript、pytest、Playwright。

**Spec:** [首批 41 闭环设计](first-41-closed-loop-plan.md)。先读该设计，再按需引用 [原周线质量设计](design.md)。

## 全局执行合同

- 本轮 owner 已要求开始处理；不要再以技能流程为由要求批准相同设计。普通测试失败自主定位修复。
- 本文优先于旧 60 品种任务的执行分母与交付顺序；业务质量/时序合同仍以当前 accepted canonical 为准。
- 固定首批 41，分母 41 品种、123 策略组合。41 是上一轮历史依赖通过清单，不代表当前输入永远通过。
- D1 60 品种必须保留；其余 19 周线、60m、完整跨周期 explanation 保持未开放；不修改 operational/Alert Scope。
- 三策略公式、参数、参考价格和收益口径不变；W1 快照/质量身份版本化，禁止无意改变 D1 Trade ID。
- 默认入口不能硬编码日期；历史固定截止回归与墙钟默认入口测试分别保存。
- 不打印凭据；既有 loader 安全加载 project.env，不读取文件内容到上下文。只读 DB 使用 readonly_transaction。
- 禁止从测试或 HTTP GET 构造真实 provider。隔离预览不得启动正式 app 的 scheduler、writer、通知或 Runtime。
- 生产下载/写入、持续维护扩围、main/tag/Release、Runtime promotion 分别需要明确授权；本计划不授予这些权限。
- 外部 Gate 未获授权时完成独立工程、测试、只读验收和精确 prepare，报告受影响部分，不提前停止所有工作。
- 一个版本只维护一个 evidence 索引和逐品种结果；复用原生 report/receipt，不编造 audit accepted=策略 READY。

## 固定顺序与证据位置

```text
批次 A / 6：AU RB CU BU PD PT
批次 B / 17：A AG AL AO AP C CF EC FG FU HC I JD JM L LC LH
批次 C / 18：M MA NI P PB PP PS RM RU SA SC SN SS TA UR V Y ZN
```

执行树内选唯一 `outputs/newow-weekly-first41-<本次日期>/`，存在旧执行时采用新的非覆盖目录。
只保存脱敏代码/config/Canonical/scope 身份及 hashes。原始证据在源工作区可只读访问：

- `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-historical-inputs-20260918/`
- `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-deploy-readiness-20260918-r2/`

它们未必随 Git 进入新工作树，不能因本树无 outputs 就宣布旧证据不存在，也不能把旧 evidence 当新结果。
2026-09-18 基线已从 d7e4d5a76 前进到 a223ece1f（D1 报价随已接受快照）；开始前刷新最新 develop。

## 任务 0：工作树、依赖、现场和可恢复进度

**读取：** AGENTS.md、STATUS.md、docs/DEVELOPMENT.md、TESTING.md、相关 Newow/data canonical。

- [ ] 确认宿主已创建 linked worktree，不再嵌套建树；记录 branch/HEAD/git status/worktree list。
- [ ] 若宿主从 main 默认基线创建，先在自己的干净任务分支吸收已核验 develop（含 a223ece1f 及本计划），
  不能在 main 或源 develop 上直接实现。使用 `codex/` 任务分支；不 reset、覆盖或清理其他修改。
- [ ] 检查 D1、AU、PD/PT、AP、W1/60m 工作树的相关共享文件。只复用已验证提交，不盲目合入整个旧分支。
- [ ] 读回本计划和设计。若新树缺文件，先读取源工作区绝对路径，再吸收计划提交，不能据此重新设计整个项目。
- [ ] 使用既有 Python/Node 依赖；确认导入路径实际指向执行树，Canonical 指向已校验生产数据根。
- [ ] 创建单份执行索引，记任务阶段、当前品种、最后通过命令、外部 Gate；中断后从此恢复，已完成项不重跑写入。
- [ ] 跑一个 D1 snapshot/reader 基线测试与 AU 只读 W1 依赖 smoke；原生报告必须非空、可解析、有终态。
- [ ] 刷新 41 的依赖与来源证明，先逐品种单进程读取；max_work=10000、每品种 300 秒为初始边界，
  超时明确 incomplete，再按实际风险调整只读预算，不缩小窗口或分母。
- [ ] 为每品种记录产品历史窗、参考统计窗、owner 前预热及全部开放 section 的依赖覆盖。

**出口：** 正确基线和执行树；41 个已核对/未检/阻塞完整分母；provider=0、生产 writes=0。
预算不足或现场暂不可达时继续不依赖现场的工程；不可把 smoke 成功记作全域通过。

## 任务 1：41 品种能力合同与三种时间身份

**修改：** `services/quant-api/app/market_data/newow/product_release.py`、`app/api/market_newow.py`、
`app/schemas/market_newow_product.py`、对应 Newow spec；前端 API/types 随合同更新。

**输入：** 单一版本化 41 清单、product/frequency/section。**输出：** 可复用范围校验、capabilities 元信息。

- [ ] 先增加反例：41×1w 有资格；其余 19、60m、完整 explanation 不开放；D1 60 保持原行为。
- [ ] 让默认快照、显式 as_of、所有 section、历史入口、comparator 和预览使用同一个产品范围校验。
- [ ] 添加 product-aware 检查，避免旧的 frequency-only helper 绕过范围；范围不是数据 READY 结论。
- [ ] 定义 requested_at、expected/available_period_end、snapshot_as_of、publication/freshness、current_context。
- [ ] 同步 canonical 和 schema 版本；禁止把待发布、维护失败、数据损坏合成一个 pending。
- [ ] 测试不在 operational 清单、大小写/非法 symbol、scope 版本变化、深链接绕过和旧客户端兼容。
- [ ] 通过定向测试后提交本任务范围；候选开关仅作用隔离代码，正式 Runtime 不改。

**出口：** 后端为唯一开放资格权威；可见能力与实际路由一致；未开放不能被 matrix 计为已通过。

## 任务 2：周来源质量与计算/参考交易中断

**修改：** `app/market_data/` 下 coverage、MDS、既有 source/weekly quality 与 reader；
`packages/quant-core/guiyi_quant/newow/product_adapters.py`、`reference_trades.py` 及对应证明/缓存。
**测试：** `services/quant-api/tests/data_foundation/` 中相关覆盖/存储测试；`tests/newow/` 的 adapters、reader、
reference_interruptions、reference_statistics、replay_invariants、snapshot_cache。

- [ ] 先复现 D1-only quality 边界，并核查旧工作是否已存在可复用实现，避免复制第二套 weekly classifier。
- [ ] 完整周证明逐端点检查同合约 D1 正常/缺价事实；未知缺日、重复、错合同、hash/revision 冲突 fail-closed。
- [ ] 正常 W1 与 D1 来源存在冲突时标阻塞，不能只因 W1 可读继续验收；无来源证明则保留 source-unverified。
- [ ] 周中断无 OHLC；完成端点之前不可注入正式 replay，NO_TRADE 不产生中断也不推进有效预热。
- [ ] reader 返回一致的 Bar/quality/segment 身份；预主力前缀、owner 内、chart/reference 分窗证明不互相矛盾。
- [ ] 断后以有效完整周重新预热；跨物理合约/区段不配对，初始 HOLD 不伪造 BUILD。
- [ ] CLOSED 历史保留；中断 OPEN 不伪造退出价格或收益；当前 READY 与历史 PARTIAL 独立报告。
- [ ] 添加 prefix invariance、batch/incremental/restart parity、跨月周、短 owner 零周、混合缺价/未知缺日回归。
- [ ] 保存 D1 Trade ID 与数值回归，W1 新版本不能因共享常量改动波及 D1。
- [ ] 将新发现的数据差量交任务 7；其他可测工程继续。混合零价周改变 OHLC 语义需 owner 决策，不能擅改。

**出口：** 周质量传播完整，通用 strict reader 未放松；真实坏输入保持坏，隔离 fixture 只证明工程行为。

## 任务 3：完整周快照服务

**修改：** 现有 `daily_snapshot.py`、新增同目录最小 completed-period 模块、reader/service/cache、API/schema。
**测试：** `test_daily_snapshot.py`、新增周快照用例、`test_market_newow_product_api.py`、`test_product_snapshot_cache.py`。

**输入：** product、频率、墙钟 requested_at，以及 Calendar/Session、维护事实与当前 Catalog/MDS。
**输出：** 与策略盈利或 READY 无关的共同周截止；同品种三策略绑定同一选择，面板返回各自状态。

- [ ] 测试周一/周内默认请求在当天 Map 不存在时，仍能验证上个完整周，当前 owner 显式未知。
- [ ] 测试周五收盘前、收盘后未发布、已发布、维护失败/卡住；只凭 Map 缺失不能判断“正常待发布”。
- [ ] 仅可证明的末尾待发布允许紧邻前一周；历史内部缺口、来源冲突不能后退，也不能循环寻找成功周。
- [ ] 测试新周已证实中断/预热不能退回旧 READY；同周中断必须按任务 2 的新事实展示。
- [ ] 通过 authority 处理节假日短周、跨年 ISO 周、不同 Session、夜盘；禁止自然周五硬编码。
- [ ] 实现请求取消/30 秒有界解析、输入 revision 校验、schema/policy/频率缓存隔离。
- [ ] D1 采用兼容适配，保留已批准的 D1 回退边界；不把 W1 政策全局套入所有 reader。
- [ ] 先运行单元、再同输入 API 验证；所有元信息与真实 cutoff 一致。

**出口：** 新周端点、可用周端点和当前身份严格分开；错误无法被历史搜索掩盖。

## 任务 4：页面与六品种垂直验收

**修改：** `apps/quant-web/src/api/newowProduct.ts`、`src/types/newowProduct.ts`、
`src/composables/useNewowProduct.ts`、`NewowProductWorkspace.vue` 及直接相关面板。
**测试：** `useNewowProduct.test.ts`、相关参考面板测试、`e2e/newow-product.spec.mjs` 与既有 helpers。

- [ ] 默认页面先取得 W1 快照，后请求各面板；当前状态独立显示，历史 OPEN 文案包含截止。
- [ ] 处理待发布、过期、错误、预热、中断和无交易；空收益不转成 0%，没有信号不算错误。
- [ ] 品种/周期/策略切换取消旧请求，重置分页和 token；迟到响应不能覆盖新页面。
- [ ] 读取候选 preview 的身份校验合同；若现有固定时间 preview 不支持墙钟默认解析，做最小只读扩展，
  不用普通 app 启动器绕过隔离，不沿用旧 preview identity。固定时间 fixture 不能替代墙钟验收。
- [ ] 每次启动候选核对端口未占用、代码/config/Canonical 身份；不得终止其他任务进程，不暴露秘密。
- [ ] 按 AU→RB→CU→BU→PD→PT，每品种三策略检查 chart、全部开放副图、reference/performance/comparator。
- [ ] 浏览器自然首次加载检查主图、默认副图、参考卡片和截止；不携带固定 as_of，不预热、不刷新后补绿。
- [ ] 保存首次失败及修复后的新一次结果，记录请求耗时、错误码、快照、输入 revision 和页面证据。
- [ ] 跑历史分页、交易定位、切换与旧响应隔离交互。测量资源，确认可推广到 41。

**出口：** 六品种 18 组合工程/真实读取/页面状态各有证据；未知或 source-unverified 不计通过。

## 任务 5：扩大至固定 41

- [ ] 批次 B 再批次 C，按上方顺序串行；不并发轰击生产 DB/磁盘。
- [ ] 每品种依次：输入与来源→统一快照→三策略各 section→默认浏览器首载→历史交互→独立结果读回。
- [ ] 逐项记录 data_ready、source_quality_verified、strategy READY/WARMING/INTERRUPTED、page_verified、
  available/expected 周截止、current_context、错误原因；不要用一个 accepted 字段概括全部。
- [ ] 总索引明确已完成、失败、未开始和超时；123 策略组合必须全覆盖且没有 budget_exhausted 冒充完成。
- [ ] 同一品种阻塞不阻止其他独立只读/工程任务。修复共享代码后，重测受影响批次并记录新的精确 commit。
- [ ] D1 全 60×3 回归；默认入口和历史 cutoff 分别测试，保留默认报价随 snapshot 的 a223ece1f 行为。
- [ ] 核对其余 19、60m、explanation 都仍未开放。正常历史、历史中断而当前恢复、当前预热分别汇总。

**出口：** 41/123 完整分母，真实成功与合法状态透明，未完成项不能通过缩 scope 消除。

## 任务 6：盘后消费者验证与新主力接续

**修改/测试：** `app/market_data/after_market.py`、maintenance/planner、相关 health/public schema，
`tests/data_foundation/test_after_market.py` 与直接相关 planner 测试、DATA_CENTER.md。

- [x] 为消费者审计添加 W1 41 范围，复用 D1 有界执行骨架；维护终态/锁释放后新只读事务运行。
- [x] 测试输入修订在检查中改变、锁忙、超时和未检项；不能写成功，不启动下载、retry、通知。
- [x] 分开 canonical_updated 与 consumer_checks.newow_w1；按合法策略状态验收，不强制所有都 READY。
- [x] 依据六品种耗时确定 D1+W1 总预算；如无法在既有边界完成，先优化重复读取与可复用证明，
  必要调度/持续运行边界变更需写明决策，不无界延长或省略检查。
- [x] 新 owner 的物理预热以真实消费窗口验证；已有 update 若不覆盖，复用 ContractWarmupPlanner 生成差量，
  在数据维护阶段执行，消费者只读阶段不执行 mutation。
- [x] 默认关闭任何新增生产 writer/扩围行为。需要持续授权时生成可审查范围与实测请求/字节/时限预算。
- [ ] 假时钟验证完整周发布→Catalog/MDS→消费检查→默认页面及重启后的同一结果。

**出口：** 持续维护代码与授权差量明确；自然周事件尚未发生时保持待验证，不能宣称 Runtime ready。

## 任务 7：必要数据差量与外部 Gate

- [ ] 无差量时标记 no mutation needed，不制造补数动作；有差量用原生 planner/prepare，禁止沿用旧包直接 apply。
- [ ] 包中固定环境、代码、41 范围内合约、D1+W1 窗口、expected endpoints、plan hash、已有分区保护、
  provider 请求/字节/时限预算、锁、首次失败处理、幂等及恢复方式。
- [ ] 在真正操作前检查本任务已有授权是否覆盖且未消费；不足则向 owner 一次请求具体批次授权。
- [ ] 获批后串行执行，并用独立只读进程核对 Catalog pointer、文件 hash、MDS 精确端点/质量和 replan。
- [ ] partial/结果未知不自动重试或回滚已提交分区；只读查清，按授权恢复边界处理。
- [ ] 补数影响 D1 时重跑对应 D1/历史引用测试；任一新 code/data revision 使旧受影响证据失效。

## 任务 8：Review、集成、候选与交付

- [ ] 定向验证后跑相关模块、Web test/build、OpenSpec、secret scan、diff check；命令见下节。
- [ ] 独立 Review 固定 base/head，重点审快照退让、来源/质量、参考配对、产品范围、缓存与生产副作用。
- [ ] Confirmed Issue 修复后复测；Risk 标明是否阻断本版，不用 finding 数量衡量 review。
- [ ] 仅暂存/提交本任务文件，普通 commit/push 和条件满足的 develop 集成按当前流程完成，保留无关修改。
- [ ] 集成后冻结 exact candidate，验证代码与数据身份，复验受影响真实矩阵；旧分支结果不覆盖新候选。
- [ ] 完成 release 包和 Runtime 包：精确版本/差异/服务/兼容回退/验收命令；未获授权不得 main merge/tag/release/switch。
- [ ] 授权后按 release-agent 执行；本机和公网各 123 W1 默认首载及 D1 默认回归，记录实际服务版本。
- [ ] 未获外部授权时交付 CODE_COMPLETE_EXTERNAL_GATE_PENDING 和唯一明确下一动作，不声称闭环全部完成。

## 任务 9：自然更新验收

- [ ] 部署后使用已授权自然维护结果证明下一完整周发布、123 消费者状态及随后开市时段默认使用。
- [ ] 不为取证手动重跑定时任务、不新增提醒自动化或发送通知；未来事件未发生则自然 Gate 待验。
- [ ] 自然换月没发生，保留确定性/历史回归已过与自然待观察；不能生成假现场证据。
- [ ] STATUS.md 只按真实完成阶段更新；最终列41品种完成/未完成、123组合状态、外部Gate及最小下一步。

## 验证命令入口

先确认以下解释器存在且导入当前树；新测试创建后加入对应组。只读现场命令需先安全加载项目配置，
不可使用 ambient `.env` 误选 Canonical。下面不包含任何 provider/apply 命令。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_daily_snapshot.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow \
  services/quant-api/tests/data_foundation/test_after_market.py

pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git -c core.fsmonitor=false diff --check
```

E2E 使用 TESTING.md 对应 Newow fixture 和真实只读候选入口；先读当前 Playwright/preview 配置，
不得把固定截止 fixture 截图当真实默认页，不使用 `--update-snapshots` 消除未解释差异。

## 进度和暂停规则

每完成一个任务更新复选框和最小证据引用；耗时任务持续给出有意义进度，普通失败自行修复。
需要 owner 的仅限真实语义歧义、覆盖他人修改、权限扩大或未授权外部动作。
已授权普通工程不得因为未来存在生产 Gate 就停在“给出建议”。所有可独立完成的准备应先完成。
暂停点报告精确失败、受影响品种/阶段、已完成部分、可继续工作、所需最小决定；不得静默跳过失败测试。
