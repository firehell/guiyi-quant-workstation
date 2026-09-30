# HC 分钟历史产品闭环

2026-09-28：沿用 RB 的 **5m/15m/30m/60m × 趋势/震荡/独立双策略**，固定分母 12。1m 仅可信聚合输入，Newow 1m 显示、策略产品与 readiness 留独立版本；通用 Market/HTDY 1m 不变。主升浪分钟、其他品种、正式发布及 Runtime 不在本轮。

## 身份与数据

- 起点 develop 与冻结业务源码 `e936651187f1e074bf5e1f2205bf22ad03657f30`，无业务代码变更。
- 独立工作树 `/Volumes/扩展盘/worktree/hc-minute-closeout/guiyi-quant-workstation`；候选 API `http://127.0.0.1:8011`，Web `http://127.0.0.1:5176`，只读、固定 as_of、realtime=false；RB 服务不切换。
- 历史窗口 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`；分钟近一年记录下界 2025-09-25。
- 12 个 rank1 owner：HC2305、HC2310、HC2401、HC2405、HC2410、HC2501、HC2505、HC2510、HC2601、HC2605、HC2610、HC2701。

盘点 1m/15m/30m/60m 各 138 个 Catalog 分区，5m 原有 56 个。按 physical owner 有效截止执行 **93 个 5m 派生维护目标**，全部 READBACK_VERIFIED、零 provider。维护 plan SHA256 `8e633bcfc5af7d64e5a44618c76fbdc3067d17badad5c63b77f514e496bc5eba`；前像、旧不可变文件、维护锁、单次 durable attempt、质量及缺口读回保留。1m 输入及其他频率未重写。

同物理合约完整 Session `(start,end]` 前缀独立重算 **138 个 contract-month、173,385 根 5m Bar**，Decimal OHLCV/turnover/OI 逐值一致，包含上市预热月份。15m/30m/60m 九条既有流的 source/hash/revision/generation 与实际当前输入一致后复用；5m 构建两基础流与一融合流。资产仅在既有 `newow_intraday_pilot_20260927` 隔离 schema，不启用 worker。

## 已完成验收

**HC source → assets → API → browser → root 视觉审核 12/12 PASS**，数据维护、构建、实时保存资产、API 与浏览器真实证据已独立 Review。12 条保存流全部 READY、computed_through=`2026-09-24T07:00:00+00:00`、disabled、generation=0。5m 基础构建 167.601 秒、融合 56.209 秒；各计划、一次性 attempt 和完成报告对应。回放输入 173,396 项含 173,385 根行情 Bar 与 11 个换月边界事件，不把事件计作行情。

| 周期 | 趋势 | 震荡 | 独立双策略 |
| --- | --- | --- | --- |
| 5m | PASS | PASS | PASS |
| 15m | PASS | PASS | PASS |
| 30m | PASS | PASS | PASS |
| 60m | PASS | PASS | PASS |

152 次实际 API GET 全部 HTTP200，源/hash/snapshot/保存代次、completed physical 主图、共同 OHLCV、参考曲线、近一年记录、主图与参考游标、融合独立身份及基础来源、辅助状态全部核对。HC-only capability 为 v26；API identity 与 Web 编译模块独立验证冻结 SHA 和截止。正式服务实际 capability 仍仅日周。

真实 Chrome 12 个组合、322 个响应通过，XHR 请求与真实正文唯一绑定；主图、记录、已完成累计曲线、五项辅助、周期/策略离开返回、分页稳定及错误检查通过。root 逐张审核 24 张原始分辨率 main/full-curve 截图，哈希保留。同日分页只计 **3 PASS（60m dual、5m trend、5m oscillation）**；另 3 项无下一游标、6 项实际跨日，保持 NOT_APPLICABLE。API 普通参考同日样本 5 项、融合另 2 项，不能外推所有分页都同日。

实际 pending 请求取消、250ms 客户端超时、返回 5m HTTP200 恢复通过；5m 旧 snapshot 用于 15m 主图及参考分别 HTTP409 `NEWOW_SNAPSHOT_GENERATION_CONFLICT`，fresh 15m 主图/参考同 token 恢复。原探测复用可变参数导致请求记录污染的报告保留为 `snapshot-recovery-param-alias-original.json`；参数副本修正后另做真实 GET，最终报告独立复核通过。取消工具第一次因 API 前置报告未生成而在浏览器调用前停止，日志保留；不把这次前置失败算作取消测试。

HC D1/W1 三模式共六个真实页面完成兼容回归：非空 completed physical 主图、完整已完成曲线、近年记录精确投影、MACD/趋势转折、60m 离开返回及无错误。严格离线复核拒绝空 bars 与陈旧 reference；root 审阅十二张日周截图。三种 W1 趋势转折均保留 `NEWOW_TREND_REVERSAL_WARMING`，不改写为 READY。HC 日线更早主图分页未实测，不沿用 RB 历史缺陷为 HC 事实。

## 实际验证与 Review

全部命令在冻结 HC 工作树执行，Python path 为 `.:services/quant-api:packages/quant-core`；输出保存于本轮 evidence：

- `python -m pytest services/quant-api/tests/newow/test_candidate_preview.py outputs/hc-minute-closeout-20260928/test_maintenance.py -q`：**72 passed in 1.99s**。
- `python .../maintain_5m.py --apply --expected-plan-sha256 8e633bcfc5af7d64e5a44618c76fbdc3067d17badad5c63b77f514e496bc5eba`：12 单位、93 target 读回通过、0 provider。
- `aggregation_full_prefix.py`、`source_assets.py`（初始/`--final`）、`base_readback.py`：实际只读前缀/来源/代次检查通过；两 build 脚本 `--product hc --frequency 5m` 完成；独立 Review 强制 read-only PG 查询与最终 12 资产完整对象逐字段一致。
- `api/readback.py --execute`、`browser/verify_hc12.py --execute`、`capture_full_curves.py --execute`：实际上述 12 API/UI 组合及完整曲线验收。
- `legacy_regression.capture.py --execute`、严格 `legacy_evaluate_final.py`、`regression_recovery.py --kind cancel-timeout --execute`、`snapshot_recovery.py`：真实兼容性/恢复及离线负例复核。

没有业务代码变更，复用已验 e936 的 v26 子集能力；未重复运行与 HC 数据验收无关的全量代码/构建套件，不将历史测试改写为本轮结果。

独立分工：rb_review 审维护/构建/当前 PG 数据；rb_backend 审工具、152 API GET、322 UI 响应与快照补测；rb_web 审日周严格判定工具与负例；root 审全部截图。原始观察文件保留，最终 `browser/matrix.json` 单列视觉结论，未覆盖失败或 NA。

## 边界与恢复

本轮仅历史候选，正式 v1.10.39、日周正式入口、Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变。页面零成本参考收益不代表因果/OOS/账户收益。分钟持有过程曲线沿用已有明确不可用边界，已完成累计、OPEN 浮动与换月中断分离。

维护与资产若结果不明只读核对，禁止自动重试；旧分区及前像保留，不以宽泛路径回滚。HC 日线更早主图分页未在本轮单列实测，不把 RB 的历史缺陷当作 HC 新证据。

证据位于 `outputs/hc-minute-closeout-20260928/`，不提交原始 DB/API/browser 输出。
