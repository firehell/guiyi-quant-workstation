# P7B-01 SC 原油四周期历史候选处理

状态：**PARTIAL / DEFERRED_DATA_BLOCKED，0/12 页面闭环；允许集成 develop（仅安全暂缓记录）**。只处理 SC，未启动 CF。冻结源码 `2283b66fc306c3f601838bc93bbe4fefb436708a`；独立第二轮分母为 13 品种，不改变原 21 品种记录。窗口 `2023-01-01..2026-09-24`，`as_of=2026-09-24T07:00:00.000001+00:00`；SC 权威 `rq_or_listing_start=2018-03-26`，维护 floor 为 2023-01-01。1m 仅作可信聚合来源，目标为 `5m/15m/30m/60m × trend/oscillation/dual`，四输入、八基础、四融合、十二页面。

证据保留于 `.worktrees/sc-candidate-pilot/outputs/sc-candidate-pilot-20260930/`，不入 Git；失败 attempt、原始报告和工具路径错误日志均保留。

## 精确维护与停止

SC 自身 rank1 Map 冻结 46 个物理 owner、184 个 owner×周期单元，初始 6 DATA_READY、178 缺口，候选保存流为零。原生 dry-run 冻结 848 个去重源月请求、3414 个派生目标；campaign 文件 SHA `31f2156bb22757ea185095258174d77c6e583ffcd9209718c1fb0b7beeec7013`。全量源的保守字节估算约 9.53 GB，高于当时账号余量 991127560 bytes，因此 `overall_theoretical_budget_pass=false / completion_guaranteed=false`；单 unit 最大保守预算 399360000 bytes，通过每 unit 与锁内 fresh quota、磁盘约 749.6 GB、原生 SC scratch 发布及相同 SHA 严格读回和维护锁门禁。独立 preapply Review 通过后，仅执行一次。

SC2302 四周期 **4/184 单元 READBACK_VERIFIED**，5m 单元 12 次 provider 请求，其余三周期复用来源，合计发布 60 个分区。随后 SC2303/5m 单元在 **源 `SC2303/1m/2022-04`** 发布失败：`ATOMIC_PUBLISH_FAILED → ArrowInvalid`；该物理合约完整前缀起于 2020-03-02，不缩为页面窗口。失败 unit 的原生 plan hash `58bc905b31bae66c973e0703f102b5e118aaa0475c4def9b58c09eb4b6f0e3c9`；campaign 和 unit attempt 保留 `PENDING / retry_allowed=false`，没有该 unit native result 或 campaign-complete。执行日志退出 1，耗时 186.484 秒，不重试，不改 hash、不缩窗，不启动后续单元。

请求证据分别为 **12 个已完成单元请求 + 26 个失败 unit 已启动逻辑请求 = 38 个观察到启动的请求**。这不证明全部已提交，也不证明供应商内部网络次数或失败响应消费字节。最后账户余量为 986496132 bytes；账户 delta 不冒充本任务消费。失败 Bar 与 Arrow 异常正文没有保存，具体根因仍 **UNKNOWN**，不能据此宣称 SC 来源质量问题或共享存储已修复。

## 已提交边界与独立复核

七频 before/after 原生严格读回和独立差集均 PASS：328 旧 dataset 保持，2662 旧文件及指针全部保持，0 changed、0 removed；新增 **110** active 分区，仅 SC2302 五频各 12 个，共 60；SC2303 `1m` 与 `5m` 各 25 个，共 50（2020-03..2022-03）。1907 个 D1/W1 分区保持，无旧 Bar 替换。其余 SC 合约及 continuous 不变。

失败 unit 独立读回为原 82 个文件保持、50 新增、0 changed，72 个原日周指针保持；最早剩余源为 SC2303/1m/2022-04。该源及同月 5m 无 active pointer，目录为空，无 tmp 或孤立文件。26 请求不能将失败 unit 计为 READBACK_VERIFIED。

`independent-submitted-aggregation.json` 对实际已提交范围从 Catalog 绑定的同物理合约 Canonical 1m、权威 Session `(start,end]` 独立 Decimal precision 200 重聚合，逐字段及端点一致：SC2302 完整四频前缀分别 25068 / 8356 / 4293 / 2488 Bar；SC2303 已提交 25 月 5m 为 52758 Bar，共 **92963 Bar / 77 合约×频率×月**，PASS。SC2303 剩余完整前缀及整个 SC 四输入未完成，`all_product_prefixes_proven=false`。

前后 SC rank1 46 owner 及映射日期相同，候选 12 组合前后均 0 stream/0 revision。没有捕获全库 raw metadata preimage，不能宣称所有 metadata 表逐字不变；已核验显式 contract-warmup 禁止 metadata sync、失败 unit 生命周期及 Session 派生 replan 范围一致，实际新增仅精确 SC 合约目标。独立最终 Review `independent-stopped-boundary-review.json` 为 **REVIEW_COMPLETE_SAFE_DEFERRAL**，允许安全暂缓记录集成；不表示 Arrow 根因已解决。

## 验证与交付边界

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core .../.venv/bin/python -m pytest tests/newow_candidate_tools -q -p no:cacheprovider`：**159 passed in 2.05s**。
- 相同环境运行 `services/quant-api/tests/data_foundation/test_historical_data_manager.py`、`tests/newow/test_product_reader.py`、`test_candidate_preview.py`、`test_product_snapshot_cache.py`、`test_fusion_reference.py`：**457 passed in 7.28s**。此前两次不存在的 fusion 测试路径退出 4、零测试，日志保留；不计为通过。
- `seven_frequency_snapshot_readonly.py --output-name seven-frequency-after.json`、`failed_readback.py`、`seven_frequency_stopped_difference.py`、`submitted_aggregation_review.py` 和 `resources_final_readonly.py` 均实际退出 0、PASS。
- 最终 maintenance 锁 granted=0/waiting=0，8012/5178 无监听；未启动 SC API/Web/Chrome，未构建基础或融合资产。`matrix.json` 固定十二项 `DEFERRED_DATA_BLOCKED`；日周六模式、API、浏览器、49 原图、CLOSED/SVG 验收均未运行，不使用其他品种证据替代。

无产品源码、公式、收益或策略版本变更；正式分钟、Release/main/tag、Runtime、Scope、通知、交易与账户未触碰。已成功发布 110 个不可变分区保留，不批量回滚。SC 恢复须取得失败来源/Arrow 原因与安全精确恢复合同的新证据，现有 attempt 禁止重试。

唯一最小下一步：总控核对并集成 SC 安全暂缓记录后，按固定顺序启动 **P7B-02 CF** 的自身 preflight。
