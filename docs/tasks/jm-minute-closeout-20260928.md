# JM 分钟历史产品闭环

2026-09-28：JM **5m/15m/30m/60m × 趋势/震荡/独立双策略，12/12 历史候选闭环完成，独立 Review PASS，允许集成 develop**。1m 仅可信聚合输入，Newow 1m 显示与策略留后续独立版本；通用 Market/HTDY 1m 不变。本次按问题影响补跑局部验证，不重复全量检查。

## 身份与数据

冻结源码 `a9f3ab4a20bfbdecf3cd1cecebed1642a8da41b2`，已含前序 J 页面修复；产品源码、公式和收益合同未改。复用空闲工作树 `/Volumes/扩展盘/worktree/i-minute-closeout/guiyi-quant-workstation`，任务分支 `fix/jm-minute-5m-closeout`，保留 I 证据。JM 只读候选 API 8012/Web 5178 接替经 PID/命令/cwd 核对的 J 两个预览进程；旧 I/J 资产、证据和工作树保留。固定 as_of、realtime=false，不切换正式消费者。

历史窗口 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`，分钟近一年下界 2025-09-25。12 个 rank1 owner：JM2305、JM2309、JM2401、JM2405、JM2409、JM2501、JM2505、JM2509、JM2601、JM2605、JM2609、JM2701。

1m/15m/30m/60m 各 140 分区、5m 原有 55 分区。精确维护 12 单位、95 个 5m 派生目标，全部 READBACK_VERIFIED、progress COMPLETED、零 provider/direct target。计划 SHA256 `4a505572c312d9b2f3d7aa874482e577cd8e5dbf330304b0d770b63089b97786`；独立核对 195 个原始分区 SHA，源 1m 和其他周期未重写。任务维护脚本只修复首次 mkdir 后缺少父目录 fsync 的持久化缺口，增加对应局部测试。

完整物理 Session `(start,end]` 前缀逐值重算 **140 个 contract-month、176,205 根 5m Bar**，Decimal OHLCV/turnover/OI 与同物理合约可信 1m 聚合一致。旧九条 15m/30m/60m 保存流在当前来源与完整 stream/summary 身份一致后复用；5m 新建两基础流、一融合流，仅使用既有隔离 schema `newow_intraday_pilot_20260927`。每流原计划 176,216 个回放输入；基础构建 159.788 秒、融合恢复构建 63.495 秒。最终十二保存流 READY/disabled/generation=0/current revision/seq，computed_through 精确为 2026-09-24T07:00:00+00:00。

## 意外退出后的恢复

原融合 attempt 保持 PENDING/retry_allowed=false；原计划 SHA256 `92c93f5f9d9dffcbc2d0c4ebaeff942ade9e5c049a364554c247a253289d352d`。退出后首次最终来源检查失败 STREAM_MATRIX_INCOMPLETE，该失败与原 attempt/plan 均原样保留。

只读核对原进程不存在、精确 stream/revision 不存在、六张资产表该 stream 全部零记录，无持久化 checkpoint；独立 Review 验证零写入证明。受控 `recover_fusion_zero_write.py` 用原始 plan_from_dict，校验来源 token、依赖、计划和证据 SHA、源码身份，在维护锁内重新确认六表零写入，再以 O_EXCL 创建独立恢复 attempt，调用既有服务执行原计划。没有伪造 ResumeToken、重置原 attempt、重新调用原融合 build 或删除资产；恢复 exit0/COMPLETED，最终 PostgreSQL 只读复核十二流通过。结果未知时禁止盲目重试，恢复依据必须重新证明。

## 实际验证

以下脚本均位于 `outputs/jm-minute-closeout-20260928/`，实际执行日志、原图和报告保留在本机，不提交原始输出。

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest outputs/jm-minute-closeout-20260928/test_maintenance.py -q`：**10 passed in 0.87s**；独立 Review 另跑同十项通过。产品源码未改，不重复前序全量 Web/build。
- `maintain_5m.py --apply --expected-plan-sha256 4a505572c312d9b2f3d7aa874482e577cd8e5dbf330304b0d770b63089b97786`：95 target、12 单位完成读回、零 provider；`aggregation_full_prefix.py` 全物理前缀一致。
- `source_assets.py --final`、`base_readback.py`、`recover_fusion_zero_write.py`、`independent_final_pg.py`：来源四频/十二 owner、三条新流、九条旧流复用与保存结果通过。独立 PG 核对使用只读事务，不重复 MDS 前缀计算。
- `api/readback.py --execute`：**12 READY，152 个实际 GET 全部 HTTP200**。`snapshot_recovery.py`：两个错频旧 token 实际 HTTP409，随后新 15m 图表/参考同一新 token READY。独立最终 API Review PASS。
- `browser/verify_jm12.py --execute`：**12 个真实 Chrome 组合通过、325 个实际响应**；主图、辅助数值、参考记录、累计曲线、切换返回及错误状态通过。`capture_full_curves.py --execute` 仅补齐完整曲线原图视口；root 审阅十二主图与十二完整曲线原图，原始观察状态保留，`finalize_matrix.py` 生成十二项 PASS。
- 同日参考分页 **4 PASS/8 NOT_APPLICABLE**，按真实无下一游标或跨交易日判定，固定分母仍为十二。四个双策略周期均实际从 50 追加到 100 条，旧前缀保持、100 身份唯一；主图加载更早不重置记录或曲线。
- 日周真实六组合兼容回归 **112 个响应通过**，严格验收器拒绝空主图/过时窗口负例；root 审阅十二原图。D1 趋势转折可计算；W1 当前合约 35 根不足 120 根，在三模式如实披露 WARMING。
- `regression_recovery.py --kind cancel-timeout --execute`：实际 pending 取消、约 0.2518 秒客户端 AbortError 超时、恢复 60m 并返回 5m 图表 HTTP200 通过；root 审阅恢复原图。
- 最终独立 Review 核对 **37 张原图 SHA**、真实响应、分页、日周和取消/超时恢复，零额外 API/Chrome/MDS 请求，无 Confirmed Issue，结论允许集成 develop。报告：`independent-final-browser-review.json`、`independent-final-api-review.json`、`independent-final-pg-review.json`、`independent-fusion-zero-write-review-final.json`。

## 边界与交付

本轮完成历史候选闭环，不代表正式分钟开放、main/tag/release 或 Runtime 晋升。正式 API 8000 capability 仍只开放 Newow 1d/1w；正式 v1.10.39、worker、Scope、通知、订单和 auto_order=false 不变。页面零成本参考收益不代表因果/OOS/账户收益；分钟持有过程曲线仍明确不可用，已完成累计、OPEN 浮动和换月中断分离。JM 更早主图窗口分页未测，不用 RB 历史缺陷代替 JM 事实；W1 预热不表述为公式 READY。

本次只向 develop 提交 JM 状态新增及本说明，已有 STATUS/roadmap 修改保留，243 个证据文件复制到根工作区并逐 SHA 校验。候选工作树保留用于当前页面；文档恢复使用精确 forward revert，数据恢复须按保留前像和精确目标核对，不批量覆盖其他资产。最小下一步为按同范围处理 SF。
