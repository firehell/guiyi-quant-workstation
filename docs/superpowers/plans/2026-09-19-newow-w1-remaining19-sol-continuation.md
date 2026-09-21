# 牛哇 W1 剩余 19 品种：Sol Medium 接续方案

> 执行：一个新的 Sol medium 任务，使用 executing-plans；本方案补充原方案，优先描述实际未完成部分。质量、时序、身份和写入边界由独立 reviewer 审查。按 AGENTS.md 连续完成已授权工程，不重复要求设计批准。

**Goal:** 在保留旧 v1 和正式 41 品种行为的前提下，补齐隔离 W1 v2 消费链，完成实际冲突诊断和精确批次准备；获批后修复数据并验收固定 19×3=57 组合。不能可靠实现的明确记录，不强行凑 READY。

**Architecture:** 同一个不可变、经校验的 W1 质量政策贯穿 composition → Reader/MDS → 策略输入 → ProductIdentity/计算段 → 快照缓存/令牌 → ReferenceTrade/适配器。只复用现有领域及统一参考 reducer，不创建第二套实现。

**Spec:** 原方案 `2026-09-19-newow-w1-remaining19-repair-plan.md` 的数据合同、固定范围和受控写入边界继续有效；本文件解决其执行中暴露的身份与协作问题。

## 1. 真实交付状态

- 已完成任务“牛哇周线剩余19品种修复与57组合验收”，任务 ID `01a0b970-ea18-7893-af30-b5853986f7a8`，最终明确 PARTIAL。
- 原分支 `codex/newow-w1-remaining19-repair`，提交 `5ba5a7cc36bd7bdaace2432e6aff3c7b7b50d645`，已报告推送，未集成 develop。
- 原 worktree `/Users/zhangzhao/.codex/worktrees/8590/guiyi-quant-workstation` 已核对干净，保留不删除。
- 只完成 `weekly_quality.py` 的显式 v2 证明及 MDS opt-in；Reader 暴露已因审查发现身份混用而撤回。没有候选页面入口，没有数据修复，没有57验收。
- 上一任务报告相关回归310 passed；本次在该提交重新运行 weekly_quality 与 catalog_and_service 两文件，125 passed in 2.24s。不把历史310当新任务验证。
- 主树核对 develop 为 `a23475c3d08debabc416f1300c8b58e0984c7ab4`，有其他任务未跟踪计划，不覆盖或暂存。
- 统一参考交易 P2 接续任务正在运行：`01a0b97b-2230-7ad2-b2a8-20afc9d16381`，实际接续分支 `codex/unified-reference-trading-p2-closeout`。共享 reference/adapters/checkpoint 等文件须在实施时读最新事实；不因它未结束而停止数据诊断/prepare。

任务输入：主树 `/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining19-20260919/`；完整原生报告与 summary 尚未跟踪。原分支已保存紧凑输入和 SHA 于 `docs/superpowers/plans/inputs/newow-weekly-remaining19-20260919/PROVENANCE.md`。它们是旧审计输入，不是当前数据修复回执。

## 2. 原任务问题与新的执行原则

| 问题 | 已有事实 | 本轮处理 |
|---|---|---|
| v2 只进 Reader 会与 v1 身份混用 | v1 版本来自全局常量，ProductIdentity无质量政策；快照fact_key/token/参考身份未随请求隔离 | 一次贯通身份再开放候选；不要反复局部接入再撤回 |
| 与统一参考 P2 共享实现 | P2正收敛公共reducer、checkpoint和旧DTO | 保持唯一配对逻辑；本任务提供质量/stream身份，不重写P2 |
| 20合约冲突只重复旧错误码 | 现存W1与D1聚合不等，未完成字段和来源裁决 | 做真实字段对照；无法判来源则SOURCE_VERIFICATION_REQUIRED |
| 旧151 PROPOSED未刷新 | plan hash和数据修订不再可假定有效 | 先刷新J小批次，再PG/SI；与冲突组分开，不要求全部19先解决 |
| 57全量验收尚未开始 | 正式开关仍57 UNOPENED | 候选入口就绪后立即验现有输入，数据阻塞保留；授权后只补必要数据并完整复验 |

