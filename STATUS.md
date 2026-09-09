# 当前状态

文档核对：2026-09-09，develop 代码基线 `79c59ccb4`；统一详情页本轮修复已通过 owner 视觉接受并集成 develop。
本日 P1 验证使用临时数据与隔离 PostgreSQL；后续 WebSocket/详情页验证使用离线测试与浏览器 fixture。
上述工程验证没有连接生产 PostgreSQL/Redis/RQData 或重新验收 Runtime。
另有本日获准的 AU 来源查询与单键生产 Calendar 更正，具体事实及边界见 Newow 小节；没有切换 Runtime。
以下生产结论保留原采集时间，不能当作今天的实时健康状态。

本文件只保留 release、Runtime、Scope、关键验收事实与未完成 Gate。稳定产品面见 `PROJECT_SOURCE.md`，
长期决策见 `DECISIONS.md`，active 依赖见 `docs/ARCHITECTURE.md`。已完成的计划、逐次操作、旧候选矩阵及
逐合约结果从 Git history、tag、PR 和原 evidence 追溯；历史授权不授权重跑。

## v1.10.5 已发布并切换（两合约补齐待执行）

- 独立候选分支 `codex/subing-input-release-candidate` 基于 `0eca85209008e036626b37eb5563fc504dba12bc`；
  API/Web/Python/lock 版本身份与版本一致性断言为 `1.10.5`；已审候选为 `0d2273445637a6dd5cfef2a45c4f1242276952c5`。
- 本次新跑验证：直接相关 `357 passed`；backend + engineering `2967 passed, 16 skipped, 28 deselected`；
  隔离 PostgreSQL publication `6 passed`；Web `504 passed, 1 skipped`、typecheck/build 通过。
  浏览器首轮 89 passed / 60 failed / 3 skipped：60 项源于运行端口 5192 与 fixture 固定 5182 不一致；
  使用正确端口复跑这 60 项全部通过，candidate-preview 专用 3 项另跑全部通过。
  Ruff、Mypy（150 source files）、9 项 OpenSpec 与 secret scan 通过；代码基线独立 Standards/Spec Review 无阻塞。
  版本收尾后的 engineering + health `80 passed`、离线 `uv lock --check` 与 Web build 通过；版本增量独立复核无阻塞。
- 该候选包含已集成的 Canonical P1、captured Runtime 身份解析、WebSocket 资源边界、统一详情页、
  SuBing 历史参考与 Newow 只读相关改进，不是仅两合约数据修复的最小代码补丁。
- 本轮批准的 main/tag/release 已执行并读回；AO2701/OI2701 的真实下载与 1m→15m 发布尚未执行。
  五项 Runtime 已获准切换并读回。12:07:40 CST 在现役 v1.10.5 重新 dry-run：各 9 个 1m + 9 个 15m，
  合计 36 目标、预计 18 次行情请求；两个 CLI exit 0、readonly=true、applied/blocked/failed=0。
  AO2701 plan hash `602821c7195a11c35a2b44b6a18c4b6d806d8e7b9eb98b1be1cc15e0d9e5f504`；
  OI2701 plan hash `a7431d8eac813486181e2c773f43b1a99b01f30c9469bd25be66d1d6cd7a1a4f`。
  两者仍限定 through=2026-09-08、15m（仅依赖 1m），与旧计划 hash 一致；真实 apply 尚待对应单次执行意图。
  新 hash URI 产生后不得回退只支持固定 URI 的 v1.10.4。

## Release、Runtime 与 Scope

