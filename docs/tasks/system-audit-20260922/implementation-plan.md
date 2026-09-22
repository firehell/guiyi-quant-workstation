# 全系统审计：Sol 实施任务包
日期：2026-09-22。配套：[主报告](decision.md)。

**本文件是待批准的实施设计，不是实施或生产操作授权。** 本轮只写两份规划文件，未改业务、未提交。
审计基线为 develop@5b46cf0d6972478f0a06e9d70b56b3870c44dd1f。
完整路径相对仓库根；最小读集中的 `app/` 简写指 `services/quant-api/app/`，
相邻未带前缀的文件沿用上一模块目录，源码 `src/` 指 `apps/quant-web/src/`。独立会话先读取实际 AGENTS 和授权，再使用任务 prompt。
不要依赖聊天记忆、/tmp 审计脚本或另一个会话的隐含设计。

## 1. 证据、命令与安全验证入口

### 1.1 本轮实际执行记录

固定源码 archive：/tmp/guiyi-system-audit-5b46cf0d6，解释器借用
/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python。
所有测试先检查 fixture，使用纯对象、内存 SQLite、临时真实 Parquet、fake Redis/provider/transport。
未运行隔离 PostgreSQL、生产 Redis、真实 provider 或通知。以下记录不能当成修复后通过。

| 执行集合 | 实际结果 |
|---|---|
| 数据完整性/身份/metadata 8个node id（含参数化） | 9 passed |
| Live provenance/派生/恢复 6个node id（含参数化） | 8 passed |
| Runtime 6文件：Live、after-market、weekly、Alert、health、entry | 268 passed |
| reference纯核/checkpoint + Newow因果研究 9文件 | 133 passed |
| repository + adapters/projector + SuBing 10文件 | 226 passed |
| Web health types/presentation + Range golden + indicators | 29 passed |
| engineering：文档卫生、权限模式、版本一致性 | 2 failed / 1 passed；F-06中的既有失败 |
| 主代理独立复现 | 稀疏Calendar/错误Session来源被接受；UNKNOWN假正常；长事务；诊断类别丢失；ORPHAN_MARK原子回滚；无evidence CLEAR；legacy同身份异内容被忽略 |

实际命令记录（工作目录为 archive；不是要求未来复制临时目录）：

```sh
# 数据域；wrapper 禁 socket.connect，pytest 参数如下。
env -i PATH=/usr/bin:/bin DATABASE_URL=sqlite+pysqlite:///:memory: \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/guiyi-system-audit-5b46cf0d6/services/quant-api:/tmp/guiyi-system-audit-5b46cf0d6/packages/quant-core \
  '/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python' \
  /tmp/guiyi-audit-data-pytest.py -q -p no:cacheprovider \
  --basetemp=/private/tmp/guiyi-audit-data-tests \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py::test_actual_dominant_rejects_missing_intraday_endpoints_in_query_and_page \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_minute_response_rejects_wrong_contract_or_duplicate_endpoint \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_exchange_daily_rejects_response_for_another_contract \
  services/quant-api/tests/data_foundation/test_infrastructure.py::test_current_day_metadata_snapshot_fetches_iso_week_period_evidence \
  services/quant-api/tests/data_foundation/test_metadata.py::test_current_day_sync_uses_later_iso_week_session_evidence_without_writing_those_sessions \
  services/quant-api/tests/data_foundation/test_metadata.py::test_current_day_sync_replaces_next_trading_day_sessions_only \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py::test_manager_rejects_duplicate_provider_bar_before_publish \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py::test_manager_rejects_batch_bound_to_another_contract
# 第二组使用相同前缀，basetemp=/private/tmp/guiyi-audit-data-live-tests：
# test_live_market.py 中以下六个node id：
# test_provenance_read_rejects_legacy_invalid_or_mismatched_rows
# test_due_bar_retains_ingested_contract_if_mapping_changes_before_flush
# test_live_derived_buckets_match_shared_historical_aggregation_exactly
# test_live_derived_bucket_rejects_legacy_source_without_provenance
# test_live_coverage_after_restart_uses_full_authoritative_day
# test_live_coverage_lost_snapshot_during_trading_is_unverified

env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 DATABASE_URL=sqlite:// \
  REDIS_URL=redis://127.0.0.1:1/0 \
  PYTHONPATH=/tmp/guiyi-system-audit-5b46cf0d6/services/quant-api:/tmp/guiyi-system-audit-5b46cf0d6/packages/quant-core \
  '/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python' \
  /tmp/guiyi-runtime-audit-pytest.py
# wrapper 有 __main__ 保护、禁socket connect/connect_ex；
# 调pytest -q -p no:cacheprovider，精确文件：
# services/quant-api/tests/data_foundation/test_live_market.py
# services/quant-api/tests/data_foundation/test_after_market.py
# services/quant-api/tests/data_foundation/test_weekly_audit.py
# services/quant-api/tests/test_alert_runtime.py
# services/quant-api/tests/test_runtime_health.py
# services/quant-api/tests/test_runtime_entry.py

env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=/tmp/guiyi-system-audit-5b46cf0d6/packages/quant-core:/tmp/guiyi-system-audit-5b46cf0d6/services/quant-api:/tmp/guiyi-system-audit-5b46cf0d6/services/quant-api/tests \
  '/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python' -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/reference_trading/test_contracts.py \
  services/quant-api/tests/reference_trading/test_reducer.py \
  services/quant-api/tests/reference_trading/test_checkpoint_parity.py \
  services/quant-api/tests/reference_trading/test_adapter_input_order.py \
  services/quant-api/tests/reference_trading/test_strategy_checkpoint.py \
  services/quant-api/tests/newow/test_research_backtest.py \
  services/quant-api/tests/newow/test_research_walk_forward.py \
  services/quant-api/tests/newow/test_research_evidence.py \
  services/quant-api/tests/newow/test_engine_causality.py
# 133 passed；第二组用同一env/pytest前缀，精确文件：
# reference_trading/test_repository.py test_repository_seed.py
# test_repository_snapshots.py test_repository_contracts.py
# newow/test_product_adapters.py test_reference_trades.py
# test_reference_interruptions.py test_reference_statistics.py
# services/quant-api/tests/test_subing_reference_projection.py
# services/quant-api/tests/test_subing_ths_kernel.py
# 226 passed

# archive/apps/quant-web 下：
node --test tests/runtimeStatus.test.ts tests/runtimeHealthTypes.test.ts \
  tests/rangeDetectorGolden.test.ts tests/indicators.test.ts
```

工程测试在 archive 上指定 GIT_DIR 为原仓库 .git、GIT_WORK_TREE 为 archive（只读 Git），
逐项执行 `tests/engineering/test_repository_hygiene.py::test_noncanonical_superpowers_documents_are_not_tracked`、
`test_canonical_consistency.py::test_project_codex_permission_mode_is_preserved`、
`test_canonical_consistency.py::test_release_versions_are_consistent`。
分别失败、通过、失败；测试环境指定内存SQLite和无效Redis端口。没有把该三项说成全工程套件通过。

