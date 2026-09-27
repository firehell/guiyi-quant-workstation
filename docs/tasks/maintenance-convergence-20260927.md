# 全项目维护性与稳定性收敛（2026-09-27）

## 目标、现场与审计粒度

Owner 批准“保留现有产品能力，清除无用内容、重复实现与补丁式兼容”的聊天方案，并要求实现。
基线为 `develop@5f62b5c69f1466940cfb5296a66a75e047179f9c`，使用独立任务 worktree。
主工作区的 Newow 双策略图表、comparison、测试、路线图及未跟踪验收产物不属于本任务。
不改公式、输入质量政策、收益、数据/迁移、Scope、通知、Release 或 Runtime。

[逐文件清单](maintenance-convergence-20260927-inventory.tsv) 覆盖基线全部 2,347 个 tracked files。
覆盖指文件登记、静态结构/引用检查及候选复核，不代表逐行形式化证明、生产数据验收或所有动态路径均已执行。
清单是本次冻结审计，不建立新的长期事实源；新增/变化的实现以 Git diff 为准。

| 分类 | 文件数 | 检查方式与结论 |
|---|---:|---|
| 源码/配置/脚本/资产 | 650 | Web main import 闭包（含动态 import 和类型引用）、Python AST imports/函数重复、Ruff、入口/部署补查 |
| 测试及 fixture | 361 | 对应实现消费关系、现役回归与失效断言核验 |
| 文档 | 105 | 当前产品/架构/验证导航与实现交叉核对；历史文档保留原证据语境 |
| 历史 outputs/output | 1,183 | 文件登记、字节重复与证据引用检查；未证明失去追溯用途，不删除 |
| Alembic 历史版本 | 48 | schema lineage，不按退役 application 名称删 migration |

TS import 未解析项为 0；清理前 9 个源码文件从 main 不可达，清理后为 0。
Python AST 中没有内部入边的模块逐项对照 scripts、deploy、测试与职责；不能把 CLI、preview、worker、
手动 activation/reconciliation、研究 evidence、质量恢复入口误删。声明的主要运行依赖均有现役用途，未更改锁文件。

## Confirmed Issue：本次处理

### 1. 孤立前端实现（维护风险，中）

当前 `/market/chart` 已进入 MarketDetailPage / NewowProductWorkspace。旧链只在链内和专属测试被引用，
不存在 Vue 动态注册/自动目录扫描。删除以下 9 个源文件：

- `apps/quant-web/src/api/newow.ts`
- `apps/quant-web/src/composables/useNewowTrendDetail.ts`
- `apps/quant-web/src/types/newow.ts`
- `apps/quant-web/src/utils/newowTypes.ts`
- `apps/quant-web/src/utils/newowViewModel.ts`
- `apps/quant-web/src/components/market/detail/newowTrendChartPrimitives.ts`
- `apps/quant-web/src/components/market/detail/MarketDetailFactStrip.vue`
- `apps/quant-web/src/components/market/detail/MarketDetailStatusStrip.vue`
- `apps/quant-web/src/utils/runtimePresentation.ts`

删除专属的 newowApi/newowTypes/newowViewModel/useNewowTrendDetail/newowTrendChartPrimitives/runtimeStatus
六个 unit test 文件；共享 shell 测试只移除已删除组件部分。保留 Free、HTDY、SuBing、现役 Newow、
Runtime 后端与主页消费者的验证。E2E 删除无人消费的旧 trend-detail payload/杯柄 fixture 构造，
保留旧 URL 规范化验证和“不应再调用旧前端请求链”的捕获。

后端 `/api/v1/market/newow/trend-detail` 的固定 D1 合同与测试完整保留。删除前端旧链不等于删除此 API。

### 2. capability 版本分支堆积（维护风险，中）

