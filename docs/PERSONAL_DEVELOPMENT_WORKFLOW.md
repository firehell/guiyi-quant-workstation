# Personal Development Workflow

本文件是个人开发模式的详细 workflow canonical。日常入口见 `docs/DEVELOPMENT.md`。其目标是让
单一项目所有者在 `develop` 上快速迭代，同时把业务正确性与真实外部副作用边界保持为不可绕过的
约束。当前可执行产品面以 `STATUS.md` 为准（Market-only）。

## 1. 操作分类

开始前只需判断本次工作属于哪一类：

| 分类 | 典型范围 | 授权边界 |
|---|---|---|
| 普通仓库变更 | Git 跟踪的源码、测试、普通配置、研究实验、文档 | 可直接在 `develop` 修改并本地验证 |
| 普通仓库删除 | 过期源码、测试、工程流程、hook/rule、CI、ADR、文档 | 更新引用后直接删除；Git 历史恢复 |
| 受控外部操作 | 生产 DB/正式数据、Runtime/live、真实通知、远端 release/tag、Git 历史、GitHub 规则 | 一次明确、范围匹配的用户执行意图 |
| 业务正确性约束 | 数据质量、策略/回测语义、密钥、默认关闭、禁止订单 | 始终强制，任何意图都不能覆盖 |

路径在仓库内并不自动代表普通操作：如果命令会改变生产数据库、正式数据、Runtime 状态、远端
ref、live 配置或真实通知渠道，它就是受控外部操作。相反，删除 Git 跟踪的过期流程文件是普通
仓库删除。

## 2. 普通变更状态流

```text
START
  -> 确认仓库、develop、status 与最近提交
  -> 记录并保护任务开始前已有的 dirty/index paths
  -> 读取相关实现、测试和 canonical
  -> 仅修改当前任务范围
  -> 根据影响选择本地验证
  -> 必需验证全部通过
  -> 可选 commit（只暂存当前任务文件）
  -> 可选 git push origin develop
END
```

协作门禁与可选工具边界见 `AGENTS.md`「个人开发工作流」与 `DECISIONS.md`「个人开发」；本文不重复罗列。

### 2.1 保护已有改动

- 开始和结束都检查 `git status`，区分预存改动与当前任务文件。
- 不还原、覆盖、stash、清理或暂存无关路径。
- 发现同一目标文件被并发修改时，先重新读取并合并意图；无法安全合并则停止并报告。
- 自动化如需暂存，只列出明确路径；不把全仓库 dirty state 当作当前任务成果。

## 3. 影响匹配的本地验证

验证回答“当前改动是否正确”，不回答“是否获得真实操作授权”。

1. 文档-only：检查引用闭合、格式和 `git diff --check`。
2. 普通 executable change：定向单测优先，再按影响运行模块测试、lint、type check、build 或 CLI smoke。
3. 深领域 change：数据身份/质量、策略、回测、信号、migration、Runtime、live、通知必须运行对应
   专项测试并更新所需 deep canonical。
4. Secret-bearing surface：运行本地 secret scan，报告位置与 pattern family，不输出命中值。
5. 任一 required check 失败或不可用：报告真实状态和最接近的可执行替代，不产生成功结论。

CI 是可选补充。CI 成功不能代替本地验证，CI 缺失也不能单独阻止普通开发、commit 或 push。

## 4. 开发态 Runtime 部署

即使源码路径位于仓库内，重载 API、Web、Live 或盘后 launchd 任务仍会改变 Runtime 状态，属于受控外部操作。修改 `develop` 不会热更新已运行进程：Web 须先 build，API/Live 须重载。

```text
clean develop + 精确预期提交
-> 受影响验证全部通过
-> Web build 和 Runtime 依赖可用
-> 用户给出当次、范围明确的部署意图
-> render/lint
-> 只重载已授权服务
-> 读回安装的 GUIYI_PROJECT_ROOT 与运行状态
```

工作区 dirty、必需检查失败、Web 构建缺失、依赖不可用或安装根与目标不一致时停止，不重试、不 force、不扩大范围。重载后只读验证 API/Web 可达、四品种 Live 状态、安装根和计划任务保持空闲。不手工运行 `guiyi data after-market` 代替自然 17:00 证据。

