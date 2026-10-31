# 个人开发与本地验证

任务边界与协作方式只看 [AGENTS.md](../AGENTS.md)，当前状态看 [STATUS.md](../STATUS.md)。
本页保留代码定位、必要验证和本地联调入口，不另设开发阶段或审批流程。

## 讨论、开发与真实操作

owner 控制任务、架构与节奏，Codex 负责定位、实现、必要验证和交付。目标清楚就直接推进；
已讨论方案交办实施后不重开设计审批。只读、讨论、Plan-only 或仅编码限制继续有效。

## Codex 模型调度

新线程默认 **GPT-6 Sol Medium**，单次显式选择优先。按任务需要选模型，不固定分工接力。

| 任务 | 默认模型 / 推理强度 |
|---|---|
| 边界清楚的机械修改、文档和简单测试 | GPT-6 Luna / Medium |
| 普通工程、指标与策略实现 | GPT-6 Sol / Medium |
| 根因复杂、并发/恢复、OOS/Walk-forward、未来函数、重绘、参数稳定性与候选评价 | GPT-6 Sol / High |
| 架构、跨域语义争议、高风险独立 Review | GPT-6 Astra / Medium 或 High |
| 上述层级仍无法可靠收敛的极端复杂问题 | Ultra，例外使用 |

量化公式与回测实现至少 Sol Medium；研究方法争议用 Astra High。GPT-5.6 Sol/Terra 仅作历史续接或回归备用。
模型等级不增设 owner 审批，也不替代必要测试。

## 日常 develop 流程

```text
交办 → 快速核对工作区与相关实现 → 开发 → 必要测试与自审 → 提交/按目标发布 → 确认实际生效
```

- 默认使用合适的现有工作区；有实际冲突再从 develop 隔离。不固定要求 task branch/worktree、Issue、PR 或分支收尾。
  遵守远端实际限制，保留用户与其他任务修改，不全量暂存无关内容；集成后顺手清理本任务临时资源。
- 不设候选冻结、解冻或 release candidate 阶段，不因修复产生新 commit 重走整套验收。
  owner 控制本次范围；Codex 补验受影响部分，普通发布不等待未受影响历史数据或全部自然业务场景。
- 小任务用聊天和 diff，复杂架构才写必要设计；不固定写 Spec/Plan、验收矩阵、报告与收尾清单。
  工具需要的精确输入和执行记录保留，不再另做同内容材料。
- 先定位代码、数据、运行或证据问题，再修对应原因；不能用页面默认值掩盖不足，不能以体验修复名义顺带改公式或收益。
  实际缺陷要修，不将其改名为“已知限制”。新增需求说明影响，重要范围或语义变化由 owner 决定。
- 实现者负责必要验证和自审；仅实际高风险或任务要求时独立 Review。不强制多代理、固定 TDD 或全仓测试套餐。
  独立工作可并行，共享生产状态、补数与运行切换按依赖和锁串行，不抢占自然维护。

## 文档与版本的唯一入口