现场只读证据时间：2026-09-22 21:15:49–21:16:20 CST；六launchd服务root/commit、3个HTTP GET、
当次after-market status和有限日志字段。health JSON SHA256
`7f835f5fa6a37a983c253f9091731ae24172d67da8dbf273e938ee6edec36b11`；
after-market status SHA256
`b810c75ede127cc001819fb55cfeb65ada2e16f78c8fb0face4df58f9634ea10`。
临时原始公开JSON在本机/tmp，不是长期保留承诺；以后验收须重新绑定当时身份，不能要求它证明新版本。

### 1.2 未来任务通用安全启动

每个会话先检查 branch/HEAD/dirty/worktree、当前develop和main差异，逐项核对本任务依赖是否仍适用。
原工作区dirty和P4并行状态见主报告2.2；不能覆盖它们。固定审计行号仅用于定位，实施以新基线符号为准。
有实施授权后，按冲突选择隔离worktree；不机械复制生产.env或Runtime state。
先检查所选测试fixture：仅隔离资源才能执行。不要直接从生产环境继承DATABASE_URL运行pytest。

以下 `check_py` 是任务会话临时的离线测试助手，**不加入产品代码、不用于真正基础设施测试**。
它在当前解释器禁止socket连接，并用继承环境开关关闭项目.env自动读取；不能用于验证env加载本身的测试。
socket monkeypatch不跨subprocess exec，子进程仍须逐项检查其行为与替身；当前dotenv已核验支持PYTHON_DOTENV_DISABLED。

```sh
AUDIT_ROOT="$(git rev-parse --show-toplevel)"
AUDIT_PY='/Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python'
AUDIT_TMP_DIR="$(mktemp -d /tmp/guiyi-offline-pytest.XXXXXX)" || exit 1
AUDIT_RUNNER="$AUDIT_TMP_DIR/runner.py"
cat > "$AUDIT_RUNNER" <<'PY'
import socket
import sys
def reject_network(*args, **kwargs):
    raise RuntimeError("OFFLINE_TEST_NETWORK_FORBIDDEN")
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network
from app.core import env
env.load_project_env = lambda: None
if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]]))
PY
check_py() {
  /usr/bin/env -i PATH=/opt/homebrew/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHON_DOTENV_DISABLED=1 \
    DATABASE_URL=sqlite+pysqlite:///:memory: REDIS_URL=redis://127.0.0.1:1/0 \
    PYTHONPATH="$AUDIT_ROOT/services/quant-api:$AUDIT_ROOT/packages/quant-core:$AUDIT_ROOT/services/quant-api/tests" \
    "$AUDIT_PY" "$AUDIT_RUNNER" "$@"
}
```

执行前确认AUDIT_ROOT为本任务工作树、AUDIT_PY存在；PATH按本机可用工具调整，不安装或升级全局配置。
每个任务下面的 `check_py` 命令从仓库根执行。工程Git测试不从临时archive读取未提交任务文件。
新回归加到列出的文件，避免只运行旧绿测；报告pass/fail/skip及具体环境。
本轮已实际运行本节最终助手：test_runtime_logging.py + test_runtime_entry.py，12 passed；
隔离PG/Redis测试另按当前TESTING和机器guard准备，**不可删除socket限制后直接跑生产连接**；
缺环境就保留相应TEST/INTEGRATION_GATE_PENDING，不把skip算通过。
普通修复通过后可按届时明确授权完成develop交付；本审计本身没有commit/push授权。

## 2. 跨任务冻结的设计合同

以下作为批准后共同设计；修改这些合同须回主设计者，不能由各Sol独立扩展公共状态。

| 接缝 | 输入/输出与错误合同 | 单一修改负责人 |
|---|---|---|
| Historical facts | 现有MDS query/page/lifecycle接口不变；调用方指定有界请求窗口，先证明完整Calendar、rqdata来源、exact active Session、lifecycle/rank1身份，再展开expected。失败沿用已有typed MarketDataError/InfrastructureError到公开码映射；不静默裁窗，不新增provider或缺口authority | SA-03；catalog/session_clock/coverage_source独占 |
| Live当前健康 | 沿用TRADING/BREAK/CLOSED/UNKNOWN、available、coverage state、health status。UNKNOWN或phase计数不闭合不能以旧ok证明当前健康；对应当前coverage=unverified，Live子项degraded，既有错误分类复用。available是MDS/Home也使用的全局门，不能把任一UNKNOWN直接变成全局false；保留其连接/采集可用语义，全UNKNOWN可false，混合时正常品种仍可读，未知品种由当前phase/coverage拒绝。保留last_bar，合法全CLOSED例外保持 | SA-02；Live与health同owner |
| Alert当前覆盖 | 依有权威当前Session的Live事实判断当前due/已处理水位；UNKNOWN不得用旧session回绿。已有失败诊断不得因缺事实被覆盖为成功；不改Event幂等、first_seen/exact、发送一次合同 | SA-02；health聚合，不改evaluator策略 |
| health聚合 | market runtime v2总体仍为DB/Redis/Live/after-market；Alert、weekly独立。Web映射服务端typed字段，不自行查交易时钟。不新增第二份业务可用性计算 | SA-02 |
| 盘后诊断 | 固定字段stage、detail_code、attempt、exception_type；exception_type仅既有允许类名InfrastructureError/RuntimeError/ValueError/TypeError/OSError/StorageError，其余REDACTED。领域公开码沿用allowlist；不输出str(exc)、SQL、URI、stack或任意class名。固定callsite传结构化字段，不解析模板自由文案 | SA-01 |
| 盘后生命周期 | guard → durable current_run → lazy provider readiness → 原有update/cleanup/checks → terminal。初始status写失败时provider调用0；init异常进入既有失败终态。notification runtime至多一次、manual默认0；仅原批准的下一交易日未就绪可+1h一次 | SA-01；不改provider事实适配算法 |
| Live DB生命周期 | 每poll的短只读session/UoW结束后无悬空事务；provider、Redis、guard和recovery worker仍属长期service。值对象可以离开session，ORM对象/session不能跨线程；本轮相同身份不能重复用不同authority结果 | SA-04 |
| reference仓储 | mark证明sealed bar当时有效OPEN，不要求该trade在整个batch最后仍OPEN；保持每批每trade一个最终结构版本，依已存entry/exit Action、effective_bar_end、mark和observed_at恢复cutoff前OPEN；不在同一valid_from_seq插多个版本，不改schema。原子提交所有action/trade/mark/checkpoint。batch分割不改变业务结果；CAS/no-op/冲突语义保持 | SA-06 原P4 owner |
| reference reducer | active公共入口统一typed CompletedReferenceBar；任何保留legacy兼容必须先规范化并参与相同hash，或者确认无真实消费者后删除。same identity different content必须冲突；Decimal、physical owner、segment、entry_action_id不可弱化 | SA-06 |
| Newow Action资格 | D2未决，SA-05不能实施语义选择；adapter/projector和checkpoint使用同一明确身份。Action-only不创建ReferenceTrade/收益，历史不等于forward观察；只在owner选定后更新对应canonical | SA-05，codec交接SA-06 |
| 工程和根文档 | SA-00负责release修正回流清单；SA-07负责稳定验证文档/规则；SA-08负责最终集成事实。其他任务提交必要文档建议给owner，禁止并行改STATUS/DECISIONS/TESTING造成真假状态混杂 | 00→07→08顺序交接 |