开发态证据只属于当时的 `develop` 工作树。功能收口后重新创建绑定精确提交的独立 Runtime worktree，再采集最终自然时点证据。

## 5. 普通仓库删除与恢复

```text
确认目标仅为 repository-local tracked asset
-> 扫描 active references/callers/config
-> 在同一变更中更新调用方或引用
-> 删除目标
-> 运行受影响验证和引用扫描
-> 需要时从 Git 历史恢复
```

普通删除的协作边界与恢复方式见 `AGENTS.md` / `DECISIONS.md`：关闭 active references，仅用 Git
历史恢复。

恢复方式：

- 未提交：从 index 或 `HEAD` 恢复指定路径。
- 已提交未共享：由开发者选择普通 revert 或其他非破坏性 Git 恢复。
- 已推送：在 `develop` 创建普通 revert commit。
- 查阅旧内容：读取删除前提交；Git 历史是唯一仓库恢复来源。

若目标是生产 DB 行、正式数据、Runtime state、live config、remote ref、Git history 或仓库外资源，
立即改判为受控外部操作，不适用本节。

## 6. 受控外部操作的一次性意图

### 6.1 执行前必须明确的内容

用户的直接请求必须同时标识：

- 操作类别，例如 production data write/delete、release branch、push tag、force/history rewrite、
  Runtime switch、live enable、real notification 或 GitHub rule change；
- 可识别范围，例如环境、目标资源集合、remote + ref/tag、通知渠道与发送范围；
- 紧随请求后的一个执行尝试。

缺少类别、范围或直接执行请求时，在第一次外部 mutation 前停止。一次意图不能跨类别授权，例如
release/tag 请求不能授权 Runtime/live、通知、数据写入或 GitHub rules 修改。

### 6.2 一次消费且不持久化

意图只用于一个立即发生且范围匹配的尝试。以下情况必须重新获得明确请求：

- 首次尝试成功或失败后重试；
- target、environment、resource boundary 或 operation category 改变；
- 进入后续会话；
- 先前只请求或执行了 dry-run；
- 仅存在旧审批材料或过去执行结果（细则见 `AGENTS.md`「受控外部操作」）。

Dry-run 展示或验证计划，但 **绝不授权 mutation**。不得从 dry-run、先前会话或历史结果推断当前
权限。意图不落盘复用。

### 6.3 安全优先级与结果

```text
业务正确性与禁止事项
> 输入、认证、范围、质量和安全开关校验
> 当前一次性明确意图
> 实际执行
```

任何意图都不能绕过 failed quality、分区 coverage/可读性、未来函数保护、secret 保护、默认关闭状态、禁止订单
或超范围资源。执行后只报告非秘密的 attempted scope、success/failed/blocked 状态和有界错误。
失败不自动回滚、force、扩大范围或再次执行。

## 7. 保留的项目边界

- 数据：RQData -> staging -> validation -> Historical Canonical ->
  八表 Catalog/MainContractMap -> MarketDataService；正式请求使用明确 DatasetKey 和 kind，
  coverage/physical failure 不静默回退。
- 策略与回测：禁止未来数据泄漏，交易数值使用 `Decimal`，保留可复现 lineage；HTDY original 仅限
  deep canonical 定义的 observation-only 白名单。
- 信号与操作：保持 `Strategy -> SignalEvent -> Notification Gate -> Channel`；研究结果不是交易
  指令，`auto_order=false`，任何下单请求都拒绝。
- 默认状态：live、Runtime switching/promotion、真实通知和 autosend 都默认关闭；配置缺失、异常、
  过期或不一致时继续关闭；repair/replay/backfill/migration/EOD 不发送历史真实通知。
- 安全：凭据、token、webhook、password、cookie、license 和 private key 不进入源码、文档、测试、
  日志或输出；外部输入在命令、路径、网络、数据库或文件敏感操作前完成白名单校验。

## 8. 完成报告

任务完成时说明：变更文件、实际运行的命令与结果、未运行或不可用检查、剩余风险，以及是否发生
外部操作。完成报告不得把协作材料写成授权证据，也不得把一次受控操作结果扩写为交易、盈利、
long-running 或 production readiness（见 `AGENTS.md` / `DECISIONS.md`）。
