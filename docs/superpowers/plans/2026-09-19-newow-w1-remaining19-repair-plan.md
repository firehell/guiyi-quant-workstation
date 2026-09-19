# 牛哇 W1 剩余 19 品种修复与 57 组合验收方案

> 执行方式：一个 Terra medium 开发任务，按 superpowers:executing-plans 顺序实施；共享时序、质量、身份和数据提交变更做独立 Review。仓库 AGENTS.md 优先；不因技能重复请求已授权的工程开发许可。

**Goal:** 修复已证实的工程缺陷，按实际缺口准备并在明确授权后执行数据批次，使固定 19×3=57 组合全部有真实验收结论；可用、合法预热、中断、来源不足和阻塞都如实记录，不强求 57 READY。

**Architecture:** 复用 RQData → Canonical/Catalog → MDS → Newow reader → 三策略/ReferenceTrade → Web。质量处理复用现有 SourceQualityFact 与 weekly_quality；W1 新质量语义先作为显式版本的隔离候选验证，不扩大旧 D1 或正式 41 品种合同。没有第二套 resolver、行情存储或数据写入脚本。

**Tech Stack:** Python、SQLAlchemy、Canonical Parquet、现有 Newow 纯域、Vue/TypeScript、pytest、现有浏览器验收工具。

**Spec:** 本文“设计决策与合同”是本任务设计；同时遵守 `openspec/specs/newow-product-reference-trading/spec.md`、`openspec/specs/canonical-market-storage/spec.md`、`docs/DATA_CENTER.md`、`AGENTS.md`。本文中的候选 v2 不视为已晋升的 active canonical。

## 1. 授权、固定范围和证据

用户本轮要求：设计方案并交给一个 Terra medium 会话开发，完成方案后推进第四步的数据修复与 57 组合验收；不能实现的记录原因，不强行实现。已授权代码、隔离测试、只读诊断、prepare、隔离开发预览、Review 和满足条件的 develop 集成。

真实 RQData 请求/下载、Canonical/Catalog 或 production DB 写入尚未授权。提交精确批次后等待对应授权；其间继续独立安全工作。main/tag/release、Runtime 切换、通知及 Scope 变更均不包含在本任务。

固定品种：`B BZ CJ EB EG J OI PF PG PK PL PR PX RS SF SH SI SM SR`。
三策略：`trend / oscillation / main_rise`，频率仅 `1w`。1d 仅作为 W1 权威来源与回归面，不能顺带扩大 D1 策略质量语义；60m/explanation 不开放。首批 41 品种范围保持原样。

设计核对基线为 develop@a23475c3d08debabc416f1300c8b58e0984c7ab4；正式 Runtime 为 v1.10.17@305cf36b94121dff37d6ce280f98869d979a2b8b。执行前刷新 STATUS、分支、HEAD、dirty state、其他 worktree 和依赖；不能用本段替代现场。

