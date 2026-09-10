# 当前状态

文档核对：2026-09-10。正式代码基线 `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09`；
develop 代码基线 `a28775b28bb8ef1d390e53aa0a93a753e50e6880`。本文件只保留当前版本、已证明事实、
尚缺证据、本轮冻结范围与唯一下一步。操作过程、逐次授权和旧候选矩阵从 Git history、tag、PR
与原 evidence 追溯；历史授权不授权重跑。稳定产品面见 `PROJECT_SOURCE.md`，长期决策见
`DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。

工作 2 已用当前 develop CLI 对现役 v1.10.5 做一次只读 closeout，未 apply、未补行情、未切换 Runtime。

## 当前阶段

| 项目 | 阶段 | 说明 |
|---|---|---|
| 正式 Release | `RELEASED` | `v1.10.5`，PR #359 合入 main |
| 现役 Runtime | 已切换，未声明 `RUNTIME_READY` | API/Web/Live/Alert 加载 v1.10.5；after-market 已安装但未加载；现版本自然盘后验收未完成 |
| 中断盘后收尾 | `CODE_COMPLETE` / `EXTERNAL_GATE_PENDING` | 2026-09-10 用 develop 代码一次只读停在身份绑定；未 apply；状态字节未变 |
| 盘后生命周期修复 | 待精确基线复现 | 不把上轮线索直接写成生产根因 |
| 牛哇加载一致性 | 待精确基线复现 | 黄金固定截点本地预览已完成，不代替当前全品种验收 |
| 本轮稳定版 | 范围已接受全量 develop，候选 commit 未冻结 | owner 已接受相对 v1.10.5 的全部 develop diff；精确冻结仍留工作 5 |
| 其他品种历史 | 元数据已完成；物理历史未盘点 | 不阻塞盘后稳定版，除非发现共享完整性问题 |
| 牛哇新版综合解释 | `RESEARCH_EVIDENCE_COMPLETE` / `IMPLEMENTATION_PENDING` | 规则差异已确认，未批准新合同 |

## Release、Runtime 与 Scope

| 项目 | 最近已记录事实 |
|---|---|
| 正式 Release | `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09`；PR #359 于 `2026-09-09T03:53:57Z` 合入 main；tree `11704da35b2eccf62bdddc330eb0e42ea5930247`；annotated tag object `71bad4102a9be883ba341c7dd27f0e98f59dab41`。GitHub Release 同日 `03:55:28Z`，non-draft、non-prerelease。API/Web/Python/lock 为 1.10.5。 |
| 发布验收 | 已审候选 `0d2273445637a6dd5cfef2a45c4f1242276952c5` 与发布 tree 一致。该候选不是“只修两合约数据”的最小补丁，还含 Canonical P1、captured Runtime 身份解析、WebSocket 资源边界、统一详情页、苏冰历史参考与 Newow 只读相关改进。 |
| Runtime | 2026-09-10 现场重绑：已加载 API/Web/Live/Alert 均为 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1` / `cdd72d7501227d8e7f905ea0b8a54c038b521a09`，state=running。`com.guiyi.quant-after-market` 已安装且 domain enabled，但 `launchctl print` 返回 113 not found，不是 idle。现役根干净 detached `v1.10.5`。2026-09-09 12:09 的五项均加载读回不能当作今晚仍成立。未使用回退。现版本自然盘后验收仍待完成。 |
| Runtime 工作树 | 现役根为 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1`；原 v1.10.4 根仍保留。旧根无五项 launchd 引用，未清理。生产已产生 hash URI，不得把只支持固定 URI 的 v1.10.4 当作通用回退。 |
| 最近 health | `2026-09-09 14:03:17 CST`：API 1.10.5、Runtime health ok/readonly，严格 captured 身份通过；60 品种 TRADING、subscribed_count=60；苏冰自然评估到 14:00。该结论保留原采集时间，不是 2026-09-10 的实时健康。 |
| Database | 最近生产 readback 为 Alembic `20260903_0045`。 |
| Market Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 审计：HTDY 仅 `jm × 5m/15m`；苏冰 60 品种 × 15m；两 Rule enabled。HTDY“焦煤 15m/5m，其余 59 品种 60m”共 61 对仍是未应用目标。 |
| 最近自然 After-market | v1.10.3 于 2026-09-08 自然运行，18:05:05 开始、19:05:52 完成，passed、attempts=1、60 品种。该状态字节随后带入 v1.10.4/v1.10.5，hash `cece65929ba734c37cf91ee47af1b0d23b5dc3dd413c9d703888f669428347d5`。它不是 v1.10.5 自然盘后证据。 |

## 已证明事实（不得重新打开，也不得扩大解释）

1. **苏冰本次自然推送已闭环**，归属 exact `v1.10.5@cdd72d750`。补齐 AO2701/OI2701 后，2026-09-09 自然生成 Event #143–#146；#146 PT2610 14:00 买入与 `last_provider_accepted_at` 匹配，owner 确认该条微信收件。该确认不声明另外三条或 Topic 其他成员送达，也不替代现版本自然盘后验收。旧 `last_failure_at=2026-09-09T03:30:05.449850Z` 保留，不得手工清除来制造通过。更早的 v1.9.15 G11/G12 闭环见 Issue #307，只归属当时版本。
2. **黄金牛哇固定历史截点本地预览已完成**。截点 `2026-09-08T07:00:00.000001Z`，候选 `e79e82f42`；九组合主图/副图/解释/参考统计/历史定位在 API8010/Web5174 真实浏览器通过。周线默认本周未完成保留；震荡周线 AU2610 比较器明确不足 20 根。这不是当前时点或全品种生产验收。目标/吸筹 previous-close、原页面时序、期货 owner/segment 仍为 `EVIDENCE_REQUIRED`。
3. **Calendar/Session 元数据恢复已完成**：黄金五合约夜盘/Session 缺口关闭；其余 59 品种在 `a53389cc5` 后 Calendar/Session 剩余唯一缺口为 0。这不证明分钟历史或九组合页面已恢复。
4. **中断盘后收尾入口在 develop 已是代码完成**。来源时间模型 `4cd08ff19` 已合入 `develop@00c7fec60`；其后又合入 launchd 环境解析、inert 配置剔除与依赖来源保护。`data close-interrupted-after-market` 默认只读；`--apply` 只可将旧运行记为 `interrupted`，不能记成功、补行情或放宽 promotion。合同见 `docs/DATA_CENTER.md` 与 `openspec/specs/historical-data-maintenance/spec.md`。
5. **统一详情页、Canonical P1、captured 身份解析已随 v1.10.5 发布或已集成 develop**。详情页 owner 视觉接受只授权 develop 集成；fixture 不证明生产数据。Canonical 后续每批写入仍须独立单次意图。

## 尚缺证据

| 缺口 | 类型 | 当前证据边界 |
|---|---|---|
| 用当前 develop 收尾代码重跑现场只读 closeout | 现场验收 | 2026-09-10 晚间一次只读：执行基线 `a28775b28`，`--runtime-root` 为已加载四服务的 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1`，commit `cdd72d7501227d8e7f905ea0b8a54c038b521a09`，状态 SHA-256 仍为 `08d63356c9978423431fe7db2a926d655a159ffb5c8f64b1237c2c7f5c79ee57`。`current_run` 仍是 `2026-09-09T18:05:06.737372+08:00` / schema v2。CLI 返回 `status=blocked`、`error_code=AFTER_MARKET_CLOSEOUT_BINDING_UNAVAILABLE`、`status_written=false`、`data_writes=0`、`provider_requests=0`。公开错误码无 `last_stage`；现场已见 after-market 未加载，身份合同要求其 loaded 且 idle。数据一致性与 `source_age` 未形成本次证据。更早一次只读停在 `source_age` 的记录早于来源时间代码修复，不能当作本次失败原因。未 apply。 |
| 收尾后部署预检 | 现场验收 | 未写入 interrupted。现役 `run-local-service.sh market-runtime-preflight` 返回 `blocked` / `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。未跑 installer、未 promotion。 |
| v1.10.5 自然盘后 | 现场验收 | 不得用 v1.10.3 成功记录或旧状态字节代替。 |
| 盘后日历未知、异常退出、副作用报告 | 代码缺陷 | 上轮线索见下节；须在任务精确基线复现。已实现的日常增量与独立 weekly-audit 不得被包装成“全历史已完整”。 |
| 现有牛哇旧请求回写、面板冲突、分页定位 | 代码缺陷 | `useNewowProduct.ts` 已有代次/取消/冲突处理；隔离脚本只是线索。黄金固定截点九组合可作为回归基础，不得改截点或冒充当前全品种。 |
| 其他品种物理历史与页面可用性 | 数据缺口 | 元数据不得再列为待修。须按品种/周期/面板区分元数据缺失、物理历史缺失、质量异常、正常样本不足和原站证据不足。 |
| 牛哇新版综合解释 | 新版需求 | 同输入已确认新版五项/`R0–R4`/`MM1–MM4`/计龄与当前 v3.2.59 四项/13 格合同 3/3 不一致；总分含未展示 `certExtra`。详见 [当前复核](docs/research/newow-current-review.md) N09。震荡 60 分钟图表差异为 `KNOWN_DIFFERENCE_ACCEPTED`。 |

## 本轮稳定版边界（冻结）

近期里程碑是：交付一个盘后结果可信、失败可诊断、部署可验收的稳定版本。工作 1–5 服务该里程碑；工作 6、7 不是同一任务，不要求完成后才能发布。

**本轮阻塞**

- 工作 2：旧中断运行未得到有证据的归类，或收尾后部署预检仍失败且原因不明。
- 工作 3：若进入本轮候选，则日历未知假跳过、普通异常假运行状态、部分提交假成功、未知结果假只读必须先有隔离故障注入证明。
- 工作 5：候选相对 `v1.10.5` 的真实 diff 未冻结、未审查；发布与 Runtime promotion 未分别批准；新版本自然盘后未验收。
- 工作 4 仅当主动合入同一候选时，才成为该候选的阻塞项。

**本轮不阻塞（已披露限制）**

- 牛哇新版评分、`certExtra`、收益曲线、盘中确认时钟、Newow 真实推送。
- 其他品种全部历史补齐、真实全品种九组合矩阵。
- 已接受的原站差异，包括震荡 60 分钟同根重建。
- 正常空仓、未完成周线、样本不足；不得改成“有结果”。
- HTDY 61 对 Scope 未应用；BU/BZ D1/W1 异常。
- 原件缺口继续 `EVIDENCE_REQUIRED`：诊断 token、六组合评分/排序、AI 逐字 copy、目标/吸筹权威昨收与期货 owner parity、比较器 browser-final/tie golden。
- 旧苏冰 failure 时间戳、Topic 其他成员送达人数。

`develop` 相对 `v1.10.5` 已包含中断收尾、来源时间、closeout 配置、日常增量/weekly-audit、牛哇显示与黄金/59 品种数据记录等。owner 已接受该全量 diff 作为下一稳定版范围；工作 5 仍须在发布前冻结精确 commit 并覆盖验收，不能把范围接受写成已经发布。

## 待办分类

上轮四项代码问题列为待精确基线复现，不直接认定为生产根因。已被后续提交修好的，只补验证，不重复修改。GitHub 当前无开放 Issue；不新建平行台账，统一挂到下表已有记录。

### 现场验收

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 旧盘后中断收尾 | `docs/DATA_CENTER.md` 收尾合同；OpenSpec `historical-data-maintenance` | 本次只读授权已消费且失败。下一步先使 after-market loaded 且 idle，再取得新的只读 closeout 意图；不重用本次命令、不加载服务冒充 idle |
| 现版本自然盘后 | 本文件 Runtime 表；不得使用 `cece65929…` 旧成功字节 | 工作 5 发布并切换后再验收 |
| 收尾后部署预检 | `deploy/README.md`；今晚 preflight 为 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` | 工作 2 写入 interrupted 之后再预检；当前部署仍阻塞 |