所有任务不变量：RQData唯一外源、Historical/Live分离、completed-only、strict-before、
自然日/交易日/Session(start,end]、rank1/physical owner、同合约warm-up、prefix/batch/restart parity、
Event先commit/one-shot、无自动promotion、auto_order=false。
不修改Scope、开放产品/周期、公式/收益/账户口径，不引入通用任务/重试/消息框架。
已有真实锁、事务、幂等和安全Gate不能为简化删除。

**并行所有权**：SA-01改after_market/runtime_logging；SA-02改live_market/runtime_health；
SA-03改catalog/session_clock/coverage_source及MDS；composition.py仅由SA-03完成普通读接入后交SA-04。
SA-01若需要composition改动，先交SA-03单点落补丁，不并改。
SA-05独占Newow adapter/projector，完成后SA-06处理公共codec/P4；SA-06其他仓储部分可先做。
SA-07不重做01–06测试，不移动它们的模块。worktree不是接口冲突解决办法。

## 3. 任务定义与启动 prompt

### SA-00 / develop与发布修正回流 / P1

- **问题与结果**：F-06；消除“develop遗漏已发布行为修正”，建立所有后续任务共同可核验基线，不整树搬main。
- **证据/设计**：主报告2.1、F-06、D3；5/22是提交图，16文件才是当前tree差异。先区分等价提交、真实修正、版本、STATUS及发布专用记录。
- **前置**：owner授权此工程实施；最新refs/dirty核验。不能因老main授权推导新main merge。
- **最小读集**：AGENTS、STATUS头部、docs/DEVELOPMENT、主报告2/4/7；
  main-only `6c4590a29`、`f197846dd`、`4802c0dfd` 与 develop↔main diff；
  `apps/quant-web/src/api/newowProduct.ts`、`src/components/market/detail/newow/NewowDetailDialog.vue`及相应能力/路由测试。
- **修改范围**：只回流证明属于稳定行为的Web API envelope、路由、fixture及对应测试；版本四处仅统一到经当前发布流程确认的开发值，不发版。不覆盖develop STATUS或现有dirty chart/e2e；工程规则交SA-07。
- **接口/不变量**：capability必须精确集合与policy/profile版本匹配，不能把数量相等当集合相等；D1/W1开关范围不变；60m/explanation关闭。已有正确产品API行为保留。
- **步骤**：重算差异→逐项写简短处理表（可直接在PR/任务回复）→在隔离工作树复用最小修正→消费者负例→与P4核对依赖→交付新develop SHA。不能执行merge main到当前dirty工作区来代替核对。
- **验证**：能力同数量错品种、wrong policy、缺section/cursor、D1/W1路由；保留现有chart用户修改。命令：
  `node --test apps/quant-web/tests/newowCapabilities.test.ts apps/quant-web/tests/newowApi.test.ts apps/quant-web/tests/newowProductRoutes.test.ts`；
  `pnpm -C apps/quant-web build`；`git diff --check`。缺依赖先使用既有runtime，不联网隐式升级。
- **现场/授权**：只需隔离fixture/browser预览；新Release/Runtime回读留SA-08后独立Gate。无生产操作。
- **迁移/回滚**：每项回流可单独revert；不引入永久main/dev两套API。等价提交只记录，不重复cherry-pick。
- **并行/Review**：相关基线先核对，完整回流可与01/02并行；原dirty文件不抢占，先与owner交接。普通回流自审，涉及capability身份独立review；出现版本/产品策略歧义回Astra，不由Sol猜。
- **模型**：Sol medium。

启动 prompt：

> 在 firehell/guiyi-quant-workstation 执行 SA-00，前提是本消息明确授权工程实施。读取 AGENTS、docs/tasks/system-audit-20260922/decision.md 和同目录 implementation-plan.md 的 SA-00/第2节。审计基线 develop@5b46cf0d6972478f0a06e9d70b56b3870c44dd1f，先核对最新refs、HEAD、dirty与P4工作；保留其他修改。逐项核对main发布修正与develop，回流确有缺失的capability/路由/fixture行为，不能整树覆盖、自动选发布版本或改产品开关。按SA-00负例和Web build验证，交付差异处理表、新开发基线及剩余项。工程规则留SA-07；禁止真实数据/通知/服务操作、main/tag/Release/Runtime切换。目标与合同不变时连续完成实现、验证及授权内develop交付，重大歧义回主设计者。

### SA-01 / 盘后根因鉴别与诊断生命周期 / P1

- **问题与结果**：F-03/R-01/F-07。当前事故先有明确鉴别结果；以后初始化和update失败可从同一运行身份追踪，保持脱敏。
- **证据/设计**：主报告现场21:16及固定develop formatter复现；第2节诊断字段/lazy生命周期。**事故根因未知，调查结论不能预先指定metadata或v1.10.19。**
- **前置**：只读事故调查可立即开始；代码实施等owner授权及相关文件基线核对，完整SA-00回流可并行。调查和已证实诊断修正互不阻塞。
- **最小读集**：docs/DATA_CENTER盘后/metadata、deploy/README运行身份；`app/runtime_entry.py`、
  `app/runtime_logging.py`、`app/market_data/after_market.py`、`rqdata_adapter.py` current-day/client、
  `metadata.py` current-day事务、`market_phase.py`；test_after_market/test_runtime_logging/test_runtime_entry。