本任务输入证据位于主工作树的绝对目录：
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining19-20260919/`。
这些文件当前尚未提交，新 worktree 必须从该路径读取；需要纳入交付的紧凑证据复制进本任务目录，并记录原始来源/哈希，不覆盖主树原文件。

必读：`report.md`、`audit-identity.json`、`readiness-full.json`、`summary.json`、`unknown-diagnosis.json`、`unknown-diagnosis-develop.json`、`integrity-diagnosis.json`。

审计截止 `2026-09-18T07:00:00.000001+00:00`，Catalog 修订 `e8450448b08f833ee7f4990856dc9f9937c35aa3fad040c89e172526e3ffa64c`，前后相等；784 条消费依赖含重复 owner/不同 cutoff，不能当物理合约数量。154 READY、20 N/A、500 缺口、40 完整性冲突、8 来源异常、62 UNKNOWN；正式 W1 57 项 UNOPENED。原生报告 incomplete，未耗尽预算，零 provider/写入。

已复现：
- 62 UNKNOWN 去重 31 个合约/截止依赖。旧 reader 在 PriceUnavailableFact.from_record 失败；develop 30 项 SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED、OI2609 一项 REPLAY_ENDPOINTS_MISSING。不是 31 个都应重新下载。
- 20 个冲突合约：B 7、BZ 3、CJ 8、EB 1、EG 1。现存 W1 != D1 完整周聚合，尚未证实哪一侧事实错误。
- CJ2305、RS2309、RS2311 存在 SOURCE_NONPOSITIVE_PRICE。不得当普通缺口或 NO_TRADE。
- 原生 151 项 PROPOSED、91 项 REVIEW_REQUIRED；前者估算 2826 请求。不是全量预算，不是写入授权，旧 plan hash 在刷新后必须重新校验。

## 2. 设计决策与合同

### 2.1 选择分流修复，拒绝“一键重下全部”

普通端点缺口用已有 warmup/planner/recovery 链；来源质量事实走显式质量语义；W1/D1 冲突先取证。只改能力列表、降低预热阈值、回退旧快照、缩短窗口或重下全部都不能证明修复，均不采用。

### 2.2 非正价格的 W1 候选语义

复用 `NonpositiveCloseFact`，不复制类型、不修改有效行情定义。仅在 W1 专用显式 opt-in 查询中消费 `ValidCanonicalBar | PRICE_UNAVAILABLE | NONPOSITIVE_CLOSE`，保留旧严格查询和 D1 Newow/SuBing 各自边界。

允许生成“中断证明”的必要条件：
1. 固定物理合约、Calendar/Session、完整 ISO 周及已确认 cutoff；周内每个预期 D1 端点都被正常 Bar 或来源可验证质量事实互斥且完整覆盖。
2. 每条事实有正确日期/合约/来源证据、request/response hash、分类版本；缺证、未知类别、重复、交叠、Map/Session 不足都阻塞，不转成中断。
3. 任一非正价事实使该完整周不可用于计算，生成一个类型可追踪的 W1 break；不合成 W1 OHLC，不把零价当 NO_TRADE，不通过吞掉异常继续计算。
4. break 只在完成周端点生效，之后重建 calculation segment、独立重新预热；ReferenceTrade 在 break 处中断，无虚构清仓 Marker/退出价/收益，不与下段配对。
5. 同一周同时存在有效 W1 Bar 与质量中断证明时仍显式冲突，先诊断并取得数据处置授权，不能在 reader 中静默忽略现存 Bar。
6. 中断身份绑定已知源事实和前置 break，不受未来数据或 owner 终点延长改写。prefix、batch/incremental、restart 一致。

拟用独立 W1 质量版本 `weekly-d1-quality-v2`、W1 adaptation `newow_futures_weekly_quality_segment_v2`；实施前检查无命名冲突。版本绑定快照、缓存、计算区段与参考身份；不改变三策略公式，不改变 D1 Trade ID/收益口径。不得仅修改全局常量让旧正式 41 品种静默切换；先用候选政策显式选择，复用同一算法实现。确认晋升后再收敛旧候选配置，避免永久双实现。

这是新 W1 语义的候选设计，允许实现和隔离验证；如与既有 canonical 或源证据存在实质矛盾，停受影响语义并提出具体取舍，继续其他组。不能用本计划宣称 active 合同已批准晋升，不能自动开放正式范围或切 Runtime。

### 2.3 W1/D1 冲突

按异常合约及首个冲突周读取现存 W1 与同周物理 D1，逐项比较 open/high/low/close/volume/turnover/open_interest、端点、精度、质量修订和周边界。比较用 Decimal；区分数值不等、精度/类型、Session/跨月归属、来源修订、存储身份等，不以某侧“更方便”判权威。

W1 仍为 RQData 直接事实；D1 聚合用于一致性验证，不直接替代来源 W1。仅当原来源 evidence 足以证明原因时形成精确修复建议；需要新 provider 比较则作为 source-verification 批次单独申请，不能藏在只读审计中。

### 2.4 隔离 57 组合验收与失败记录

复用已有 candidate preview 的 checkout/identity 校验，增加本任务固定 19 品种 W1 候选范围；隔离端口、只读 DB，无 Runtime/通知能力。正式 v8/41 清单及默认页面保持原值，禁止 monkeypatch 正式开关或绕过正式入口制造通过。

57 项分母固定，逐项保存：品种/策略、code SHA、as_of、data revision、物理合约/区段、质量政策、主图/辅助/reference/comparator、页面结果、阻塞及下一动作。分别统计 DATA_READY、STRATEGY_READY、PAGE_PASS，不能一个 PASS 混用。合法 WARMING/DATA_INTERRUPTED 可以是正确页面状态，不能记成 STRATEGY_READY。源不足/不可解决显式 BLOCKED 或 DATA_INSUFFICIENT，记录证据、原因、未来解锁条件。

## 3. 执行步骤与出口

### P0 基线、候选合同与冻结复现

- [ ] 新独立工作树先核对并对齐当前 develop；保留其他任务修改。若从 main 创建，用正常分支/合并方式接入 develop，再核对任务依赖。
- [ ] 读取现有数据 canonical、新 SuBing D1 opt-in 合同及原 W1 质量合同；在同一计划记录候选合同差异、版本和取舍，不改成 active 完成。
- [ ] 将上述三个真实问题各转成最小脱敏 fixture 回归；fixture 只证明代码，不替代生产验收。
- [ ] 运行必要只读样本复现，记录当前 SHA、修订及与本报告差异；不要首先重跑全仓或重新下载。

出口：已知异常有可复现分类；其余未知有明确待查项，不误记成零缺口。

### P1 W1 质量候选与可解释诊断

主要落点：
`services/quant-api/app/market_data/source_quality.py`、`weekly_quality.py`、`market_data_service.py`、`newow/product_reader.py`、`newow/readiness.py`、`newow/public_errors.py`；必要的身份/adapter/reference 落点在 `packages/quant-core/guiyi_quant/newow/`，不顺带重写统一参考交易框架。

- [ ] 先写反例：新质量事实不再暴露 INTERNAL_ERROR；旧严格入口继续拒绝未支持类别； malformed/unknown 仍阻断。
- [ ] 实现 W1 opt-in 完整端点质量证明和候选 v2 身份；D1 接口不顺带扩围。
- [ ] 覆盖混合两种异常、一周多缺价、未完成周、夜盘、节假日短周、跨月、合约切换、冲突 Bar、零价 NO_TRADE 区分、缺失 evidence。
- [ ] 覆盖三策略 break 后预热、开放参考中断、无退出收益、跨段不配对及 prefix/incremental/restart。
- [ ] 检查 D1 与首批 41 正式 v1 结果不变；新增候选 v2 的有意身份变化独立记录。

出口：工程测试通过、错误明确；质量证明不足品种仍阻塞。

### P2 冲突诊断与精确 prepare

复用 `ContractWarmupPlanner`、`scripts/newow_weekly_recovery.py`、`scripts/newow_weekly_recovery_campaign.py` 和现有验证链；只有当前工具无法表达已查明问题时才作最小局部扩展。

- [ ] 完成 20 合约逐字段只读对照及来源判定。无法判定的记 SOURCE_VERIFICATION_REQUIRED，不自动选边。
- [ ] 刷新 19 范围的 consumer dependency/repair 结果，保留原始报告。记录请求频率 W1 及实际 D1 companion 写入范围。
- [ ] 先准备 J 的小批次，再 PG/SI；SR 混合项独立。其余按“质量已证明”“冲突已查明”“仍阻塞”分组，不按旧 151 清单直接 apply。
- [ ] 批次包含精确品种、合约、频率、完整周跨月窗口、目标分区、配置/Canonical 身份、代码 SHA、当前 revision、plan hash、请求数/流量预算、源异常停机规则、幂等、失败恢复和写后回读。
- [ ] 覆盖/删除须提供当前活动分区前像、影响、dry-run、可验证恢复方法和保留期限；不能伪造已有备份。prepare 不触碰生产写入。

出口：具体可审核批次；PROPOSED 不是执行许可，REVIEW_REQUIRED 不可直接 apply。

### P3 完成第四步：受控修复及真实 57 矩阵

- [ ] 完成代码、局部测试及只读准备后向 owner 提交批次，明确仅批准下载或同时批准 Canonical/Catalog 发布的差别；等待精确授权。
- [ ] 等待期间完成不依赖真实写入的候选接口、页面状态测试、已有可读输入的真实矩阵，不能因一项 Gate 停所有工程工作。
- [ ] 授权后先 fresh preflight/锁/hash 校验，再按批次串行执行；结果不明先只读核对，未明确授权的 retry 不执行。不得补发通知或触发 Runtime。
- [ ] 写后独立回读每个合约活动身份、覆盖、完整周、D1 companion 变化、来源质量、幂等与 W1 consumer；保留原始失败及后续成功，不覆盖。
- [ ] 以同一可验证修订完成 19×3=57 主图/辅助/reference/comparator 矩阵。默认首载不带固定 as_of 绕过快照；API 的冻结截点验收另列，核对 token/截止一致。
- [ ] 浏览器严格串行、每页独立上下文、单次导航；原脚本会因浏览器退出未生成 summary，须用 try/finally 保存终态和未检分母。本任务受限时间/预算时保留未检，禁止缩分母凑通过。
- [ ] 既有41 W1与60 D1按共享影响做回归；公网、本机正式部署首载及自然任务证据不以隔离页面替代。

出口：57/57 有明确实际终态或明确未检/外部 Gate；不可实现项留在分母。没有下载授权时不能宣布数据修复完成。

### P4 Review、集成和交付

- [ ] 高风险质量/时序/版本/写入边界由独立 reviewer 审查；按 Confirmed Issue / Risk / Optional 分类，修正后定向复验。
- [ ] 与并行“统一参考交易 P2”“牛哇算法显示”改动逐文件对齐，不复制 reducer 或公共 resolver。必要时只提交自己文件，禁止 git add -A。
- [ ] 可独立交付且保持正式范围的工程代码通过 Review 后 commit/push，并在无冲突条件下集成 develop；候选语义不能冒充正式开放。未确认的重要合同取舍保持待决。
- [ ] 一个报告汇总工程、数据、57 矩阵、不可实现原因和 pending Gate；不提前更新 STATUS 为 READY。main/tag/Runtime 另授权。

## 4. 验证入口与评审重点

先检查文件实际存在，再按改动运行：

```bash
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q \
  services/quant-api/tests/data_foundation/test_weekly_quality.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_weekly_snapshot.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/newow/test_reference_interruptions.py
