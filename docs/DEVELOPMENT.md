# 个人开发与本地验证

本文提供日常开发导航、任务收敛与版本交付规则。工程授权与外部操作规则见 `AGENTS.md`；当前状态见
`STATUS.md`；产品和数据边界见 `PROJECT_SOURCE.md`、`DECISIONS.md` 及对应 deep
canonical；可执行命令见 `TESTING.md`。

## 讨论、开发与真实操作

- “先讨论”“比较方案”“只读审计”或 Plan-only 只产出分析或计划，不提前修改。
- 明确要求实现且目标、边界、验收已确定时，Codex 连续完成范围内的编辑、修复、相关测试、Review、
  commit/push 和已授权的 develop 集成，不把进度更新变成新的批准 Gate。
- 局部命名、组织方式和测试选择由实现者按现有模式与风险决定；发现本任务引入的失败时继续修复和重测。
- 数据、策略、Alert、Runtime、发布等设计与真实 mutation 是两层边界：设计获批后可连续编码，但代码完成或
  develop 集成不授予生产写入、main/tag/release 或 Runtime promotion。

## 日常 develop 流程

```text
develop
-> 检查 branch、worktree、dirty state 与最近提交
-> 保留并避开其他任务或用户已有修改
-> 只修改当前任务范围
-> 按影响运行本地验证
-> 独立 Review（任务要求或风险需要时）
-> 提交并按任务授权集成 develop
```

普通源码、测试、文档和仓库内普通删除可按上述流程执行。删除前先关闭 active
references；历史恢复使用 Git，不建立 archive、backup 或 legacy-copy。

## 任务收敛与版本冻结

阶段顺序和当前出口统一看 [STATUS.md](../STATUS.md) 的“已接受的后续交付规划”，
不在本页另存阶段完成状态或建立平行路线图。

每个可独立交付的任务先固定目标、所属阶段、允许/禁止范围、输入依赖、验收及未完成 Gate。
小型、低冲突任务可在正确工作区 Direct；中等、Lane 3 或可能与其他工作冲突的任务从 develop 创建
task branch/worktree。保留用户已有修改，按协作需要选择 PR 或可追溯的集成记录，不强制 Issue/PR 仪式。
确认提交已进入 develop 后，
才清理本任务的临时 worktree 和已合并 branch；不清理其他任务或 main/runtime 工作区。
本页不另设权限，普通文档更新可沿用上述日常 develop 流程。

### 冻结后只处理交付阻断

候选冻结精确 commit、真实 diff、声明支持范围与验收矩阵。已接受的集成不为追求“最小补丁”
反向重拆；冻结后不再接收无关需求。确需修正阻断项时更新精确候选并补跑受影响验证，
不能让旧 commit 的验收结论自动覆盖新候选。

数据错误、结果误导、旧响应污染、无法部署、故障状态不可信，以及适用检查失败，
是该次交付的阻断候选；按实际影响和证据判定。未开放范围的历史不足、纯视觉改进、
新研究想法不自动进入当前版本。已披露限制只有在不破坏共享完整性和声明支持范围时才可后置，
不得把应修缺陷改写成“已知限制”来绕过 Gate。范围实质变化须重新明确任务与验收。

### 问题分类，不混修

| 类型 | 处理方式 | 不允许的替代 |
|---|---|---|
| 代码缺陷 | 在最新精确基线复现；已合入修复先验证，未解决的定向修复并保留回归 | 未复现就写成生产根因，或重复重写已修逻辑 |
| 历史缺口/质量异常 | 复用 readiness/MDS，明确物理合约、窗口、原因和单批处理范围 | 因页面空白同时改数据、公式、API 与 Web；造数、缩窗、跨频回退 |
| 证据不足/正常样本不足 | 分别披露并保持原策略结果与证据状态 | 以无信号、0 分、示例值或默认值掩盖不足 |
| 发布/现场状态问题 | 核对 exact 版本、现场证据、部署条件与恢复路径，独立完成对应 Gate | 用测试通过、旧成功记录或收尾 interrupted 宣称当前运行成功 |
| 新版需求 | 独立任务、合同和验收；涉及语义变化先审计划 | 以显示修复、数据恢复或体验优化名义顺带改评分/公式/通知 |