不要把“需要跨模块改动”本身当作无法实现。先列接口、改动范围、负向测试并验证；只有真实证据/合同矛盾、无法安全隔离、必要外部授权或并行修改冲突才暂停受影响部分。

## 3. R0：承接原成果，不重做

- [ ] 新独立工作树、新 codex/分支，以 `5ba5a7cc3` 为成果基础并核对最新 develop。若原生创建从main启动，先在干净树内建立正确接续分支；不把main强行合入develop制造无关UI冲突，不改原8590树。
- [ ] 核对原提交是否已被其他任务集成；已包含不重复cherry-pick。用正常Git合并或选取必要提交，不reset用户工作、不force、不清理原树。
- [ ] 复制本计划进新树；复验125项直接相关测试及必要扩展，固定旧v1/D1 golden身份。核对 compact evidence哈希与原始报告。
- [ ] 读取 P2任务最新紧凑状态和共享文件diff，明确本任务仅负责质量版本传递，P2拥有公共配对/checkpoint实现。不得给另一任务发送新的工作指令或修改其worktree。

## 4. R1：完整且向后兼容的质量身份

落点：`packages/quant-core/guiyi_quant/newow/product_contracts.py`、`product_identity.py`；`services/quant-api/app/market_data/newow/product_reader.py`、`product_service.py`、`weekly_snapshot.py`、`snapshot_cache.py`、`product_release.py`、`public_errors.py`、`readiness.py`；必要 API/schema/Web 类型落点按实际调用图定位。

### 唯一政策与校验

- [ ] 引入最小不可变质量政策值对象或既有身份字段扩展，只接受已定义的v1/v2；同时确定 source classification、W1 adaptation、输入政策身份，禁止任意字符串拼装不一致版本。
- [ ] 通过 composition 显式选择并向下传递；没有参数时解析为旧v1。D1/60m拒绝W1 v2，正式41入口保持旧政策，固定19隔离候选才允许v2。不能让普通HTTP参数直接切正式服务政策。
- [ ] Reader的actual-dominant主序列、physical前缀、周快照候选、readiness、auxiliary/reference重放必须共享同一政策。检查 `_quality_source_identity` 中硬编码weekly_quality:v1，避免v2挂v1标签。

### 身份绑定清单

- [ ] ProductIdentity能明确承载输入质量政策，公式版本保持原意；chart/reference元信息可验证政策，旧DTO默认字段/序列化行为有兼容测试。
- [ ] `ProductService` 的 common fact key、section key、chart pagination anchor/proof、in-flight dedup、snapshot token proof 全部绑定质量政策；只在cache键添加后缀不足以解决串用。
- [ ] token在不同政策间双向拒绝；同政策各panel、分页、日周切换回来的请求及刷新前后保证一致。前端迟到响应不能覆盖另一政策。
- [ ] calculation segment、signal/marker、reference及策略恢复stream身份绑定必要质量政策；v2 break自身来源完整，未来追加不能改写旧前缀。
- [ ] 保持v1既有ID和序列化hash payload逐字一致，v1默认值不能无条件进入旧hash；v2使用独立版本命名空间，即使尚未遇到break也不能与v1共享候选参考/缓存身份。
- [ ] 统一Reference P2若尚未集成，先基于当前唯一正式投影传递必要身份并设明确衔接测试；不得复制配对算法、创建替代reducer。触及其活跃共享文件时先固定接口，继续R2/R3安全工作，待接续基线明确再集成复验。

测试须先证明失败再修复：相同品种/策略/as_of/data revision的v1和v2并存；v1→v2及v2→v1错token；缓存命中/失效/并发dedup不串用；无break和有break均隔离；旧D1/41 W1的signal/trade/segment/golden不变；break后重新预热、无虚构退出收益；prefix、batch/step、重启一致。

出口：Reader→策略→Reference→API候选全链可证，才允许浏览器候选矩阵。无法安全完成的精确定位到某个接口/测试，不以“改动较大”收尾。