- **调查边界/出口**：以精确Runtime root/commit、2026-09-22失败run及9/22–27 Calendar、9/22–23逐品种Session/rank1现存只读事实对齐。只读事务、固定查询、只打印计数/日期/provider/身份和有限错误码，不读取凭据正文、不打印SQL/连接串。不可调用可能下载的manager/provider构造；不得重跑盘后。给出已证明分支或UNKNOWN+最小缺证；如果已过事故窗口或资料不在，明确不可还原。
- **修改范围**：after_market.py/runtime_logging.py及相关测试；若lazy seam需改rqdata_adapter，只允许client生命周期接口，数据适配算法不动；runtime_entry只必要装配。不新增诊断库、自动恢复CLI或生产state写入。
- **接口/不变量**：第2节四字段；run identity复用trading_day+started_at+attempt。公开terminal error_code不改；结构化logger可直接表达exception_type。状态写成功在provider第一次使用前；unknown commit停批；manual通知0/runtime≤1，重试次数不变。
- **步骤**：复现formatter类别丢失与factory提前init→只读调查输出→结构化字段贯通formatter→lazy client由run readiness阶段使用→故障路径回归→独立审查。若发现新数据根因，仅提出有界后续修复，不塞入本任务。
- **新增/保留验证**：RuntimeError/OSError可区分；敏感诱饵全部不出现；未知类名REDACTED；起始state写失败client0次；init失败一个terminal；guard释放、readonly consumer/projection失败不改主结果；one-shot、commit unknown保留。
- **命令**：`check_py services/quant-api/tests/data_foundation/test_after_market.py services/quant-api/tests/test_runtime_logging.py services/quant-api/tests/test_runtime_entry.py`；
  调整adapter seam再加`check_py services/quant-api/tests/data_foundation/test_infrastructure.py`。
- **现场/授权**：代码离线验证可完成；实际provider/download/数据修复/通知/retry/Runtime均不在范围。新版本自然18:05终态另验收，无自然机会则待验。
- **迁移/回滚**：旧terminal/health schema继续读；不强制status文件迁移；回退仅代码commit，无生产state复制/清空。删掉被替代regex解析，不能保留两套字段抽取。
- **并行/Review**：可与02/03并行；同一owner完成诊断和lazy生命周期；数据owner审查adapter与错误分类，Runtime reviewer审查通知/锁。需要新诊断schema或新retry规则则回Astra。
- **模型**：Sol medium完成已定接口；事故跨域结论或未知副作用回Astra。

启动 prompt：

> 在目标仓库执行 SA-01。先读 AGENTS、两份2026-09-22-system-audit文档中 SA-01 和共享合同。调查阶段仅只读：核对实际Runtime、9/22盘后run以及现存Calendar/Session/rank1，区分已证实与UNKNOWN，不得为取证触发provider、盘后重跑、通知或生产写入。已有独立证据是formatter丢失异常类别、provider在current_run前初始化；若本消息授权工程实施，按冻结字段和lazy生命周期修复这两项，保持状态、锁、仅既有+1h retry及one-shot政策。最小范围为after_market/runtime_logging及必要装配/测试，不猜测修复事故数据。运行SA-01离线故障矩阵并独立Review，报告代码证据与自然运行待验分别成立；没有明确实施授权时停在调查结果和可审阅diff建议。

### SA-02 / UNKNOWN与当前覆盖健康一致 / P1

- **问题与结果**：F-01；全/局部UNKNOWN不会展示当前正常，页面与Alert覆盖不再借旧session回绿；已知正常休市不误报。
- **证据/设计**：主报告F-01；现场Live ok/UNKNOWN60/0订阅；第2节状态合同已限定不新增公共enum。
- **前置**：相关文件基线核对、owner工程授权；main差异无Live/health，完整SA-00可并行，不依赖metadata修复或SA-03。
- **最小读集**：docs/DATA_CENTER Live/health、subing-ths-alert spec输入/health；
  `app/market_data/live_market.py` poll/_write_heartbeat/coverage；
  `app/services/runtime_health.py` live/alert聚合；
  `apps/quant-web/src/utils/runtimePresentation.ts`、runtimeHealth类型和对应测试。
- **修改范围**：live_market、runtime_health及现有DTO必要一致性映射、Web presentation/fixture；必要的MarketReadService/Home逐品种资格接入由同owner负责；不改market_phase时间算法、provider订阅政策、正式Rule或evaluator公式。
- **接口/状态**：UNKNOWN对应产品当前coverage=unverified，总Live非ok；available不能因单品种UNKNOWN一律false，避免全局读取门停掉正常品种。phase数量不闭合按现有invalid/unavailable路径降级。历史last_bar与已知gap保留；Alert当前覆盖无法证明则unverified，已有failed优先不抹掉。
- **不变量/不做**：DB/Redis/Live/EOD总体v2不变；CLOSED例外、BREAK和末尾grace保留；未知品种不拖停已知品种。不能把“无新Event”当业务正常，不能补发、replay或清diagnostics。
- **步骤**：固定现场结构的脱敏fixture→全UNKNOWN旧ok回归红测→按phase identity阻断旧coverage复用→health独立拒绝旧/不闭合heartbeat→Alert同当前session资格→Web只映射→恢复回绿测试。
- **验证**：全UNKNOWN、混合UNKNOWN/TRADING、CLOSED清理、BREAK、夜盘归属、周末/假日、计数不闭合、重启旧heartbeat、phase恢复、当日已lagging保留；增加真实MarketReadService和MarketHomeLive混合品种接入，已证明品种仍可读、未知品种拒绝。各例零新Event/通知/provider调用。
- **命令**：`check_py services/quant-api/tests/data_foundation/test_live_market.py services/quant-api/tests/test_runtime_health.py services/quant-api/tests/test_alert_runtime.py services/quant-api/tests/data_foundation/test_market_read.py services/quant-api/tests/data_foundation/test_market_home_live.py`；
  `node --test apps/quant-web/tests/runtimeStatus.test.ts apps/quant-web/tests/runtimeHealthTypes.test.ts`；
  改DTO/UI后`pnpm -C apps/quant-web build`。
- **现场/授权**：新Runtime自然重新开盘/夜盘与实际订阅回读是独立待验；不能用重启制造成功。无需现有生产数据修改。
- **迁移/回滚**：兼容旧heartbeat解析，旧记录缺当前证明须保守降级；不迁移Redis、不加旧ok fallback。代码回退会恢复已知误报，回滚说明必须披露。
- **并行/Review**：同owner独占live_market/runtime_health；SA-04等此任务结束。独立Runtime+data review，尤其局部降级和CLOSED边界；改变overall或未知时停全部订阅需回Astra。
- **模型**：Sol medium，跨域review；不默认Ultra。

启动 prompt：

> 执行 SA-02（需本消息授权工程实施）：读取 AGENTS、docs/tasks/system-audit-20260922/decision.md 的F-01及配套任务包第2节/SA-02。先核对最新develop和并发dirty。修复UNKNOWN阶段利用旧Session coverage导致Live正常、Alert旧覆盖回绿的问题；使用现有phase/coverage/status，不新增一套时间resolver，保持合法CLOSED/BREAK、末尾grace、局部品种继续和overall market-v2组成。范围仅Live heartbeat、health及薄Web映射/测试；不改策略、Scope或发送规则，不清生产状态、不重启或触发provider。新增全未知/混合/旧心跳/跨夜恢复等故障行为测试，运行指定Python/Web/build并独立Review。代码通过与自然夜盘验收分别报告，生产发布和Runtime另行授权。