`newowProduct.ts` 原来为每版复制 stage/frequency 判断，并串接 14 个 formalWeekly 分支与品种三元表达式。
改为内部显式版本表 + 一条校验路径。20 个已有 wire 版本、候选范围、精确顺序、冻结行为及错误分类保持不变；
未知版本不回退。逐版本既有测试和新增非法响应测试先在旧实现通过，再验证重构；临时差分程序对比
20 版共 2,672 个有效/变异输入，真假判定全部一致。未抽象日周 snapshot policy，也没有新增公共 API。

### 3. 失效测试与序列化残留（低）

基线 Web 739 passed / 6 failed / 1 skipped。五项失败来自普通 Newow URL 序列化包含
`newow_mode: undefined`；改为只在 dual 时输出该可选字段，保留 dual roundtrip 测试。
另一项测试仍要求旧“主升浪”导航标签，更新到已提交的“双策略”，不改当前导航或策略身份。

工程 AGENTS 测试要求已经废止的审批固定措辞；移除措辞清单，保留领域导航实际存在、引用与边界不复制检查。
清除恢复 verify 脚本的一处未使用 import。TESTING 删除已退役前端 test 命令引用。

浏览器夹具尚未接受当前独立三个月记录请求（limit=200 + snapshot + 窗口），修正精确请求形状和窗口响应，
保留原普通累计摘要；旧 CSS 测试改为比较实际公共样式与 unified 状态，不要求不同视角有完全相同的 class 字符串。
没有更新截图基线、降低阈值或用 fixture 证明真实行情。

### 4. 架构/产品文档漂移（中）

更新 `docs/ARCHITECTURE.md` 的职责表与 ReferenceTrading 仓储/worker/query 依赖，纠正默认日线快照政策，
把逐批开放名单的权威收回 `product_release`，防止架构文档继续停留在 48 品种。
`PROJECT_SOURCE.md` 更新现役导航与统一参考交易描述；不复制生产启用状态、不恢复已退役账户/执行域。

## Risk / Needs Verification：保留并披露

- `test_newow_screenshot_distribution_owner_decision_is_explicit` 在基线失败：测试精确集合仅覆盖原29张及9/18的5张，
  而仓库已有9/26新增截图/文本。该项包含分发合同，不能为通过测试自动扩充批准集；本任务不修改这些文件或批准状态。
- `apps/quant-web/e2e/newow-product.spec.mjs` 的旧参考历史分页场景仍假定全历史记录和“加载更多参考历史”，
  与现役固定三个月记录不同；独立Review以 `--grep 'reference pagination exposes' --timeout=15000` 实测，
  OPEN/CLOSED展示通过后在第367行等待旧按钮超时。原helper已拒绝limit=200，本次未改变limit=50行为；
  此项为既有测试漂移。本轮6项smoke通过，不声称整套历史E2E已通过。
- 全仓发现184处宽泛异常处理；重点复核吞异常/None分支，涉及日志清理、资源释放、Live provenance 不可用、
  Calendar 缺失与失败后释放锁。它们不能统一替换为抛异常；本次未确认需要改变运行语义的具体缺陷。
  静态审计不证明所有生产异常路径正确，未来如有触发证据应按具体故障处理。
- 持久化 ReferenceTrading 与纯页面投影不是同一事实；activation/reconciliation 即使只被测试/显式操作使用，
  也不能作为“无HTTP调用”删除。worker启用与P9现场问题不在本次代码清理内。
- 历史证据中两个 `collect.py` 字节相同，但属于9/10和9/11两次采集记录，保留各自语境；不重写Git历史清理体积。

## Optional Improvement：本版不做

- HistoricalDataManager、MarketDataService、ReferenceRepository 等大文件：行数本身不是缺陷，
  没有可靠的职责迁移收益时不机械拆分，避免把时序/事务复杂度转移给调用方。
- daily/historical snapshot 构造器及两种 source quality 的 to_record 有局部重复；政策和类型不同，
  仅为减少几行引入基类/泛型会扩大接口，保持局部实现。
- 有界修复脚本的 SHA/JSON/bar 序列化不能未经冻结 hash parity 合并；依赖已存在的历史恢复入口保留。
- Vite 提示 request.ts 同时静态/动态导入；动态导入还承担 Node 测试隔离，非第二套 transport，暂不为消除警告改结构。

