# D1 分页质量窗口与周审计补跑设计

日期：2026-09-19  
状态：已批准  
范围：MarketDataService 历史分页、weekly audit 调度/健康诊断、对应 API/Web/运维展示

## 目标

修复三个 P1：

1. actual-dominant D1 最新分页被窗口外旧 `PRICE_UNAVAILABLE` 事实误阻塞；
2. 周六 09:00 周审计在休眠/唤醒或短暂不可运行场景下没有有界补跑；
3. 周审计到期未运行仍显示 `not_run`，不能明确诊断 `missed`。

实现继续遵守：RQData 与 Canonical/Catalog 零写入、零 provider 请求、零通知；代码交付不包含 LaunchAgent 安装、重载、Runtime promotion 或实际周审计执行。

## 非目标

- 不修复、覆盖或隔离既有历史质量事实；
- 不改变严格区间查询 `_read_physical` 的 fail-closed 语义；
- 不给周审计增加失败重试、数据修复、通知或 operational overall 依赖；
- 不通过插值、缩窗或静默跳过质量断点返回行情；
- 不改变 actual-dominant 主力归属和 W1 周末 owner 语义。

## 1. 分页质量判断

### 当前问题

`_physical_page_bars` 在确定页面边界前检查游标之前的全部分区；`_actual_dominant_page` 读取月分区时也由 `_partition_bars` 对整月质量事实直接失败。因此，同月或更早月份中位于本次页面之外的旧质量事实会阻塞最新正常数据。

### 设计

分页读取使用一个仅供分页的质量感知分区入口，同时读取已验证的 bars 与 `PriceUnavailableFact`。正常价格与质量事实按 `bar_end` 组成倒序端点流，再应用游标、物理合约或 actual-dominant owner 规则。

- 质量事实若位于本次实际页面窗口内，返回 `PRICE_UNAVAILABLE`；
- 质量事实若位于页面窗口之前，不阻塞当前页；
- 后续游标使该事实进入页面窗口时，必须返回 `PRICE_UNAVAILABLE`；
- actual-dominant 只让对应交易日 owner 合约的端点参与页面窗口，非 owner 合约质量事实不得误伤；
- 分页仍需要判断窗口之后是否存在更早端点，以正确生成 `has_more_before`，但仅作为页外 sentinel 的质量事实不直接使当前页失败；
- 完整性、排序冲突、Calendar、Session、MainContractMap 和分区连续性校验保持不变。

严格区间读取继续使用现有整窗质量拒绝逻辑，避免放宽普通查询合同。

## 2. 周审计有界补跑

### 调度

LaunchAgent 的 `StartCalendarInterval` 改为周六 09:00 至 23:00 的小时级有限触发数组，不使用 `RunAtLoad`、`KeepAlive` 或跨日无限轮询。这样机器在周六晚些时候恢复后仍有自然触发机会。

### 应用层幂等门禁

计划任务使用独立的 scheduled 入口。入口在现有 status sidecar 锁内计算当前上海时区周六 09:00 的计划身份：

- 未到本周计划时点：无副作用 `not_due`；
- 本周已有计划尝试：无副作用 `already_attempted`；
- 本周尚无计划尝试且已到期：写入本周 `scheduled_for` 后执行一次审计。

`running`、`passed`、`findings`、`failed`、`skipped_busy` 都算本周已经尝试。后续触发不能覆盖它们，也不能重新运行。手工 `guiyi data weekly-audit` 与手工 Runtime 入口不受该去重规则限制，并明确记录 `trigger="manual"`；LaunchAgent 使用 `trigger="scheduled"`。

周审计状态 schema 升级，至少记录：

- `trigger`；
- `scheduled_for`（计划任务为本周六 09:00，手工任务为 `null`）；
- 原有 readonly、provider_requests=0、data_writes=0、runtime identity 和进度字段。

## 3. `missed` 健康诊断

新增独立 `weekly-audit-enabled` activation marker，由 `--confirm-weekly-audit` 安装流程原子写入，并复用现有 marker 前像、失败恢复和权限校验机制。它不与 Market/Alert marker 合并。

健康状态按安装和本周计划身份计算：

- marker 未启用：`disabled`；
- marker 已启用、尚未到本周六 09:00，且没有本周计划尝试：`not_run`；
- marker 已启用、已经到期，但没有本周计划尝试：`missed`；
- 有本周计划尝试：展示该次真实状态；
- malformed、超时 running 和过旧已完成状态仍分别保留 `invalid`、`stuck`、`stale` 诊断，但旧周结果不能掩盖当前周 `missed`。

`missed` 只做诊断，不启动审计、不排队、不发通知、不改变顶层 operational health。

API schema、TypeScript 类型、页面标签/颜色和 `local-services-status.sh` 的白名单同步加入 `disabled`、`missed`。

## 4. 安装与兼容边界

- render-only 只渲染 plist，不创建 marker；
- `--confirm-weekly-audit` 才创建 marker、替换 weekly plist 并加载 label；
- 任一安装阶段失败时恢复 plist/label 和 marker 前像；
- 已有 schema v1 状态可作为“历史最后结果”读取，但没有本周 `scheduled_for` 时不能证明本周计划任务已执行；到期后应显示 `missed`；
- Runtime 部署、weekly label 重载和当前漏跑周的真实补跑属于独立外部 Gate。

## 5. 验证

### 分页

- 同月旧质量事实位于 limit 外时，最新 physical/actual D1 页面成功；
- 跨月旧质量事实位于 limit 外时，最新页面成功；
- 质量事实进入当前页或下一页时返回 `PRICE_UNAVAILABLE`；
- 非 owner 合约的质量事实不阻塞 actual-dominant 页面；
- `has_more_before`、游标排他性和 endpoint 完整性不回归；
- W1、intraday 与严格区间查询既有测试继续通过。

### 周审计

- 计划入口在到期前不运行；
- 本周首次到期触发运行一次；
- 同周后续触发不运行、不覆盖状态；
- `failed` 和 `skipped_busy` 不自动重试；
- 手工入口仍可显式运行；
- 审计保持 readonly、零 provider、零数据写入、零通知。

### 健康与安装

- marker 缺失为 `disabled`；
- 到期前为 `not_run`；
- 到期后无本周尝试为 `missed`；
- 当前周状态和跨周切换正确；
- plist 是周六有限小时数组，无 `RunAtLoad/KeepAlive`；
- render-only 不写 marker，安装成功写 marker，安装失败恢复 marker；
- API、Web 和本地状态输出接受并正确展示新状态。

## 6. 交付 Gate

代码、测试、Review、develop 集成分别取证。以下不在本任务自动执行范围：

- main merge、tag、release；
- Runtime promotion；
- LaunchAgent 安装、重载或 kickstart；
- 实际执行周审计；
- RQData、Canonical、Catalog 或生产数据库写入。
