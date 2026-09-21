# SuBing D1 Quality Segmentation Production Gate

状态：`CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE / PRODUCTION_APPLY_BLOCKED`

固定截止：`2026-09-18T18:30:00+08:00`

prepare-only plan：`outputs/subing-four-period-readiness-20260918/d1-quality-segmentation-production-plan.json`

plan SHA-256：`5d5475b0709ea4f6c6464491938e38c4d0867d30d42a6f8366004594a282561c`

隔离候选 manifest：`outputs/subing-four-period-readiness-20260918/d1-quality-segmentation-complete-candidate-manifest.json`

manifest SHA-256：`2a15f7aa0fe896804c2ee2b0b19dd5658407cf05eb6e9e96a4fad9e7245371ba`

## 已冻结范围

- 17 个 D1 品种；156 个精确月分区目标。
- 154 个 existing partition replacement 均绑定旧 partition id、URI、file SHA-256、已有 quality SHA-256
  和受影响日期。
- OI2609、PF2609 的 2026-09 为两个独立 `CREATE_MIXED_UNION_PARTITION` 目标，各 9 个 expected endpoint；
  合计 8 个 Valid Bar、10 个 `NONPOSITIVE_CLOSE` break。
- 40 个无关 lifecycle targets 明确排除。
- production apply plan 的 provider request budget=0；独立 source recovery 已完成，本候选执行 production writes=0。
- 质量策略 `subing-d1-quality-segment-v1`；Reference v2；D1 公式仍为 `subing_ths_1d_v1`。
- RS 最新 owner 保持 3 根有效 D1、`WARMING`；不能计为 ready。
- 154 个 replacement 与 2 个 create target 已在 worktree 隔离根生成不可变 Parquet 与质量 sidecar，冻结
  file/content/quality/sidecar hash；候选发布后由 strict reader 回读，共承载 1,217 个质量事实。
- 缺失原始响应恢复计划 `3797e61a8657facc1dc2fb47bf8557cc9dce45000ce302f3d3110d570264e9df`
  完成 10/10 provider 请求、60/60 目标日与 28 个上下文日，零重试；raw、journal、result 已落盘并绑定 manifest。
- 156 个候选共 312 个 Parquet/sidecar 制品哈希回读零错误；相同输入幂等重跑产生同一 manifest hash。
- 候选生成只读取 production PostgreSQL/Catalog/Canonical，production writes=0；恢复批次不执行 manager apply。

## 执行合同

任何未来 production apply 必须：

1. 先在隔离 root 生成不可变候选文件并冻结每个新 file/content/quality hash；OI/PF 两个 create target 在这些
   hash 产生前保持 `REQUIRES_IMMUTABLE_CANDIDATE_HASHES_BEFORE_APPLY`。
2. 取得 market-data 独占维护锁，逐项比较旧 pointer 与本 plan 绑定的旧 hash；任一漂移整批零写入退出。
3. 逐分区完成 stage、hard validation、fsync 与原子 Catalog pointer commit；不得请求 provider。
4. commit 后以 strict Catalog/MDS readback 验证精确 union、唯一端点与 hash；已精确应用项幂等返回。
5. 部分提交时恢复旧 pointer，保留不可变候选文件供审计；不得继续后续目标。
6. 完成后按同一截止重跑 17 个 D1、全部 240 组合数据/API/真实浏览器首屏。生产正式状态在此之前仍为
   `223/240`，17 个 D1 blocked。

## 当前不能执行的原因

完整 156 项候选已冻结，原始响应 Gate 已关闭。production apply 尚未执行；应用前仍须重新核对旧 pointer/hash、
维护锁、原子提交与失败恢复，应用后再完成同截止 Catalog/MDS、17 个 D1 和 240 组合验收。本文件不是 apply
receipt 或写入授权。

## 独立 Gate

本包不授权 PostgreSQL migration、provider 请求、Redis 写入、Scope/Runtime/通知修改、develop 集成、
main/tag/release 或 Runtime promotion。草稿 PR 保持 draft，直到 production apply 与同截止验收产生独立证据。