## 验证与交付

所有 fixture 验证只证明应用交互，未访问真实来源或生产数据。

| 实际验证 | 结果 |
|---|---|
| `pnpm -C apps/quant-web test` | 684 passed / 1 skipped / 0 failed（685 total；删除孤立测试不计作修复旧功能） |
| `pnpm -C apps/quant-web build` | vue-tsc、Vite、bundle topology 通过；保留既有静/动态 import 提示 |
| `node --test apps/quant-web/tests/newowCapabilities.test.ts` | 22 passed；新增非法字段/未知版本/冻结行为覆盖 |
| 临时 Node stripTypeScriptTypes 差分旧/新校验函数 | 20版本 × 有效/变异输入，共2672次结果相同 |
| `pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs --grep 'owns an independent chart\|missing view migrates\|Free uses\|Newow HTDY and Free share'` | 6 passed；隔离fixture，非生产或自然验收 |
| `python -m pytest -q -p no:cacheprovider tests/engineering/test_canonical_consistency.py tests/engineering/test_repository_hygiene.py services/quant-api/tests/newow/test_market_newow_api.py services/quant-api/tests/newow/test_market_newow_product_api.py` | 80 passed / 1 baseline failure（上文截图批准集合）；不含hygiene的76项全部通过 |
| `python -m ruff check services/quant-api/app packages/quant-core/guiyi_quant scripts tests/engineering/test_canonical_consistency.py` | passed |
| `python3 scripts/engineering/secret_scan.py --json <本次变更的存活文件与两份审计文档>` | passed，0 findings |
| 同扫描器全 tracked scope | 1项既有test Reader.token修订标识命中，AST核对为测试快照标识，不是凭据；不更改扫描器/白名单 |
| `git diff --check`、清单精确覆盖与任务文档链接检查 | passed；2347条唯一基线路径，15项删除 |