### SA-03 / Historical Calendar与Session权威证明收口 / P1

- **问题与结果**：F-02；普通contract/actual_dominant/query/page与严格lifecycle读取，在同一有界窗口采用一致可信事实。
- **证据/设计**：主报告F-02的两例真实SQLite+Parquet复现；共享合同仅统一“证明”，不统一所有查询请求语义。
- **前置**：工程授权及SA-00相关文件基线核对（完整回流可并行）；MDS入口当前依赖已核验；数据/Runtime接口如有漂移先协商。
- **最小读集**：market-series-query、data-foundation-metadata、canonical-market-storage、historical-data-maintenance specs；
  `app/market_data/catalog.py`、`session_clock.py`、`coverage_source.py`、`market_data_service.py`、
  `composition.py`；`market_phase.py`只作消费者审查；
  test_catalog_and_service/test_market_pagination/test_infrastructure/test_historical_session_window。
- **修改范围**：上述Catalog/Session/coverage事实证明及MDS接入；同文件内私有纯函数/小值对象即可。
  不新建data服务层、事实表、额外manifest，provider/storage写链和策略不动。
- **公共接口/错误**：MDS公开request/response/page cursor保持；query依据原始有界自然日集合证明Calendar完整，不能先删缺行再求expected；Session要求rqdata/exact active、合法窗口与夜盘anchor。Calendar/Session缺证、冲突沿用对应已有typed错误映射，不能抛裸SQL/栈。rank1/lifecycle边界按查询模式保留。
- **不变量/兼容**：显露缺口是正确拒绝；不自动下载/换频/缩窗。contract listing前窗口按已接受lifecycle合同处理，不强索上市前无意义Session；非交易日Calendar仍须完整；W1只在其已完成周窗口证明，不借以后周补齐。
- **步骤**：两反例→定位既有严格validator并最小抽取→普通contract interval代表链→actual_dominant+page→lifecycle/maintenance接入一致性→删重复弱检查分支；MarketPhase只复用适用事实规则，业务phase政策不强并。
- **验证**：缺中间交易日及非交易日Calendar、Calendar/Session错来源、range/open-ended/overlap、夜盘跨日与周五→下一交易日、假日无夜盘、listing/delisting、rank1切换、短owner、跨月/ISO周、1m缺端点、D1/W1、page seam。
- **命令**：`check_py services/quant-api/tests/data_foundation/test_catalog_and_service.py services/quant-api/tests/data_foundation/test_market_pagination.py services/quant-api/tests/data_foundation/test_historical_session_window.py services/quant-api/tests/data_foundation/test_calendar_authority.py services/quant-api/tests/data_foundation/test_market_phase.py`；
  再跑`check_py services/quant-api/tests/data_foundation/test_actual_dominant_research.py services/quant-api/tests/newow/test_product_reader.py services/quant-api/tests/test_subing_reference_projection.py`。
  维护消费者补充命令：
  `check_py services/quant-api/tests/data_foundation/test_infrastructure.py::test_database_coverage_uses_actual_exchange_sessions_and_complete_iso_week services/quant-api/tests/data_foundation/test_infrastructure.py::test_contract_coverage_requires_complete_historical_facts services/quant-api/tests/data_foundation/test_infrastructure.py::test_contract_valid_boundaries_requires_exact_identity_lifecycle_and_session services/quant-api/tests/data_foundation/test_infrastructure.py::test_coverage_resolves_friday_night_endpoint_to_monday_trading_day services/quant-api/tests/data_foundation/test_historical_data_manager.py::test_contract_warmup_dry_run_has_exact_month_targets_stable_hash_and_no_writes services/quant-api/tests/data_foundation/test_historical_data_manager.py::test_contract_refresh_preserves_but_does_not_refetch_after_through_bar`。
  这些是共享事实验证的writer接入回归；只用既有隔离fixture，不运行真实维护。
- **现场/授权**：只读Catalog/Canonical样本可核验影响，报告显露哪些缺证；任何修数据、provider下载另批。高风险数据边界需独立Review，不以生产全资产扫描作为代码修正前提。
- **迁移/回滚**：无schema/data迁移；逐consumer替换后删除同义validator，维护冻结expected不同合同保留。回退单commit可行，但不得通过降级版本掩盖已经识别的数据不足。
- **并行/Review**：独占catalog/session_clock/coverage_source/MDS；composition由本owner接入完交04。02不改这些文件。数据review必须检查真实Parquet+DB而非纯mock；遇到新业务窗口定义、来源替代、需要外部事实回Astra。
- **模型**：Sol medium实现已定合同；重要数据语义歧义回Astra。

启动 prompt：

> 执行 SA-03，前提是工程授权明确。读取 AGENTS、四个数据spec及2026-09-22-system-audit两份文档的F-02/第2节/SA-03。固定审计反例为：1/6–1/8缺1/7 Calendar和Bar仍被普通MDS接受；Session provider=other仍接受，同库严格contract facts拒绝。先重现再在现有catalog/session_clock/coverage_source收口只读事实证明，保持公开query/page和各自窗口语义；迁移代表链及消费者后删弱重复分支。覆盖夜盘/周末/休市日/listing/owner/1m/D1/W1分页，保留真实SQLite+Parquet接入验证和独立数据Review。不得造数、缩窗、换频、下载、写Canonical/生产DB或改策略。发现当前资产不足只报告；新语义回主设计者。与SA-02避开共享文件，composition结束后交SA-04。

### SA-04 / Live有界数据库读取与退出释放 / P2

- **问题与结果**：R-02；常驻进程不把一次DB事务持有到下一poll/休市；异常释放、退出资源归属明确。
- **证据/设计**：两轮SQLite begin=1/rollback=0/in_transaction=true；未证明事故根因或OOM。第2节短UoW已定，缓存/队列扩展必须先测。
- **前置**：02/03完成公共phase/facts接口；工程授权；重读composition/Live以新HEAD为准。
- **最小读集**：Live/recovery DATA_CENTER合同；`app/runtime_entry.py`、`market_data/composition.py`、
  `live_market.py`、`market_phase.py`、`live_recovery.py`、`live_recovery_guard.py`；
  test_runtime_entry/live_market/live_recovery_queue/live_recovery_concurrency。
