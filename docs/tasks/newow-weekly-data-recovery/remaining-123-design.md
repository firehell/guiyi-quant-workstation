# 牛哇周线剩余 1–3 项设计

日期：2026-09-14。状态：DESIGN_REVIEW_COMPLETE；仅设计与工程开发委派，不是新一轮真实下载或正式写入批准。

## 目标与边界

用户要求将剩余三项交给一个 Sol high 任务连续处理：普通 W1/D1 补数、EC2607 失败执行器修复、新增 RS2309/RS2311 专项。执行顺序为先修复共用执行链，再普通补数；RS 专项的本地检查可穿插，真实请求串行。

不包含第 4 项完整 180/540 组合、页面/browser 总体验收；不包含发布、main/tag、Runtime、Scope、通知、策略或 ReferenceTrade 语义变更。单次补数后的严格 MDS 回读和原生 replan 属于本范围必要验证。保留 W1 优先及同源 D1 companion，不顺带启动 60m。

用户已明确不要求配额预算、流量预测或校准；不再设计这些前置步骤。但目标/hash、环境、真实操作意图、维护锁、质量校验与失败停止仍必须保留。

## 当前事实与证据边界

设计时主仓库 develop/origin 为 `b32d9b0f791e1e0c2cc009b5fcedce49013f574e`。它新增了 Session 查询 trading-day 下界修复，开发任务必须保留。父任务 `codex/newow-weekly-60@c60e147f` 仅保存本设计，不能作为实现基线。创建任务时再次核对最新 develop。

