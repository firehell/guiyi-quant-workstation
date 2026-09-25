# RS W1 旧无交易聚合修复批次（待数据写入授权）

- 环境：本地归一量化正式 Canonical root 与 PostgreSQL Catalog，由既有 `project.env` 安全加载；不读取或记录凭据。
- 代码：`develop@09482651c9cad177ab04bd1e4e9c4df004de7ca0`；完整周截点：`2026-09-18T07:00:00.000001Z`。
- RS D1/W1 Catalog revision：`1e443f64f7c28a8f4a81e32333f1629d3669d4936847e14a743e7bfd4f141fc5`。
- 唯一准备文件：[rs-no-trade-prepare.json](rs-no-trade-prepare.json)，SHA-256：`c1acf23ba52b0ad9551425f6878874ce9fcaaceb49c5c952d685769e8907e7de`。文件逐月列出旧 URI/hash、新 URI/hash、D1 月分区前像、每根差异周及保留行数。
- 精确范围：RS2309、RS2311、RS2407、RS2409、RS2411、RS2507、RS2509、RS2511、RS2607、RS2608 的 64 个 `contract/rs/*/1w` 月分区，133 根旧聚合周；同月其余 118 根 W1 保持原值。各月清单仅以准备文件为准，不接受新增目标。
- 资源上限：provider/RQData 请求 0；D1、1m、主连及其他品种写入 0；最多发布 64 个不可变 W1 Parquet 文件并在同一 DB transaction 更新其 64 个 Catalog 指针；不覆盖或删除旧文件。
- dry-run：当前 64/64 active 指针仍为 old，133/133 候选差异能由现有完整 D1 重算，全部候选月 hash 与准备文件一致；旧准备的 64 个月内容逐项相同。候选三策略矩阵 `audited/complete` 仅表示审计跑完，不能当作全 READY：趋势、主升浪主图与参考为 READY；震荡主图/参考按合法质量事实 WARMING；副图保留预热，震荡比较器为 INSUFFICIENT_BARS。
- 执行前：重新验证准备 SHA、prepare/repair/aggregation 源码 SHA、HEAD、固定 `project.env` 路径及内容 SHA、Canonical root、RS Catalog revision、D1 active 前像、64 个 old 指针、维护锁；任一漂移或锁忙即停止，且不进入写入。
- 执行与回读：只调用一次 `apply`；逐月发布不可变文件并更新 Catalog 指针，逐合约运行 W1-D1 v2 质量读取，单次 commit 后在独立只读事务核对 64/64 candidate URI/hash 和 D1 前像，再重新运行 RS 三策略候选/正式 API 与真实页面首载。
- 结果不明或失败：停止受影响 mutation，不盲目重试；独立 `inspect` 判明 old/candidate/mixed。commit 前失败由事务 rollback 保留旧 Catalog 指针，可能遗留未引用的新不可变文件；旧 W1 文件保留。任何 mixed/unknown、回读失败或质量异常都要求新的精确恢复决策。
- 本批不含正式 RS Scope、main/tag/Release、Runtime promotion、通知或其他 8 个品种数据写入。