### 并行与测试边界

同时最多一个主任务和一个互不干扰的独立前端任务。互不依赖的源码工作可并行；
生产补数、旧事故收尾和 Runtime 切换串行，共享锁或数据依赖的现场操作不能并行推进。
审计、受控补数与自然维护复用既有锁和资源边界，不抢占自然盘后任务。

Web 正确性随对应功能版本完成，不能延后到视觉优化；体验任务不顺带改公式、统计窗口和来源。
后续纯 Web 版本不等待 60m 历史补齐；数据准备完成也不自动开放 60m 产品。
测试嵌入每项修复、功能和候选验收，不另开无明确出口的全面测试重构；不放宽质量断言、
未来函数保护或截图阈值制造通过。

### 发布与运行验收分开

工程验证、develop 集成、main/tag/release、Runtime promotion、自然运行验收分别记录，
release 批准与 Runtime promotion 批准是两个独立人工 Gate，均不能由任务集成推导。
旧事故收尾不等于数据维护完成；日常成功不等于全历史完整；数据就绪不等于策略/页面已开放。

发布前确认候选与所有消费者的兼容性及可用恢复路径；生产已产生 hash URI 时，
不得将只支持固定 URI 的旧版本作为通用回退。切换后才采集对应 exact 版本的自然业务证据；
尚未发生或未验证的场景如实保持待验收。受控写入、真实查询、失败后的重试与跨会话继续，
仍遵守 `AGENTS.md` 的范围校验和单次执行意图，不因本规划获得新的持续授权。

## 修改前检查

- 确认当前任务目标、允许范围、验收标准和禁止范围。
- 数据、策略、回测、Alert、Runtime 或发布语义有冲突时 fail-closed，并以对应
  canonical 和 `STATUS.md` 为准。
- 不读取、输出、提交或记录凭据；不覆盖、不清理无关 dirty paths。

## 按影响验证

- 文档或注释：引用检查、`git diff --check`，以及适用的 OpenSpec/secret scan。
- Web：定向 unit/E2E，再按风险运行完整 Web unit、Playwright 和 build。
- 后端：定向 pytest，再按风险运行模块/完整 pytest、Ruff 和 Mypy。
- 数据身份、策略、migration、Runtime、live 或通知：追加对应领域测试；isolated
  PostgreSQL 只按 `TESTING.md` 使用专用可销毁数据库。
- 任何必要检查失败时只报告失败，不声明完成。

测试、fake runner、route intercept、render-only、dry-run 和只读 health 都不授权真实
RQData、Canonical、DB、Redis、Scope、Runtime、通知或发布操作。

## 按任务定位

- Web、Vue、图表或浏览器问题：从 `apps/quant-web/src/`、相关 Market API/OpenSpec 和现有 unit/E2E 定位。
- FastAPI、Pydantic、应用数据库域、Redis、Alert、Runtime 或 CLI：从 `services/quant-api/app/`、
  `docs/ARCHITECTURE.md` 和对应 OpenSpec 定位；Alembic 只有涉及 Market/Catalog 时才归入数据任务。
- RQData、Canonical、Catalog、MainContractMap、数据质量或 `guiyi data`：使用项目 `futures-data` skill，
  以 `docs/DATA_CENTER.md` 和相关 data OpenSpec 为合同。
- release candidate、main/tag/Release、Runtime switch 或 worktree 清理：使用项目 `release-agent` skill，
  并读取 `deploy/README.md`；发布和 Runtime promotion 始终分开。
- 测试命令从 `TESTING.md` 选择，先定向、后按影响扩展；不为无关改动机械运行全仓库验证。

受控操作和持续授权的精确判断只看 `AGENTS.md` 及其指向的领域 canonical；当前状态只看
`STATUS.md`。本页不复制权限清单或业务合同。

## 相关入口

- 工程规则：`AGENTS.md`
- 当前状态：`STATUS.md`
- 产品与长期决策：`PROJECT_SOURCE.md`、`DECISIONS.md`
- 架构与数据：`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`
- active OpenSpec：`openspec/specs/`
- 验证命令：`TESTING.md`
- 本机部署导航：`deploy/README.md`

已完成的实现笔记只从 Git history 追溯，不把 `docs/superpowers/` 当当前设计源。