| 项目 | 最近已记录事实 |
|---|---|
| 正式 Release | `v1.10.5@cdd72d7501227d8e7f905ea0b8a54c038b521a09`，PR #359 于 `2026-09-09T03:53:57Z` 合入 main；tree `11704da35b2eccf62bdddc330eb0e42ea5930247`，annotated tag object `71bad4102a9be883ba341c7dd27f0e98f59dab41`。GitHub Release 于 `2026-09-09T03:55:28Z` 发布，non-draft、non-prerelease；远端 main、peeled tag 与 Release target 一致。API/Web/Python/lock 为 1.10.5。 |
| 发布验收 | 已审候选 `0d2273445637a6dd5cfef2a45c4f1242276952c5` 与发布 tree 完全一致；验证矩阵见上节。本轮重新核验四处版本、远端 main、annotated tag 及 Release target；未重复运行已通过且输入未变的全套测试。 |
| Runtime | `2026-09-09 12:09:27 CST` 严格读回：五项 launchd 均加载 `/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1@cdd72d7501227d8e7f905ea0b8a54c038b521a09`；API/Web/Live/Alert running，After-market idle；Market/Alert marker enabled，Live/Alert 新鲜心跳同根同 commit 且 `recovery_guard_enabled=true`。切换完成、未使用回退；自然 completed Bar 验收待完成，不声明 `RUNTIME_READY`。 |
| Runtime 工作树 | 现役 detached v1.10.5 根与原 v1.10.4 根均保留且干净。新根离线安装锁定 Python/Web 依赖并 build；render-only 与三个 installer 模式均一次通过，未重试。旧根目前无五项 launchd 引用；未清理，新格式数据发布后不可将其作为兼容回退根。 |
| 最近 health | `2026-09-09 12:09:27 CST`：API 1.10.5；API/Web HTTP 200，Runtime health ok/readonly，Live/Alert 心跳新鲜，60 品种 BREAK、subscribed_count=0、last_bar_at=null；本地隧道通过。严格 captured Runtime 身份 verifier 通过。SuBing 保留切换前 `last_failure_at=2026-09-09T03:30:05.449850Z`；Rule error_type=null 不证明两合约输入恢复，历史缺失仍未关闭。 |
| Database | 最近已记录 production readback 为 Alembic `20260903_0045`；session anchor repair 已发布。旧全库 Dataset/分区/行数快照不作为当前总量。 |
| Market Scope | `operational_products.txt` 的 60 个品种。 |
| Alert Scope | `2026-09-07T06:49:43Z` 审计：HTDY 仅 `jm × 5m/15m`；SuBing 全部60品种 × 15m，两 Rule enabled。HTDY“焦煤15m和5m，其余59品种60m”共61对仍仅是未应用目标。 |
| 最近自然 After-market | v1.10.3 于 2026-09-08 自然运行，18:05:05 开始、19:05:52 完成，passed、attempts=1、60 品种，last_failure/current_run null。该状态经校验 create-only 先带入 v1.10.4，本轮以相同 bytes 带入 v1.10.5，hash `cece65929ba734c37cf91ee47af1b0d23b5dc3dd413c9d703888f669428347d5`；它不是 v1.10.5 自然盘后证据。 |

## Runtime 验收阻塞与开发差异

- WebSocket 阻塞读取修复 `fd6f566cc` 已合入 develop：同步读取进入最多四个并行 worker，
  每次独立创建与关闭 Session/Redis，取消不提前释放仍在执行的容量。backend 全量
  `2859 passed, 16 skipped, 21 deselected`、engineering `74 passed`，Ruff/Mypy 与独立 Review 通过。
- 统一详情页候选已删除旧页面及专用代码，保留旧链接的确定性迁移、Event 精确定位、
  失败态品种选择和盘后失败披露。Web `504 passed, 1 skipped`；完整浏览器 `149 passed, 3 skipped`
  （candidate-preview 专用场景）；build/typecheck、OpenSpec/secret/diff 与独立 Review 通过。
  工程状态为 `CODE_COMPLETE`、`TEST_COMPLETE`、`REVIEW_COMPLETE`；owner 已接受桌面/390px fixture 截图并明确允许合入 develop。
  本轮不发布、不切换 Runtime，fixture 不证明生产数据或自然业务闭环。

- Canonical P1 修复 `a6317cde262a14317e8db1f5fed962f94cd6e18d` 已完成不可变文件与 Catalog
  单分区原子指针发布；提交失败不再覆盖旧文件，结果不确定时明确停批。实际验证：backend
  `2855 passed, 16 skipped, 21 deselected`、隔离 PostgreSQL `6 passed`（含进程退出与事务可见性）、
  engineering `74 passed`，Ruff/Mypy/OpenSpec/secret/diff 通过，独立 Standards/Spec Review 无剩余阻塞。
  状态为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；尚未在生产发布 hash URI。首次生产使用前须统一升级
  消费者、停止旧 writer，并分别取得发布及 Runtime 切换授权；新指针产生后不得盲目回退旧读取代码。
  旧文件保留支持已有 reader，本次不执行文件回收或数据迁移。合同与命令分别见 `docs/DATA_CENTER.md`、`TESTING.md`。

