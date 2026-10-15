# 后续三个工程收敛批次设计与实施记录

基线：`986a62f22712425221b7aeb24d2761bf04f09020`。交办范围为前次列出的后端职责、Runtime工具、
策略公共计算及版本合同三个后续批次；交付至develop。

## 设计与不变量

继续采用模块化单体，以已有消费者为依据提取小型公共模块，不引入依赖或插件框架。

- Reference：事务内来源允许性及已消费恢复receipt校验下沉为公共guard/query，repository不再实例化调度器；
  checkpoint/watermark抽成纯工具，已有策略推进用明确adapter分派。锁、查询、原子提交与错误码保持。
- Newow组装：reader基础依赖与service装配统一；quality/context policy、时钟、缓存、reference来源显式传入。
  HTTP、快照搜索、readiness各自政策保留，用同配置结果与差异政策测试证明。
- Runtime身份：launchd只读查询、载入身份验证、文件快照及参数解析归公共底层模块；专项恢复仅组合政策。
  心跳身份与既有错误适配保留；公共模块纳入适用launcher/input指纹，旧计划不跨代码身份复用。
- 工具配置：安全私有配置读取及确有相同合同的文件写入离开专项脚本。旧恢复入口、错误类型、
  exact hash与attempt合同保留；消费者调用公共入口，不读取或显示真实凭据，不执行恢复。
- 新苏冰：显式公共计算版本封装相同Snapshot构建、divergence扫描和输入校验；V1/V2 Profile、
  setup解释、交易引擎、账户和结果独立。先冻结旧实现输出，再验证逐值、prefix及输入/执行哈希不变。
- 能力合同：冻结版本及精确顺序继续校验；当前active/candidate等后端仍支持的响应跨语言实测，
  历史rollback/preview profile保留，未知版本不回退。优先共享版本资料或生成消费者资料，避免双份手写。

## 实施计划

1. [x] Reference事务guard及checkpoint/策略推进解耦，定向测试并补必要隔离事务验证。
2. [x] Newow基础组装收敛，保留调用入口政策差异，定向API/snapshot/readiness回归。
3. [x] 公共Runtime身份与配置/文件工具抽取、消费者迁移、指纹依赖覆盖，安全边界与恢复回归。
4. [x] 新苏冰公共计算与输入校验提取，冻结基线对比、V1/V2与prefix/哈希回归。
5. [x] 前后端能力合同收敛，跨语言响应验证与历史profile回归、Web类型/build。
6. [ ] 独立高风险Review、整合验证、文档更新、commit/push与develop集成，清理本任务工作区。

## 验收重点

- repository校验仍在原事务、原锁与提交之前；不移动到提交后的“补验”。
- Runtime异常继续fail-closed；无旧错误码漂移、恢复身份放宽或未计入指纹的新依赖。
- 共享计算不得让一个策略版本默认参数或状态改变另一个版本；基线golden必须在修改前冻结。
- 相同依赖与政策下不同组装入口一致；不同政策不静默统一。
- 历史能力版本的scope/顺序/stage不可改写；实际后端响应须经真实前端validator接受。

## 实际验证与交付

实施中记录真实命令、结果及限制；本任务不执行发布、Runtime切换、数据维护、通知或策略晋升。


### 已完成的模块

- `reference_trading/transaction_guards.py`、`checkpoint.py`：消除 repository→scheduler 和 checkpoint 循环职责；事务锁、错误映射与恢复提交位置保留。
- `market_data/newow/composition.py`、`api/newow_presentation.py`：统一组装基础依赖，迁移18个无行为变化的展示函数；入口政策显式传入。
- `runtime_identity.py`、`private_settings.py`、`scripts/evidence_files.py`：公共身份、安全配置与原子写入；专项恢复保持错误、容量和attempt合同。新增依赖全部进入对应执行指纹。
- `guiyi_quant/new_subing_common.py`：共享 `new_subing_common_v1`，V1/V2参数、setup与账户分别维护。
- `capability_contracts.json`：32个历史版本的唯一版本资料；生成Web合同，build检查产物新鲜度；当前active/candidate入口及关闭范围保持。
- 修正两类旧测试夹具：导入时机污染、已退役remaining19范围及snapshot/resolver缺少关键字参数。均先在未改基线复现，没有放宽产品范围。