证据根为 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-data-recovery-20260913/`。旧任务分支 `codex/newow-weekly-data-recovery@40b1f05c6` 仅有文档/evidence 记录，尚未合入 develop；不得把临时执行器当作已集成代码。

| 项目 | 已有证据 | 本次处理 |
| --- | --- | --- |
| 247 个 Session 目标 | 四批已写入 33,224 行、8,708 日期 | 不重做；只读确认当前状态 |
| MainContractMap | 冻结历史区间 49,513/49,513 个日期映射齐全 | 不造新的映射 writer，不外推今日状态 |
| 普通候选 | `post-metadata-dependency-project-env-5b31cf7c-asof-20260913/` 完整依赖审计有 1,139 PROPOSED、11 REVIEW_REQUIRED、metadata=0 | SI2308 随后完成，尚无新的全量余额；先刷新，不能把 1,139 或直接减一当成当前精确余额 |
| SI2308 | `canonical-pilot-si2308-20bff850/` 两分区成功，MDS 9/9，replan targets=0 | 排除已完成对象 |
| EC2607 | `canonical-pilot-ec2607-5c7a1deb/` 本地断言失败，8 目标仍在；Catalog/物理文件均 0 | 修复后另一次有界尝试，旧意图已消耗 |
| PF2611 + 原九个 RS | `source-verification-ab15a71d/` 41 个已核验异常点的七字段与权威来源一致 | 保留来源异常，不重复普通补数或篡改价格 |
| RS2309 / RS2311 | 新发现，尚未完成来源核验 | 单独形成当前精确异常范围，不借用原九个 RS 结论 |

有效依赖审计 hash 为 `4df491b7508887127488369f19427f379623e46341b75df5e1022d765356802e`，as-of 为 `2026-09-13T06:36:13+00:00`。不带 `project-env` 的相邻旧审计使用了错误配置，已失效，不得作为执行输入。

## 设计选择

继续使用 `HistoricalDataManager.contract_warmup`、原生 adapter、Canonical/Catalog 和 MDS。新增一个仓库内薄恢复执行入口，替换按合约复制且链式导入 `/tmp` 文件的执行器。它只负责编排、作用域绑定与执行证据；不新增数据权威、补洞算法或通用维护平台。

EC2607 原生 8 个逻辑目标为 2026 年 2–5 月 D1/W1，共 84 根。失败原因是旧执行器把 April 来源窗口写死为 4 月 1 日起，而原生 W1 为覆盖 4 月 3 日周线需要从 **3 月 30 日** 起。错误发生在 provider 返回后、本地断言阶段；没有进入 Canonical 写入，但此前实际 provider 调用数没有可靠落盘，必须标为 unknown，不能写成零。

不直接执行 `/tmp/guiyi-ec2607-w1-retry-5c7a1deb.py`。单改日期仍保留临时模块依赖与迟落盘缺陷。禁止为每个合约再硬编码 physical call 列表或最大调用数。

### 原生请求与执行观察

- 逻辑输入绑定原生 plan hash、symbol、physical contract、frequency、through、每个目标身份及运行环境。原生 manager 继续在 maintenance lease 内重算并校验 hash，然后执行既有 projection invalidation 和 writer。
- W1 来源日集合只复用 adapter 的 ISO 周展开、Calendar 与挂牌/到期裁剪；D1/W1 继续共享一次 `fetch_many` 的来源 cache。不得新写第二套 ISO/缺口 resolver。
- 若需要预先展示允许来源区间，将现有 `_weekly_bars` 的来源日展开抽为一个私有纯查询 helper，由读取与恢复 preflight 共用。不要模拟 provider 返回来“预演”请求，也不要增加外部流量预测。
- 授权对象是明确的逻辑目标及其原生完整周来源范围，不是猜测的 SDK 请求次数。真实调用前检查 contract、method、日期范围属于冻结的允许区间；越界在调用前拒绝。共享 cache 实际减少多少请求，只记录实测。
- 通过 adapter/client 的最小可选观察接缝或受控 client 包装记录调用，不 monkeypatch 进程全局或自行实现 `fetch_many`。默认路径行为不变；禁止分钟接口、连续合约替代或额外元数据下载。

### 不丢失且不冒充授权的执行证据

一个 attempt 使用独立目录，复用现有 plan/result/readback 结构；仅增加必要的逐请求 journal 与受限来源 payload。它们是审计材料，不是自动重放、自动重试或独立行情读取入口。

新的准备产物默认写在新任务 worktree 的 `outputs/newow-weekly-recovery-attempts/` 专用忽略目录内，不覆盖主仓库旧 evidence；该目录中的 prepared、attempt、journal 与大型行情 payload 均不进入 Git，也不会令逐单元 clean-checkout 门禁自我阻断。其他未跟踪文件仍会 fail-closed。正式目标根只来自经过绑定的生产配置，不由输出目录或输入文本推导。

1. 输入验证、配置身份、计划漂移、文件可写性与 journal 初始化都在 provider/正式 mutation 前完成。只使用现有配置加载方式读取 `project.env`，不展示、复制或记录凭据，缺配置不回退 primary `.env` 或仓库默认数据湖。
2. 调用前持久保存 started 记录并 flush/fsync；失败则零次调用。provider 返回后，先原子保存白名单来源字段与 hash，再记 response_saved，再进入本地验证/聚合。不得依赖整个 warmup 成功后才写统计。
3. journal 不保存原始 SDK 异常文本、配置或连接信息。异常使用受控 code。started 无对应 response 的请求统一为 outcome_unknown，禁止把它算作未请求并重试。
4. 保存失败或来源身份校验失败立即停止，将已返回但未可靠保存的结果记为 unknown；不得绕过门禁继续写入。来源 payload 不经原生 hard validation 不能直接恢复为 Canonical。
5. plan、当前执行代码身份、配置/数据根非敏感指纹与 fresh 单次意图要关联。prepare/apply 均要求 checkout clean 且 HEAD 精确一致，从而由 commit 绑定全部 tracked 执行依赖；apply 在首次 provider 调用前原子保存包含 prepared hash 与上述身份的 invocation receipt。文本字段写“owner approved”不构成批准；旧脚本 hash、旧会话或失败前批准均不可继承。
6. 每个成功单元原生提交后执行严格 MDS/Catalog/物理 hash 回读及 replan；COMMIT_OUTCOME_UNKNOWN 时冻结后续工作，只读对账，禁止自动删文件/回滚 active pointer/重试。

### 普通补数队列

刷新同一冻结历史 as-of 的 60 品种依赖审计，必要时明确另列当前 as-of；不混用分母。只从当前 PROPOSED 原生计划提取队列，排除已完成、REVIEW_REQUIRED、SOURCE_EXCEPTION、metadata 未满足、完整性不明对象。保存前后余额与分类迁移，不能用“请求成功数”替代数据就绪数。

先 EC2607 单个试点：原始 hash `5c7a1debdae9001497638f747b9ec0eb8cca2c8b3cf66e32ec28351b353dae72` 仅供比较，必须现取；若漂移，输出新差异与新 hash，不执行旧包。通过后按固定顺序形成有限批次，每批最多 20 个逻辑 contract-warmup 计划，单个计划不可为凑数量拆断完整周。20 是失败影响与交接上限，不是配额估算。每批列明所有目标、根目录、必要 projection invalidation、原生来源边界、hash 和回读方式。

执行一个获批批次可以包含明确列出的多个串行单元；每单元前重验原生 hash。漂移、首次异常、来源质量错误或 unknown 时停止整批，记录先前已成功的单元和未尝试尾项。不得自动重试、无限队列刷新后继续、或对未列入包的目标下载。重新形成剩余包并取得新的精确意图后才继续。

### 新增 RS 专项

- RS2309：初始诊断范围到 2023-06-28，2023 年 6 月 D1/W1 非正价格与端点缺失。
- RS2311：初始诊断范围到 2023-11-01，D1 2023 年 1–6 月和 11 月，W1 1–6 月；6 月同时有端点/周上下文问题。
- 以上是定位索引，不是最终下载清单。先从当前 Catalog URI、revision/hash、物理文件、精确 bar timestamp 和完整周来源上下文生成有界清单。逐项区分“存在但非正”“文件/分区损坏”“真实缺失”，不混为一种异常。
- 用同一个 RQData `futures.get_exchange_daily` 来源、七字段 OHLC/volume/turnover/OI、严格日期身份核验。请求范围可去重但不能合并到未经批准的额外时间；当前证据不能决定请求数。专项下载独立申请当前精确单次意图，不做 Canonical 写入。
- 分类为来源非正且一致、来源合法而本地冲突、来源缺失、来源未知/请求失败。缺上下文则仍为证据不足；不得把抽样点结论外推全部历史。
- 仅来源合法且能证明原生 hard validation 可通过者，形成单独修复 plan，经独立 Review 与精确正式写入意图再处理；不能静默塞入普通队列。来源一致非正保留 fail-closed，不改零为正、不插值、不丢 bar、不缩窗口冒充就绪。

## 完成定义与交接

工程完成：新入口/观察接缝、回归测试、自审及独立 Review 通过，允许普通 develop 集成。数据完成：每个已批准成功单元具备真实读回/replan；异常完成也可为有证据的 SOURCE_EXCEPTION 或 DATA_INSUFFICIENT，不要求伪造“60/60 全绿”。

缺少真实执行意图时，继续完成全部独立、安全的工程、当前队列与 RS 本地核验，并明确 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；不能据此宣称补数已完成。生产数据不提供自动破坏性回滚；通过既有 Catalog/文件证据对账提出精确恢复方案，另取意图。

交付只有一个事实进度表：完成/待执行普通单元、EC 状态、新 RS 分类、来源请求已知/unknown、正式写入与 MDS 结果、代码/Review/develop Gate。保留旧 evidence，不新建冗余治理体系。第 4 项页面与完整矩阵仍交回 owner 单独安排。

## 设计审查

2026-09-14 独立 reviewer 核对最新 develop 与原生接口后，结论为 REVIEW_COMPLETE，0 P1 / 0 P2，允许继续实现并委派单个 Sol high 任务。实施 Review 仍需检查观察接缝默认零行为变化、不复制响应规范化、不建立第二行情入口。此结论不代表新代码、数据补数或外部 Gate 已完成。
