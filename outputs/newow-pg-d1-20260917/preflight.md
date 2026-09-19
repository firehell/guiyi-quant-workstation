# PG 日线候选：生产写入前只读 preflight

状态：`PARTIAL / RECOVERY_GATE_PENDING`；获批执行后的实际进度见文末。2026-09-17 在 `develop@c9e0297a0b7bd7257e1e246e432f7a45cc175cd9`、固定业务截止 `2026-09-15T07:00:00+00:00` 对 PG 运行单品种 `newow-readiness --frequency 1d --matrix --compact`，并对下列 19 个物理合约分别运行原生 `contract-warmup` dry-run。全部预检只读，provider 请求和写入均为 0；本文件本身不是 apply 授权。

审计返回 `audited/complete=true`、`budget_exhausted=false`；40 项日线依赖中 21 项 `DATA_READY`、19 项 `DATA_UNAVAILABLE:DATASET_OR_PARTITION_MISSING`，三策略 main/chart/reference 均尚不可用。19 项修复目标均为 `PROPOSED`，未报 metadata、source 或 integrity finding。原生计划合计 176 个目标月分区、3,552 个目标 Bar 端点、其中 3,404 个待补端点，最多 176 次 RQData 请求。旧库存的 40 合约/7,825 缺口不是本次授权计数。

| 合约 | 物理合约日线窗口 | 目标月 | 目标/待补 Bar | 请求上限 | 原生 plan SHA-256 |
|---|---|---:|---:|---:|---|
| PG2410 | 2023-10-27..2024-09-20 | 10 | 205/194 | 10 | `5a566febaa3c2522be81f36fcf74ced451c50d0cebfd1ca9eeffb14465366429` |
| PG2411 | 2023-11-28..2024-10-18 | 8 | 159/153 | 8 | `d9a570e4ed1bae1840e7fa1c58717c2661f89e880945ea7abe8d3d484d7ec5ff` |
| PG2412 | 2023-12-27..2024-11-20 | 10 | 199/190 | 10 | `273f6ea3d9c4072ba657a2a97faf6b01fe606dd6c3189f8db0534adf11b8daa6` |
| PG2501 | 2024-01-29..2024-12-13 | 9 | 183/176 | 9 | `84226097caf26b144eeeac3c4a3f4636e70f961e752bdd4ac3eb007a9c5a36e3` |
| PG2502 | 2024-02-27..2025-01-15 | 8 | 164/152 | 8 | `19f1588ed16daaa89642f3a31b827a3da990d4d7d65128f9e530e8b3c3283fbe` |
| PG2503 | 2024-03-27..2025-02-21 | 9 | 182/174 | 9 | `c5718d374417aa6ce19a7c50d384e33daae6fac80a13b59c9a847bdcd75a02a4` |
| PG2505 | 2024-05-29..2025-04-18 | 10 | 201/195 | 10 | `44bbe2208bde8b08aff5daac88a54f262110a684a2d4f75129b5c054dff0ea7d` |
| PG2506 | 2024-06-26..2025-05-22 | 10 | 203/195 | 10 | `28bd9bb4b31d35d8940a1872413c41ffaa3530b63fba5f6cdabe94a3d24a90b1` |
| PG2507 | 2024-07-29..2025-06-23 | 10 | 199/193 | 10 | `b9780a4dea93074acc7ed21c8fd05db3dca3bb86d3839d37b798a9d3044310dc` |
| PG2508 | 2024-08-28..2025-07-21 | 10 | 197/192 | 10 | `920a2cdae0d6d0320f7a552cc7733c473a0a9f75d7ba13e6d82eb6eff0e3fb60` |
| PG2510 | 2024-10-29..2025-09-18 | 10 | 204/196 | 10 | `f320554051d32babb97a10681cbd941c981e3be406e616913917e8e3da42afc9` |
| PG2511 | 2024-11-27..2025-10-17 | 8 | 165/157 | 8 | `feca5084853a98736bd6b2371ab741494b276097439b478c981554cf7f7b26db` |
| PG2512 | 2024-12-27..2025-11-21 | 9 | 182/172 | 9 | `22943fa92f1fd34800c23191e75d5e23375239ff4b801c4009e516e0571525a1` |
| PG2602 | 2025-02-26..2026-01-13 | 10 | 207/197 | 10 | `32539b06e2ee742c70c4f31ee563c2f3e69ef0717b634a830b493c4f12837e73` |
| PG2604 | 2025-04-28..2026-03-23 | 9 | 180/176 | 9 | `144c61b32bdb291ecacdbfe6e722c1ea8a424077ab360dcf9e84a8780fce9d9a` |
| PG2605 | 2025-05-28..2026-04-15 | 10 | 202/196 | 10 | `2dd70008309741f66a4a7ac1b361c27ca9e9e5cc2b477ab52f0178ea213d115a` |
| PG2607 | 2025-07-29..2026-06-23 | 9 | 180/169 | 9 | `32aa420073e11c5d21d641e98e9fcc71a57432e8c5c4d8600ff5a69b23479b9e` |
| PG2610 | 2025-10-29..2026-09-15 | 9 | 182/176 | 9 | `50898fc768ae6f973297ce04c8349e9f156ddfa75ac0f57874ba88b31dd96289` |
| PG2406 | 2023-06-28..2024-05-23 | 8 | 158/151 | 8 | `f2f86fe86fcb4e7b72ae2908c306bbc069644dcedaa4901fad144cb21f5280e9` |

