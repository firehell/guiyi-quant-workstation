# SM 周线逐品种验收（2026-09-24）

- 固定截点 `2026-09-18T07:00:00.000001Z`。初始 Catalog revision `a03ac32d7b62cca27a3c5b5b9aa5c55e42024a9a1e1e59e867f939fa2590598e`；19 个物理合约，247 个完整 D1 对应缺周、29 个旧无交易聚合周、6 个日周成交额冲突、24 个合法质量中断。
- SM2311/2023-09-01 缺 D1 回执；唯一一次来源查询计划 SHA `8ab434338f805552d7c4deabcfb06204bd64c7269fd479868bcd2747660c5c90`，5 日响应，零写入、零重试。来源表明 D1 该日成交额应为 `7,919,564,100`，W1 该周应为 `24,932,701,700`；两个旧值均不符，其余数值字段一致。双分区精确包 SHA `fb0fc66b1f9fed8dbf1345696a418de8558552ee89003bec615ca6cb6e95dccb`，只改 D1/W1 各一个 2023-09 月分区，维护锁内同一 Catalog 事务提交，读回通过。
- 双分区写后 Catalog revision `6c7b4b5de591a858fd24a8992427c7bc40cacceb0c345827b5e89f6e6fc349cb`；刷新盘点剩 247 缺周、29 旧无交易聚合、5 个有 D1 回执的成交额冲突及 24 个质量中断。W1 精确包 SHA `2cc12719ed201c0ffa01b013d2fb3557873f40c9b6e873ad4facbe3a077a4743`：82 个 W1 月分区（64 新、18 旧）、281 个目标周；RQData 请求和 D1 写入均为 0。dry-run、82/82 旧指针、候选 MDS 281 Bar＋24 质量中断以及独立 Review 通过；一次正式提交后 82/82 新指针、MDS 和质量回读通过。
- 最终 Catalog revision `1f99cbc487c275f9186a981a863e24ceec11e12eb99d58dcdb559818652264bc`；刷新盘点仅剩 24 个合法质量中断。实际 Catalog 上三策略周线主图和参考交易均 READY，MACD WARMING，震荡比较器 UNAVAILABLE，其他比较器 NOT_APPLICABLE；没有造价或放宽质量阈值。
- 正式候选 Scope v22：`develop@10e6805665ede2cff18c3ebd40808dad11471529`，60/60，已 push。后端定向 76 passed，Web 全部 684 passed、1 skipped，Web build、ruff、目标 OpenSpec strict、diff check 和独立 Review 通过。完整 OpenSpec 全量校验的历史非本任务 `reference-trading/spec.md` 两处结构错误未在本任务改动。正式只读 API smoke：三策略各图表、参考交易、MACD、比较器共 12 个 HTTP 200，状态与候选盘点相符。
- 隔离真实浏览器在相同 commit 和截点完成三策略首次导航：趋势 FLAT、震荡 FLAT、主升浪 HOLD；周线图、辅助状态及参考交易统计加载。主升浪截图 `output/playwright/sm-weekly-v22-main-rise-20260924.png`。顶部独立报价不可用与主力元数据不可判定不表示周线策略失败；隔离预览按合同拒绝 `/reference-trading/streams` 的 403。预览进程已关闭。
- Release 与 Runtime promotion 均未执行。现役正式 Release/Runtime 仍以 `STATUS.md` 的 v1.10.30、周线 50/60 为准；develop v22 是待发布候选。