### 代码缺陷

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 交易日 / 非交易日 / 日历未知 | `coverage_source.py` `latest_metadata_day` 与 `after_market.py` 跳过 `NON_TRADING_DAY` 的连接 | 先证明“今天记录缺失、昨天存在”的触发路径，再按权威 Calendar 修复 |
| 异常退出状态转换 | `after_market.py` 状态写入；禁止用一个 `finally` 清掉所有 `current_run` | 区分写入前失败、部分分区已提交、提交结果未知、进程中断 |
| 副作用报告 | `runtime_entry.py` 对 after-market/weekly-audit 异常固定 `readonly=true` | 已写入时不得报未经证明的只读或零写入；错误码可诊断，不输出凭据/SQL/敏感异常 |
| 牛哇旧请求回写与分页定位 | `apps/quant-web/src/composables/useNewowProduct.ts` 及其测试；黄金固定截点预览 | 用可控延迟在真实组合式函数/页面复现后，统一取消、代次、在途快照、面板与分页绑定 |

### 数据缺口

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 59 品种元数据 | develop `e27ede9bd` / `a53389cc5` | 已完成，不再重开 |
| 黄金日周分钟与本地九组合 | 本文件已证明事实 2；Git history 保留逐批 hash | 已完成本地预览；不把截点证据改写为当前生产矩阵 |
| 其他品种物理历史 | 现有 bounded readiness / MDS 读回入口 | 稳定版之后按共享物理合约去重分批，先定范围再申请写入 |

