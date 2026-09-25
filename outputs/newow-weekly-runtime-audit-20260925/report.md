# 牛哇现役周线入口与 180 项首载只读审计

- 检查时间：2026-09-24 夜至 2026-09-25 凌晨（Asia/Shanghai）。
- 现役身份：`v1.10.33@943c23b61a18156e0d068726ace843aacb6d4e43`；检查前后 API 均为 `1.10.33`，正式能力 `newow_product_capabilities_v22`、W1 60 品种。
- 本次只执行本机 API GET、真实 Chrome 首载、生产数据库 `SET TRANSACTION READ ONLY` 查询和现有状态文件读取；未调用 provider、未运行盘后/周审计、未写生产 DB/Canonical/Runtime。

## 分层定位

| 层级 | 只读结果 |
| --- | --- |
| Calendar | 2026-09-24 五交易所 CZCE/DCE/GFEX/INE/SHFE 均为交易日。 |
| Session | 当天有 60 个品种的有效 Session。 |
| rank1 MainContractMap | 2026-09-23 与 2026-09-28 均与 operational 清单精确相等，60/60；2026-09-24 为 0/60。 |
| 物理合约 Catalog | 以 9/23 rank1 的 60 个物理合约为界，9 月 D1 分区 60/60 的 coverage_end 均为 9/23 07:00 UTC；已有 W1 分区 56 个，coverage_end 均为 9/18 07:00 UTC。未证明本周 D1/W1 已发布。 |
| 盘后 | 旧 v1.10.30 根的 9/24 自然盘后 `failed / CALENDAR_NIGHT_AUTHORITY_MISSING / attempts=1`；现役新根对该日为 `pending / current_run=null`，不是一次新失败或成功。 |

当前周部分交易日有 rank1、9/24 无 rank1，周线快照按合同拒绝历史回退。即使将来单独补齐 9/24 映射，也必须对 D1/W1 的真实缺口重新规划、发布并读回；不能把映射修复视为页面 READY。

## 正式 API 与真实浏览器矩阵

同一正式 v22 能力清单的 60 个品种 × 趋势、震荡、主升浪，共 180 个唯一组合，串行执行，无重试：

- 正式 `weekly-snapshot` API：180/180 返回 `409 NEWOW_DATA_UNAVAILABLE / MAIN_CONTRACT_MAP_MISSING`，无其他错误类别。
- 真实 Chrome 首次导航：180/180 页面导航为 200，周线快照请求为 409，页面显示“主图事实不可用”和“主力合约映射缺失”；没有把不可用显示为 READY 或无信号。
- RS 震荡当前同受 rank1 缺口阻断，无法重新判定其真实当前输入是否仍为 `WARMING`。额外用现行只读 readiness 在 2026-09-18 固定截点复核 RS，返回 `incomplete`，三策略均为 `UNKNOWN / MAIN_CONTRACT_MAP_MISSING`，见 `rs-20260918-readiness.json`；这说明此前同截点的候选 WARMING 不能直接沿用为现役结论。该历史截点异常的精确缺失日期尚未定位，不能归因于 9/24 缺口。

逐项原始结果见 `matrix.jsonl`，聚合计数与该文件 SHA-256 见 `summary.json`。

## 后续 Gate

本轮完成了现时页面缺口定位和正式现状矩阵；当前 180 项业务 READY 验收未通过。先对 9/24 元数据与 D1/W1 形成精确只读恢复计划、来源和影响范围，并独立定位 RS 固定截点的映射拒绝；再按项目生产写入 Gate 取得授权执行。写后分别读回 rank1、Canonical/Catalog 和 MDS，最后重跑同一 180 项正式 API/浏览器矩阵。自然盘后与自然 weekly audit 仍是独立 Gate。
