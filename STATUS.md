# 当前状态

文档核对：2026-09-12。正式代码基线 `v1.10.6@a8e67790dcd33db95f65c442c415378782927618`；
本轮 develop 候选代码截至 `83de0c403`，其中生产修复固定于 `bf48284cf`。本文件只保留当前版本、已证明事实、
尚缺证据、已接受的阶段规划、本轮冻结范围与唯一下一步。操作过程、逐次授权和旧候选矩阵从 Git history、tag、PR
与原 evidence 追溯；历史授权不授权重跑。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见
`DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

工作 2 已于 2026-09-11 完成：只读 closeout 返回 `ready` 后，owner 批准的单次 apply 将 2026-09-09 旧运行记为 `interrupted`，独立读回通过。当时部署预检受当天 60 品种 Session 缺失阻塞；该收尾未补行情、未切换 Runtime。本次新读回见下节。
工作 3 已于 2026-09-11 完成源码、测试、合同和独立 Review，并随 v1.10.6 发布；尚未取得新版本 Runtime 与自然盘后证据，后续仍归工作 5。

## 2026-09-12 D/E/F 与候选收口

- 2026-09-11 的第二次旧盘后运行已按 owner 精确意图行政收尾：schema v5、`current_run=null`、
  `last_run=interrupted`，terminal SHA-256 为
  `98c09006fee9624b0cef0f50e01c11b4d59e5ac8e6bdb57e76e7ba47e6566d08`。旧 writer 的 installed plist
  保留且绑定 `v1.10.5@cdd72d750`，label 明确 absent；API/Web/Live/Alert 四服务继续运行旧版。该处置避免旧
  writer 再覆盖 v5，但不等于发布或 Runtime promotion。
- 停止状态后的公共维护、兼容恢复与 promotion authority 已收敛。`bf48284cf` 删除 installer 中漂移的
  shell launchd classifier，所有安装前像、cleanup 与恢复状态均由 Python authority 给出 bounded
  `loaded/absent`；只有 exit 113 与 exact requested label/user（含现场 `Bad request.` 前缀）可判 absent，其他
  结果 fail-closed。独立复审已确认生产修复与七服务 allowlist 正确；其指出的测试桩重复解析已在
  `83de0c403` 改为预设 bounded state，exact 候选仍待最终复审。
- E 的真实 metadata source capture 固定 snapshot
  `8586532f98bceb2c525ffafeb9dedf4b0286bb13d4d58cd83414e88bc36a0e65`，64 次应用层调用取得 Calendar 20、
  Session 450、主力源行 120。provider-free plan
  `52fead349311021e27338e59de3c4c9062189b811a23efa30f2a76bb9e1f7fcf` 只新增 operational P60 的
  2026-09-14 Session 225 行；owner 批准的一次 apply 已完成，Calendar/rank1/Canonical/provider 写入均为 0。
  独立读回确认 2026-09-11 与 2026-09-14 均为 60 品种/225 Session，apply 后重规划为全 equal no-op。
- E 后重新生成的 F daily plan
  `3e56bbe9ee2adb705904e524a7dee5ce307b424b3b50172b0e949f98ebdad1e1` 固定 960 个执行目标：840 个 P60 ×
  continuous/physical × 七周期的 9 月 9–11 日增量，以及 120 个 W1 所需 9 月 7–11 日 D1 companion。
  owner 批准的一次 apply 返回 `passed`：960 applied、0 failed、0 blocked、480 provider requests，未重试。
  正式 MDS 写后读回核对 840/840 个最终分区、487138 根 Bar 与完整 endpoint hash，0 finding；现役 API
  另读到 RB 2026-09-11 completed D1，API health 与 Web 均为 200。该结果只关闭本次受控增量，不证明全历史审计。
- 1.10.7 候选代码对上述 schema-v5 现场的只读 compatible-recovery proof 已通过，保留 interruption、P60 及
  DB/Redis/Canonical/RQData 配置身份，零 provider/数据/Runtime mutation。`recovery_ready=false` 仍正确保留
  exact published tag、immutable recovery root 与独立恢复执行意图三个 Gate；v1.10.5/v1.10.6 不列为恢复版本。
- 前端证据仍绑定 `24ab72601` 的 543 passed / 1 skipped 与 production build 通过；从该提交到
  `83de0c403` 的 Web source/config/lock diff 为空，按冻结计划复用。当前隔离 worktree 的顶层依赖链接缺失所致
  的复跑失败仅是环境证据，不改写上述通过结果，也不把它计作产品失败。
- 当前为 `CODE_COMPLETE / TEST_COMPLETE / DATA_RECOVERY_COMPLETE / FINAL_REVIEW_PENDING`。尚未执行 v1.10.7 的 main merge、
  annotated tag、GitHub Release、immutable Runtime/recovery root 或五服务切换；这些仍按发布与 Runtime 两个
  独立 Gate 处理。自然 Live Bar、自然盘后及后续交易日增量也仍待新版本 Runtime 验收。

## 9 月 11 日新中断与 1.10.7 候选准备

- 20:56 停止后的最初读回确认旧版盘后进程退出、维护锁释放，当时状态仍保留 `current_run`；后续 D 的
  精确 apply 与读回已按上节完成。此次与已完成的 9 月 9 日旧运行收尾分开。
- 当时 Calendar 五交易所 9 月 11–14 日均在、9 月 14 日 Session 全部缺失、两日 Live snapshot 缺失，
  且 60 品种行情截至 9 月 8 日/周线 9 月 4 日。E/F 已关闭 Session 与行情增量缺口；snapshot 不被伪造，
  promotion 仍须使用当前现场重新运行正式 predicate。
- 隔离旧/新完整维护链确认旧版盘后全历史同步会删除下一交易日 Session。已发布 daily 改造避开该路径；
  full/refresh 仍存在同类缺陷，本轮 `97ef59b97` 将历史替换限制到截止日并拒绝含糊模板。
  Session 回归 465 passed；独立 Review 240 passed、事务回滚/其他品种保留复核通过，无 P0–P3。
- owner 已批准同日缺 snapshot 收尾方案，正式语义见[数据合同](docs/DATA_CENTER.md)，审批笔记从
  `262670773` 的 Git history 追溯，不作为 active 设计源。
  新 schema v5 只记录行政中断及 `not_verified_missing`，完整物理审计、双锁、身份/CAS 与 promotion
  保持原约束。独立 Review 发现的第二次 snapshot 读取竞争已修正，复审 183 passed、无 P0–P3；
  相关后端 323 passed / 12 skipped，真实隔离 PostgreSQL 3 passed，Web 10 passed/build、Mypy/Ruff 通过。
- 收尾提交 `262670773` 回归：完整后端 3353 passed / 16 skipped / 31 deselected，唯一两项失败为沙箱禁止绑定
  loopback 的真实 socket 测试；相同代码在隔离本机 HTTP 环境重跑 2 passed。工程 84 passed；Web
  全量 543 passed / 1 skipped、build 通过；Mypy 154 文件、Ruff、OpenSpec 9、secret scan 0 findings、
  offline lock check 与 diff check 通过。未将 fixture 或工程结果计作现场业务验收。
- 固定 `262670773` 的新现场只读 closeout 已执行并 blocked：首个 `A2305/1m/2022-05` 分区所需
  9 个交易日 Calendar 均在，但 Session 全缺，正式 reader 返回 `SESSION_BOUNDARY_INVALID`。
  零 provider/数据/状态写入，原状态 SHA 未变；未取得 ready。原始文件解码不等于边界验收通过。
- 后续只读 Catalog 盘点：2023 年前共有 a/au 两品种、9 合约、200 分区；现有 Session 均为本次
  18:09 创建，起点在 2023 年或以后。仅修复替换上界仍不够；追加的双边界修复已完成，先证明完整
  来源窗口再替换，保留窗口前 warm-up 与窗口后 Session。独立 Review 262 passed、无 P0–P3；
  真实 adapter/SQLite 回归先 RED 后 GREEN，相关维护链 579 passed。
- 双边界最终完整后端回归 3377 passed / 16 skipped / 31 deselected（含真实隔离 socket），Mypy
  154 文件、Ruff、OpenSpec 9、secret scan 0 findings 与 diff check 通过。此结果不恢复生产缺失事实。
- 提交后的跟踪态检查另发现 `262670773` 跟踪了仓库禁止保留的实现笔记；之前的工程 84 passed
  发生在该文件暂存前，不能覆盖此问题。已移除 active 笔记并保留 Git history、改链正式合同，
  repository-hygiene/canonical-consistency 复验 22 passed，未修改或放宽测试。
- 既有 metadata-repair 计划限定 a 155 日、au 196 日，Calendar 缺口为 0。owner 批准的一次
  351 请求已完成，取得 1396 行 Session（a 617、au 779），snapshot `d571d874…4306d`，无 blocker。
  源快照独立审查与真实只读 recheck 通过。随后 owner 批准的单次生产 apply 于 22:06 完成：
  新增 1396 行 Session，Calendar 0 行、provider 请求 0；使用冻结代码 `262670773`、计划
  `ff24fc9a…49978` 与上述 snapshot。22:07 独立读回逐行一致，351 个目标缺失日期归零，
  固定 200 个分区经正式 reader 读取 451900 根 Bar 全部通过；状态 SHA `37d7dbd0…c1c2` 不变。
  本地执行证据独立 Review 通过，仅关闭 a/au 的这批历史 Session 缺口，未补任何 OHLCV。
- 22:11 使用现役 Runtime 的认证连接重新读回：五交易所 Calendar 9 月 11–14 日完整；
  9 月 11 日 Session 仍为 60 品种/225 行，9 月 14 日仍为 60/60 缺失，phase 全部 UNKNOWN；
  11 日及 14 日 Live snapshot 均明确 missing。早一次普通连接诊断的 unavailable 不作为缺失证据。
  修复后的正式全量只读 closeout 于 23:23 返回 `ready`：45362 个 Catalog 已提交分区全部经正式
  reader 读取；60 品种覆盖审计仅发现 840 项 `EXPECTED_PARTITION_MISSING`，均通过合法子集检查。
  原日 snapshot 两次读取均为 `not_verified_missing`，`reconciliation_verified=false`；最终身份检查
  通过，状态 SHA 未变、状态写入为 false。此 ready 只允许提出行政中断收尾，不代表行情完整或 passed。
  23:24 独立读回 advisory lock 为 0，current_run 仍在；14 日 Session 仍缺失，两日 snapshot 仍 missing，
  phase 仍 UNKNOWN60。正式只读 promotion preflight 仍 blocked / `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。