### 新版需求

| 项 | 既有记录 | 下一步 |
|---|---|---|
| 牛哇新版综合解释 | [当前复核](docs/research/newow-current-review.md) N09；稳定合同仍见 `PROJECT_SOURCE.md` 与 OpenSpec `newow-product-reference-trading` | 先批准来源版本、计龄、五项、总分与 `certExtra` 显示或禁用；新版本身份，不改主动作/参考交易/通知 |
| 收益曲线、嵌套路径、盘中确认、Newow 推送 | 同上 N03/N10/N11/N12，标为 P2 | 本轮不扩展 |

## 七项工作对应

| 编号 | 工作 | 类型 | 目标 | 范围 | 前置 | 验收 | 阻塞对象 | 下一步 |
|---|---|---|---|---|---|---|---|---|
| 1 | 状态和范围收敛 | 文档 | 能直接看出现在做哪一项、还差什么 | 只改当前状态表述与任务对应；不改公式、产品边界、业务代码 | 无 | 打开本文件即可区分已完成/待验证/待修复/新需求 | 不阻塞发布本身；阻塞“继续混成一个大任务” | 本项随本文完成；下一项为工作 2 |
| 2 | 当前中断盘后安全收尾 | 现场验收 | 旧运行有证据归类；部署是否仍阻塞可说明 | 只读核验现役 Runtime、五服务、状态文件、共享锁、配置来源；条件满足后单独批准 apply 记 `interrupted` | 现场只读授权已消费 | 通过到身份绑定后失败；状态未写；部署仍阻塞且原因为 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` | 继续阻塞 Runtime 切换 | 不重试本次；after-market 加载与下一次 closeout 均需新意图 |
| 3 | 盘后运行生命周期与错误判断 | 代码缺陷 | 降低下次故障恢复成本 | `coverage_source`/`after_market`/`runtime_entry`；日常增量与 weekly-audit 保持独立 | 工作 2 的生产写入不得与本项生产操作并行 | 隔离故障注入：日历未知不假跳过、普通异常不留可避免假运行、部分提交不假成功、未知结果不假只读、不自动重试 | 本轮稳定版后端主任务 | 先复现再修；不新增队列、不放宽写入、不重写数据中心 |
| 4 | 现有牛哇加载与显示一致性 | 代码缺陷 | 现有公式下页面可靠 | 请求取消/代次/在途快照/面板/分页；策略/周期切换、历史分页、参考定位、冲突恢复 | 独立前端任务；与盘后生产写入解耦 | 旧响应不能恢复失效数据；分页和定位不改变参考统计口径 | 仅在合入同一候选时阻塞该稳定版 | 精确基线复现；不改三策略主动作、新版评分或参考价格口径 |
| 5 | 范围固定的稳定版本 | 发布/部署 | 结束继续加内容的循环 | 冻结候选真实 diff；相关回归、集成、Web 构建、浏览器验收、独立 Review；main/tag/release 与 Runtime promotion 分批批准；新版本自然运行验收 | 工作 2 未闭环可能阻塞切换；范围已接受全量 develop | 发布了哪个精确版本、部署了哪个版本、哪些自然 Gate 已完成/仍待验证全部清楚 | 本轮里程碑 | 工作 2 闭环后冻结精确 commit；本步不发布 |
| 6 | 其他品种可用性与分批补数 | 数据缺口 | 事先知道可用范围和缺口 | 复用 readiness；按真实依赖去重；每批 MDS 读回和对应页面 | 稳定交付恢复后；每批真实查询/写入另需单次意图 | 每批有输入范围、结果和未关闭问题；未恢复品种明确披露 | 不阻塞无共享完整性问题的盘后稳定版 | 先出可用性清单，不边跑边扩范围 |
| 7 | 牛哇新版综合解释 | 新版需求 | 把规则适配从显示修复中分开 | 新版本身份；先内核固定输入，再接口和页面 | 先批准新合同，含 `certExtra` | 同输入能解释新旧差异；分项与总分可核对；不改变主动作、参考交易或正式通知 | 独立后续候选 | Plan-only；本轮安排不构成实现或发布批准 |

工作 2 处理旧事故，工作 3 防止同类事故再变成复杂恢复；可以分别推进，但不能同时进行会互相干扰的生产操作。同时最多一个盘后主任务和一个独立前端任务。生产写入、收尾和 Runtime 切换串行。测试建设嵌入工作 3、4、5，不再单开没有终点的全面测试重构。

## 仍待人工裁决

1. **稳定版候选范围**：owner 已接受当前 develop 全量 diff。精确冻结 commit 与验收矩阵仍属工作 5。
2. **工作 4 是否进入本轮稳定版**：仅当范围与验收已满足同一候选条件时合入；否则独立后续版本。
3. **上轮四项代码问题的生产归因**：在精确基线复现前，不写成现役 v1.10.5 故障根因。
证据不足的条目保持待裁决。临时 evidence 路径再次使用前须检查存在与完整性。

## 唯一下一步

工作 2 本次只读已失败并停止：after-market 未加载，closeout 未越过身份绑定，旧运行仍是 2026-09-09 `current_run`，部署预检为 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。下一步是使现役 `com.guiyi.quant-after-market` loaded 且 idle，再取得 **新的** 只读 closeout 意图。本次授权已消费；不加载服务、不重跑本次命令、不 apply。

工作 3 隔离复现仍可另开，但不得与下一次生产 closeout 并行。本文件不构成 launchctl load、apply、发布或 Runtime promotion 批准。
