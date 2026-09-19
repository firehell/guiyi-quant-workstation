# 固定 41 品种步骤 5：四合约 W1 数据恢复回执

状态：`COMPLETED`。执行代码为
`f0b567823210c8c0e984f96742a0db9ef433cd65`，截止日期为 `2026-09-18`。
本批次只处理 `AL2611`、`SC2611`、`SS2611`、`ZN2611` 的 D1/W1
物理合约前缀；不包含发布、Runtime、Scope、正式周期开放或通知。

## 精确范围与执行结果

| 合约 | 计划 SHA-256 | 目标 | Provider 请求 | D1 / W1 Bar | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| AL2611 | `722e7bf95aba6cea8f25f3ec947b699a421c8c73e75ca63072e38341a715a4a6` | 22 | 22 | 206 / 43 | 22 applied |
| SC2611 | `ba8c80dbfcea612eb95b3ef7733d5e089bf70c0df98110dc57612a905535d4ad` | 22 | 22 | 217 / 45 | 22 applied |
| SS2611 | `fd14e520be08eabd4eed33f6e16e262f49424a199cf4f8fd96869dd6fe91c695` | 22 | 22 | 206 / 43 | 22 applied |
| ZN2611 | `53b8c27adc927d3ef4d1489996e21a65161ec0b3de0b5b9ee4a1aec09a974a4d` | 22 | 22 | 206 / 43 | 22 applied |

合计 88 个直接目标、88 次 RQData 请求，`blocked=0`、`failed=0`。
每个合约现有 11 个 D1 和 11 个 W1 活动月分区。写入前后 44 个 D1
文件 SHA-256 全部不变；44 个 W1 活动分区完成发布。四合约
`source_quality` 缺价事实合计为 0。

## 回读

- 四品种 W1 readiness 为 `audited / complete=true`：356 个依赖
  `DATA_READY`，SC 的短 owner 2 项为合法 `NOT_APPLICABLE`；零 provider、零写入。
- 无固定 `as_of` 的 12 个默认周快照全部 HTTP 200，共同解析到
  `2026-09-18T07:00:00.000001Z`。
- 固定同一截止的 12 组主图和参考交易全部 HTTP 200，`as_of` 与
  `snapshot_token` 一致。
- 12 个候选页面各用独立 Chrome、单次导航、无刷新验收；周快照、主图和
  参考交易均成功，页面没有数据不可用或加载失败。

结合步骤 5 既有 111 个可读组合，固定 41 品种 W1 当前为 **123/123
页面可读**。D1 的四合约文件未变化，既有 60×3 结论仍为 179 READY、
RS 震荡 1 WARMING；其余 19 品种的 W1/60m 仍未开放。

## 保留的非成功证据

- 首次 AL apply 因另一个正在运行的全品种只读 audit 持有维护锁而返回
  `maintenance_locked`；`provider_requests=0`、`applied=0`。该 audit 自然结束、
  锁释放且四计划哈希再次一致后才执行本批次。
- 四路并发 section 探针产生 9 个 `NEWOW_RESOURCE_BUSY` 和 3 个
  `NEWOW_SNAPSHOT_GENERATION_CONFLICT`；随后使用产品正常的串行同快照读取完成
  验收，不覆盖并发限制证据。
- 早期浏览器探针的 settle 条件错误并发生 Chrome 进程退出，不计入验收；
  最终 12 页结果来自独立新 Chrome 的单次导航。

证据索引与机器可读汇总见同目录 `recovery-closeout.json`、四份计划和 apply
结果、写入前后 Catalog 回读、readiness、snapshot、section 与 browser 文件。
