# J 分钟历史产品闭环

2026-09-28：沿用 I 的 **5m/15m/30m/60m × 趋势/震荡/独立双策略**，固定分母 12。1m 仅可信聚合输入，Newow 1m 显示与策略产品留独立版本；通用 Market/HTDY 1m 不变。其他品种、正式发布及 Runtime 不在本轮。

## 身份与数据

数据维护及资产构建冻结 `60ffc5ba1dd47b170c4d1d091f77fc731694ad32`；最终 UI 请求顺序和分页保持修复冻结 `90c9808a51387b4926748bbef851a17a5471633d`。仅五个 Web 文件变化，后端、公式和资产语义未改；保护源码逐 blob 比较，当前来源与保存结果只读复核。独立工作树 `/Volumes/扩展盘/worktree/j-minute-closeout/guiyi-quant-workstation`。API 8012、Web 5178 同为新 SHA，复用 I 候选端口，仅停止经 PID/命令/cwd 精确核对的 I 两个预览进程；I 资产、证据及工作树保留，RB/HC 与正式服务不变。只读、固定 as_of、realtime=false。

历史窗口 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`，分钟近一年下界 2025-09-25。12 个 rank1 owner：J2305、J2309、J2401、J2405、J2409、J2501、J2505、J2509、J2601、J2605、J2609、J2701。

1m/15m/30m/60m 各 141 个分区，5m 原有 56 个。实际执行 **96 个 5m 派生维护目标**，12 单位全部 READBACK_VERIFIED、零 provider；plan SHA256 `b3144c1f073cc0cad8b49e9c53f88846ef04cbd1d075e9e767dd30dabc185ef5`。独立 Review 逐文件重算 197 个前像（141 源1m、56 旧5m）；精确 product/contract/截止/上市预热、维护锁、一次性 durable attempt、原子发布与失败停止保护保留。1m 与其他周期未重写。

完整物理 Session `(start,end]` 前缀逐值重算 **141 个 contract-month、179,310 根 5m Bar**，Decimal OHLCV/turnover/OI 一致。旧九条 15m/30m/60m 资产在当前来源哈希与七项保存身份一致后复用。5m 新建两基础流与一融合流，仅写既有 `newow_intraday_pilot_20260927` 隔离 schema；基础构建 167.039 秒、融合 57.74 秒。每条回放 179,321 项，即 179,310 根行情与 11 个换月边界事件。

## 当前验收

最终 `90c9808`：十二组合 API READY，152 个实际 GET 全部 HTTP200；十二个 Chrome 页面功能检查通过，322 个实际浏览器响应全部成功，root 审阅 12 张主图/辅助及 12 张完整累计曲线原图。实际同日参考分页 3 PASS、9 NOT_APPLICABLE；其余按无下一游标或真实跨交易日保留，不改分母。四个双策略分页均从 50 条追加至 100 条；30m、15m 经主图加载更早后仍保持追加记录，旧 NOT_RUN 未改写。

日周六模式兼容回归和 112 个实际响应通过，root 另审阅 12 张原图；日周六项趋势转折均如实披露 WARMING，周线当前合约 35 根未达到 120 根，不以绿灯掩盖。实际 pending request 取消、约 0.253 秒客户端 AbortError 超时及返回 5m 恢复通过，root 审阅恢复原图。错频旧快照两次 HTTP409 拒绝，随后新 15m 图表/参考使用同一新 token READY。最终独立 Review 核对 37 张原图 SHA、实际响应、分页与失败保留通过，无 Confirmed Issue；J **12/12 历史候选闭环完成，允许集成 develop**。

日周兼容最初三次周线双策略真实 HTTP429 及第一修复 `eb2b520` 的分钟分页回归均保存。根因是另一策略参考与融合竞争固定重型队列，以及等待状态导致面板卸载。最终稳定挂载面板，只延后首次或新身份请求；保留运行 1、等待 2、等待 5 秒预算、同身份分页记录、新身份清理、取消与旧回包隔离，不增加自动重试、不改变公式。旧失败与新成功分别绑定源码身份。

## 实际验证

- 最终冻结版本 `python -m pytest services/quant-api/tests/newow/test_candidate_preview.py outputs/j-minute-closeout-20260928/test_maintenance.py -q`：73 passed in 1.94s；其中包含 9 项 J 维护约束测试。初次 60ffc 测试日志也保留。
- 最终 UI 修复定向 18 passed；完整 `pnpm -C apps/quant-web test` 754 passed、1 skipped、0 failed；typecheck/build 通过。独立 Review 实际另跑五个相关测试文件，112 passed；真实 Workspace 模板与 Panel 渲染回归覆盖等待期间禁发、追加记录保持、换身份取消和晚到隔离。
- `maintain_5m.py --apply --expected-plan-sha256 b3144c1f073cc0cad8b49e9c53f88846ef04cbd1d075e9e767dd30dabc185ef5`：96 target 全部读回，0 provider。
- `aggregation_full_prefix.py`、`source_assets.py` 初始/最终、`base_readback.py` 和两 build 脚本 `--product j --frequency 5m`：实际前缀、来源、构建及保存结果通过；独立实时 PostgreSQL 最终复核已通过：十二条完整 stream/summary、四频当前 source、旧九流复用身份均逐字段匹配，READY/disabled/generation=0/current revision/seq，computed_through 精确为 2026-09-24T07:00:00+00:00。
- 最终五文件 UI 改动之外的 2,457 个 tracked blobs 与 60ffc 完全一致。原始数据/构建证据保留旧身份；最终 `source_assets.py --final`、`api/readback.py --execute`、`snapshot_recovery.py`、`ui-final-transition-readback.py --execute` 实际重新读回，完整来源/资产对象与前一候选相同。独立最终 API、来源、游标和快照 Review 通过。
- `verify_j12.py --execute`、`capture_full_curves.py --execute`、`legacy_regression.capture.py --execute` 和 `regression_recovery.py --kind cancel-timeout --execute` 均为实际 Chrome 操作；保存原始观察状态，以原图 SHA 和独立结果生成最终矩阵。空主图和过时参考窗口负例被严格验收器拒绝。
- 候选启动最初使用错误变量名，独立 Web identity assertion 拒绝；改用 `GUIYI_PREVIEW_CANDIDATE_ORIGIN` 后实际 API/Web 身份通过。失败发生在数据 mutation 前，原失败原因独立保存，不计作通过。

## 边界与恢复

本轮仅历史候选，不发布 main/tag、不切换正式 Runtime、worker、Scope、通知或订单，`auto_order=false` 不变。页面零成本参考收益不代表因果/OOS/账户收益。分钟持有过程曲线沿用明确不可用边界，已完成累计、OPEN 浮动与换月中断分离。

结果不明先只读核对，禁止盲目重试；旧分区及前像保留，不以宽泛路径回滚。J 更早主图分页未实测，不将 RB 历史缺陷当作 J 事实。证据位于 `outputs/j-minute-closeout-20260928/`，不提交原始 DB/API/browser 输出。

最终五文件修复已快进集成 develop；本任务仅提交 J 状态新增与本说明，原有 STATUS 和分钟 roadmap 未提交修改保留，证据 507 个文件逐字节复制校验。J 候选工作树保留用于页面验收；代码恢复采用精确 forward revert，不因恢复页面版本批量覆盖已通过质量校验的数据或资产。
