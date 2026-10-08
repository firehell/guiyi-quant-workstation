# 2026-10-08 盘后四项修复

状态：数据修复、代码、测试与独立 Review 已完成；Runtime 部署预检阻塞，不能声明新版本自然验收通过。
代码提交 `a39571f5d`、`8c52e2edf`。原自然任务、失败检查与首次预算耗尽记录保留。

## 实际数据修复与读回

- RM2701 2026-01 至 2026-09 的 5m/15m/30m 各新增 9 个分区，共 27 个。
  仅从既有完整 Canonical 1m 聚合，provider 请求 0，覆盖旧分区 0。
  首次执行因维护锁 `blocked`，0 提交；锁自然释放后重新校验旧文件及 exact plan hash，使用新执行意图。
  三频各 applied=9、failed=0；没有重跑自然 after-market 或重试失败发布。
- 新只读事务独立按 Session 与 Decimal(precision=200) 验证七个字段及全部端点：
  5m 11724、15m 3908、30m 2040 根，缺口和额外端点均为 0。原 33 个分区文件 SHA 保持不变。
- BZ2611、EG2611、RM2701 当前 D1 完整前缀分别为 203 Bar+5 typed quality facts、207+1、172+0，全部通过。
  原 18:26 检查使用此前输入，未被改写；本次完整消费者检查中三品种无前缀错误。

## 性能与证据实现

- 只读审计实例复用精确 Session 与物理 replay，保持质量、窗口、生命周期与完整周校验；普通 API 默认关闭缓存。
- 首次完整读回：W1 全 60 品种、180 cases，532.573 秒，0 失败、0 未检，未耗尽；179 主图/参考 READY，
  其余合法非 READY 状态保留。此实测使用初版性能补丁，后续批量优化的输出一致性由独立回归验证。
- 同轮 D1 仍 602.016 秒耗尽、12 品种未检，此结果原样保留。
  进一步 profile 定位批量 replay 的逐 Bar deepcopy 开销；仅私有批量状态使用原计算核，公开原子、幂等 step 未改。
  相同 SC D1 输入 profile 119.367→51.212 秒。
- 固定 `8c52e2edf5f8984dc25daf0642ed26a8c115299e` 后 D1 全 60 品种、180 cases，474.059 秒，
  主图/参考 180 READY，0 失败、0 未检，预算未耗尽。新事务核对 D1/W1 输入 revision 均未变化。
  这些是候选代码对真实数据的只读验证，不是自然任务记录。
- 健康接口对未重新绑定当前 revision 的旧 consumer receipt 显示 freshness=unverified，保持旧结果。
- 新自然运行在 Redis 清理前持久保存 rank1/subscription/run/scope 摘要，清理后读回 namespace。
  新 Historical 发布通过 immutable Parquet metadata 与已确认提交 receipt 保留输入来源和质量 facts 摘要；
  partial 保留确认提交，unknown commit 不冒充确认。文件和目录 fsync、1024 次/256 KiB 摘要及 1 MiB 状态边界均验证。
  旧资产与已删除的旧 Live snapshot 不补造来源证据，不为加标签重写资产。

## 验证与部署边界

- 合并后 data_foundation/after-market/storage/Catalog/coverage/runtime-health 七模块：741 passed。
- 批量与增量、prefix、换月、typed gap、checkpoint：153 passed；额外 Newow reader/service/contracts/reference：450 passed。
- 两轮独立 Review 通过；OpenSpec 10 passed，ruff、diff 和 secret scan 通过。
- 部署前只读 predicate 实际返回 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。
  现场 API/Web/记录 worker 与 Market/Alert 处于不同发布根；本任务没有绕过该检查、重载服务或手工运行盘后任务。
  后续版本切换可能改变现场身份，部署前必须重新核对；不能以 develop 集成冒充已部署。

原件与当前读回保存在 `output/after-market-fix-20261008/`：精确计划、blocked/apply 结果、旧文件指纹、
独立数值验收、原自然状态、首次 consumer 结果及最终 D1 结果。
唯一最小下一步：解除正式 Market Runtime 身份/状态预检阻断后部署补丁，按下一次自然任务验收新 Live 证据。