- 同一现役绑定的原 daily dry-run 固定为 60 品种、960 个窗口；E 后重新规划得到相同 core window，并用
  完整 expected/missing endpoint hash 形成上节 F plan。该计划已按一次精确意图完成并通过 MDS 读回；
  周线 companion 仍是 9 月 7–11 日整周刷新，不能把其中已存在的 9 月 7–8 日称为缺失。
- 切换时机隔离验证：周六 06:00（含）至 18:00（不含），若所有品种均处于非交易 Calendar 的
  `CLOSED / trading_day=None / current_session=None`，且盘后状态有效、没有 current_run，可走
  `non_trading_interval`，不要求缺失的未来 Session/snapshot；18:00 起缺 Session 又会 UNKNOWN。
  SQLite/内存边界复核及既有 71 项测试通过。这不是 9 月 12 日现场 passed；届时必须正式只读 preflight。
- 版本身份为 1.10.7，收敛 daily/生命周期、Session 保留、收尾、单 worker、周检状态和停止状态恢复补丁。
  相对 v1.10.6 还包含既有 `c073e255` 研究输出，未删改或据此缩称为纯代码补丁；最终候选在本状态更新后冻结。
- `EXTERNAL_GATE_PENDING`：D/E/F 已关闭；尚缺 exact `83de0c403` 候选独立 Review、v1.10.7 发布、compatible immutable
  recovery root、Runtime 切换及新版本自然验收。旧 writer 已明确停止且不会参加下一次 18:05 调度；未自动
  发布、安装 weekly audit、切换服务或发送通知。

