# 剩余 10 品种 W1 当前只读盘点

- 代码：`55454558629734aff0856d02692c1d4242500980`；完整周截点：`2026-09-18T07:00:00.000001+00:00`；Catalog revision：`8e7346f6a729681648fa5c1ab4ed95194e1973dab72242265de534a5bdc26e72`。
- 事务内及独立新事务 revision 一致：`True`；provider 请求 0；生产写入 0。
- 原生矩阵：`audited`、complete=`True`、budget_exhausted=`False`、W1 三策略主图 READY=0/30；另有 30 项 D1 `UNSTARTED` 和 30 项 60m `UNOPENED` 为矩阵占位，不计入周线验收。
- 物理范围：179 合约；其中 176 已扫描，3 无需消费的完整 owner 周。

| 品种 | 缺 W1、D1 完整 | 旧无交易聚合 | D1/W1 值冲突 | 合法质量中断 | 首个主图阻塞 |
|---|---:|---:|---:|---:|---|
| PF 短纤 | 1054 | 138 | 26 | 84 | PF2302 / 2022-03-04 / DATA_INTEGRITY_INVALID |
| PK 花生 | 149 | 0 | 5 | 1 | PK2411 / 2023-11-17 / REPLAY_ENDPOINTS_MISSING |
| PL 丙烯 | 63 | 0 | 5 | 89 | PL2603 / 2025-07-25 / REPLAY_ENDPOINTS_MISSING |
| PR 瓶片 | 389 | 19 | 12 | 106 | PR2506 / 2024-08-30 / REPLAY_ENDPOINTS_MISSING |
| PX 对二甲苯 | 214 | 8 | 7 | 33 | PX2501 / 2024-01-19 / DATA_INTEGRITY_INVALID |
| RS 菜籽 | 0 | 133 | 0 | 18 | RS2311 / 2022-12-09 / DATA_INTEGRITY_INVALID |
| SF 硅铁 | 725 | 33 | 19 | 10 | SF2303 / 2022-03-18 / DATA_INTEGRITY_INVALID |
| SH 烧碱 | 162 | 0 | 4 | 5 | SH2501 / 2024-01-19 / REPLAY_ENDPOINTS_MISSING |
| SM 锰硅 | 247 | 29 | 6 | 24 | SM2305 / 2022-05-27 / DATA_INTEGRITY_INVALID |
| SR 白糖 | 0 | 1 | 0 | 0 | SR2303 / 2022-03-18 / DATA_INTEGRITY_INVALID |

总量：缺 W1 `3003` 周；旧无交易聚合 `361` 周；日周值冲突 `84` 周；合法质量中断 `370` 周。单位均为物理合约×周，类别不等于可执行写入计划。

## 已有修复的当前效果

- OI 已正式开放，不在本轮分母。PF2611、RS2609 质量事实与存量 W1 并存的 15 周已不再出现；RS2609 的 4 根缺 W1 也已不再出现。
- SR 仅余 SR2303/2022-03-18 一根旧聚合 W1；单月精确只读 prepare 与内存候选三策略验收见 `sr-prepare.json`、`sr-candidate-acceptance.json`。正式指针仍为 old。

## 批次顺序

1. SR 一月一行：只用现有 D1 重算，单独数据 apply/读回；随后三策略、参考、比较器和真实页面首载，再决定正式开放 Gate。
2. RS 先对 133 根旧无交易周按 64 个合约月冻结完整前像和候选；不重做已完成的 RS2609 4 根缺周及 15 根质量冲突。
3. PF/PR/PX/SF/SM 的旧无交易聚合与各自缺 W1 分开处理。PK/PL/SH 先处理缺 W1 和来源值冲突。84 根日周值冲突先核对来源版本/回执，83 根仅 turnover，SF2506 一根还涉及 volume；不得直接选修复侧。
4. 370 根合法质量中断保留为中断，不造价。每个品种修复后重新冻结 revision，跑三策略主图、副图、ReferenceTrade、比较器、候选 API 和真实浏览器，再单列 Scope、Release、Runtime Gate。

## 84 个日周值冲突的来源回执核对

- 详见 `conflict-receipt-map.json`。只读扫描本地成功的 D1 `unit-result.json`，按品种、合约、月份和回读文件 SHA 与当前 Catalog 指针精确匹配；全部 84 根 W1 当前均指向旧 `part.parquet`。其中 82 根冲突周所需的全部 D1 月分区均有成功回执，按现行 D1/W1 同源数值合同，应将旧 W1 作为精确重建候选，保留 D1 不动；仍需逐月冻结旧新 hash、候选数值及写入授权。
- PK2611/2026-08-14 的 D1 月仍是 `part.parquet`，没有匹配的成功 D1 回执；SM2311/2023-09-01 横跨 8/9 月，8 月 D1 有匹配回执，9 月 D1 为 `part.parquet` 且无匹配回执。这 2 根不能仅凭现有本地版本链裁定修复侧，须先核对原始来源回执；证据不足时才提交精确 provider 核验批次，不直接重建。
- 84 根中 83 根仅 `turnover` 冲突；SF2506/2025-04-11 同时涉及 `volume` 和 `turnover`，D1 2025-04 月指针 SHA 与成功 D1 回执完全一致，旧 W1 为重建候选。当前没有任何冲突行的生产写入。

