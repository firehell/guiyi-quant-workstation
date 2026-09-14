# 普通 W1 补数一次总包闭环：设计与实施计划

> 执行时使用 `superpowers:executing-plans`，由一个主执行任务连续推进，阶段末独立 Review。Owner 已确认工程计划并随后批准精确总包一次执行；该次因B2411来源异常停止，意图已消费，不创建新用户任务或恢复旧任务。

日期：2026-09-14。设计基线：`develop/origin/develop@7982c8c921245853d52c0740e20278ec144e7464`。当前状态：`PARTIAL`；工程已集成develop@4c891d8df，一次总包执行102成功/1失败/1014未尝试，全部102成功单元独立读回及零缺口replan通过。详见[执行证据](remaining-123-execution-evidence.md)。以下计划步骤与旧计数保留为原设计，不授权失败后重试或续跑。

工程检查点：实现提交 `84df05552`，专项 Review 的两轮修复为 `f3a30ec79`、`842844a19`，最终专项
复审无阻断；总审补充的 repair 反向覆盖和来源 journal 核对由 `4c18a9a23` 修复并覆盖回归。
主会话组合测试 576 passed，Ruff/Mypy、OpenSpec 9 项、secret scan 通过。
Tasks 1–2 的实现、隔离测试和专项 Review 已完成；下列清单保留审批时的步骤定义，不由勾选代替实际
证据。代码集成以 Git 记录，Tasks 3–4 的真实准备与执行以冻结代码对应的本地 evidence 为准，普通
总包完成必须满足文末结算条件。

## 目标、事实与边界

目标是一次准备并交付全部剩余普通 W1 补数的精确范围，取得一次匹配的总包执行意图后连续执行到结算，不再只做首批 20 个单元后交回。一次总包不等于一笔数据库事务，也不保证在外部故障或漂移下无条件完成。

已有成功对象：Session 247 目标/33,224 行；SI2308；EC2607 8 targets；普通 batch-001 的 20 单元/378 targets；RS2309/RS2311 专项 26 targets。不得重新下载这些已完成目标。原 PF2611、原九个 RS 和新增两 RS 的来源非正事实继续隔离，不属于本次普通补数。

上次完整普通清单 1,138 个候选发生在 EC 和普通首批执行前；扣减得 1,117 原本仅是账面数。**本轮已重新审计确认普通候选确为 1,117 个**：历史截点 `2026-09-13T06:36:13+00:00`、operational 60、frequency=1w、matrix=false；`complete=true`、`budget_exhausted=false`、3,746 work、耗时 808.91 秒、provider requests=0、生产 writes=0。不得把当日新增日期混入本轮。

### 本轮实测范围

| 量纲 | 实测值 |
| --- | ---: |
| 普通唯一 physical-contract W1 单元 | 1,117（覆盖 55 个品种） |
| 内部分批 | 56：55 × 20 + 17 |
| 原生 D1/W1 月目标 | 22,695：D1 11,421 + W1 11,274 |
| 目标完整 expected bars | 264,546 |
| 实际 missing endpoints | 251,384：D1 207,716 + W1 43,668 |
| 额外待专项审查候选 | 9，全部为原九个 RS，不纳入普通总包 |
| metadata proposals | 0 |

dependency 分类为 DATA_READY 142、DATA_UNAVAILABLE 2,270（12 个分区缺失、2,258 个前缀缺失）、NOT_APPLICABLE 20、SOURCE_EXCEPTION 8。dependency 数不是合约数，也不代表页面矩阵结果。22,695 是逻辑月目标，不是底层实际 SDK 调用数；本轮没有估算下载流量。

原始报告：`/tmp/guiyi-ordinary-closeout-audit-20260914.ndaDfr/full-report.json`，SHA-256 `3f4a5693194bf6844c8e4134e614297755535c2a83a97c4468cc51bdf9991ec1`；同目录 `compact-report.json` 和 `summary.json`。原始报告不属于可直接 apply 的包；实施任务须在稳定工作树保存并校验它，临时文件若不可得就原生重审，不凭本文数字伪造目标。首次受 sandbox 连接限制的诊断没有开始事务；实际成功审计在显式只读事务中完成，非 provider 重试。

