# B / BZ / PG D1 精确恢复批次

状态：PREPARED / EXTERNAL_GATE_PENDING；未执行真实下载或生产写入。

- 执行代码：`3a76203fd71a0b031df4d8dc0b21d9c4ada1fb79`。
- 执行工作树：`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/newow-final-three`。
- 环境：本机既有正式 `GuiyiQuant/project.env` 指向的 Catalog 与 Canonical；安全 loader 读取凭据，不打印或复制配置。
- 配置身份：`c9df3ef2a1a9f4b856b0fdc7a0839eaf9040fcad0eb56b6adc573b819c4ab746`。
- Canonical 根身份：`1094b8d30a5f54593c407af265e2f3fc9bdb1655f9a9db84aeba15b74289e5ab`。
- 执行代码 hash：`d2ebaa0831e5e4576b9bb236a9b29954a42c1f174be70f643c69f57b02f22af8`。
- 准备文件：`final-three.prepare.json`；SHA-256：`e3038cedeb47a81f57c6d3ec0f827a2dde9175c662ec733c15b7622c59991545`。
- 只读 prepare：maintenance_lock_available=true，provider_requests=0，writes=0。

## 一次授权范围

- 20 个下表物理合约，仅 D1，按 B → BZ → PG 串行；182 个目标月、3,526 个缺失端点，最多 182 次应用层来源请求（不是供应商计费额度保证）。不自动重试。
- 范围内含 RQData 下载、staging/硬校验、Canonical 发布、Catalog 月分区登记、既有首页派生投影失效及独立读回。
- 每单元前核对 exact code/config/root/plan，取得维护锁；source 请求与响应落盘，typed 结果先落盘，再验证 replan 零目标及 Catalog/Parquet/MDS。
- PG2410、PG2411 不在本批，禁止重跑；不修改其他周期、主力映射、策略公式、Scope、通知、Release 或 Runtime。
- 仅已批准的 rqdata-d1-zero-ohl-v1 质量事实可按现有合同保留，不造价；未知异常、超边界、收据缺失或读回失败立即停止后续单元。

## 精确窗口与原生计划

| 品种 | 物理合约 | 上市起日 | through | 目标月/请求上限 | 计划 SHA-256 |
|---|---|---|---|---:|---|
| B | B2411 | 2023-11-15 | 2024-10-23 | 10/10 | `fb472ab4fd83b82560e660ec388626c0a806a975509073d140b84bb8195813c6` |
| BZ | BZ2605 | 2025-07-08 | 2026-04-20 | 8/8 | `dd2cd6b8ff2068ff4740115cd0e3e8fa006d85dc623f9d9345def970f0b49e53` |
| BZ | BZ2610 | 2025-10-29 | 2026-09-15 | 6/6 | `0bffdb10779c73e0c70ca81fddebe17df1b76dd0feca57bb70b2f6fd4f764126` |
| PG | PG2412 | 2023-12-27 | 2024-11-20 | 10/10 | `273f6ea3d9c4072ba657a2a97faf6b01fe606dd6c3189f8db0534adf11b8daa6` |
| PG | PG2501 | 2024-01-29 | 2024-12-13 | 9/9 | `84226097caf26b144eeeac3c4a3f4636e70f961e752bdd4ac3eb007a9c5a36e3` |
| PG | PG2502 | 2024-02-27 | 2025-01-15 | 8/8 | `19f1588ed16daaa89642f3a31b827a3da990d4d7d65128f9e530e8b3c3283fbe` |
| PG | PG2503 | 2024-03-27 | 2025-02-21 | 9/9 | `c5718d374417aa6ce19a7c50d384e33daae6fac80a13b59c9a847bdcd75a02a4` |
| PG | PG2505 | 2024-05-29 | 2025-04-18 | 10/10 | `44bbe2208bde8b08aff5daac88a54f262110a684a2d4f75129b5c054dff0ea7d` |
| PG | PG2506 | 2024-06-26 | 2025-05-22 | 10/10 | `28bd9bb4b31d35d8940a1872413c41ffaa3530b63fba5f6cdabe94a3d24a90b1` |
| PG | PG2507 | 2024-07-29 | 2025-06-23 | 10/10 | `b9780a4dea93074acc7ed21c8fd05db3dca3bb86d3839d37b798a9d3044310dc` |
| PG | PG2508 | 2024-08-28 | 2025-07-21 | 10/10 | `920a2cdae0d6d0320f7a552cc7733c473a0a9f75d7ba13e6d82eb6eff0e3fb60` |
| PG | PG2510 | 2024-10-29 | 2025-09-18 | 10/10 | `f320554051d32babb97a10681cbd941c981e3be406e616913917e8e3da42afc9` |
| PG | PG2511 | 2024-11-27 | 2025-10-17 | 8/8 | `feca5084853a98736bd6b2371ab741494b276097439b478c981554cf7f7b26db` |
| PG | PG2512 | 2024-12-27 | 2025-11-21 | 9/9 | `22943fa92f1fd34800c23191e75d5e23375239ff4b801c4009e516e0571525a1` |
| PG | PG2602 | 2025-02-26 | 2026-01-13 | 10/10 | `32539b06e2ee742c70c4f31ee563c2f3e69ef0717b634a830b493c4f12837e73` |
| PG | PG2604 | 2025-04-28 | 2026-03-23 | 9/9 | `144c61b32bdb291ecacdbfe6e722c1ea8a424077ab360dcf9e84a8780fce9d9a` |
| PG | PG2605 | 2025-05-28 | 2026-04-15 | 10/10 | `2dd70008309741f66a4a7ac1b361c27ca9e9e5cc2b477ab52f0178ea213d115a` |
| PG | PG2607 | 2025-07-29 | 2026-06-23 | 9/9 | `32aa420073e11c5d21d641e98e9fcc71a57432e8c5c4d8600ff5a69b23479b9e` |
| PG | PG2610 | 2025-10-29 | 2026-09-15 | 9/9 | `50898fc768ae6f973297ce04c8349e9f156ddfa75ac0f57874ba88b31dd96289` |
| PG | PG2406 | 2023-06-28 | 2024-05-23 | 8/8 | `f2f86fe86fcb4e7b72ae2908c306bbc069644dcedaa4901fad144cb21f5280e9` |

## 失败恢复与验收

现有 Catalog/Canonical reader 身份保持。发布按既有 staging 与 immutable 分区机制执行；不删除旧版本或逆向回滚已提交事实。plan-hash 锁及逐项零目标读回防重复执行；结果不明时不以同一 apply 重试，保留 journal、source response、warmup-result 和已提交分区，独立只读核对后重新确定剩余范围。若恢复需要新的写入或回滚，另列精确目标。

数据批次完成后，验证 B/BZ/PG 三策略及历史页面参考收益、九个首次加载页面；再以同一代码和 2026-09-15 固定截止重验 60 品种/180 页面。页面收益仍为 page-parity，不代表模拟或真实账户收益。最新完整交易日仅追加只读审计；新的缺口不并入本批。

工程证据：421 项恢复/CLI/存储回归、282 项 manager/verification/CLI 回归（集合有重叠）；合并后 205 项通过。独立 Review 的短写发现已修正并复核通过。PG 旧 stdout 丢失的底层根因仍未证实，新执行依靠落盘证据，不将旧执行补记为成功。
