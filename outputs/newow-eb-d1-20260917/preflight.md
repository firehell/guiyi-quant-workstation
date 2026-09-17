# EB 日线候选：生产写入前只读 preflight

预检状态：`COMPLETED`；后续获批执行与候选验收结果见文末。2026-09-17 在 `develop@64882654875b86526104c0dfeceeaed1479fb0c1`、固定业务截止 `2026-09-15T07:00:00+00:00` 对 EB 运行单品种 `newow-readiness --frequency 1d --matrix --compact`，并对下列 19 个物理合约分别运行原生 `contract-warmup` dry-run。预检阶段全部为只读，provider 请求与写入均为 0；本文件本身不是 apply 授权。

审计终态：`complete=true`、`budget_exhausted=false`，45 项日线依赖中 26 项 `DATA_READY`、19 项 `DATA_UNAVAILABLE:DATASET_OR_PARTITION_MISSING`；三策略 main/chart/reference 均暂不可用。修复提案 19 项，均为 `PROPOSED`。原生计划合计 173 个目标月分区、3,480 个目标 Bar 端点、其中 3,349 个待补端点，最多 173 次 RQData 请求。

| 合约 | 物理合约日线窗口 | 目标月 | 目标/待补 Bar | 请求上限 | 原生 plan SHA-256 |
|---|---|---:|---:|---:|---|
| EB2403 | 2023-03-29..2024-02-26 | 7 | 146/139 | 7 | `922aa28d445775b2c85902c48c57d6e1d92787481a61081ce7c336dc99685b32` |
| EB2404 | 2023-04-26..2024-03-18 | 8 | 161/158 | 8 | `2b95180c45252c0d7a4ba4582392bc6e8b5d79bc59b008fec72d360c5298fb5a` |
| EB2406 | 2023-06-28..2024-05-22 | 7 | 138/132 | 7 | `95052051d5fba23e3bfe3511b889b4011d0c25fc29581c8f2f6231434dc06e72` |
| EB2407 | 2023-07-27..2024-06-24 | 8 | 158/151 | 8 | `a5136af08c8ddd5413ed18595434189eca456825ae64b26019cb60267650302c` |
| EB2410 | 2023-10-27..2024-09-20 | 10 | 205/197 | 10 | `38f36672573125416842880825574cb193024b6fc2a9c398cbd913e95855d349` |
| EB2411 | 2023-11-28..2024-10-23 | 9 | 181/175 | 9 | `4450ee1edb8c20d946183b2223714ad9663b910b32a0f814b36bb54f5dd10116` |
| EB2412 | 2023-12-27..2024-11-21 | 10 | 199/193 | 10 | `28a725335b7ebeed5308174a3557ca81a54ef5fe0ae0acc9afccee127b0dfa4e` |
| EB2502 | 2024-02-27..2025-01-16 | 9 | 184/177 | 9 | `d7d719524921a1ac2151baf2d0f850bf9dd069d2a23bec0ab231402f92848490` |
| EB2503 | 2024-03-27..2025-02-18 | 8 | 162/155 | 8 | `017cc27befc8cbbefdfec7c042338168dfe695d84264bc6177cddeb588f373b4` |
| EB2504 | 2024-04-26..2025-03-19 | 9 | 180/172 | 9 | `241924b0a444e65d17bd1cfbd313e84420ae52abd95a839212f267f52f265b8b` |
| EB2506 | 2024-06-26..2025-05-23 | 10 | 203/194 | 10 | `c6b4dc7bf047e4402e62fc2cebfe5f1b440c5cf5a4e7dd8b3c9a9199644d703d` |
| EB2507 | 2024-07-29..2025-06-23 | 10 | 199/194 | 10 | `8ad6194f7b6debe5a6eee54bb40ef1fef7636973929c6d189b72ddbfd31f77fd` |
| EB2508 | 2024-08-28..2025-07-21 | 10 | 197/192 | 10 | `bf369d3c5d67ab712e5b314b06f20fa48cfcd1ef4bb2eb2613040f7a9ac4d88d` |
| EB2603 | 2025-03-27..2026-02-24 | 10 | 206/199 | 10 | `f3430d42a41b32091f69afdd318676fd9fb2d31453f16a320901fc6c7856e938` |
| EB2604 | 2025-04-28..2026-03-20 | 9 | 180/177 | 9 | `84d88f28cec49912da1ec3147d87a510efd04415f23d20c9fb6a52694068154d` |
| EB2606 | 2025-06-26..2026-05-12 | 10 | 203/197 | 10 | `979d7f8f8c0c79a1d8a4d7f7ebca13489ccea475d02bd48dcad056ff1a1ec47a` |
| EB2607 | 2025-07-29..2026-06-22 | 9 | 177/164 | 9 | `d8d1d8ebff15775a5e9a2dd99bc88f514d34d9b3d4e6f807d5926f7b46e5e281` |
| EB2608 | 2025-08-27..2026-07-22 | 10 | 198/192 | 10 | `2257c03a7a64f2a44e5af6f131773b8a94c57c7e8d42dbfb973f3840e1c887ff` |
| EB2610 | 2025-10-29..2026-09-15 | 10 | 203/191 | 10 | `842b7fffe65ff662858c41baf067aff926d5099cf6c91342e3ca7b086960a5ad` |

