# 实时来源修订与独立 Canonical 历史

Owner 于 2026-10-23 选择：保留实时参考记录，盘后按 Canonical 重算独立历史结果，明确展示来源修订及影响；真正身份/质量错误继续阻断。本文件同时记录最小设计和实施计划，不重复设置审批。

## 已验证事实

- 正式 v1.15.16/gen22；本轮周线质量修复 PR2612 14 周/SF2701 1 周、6 月分区，8 合约 W1 warmup 170 请求/170 发布均通过；10 个物理前缀与三策略读取通过，32 路 W1 lag 已全部自然追平。
- 176 H1 路冲突；42 产品 1860 分钟双侧原生聚合一致，200 分钟输入有数值差；3 次同物理查询 1035 根与 Canonical 完全一致。
- RQData 官方 generic-api 实时推送注意事项明确实时遗漏迟到 tick、盘后完整 tick 清洗，差异以历史为准。不存在延长固定等待可保证一致的证明。
- 旧 2565 根 1m 自然原件缺失，无持久副本；不补造、重放或改原时间。Canonical 历史完整不等于自然采集完整。

## 设计边界

1. 两层事实不合并：forward observation 继续以实际 first-seen completed 原件计算；historical replay 只用 Canonical。策略公式、Scope、Rule、audience、交易阶段及 auto_order=false 不变。
2. 保留既有 mismatch 和 quarantine 事实，不把 mismatch 改写 matched。通过新的版本化、追加式来源修订证据，绑定同物理合约/owner/端点、完整有效数值、原始及 Canonical 全字段哈希与具体差异。缺身份、质量、缺口或未知源不能分类为正常修订。
3. 被证实的来源数值修订不永久阻断实时路径；未解释冲突继续 fail closed。新鲜完整读回确认本轮 176 路均已正常计算到 10/23 15:00，quarantine/original terminal/pending 全部为 0，没有漏算区间。因此不新增恢复入口，不重放、不重置 FLAT、不改变实时持仓/水位；生产前须重新证明该条件，发生计算缺口则停止相关分类准入。
4. Canonical 历史使用原生独立 historical planner/driver 重建与复算，不把修订后的价格回写实时原件或旧结果。展示两层 cutoff、来源状态、修订字段/影响及历史是否重算完成。
5. 正式写入使用精确计划、旧表摘要、锁、幂等、原子提交及独立 readback；未知结果停止，不盲重试。

## 实施计划

- [x] 添加来源修订证据的纯验证、追加写入、幂等和冲突投影；测试损坏哈希/端点/owner/质量/未知值拒绝。
- [x] 接入原生 reconciliation、transaction guard、health 和 UI；保留旧 mismatch，分类结果明确 source revised，暴露独立 Canonical 历史状态。历史 CURRENT 仅证明计算端点追平，来源版本另行验收。
- [ ] 再核对 176 路无计算缺口及原有 OPEN/水位不变；使用原生历史 rebuild 独立重算 Canonical，不新增当前不需要的 quarantine 恢复能力。
- [x] 当前实现定向回归、API/Web 验证、canonical 更新、自审和独立 Review；发布版本与精确发布树复验仍待发布阶段。
- [ ] 按仓库流程集成、发布及必要 Runtime promotion，精确生产恢复后读回 720 路/原件/历史/推送不变与自然新 H1；不以修复代替自然验收。

## 回滚与验收

旧 immutable 文件、comparison、实时批次与修订均保留。版本回滚前核对新增证据兼容与活跃 checkpoint；不能清除新证据或重复消费。完成声明区分工程、发布、Runtime、来源修订恢复、独立历史重算和自然业务验收。

## 2026-10-23 工程验证

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../.. GUIYI_LOG_DIR=/private/tmp/guiyi-source-revision-test-logs python -m pytest -q -p no:cacheprovider tests/reference_trading`：845 passed / 81 skipped；跳过项目需要独立 PG 的测试另在真实隔离库运行。
- `node --test tests/newowRecording.test.ts tests/newowRecordingPanel.test.ts`：22 passed；Web build/typecheck/topology 通过。
- 两次独立 PostgreSQL attempt 均通过事务回滚、精确幂等、并发写入及既有 guards；每次专用测试库创建前不存在，测试后删除且独立确认不存在。证据 `output/data-three-repair-20261023/isolated-postgres-attempt00{1,2}/`。
- OpenSpec strict：11 passed；secret scan：0；Ruff、diff 检查通过。
- 独立 Review 首轮发现旧 receipt 原生 bounded recovery 不关闭 disabled_at 的边界问题，已使用实际后继 receipt 激活时间形成半开有效窗，并增加原生链测试；补齐 health 读字段避免 N+1。复核 74 passed / 2 skipped，无剩余 Confirmed Issue，允许集成 develop。
- 上述仅为工程完成证据；正式 v1.15.16 尚未使用新规则。旧 2565 条自然原件仍不可恢复。
