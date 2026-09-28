# I 分钟历史产品闭环

2026-09-28：沿用 RB/HC 的 **5m/15m/30m/60m × 趋势/震荡/独立双策略**，固定分母 12。1m 仅可信聚合输入，Newow 1m 显示与策略产品留独立版本；通用 Market/HTDY 1m 不变。其他品种、正式发布及 Runtime 不在本轮。

## 身份与数据

起点 develop `5a2dbfc9d12b4c789c14a4dbc8857a7cabe43106`；冻结候选业务源码 `604a338ee3836f82505fde8c79f0d3e69b3a2f43`，仅增加第三组固定本地候选端口，已快进集成 develop。独立树 `/Volumes/扩展盘/worktree/i-minute-closeout/guiyi-quant-workstation`，API 8012、Web 5178，GET-only、固定 as_of、readonly、realtime=false；原 RB/HC 服务保留。

历史窗口 2023-01-01..2026-09-24，as_of `2026-09-24T07:00:00.000001+00:00`；近一年记录下界 2025-09-25。12 个 rank1 owner：I2305、I2309、I2401、I2405、I2409、I2501、I2505、I2509、I2601、I2605、I2609、I2701。

1m/15m/30m/60m 各 139 个 Catalog 分区，5m 原有 55 个。精确执行 **94 个 5m 派生维护目标**，12 单位全部 READBACK_VERIFIED，零 provider；plan SHA256 `79da93880d397cc429d3b2dc8b31dd63795d7da6ade3a1fd5128cd1495c731d9`。194 个前像逐文件哈希核对、旧不可变文件、维护锁、一次性 durable attempt、质量与缺口读回保留。1m 与其他周期未重写。

完整 Session `(start,end]` 物理前缀独立重算 **139 个 contract-month、173,286 根真实 5m Bar**，Decimal OHLCV/turnover/OI 逐值一致，包含上市预热。15m/30m/60m 九条旧流的当前 source/hash 与七项保存身份完全一致后复用；5m 新建两基础流与一融合流，资产仅写既有 `newow_intraday_pilot_20260927` 隔离 schema。基础构建 171.387 秒、融合 57.445 秒；每条回放 173,297 项，由 173,286 根行情 Bar 和 11 个换月边界组成。

十二条保存流独立实时 PostgreSQL 只读复核，与最终 stream/summary 逐字段一致；全部 READY、disabled、generation=0、当前 revision/seq 匹配，computed_through 精确为 `2026-09-24T07:00:00+00:00`。

## 验收

**I source → assets → API → browser → root 视觉审核 12/12 PASS**。四周期各三个模式均通过；实际 152 次保存 API GET 全部 HTTP200，源码/as_of/source/physical/snapshot/保存代次、主图与参考游标、融合独立身份与基础来源逐项核对，杯柄保持 NOT_APPLICABLE。

真实 Chrome 十二组合保存 **325 个响应**，主图、记录、已完成累计曲线、五项辅助、周期/策略离开返回、分页稳定与错误检查通过；root 逐张审阅 **24 张原始分辨率 main/full-curve**，精确哈希绑定。浏览器同日续页 **2 PASS（5m trend、dual）**，另 10 项按真实无游标或跨日保持 NOT_APPLICABLE。API 普通参考另有 9 个同日、3 个跨日样本，融合 4 个同日；不能混为所有 UI 分页通过。原始观察仍为 OBSERVED_NEEDS_VISUAL_REVIEW，最终 matrix 单列实际视觉结论。

实际 pending 请求取消、250ms 客户端超时与返回 5m 后 HTTP200 页面恢复通过；原始功能观察保留，root 原图审核以独立 final 哈希绑定。

D1/W1 六页实际兼容观察与 112 个真实响应完成独立审核，主图、完整累计曲线、近年卡片、辅助及 60m 离开返回通过；root 逐张审阅十二张原图并绑定哈希。严格离线复核拒绝空 bars 与陈旧 reference。三种 W1 趋势转折均保留 `NEWOW_TREND_REVERSAL_WARMING`（35 < 120），未伪报 READY。I 更早主图分页未实测，RB 历史缺陷仅背景。

实际跨周期快照恢复完成：5m 旧 token 用于 15m 主图与参考均返回 HTTP409 `NEWOW_SNAPSHOT_GENERATION_CONFLICT`，fresh 15m 同 token 主图/参考恢复；每次请求使用独立参数副本。

## 源码与验证

源码仅改 `services/quant-api/app/preview.py`、对应候选测试、`apps/quant-web/previewProxy.ts`、`vite.config.ts` 和候选测试。第三候选固定 API8012/Web5178，保留旧端口行为、strictPort 与 GET-only/路径/loopback/Host/upgrade 防护，不改数据或策略公式。

- 候选后端与维护定向：`python -m pytest services/quant-api/tests/newow/test_candidate_preview.py outputs/i-minute-closeout-20260928/test_maintenance.py -q`：73 passed in 2.09s。
- Web 候选：`pnpm -C apps/quant-web exec node --test tests/candidatePreview.test.ts`：14 passed；完整 Web 测试：746 passed、1 skipped、0 failed；补跑标准 `pnpm -C apps/quant-web test` 并保存可审计日志（747 total，5.778s）。
- `pnpm -C apps/quant-web build`：类型、Vite 与 bundle topology 通过，保留既有 ineffective_dynamic_import 提示。
- root develop 集成后同候选后端 64 passed in 1.99s、Web 候选 14 passed；`git diff --check` 通过。误用未安装 vitest 的前置命令失败日志保留，改用仓库 node:test 正式入口，不计作通过。
- 数据维护、完整前缀、初始/最终 source assets、基础/融合构建及独立 PostgreSQL readback 均保存实际命令、报告、一次性 attempt。

独立 Review：rb_review 实际只读 PostgreSQL 与当前四频来源、维护/构建证据逐字段核验；rb_backend 复核 152 API、325 XHR 真正文绑定、分页 NA、快照与取消恢复、最终矩阵；rb_web 复核日周严格判定及实际负例、最终文档与哈希；root 亲审全部原图。无 Confirmed Issue，允许集成 develop。

## 边界与恢复

本轮仅历史候选；正式 v1.10.39 capability 实际仍仅 1d/1w，Runtime、worker、Scope、通知、订单及 `auto_order=false` 不变。页面参考收益不代表因果/OOS/账户收益。分钟持有过程曲线沿用明确不可用边界，已完成累计、OPEN 浮动与换月中断分离。

结果未知只读核对，禁止盲目重试；旧文件及前像保留，不以宽泛路径回滚。证据 `outputs/i-minute-closeout-20260928/` 不提交原始 DB/API/browser 输出。