- v1.10.4 的 captured-source 恢复入口误解析 launchd `event triggers` 中的 `=> {` 嵌套块，
  After-market 身份 Gate 失败。部署后的只读核对确认实际 root、commit、WorkingDirectory 与 idle 状态正确。
- `f08d86d88` 已在 develop 修复纯解析器并保留层级、重复字段、身份与括号校验；已记录验证为身份模块
  `76 passed`、调用链 `249 passed / 11 skipped`、engineering `18 passed`，两轴独立 Review clean。
  同份实机脱敏输出旧解析器失败、新解析器通过；未从开发根绕过 exact-tag Gate 运行恢复入口。
- 修复已发布并进入现役 v1.10.5；本轮真实 launchd、exact annotated tag 与新鲜双心跳的严格身份校验通过。
  自然苏冰评估与两合约历史输入修复仍待真实证据，不清除旧 failure，不将身份 Gate 通过视为业务闭环完成。
- 2026-09-08 19:26:46..19:26:57 CST 只读确认 RS2609 当日 Canonical 五周期
  `1m/5m/15m/30m/60m` 为 `225/45/15/8/5` 根，原五根日内目标均存在。
  当日 Live 已由自然盘后清理，恢复水位/circuit null，provider attempt count 仍为3。
  旧日内恢复计划已失效，不能为了完成步骤重建过期 Live 数据；以后恢复须另取当日精确计划和单次授权。

## 历史输入与自然闭环

- PF2611 于 2026-09-05 使用 exact v1.9.15 完成截至 `2026-09-04` 的 warm-up：76目标 applied，
  physical 15m 为4,491根，audit无finding；plan hash
  `7a51886988ff0508f6b3295d40665cef11ff54bc7b0b63ab79aee4fec5544f19`。该批准已消费。
- 苏冰截至 `2026-09-04` 的历史物理15m已完成 `60_OF_60_HISTORICAL_PHYSICAL_15M_VERIFIED`。
  2026-09-08 02:27:44..02:28:20 CST 经 MDS/Catalog/Canonical 全量读回259,183根、640个月分区，
  每项 actual=expected、`coverage_exact=true`。新增50合约为465 direct 1m + 465 derived 15m，930全部 applied，
  无partial/failed/blocked/unstarted或retry；批次hash `c181453a449c95ec711ac80cfee365ae6cec0cb3e6f89fa89572b6458a2e31c1`。
  原 `verify-last-run.json` hash `2d4afc3f714538a94758cc7af9e65e5618c282f35e6f8bfafecdbde9de1089d3`，
  evidence目录 `/private/tmp/subing-physical15m-20260907/`；保留索引不保证临时文件当前仍存在。
- 2026-09-08 盘后再次确认当日60个rank1合约上市日至收盘的physical15m前缀均exact；JD当时主力为JD2611。
  历史输入完整不能替代当前 Live readiness 或自然 Event 验收。
- BU/BZ旧七周期warm-up的D1/W1缺口仍未关闭。BZ `2026-03-20` 有 `volume=2`、O/H/L全0、close=7811，
  不能用close、settlement或1m填补；该问题不否定已完成的限定1m→15m历史验收。
- exact `v1.9.15@36fef03923a168145e6fd2eab023dc1d2b411ad6` 于2026-09-07夜盘自然生成
  AG2610 Event id=31，bar_end=`2026-09-07T13:15:00Z`，buy，detected_at=`2026-09-07T13:15:15.222713Z`；
  AL2610另在13:30Z/14:00Z形成sell/buy Event，均记录one-shot provider acceptance。
  Owner于2026-09-08确认收到对应沪银/沪铝微信通知，G11/G12完成，
  `SUBING_WECHAT_DELIVERY_CONFIRMED / SUBING_NATURAL_CLOSURE_COMPLETE`。Issue #307八项Gate已完成。
  这只归属v1.9.15历史闭环，不证明Topic其他成员送达或v1.10.4当前健康；provider accepted仍不等于送达。