只处理当前 PROPOSED 的 physical contract W1 与同源 D1 dependency。排除 REVIEW_REQUIRED、SOURCE_EXCEPTION、metadata 不满足、unknown、无法读验的对象；所有排除项仍留在结算分母。无报价替代、跨频补洞、零价改正、删 bar、缩窗、补 MainContractMap 或新建 Session writer。

不做配额估计、校准或额度探测；实际 provider quota/error 仍须准确报告并停批。不包含完整页面/540-case matrix、D1/60m 产品开放、发布/main/tag、Runtime/Scope/通知/策略/真实交易。

## 推荐方式：一个总包，复用每批 20 单元的执行器

不把 `newow_weekly_recovery.py` 的 20 单元限制改成无限，也不手工开展约 56 轮独立临时操作。增加一个薄的总包编排入口，复用已经验证的 prepare/apply/inspect 子执行器。

1. 从完整原生审计提取唯一 `(symbol, contract, frequency)` 候选，保留原生最大 required through 和 consumer provenance。相同合约重复/冲突输入拒绝，不用手工 max/合并取代原生 coalescing，也不同时加入 D1 独立计划重复补数。
2. 全部候选稳定排序并划分每批最多 20 个完整 W1 单元。N 个单元产生 `ceil(N/20)` 批；本轮已核实的 1,117 对应 56 批，末批 17 个。执行包仍须从完整原生报告和新 prepare 生成，不能仅凭计数执行。
3. 所有子包在执行代码冻结、工程 Review 通过后用原生 prepare 生成。总包只索引既有子包相对路径、内容 hash、批次顺序和目标身份，并绑定审计 hash、固定 as-of、universe hash、代码/配置/Canonical 根身份与精确总计。它不是第二行情或缺口权威。
4. 一次明确审批可以同时批准这个已枚举总包及所有子包的 exact hash。一个主进程执行这一总 attempt，内部调用各子包一次；正常批间切换不再重复询问。旧批准、文件中的 approved 字段或历史 hash 不能替代当前意图。
5. 所有子包及输入身份在首次 provider 前全量验证，之后每个子包运行前重新核对 hash/路径，单元继续使用原生维护锁内 replan。prepare 与执行之间任何实质漂移都停止，不静默刷新包然后接着跑。
6. 每个单元仍由原生 manager 做 D1/W1 同源下载、staging/hard validation、逐分区原子发布、projection invalidation、Catalog/Parquet/MDS 回读和零目标 replan。只有本批全部通过才进入下一批。

总包源码独立于行情算法，只负责输入完整性、顺序、一次执行和结算。每批在同一主进程内调用现有 `newow_weekly_recovery.main(argv, stdout=...)`，使用离散参数和独立输出缓冲，解析返回码及原生结果，不启动后台子进程或 shell。这样 writer guard 覆盖整个执行调用，不会留下控制器已死、子执行器仍偷偷继续的问题。把总包入口纳入执行代码 hash，防止源码变更却复用已批准总包。

## 一次执行的失败与运行约束

- 第一次计划漂移、源异常、额度/网络错误、维护锁冲突、文件保存失败、readback 不通过、子执行返回非零或未知提交，立即停止整个总包；后续子包不启动，不自动重试。
- 停止时保留已提交成功对象；给出 completed/failed/unattempted/unknown 四类和已知 provider 计数。退出异常可能发生在子包写 receipt 前，因此不能把缺少 receipt 的已启动子包算作未尝试。
- 外层在启动每个子包前持久记 started，返回后关联原生结果并记终态。事件缺失、receipt/hash 不一致、journal started 没有响应均只允许只读对账，不自动 resume。现有原生 journal/receipt 继续为具体单元证据，不复制为另一套执行账本。
- 总 attempt 目录独占且不可覆盖，同一 id 二次启动拒绝；并发实例必须在 provider 前有本地总包 writer guard。已存在/运行中的 attempt 不能自动接管；进程死亡后新进程也不能靠进度文件获得写入权。
- writer guard 位于总包绑定的唯一共同输出根，以 Canonical 根身份命名并持有稳定 inode，不能放在每次新建的 attempt 子目录。复制总包或改 attempt id 不改变 guard 位置；不同工作树须使用同一已批准输出根，缺失/不可验证或改根均停止，不创建可绕过的替代 guard。这个本地互斥只防总包执行器互相重入，不代替原生数据库维护锁。
- 宿主退出、系统休眠、代码/配置更新或生产维护可能打断长任务；不安装 launchd/cron、不启用自动重启、不改休眠设置、不停 Runtime，也不长时间独占全局维护锁。当前 18:05 盘后等自然维护按既有授权运行；冲突就停，不能为完成总包接管生产调度。
- 原生锁按单元获取/释放。执行窗口的只读 preflight 必须披露已运行维护和已知计划任务；如果不能确保本轮兼容，不开始真实执行。不得靠硬编码睡眠/自动重试绕过 maintenance_locked。
- 若失败后继续，需要只读刷新剩余范围、排除已有成功对象，形成新的精确总包并取得新意图。不会自动重复下载成功内容，也不会“一个审批永久恢复运行”。