原生 `57/57 PAGE_PASS` 只证明 unavailable 页面显示正确，不能当作数据或策略 READY。

## RS 只读批次与候选验收补充

- 精确只读计划 `rs-no-trade-prepare.json`：SHA-256 `c066c30d9c5001604205bffef0d486ef53ab1a8fc220bde5ee0c915955a25e97`，10 个合约、64 个 W1 月分区、133 根旧无交易聚合差异，其他 118 根同月 W1 保持不变。当前没有 RS 生产 apply 实现或写入授权回执。
- 第一次内存叠加候选返回 `NEWOW_DATA_IDENTITY_INVALID`；追踪到同一 RS2609/2025-09-19 合法中断对应两个后续 owner 区段。首版只保留所属 owner 中断的改法经独立 Review 判定会丢失重入段预热断点，已撤回。修正版保留各 owner 中断，在 dependency proof 中校验同一物理缺周的来源与完成时点必须相同，并分别证明各 owner 的中断。
- 修正版把重入前缀缺口保留给计算段；参考交易覆盖及图表只展示真实归属 owner 的单条缺口，并将物理行情与 owner 身份分别纳入 snapshot proof。内存候选矩阵 `audited`、complete=`True`：趋势、主升浪主图及参考 `READY`；震荡主图和参考按真实中断为 `WARMING`；多个副图也在合法预热，震荡比较器为 `UNAVAILABLE / INSUFFICIENT_BARS`。这是候选数据和本地代码的预检查，仍需独立 Review、生产数据读回、真实页面首载及正式开放 Gate。
- 服务层修正经独立 Review 无 Confirmed Issue，`167 passed`、ruff、`git diff --check`，已提交并推送 `develop@7ca695d5ff2bf8ab8b90c97d77e115cc0e44293e`。完整 Newow 测试目录在 339 项通过后进入耗时的杯柄计算，人工停止；不能称全目录通过。上方只读数据盘点固定的是此前代码 `55454558`，数据 revision 尚未因本次代码提交改变。

## SR 授权批次执行与逐品种验收

- Owner 明确授权准备文件 SHA `054eaa727285ae9c3ecdbf486fb1ba592a90e8786ba8df5525a42748d601d7b6` 的单次 SR2303 W1 2022-03 Canonical/Catalog 写入，明确排除 Scope、Release、Runtime。执行前计划、修复源码、聚合源码 hash 匹配，独立 `inspect=old`；仅执行一次 apply，返回 `committed / target_count=1`。独立新进程 `inspect=candidate`。
- `sr-post-apply-readback.json`：新 Catalog revision `614a2185c7d59cb63f495a3194c0477cc08d21484d5c02846009f1b2098c6406`；新分区 SHA `bfea4244281706b53333d6e170997a5eedf581090e0ce2f4f657961c3c073ac8`；月内 2 行仅 2022-03-18 改动；旧 W1 文件保留，D1 前像 hash 未变；MDS v2 质量回读通过。provider 请求 0、D1 写入 0。
- `sr-post-apply-readiness.json`：基于真实新指针的候选只读矩阵 `audited / complete=true`；趋势、震荡、主升浪的 W1 主图和 Reference 均 READY，已开放的 4 个辅助图层均 READY。震荡比较器 `UNAVAILABLE / INSUFFICIENT_BARS`，另两种比较器 NOT_APPLICABLE；跨周期解释 UNOPENED，不计为失败。
- 隔离真实浏览器：候选预览身份为 `develop@7ca695d5`、截点 `2026-09-18T07:00:00.000001Z`，API `127.0.0.1:8010` 与 Web `127.0.0.1:5174`。SR 三策略周线首次导航后主图/辅助图层均显示 `ready`，页面参考摘要与卡片均出现；趋势 21、震荡 8、主升浪 2 张可见卡片。候选 API 的图表、参考、辅助图层请求均为 200。预览按隔离合同拒绝 `/reference-trading/streams`（403），其“已保存历史参考”提示不能当作 Newow Reference 失败。截图：`output/playwright/sr-weekly-candidate-main-rise-20260924.png`。临时浏览器、API、Web 均已关闭，8010/5174 无监听。
- **正式 Scope 仍 50/60；本轮没有 Release、Runtime promotion。** SR 数据 Gate 已通过，正式开放仍需独立 Scope/Release/Runtime 授权与各自回读。

### SR 下一 Gate 的精确边界（尚未执行）

- 正式 Scope 若另获授权，目标仅把 `sr` 从剩余 10 品种移入已开放集合，比例变 51/60；W1 输入质量策略改用现有 `WEEKLY_V2`，不改策略公式、D1、其他 9 品种或候选预览 v9 身份。`product_release.py` 的正式 capability schema 需升版，Web `newowProduct.ts` 精确数组校验及对应 API/Web 测试同步更新。代码评审和正式 Scope 回读后，才可单独评估 Release Gate。
- 本批数据授权不包括以上 Scope 代码生效，也不包括 main/tag/Release、Runtime promotion。后两者需独立精确授权；正式页面自然首载必须在相应版本发布及 Runtime 读回之后另记，不能用此次隔离候选首载替代。