- [README](../README.md#工程入口)索引现役入口；执行、状态、产品、架构、业务与验证各归原有权威文档，不复制规则或待办。
- 被现役合同取代的计划、实现笔记和旧代码先检查消费者/引用再删除，历史从 Git 找，不建 archive、backup 或 legacy-copy。
  已完成 OpenSpec change 的 delta 同步到 active spec、实现集成后移除；来源、研究输入/结果、账本及必要恢复记录按用途保留。
- 牛哇公式与最新对照只维护[唯一手册](research/newow-v3.2.82/REPLICATION_MANUAL.md)，不因应用发版另建版本手册或常驻导出件。
- 只维护当前应用实现，不维护旧应用兼容矩阵、历史发布分支或常驻回滚源码。旧发布树解除实际运行与恢复引用后清理，
  具体引用检查见 [部署合同](../deploy/README.md#发布工作树存储)，不固定执行完整封存链。
- 应用版本唯一来源仍为 `services/quant-api/app/version.py` 的 `APP_VERSION`，API、包与 Web 共用。
  编号、现有工具要求的 tag/commit 和对应构建检查由 Codex 随发布处理，不单开版本管理任务或等待 owner 指定编号。
  改版本时运行版本一致性检查、`uv lock --check --offline --project services/quant-api` 和受影响构建。
- 不移动已发布 tag、不将 dirty 源码冒充原版本。运行代码保留可核对的 commit；公式、数据和账户历史所需身份继续保留，
  不为此维护旧应用代码或人工版本材料。研究比较固定输入、规则和评价口径；普通工程不套用研究冻结流程。

## Web 支持与验收范围

当前仅支持 **PC 浏览器 Web**。页面、图表、弹窗、文字与交互按 PC 窗口验收；根据实际使用检查桌面窗口尺寸、浏览器缩放和高 DPI 显示。
手机、移动端布局、移动视口和触摸手势不属于开发或验收要求，不为这些场景新增适配、缺项或阻断。
既有移动端样式、测试及历史截图不构成持续维护承诺；后续只有 owner 明确交办才扩大支持范围。

## 按影响验证

- 文档/注释：引用与格式、`git diff --check`，按内容做 secret/OpenSpec 检查；不跑无关业务测试。
- Web/API/后端：先验证直接受影响功能，再决定是否扩大 unit、E2E、pytest、lint、typecheck、build 或 smoke。
- 数据、公式、migration、并发、成交与账本：保留对应正确性、隔离集成和必要独立 Review；隔离库按 [TESTING](../TESTING.md) 使用。
- 不固定 TDD 顺序，不重复验证未受影响部分，不放宽质量断言或截图阈值制造通过。
  当前实际运行身份和功能需现场确认，fixture、dry-run、health 与历史成功不能替代真实业务结果。

## 发布与运行确认

目标包含发布或上线就连续完成，不另停在候选阶段。工程、发布、服务生效及自然业务结果如实说明即可，
不强制逐级状态枚举或分阶段报告。普通发布确认新代码和受影响功能/服务生效即可交付；自然行情或通知尚未发生单独注明，
仅当本任务明确以自然闭环为验收目标时等待对应事实，不拖住无关工作，不擅自补发或重放。

问题默认在当前代码向前修复再发布，不常驻维护回滚版本。数据和账本变更仍要有可验证恢复办法；
生产结果不明先查清，现有安装器的原子失败恢复、互斥、幂等和禁重试合同不因流程简化取消。

## 按任务定位

- Web/图表：`apps/quant-web/src/`、相关 API/OpenSpec 与 unit/E2E。
- 后端/CLI/仓储/Runtime：`services/quant-api/app/`、[架构](ARCHITECTURE.md)及对应业务 canonical。
- RQData、Canonical、Catalog、MainContractMap 或 `guiyi data`：项目 futures-data skill 和 [数据合同](DATA_CENTER.md)。
- 发布、运行切换、发布树清理：项目 release-agent skill 和 [部署合同](../deploy/README.md)。
- 验证命令只从 [TESTING](../TESTING.md) 选本次需要的部分；按需协作见 [角色清单](AGENT_ROLES.md)，不强制角色组合。

## 本地联调

### 独立 develop 首页联调

在 develop checkout 的仓库根目录启动独立 API：

```sh
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m app.develop_preview api
```

在同一 checkout 的 `apps/quant-web` 运行 `npm run dev:develop`，页面为 `http://localhost:5175/market`，HTTP 与 WebSocket 默认代理到同一 develop API8002。正式5173/8000不随此命令切换。

首页控盘复用确认 Bar 的现有控盘指标；日线收益展示现有 ordinary 页面参考收益及参考交易数，零手续费与滑点，不是牛哇私有最佳周期准确率或账户收益。目标／吸筹空间以确认收盘价计算；日周综合信号与日线参考价格分别表达。缺失或身份不匹配的数据继续显示待确认。


首页策略联调先显式执行 `guiyi home build --output <开发派生文件>`，启动8002 API时设置
`GUIYI_HOME_PROJECTION_PATH` 指向该文件。首页GET只读投影，首次缺失不会自动计算。
正式默认投影与开发文件分离；不要为预览启用盘后任务或切换正式Runtime。

开发预览入口使用既有严格读取器加载 `~/Library/Application Support/GuiyiQuant/project.env` 的
DB、Canonical 和 Redis 依赖，不输出或修改配置；按正式启动器规则补齐 Redis URL 认证。
先运行同前缀的 `python -m app.develop_preview build`，显式构建 `.run/develop-newow-home.json`；
API 固定读取该开发文件，不覆盖共享正式派生资产。缺失时显示未发布，GET 不自动构建。
首页日周图标旁的“历史”及展开原因说明发布有效性；正常已完成日周线不会因分钟报价变化而重算。
参考收益显示累计页面收益与笔数；距离始终按日线参考收盘价计算，正常卡片在悬停说明中提供基准及日周各自截至时间；历史／失败状态保留可见原因。

### HTDY 60m 冻结历史参考联调

独立 develop API 与 Web 启动方式沿用上节。首次显式构建（只读行情、写开发派生目录）：

```sh
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m app.reference_trading.htdy_snapshot build --symbol jm --since 2025-10-30 --through 2026-10-30
```

普通历史查询展示窗口最多一年，底层仍从权威物理前缀预热；显式构建使用 `--full-history` 可从权威 product_start 冻结全部现有历史，换品种替换 `--symbol`。构建安全加载既有受保护依赖，
不连接Broker、不下载行情。快照在 `.run/htdy-snapshots`，GET不会构建；未生成时明确不可用。
主图默认回放参考，来源切换联动独立记录区；SimNow和首次观察缺公式身份时并列，不用当前常量补造历史证据。

全品种现有历史回放采用单次串行队列（同上 PYTHONPATH/python 前缀）：

```sh
python -m app.reference_trading.htdy_snapshot_batch run --through 2026-10-30 --seed-jm-snapshot <已核验的JM全历史快照ID> --preflight
python -m app.reference_trading.htdy_snapshot_batch run --through 2026-10-30 --seed-jm-snapshot <同一ID>
```

队列冻结 active/operational 同一60品种、各自权威维护起点、公式/模型/展示及相关执行文件hash；
JM优先，其余按清单顺序。每品种600秒只读构建，进度在 `.run/htdy-full-2026-10-30.json`。
续接先核对进度文件未被修改，且manifest与执行文件一致；只处理pending，已成功项只读核验，
失败和中断不自动重试。单项证据失效标为interrupted，继续其他pending；finished只表示队列结束，
只有全部60项succeeded且快照分别读回通过才可报告全品种构建完成。该入口不下载或修复行情。

已定位并修正失败原因后，可显式用 `--inherit-state <旧进度绝对路径> --state <新进度绝对路径>`
创建新尝试；必须先取得旧批次锁确认其已停止。旧文件保留，成功快照校验后继承，只有明确 failed 项恢复 pending，未知中断仍不重试。
显式 HTDY builder 只保留每物理段全部 owned bars 及首个 owned Bar 前至少31根的整交易日上下文；
预算预检和读取共用权威 endpoint，不改变完整历史计算区间、质量校验或普通查询默认行为。
闭合参考收益摘要和曲线统一按退出时间及交易ID累计 Decimal，避免不同展示顺序产生尾差误报。
