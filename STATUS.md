# 当前状态

更新：2026-09-27。本页只保存当前交付状态、证据入口和未完成事项。历史检查点从 Git 和对应任务证据查找，
不再把旧版本“当前状态”按时间堆在本页。执行授权见 [AGENTS.md](AGENTS.md)，版本维护见
[开发流程](docs/DEVELOPMENT.md#文档与版本的唯一入口)，产品边界见 [PROJECT_SOURCE.md](PROJECT_SOURCE.md)。

## Release 与 Runtime

正式发布及已切换 Runtime 的精确身份为 **v1.10.38@18b29c985817683bf5dfd08ae3328a4762caf9b3**。
PR #403、annotated tag 与非草稿 [GitHub Release](https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.38)
已读回。develop 后续提交不自动属于该 tag 或现役 Runtime。

现役源码根为 linked worktree `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-v1.10.38`，
迁移时 detached/clean；六项服务 root/commit、HTTP200 和 readonly health 已读回。
发布树统一位于扩展盘，切换读回后只保留最新版本；旧 runtime-v1.10.34～38 和旧 linked release-v1.10.36 已移除。
问题在最新发布树向前修复并发布补丁，不覆盖旧 tag。必要历史盘后/周检 JSON 在
`outputs/newow-release-v1.10.38-20260927/retired-runtime-evidence/`。

状态为 **RELEASED，切换及即时读回通过**；新根第一根自然 completed Bar、自然盘后增量/MDS 与新根 weekly
验收仍待完成，**不声明 RUNTIME_READY**。9/24 周检的 23 条 finding 保留；新根 missed/无结果不能替代历史结论。
详见 [发布与切换记录](docs/tasks/newow-release-v1.10.38-20260927.md) 和
`outputs/newow-release-v1.10.38-20260927/`。

## 当前产品与验证范围

- Newow 日周三策略以及日周 CDV2 解释、独立双策略入口已随本次版本交付；主图、辅助、参考曲线和近三个月记录分层。
  Newow 60m 未开放，日周解释不构成 StrategyDecision、模型账户或真实交易。
- 正式 60 品种 D1/W1 默认快照、质量断点与预热披露已完成本轮数据/页面验收；不是每个组合均 READY 或盈利的声明。
  来源不足、WARMING、报价不可用及数据中断仍按合同表达。
- 正式 JM 日线页面主图/辅助/参考收益及双策略入口已读回；普通 74 笔累计 183.66 是页面参考统计，
  理论值与普通参考曲线具有独立口径，不是账户收益。
- 最终发布验证：前端 691 passed / 1 skipped、后端定向 171 passed、隔离浏览器 6 passed；
  build、Ruff、Newow spec 与独立 Review 通过。工程检查 22 passed / 1 既有截图批准库存失败；
  旧分页 E2E 漂移与全模块测试中断已披露，未声明全量通过。以上仅归属冻结发布候选。
- 当前持续服务保持既有 operational 集合、Rule/Scope/audience（2）及 transport；reference worker 关闭，
  `auto_order=false`。本页不授权新增数据范围、通知、订单或可选定时任务。

日周数据与验收依据：
[W1 收尾](docs/tasks/newow-w1-closeout-20260926.md)、
[W1 页面验收](docs/tasks/newow-w1-page-acceptance-20260926.md)、
[日周发布及 RS 修复](docs/tasks/newow-d1-w1-release-v1.10.36-20260926.md)。
SuBing 已有自然 Event/实际收件闭环归属旧 exact `v1.10.5@cdd72d750`：2026-09-09 Event #143–#146，
owner 确认 #146 PT2610 14:00 对应微信收件。该完成事实不重开，也不证明当前版本或其他受众实际收到。

来源版本与公式复刻边界见 [当前研究复核](docs/research/newow-current-review.md)；历史原站证据不等于当前期货 OOS。

## 分钟 Newow 首品种历史候选

P0–P6 首轮工程与隔离验收已完成并快进集成 develop，集成后定向回归通过。RB `1m/15m/30m/60m × 趋势/震荡/独立融合` 的
4输入、8基础保存流、4融合流与12页面模式都有证据；36期货边界样本、48辅助、上市预热、同日分页、
容量/取消、真实Chrome及高风险独立Review已完成。精确实现候选为 `10d40faa05badc04c86cefb65c53525a11dba4fb`，
本节不把后续文档提交当另一轮业务实现。

候选默认关闭、只在隔离preview对RB开放；资产只写隔离schema `newow_intraday_pilot_20260927`。
复用已有Canonical，实际缺口为零，provider/Canonical/Market Catalog mutation均为零。
正式日周开关、worker、Scope、Runtime与 `auto_order=false` 未变。P7全量、发布/切换、观察启用、通知、
订单及因果/OOS研究未执行。SQL/hydrate取消有界但非即时；旧7项fixture漂移与既有reference-trading
OpenSpec结构失败单列，没有声明全套通过。详见 [首轮执行与验收](docs/tasks/newow-intraday-pilot-20260927.md)；
下一轮从 [P7精确盘点](docs/superpowers/plans/2026-09-19-newow-intraday-roadmap.md#p760-品种扩大与维护接续) 开始。

## 统一参考交易与数据恢复未完成项

P0–P8 工程和隔离验收已经集成；**P9 生产闭环未完成**。Newow 页面参考投影验收不等于持久化统一参考交易验收。

- 460 个 SuBing D1 质量候选已一次性原子发布；生产读回 `already_applied=460/460`、`old_count=0`。
  3,113 个源 Close=0 分类为 `NONPOSITIVE_CLOSE_SOURCE_FACT`，保留 5,175 根有效 Bar 与显式质量事实。
  精确备份及 journal：`outputs/reference-p9-d1-quality-20260925/`。
- 首波 175 单元 warm-up 中前 6 单元已提交、读回 80 个分区，已知 provider 请求 21 次。
  第 7 单元 `al/AL2302/15m` 为 `UNIT_OUTCOME_UNKNOWN`：22 个目标仍未发布、请求次数无法证明，
  **未重试，余 168 单元未启动**。结果不明保持阻断，不用重规划缺失证明请求可安全重试。
- 最近一次 600 流只读审计为 `SOURCE_READY=387 / BLOCKED=213`；之后 15 条 W1 流复核中 SC/SI 六条
  SOURCE_READY，PL/PX/RS 九条仍为 `REFERENCE_BOUNDARY_CONTEXT_MISSING`。这些是对应旧精确提交的审计，
  当前版本完整矩阵、历史构建与持续更新须重新绑定 exact code/input identity，不能沿用旧结论。
- 未完成 0048 migration、剩余历史构建、全局 persisted reader 切换和 reference worker 启用；
  P9 持久化“统一参考交易”面板的既有 503 未关闭。Newow 页面参考投影不受此结论替代。
- A2611 旧来源请求已按 `SOURCE_RESPONSE_IDENTITY_INVALID` 停止且禁止重试；后续 D1 修复后重审无新恢复目标，
  不是对旧请求的重试。六个 W1 新批次共 64 个 W1 与 64 个 D1 同源上下文目标通过，来源 journal 64 次请求。

完整 P9 证据与恢复边界见 [rollout](docs/tasks/unified-reference-trading-p9/rollout.md)，
`outputs/reference-p9-warmup-wave1-20260925/`、`outputs/reference-p9-source-inventory-20260925/`。
旧盘后 D/E/F 已关闭，不重跑；旧事故未证明的生产归因继续保持证据不足。

## 已接受的后续交付规划

日周交付 → 关闭已记录页面缺口与自然维护验收 → Web 体验改善与分钟数据准备 → 分钟产品独立验收开放。
当前日周交付已发布；不能再按旧 v1.10.8/v1.10.9 检查点把该阶段重开，或把最新切换认定为自然验收通过。

- Web 正确性随对应版本验收，纯 Web 改善不等待分钟补数；不顺带改变公式、参考收益或数据来源。
- 分钟准备由同物理合约 Canonical 1m 派生，复用 Catalog/MDS、Session、质量校验、维护锁与预算；
  去重窗口、有源先派生，只对明确缺失安排恢复，失败按合同停止。补数完成不自动开放产品。
- 分钟开放分别验预热、Session 聚合、换主力、completed Bar、参考记录、分页与故障状态；
  跨周期解释保留 bar_end/as_of，不用未来完成周线回填历史决策。
- 策略公式、页面参考、因果研究、OOS/Walk-forward、Shadow 和账户事实分别验收；解释评分不自动成为执行 Gate。

分钟任务当前另有工作树和未提交路线图，不由本文档整理重新解释或推进。

## 唯一下一步

按最新 exact Runtime 版本完成自然 completed Bar、盘后增量/MDS 和 weekly 的证据读回；
期间页面已确认缺口与 P9 未知结果分别按各自合同处理，不制造 Bar、不盲目重试，也不扩大现役运行范围。