- 早期自然Event为0、2026-09-03盘后`LIVE_DOMINANT_MISMATCH`失败等历史观察从Git history追溯；
  后续成功不改写这些历史失败，也不授权补评/补发。

## Newow 产品证据与开发候选

- 2026-09-09 黄金元数据接力已完成五合约 `AU2304/AU2306/AU2308/AU2310/AU2312` 的本批缺口修复。
  新来源审计于 `04:02:05..04:02:20Z` 独立完成 613 次 public metadata API（42 Calendar、571 Session），
  SDK RPC dispatch 575 次；无 retry、OHLCV、DB 或 Canonical 写入。source evidence hash
  `32c49db5713229aa290e1e4db734cc770390c6e8a96d62ac7634c3eb9b5a0a77`，目录
  `/private/tmp/newow-au-source-isolated-20260909-re136gmd/`。这不是旧失败批次的逐请求轨迹；旧批次已执行数仍未知。
  173 个候选中 168 个日期获得夜盘正证据；其余 `2022-04-06/05-05/06-06/09-13/10-10` 未更正。
  `04:14:31..04:14:32Z` 精确将 168 个 SHFE Calendar 的 `has_night_session` false→true，一次 commit、
  独立只读 readback verified，其他字段不变；不重复原 id46796 更正。plan hash
  `23c252c9d5d779ad3342b2bd768a6878c3edb33e7600a7420896b90a89406978`，结果
  `/private/tmp/newow-au-calendar-batch-20260909-9tu4f_4f/apply-result.json`。
- 更正后 fresh plan 与保存响应逐项核对，通过原生 snapshot 校验；`04:22:16..04:22:18Z` 再一次提交
  102 条 SHFE 非交易日 Calendar 与黄金 196 天的 779 条 Session，共 881 行，保留既有 200 天 Session。
  本次无 Calendar UPDATE、RQData 或 Canonical 写入、无 retry；独立只读回读一致，五合约本批范围的
  Calendar/Session 缺口均为 0。plan `aa8c8e3148181c54dfbb140083a60ff5757177ff14f45a590fb45e0c015e28b8`，
  snapshot `cd497e3249ba674b5a7a5d281f6e166bd94b59eff98e05758bb5961ff07e1af0`，结果
  `/private/tmp/newow-au-metadata-insert-20260909-one/apply-result.json`。
  上述两次 mutation 执行代码基线 `951d310df7bba7ac95597f1c77c658afac231be6`；168 更正包装器隔离测试
  9 passed，原生 bounded metadata 本轮 60 passed，独立 Review 通过。这些测试不证明页面恢复。
- 本轮只读核实五项 installed/loaded Runtime 同为 `v1.10.5@cdd72d750`，API/Web/Live/Alert running、
  After-market loaded、当前 not running，未发现旧 v1.10.4 根进程引用；本任务未重复切换。随后截至 `2026-09-08T07:00:00.000001Z`
  的 AU 真实矩阵审计返回 `PREFLIGHT_FAILED`，结果文件为空，仅保留通用错误码，不能声称矩阵已完成或定位真实原因。
  失败证据 `/private/tmp/newow-au-post-metadata-20260909-one/baseline.jsonl`；已停止外部操作、未重试。
  离线复现旧包装器不能序列化有效计划的 date 对象；预备入口增加类型序列化与安全 phase/error-type 记录，
  离线 3 passed；新的单次只读审计随后获准并完成，结果见下文。黄金历史行情补齐、
  真实矩阵验收与 8010/5174 浏览器验收仍未完成，未启动预览。所有临时 evidence 使用前须检查存在与完整性。