建议的受控批次：仅上述 EB 物理合约 `1d`，按表中顺序串行；每项 apply 前在维护锁内重算并匹配该项原生 plan hash，成功后独立只读重规划目标为 0，再进入下一项。总请求上限 173、每项次数见表；不自动 retry、不扩至 W1/60m、其他品种、Runtime、通知或发布。严格分类的 `PRICE_UNAVAILABLE` 仅按现行质量事实合同处理，不生成 Bar；其他来源质量异常、配额失败、发布失败、结果不明或哈希漂移停止后续批次并只读核对已完成项，恢复须新的边界确认。全部输入核查结束后，单独进行三策略、历史参考收益和只读候选页面验收。

## 获批执行与只读验收

Owner 在上述精确 preflight 后明确批准该 19 合约批次。逐合约重读原生计划并核对表中 hash、目标数和请求上限，再串行 apply；19/19 均返回 `passed`，共发布 173 个目标月分区、发起 173 次 RQData 请求，失败 0、阻塞 0、重试 0。每项 apply 后独立重规划均为 `direct_target_count=0`、`derived_target_count=0`、`provider_request_count=0`、`targets=[]`。

EB 整品种 `newow-readiness --frequency 1d --matrix --compact` 在相同业务截止返回 `audited/complete=true`、`budget_exhausted=false`、`repair_targets=[]`、只读 provider 请求与写入均为 0；26 项依赖 `DATA_READY`，19 项 `DATA_INTERRUPTED:PRICE_UNAVAILABLE`。趋势、震荡、主升浪的 main/chart/reference 九项均 `READY`。Catalog 只读事务核得获批合约共 54 条 `rqdata-d1-zero-ohl-v1` 质量事实；逐日与权威 rank1 MainContractMap 交叉核对，54 条中属于同合约 rank1 的为 0。缺价事实仍保留，不转换为 CanonicalBar，也不称作无异常价格历史。

在 exact `develop@64882654875b86526104c0dfeceeaed1479fb0c1` 的本地候选只读预览中，EB 三策略 `1d/actual_dominant` 图表均 `ready`，历史参考收益卡成功加载，浏览器 pageerror 与 Newow 4xx/5xx 均为 0。页面口径为零手续费、零滑点、非账户成交的乐观参考收益：趋势已完成 52 笔、收益合计 +39.11 百分点、未清仓 1；震荡已完成 15 笔、+57.2 百分点、未清仓 0；主升浪已完成 2 笔、-0.92 百分点、未清仓 0。三者显示的数据中断交易均为 0，与上述 rank1 交叉核对一致。候选页面验收不代表因果收益、Release 或 Runtime promotion。