建议的单次受控批次：只对表中 19 个 PG 物理合约 `1d` 按表中顺序串行；每项 apply 前在维护锁内重算并匹配原生 plan hash、identity、窗口、目标数及其请求上限，成功后独立只读重规划为零再继续。合计最多 176 次真实 RQData 请求，不自动重试，不扩至其他合约/品种、W1/60m、Runtime、通知或发布。严格匹配合同的 `PRICE_UNAVAILABLE` 仅保留版本化质量事实并中断计算，不生成 Bar；其他来源异常、缺日、重复冲突、配额/发布失败、结果不明、哈希或现场身份漂移，立即停止后续批次并只读核查已完成项，恢复需重新确定边界。批次完成后，再独立做 PG 三策略、历史参考收益与只读候选页面验收。

## 获批批次的部分执行与停机

Owner 批准上述精确 19 合约批次。第一项 PG2410 的原生只读计划匹配预检中的 hash、窗口、目标数与请求上限，随后发起一次 `--apply`。该进程退出码为 0，但调用脚本未捕获到非空的 CLI JSON 回执，无法凭回执确认 `applied`、实际 provider 请求数及 terminal status；脚本在解析回执时立即退出，没有发起 PG2411 等其余 18 项，也没有重试 PG2410。

独立只读重规划显示 PG2410 的 `direct_target_count=0`、`derived_target_count=0`、`provider_request_count=0`、`targets=[]`。Catalog 只读事务显示该合约 12 个现存月分区、220 条合法行情行与 1 条 `rqdata-d1-zero-ohl-v1` 来源缺价事实（2023-11-24）；该日权威 rank1 为 PG2401，不是 PG2410。整品种重新审计返回 `audited/complete=true`，21 项 `DATA_READY`、1 项 `DATA_INTERRUPTED:PRICE_UNAVAILABLE`、18 项 `DATA_UNAVAILABLE:DATASET_OR_PARTITION_MISSING`，修复目标 18 项、三策略 main READY 仍为 0，审计自身 provider 请求和写入均为 0。PG2410 的目标已清零且质量事实保留，但本次未保有可验证的原始 apply 回执，不能宣称整批或页面验收完成。

按照获批停机规则，剩余 18 项暂不执行。若继续，应在新边界下先只读重核这 18 项的原生 hash、窗口和目标，再串行 apply、逐项保存可验证回执并零目标回读；不得重跑 PG2410。原计划表中剩余请求上限合计 166，仍以新预检读回为准；不自动重试、扩频、扩品种、启用 Runtime 或发布。

## 第二次恢复批准后的停机

Owner 另行批准仅处理上述剩余 18 项、总请求上限 166，明确不重跑 PG2410。恢复前 `develop` 与 `origin/develop` 均为 `c9e0297a0b7bd7257e1e246e432f7a45cc175cd9`；PG2410 只读重规划仍为零目标。第一项 PG2411 的原生只读计划重新匹配 hash `d9a570e4ed1bae1840e7fa1c58717c2661f89e880945ea7abe8d3d484d7ec5ff`、窗口、8 个目标月、159/153 个目标/待补 Bar 及 8 次请求上限，随后仅发起一次 hash-locked `--apply`。与 PG2410 一样，调用方未取得可解析的 stdout JSON；解析当即失败并停机，没有发起后续 17 项或重试 PG2411。不能凭这次调用主张可验证的 terminal status、`applied` 或实际 provider 请求数。

独立只读重规划 PG2411 返回 0 个 direct/derived targets、0 次预计 provider 请求；Catalog 有 12 个现存月分区、213 条合法行情行及 1 条 `rqdata-d1-zero-ohl-v1` 质量事实（2024-02-05，权威 rank1 是 PG2403）。重新审计 PG 全品种为 `audited/complete=true`、21 项 `DATA_READY`、2 项 `DATA_INTERRUPTED:PRICE_UNAVAILABLE`、17 项 `DATA_UNAVAILABLE:DATASET_OR_PARTITION_MISSING`；修复目标 17 项、三策略 main READY 为 0，审计自身 provider 请求/写入为 0。重复出现的无回执问题尚未定位根因；本轮不再尝试任何生产写入，剩余 17 项原计划请求上限合计 158，实际继续前需解决回执可验证性并重核现场计划。PG2410 和 PG2411 均不得重跑。