## 完成标准

同时达到以下条件，才可称普通补数本轮完成：

- 总包每个冻结普通单元都有 passed/noop 的原生结果、可靠来源 journal、严格三层读回、remaining_target_count=0；noop 也要有同一合法计划和读回，不能把漂移伪装为 noop。
- 新进程对全部冻结单元原生 readonly replan 为零；这是本次写入结算，不仅检查最后一批。
- 同一 as-of 的全 60 品种 dependency-only audit 完整跑完，complete=true、budget_exhausted=false，并输出普通/异常/metadata/unknown 分类变化。全局普通候选为零才能称该固定范围普通缺口归零。
- 后审计若发现未被总包覆盖的新 PROPOSED、新的 metadata/unknown 或更多异常，保留并列为未完成，不自动加入执行，也不宣布只剩页面验收。新目标需新的精确范围。
- `STATUS.md` 的旧 896/494/EC pending 与任务证据同步；历史报告保留并注明被新审计取代，不改写过去结果。代码完成、总包执行完成、普通缺口归零、完整页面就绪是四个不同状态。

## Task 1：精确输入与总包准备

文件：新增 `scripts/newow_weekly_recovery_campaign.py`；新增 `services/quant-api/tests/newow/test_weekly_recovery_campaign.py`；在 `scripts/newow_weekly_recovery.py` 的执行身份文件清单加入新入口。命令仅登记 `TESTING.md`。

接口（总包模块内）：`partition_ordinary_units(report: Mapping[str, Any]) -> tuple[tuple[dict[str, Any], ...], ...]`；输入原生完整 report，输出每组 1–20 个原生 unit 输入；N=0 输出空 tuple，零下载的 readonly completed 结果，不伪造空子包。

- [ ] 写失败测试：不完整/耗尽/错误 as-of 或频率的 report 拒绝；非普通状态不进入队列且进入排除统计；重复 contract/frequency 身份、through/hash 冲突拒绝。
- [ ] 用隔离 fixture 分别验证 0、1、20、21、1,117 个互不重复普通单元，确定边界与目标集合不丢失；示例断言如下（生成器由测试定义，生产不造数据）。

```python
batches = partition_ordinary_units(native_report_with_1117_unique_ordinary_units)
assert len(batches) == 56
assert [len(group) for group in batches] == [20] * 55 + [17]
assert len({(u["symbol"], u["contract"], u["frequency"])
            for group in batches for u in group}) == 1117
```

- [ ] RED 后实现最小切分与校验，不改原生 planner。以原生 prepare 为每组生成现有格式子包，记录真实 child hash；检查首个/末个子包与联合身份全集。
- [ ] 实现总包 schema v1：固定审计/作用域/执行身份、按序 child path/hash、每批及全体 unit/target/expected-bar 数。所有路径限定同一 evidence 根，拒绝绝对/逃逸/符号链接、覆盖、过大或错类型输入；无 secret/payload 进 Git。
- [ ] 测试 child 完整集合校验：丢批、添批、改序、重复单元、错误 hash、来源根或代码身份不一致均为零 provider/写入。执行准备过程中不调用 provider，不计算 quota。
- [ ] GREEN、Ruff/typecheck、独立 Review，修复后提交；不要为准备包不断写新的生产代码版本导致所有包失效。

## Task 2：一次总 attempt 串行执行