### 实际验证

以下从仓库根执行，Python使用已有 `services/quant-api/.venv/bin/python`，共同环境为
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core`。

- `pytest -q -p no:cacheprovider services/quant-api/tests/reference_trading services/quant-api/tests/test_runtime*.py services/quant-api/tests/test_captured_recovery*.py services/quant-api/tests/data_foundation/test_closeout_binding.py services/quant-api/tests/data_foundation/test_runtime_status_authority.py services/quant-api/tests/data_foundation/test_newow_readiness_cli.py services/quant-api/tests/newow/test_composition.py services/quant-api/tests/newow/test_product_service.py services/quant-api/tests/newow/test_market_newow_product_api.py tests/unit/new_subing tests/unit/new_subing_v2 tests/engineering/test_newow_capability_contract.py --tb=short`：1625 passed、78 skipped；跳过项不计为通过。
- 独立 PostgreSQL 16 容器 `guiyi-architecture-followups-pg`，loopback15483、无volume、测试库 `guiyi_architecture_isolated_test`；`test_repository_postgresql.py test_conflict_postgresql.py test_original_conflict_postgresql.py test_transaction_guards_postgresql.py`：24 passed。覆盖真实行锁等待、健康恢复与checkpoint/capture原子回滚；容器已停止并自动删除。
- `pytest services/quant-api/tests/test_runtime_shared_tools.py services/quant-api/tests/newow/test_weekly_recovery.py services/quant-api/tests/newow/test_weekly_source_verify.py services/quant-api/tests/newow/test_weekly_recovery_campaign.py services/quant-api/tests/scripts services/quant-api/tests/reference_trading/test_newow_bootstrap.py -q -p no:cacheprovider`：368 passed、2 skipped。
- `pytest tests/engineering/test_canonical_consistency.py tests/engineering/test_repository_hygiene.py tests/engineering/test_secret_scan.py -q -p no:cacheprovider`：34 passed。
- `node --test apps/quant-web/tests/*.test.ts`：1129 passed、3 skipped；`pnpm -C apps/quant-web build`：类型、生成产物校验、Vite和bundle topology通过。
- 所有改动Python文件Ruff通过；能力资料两个模块按仓库MYPYPATH与explicit-package-bases检查通过。首次缺少MYPYPATH的检查因导入配置失败，不计为通过。
- 独立Review从 `git archive 986a62f22` 重新计算V1/V2 golden：各112快照、22类输入校验、9种研究组合与prepared hash一致；真实旧/新TS validator对32版本及1509变异响应零接受差异。18个展示函数、事务查询/锁位置与Runtime身份函数通过AST核对；最终6项依赖哈希回归独立复核24 passed。无Confirmed Issue，允许集成develop。

完整Newow目录的探索性测试在720通过后因无关CupHandle Fraction计算耗时中断，不报告全目录通过。
本批不更新视觉快照，不发布、不切换Runtime，不读取生产凭据、不执行真实恢复或数据写入。


### 并行 develop 变更整合

实现提交 `0132419fa` 合入当时最新 `origin/develop` 的闭市provider修复 `58e6aaeb1`，merge为 `45ebdd13e`。
`live_market.py`/`market_feed.py` 自动合并后独立逐字核对：闭市缓冲/退役逻辑完整保留，只迁移身份函数import；
`composition.py` 与并行修复父提交完全一致。
`pytest services/quant-api/tests/data_foundation/test_closed_cleanup_provider.py services/quant-api/tests/data_foundation/test_composition.py services/quant-api/tests/data_foundation/test_live_market.py services/quant-api/tests/test_runtime*.py -q -p no:cacheprovider`：441 passed、1 skipped。
此前命令误写不存在的 `test_market_feed.py` 未收集到测试，已修正路径后运行上述真实测试，不计首次命令为通过。
全仓secret scan及 `git diff --check` 通过。以上测试不授权或证明生产Runtime已使用新代码。
