# FU 四周期历史候选处理

2026-09-28：P7-01 **DEFERRED_DATA_BLOCKED，0/12 页面闭环**。已完成 FU 精确依赖核对、部分数据修复和失败隔离；未达到候选闭环。独立 Review 允许安全暂缓，下一品种 MA 在其自身 exact plan、预算与存储 preflight 后可继续。本次不创建下一品种会话。

## 身份与范围

会话 `01a0e788-a1d4-7b82-9446-b72f5f4815ae`；目标通过 `get_goal/create_goal` 实际创建，未设置 token budget。冻结 develop 基线和全部生产维护源码 `e09e67930ad63942fecb431cf87cde9e09ade0a6`；从最新 P7 队列推进，不沿用旧板块批次。任务分支 `codex/fu-minute-closeout`，隔离工作区 `/Volumes/扩展盘/worktree/fu-minute-closeout/guiyi-quant-workstation`；开始时 develop 与任务工作区均 clean。原始证据保存在主工作区 `outputs/fu-minute-closeout-20260928/`；本次集成仅为本记录、P7-01、STATUS 和证据目录 ignore，无产品源码/公式变化。

仅 FU `5m/15m/30m/60m × trend/oscillation/dual`，固定 4 输入、8 基础、4 融合、12 页面。1m 只验证可信聚合来源。历史窗口 `max(2023-01-01, 权威起点2004-08-25)..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`。21 个 rank1 owner、21 个物理合约从 FU2305 到 FU2611；完整 owner 日期与生命周期见 inventory/maintenance-dry-run，不缩短物理上市前缀。当前 completed 端点为 `2026-09-24T07:00:00+00:00`。来源使用既有 Catalog/MDS/Canonical reader；保存资产检查仅既有隔离 schema `newow_intraday_pilot_20260927`。

候选端口 8013/5179 仅预留，**未启动**，无 API/Chrome 页面成功证据。现场正式 8000/5173 和其他任务预览未停止或切换。Canonical Arrow schema SHA-256 `679ce5bb0b71aad3cb60bd7dc3c60539b0e08bf6d00e667fd16c6767cb41434a`；实际 schema、URI、文件 SHA、原生计划 hash 统一见 `summary.json` 与各 readback。

## 实际数据结果

初始四频依赖 **3/84 DATA_READY、81 缺前缀**；FU2611 15m/30m/60m 完整，其余失败为 `DATASET_OR_PARTITION_MISSING`。12 项保存流检查全部为空，没有可复用基础或融合资产。只读 dry-run 去重为 196 个 1m 源月、794 个派生月，不触发全品种盘点。

首包 FU2305：原生计划 `ab11cd5ace9da06f716a1af8178ddd56e936911863c956f601f7a9f0203da588`，封装文件 SHA `f0667d72950c2eec9166ba13902364590c93b05d918aae98676cfbe4fb804c1c`。8 个 1m + 8 个 5m 目标成功发布，实际结果报告 8 次 provider 请求；43 个七周期前像未变，新增16分区、完整1m/5m prefix及共享锁读回通过。

剩余 campaign 文件 SHA `d66ebb90953fb1698f59d2a09c4cdb578af50215cc6a1697fa412c5a03a675a4`，预算上限188源月/786派生；依原始缺口只允许已成功补源使后续目标减少，禁止扩大、重试或重置 attempt。FU2305 15m/30m/60m 各新增8派生，provider=0，各单位独立 readback 通过。共 **8源+32派生=40个新增分区**，均为FU2305 2022-05..12；全FU五频 inventory **351→391，原351分区零删除/零改写**。

FU2305 四频各12个月完整物理前缀按历史 Session `(start,end]` 从同合约1m逐值重算：5m 15,381根、15m 5,127根、30m 2,676根、60m 1,563根，Decimal OHLCV/turnover/OI与已存数据一致。不将这一合约的证据推广到其余 owner。最终依赖 **7/84 DATA_READY、77/84仍缺前缀**；四个完整历史输入为0/4，基础0/8、融合0/4、页面0/12。新增/复用 Reference 资产均0。

## 精确失败与隔离

停止在 **FU2309**，owner **2023-04-04..2023-08-11**，维护请求 **5m**（依赖1m），物理前缀窗口 **2022-09-01..2023-08-11**。首个失败目标为 **1m / 2022-09**，7,125个应有端点，精确 **2022-08-31T13:01:00+00:00..2022-09-30T07:00:00+00:00**（上海时间08-31 21:01..09-30 15:00）。错误 `StorageError / ATOMIC_PUBLISH_FAILED`，原生计划 hash `d3e9313b59225e924136a4b8d58ffb79c8c1157fdaead81d31af3ae50a34e9cf`。