## 单 API worker 补丁候选（面向 v1.10.7，未发布）

- 修复代码 `044972b82201afe6dc9ee5a532040d748b862bac`：正式 API launcher 显式固定一个 worker，
  保留进程内快照、token 逐事实校验、重型门禁、取消与去重。它修复部署契约，不重开已发布的前端旧响应修复。
- `CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE`：Newow 1326 passed / 1 skipped，新增真实 socket
  2 passed；工程 84 passed；Web 定向 unit 117 passed、浏览器 fixture 51 passed；OpenSpec 9、Ruff、
  secret scan 0 findings、diff check 与 launchd render-only 通过，独立 Review 无 P0–P3。
- 黄金趋势 1d、截点 `2026-09-08T07:00:00.000001Z` 的五组新进程真实只读 HTTP 链路通过；四连接交错、
  主图/参考分页、副图和重启旧 token 拒绝保持正确。重型运行重叠采样：health 2078 次，p95 12.9 ms、
  最大 165.2 ms；普通行情 722 次，p95 91.4 ms、最大 328.7 ms；全部采样无错误或超时。
- 精确候选真实浏览器无业务拦截，参考记录 50→70、统计摘要不变、精确信号定位及当前窗口照妖镜绘制通过。
  旧历史视窗未读取的副图范围不据此宣称完整。未清 OS/磁盘缓存，初期采样有并行 fixture 测试 CPU 活动；
  不外推全品种、吞吐上限或双 worker 性能对比。证据与冻结脚本见
  [单 worker 验收记录](outputs/newow-single-worker-20260911/acceptance.json)。
- `EXTERNAL_GATE_PENDING`：尚未发布新补丁或切换 Runtime；现役状态与 v1.10.6 release 事实保持下文所述。
  下一步是冻结新补丁 release candidate 并单独取得发布意图，之后另行处理 Runtime promotion 与现场进程/请求验收。

## 周检状态归属补丁（未发布、未启用）

- 修复代码 `838a7e649`：同一状态路径先取得专属写入锁，再写 running、获取维护锁和执行只读审计；
  竞争者只返回 `skipped_busy`，不覆盖持有者状态。独占新尝试的维护锁 busy/异常仍写入本次 skipped_busy/failed，
  不沿用旧成功。锁覆盖终态发布和维护 lease 释放，进程中断保留未完成状态。
- `CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE`：周检定向 43 passed（含独立复跑）；相关回归 368 passed，
  首次唯一失败是隔离 worktree 缺前端依赖，复用已有依赖后该项重跑 1 passed；隔离 PostgreSQL 2 passed。
  Ruff、Mypy、OpenSpec 9 项、引用检查、secret scan 0 findings、diff check 通过；独立 Review 无 P0–P3。
- `EXTERNAL_GATE_PENDING`：补丁尚未发布或进入 Runtime；周检安装和新版本自然运行验收仍为独立 Gate。
  weekly audit 保持可选，不是 operational health 的 required service；未运行本身不要求停止 API/Live 等服务。

## v1.10.6 Release（Runtime 未切换）

- 独立候选 `2cb4538da362d4833262d303c4bf02f041575e76` 由 PR #362 合入 main；merge commit
  `a8e67790dcd33db95f65c442c415378782927618` 与候选 tree
  `4d51ac0d81e4d0c9e306df5e103f5ba0ef74e37e` 完全一致。annotated tag object 为
  `1c4fe01b2e4717e46b88a2db879620610100a534`，peeled commit 为同一 main commit。
