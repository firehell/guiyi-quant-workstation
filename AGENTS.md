# 归一量化 AGENTS.md

本文件是仓库唯一的开发执行规则。当前状态见 `STATUS.md`；长期产品边界见 `PROJECT_SOURCE.md`；业务语义见对应 deep canonical。

## 项目边界

- 做：数据治理、K 线、策略研究、回测、报告、复盘、信号提醒与人工观察。
- 不做：自动交易、实盘下单、SaaS、多用户权限、手机 App、无人值守交易。
- 信号、通知和 Web 始终是研究观察，不是交易指令。

技术栈固定为 Vue 3/Vite/TypeScript/Naive UI、FastAPI/PostgreSQL/Redis/RQ、RQData → Parquet → DuckDB，以及不修改源码的 vn.py 回测引擎。

## 日常开发与保护模式

普通开发适用于 Web、普通 API、只读查询、测试、非业务语义重构、文档与研究实验。直接说明目标和边界，在非 protected 的开发 worktree 实现、运行定向测试并交付 diff/风险即可。默认不要求 Issue、PR、任务合同、状态更新或每任务新建 worktree。

保护模式适用于策略或信号语义、回测成交/成本/换月/资金口径、migration、正式数据或 Profile 写入、live 表、Runtime、密钥与生产配置、真实企业微信发送及任何自动交易路径。必须保留 Issue/受控任务合同（如适用）、Plan、专项测试、业务专用 approval packet/Gate、用户明确的真实执行批准与 final receipt。

普通工作仍不得直接在 `main`、`develop` 或 Runtime checkout 修改。按当前 worktree 生命周期在受控开发或 task worktree 进行；Runtime 保持独立 detached。不要为了文档或小修复改变数据、策略、Runtime 或 Gate。

## 工程硬规则

1. 先检查分支、工作区、最近提交、相关实现与测试；不覆盖用户或其他会话的改动。
2. active 数据仅可来自 `rqdata/local_parquet + primary + quality_status != failed`；严格研究默认 `passed`。上层不得自行 glob、选 active、判主力或绕过 quality。
3. historical canonical 与 live observation 分离；live 不得直接提升为正式历史 active。
4. 策略、回测和正式历史信号禁止未来函数、泄漏和重绘；所有交易相关计算使用 `Decimal`。HTDY original 仅可使用 `docs/INDICATOR_KERNEL.md` 与 `docs/SIGNAL_EVENTS.md` 所定义的精确 observation-only 白名单。
5. 信号链路保持 `Strategy -> SignalEvent -> Notification Gate -> Channel`；默认关闭 autosend，永不产生订单。
6. 禁止读取、显示、提交或记录凭据；不修改 `.env`，不破坏 `data/raw/`、历史报告或冻结任务事实。
7. 真实数据、DB、Runtime、通知或部署写入必须使用业务专用、hash-bound、scope-bound Gate。没有专用 Gate 即禁止写入；Issue 批准不能代替代码哈希验证。
8. 不自动 push、merge、deploy、关闭 Issue/PR 或删除 worktree。ADR-WS-004 的合规 Lane 1/2 task 仅可通过受控入口完成固定验证、commit、push 与 draft PR；PR ready、merge、release、tag、Runtime、Lane 3 与 GitHub 规则仍须人工 Gate。发现环境、挂载、数据源或身份漂移时 fail-closed。
9. 输入、CLI、文件、网络和数据库值先验证类型、格式、范围和关联字段；SQL 使用参数化查询或既有 ORM。

## 数据核心 V2 迁移治理

`docs/tasks/GY-DATA-CORE-V2.md` 是当前数据交互核心收口的 active 执行合同。其目标架构已经冻结，
但除文档明确列出的已合入代码外，数据迁移、消费者切换、live/EOD 收口、删除和 Runtime 验收
均不得写成已经完成。

- active target 只有一个：RQData → 临时 staging → 校验 → 单一 historical canonical
  Parquet（provider 直接提供的 1m/1d/1w）→ 轻量 Catalog/Manifest/Gap/MainContractMap
  → `MarketDataService` → consumers。
- `continuous` 与 `actual_dominant` 是显式、不可互换的数据类型；消费者不得静默回退、
  替换或自行判断主力。
- 旧 Profile/ActiveBinding/复杂 lineage 只作为迁移期 legacy compatibility；不得继续扩展
  为新的 active selector。删除只能在消费者完成切换、Shadow/rollback 通过并获得独立批准后进行。
- 旧 `GY-CORE-04～08` 执行路线已 superseded/paused。`GY-CORE-02` Facade 与
  `GY-CORE-03` CLI 壳允许复用；已合入的 `GY-CORE-04` 代码保留为 legacy compatibility，
  但不得据此继续旧 Shadow/Runtime 路线。
- historical evidence/report/receipt 默认保护。只有逐文件 deletion manifest、替代回归证据、
  active 引用扫描、独立 Review 和用户对 exact scope 的批准全部具备时，才可执行受控删除；
  本规则本身不授权删除任何文件、Git 历史、数据库记录、Parquet、report 或 receipt。

协作 Lane、worktree、PR 与人工 Gate 见 `docs/DEVELOPMENT.md`；业务目标与迁移顺序不得复制到
该工作流文档中另行解释。

## 文档与验证

- 只在事实变化时更新对应 canonical：Gate/阶段更新 `STATUS.md`；长期边界更新 `PROJECT_SOURCE.md`；长期决策更新 `DECISIONS.md`；命令更新 README/`TESTING.md`；数据、回测、信号语义更新对应 deep canonical。
- 普通 bugfix、UI 调整和测试增加默认不更新项目状态文档。临时分析和会话 Plan 不入仓库。
- 修改后优先运行定向单测，再运行模块测试、CLI smoke、lint/type/build、API/browser smoke；真实 Gate 与代码测试分开陈述。
- 完成交付必须说明变更、实际测试命令和结果、风险/外部 Gate、文档更新及一个最小下一步。测试或真实 Gate 未运行时明确标记。

## 接手最小阅读

1. `AGENTS.md`
2. `STATUS.md`
3. 与任务相关的 deep canonical、受控任务合同、Issue 或 receipt

工程入口：`scripts/engineering/preflight.sh`、`test.sh`、`check-secrets.sh`、`runtime-health.sh`；
首轮统一业务 CLI 入口为 `uv run --project services/quant-api guiyi`，当前只允许
`data verify`、`runtime status` 与 `runtime plan` 的只读/dry-run 合同。详细运行/发布边界见
`docs/WORKTREE_RELEASE_WORKFLOW.md` 与现行 ADR。

## Worktree 与发布生命周期

`main`、`develop` 与 Runtime checkout 均不得直接开发；`main` 是 canonical/release，`develop` 是长期集成主干，Runtime 保持 detached。task 从 `develop` 在 `GuiyiWorktrees/tasks/` 创建，经用户手动 PR merge 回 `develop`。只有 task clean 且其 HEAD 已被 integration branch 包含时，才可移除该 task worktree 与本地分支。`worktree_flow.py` 默认 dry-run；`release-flow.sh publish --expected-sha <sha>` 只在用户批准、main/develop clean 且精确匹配时更新远端。它们不创建 PR、自动 merge、打 tag 或切换 Runtime。