Python 使用既有 `services/quant-api/.venv/bin/python`（主工作区绝对路径），
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core`，代码来源为任务 worktree。
隔离浏览器的旧详情fixture未提供持久化ReferenceTrading流，拒绝连接到固定无服务端口，
该独立面板不可用不代表真实持久化链路验证成功。

恢复方式：所有删除来自 Git tracked files。按本任务 commit 做整批 revert 可恢复；不建立备份副本、不撤销用户其他修改。

## 独立 Review 与集成出口

独立 GPT-6 Astra High Reviewer 检查完整变更、动态入口、20版capability、fixture与文档职责，
结论：无本次新增 Confirmed Issue，允许集成 develop；保留上述历史E2E风险。
Reviewer 独立运行 capability/route/shell/status/navigation 55项unit，全通过；diff检查通过。
本轮保留现有产品能力，正式数据、通知、main/tag/release和Runtime均未变更。
本任务提交可独立回滚；集成与远端身份以最终Git祖先检查和读回为准。

## 2026-09-27 验证遗留项收敛

本轮基线为 `develop@779551f310edd67d5eb4e25120bb0599cbf5698e`，在独立工作树实现；
只修改验证代码和测试数据标识，不修改生产组件、公式、数据、Runtime 或截图材料。

- 截图卫生检查：原 Owner 批准的29项及9/18五项哈希保持冻结；已经在仓库中的9/26
  18项公开观察使用 `latest-audit-20260926.json` 校验精确路径、类型、大小、哈希与重复。
  拒绝路径逃逸、symlink和未登记文件；不将原审批改成任意 glob 审批，不添加新分发材料。
- 完整秘密扫描：Reader 的 source revision 标识明确使用既有 `test-only` 约定，扫描器未改。
  新正例保证真实长 token 赋值仍被报告且不回显值。
- 旧参考分页验证：按固定三个月 `history_limit=200` 建立可分页场景，严格倒序且按同一
  Bar owner 复用价格事实；收益曲线读完整两笔 CLOSED，记录独立分页，中断浮动不混入已完成收益。
  替换已移除的逐条展开/筛选/建仓信号定位操作，验证当前曲线定位记录、窗口隔离和显式记录重试。
  统计409夹具只命中统计请求，保留主图 `not_requested` 和去除 snapshot 绑定的恢复断言。
- 新增 `newowRecordsFixture.test.ts`，以固定日期、精确Decimal汇总与价格预期验证新夹具；
  初始化同时验证三策略×三周期的跨section owner事实。

| 实际验证 | 结果 |
|---|---|
| `pnpm -C apps/quant-web test` | 685 passed / 1 skipped / 0 failed |
| `pnpm -C apps/quant-web build` | vue-tsc、Vite及bundle topology通过；保留既有动态import提示 |
| `PLAYWRIGHT_PORT=5199 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs --grep 'reference pagination\|curve selection\|curve window\|record cursor\|reference rebuild\|owns an independent chart\|missing view migrates\|Free uses\|Newow HTDY and Free share' --timeout=20000 --reporter=line` | 最终11 passed（9.2s）；独立Review另跑其中5项全部通过 |
| `python -m pytest -p no:cacheprovider tests/engineering/test_repository_hygiene.py tests/engineering/test_secret_scan.py tests/engineering/test_canonical_consistency.py services/quant-api/tests/reference_trading/test_revision_rebuild.py -q` | 36 passed / 3 skipped；三个PostgreSQL重建用例因未配置隔离测试数据库跳过，未访问生产DB |
| `python scripts/engineering/secret_scan.py --json` | full tracked scope通过，0 findings |
| `python -m ruff check tests/engineering/test_repository_hygiene.py tests/engineering/test_secret_scan.py services/quant-api/tests/reference_trading/test_revision_rebuild.py` | passed |
| `git diff --check` | passed |

独立Review：工程16项、定向浏览器5项及九组合跨section校验均通过，允许集成已完成部分；
未发现Confirmed Issue。当前完整浏览器套件与视觉Gate仍未闭合，不能据上述定向结果声称全部通过。

### 尚未收敛的完整浏览器 Gate

完整回归命令：`PLAYWRIGHT_PORT=5199 pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/market-detail.spec.mjs --timeout=15000 --reporter=line`。
本轮扩展扫描得到63 passed / 16 failed；执行期间增加过夹具预校验，最终定向出口另行重跑。
失败涉及旧动作点击/密集节点交互、已移除的主升浪Tab/记录定位入口、刷新按钮名称、
独立记录请求增加后的请求计数、旧桌面/移动截图、对话框滚动，以及SuBing视觉和HTDY Event刷新。
这些失败未全部逐项证明为旧断言漂移，不能统称为无害基线，也不能通过删测试或换截图全部消除。
`newow-desktop-reference.png` 原断言所覆盖的旧展开卡片已移除；本轮迁移为当前卡片字段与
窗口隔离检查，未建立该画面的新视觉基线，旧PNG保持原样。

宿主自动审批两次阻断验证迁移：一次阻断将`not_requested`直接改为`ready`（已经通过
修正冲突注入对象、保留原断言解决）；另一次阻断批量将已退役动作点击测试改为展示属性断言，
认为可能掩盖行为回归。后者未执行，不绕过自动审批。剩余处理方案为：先对每个失败确认
当前产品合同和等价覆盖，再迁移旧用例；截图须逐张确认新画面后建立基线，保持现有阈值。
已完成部分可以独立集成；完整E2E/视觉验收状态仍为PARTIAL。

集成前现场发现另一任务已将 `dfcb8796b1b6a9f26f033bbbce6fc633c3eb84d8`
（v1.10.38 Newow交互收尾）提交到develop，与本轮七个文件无重叠。
任务分支先合入该提交，随后重新验证实际集成候选：前端692 passed / 1 skipped，
build及bundle topology通过，最终11项浏览器回归再次全过（8.9s），完整秘密扫描0 findings。
这次集成复验仍不替代完整E2E与视觉Gate。
