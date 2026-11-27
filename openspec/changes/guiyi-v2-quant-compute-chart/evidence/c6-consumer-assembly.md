# Compute 消费者装配与隔离联验

以包含 Market Foundation `a0ecee24f` 的 develop 为最终复验基线。快期沿原生 H1 入口校验源代次、索引、合同、交易日和 32 根窗口，再调用本品种本交易日的 Live 计算。目标实例和已安装 Core 身份由入口验证。原生 SQLite 继续处理恢复、去重、未知提交及未决义务。16 品种的受控 Tick 跨进程读回覆盖前一根 H1、打开 SQLite、两批重复唤醒、下一根各推进一条命令和完整重放。

苏冰装配入口 `scripts/ops/macos/run-paper-market-compute.py --paper-root <冻结工作树>` 使用候选 API Python 中锁定的 Core。原生 Worker、Factors、账户与账本来自精确冻结版 `2be7a62af8cd38be67d9d1b671e132673e44f91e`，启动原生 worker 时只传 `--refresh-facts`。新队列只处理 30m、60m；1m 通过原模型执行入口，并额外验证目标完成流原件。重启复核当天已提交的分钟原件和账本字段。隔离回放从另一 Redis 实例切到正式形状的目标绑定，使用冻结源码重放原有测试 run，序号 2 → 3，重读仍为 3，下一分钟至 4。原 run 身份、旧账本前缀和实际提交源 IDs 均一致。缺少源代次的分钟和 30m 原件均被拒绝，账本停在上次成功提交。

正式 Reference 服务读取稳定归档目录的 `latest-receipt.json`。可选计算订阅由该目录的 `canonical-compute-windows.json` 指定，未配置时不创建计算进度。配置为不超过 32 行的 JSON 数组，每行包含 `product`、`contract`、`frequency`、`since`、`through` 和 `features`，仅接纳登记的通用增量指标及归档凭证覆盖的物理合约窗口。完成后在 Market 维护锁内复核 exact Catalog 修订，原子保留 `canonical-compute-progress.json` 的结果和游标。进程退出重启后补领当前凭证，重复不派工，被较新交易日覆盖的晚到凭证不回拨水位。Catalog 冲突、计算异常和进程停止保留上次成功结果。配置身份变化须显式重新绑定进度。牛哇参考计算仍只从原有归档凭证入口启动。RQAlpha 继续使用独立数据域。

## 制品

Quant Core `0.4.1` 的 179 个包内 Python 文件已与最新 develop 包源码、wheel、sdist 和四个消费者安装逐字节核对，含并行 LMS 研究变更。连续两次按锁构建，wheel 和 sdist 各自完全相同，两次各通过 36 项包内测试。五份 uv lock 检查通过。旧 0.4.0 制品保留原身份。

| 对象 | SHA-256 |
| --- | --- |
| wheel | `46e9756aea1a3edb925249b0caab410e3ea2930e2972aeb836a905e2f73676f7` |
| sdist | `8d282b2708a153000467a52a24527e77af2debc51d46dbdd8ee337e9a4ce1a19` |
| 包内源码集合 | `2ff88dc1eab6d942bec18e1ad1a4f09086f9fad67bc17fedc61a151be2db70b5` |

## 联合性能

[样本与资源记录](c6-consumer-assembly.json) 复用[原测量入口](htdy_canonical_parallel.py)，用已安装的 0.4.1、一次性 PostgreSQL、专用 Redis、独立 Parquet 和受控 Tick。两组前置并跑快期 H1 P95 为 2.188 和 2.252 秒。合入 Market Foundation 后的对照批次 P95 为 2.633 秒，三路并跑 P95 为 4.306 秒，最大 4.307 秒。该批次 16 品种均入账，苏冰首分钟组入账 370 ms，盘后处理 8 张修订凭证和 64 个新结果，重复凭证新增结果为 0。Live、Incremental 队列峰值均为 1，拒绝均为 0。Feed 峰值等待 16 份，全部队列与归档凭证收尾积压为 0。快期、苏冰、归档进程的最大 RSS 分别约 191、188、240 MiB，整段夹具 CPU 时间约 11.69、3.32、5.09 秒。原有有界队列回归也验证满载拒绝和后续恢复。

此前连续修订的 28% 变化没有伴随积压。最新同机单批的增幅更大，仍低于快期现有 20 秒本地响应预算和苏冰 2 分钟积压边界。不同批次时延波动明显，现场以自然高峰的实际取数和水位为准。本轮维持进程隔离。完整 60 × 7 继续引用既有 418/420 基线与 RS 缺价证据。

在同一候选中叠加 Quant Chart `87837006a` 后，以已安装 Core 0.4.1 运行 `pytest`，Compute Runtime、API、归档、目标 Tick、快期、苏冰及 Market 切换定向回归 445 项通过，Chart 显示计算 3 项通过。锁定 Chart 0.1.7 tarball 与已安装 Core 的 manifest 校验通过。独立 RQAlpha 28 项通过，1 项因未提供既有独立冻结行情包而跳过。禁网 VeighNa 组件与一次性 PostgreSQL 53 项通过。三个相关 OpenSpec change 均通过 strict validation。

独立 Review 复核了冻结源身份、Paper 前缀、H1 接纳、正式归档覆盖与提交竞态、包内文件及消费锁。正式宿主仍待核验：先由 Market Foundation 注册并验证精确的 Paper plist 与唯一进程，核对已安装制品和新 Redis。随后读回原生账户首根自然 H1/1m，观察 30m/60m 因子推进与重启，验证首张正式整批归档及修订后的结果和水位。现场项保留在 C6/C7。