- GitHub Release `v1.10.6` 于 `2026-09-11T07:23:52Z` 发布，non-draft、non-prerelease；API、Web、
  Python package、lock 与 health identity 均为 `1.10.6`。
- owner 已接受相对 `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09` 的全部 develop diff。
  冻结前统计为 187 个文件、1,015,631 行新增、1,798 行删除；包含盘后收尾与生命周期修复、每日增量与
  weekly-audit、Canonical 边界校验、Newow 请求失效与显示回归、黄金及其余品种的仓库内 evidence，
  不是仅盘后代码的最小补丁。
- 候选新跑验证：版本一致性 23 passed；完整 backend 3259 passed / 16 skipped / 31 deselected；
  工程 81 passed；Web 541 passed / 1 skipped，build 通过；标准浏览器 154 passed / 3 个 candidate-preview
  跳过，candidate-preview 独立 3 passed；隔离 PostgreSQL 3 passed；Mypy 154 个源码文件、Ruff、9 项
  OpenSpec strict、secret scan（0 findings）、lock check、diff check 与 launchd render-only 通过。独立
  Review 的发布状态一致性发现已在候选内修正，最终 Spec/Standards 复核无 P0–P3。
- Runtime promotion、weekly-audit 安装及新版本自然盘后验收是独立 Gate；发布时的 2026-09-11 Session 与 Live
  snapshot 缺失阻塞 promotion，不因发布自动修复；此后现场变化见本轮新读回。现役 v1.10.5 API/Web health 为 200，
  Runtime health 为 failed，当前有界 readback 未确认该失败的单一原因；weekly audit 独立显示 `not_run`，
  且不是 required service。这些都不是 v1.10.6 Runtime evidence。

## 当前阶段

| 项目 | 阶段 | 说明 |
|---|---|---|
| 正式 Release | `RELEASED` | `v1.10.6@a8e67790d`，PR #362 合入 main，annotated tag 与 GitHub Release 已读回 |
| 现役 Runtime | 未切换，未声明 `RUNTIME_READY` | API/Web/Live/Alert 四服务仍运行 v1.10.5；旧 after-market plist 保留但 label absent；新版本 promotion 与自然验收未完成 |
| 中断盘后收尾 | 9 月 9 日与 9 月 11 日均 `COMPLETED` | 两次运行分别按独立意图收尾并读回；9 月 11 日为 schema-v5 terminal，旧 writer 已停止 |
| 盘后生命周期修复 | `COMPLETED / RELEASED` | `8f2b051fd` 随 v1.10.6 发布；Runtime 与自然盘后 Gate 尚未完成 |
| 牛哇加载一致性 | `COMPLETED / RELEASED` | `fef307732` 随 v1.10.6 发布；相关 unit、九组合及完整浏览器矩阵重验通过 |
| 本轮稳定版 | v1.10.7 `RELEASE_CANDIDATE_PREP` | D/E/F 与候选代码已收口；最终验证/Review、发布、compatible root、Runtime promotion 和自然业务验收仍分开 |
| 其他品种历史 | 元数据已完成；物理历史未盘点 | 不阻塞盘后稳定版，除非发现共享完整性问题 |
| 牛哇新版综合解释 | `RESEARCH_EVIDENCE_COMPLETE` / `IMPLEMENTATION_PENDING` | 规则差异已确认，未批准新合同 |
| 后续交付路线 | 规划已接受，未据此关闭任何 Gate | 先盘后稳定，再牛哇日周六组合；随后 Web 体验与 60m 数据准备并行，最后独立开放 60m |

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
| 第一阶段：盘后稳定版 | 对应工作 3、5；工作 4 按已接受范围参与 | v1.10.6 工程验收与独立发布已完成；promotion、weekly-audit 安装及新版本自然运行仍为独立 Gate | 不追加牛哇日周开放、新版评分或 60m 大规模补数 |
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

## 架构审查三项修复（随 v1.10.6 发布）

`codex/architecture-fixes` 已完成三项批准的 OpenSpec 实现：同族同月 1m 发布先于派生、Newow 冲突撤销旧请求写入资格、Canonical 分区批量边界校验。三项独立 Review 和整分支 Spec/Standards Review 均通过；只涉及源码、测试及规范；已于 2026-09-11 fast-forward 集成 develop，源码提交 `17718f126`，并随 v1.10.6 发布。Runtime 尚未切换。

- 最终源码验证：后端 3248 passed / 16 skipped / 31 deselected；Web unit 541 passed / 1 skipped；build、Ruff、OpenSpec 与 secret scan 通过。
- 浏览器基线已由 `20dcc4f29` 修复并集成 develop：解释夹具按既有合同使用 trend 上下文，外层仍保留所选策略；九组合夹具通过正式解析器。原 Newow product 两项失败已关闭，完整 product 38 passed；扩展详情/图表共 66 passed，candidate-preview 另 3 passed。只同步六张已独立视觉复核的过期截图（日周完整日期、既有刷新按钮、自然换行），保留 500 像素阈值及既有弹窗截图；未改正式产品源码或公式。
- 根据 owner 本轮“先关闭两个未改文件中的 Mypy 基线错误，然后集成”的要求，已补齐 `domain.py` 的有限 Decimal 指数类型收窄及 `bounded_metadata.py` 的可空生命周期日期检查；全量 Mypy 154 个源码文件通过。新增 12 项行为保持回归，修复前后定向均为 147 passed；未增加类型忽略或改变行情口径。
- 批量校验的隔离真实 store 测试中，1/5/60 根 × 1/3 个交易日的 publish/readback SELECT 分别固定为 continuous 5/5、contract 6/6。这不是生产墙钟性能验收，也未修复任何既有生产分区。