## 5. R2：20合约冲突做实质诊断

- [ ] 从原始diagnostic取精确物理合约及首冲突周，当前Catalog/MDS只读重复读取，固定cutoff/revision；复用现有聚合用于比较，不产生替代Canonical。
- [ ] 保存同周正常D1与source-quality完整端点、现存W1身份，以及七字段 Decimal逐值差异、周起止/跨月、Session、precision、来源版本/修订、合约归属。
- [ ] 对B/BZ/CJ/EB/EG各类差异归因，必须区分聚合/比较实现缺陷、已存来源修订冲突、元数据不一致及未知。只有代码违反既有合同才自主修复；不能静默放宽精度或删除比较字段。
- [ ] 缺少原来源证据时列SOURCE_VERIFICATION_REQUIRED，准备受控provider查询批次；不因“只是读取RQData”绕过下载授权。
- [ ] 逐合约输出：可代码修复 / 可形成数据修复方案 / 需源查证 / 证据不足保留阻塞。原20合约不可直接全部归为可覆盖。

## 6. R3：独立准备精确数据批次

- [ ] 先J的5个旧缺口合约重新prepare；以当前依赖枚举为准，旧数量/80请求仅作比较。再PG、SI，SR待审项隔离，其余在质量/冲突可判定后接续。
- [ ] 复用ContractWarmupPlanner与已有weekly recovery/campaign；不得绕过input validation、维护锁或新建第二写入链。
- [ ] 批次必须可审：环境/根/代码SHA、数据修订、合约、D1 companion及W1频率、完整周窗口、分区、计划hash、预算、source异常停止、幂等、前像/恢复和独立回读。仅有清单或旧hash不能请求apply。
- [ ] 真实下载、Canonical/Catalog及生产DB写入仍需明确批次授权；本轮“安排开发”不授予数据写入。等待期间继续R1/R2和可读输入候选验收。记录生产失败后停止受影响mutation，授权恢复范围外不重试。

## 7. R4：固定57组合与交付

- [ ] 复用隔离candidate preview身份校验，固定19列表、W1 v2政策；不改正式41清单、不开放60m/explanation。隔离端口须空闲，不复用或重启Runtime。
- [ ] 数据修复授权未到时先验现有数据并保存57格终态，阻塞/未检如实标明，不伪造页面成功；获批修复后刷新一致快照再做完整矩阵。
- [ ] 分别记录DATA_READY、STRATEGY_READY、PAGE_PASS、合法WARMING/DATA_INTERRUPTED、BLOCKED、UNTESTED；57分母始终保留。默认首载不传固定as_of绕过快照；冻结API截点证据与默认页面证据分列。
- [ ] 本地浏览器串行、单次导航、独立context，finally写已完成/中断/未检结果；429/浏览器退出和真实源失败分开，不能覆盖首尝试记录。
- [ ] 独立Review后修正确认问题，再相关回归、OpenSpec/格式/secret检查；仅在代码/版本隔离/实际范围满足时commit/push并集成develop。已能独立交付且默认不开候选的安全代码不必等待所有数据补齐；集成时明确EXTERNAL_GATE_PENDING。
- [ ] main/tag/release、Runtime切换、正式开放、通知和自然盘后/周审计不包含本轮授权。第二项自然接续保持待验，第一项41正式首载不能冒领完成。

## 8. 验证命令与交付标准

入口先核实存在，复用实际Python环境：

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/data_foundation/test_weekly_quality.py \
  services/quant-api/tests/data_foundation/test_catalog_and_service.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_weekly_snapshot.py \
  services/quant-api/tests/newow/test_product_snapshot_cache.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_reference_trades.py
```

身份/cache/adapter相关新增反例优先；涉及恢复器增加其定向测试；Web改动按TESTING.md执行unit/typecheck/build和真实浏览器证据。不要仅复制旧测试数。

交付一份接续报告：已完成代码与commit、实测命令、Review结论、20合约归因表、当前精确数据批次、57矩阵、未完成项/不可实现原因/解锁条件。代码完成不代表数据完成；清楚区分当前不可行与尚未实施。
