# 个人开发与本地验证

更新时间：2026-08-13

本文定义仓库日常开发与外部副作用边界的唯一流程入口；产品、数据、策略、信号和 Runtime 语义仍由
`PROJECT_SOURCE.md`、`DECISIONS.md` 及对应 deep canonical 定义。当前可执行产品面以 `STATUS.md` 为准（Market-only，含有界 Historical/Live seam）。

## 唯一日常流程

普通仓库变更直接使用：

```text
develop
-> 检查 branch/status/最近提交并识别已有改动
-> 只修改当前任务范围
-> 按影响运行本地验证
-> 可选 commit
-> 可选 git push origin develop
```

普通源码、测试、普通配置、研究实验和文档变更可以直接在 `develop` 编辑、验证、提交和推送。
协作门禁与可选工具边界见 `AGENTS.md`「个人开发工作流」与 `DECISIONS.md`「个人开发」；本文不重复罗列。

开始修改前记录现有 dirty paths；不覆盖、不还原、不暂存与当前任务无关的改动。提交时只选择当前
任务文件，不使用会意外纳入无关改动的全量暂存方式。

## 本地验证

本地验证是完成声明的依据，按影响选择：

- 仅文档或非执行注释：运行适用的引用、格式和 diff 检查。
- 可执行行为：运行覆盖所改行为的定向测试，并按需要补充模块测试、lint、类型检查或构建。
- 数据身份/质量、策略、回测、信号、migration、Runtime、live 或通知：运行对应领域专项测试，
  且保留 deep canonical 的业务约束。
- tracked 内容发生变化时运行适用的 secret scan；输出不得包含命中的秘密值。

当前仓库没有 backtest API/Web/worker/queue/CLI，也没有 `guiyi runtime plan` 或 active 旧 scheduler component。
Market Runtime V1 的 `runtime live`、`data after-market` 与运行健康只读状态已实现；代码和 launchd 模板默认关闭，当前本机是否启用及部署根仅以 `STATUS.md` 为准。
Alert V1 的 Application Domain、API、Web 与独立 `runtime alert` 代码已实现；它不恢复已退役的
Signal/Review/Strategy 链。production migration、真实 WeCom canary 与 Alert Runtime activation 未经各自
明确请求不得执行，当前状态同样只以 `STATUS.md` 为准。
唯一 active 运维链为 Mac launchd → FRPC → 腾讯云 FRPS/Nginx；本地状态只使用
`scripts/ops/macos/local-services-status.sh`，分段只读检查与配置导航见 `deploy/README.md`。仓库不保留
并行 PID 管理器、远端 API/Web 副本或会隐式执行 migration 的聚合启动器。
不要用旧测试、脚本、evidence 或 Git-history 路径恢复兼容入口；未来回测重建必须单独立项并从
Canonical/MarketDataService 合同开始。

任何必需检查失败时，明确报告失败，不宣称任务完成。CI 如存在，只是补充结果，不是本地开发、
commit 或 push 的前置授权。

## 开发态 Runtime 部署

```text
clean develop + 预期提交
-> 受影响测试 / Ruff / Mypy / Web build
-> 当次明确的部署请求
-> render 并 lint launchd plist
-> 只重载已授权的服务面
-> 读回安装根和健康状态
```

`--render-only` 是普通无副作用验证；`--confirm-load` 和 `--confirm-market-runtime` 会改变本机服务状态，属于受控外部操作。直接修改 `develop` 不会自动生效：Web 需要 build/重载，API/Live 需要重载。开发态运行不是 Ready、Runtime promotion 或最终验收；功能收口后仍需独立精确提交的 Runtime worktree。

## 普通仓库删除

删除 Git 跟踪的过期源码、测试、普通配置、工程流程、hook/rule、CI、ADR 或文档属于普通仓库删除：
扫描并关闭 active references，以 Git 历史恢复。细则见 `AGENTS.md` / `DECISIONS.md`。

生产数据库记录、正式市场数据、Runtime 状态、live 配置、remote refs 或 Git 历史不属于普通仓库
删除；它们必须按受控外部操作处理。

## 受控外部操作

生产 DB/正式数据不可逆写入或删除、远端 release/tag、force update 或历史重写、Runtime/live
切换、真实通知及 GitHub 规则修改，在执行前需要用户一次明确请求，并给出操作类别和可识别范围。
该请求只授权紧随其后的一个匹配执行尝试；完成、失败、重试、范围变化或后续会话都需要新的明确
请求。

Dry-run 只验证计划，绝不转化为 mutation authorization。授权模型与禁止从历史材料推断权限的细则见
`AGENTS.md`「受控外部操作」与 `DECISIONS.md`。执行前仍须校验输入、范围、认证、质量和安全开关；
业务正确性约束优先于任何执行意图。

Release/tag 的意图不授权 Runtime/live、通知、数据写入或 GitHub 规则修改；每个类别和范围必须
分别请求。普通 `git push origin develop` 仍属于上述日常开发流，不继承为 release/tag 或其他
外部操作权限。

唯一的持续授权例外是用户明确要求在识别出的本地工作站“启用 Market Runtime V1”后，既定
`operational_products.txt`（当前与 active 60 一致）的 rank1 Live 观察与 17:00/一次 1h retry 盘后更新可
持续运行；该请求不授权其他 DB mutation、release、真实通知或订单。未
收到该请求时，只能执行 mock、临时目录、render-only 与只读健康验证。

Alert Runtime V1 是另一份独立持续授权：只有用户在识别出的本地工作站明确启用后，才允许
`htdy_original_15m × enabled scope_products × WeCom` 对后续自然 confirmed 15m Bar 持续运行。该授权
不从 Market Runtime 继承，也不覆盖新增 Rule/渠道、production migration、Runtime switch、release、
Canonical 写入或订单。migration、真实 canary、activation 三个 Gate 必须分别取得一次性执行意图。

## 不可放宽的业务边界

- 正式历史数据继续遵守 DatasetKey、精确八表 Market Catalog、MainContractMap、coverage/可读性和
  MarketDataService 边界；Historical Canonical 与 Live Observation 分离。
- 策略、回测和正式历史信号禁止未来函数、泄漏和未记录重绘；交易相关计算使用 `Decimal`。
- Signal/Review/Strategy 应用链已经退役；Alert V1 只使用新设计的 Application Domain，不得恢复旧事件表、
  RQ worker 或历史补发路径。
- Live、真实通知、Runtime switch/promotion 均受独立 Gate 约束；Market 与 Alert 两份持续授权只覆盖各自
  明确范围，不能相互或向外扩张。
- 所有输出都是研究观察，不是交易指令；`auto_order=false`，拒绝创建或提交订单。
- 不读取、显示、提交或记录凭据；外部输入在命令、文件、网络或数据库敏感操作前完成校验。

## 权威边界

- 工程执行规则：`AGENTS.md`
- 日常开发流程：本文
- 当前状态：`STATUS.md`
- 长期产品与数据边界：`PROJECT_SOURCE.md`、`DECISIONS.md`
- 数据与查询 active 合同：`openspec/specs/`

本文不得复制或重新解释业务 canonical。