三项架构修复和 Mypy 补修为 `CODE_COMPLETE / REVIEW_COMPLETE`；完整后端回归通过，补修独立 Spec/Standards Review 无 P0–P3 发现，额外 8024 组新旧 Decimal 差分一致。集成后的全量 Mypy 再验通过，包含原有未提交 closeout 修改的定向回归 226 passed。按 owner 明确要求关闭 Mypy 后集成 develop，已执行。浏览器补修的独立 Spec/Standards Review 均无 P0–P3 发现，Newow fixture 浏览器 Gate 已关闭；这不代表生产历史、原站 parity 或 Runtime 验收。原 develop 两处 closeout heartbeat 修改在架构集成时保留，随后已独立验证、Review 并提交为 `baef0d92b`，详见下节。上述范围已随 v1.10.6 发布；不新增真实数据、通知或 Runtime 授权。

## 工作 2 中断盘后安全收尾（2026-09-11）

状态为 `COMPLETED / RELEASED`。`baef0d92b` 已随 v1.10.6 发布：closeout 从生产者实际写入的 `alert:heartbeat` 读取 Alert 身份；测试只响应该精确键，保持缺失/过期/身份或恢复开关不符即拒绝。RED 验证旧键失败；直接相关五文件回归 236 passed，全量 Mypy 154 个源码文件通过，Ruff、18 项工程检查、9 项 OpenSpec strict 和 secret scan（0 findings）通过；独立 Review 无 P0–P3 发现。Runtime 尚未切换。

owner 授权停止仅属于本任务的慢速只读诊断 PID 22129，并进行一次新的只读排查。旧诊断在 50 分 16 秒时被 SIGTERM，exit 143，没有 closeout 结论。排查确认本任务的全局追踪造成额外开销：隔离真实 reader 的 1000 行分区基准中约 7.54 倍；该比例不能推算生产耗时或作为唯一原因。新诊断移除全局追踪，仅观察原函数进度，独立 Review 确认不改变检查、返回值或异常传播。

新一轮基于 `baef0d92b`，只读约 69 分 44 秒返回 `status=ready`、`readonly=true`、`status_written=false`、`provider_requests=0`、`data_writes=0`。精确目标：

- Runtime root：`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1`；commit：`cdd72d7501227d8e7f905ea0b8a54c038b521a09`。
- 状态文件：该根下 `.run/after-market-status.json`；前后 SHA-256 均为 `08d63356c9978423431fe7db2a926d655a159ffb5c8f64b1237c2c7f5c79ee57`；schema v2，原 `current_run.started_at=2026-09-09T18:05:06.737372+08:00`。
- operational 60 品种的 45,362 个 Catalog 已提交指针全部通过严格物理读取；中断日 audit 返回 720 项 `EXPECTED_PARTITION_MISSING`，随后全部通过允许缺口/有效子集检查，`pending_findings=720`。audit 自身为 failed，closeout 则按合同 ready；不证明全历史完整，也不证明这些缺口由旧中断造成。
- 2026-09-09 原 Live snapshot 与 60 品种 rank1 匹配；来源时间、配置/启动身份、锁及结束前身份/状态字节复核通过。旧 9 月 8 日自然成功证据没有晋升为新成功。