- **修改范围**：Live reader装配与每poll DB生命周期、service finally清理；不动SA-03事实算法、provider协议、派生算法及锁语义。
- **接口/状态**：一个poll使用本轮确定的phase/owner/session值；Session仅在本轮受控读取中存在，结束commit/rollback/close明确；不把ORM对象或Session交worker。连接异常走现有降级/进程退出恢复政策，不新增无限retry。
- **不变量/不做**：不能把provider/Redis每秒重建；数据锁覆盖正常flush与recovery；completed与grace不变。缓存淘汰若尚无保留合同只调查，不猜“保留N天”；禁止生产断网压测或引入资源管理框架。
- **步骤**：测试记录每轮begin/end/查询次数→单poll短Session装配→值离开Session→异常路径释放→service退出closeprovider/worker/Redis→模拟多日观察容器增长。缓存清理只有能证明不丢grace/幂等/恢复证据时纳入，否则给有界后续建议。
- **验证**：连续poll间in_transaction=false、连接归还；DB故障后无复用坏Session；provider断连不改变lock；worker不触DB；停止不丢已提交事实；跨日/跨合约和尾盘grace回归；隔离PG验证实际事务归还，非SQLite替代。
- **命令**：`check_py services/quant-api/tests/test_runtime_entry.py services/quant-api/tests/data_foundation/test_composition.py services/quant-api/tests/data_foundation/test_live_market.py services/quant-api/tests/data_foundation/test_live_recovery_queue.py services/quant-api/tests/data_foundation/test_live_recovery_concurrency.py`。
  PostgreSQL补测放既有隔离fixture下，先通过数据库identity guard；命令按新增测试文件在PR列明，缺该证据保留待验，不能伪造现成PG测试。
- **现场/授权**：只读pg_stat_activity取证需配置允许且脱敏；实际新Runtime连续运行/自然重连另验收，不操作生产故障。
- **迁移/回滚**：无持久schema；旧长Session路径在所有Live装配迁移后删除；同一进程不保留两套开关模式。回滚代码，不能复制旧Redis或status。
- **并行/Review**：02/03之后同Live owner独占composition/live/entry；与01协调entry。独立资源/并发review；改变线程、连接所有权或恢复预算超出已定边界回Astra。
- **模型**：Sol medium，资源风险由测试和独立Review保证。

启动 prompt：

> 实施已批准的 SA-04。读AGENTS、两份system-audit文档及已合入SA-02/03；先证明最新Live装配仍存在跨poll长Session。按任务第2节让DB读取每轮有界并释放，只把验证后的值留给Live；provider/Redis/锁/worker保留长期生命周期，退出有finally释放，worker不能拿Session。测试连续poll、异常rollback、连接归还、尾盘grace、换日换owner及并发锁；隔离PG补证据，不能把SQLite通过当PG完成。缓存增长先量测，不猜淘汰政策或添加框架。禁止生产断网/重启/provider调用/Runtime切换；新版本自然运行待独立Gate。接口歧义回Astra，不重设计SA-03事实规则。

### SA-05 / 主升浪Action资格、合同及身份对齐 / P1，D2待决

- **问题与结果**：F-04；adapter/projector/canonical对INITIAL_CLEAR_NO_ENTRY只有一种明确解释，不再同身份代表两种资格。
- **证据/设计**：0fd94f402与spec309–344冲突；无evidence fixture仍有CLEAR但trades=0。**D2未批准，当前只可准备差异/测试，不能选语义实施。**
- **开始条件**：owner在主报告D2明确选择。推荐恢复accepted完整lifecycle资格，暂不新增post-gap展示资格；另一选项是接受当前按计算段放宽，但必须明确版本/兼容。
- **最小读集**：newow-product-reference-trading spec，DECISIONS/PROJECT_SOURCE相关段；
  `packages/quant-core/guiyi_quant/newow/product_adapters.py`、`reference_trades.py`、`product_identity.py`、
  `reference_trading/strategy_checkpoint.py`；test_product_adapters/test_reference_trades/test_strategy_checkpoint。
- **修改范围**：D2选定的两个语义入口、明确相关identity/codec接口以及对应accepted文字/负例；根文档变更交SA-07或单点串行。不改MA/J/D1-D6等公式数值、收益统计、UI开放范围。
- **公共接口**：owner-lifecycle资格与calculation-segment“未观察到”不能同名混用；Action的provenance与eligibility可机器校验，projector独立验证。若D2只恢复严格原合同，不发明额外资格；若接受新行为，先把精确字段/identity补入本任务获owner确认后实施。
- **不变量**：无入场CLEAR不生成交易/虚构收益；截断/缺证/换owner/未来evidence fail-closed；Hint不转换成仓位；P3仍disabled。checkpoint旧tuple2→tuple3处理交接06，不能静默decode。
- **步骤**：列出三条真实fixture的旧/现/选定结果→锁定版本和checkpoint决策→修adapter/projector→修反向测试名与断言→canonical/产品文字一致→发给P4接口交接。不自造牛哇私有原规则证据。
- **验证**：完整owner初始CLEAR、warm-up已有BUILD、左裁/缺evidence/stale evidence、PRICE_UNAVAILABLE后重warm-up、换owner、未来cutoff、同Bar顺序、batch/incremental/restart与旧候选checkpoint。
- **命令**：`check_py services/quant-api/tests/newow/test_product_adapters.py services/quant-api/tests/newow/test_reference_trades.py services/quant-api/tests/newow/test_reference_interruptions.py services/quant-api/tests/newow/test_reference_statistics.py services/quant-api/tests/reference_trading/test_strategy_checkpoint.py`；
  影响identity后加`check_py services/quant-api/tests/newow/test_product_reader.py`与对应API身份测试（以实际call graph选择）。
- **现场/授权**：D2是产品语义授权；生产candidate重建、Scope/正式版本切换不包含。只读固定数据页面可验证展示，不据此证明盈利/OOS。
- **迁移/回滚**：明确候选checkpoint新schema或显式失效重建，不对假想生产数据做migration；回滚须连同identity并拒读不兼容新状态，不覆盖旧结果。
- **并行/Review**：Newow语义owner独占adapter/projector；06等接口后动codec，仓储纯修正可先做。独立策略/canonical review；无公开证据的业务取舍回owner/Astra。
- **模型**：Astra收敛D2，批准后Sol medium实施。

启动 prompt（当前为调查/决策准备，非立即实现）：

> 处理 SA-05 的D2决策准备。读AGENTS、2026-09-22-system-audit主报告F-04/D2和任务包SA-05。对照0fd94f402、accepted spec与当前adapter/projector，给出完整owner、缺evidence、post-gap三个固定输入的行为差异及版本/checkpoint影响。当前没有D2语义批准时只做调查，不修改canonical或恢复/放宽资格。若本消息已附明确D2选择，则仅实现该选择，保持Action-only不产生trade/收益、公式不变，并完成指定因果/重启/身份负例和独立Review。P4 codec由SA-06 owner接手，不并改，不执行生产重建或Runtime promotion。

### SA-06 / 原P4负责人补仓储批次与输入身份 / P1候选阻断