- `2026-09-09T04:32:40..04:34:19Z` 按新的单次批准在 `1f0ff619e` 完整执行黄金只读审计：
  `status=audited / complete=true`，12 个 section 窗口、132 项依赖全部完成，126 项
  `REPLAY_PREFIX_MISSING`、6 项 `DATA_READY`（AU2610 三周期在两个 as_of 边界），metadata proposal 为 0，
  无 source/integrity finding；主图仍为 0/9 ready，不能宣称页面恢复。provider、DB/Canonical writes、Redis、retry 均为 0。
  `/private/tmp/newow-au-audit-recovery-20260909-prepared/readiness.json` 文件 hash
  `1faddc07183e664bf861d410b79edab2c5f3b6a722eebdb72ec6ee12b3aeb0d5`。此成功不证明旧通用错误的真实原因。
  离线合并 21 合约的 63 个候选为 42 个 W1/60m 计划、904 个唯一物理分区；227 个独立 D1 窗口
  与 W1 伴随窗口逐项相同，故不重复执行。原生 provider target 计数 677 不是 public API 或 RPC 请求数。
  全部计划与 consumer provenance 见 `/private/tmp/newow-au-history-plan-20260909/consolidated.json`。
- 首批来源方案限定 `AU2304`，10 条精确交易所日行情请求覆盖 `2022-03-16..2022-12-30`，
  对应 2022-03..12 的 20 个 D1/W1 分区、196 根日线和 41 根周线。完整端点重建与原生 plan hash
  `9f4f789fc3cb0569bb43216c39d16f2b9f5cd8e60f1cb358ca4b14bf34853fad` 一致；独立 Review 已核验范围、
  日周去重与哈希。10 次调用仅是完整来源响应下的成功路径，必须用严格守卫拒绝缺日后的补充查询和越界调用。
  来源捕获守卫的 9 项离线测试通过，含缺日/重复/错合约及 timeout/GatewayError/PermissionDenied 单次派发，独立 Review 无代码阻塞；
  首批来源捕获随后按单次批准执行并停止，详见下文；Canonical 发布、补齐后矩阵与浏览器验收仍待完成。
- `2026-09-09T04:57:42..04:57:43Z` 在 `a54c51476` 执行 source-only 计划
  `e05dd542e8c35662a9cf0937bea5102ce7df350cc3bfd39089c2db7ac0107b91`，首个
  `AU2304 / 2022-03-16..2022-03-25` 请求完整返回 8 个源交易日后触发 `SOURCE_NONPOSITIVE_PRICE`，立即停批。
  实际 public API attempted/completed 均为 1，SDK RPC attempted/completed 均为 3（quota、type-list、日行情各 1）；
  原计划剩余 9 次行情请求未开始，无 retry，DB/Canonical writes 与 Redis connections 均为 0。
  结果 `/private/tmp/newow-au-history-plan-20260909/fetch-result.json`，逐请求事件同目录 `fetch-events.jsonl`；
  原始 `source-01.json` SHA256 为 `345ac234c465cb17e4e420e51fe5122e62f876038a550be29c1248b13ac17e17`。
  `2022-03-16/17/18` 三天均为 volume=0、open/high/low=0、close=400.12；其余五行 OHLC 均为正。
  现行 DATA_CENTER 零成交日规则允许用同一行有效 close 规范化全零 O/H/L，但本任务明确禁止填补原始零价，
  因而不能自动套用该规则写入或继续下载。仅离线生成三行前后对照并核验原响应未改动，见同目录
  `zero-volume-comparison.json`；该对照不是授权、真实修复或页面恢复。原捕获计划的执行意图已消费，
  后续须先明确这类零成交日的处理口径，再冻结尚未调用的范围；不重跑已取得的首个响应，不自动补取或发布。