11:22–11:23 的现役及 develop 只读部署 preflight 均返回 blocked / `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。使用相同 Runtime 绑定依赖的只读诊断确认：五交易所当天 Calendar 存在，附近 Calendar 完整性检查未失败；60/60 品种解析 2026-09-11 Session 均报 `TRADING_SESSION_MISSING`，故 phase=UNKNOWN；当天 Live snapshot 不存在，旧状态分类当时仍为 running。这里只确认当前有效 Session 缺失，不推断何时或为何缺失；既有截至旧目标日的元数据恢复不因此改写为失败。

owner 随后批准一次精确 apply；命令在同一锁窗口重验全部条件后返回 `status=closed_interrupted`、`status_written=true`、`pending_findings=720`、`provider_requests=0`、`data_writes=0`。独立读回确认状态文件仍为 0600 普通文件，新 SHA-256 为 `ee5ccb1f377d4b7ac0812cd09779f00e65295387a07dabd9466872da83ae8a4b`：schema v4、`current_run=null`、2026-09-09 `last_run.status=interrupted`、attempts=null、`AFTER_MARKET_INTERRUPTED`，最后成功日保留 2026-09-08。develop reader 可正确读取该状态；现役 v1.10.5 与 develop 的收尾后只读 preflight 仍均为 blocked / `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`，60 品种、零当天 snapshot。旧事故已完成有证据的归类；Session / Live Gate 独立保留，未执行 installer、promotion、通知或任何数据修复。

## Release、Runtime 与 Scope

| 项目 | 最近已记录事实 |
|---|---|
| 正式 Release | `v1.10.6@a8e67790dcd33db95f65c442c415378782927618`；PR #362 于 `2026-09-11T07:22:25Z` 合入 main；tree `4d51ac0d81e4d0c9e306df5e103f5ba0ef74e37e`；annotated tag object `1c4fe01b2e4717e46b88a2db879620610100a534`。GitHub Release 于 `07:23:52Z` 发布，non-draft、non-prerelease。API/Web/Python/lock 为 1.10.6。 |
| 发布验收 | 已审候选 `2cb4538da362d4833262d303c4bf02f041575e76` 与发布 tree 一致。候选包含 owner 已接受的全部 develop diff；完整工程、Web、浏览器、隔离 PostgreSQL、静态检查和双路 Review 通过。 |
| Runtime | 2026-09-11 closeout 前后身份复核通过：五服务均为 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1` / `cdd72d7501227d8e7f905ea0b8a54c038b521a09`；API/Web/Live/Alert running，after-market loaded 且 idle（runs=0），18:05 调度保留。本轮未 load、restart 或切换。现役根干净 detached annotated `v1.10.5`；现版本自然盘后验收仍待完成。 |
| Runtime 工作树 | 现役根为 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1`；原 v1.10.4 根仍保留。旧根无五项 launchd 引用，未清理。生产已产生 hash URI，不得把只支持固定 URI 的 v1.10.4 当作通用回退。 |
| 最近 health | `2026-09-11` 发布前只读检查：现役 v1.10.5 API/Web 为 200，Runtime health failed；当前有界输出未确认单一失败原因。weekly audit 独立为 `not_run` 且不是 required service。该结果不属于 v1.10.6 Runtime。 |
| Database | 最近生产 readback 为 Alembic `20260903_0045`。 |
| Market Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 审计：HTDY 仅 `jm × 5m/15m`；苏冰 60 品种 × 15m；两 Rule enabled。HTDY“焦煤 15m/5m，其余 59 品种 60m”共 61 对仍是未应用目标。 |
| 最近自然 After-market | v1.10.3 于 2026-09-08 自然运行，18:05:05 开始、19:05:52 完成，passed、attempts=1、60 品种。该状态字节随后带入 v1.10.4/v1.10.5，hash `cece65929ba734c37cf91ee47af1b0d23b5dc3dd413c9d703888f669428347d5`。它不是 v1.10.5 或 v1.10.6 自然盘后证据。 |

## 已证明事实（不得重新打开，也不得扩大解释）

1. **苏冰本次自然推送已闭环**，归属 exact `v1.10.5@cdd72d750`。补齐 AO2701/OI2701 后，2026-09-09 自然生成 Event #143–#146；#146 PT2610 14:00 买入与 `last_provider_accepted_at` 匹配，owner 确认该条微信收件。该确认不声明另外三条或 Topic 其他成员送达，也不替代现版本自然盘后验收。旧 `last_failure_at=2026-09-09T03:30:05.449850Z` 保留，不得手工清除来制造通过。更早的 v1.9.15 G11/G12 闭环见 Issue #307，只归属当时版本。
2. **黄金牛哇固定历史截点本地预览已完成**。截点 `2026-09-08T07:00:00.000001Z`，候选 `e79e82f42`；九组合主图/副图/解释/参考统计/历史定位在 API8010/Web5174 真实浏览器通过。周线默认本周未完成保留；震荡周线 AU2610 比较器明确不足 20 根。这不是当前时点或全品种生产验收。目标/吸筹 previous-close、原页面时序、期货 owner/segment 仍为 `EVIDENCE_REQUIRED`。
3. **Calendar/Session 元数据恢复已完成**：黄金五合约夜盘/Session 缺口关闭；其余 59 品种在 `a53389cc5` 后 Calendar/Session 剩余唯一缺口为 0。这不证明分钟历史或九组合页面已恢复。
4. **中断盘后收尾入口在 develop 已是代码完成**。来源时间模型 `4cd08ff19` 已合入 `develop@00c7fec60`；其后又合入 launchd 环境解析、inert 配置剔除与依赖来源保护。`data close-interrupted-after-market` 默认只读；`--apply` 只可将旧运行记为 `interrupted`，不能记成功、补行情或放宽 promotion。合同见 `docs/DATA_CENTER.md` 与 `openspec/specs/historical-data-maintenance/spec.md`。
5. **统一详情页、Canonical P1、captured 身份解析已随 v1.10.5 发布；后续架构与显示修复已随 v1.10.6 发布**。详情页 owner 视觉接受只证明对应版本范围；fixture 不证明生产数据。Canonical 后续每批写入仍须独立单次意图。

## 尚缺证据

| 缺口 | 类型 | 当前证据边界 |
|---|---|---|
| 收尾后部署预检 | 现场验收 | apply 与状态读回已完成；现役与 develop 只读 preflight 仍均 blocked / `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。当前 60 品种 Session 缺失导致 UNKNOWN，当天 snapshot 缺失；这是独立 Runtime Gate，未跑 installer 或 promotion。 |
| v1.10.6 自然盘后 | 现场验收 | 已发布但尚未切换 Runtime；后续验证自然盘后、后续增量和 weekly-audit，不得用 v1.10.3 成功记录或旧状态字节代替。 |
| 其他品种物理历史与页面可用性 | 数据缺口 | 元数据不得再列为待修。须按品种/周期/面板区分元数据缺失、物理历史缺失、质量异常、正常样本不足和原站证据不足。 |
| 牛哇新版综合解释 | 新版需求 | 同输入已确认新版五项/`R0–R4`/`MM1–MM4`/计龄与当前 v3.2.59 四项/13 格合同 3/3 不一致；总分含未展示 `certExtra`。详见 [当前复核](docs/research/newow-current-review.md) N09。震荡 60 分钟图表差异为 `KNOWN_DIFFERENCE_ACCEPTED`。 |