同一总包模块的接口：`execute_campaign(manifest: Mapping[str, Any], *, attempt_root: Path, invoke_batch: Callable[[Path, str, Path], Mapping[str, Any]]) -> dict[str, Any]`。callback 输入已验证的 child 文件、其 hash、专属 attempt 目录，输出返回码及原生 batch-result；默认实现在同一进程调用既有 `main` 的 apply 分支，不复制 open_unit/provider/writer，也不启动额外进程。

- [ ] 写失败注入测试：第 2 批失败只调用前两批，第 3 批未启动；第 2 批有部分成功要原样保留，不能记整批回滚。

```python
result = execute_campaign(three_batch_manifest, attempt_root=tmp_path,
                          invoke_batch=first_passes_second_fails)
assert invoked_batch_ids == ["batch-001", "batch-002"]
assert result["status"] == "partial"
assert result["unattempted_batch_ids"] == ["batch-003"]
assert result["retries"] == 0
```

- [ ] 测试 started 持久化失败为零子执行调用；执行异常/无法读取终态为 unknown；保存最终汇总失败不能向用户报告 completed；二次启动及并发实例拒绝。
- [ ] 测试开始前全包验证，以及执行中 child/hash/代码/config 漂移；无 source 请求、无 projection invalidation 发生在身份检查之前。
- [ ] 实现最小串行循环与根 attempt started/result 记录，复用原生 child receipts，只追加一个总包结算摘要；不实现 retry/resume/replay 或跨进程接管。
- [ ] 以隔离数据库/fake provider 完成 21 单元跨两批贯通，覆盖 D1/W1 同源、原生 lock/hash、partial/commit unknown、每单元 MDS 回读；真实外部操作不能作为测试。
- [ ] 定向测试、静态检查、自审及独立 Review 全绿后冻结代码；按已批准实现的工程流程集成 develop，不发布 Runtime。未批准本设计前不实施该代码变更。

## Task 3：冻结全部普通范围并申请一次总包意图

- [ ] 在冻结代码上重新做原生 readonly audit/preflight，核对固定历史范围与本轮审计差异；不是把 1,117 写成常量。读取当前 maintenance 状态，明确生产环境与 projection 影响。
- [ ] 生成全部子包与唯一总包；再次验证联合目标恰好等于本次全部普通候选。单元频率固定 W1，内部 D1 companion 随原生计划，不接入 RS 专项或 60m。
- [ ] 提交一次精确申请：总包 hash、代码/环境、固定截点、N 个单元/M 批/K targets/目标 bars、数据根及回读/失败边界；它已经列出每个子包 exact hash，不再每 20 单元重复申请正常批间切换。
- [ ] 只有新的、匹配该总包的一次执行意图到达后，启动一个总 attempt；本轮“规划下”不构成此意图。未获批可完成全部工程和 readonly 准备，不进行生产 mutation。

## Task 4：执行、全量结算与文档收口

- [ ] 总 attempt 按冻结顺序串行运行；终端/任务退出即视为可能中断，不自动续跑。保留每批成功证据，遇首个失败返回精确停止位置。
- [ ] 全部子包通过后，在新进程完成冻结清单逐单元 readonly replan，再跑同一截点全域 dependency-only audit。MDS/文件只是读回，不重新获取 provider 数据。
- [ ] 对账账面 N 与全部终态，保证 completed+failed+unattempted+unknown 的单位和全集一致；unknown 不重复算入其它终态。报告实际缺失端点补齐量与 expected bars，不能把两者混为一个数。
- [ ] 更新 `docs/tasks/newow-weekly-data-recovery/remaining-123-execution-evidence.md` 及 `STATUS.md`，注明新审计时间/hash、普通剩余数、明确排除项、是否完成外部 Gate；保留旧 evidence。验收后代码/文档普通提交与 develop 集成，不进行 main/tag/Runtime 操作。
- [ ] 执行恢复+campaign+readiness+Catalog/MDS 定向测试，适用 engineering、OpenSpec、secret scan、diff 检查；最终独立 Review。只有当前实际结果支持的阶段才能宣布完成。

## 本轮计划交付边界

上一轮已完成当前代码/证据核对、原生 readonly 余额审计、计划与独立 Review。本轮 owner 确认后实现总包编排，代码验证并冻结所有精确子包后，再申请一次真实总包执行意图。正常情况下只需这一份真实执行申请，异常或跨会话重启不在其中。