- 2026-09-09 AU2304／2022-03-16 的已获准单次时段查询确认：来源含夜盘，本地 SHFE Calendar
  id=46796 原为 `has_night_session=false`。owner 新的单次批准已于 `2026-09-09T03:13:36Z`
  消费：使用 `79c59ccb4` 受限入口，仅将该行夜盘标志更正为 `true`，其他字段不变，提交后独立只读核验通过。
  本次 `database_writes=1`，`provider_requests=0`、`session_writes=0`、`canonical_writes=0`，无重试。
  精确 plan hash `2384a9cc382c94fb1616d0f508006fd374b3a6b6c6673c5823ff301e574749a7`；
  原结果 `/private/tmp/au-calendar-apply-20260909-zQDruw/result.json`（临时 evidence 不保证长期存在）。
  单键更正为 `COMPLETED`，不代表 Newow 整体恢复；其后本批 Calendar/Session 进展见上文，历史行情补齐仍未开始。
  独立规范/需求 Review 无剩余阻塞；完整后端与 engineering 非隔离回归合计
  `2967 passed, 16 skipped, 28 deselected`，另有单键隔离 PostgreSQL `7 passed`，
  Ruff/Mypy/OpenSpec/secret/diff 通过。旧批次计划已因前像变化失效；当时剩余的 173 个候选日期已由上文新来源审计区分。
  旧 613 次查询与旧单键更正授权均已消费，后续操作仍须重新核对范围，不自动重跑。
  不授权其他日期、RQData、Canonical、发布或 Runtime 切换，也不自动逆向恢复旧标志。具体边界见 `docs/DATA_CENTER.md`。

- P6工程已集成并发布，产品仍为 `P6_COMPLETE / PARTIAL_PRODUCT_EVIDENCE_REQUIRED`。
  [P6历史只读证据](docs/research/newow-v3.2.82/P6_TRUSTED_CLOSURE.md)归属v1.10.0：首30品种两轮及rb45项
  均HTTP500，`REAL_WORKSTATION_MDS_REQUEST_PATH=MEASURED`，成功路径性能未验收。
  MDS缺失映射转typed `NEWOW_DATA_UNAVAILABLE / HTTP409`的修复已包含在v1.10.4代码中；错误分类修复不补数据。
- 缺少截至as_of已生效owner时必须fail-closed。把owner窗口缩到最后completed display/performance日的方案
  已因破坏rollover与segment身份被拒绝，不能重试此“修复”。原2026-09-08只读repair计划已过期。
  后续使用现有bounded readiness审计重新枚举当前依赖，再区分metadata与physical warm-up；不得重跑旧hash。
- 2026-09-08获准的RB2701/RB2605/RB2610有界1m+60m补齐为39/39分区、15次RQData请求；
  三合约60m读回1,084/1,509/1,502根。该批准已消费，不授权其他周期/合约。
- 同一固定历史rb60m样本优化前后各五组新进程/同进程结果一致；DB语句2,433→89，冷/热HTTP中位数
  2,210/2,167ms→536/488ms，未清除OS/磁盘缓存。照妖镜12组有界绘图对照像素差0，
  不代表全产品、60品种SLA或在线全页面parity。该读取/显示改进已包含在v1.10.4代码中。
- 原件缺口继续为 `EVIDENCE_REQUIRED`：诊断token、六组合评分/排序、AI逐字copy、目标/吸筹的权威昨收与
  期货owner parity、比较器browser-final/tie golden；当前Core原包重放有接口漂移。
  杯柄D1 clean-room不是原页面精确公式；18个D1/60m OOS及9个W1执行事实不足不升级为新的`OOS_PASSED`。
- develop在v1.10.4之后另有有界旧窗口、快照/导航原子接受、只读readiness矩阵、分阶段metadata repair、
  默认关闭的本地候选预览与可信报价截止修复。代码入口和验证命令分别见架构文档与`TESTING.md`；
  这些代码没有因集成获得真实下载、DB/Canonical写入、release或Runtime授权。fixture不证明真实矩阵可用。

## 剩余 Gate

1. 发布并部署已审的身份解析修复后，重新完成exact-tag身份验收；自然completed Bar评估、当前60品种
   readiness及新版本自然盘后证据仍需独立核验。现有旧failure不得手工清除来制造通过。
2. Newow在当前权威owner/coverage完整后完成真实成功请求矩阵；原站parity与期货OOS/Walk-forward缺口独立处理。
3. Market 统一详情页实现、测试、独立 Review 与 owner 桌面/390px 视觉接受已完成；
   本轮仅授权 develop 集成，发布及 Runtime 切换仍不在授权范围。
4. HTDY目标61对Scope未应用；BU/BZ D1/W1异常未关闭。数据修复、Scope、真实通知、main/tag/release与Runtime
   操作均需新的目标/环境/范围明确的单次意图，不沿用本文历史授权。