```

修改恢复器增加 `test_weekly_recovery.py`、`test_weekly_recovery_campaign.py`；身份/参考变更增加 reference_trades/statistics、daily_snapshot 及实际相关 core 测试；API/Web 变更按 TESTING.md 定向 unit/typecheck/build/E2E；canonical 变更执行 OpenSpec 校验、secret scan 和 `git diff --check`。测试数量不预先写成结果。

重点反例：1）旧 Runtime 不能解析新事实但 health 仍 ok；2）W1 与 D1 都可读但数值冲突；3）已存 W1 和已证实质量中断并存；4）未知端点被误作质量 break；5）数据修订变化后沿用旧 token/plan；6）中断前后参考串段或未来追加改写旧身份；7）浏览器退出/429/未检被误计通过；8）候选范围泄漏到正式 41 或 D1。

## 5. 无法实现时如何收口

不把“做不到”作为跳过证据的理由，也不强求实现：记录具体失败入口、合约/日期、错误码、复现证据、已排除原因、剩余依赖和解锁条件；区分临时缺证、来源真实不可用、合法样本不足、未批准语义和明确不支持。对不可用窗口不造 Bar、不产生收益、不隐藏失败。允许部分品种完成，其余阻塞；最终报告固定 19/57 分母。

最近自然运行的等待项与首批 41 正式首载证据缺口属于独立任务，本任务不冒领完成，不要求它们先完成才能开发剩余 19。