## 本轮稳定版边界（冻结）

近期里程碑是：交付一个盘后结果可信、失败可诊断、部署可验收的稳定版本。工作 1–5 服务该里程碑；工作 6、7 不是同一任务，不要求完成后才能发布。

**分层 Gate**

- 候选与发布 Gate：v1.10.6 已完成工作 3 故障回归、相对 `v1.10.5` 的真实 diff 冻结、必要检查、独立 Review 及 main/tag/GitHub Release；该 Gate 已关闭。
- Runtime promotion Gate：工作 2 已完成旧中断运行归类；当时有效的部署预检条件仍须全部满足。Session/Live 快照缺失即使原因已知仍阻塞切换；promotion 与 release 分别批准。
- 稳定版运行验收 Gate：发布并切换后，取得新版本自然盘后、后续增量和周检执行证据。此 Gate 未完成时保留待验收，不声明 `RUNTIME_READY`，也不倒置为发布前真实运行要求。

**本轮不阻塞（已披露限制）**

- 牛哇新版评分、`certExtra`、收益曲线、盘中确认时钟、Newow 真实推送。
- 其他品种全部历史补齐、真实全品种九组合矩阵。
- 已接受的原站差异，包括震荡 60 分钟同根重建。
- 正常空仓、未完成周线、样本不足；不得改成“有结果”。
- HTDY 61 对 Scope 未应用；BU/BZ D1/W1 异常。
- 原件缺口继续 `EVIDENCE_REQUIRED`：诊断 token、六组合评分/排序、AI 逐字 copy、目标/吸筹权威昨收与期货 owner parity、比较器 browser-final/tie golden。
- 旧苏冰 failure 时间戳、Topic 其他成员送达人数。

`develop` 相对 `v1.10.5` 的中断收尾、来源时间、closeout 配置、日常增量/weekly-audit、牛哇显示与黄金/59 品种数据记录等已作为完整范围随 v1.10.6 发布。发布候选只接纳阻断该次交付的问题，未追加日周开放、新评分或 60m 补数。具体执行规则见 `docs/DEVELOPMENT.md`。

## 待办分类

上轮四项代码问题已按精确基线逐项复核；已修复项关闭并随 v1.10.6 发布，仍缺的现场证据继续独立保留，不追溯认定为 v1.10.5 事故的唯一根因。GitHub 当前无开放 Issue；不新建平行台账，统一挂到下表已有记录。