- **问题与结果**：F-05/F-08/R-03；合法同批开平/中断可原子保存，旧cutoff仍读正确OPEN，批次边界不影响结果。
- **证据/设计**：同batch OPEN→CLOSE抛ORPHAN_MARK、完整rollback；legacy改mark/day仍no-op；tuple2/3 checkpoint同schema风险。第2节reference合同不改配对/收益语义。
- **前置**：**交已有codex/unified-reference-trading-p4 owner**，先检查其未提交实现/新测试是否已修，不另起竞争分支。基线同步SA-00；Newow codec/资格依赖SA-05，仓储复现修正可先做。
- **最小读集**：reference-trading spec、已有P4 plan；
  `app/reference_trading/repository.py`、`contracts.py`、`models.py`；
  `packages/quant-core/guiyi_quant/reference_trading/reducer.py`、`contracts.py`、`strategy_checkpoint.py`；
  test_repository/test_repository_snapshots/test_repository_postgresql/test_reducer及P4新增builder/driver测试。
- **修改范围**：repository批次版本/mark关联、公用输入规范化/codec、对应P4已有tests；不接P5 HTTP/P6worker、不开Scope，不独立重写planner/CLI。
- **接口**：PreparedBatch/commit_batch/checkpoint CAS保持；保持现有每批一个seq、每trade一个最终结构版本；mark按对应transition当时合法OPEN及稳定entry/owner校验，再链接同trade结构行，不能仅看最终status。查询时entry未可见则不返回；终结尚未到cutoff或forward observed_at则由entry事实恢复OPEN，并仅应用cutoff/observed_at内可见mark，不泄漏最终holding_bars/收益。终结可见后才返回CLOSED/interrupted。历史跨batch版本和旧snapshot隔离保持，截止于开平之间必须读OPEN。非法orphan仍拒；同batch replay no-op、同身份异内容冲突。
- **不变量/不做**：六表原子性、revision/snapshot/cutoff、Decimal、owner/segment/entry_action identity不弱化；禁止删除有效mark使测试通过，禁止把当前最终行冒充历史版本；不改收益统计。
- **步骤**：当前P4复跑两Bar反例→与1Bar分批结果对照→修时序版本/mark校验→统一typed reducer输入→接SA-05 codec决策→P4 resume/publish接入→隔离PG原子/CAS→独立Review。
- **验证**：batch=1/2/256、同Bar CLEAR→BUILD、跨批持有、无Action mark、roll/data conflict、seed/resume、同批no-op、异内容拒绝、旧snapshot不漂移、cutoff中间OPEN；forward延迟observed_at的action/mark/interruption分别负例；legacy若删除需全调用搜索证明只剩tests，否则规范化后同hash。
- **命令**：`check_py services/quant-api/tests/reference_trading/test_reducer.py services/quant-api/tests/reference_trading/test_repository.py services/quant-api/tests/reference_trading/test_repository_contracts.py services/quant-api/tests/reference_trading/test_repository_seed.py services/quant-api/tests/reference_trading/test_repository_snapshots.py services/quant-api/tests/reference_trading/test_checkpoint_parity.py services/quant-api/tests/reference_trading/test_strategy_checkpoint.py services/quant-api/tests/newow/test_reference_trades.py services/quant-api/tests/newow/test_reference_interruptions.py services/quant-api/tests/test_subing_reference_projection.py`。
  再运行P4已存在新tests，精确路径以原owner工作树列明。隔离PG通过`app/db/migration_test_guard.py`身份校验后，使用安全加载的`GUIYI_ISOLATED_MIGRATION_DATABASE_URL`单独运行
  `services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/reference_trading/test_repository_postgresql.py`；
  不使用离线check_py，不回显URL、不依赖生产.env，未配置skip不算通过。
- **现场/授权**：隔离PGschema测试可在已验证隔离环境进行；生产0047 migration、历史build、active revision切换和worker enable各自待明确授权。
- **迁移/回滚**：本设计不变schema，以现有Action/mark/effective time作cutoff投影；若实现证明既有字段不能表达某合同，带最小反例回主设计者，不临场扩表或插同seq多版本。旧候选checkpoint显式失效/rebuild，不静默读取。回滚前核对候选兼容，无生产清表。
- **并行/Review**：P4单owner独占repository/contracts/CLI；SA-05完成后再交codec。独立reference/持久化高风险review；需要改变sealed batch业务合同/收益/表结构回Astra。
- **模型**：Sol medium在既定P4合同内实现；跨域设计歧义回Astra。

启动 prompt（交原P4会话）：

> 请在你已有P4工作树接手 SA-06，不创建第二套P4。读取两份2026-09-22-system-audit文档及reference-trading spec，先核对当前未提交代码是否已经修复同PreparedBatch OPEN→CLOSE导致ORPHAN_MARK的问题；没有审查或覆盖你的其他改动的授权。合法历史mark须按bar当时OPEN校验；保持每批每trade一最终结构行，依已有Action/mark/effective time/observed_at恢复cutoff前OPEN，不能插同seq多版本、改schema、删除mark或降低原子性。补batch1/2/256、反手/中断、restart/no-op/冲突和旧snapshot回归；legacy reducer统一typed/hash。Newow资格和codec依SA-05明确决策，未决不自行选择。运行指定离线测试及隔离PG/CAS验证，保持0047生产migration/build/worker/Runtime未授权，独立Review后按原P4工程授权交付。

### SA-07 / 工程验证与文档职责减负 / P2

- **问题与结果**：F-06/O-01；版本/文档测试保护真实约束，不因正常版本或计划新增机械失败；一处维护当前事实。
- **证据/设计**：源码版本四处1.10.13而断言1.10.11；tracked plans68而要求0；main allowlist5同样过时。需D3同意去掉文件名逐项清单，安全Gate不删。
- **前置**：SA-00完成回流/版本基线；D3与工程授权明确；01–06文档建议收集，不等全部业务修正才能改稳定规则。
- **最小读集**：AGENTS、docs/DEVELOPMENT、TESTING、STATUS头部/当前状态、release-agent技能与deploy/README；
  `tests/engineering/test_canonical_consistency.py`、`test_repository_hygiene.py`、
  `services/quant-api/app/version.py`、两个package元数据与uv.lock根包、`scripts/engineering/secret_scan.py`。
- **修改范围**：两项工程检查、TESTING导航/DEVELOPMENT交付说明、必要release流程回流检查描述。
  不修改全局技能、宿主权限/.env；本轮审计文件保留，不清outputs/旧plans。