`campaign/FU2309-5m-attempt.json` 与 campaign attempt 保持 **PENDING / retry_allowed=false**；失败单位没有 result，未重试、未改hash、未缩窗。新只读事务核对 **49个七周期前像及文件SHA完全相同、零新增、原生dry-run plan完全一致、首目标目录为空、maintenance advisory lock=0**。底层失败发生于 store.publish 返回前，失败单位没有 active Catalog发布；源、目标及旧不可变文件均未被污染。没有修改 metadata/Map、Redis、Scope、Alert、通知、Runtime 或账户。

**预算不伪记为零：** 首包8次为实际结果报告；campaign `provider_requests_known=0` 只计已返回成功单位，FU2305三个派生单位确为零。失败单位没有实测请求计数或响应journal；由原生单月fetch及首目标发布失败路径推断其逻辑源请求为1，但SDK网络次数、失败响应消费字节未记录。失败单位冻结8次请求预算保守保留消费风险，不重置或补发。正确SDK只读接口 `rqdatac.user.get_quota` 于 `2026-09-28T10:52:37.796678+00:00` 实际读回：上限1,073,741,824、已用22,929,872、剩余 **1,050,811,952 bytes**；不借当前余额反推失败消费。

共享存储补充 smoke 使用已验证的FU2305真实6,435根Bar，仅在本任务outputs同盘隔离目录调用既有原子publisher；成功安装、SHA和逐值读回通过，零生产文件/Catalog/provider写入。首次 smoke 的读回对象字段错误保留，后续只读精确SHA URI，未重复publish。证明当前共享writer/文件系统能完成该样本，**不证明FU2309失败响应或根因**。

独立Review核对实际旧文件SHA、差异、源码路径、原生锁/hash及上述smoke/额度：允许安全隔离，无本次已证实的持久共享阻塞。发布失败原因仍 **UNKNOWN**，不能宣称已证明FU专属来源质量问题。下一品种只按自身精确计划、存储及预算preflight继续；若出现同类持续共享失败，停止相关mutation，不连续试写。

## 实际验证与证据

以下脚本均在 `outputs/fu-minute-closeout-20260928/`，使用现有Python环境和冻结隔离源码；私有配置由既有程序加载，未输出凭据。

- `inventory.py`、`dependencies.py`：21owner、84四频完整prefix及12保存流只读核对；`plan.py`：84原生contract-warmup dry-run，零provider/写入。
- `first_unit.py --apply --expected-plan-sha256 f0667d72950c2eec9166ba13902364590c93b05d918aae98676cfbe4fb804c1c`：passed，16发布/8请求；`first_readback.py`：PASS。
- `campaign.py --apply --expected-plan-sha256 d66ebb90953fb1698f59d2a09c4cdb578af50215cc6a1697fa412c5a03a675a4`：3个FU2305派生单位通过，FU2309首目标异常停止，exit1；不表述为全campaign通过。
- `failed_readback.py`、`inventory_final.py`、`dependencies_final.py`：失败单位零写入、全FU40新增/原分区不变、最终7/84/零流/锁释放读回通过。
- `FU_TARGET_FREQUENCY={5m,15m,30m,60m} aggregation_repaired_prefix.py`：四项12个月全前缀聚合PASS；实际脚本逐次运行四个显式周期。
- `publication_smoke.py`：写入outputs隔离样本成功，首次读回字段错误exit1；`publication_smoke_readback.py`：只读精确文件PASS。`quota_current.py`：一次真实额度状态查询PASS、price/metadata calls=0；首次不正确额度接口未发出查询，失败保留。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest outputs/fu-minute-closeout-20260928/test_scope.py -q`：**10 passed in 0.90s**，覆盖范围扩张拒绝、预算、provider身份、durable attempt不覆盖和tuple/JSON表示。
- 独立Review：`independent-review.md`；原始84份plan与目标减少校验、49旧文件实际SHA、全FU差异、聚合及额外隔离/预算证据通过，无剩余Confirmed Issue要求修正后执行。本次无共用产品代码变化，不重复前五品种、全量Web/build或全仓库测试。

`matrix.json` 固定12项全部 `DEFERRED_DATA_BLOCKED`，API/Chrome为 `NOT_RUN_DATA_PREREQUISITE_BLOCKED`。页面、较早主图/记录分页、切换、取消/超时恢复和FU D1/W1兼容读回未运行；不拿JM/J或HTTP200代替本品种验收。`summary.json` 保存当前SHA/schema/URI/hash、资产分母、失败边界与主要证据SHA。

## 恢复与交付边界

保留所有失败attempt、原plan、旧不可变文件和原始证据；没有可证明安全的自动重试路径。FU恢复前须获得新的可验证发布原因/来源证据、核清预算和恢复合同；不删除attempt或换hash绕过失败。已提交FU2305数据不为“回滚”批量覆盖；恢复须基于精确旧pointer/文件前像和新的可验证维护计划。任务文档恢复采用精确forward revert。

本轮只集成精确暂缓记录到develop，不发布main/tag、不切换Runtime/消费者/worker/Scope、不发送通知或交易。目标在安全暂缓、证据和集成交回完成后才标记complete。最小下一步：由总控安排 **P7-02 MA**；当前执行会话不创建或启动它。