### 现场验收

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 旧盘后中断收尾 | `docs/DATA_CENTER.md` 收尾合同；OpenSpec `historical-data-maintenance` | 已完成：单次 apply 写入 interrupted，独立读回通过；不重跑 |
| v1.10.6 自然盘后 | 本文件 Runtime 表；不得使用 `cece65929…` 旧成功字节 | Runtime promotion 后等待自然运行并独立读回 |
| 收尾后部署预检 | `deploy/README.md`；2026-09-11 收尾后 preflight 仍为 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` | 当天 Session / Live snapshot 问题独立保留，不借收尾补数或切换 |

### 代码缺陷

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 交易日 / 非交易日 / 日历未知 | `8f2b051fd`；`coverage_source.py` / `after_market.py` | 已关闭：当天精确权威 Calendar 缺失或跨交易所分歧均失败关闭，不再回退昨天后误报 `NON_TRADING_DAY` |
| 异常退出状态转换 | `8f2b051fd`；`after_market.py` | 已关闭：Calendar 普通异常写终态失败；部分提交和 commit unknown 不假成功；进程级中断保留 unfinished `current_run` |
| 副作用报告 | `8f2b051fd`；`runtime_entry.py` / `guiyi_cli/main.py` | 已关闭：after-market 未处理异常固定 `readonly=false`；weekly-audit 保持只读，错误载荷继续脱敏 |
| 牛哇旧请求回写与分页定位 | `fef307732`、`20dcc4f29`、`972162b80`；对应 OpenSpec、组合式函数、unit 与浏览器回归 | 已关闭：共享快照冲突会撤销旧请求写入资格；分页、定位、九组合与完整浏览器矩阵在 v1.10.6 候选重验通过 |

### 数据缺口

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 59 品种元数据 | develop `e27ede9bd` / `a53389cc5` | 已完成，不再重开 |
| 黄金日周分钟与本地九组合 | 本文件已证明事实 2；Git history 保留逐批 hash | 已完成本地预览；不把截点证据改写为当前生产矩阵 |
| 其他品种物理历史 | 现有 bounded readiness / MDS 读回入口 | 稳定版之后先恢复日周六组合所需历史与预热；60m 留后续支线，按共享物理合约去重分批，先定范围再申请写入 |

### 新版需求

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 牛哇新版综合解释 | [当前复核](docs/research/newow-current-review.md) N09；稳定合同仍见 `PROJECT_SOURCE.md` 与 OpenSpec `newow-product-reference-trading` | 先批准来源版本、计龄、五项、总分与 `certExtra` 显示或禁用；新版本身份，不改主动作/参考交易/通知 |
| 收益曲线、嵌套路径、盘中确认、Newow 推送 | 同上 N03/N10/N11/N12，标为 P2 | 本轮不扩展 |

## 七项工作对应

| 编号 | 工作 | 类型 | 目标 | 范围 | 前置 | 验收 | 阻塞对象 | 下一步 |
|---|---|---|---|---|---|---|---|---|
| 1 | 状态和范围收敛 | 文档 | 能直接看出现在做哪一项、还差什么 | 只改当前状态表述与任务对应；不改公式、产品边界、业务代码 | 无 | 打开本文件即可区分已完成/待验证/待修复/新需求 | 已完成 | 无需重开 |
| 2 | 当前中断盘后安全收尾 | 现场验收 | 旧运行有证据归类；部署是否仍阻塞可说明 | 只读核验现役 Runtime、五服务、状态文件、共享锁、配置来源；条件满足后单次 apply 记 `interrupted` | 已完成 | 60 品种全部已提交指针可读；720 项有效子集缺口；原日快照匹配；单次 apply 与独立状态读回通过；部署阻塞已定位为独立 Session/Live Gate | 旧事故归类已关闭；Runtime promotion 仍受独立 Gate 阻塞 | 不重跑 closeout |
| 3 | 盘后运行生命周期与错误判断 | 代码缺陷 | 降低下次故障恢复成本 | `coverage_source`/`after_market`/`runtime_entry`；日常增量与 weekly-audit 保持独立 | 工作 2 已完成 | `8f2b051fd`；最终后端 3259 passed / 16 skipped / 31 deselected，工程 81 passed，Mypy 154 文件、Ruff、OpenSpec、secret scan 和独立 Review 通过 | 已完成并随 v1.10.6 发布；自然运行归工作 5 | 等待新 Runtime 自然验收 |
| 4 | 现有牛哇加载与显示一致性 | 代码缺陷 | 现有公式下页面可靠 | 请求取消/代次/在途快照/面板/分页；策略/周期切换、历史分页、参考定位、冲突恢复 | 已完成并纳入 v1.10.6 | `fef307732` 与对应 OpenSpec/回归关闭旧请求回写；v1.10.6 完整 Web 和浏览器矩阵通过 | 已完成并发布；生产历史仍是独立数据 Gate | 不追加三策略主动作、新版评分或参考价格口径 |
| 5 | 范围固定的稳定版本 | 发布/部署 | 结束继续加内容的循环 | 冻结候选真实 diff；相关回归、集成、Web 构建、浏览器验收、独立 Review；main/tag/release 与 Runtime promotion 分批批准；新版本自然运行验收 | 工作 2、3、4 已闭环；范围已接受全量 develop | v1.10.6 main/tag/GitHub Release 已完成；Runtime 与自然业务 Gate 待完成 | 本轮里程碑 | 先解决只读 promotion predicate，再另行批准 Runtime switch |
| 6 | 其他品种可用性与分批补数 | 数据缺口 | 先恢复日周六组合，再准备 60m | 复用 readiness；按物理合约/窗口去重；每批 MDS 读回、对应页面及维护接续 | 稳定交付恢复后；每批真实查询/写入另需单次意图 | 声明范围内日周逐项可核对；60m 数据就绪与产品开放分开验收 | 不阻塞无共享完整性问题的盘后稳定版 | 先冻结日周品种/窗口/面板和预热需求，再出可用性清单，不边跑边扩范围 |
| 7 | 牛哇新版综合解释 | 新版需求 | 把规则适配从显示修复中分开 | 新版本身份；先内核固定输入，再接口和页面 | 先批准新合同，含 `certExtra` | 同输入能解释新旧差异；分项与总分可核对；不改变主动作、参考交易或正式通知 | 独立后续候选 | Plan-only；本轮安排不构成实现或发布批准 |

工作 2 处理旧事故，工作 3 防止同类事故再变成复杂恢复；可以分别推进，但不能同时进行会互相干扰的生产操作。同时最多一个盘后主任务和一个独立前端任务。生产写入、收尾和 Runtime 切换串行。测试建设嵌入工作 3、4、5，不再单开没有终点的全面测试重构。

## 仍待人工裁决

1. **现役生产归因**：工作 3 已在隔离基线关闭可证明缺陷，但未把它们追溯宣称为 v1.10.5 现场事故的唯一根因。
证据不足的条目保持待裁决。临时 evidence 路径再次使用前须检查存在与完整性。

## 唯一下一步

本次全量只读 closeout 已 ready；下一步取得 9 月 11 日中断运行状态 apply 的单次意图，并明确旧版
9 月 12 日 18:05 调度处置。9 月 14 日 Session、Live snapshot 和 Runtime promotion 各自保留 Gate，
已通过的历史 Session 恢复不重跑。

本文件不构成元数据/行情修复、发布或 Runtime promotion 批准。