- **接口/语义**：版本检查比较已有权威版本和所有consumer元数据；发行candidate另用明确expected tag，不让每次测试内手写历史常量。文档卫生保护禁止内容/失效active引用/生成垃圾与secret，不设置不断增长的精确plan名单。
- **不变量**：保留secret、退役入口、路由/single worker、输入来源、发布exact identity检查。权限模式断言若保留须归配置约束，不声称能改变宿主权限；不得为过测修改danger模式。
- **步骤**：基线复现→分开产品不变量和流程记录→版本正/负例→文档规则用代表性允许/禁止样例→TESTING按风险导航→STATUS仅在已核验事实范围整理索引，历史过程留原文件/Git，不提前标完成→独立抽查遗漏安全Gate。
- **验证**：四处版本一致通过，一处不一致失败，release期望错误失败；允许正常审计计划，禁止secret/临时垃圾/退役active入口仍失败。不要用固定文案断言替代行为。
- **命令**：`check_py tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py tests/engineering/test_secret_scan.py`；
  `services/quant-api/.venv/bin/python scripts/engineering/secret_scan.py --json`；
  `git diff --check`。先读扫描工具保证不输出秘密原文；不触发无关Web/全量算法测试。
- **现场/授权**：无生产验收需求；release/preflight规则若涉及真实执行只验证dry-run，不能执行main/tag/Runtime。
- **迁移/回滚**：单提交可回滚；用文档导航替代手抄过程但保留evidence出处；若要删除历史文件另给精确列表、理由与批准，不夹带批量清理。
- **并行/Review**：根文档单owner；业务任务不并改STATUS/TESTING/DECISIONS。普通文字自审，安全规则保留情况独立Review；删除强制Gate/变更项目授权回owner，不以“简化”代替批准。
- **模型**：Sol medium。

启动 prompt：

> 实施已批准的 SA-07/D3。读AGENTS、两份system-audit文档F-06/O-01及SA-07，先核对SA-00当前版本/回流结果。把硬编码历史版本测试改为现有版本的一致性与候选期望验证；把过时的0文件/5文件计划清单改为保护真实文档和安全约束。只整理稳定TESTING导航与必要DEVELOPMENT交付说明，STATUS完成状态必须有当前证据。保留secret、退役入口、路由、single worker、release exact identity和生产Gate；不改宿主权限、全局技能、.env，不删既有plans/outputs。运行指定正负例、engineering和安全扫描，独立检查未降低保护，再交付根文档单owner结果。

### SA-08 / 集成验收与发布准备 / P1收尾

- **问题与结果**：防止各任务各自通过但公共接缝/身份不一致；得到明确范围、当前SHA的可审阅候选及待验表。
- **证据/设计**：主报告7/8，引用01–07实际交付而非本轮旧测试。不是把“规划完成”改成“Runtime完成”。
- **前置**：明确集成owner；00→02→01→03→04→05→06→07顺序按已批准范围整合。
  D2未决可只集成稳定性子集，不把策略决策拖成事故修复前置；P4待验独立保留。
- **最小读集**：AGENTS、当前STATUS、两份审计文档、各任务diff与真实测试摘要、TESTING、release-agent技能/deploy README；无需重复全仓审计。
- **修改范围**：必要冲突修正、极窄接缝测试、当前事实记录；不借集成发明新功能。若冲突改变业务合同回原owner修，不能集成者随意选一边。
- **接口/不变量**：第2节合同逐项检查；只承诺实际选入候选的任务。git tree、version、test input和readback每项绑定SHA，不用一次“全绿”吞掉不同Gate。
- **步骤**：核对新develop/main/P4差异→审查逐任务接口→跑直接受影响集合及消费者冒烟→固定candidate diff/identity→准备release/promotion具体对象与回滚说明→停在授权边界。
- **验证矩阵**：SA-01生命周期/脱敏，02phase→health→Web，03MDS→Newow/SuBing，
  04Live事务/锁，05/06批次/版本/快照，07工程/secret；共享纯函数测一次，关键consumer接入分别保留。
  真实PG/Redis如果涉及的Gate未完成则如实pending；受影响Web实际build和隔离browser smoke。
- **命令**：重跑合入后各任务列出的定向命令，非所有任务无条件全量；
  `pnpm -C apps/quant-web build`（含Web变化时）、
  `services/quant-api/.venv/bin/python scripts/engineering/secret_scan.py --json`、
  `git diff --check`、`git status --short`、`git rev-parse HEAD`。
  release-agent render/preflight具体命令先读当前技能和目标服务，仅dry-run，不抄过期tag。
- **现场/授权**：本任务默认只形成RELEASE_CANDIDATE或CODE_COMPLETE_EXTERNAL_GATE_PENDING。
  发布批准需精确main/tag/Release批次；promotion另列root/commit/服务/恢复范围。
  获授权后由发布任务执行，再做六项installed/loaded identity、API版本、capability和health回读。
  自然夜盘/18:05/周检分别等既有日程，不手动补跑；无证据INCONCLUSIVE，schedule-only not_running不是失败。
- **迁移/回滚**：工程commit可revert；正式Runtime回滚是独立受控操作，必须考虑metadata/候选checkpoint兼容。
  明确每个旧路径已删除或暂留的实际消费者与退出条件，不能留下无人维护fallback。
- **并行/Review**：单集成owner，其他会话停止改其已交付共享文件；独立跨域review只看重要接缝，不追finding数量。范围变化或新生产恢复需求回owner。
- **模型**：Sol medium执行集成；跨领域冲突回Astra。

启动 prompt：

> 担任 SA-08 唯一集成负责人。读AGENTS、当前STATUS、2026-09-22-system-audit两份文档和已批准任务的真实交付，不用旧审计测试冒充新SHA证据。核对develop/main/P4及未提交修改，按任务所有权整合已批准子集，验证phase→health→Web、facts→consumer、Live事务、盘后生命周期和reference批次/identity接缝。D2或P4未完成不阻塞已独立通过的稳定性候选，但必须明确未纳入范围。执行相关命令、build/隔离smoke/secret检查并独立Review，交付精确candidate diff、版本、测试与待验表。默认只做开发集成和发布准备；没有精确授权不得main/tag/Release、数据写入或Runtime切换。自然运行验收独立，缺证标INCONCLUSIVE，不手动启动来制造成功。

## 4. 推荐执行编排与停止条件

第一批：相关文件基线核对；00完整回流、01只读取证/诊断修正、02健康修正可并行，集成前解决相关差异。
第二批：01诊断/lazy修正、02健康修正并行；03事实层可独立推进但共享装配单owner。
第三批：04资源；05仅在D2明确后；06交原P4 owner，仓储复现可先做；07工程规则/文档。
最后：08单集成owner。第一批小修通过即可形成独立候选，无需等待所有重构。

普通且合同清楚的实现优先Sol medium；模型名/档位按环境可用配置，不改用户级默认。
跨任务公共接口、重要产品或业务歧义回Astra；实际provider/数据/Runtime权限回owner。
Review只分Confirmed Issue、Risk / Needs Verification、Optional Improvement，不能为数量加重构。

最终每个实施任务给出：当前SHA、改动与实际验证、独立Review结论、未完成Gate、回滚边界和一个最小下一步。
本轮这些启动prompt是可复制的任务文本，**尚未分发到新会话，也没有开始实施**。
