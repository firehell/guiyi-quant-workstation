# DFD-07 滚动单品种补全设计

## 目的

在 MR-08 实时验证的等待窗口内，逐步完成 DFD-07 剩余品种的 Canonical 重建；保持每次
正式写入可控、可验收，并以真实执行数据逐步校准排期。

## 范围与不做事项

- 使用现有 `guiyi data update|audit`、八表 Catalog、Canonical Parquet 和
  `MarketDataService`；不新增脚本、队列、数据库表或第二条维护链路。
- 每次只处理一个品种。当前四交易所 canary 依次为 `ec`、`lc`；随后按只读库存估出的
  规模从小到大处理剩余品种。
- 不修改 `operational_products.txt`，不启用 MR-08 Runtime，不处理 Live、通知或订单。
- 本设计不授权 RQData 请求、生产 Catalog/Canonical 写入或 Runtime 启用；每次 `--apply`
  仍需要用户对该品种给出一次明确执行意图。

## 运行方式

维护分为互不重叠的执行队列和准备队列：

1. 执行队列只含当前一个品种。每次 `update --apply` 前，确认固定 T0、目标品种、维护锁空闲，
   且 MR-08 不处于关键实时观察、盘后维护或历史读回检查点。
2. 准备队列只包含下一个候选品种的只读 preflight：核对 revision、Canonical 根、当前分区、
   scoped audit 与 fixed-T0 dry-run 结果。preflight 不同步元数据、不请求 RQData、不写入任何状态。
3. 收到该品种的一次性意图后，只运行一次 `guiyi data update --symbol X --through T0 --apply`。
   不与另一 `update`、`refresh` 或盘后维护并行。
4. 写入自然结束后，依次执行 scoped audit、同 T0 无 `--apply` dry-run 和七周期
   `MarketDataService` 读回。三个检查都通过才关闭该品种。

## 结果、异常与估时

- 每次闭环在终端交付中记录：preflight 耗时、apply 墙钟时间、provider 请求数、发布分区数和
  验收结果。前 6 个成功样本仅用于校准排期，不作为并发或性能改造依据。
- 初始每品种预留 90 分钟；根据样本将后续品种划为短、中、长三个排期档。
- `partial`、额度耗尽、质量失败或任何 audit/dry-run/readback 失败均停止在当前品种。保留已验证的
  已发布月分区，后续从同一 T0 继续诊断或自然续传；不得自动跳到下一个品种。
- 成功唯一口径为：`audit=passed`、fixed-T0 dry-run=`noop`，且 seven-frequency
  continuous / contract / actual_dominant 读回均通过。分区写出本身不是完成依据。

## 验收

- 单次 apply 全程独占已有 maintenance lock，未与 MR-08 的关键检查或任何历史维护重叠。
- 每个关闭品种均有完整的三项只读验收和实际耗时记录。
- `ec` 与 `lc` 分别闭环后，才从四交易所 canary 过渡为常规“最短优先”滚动队列。
- 全部 60 个 active 品种的单品种闭环完成后，另行运行全域只读 audit；在此之前 DFD-07 保持
  `PARTIAL`。
