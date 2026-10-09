# 盘后每日增量稳定性修复（2026-10-09）

## 目标与授权

owner 已交办根因修复、今日只读核对、发布与 Runtime 切换；通知失败不影响每日增量结果。
不重复下载/发布，不重跑自然任务，不补发通知，不改变策略、Scope 或 auto_order=false。
独立数据验收、源码回归、Review、发布、切换与自然业务验收分别记录。

## 已定位事实

现役 v1.14.7@d957d62d363777be7091673256e8cde394153faa 的 10/9 自然任务
18:05:06–18:07:13 failed/UPDATE_FAILED。发布计数960；按合法字段格式重建摘要283321 bytes，
超过262144 bytes上限。失败分支无诊断，摘要未进入终态；不能因此认定零提交。
原自然状态及其哈希保留，不改写为 passed。

今日既有 daily-recovery dry-run noop/planned=0，provider_requests=0。
独立 Catalog/Canonical 只读核对420组合：60品种七周期当前分区完整，端点、文件hash、
身份、schema/rows/coverage及来源metadata通过。严格读回不等于全历史审计。

## 实施合同

- 同一冻结daily计划、维护锁内，W1伴随D1计入容量，provider和行情写入前校验。
- 发布证据8192条/4MiB，status读写16MiB、history封装32MiB共享权威限制；旧schema兼容。
- confirmed publication观察只记录已确认提交，节流进度最多5秒，异常/终态立即保留完整前缀；
  硬退出只证明最近持久化前缀，不是精确crash ledger，不由该前缀自动恢复或重试。
- 超限、身份错误、计数不匹配和收尾异常明确诊断，容量不足不截断证据或缩窗。
- commit未知、质量失败等保持fail-closed；既有来源就绪检查与重试次数不变。
- 通知、消费者审计和可选周审计诊断独立，通知失败不改变增量状态/成功日，不触发数据重跑。

## 验证与交付顺序

先RED再GREEN验证周五960条、跨月、主力切换、积压缺月、8192及超限、前后两轮大状态、
partial/commit未知/持久化失败及通知异常。扩大盘后/历史保留/恢复/promotion/health回归，
独立Review通过后集成develop，并从已发布v1.14.7构建仅含必要修复的补丁候选。
运行必要构建与工程检查后发布、切换所有当前启用服务并现场读回，不手工触发盘后。
新版本下一次自然盘后通过前不声明自然闭环验收完成。

## 实际结果

源码验证：14组定向 pytest 730 passed（30.65s），Market reader/authority/identity追加165 passed（3.00s），合计895 passed；OpenSpec10/10、Ruff、secret0、diff通过。
独立Review冻结候选另跑259 passed（23.42s），两个P2均已修正：可信证据alias污染与full evidence挤掉进度日志。允许集成develop及仅必要补丁发布。
容量preflight在既有metadata前置同步之后、行情Bar请求/Canonical发布之前，使用同一冻结计划；不删除metadata authority。
新版本发布、服务切换与自然验收结果分别补记，不以源码验证冒充Runtime事实。
现场独立只读证据：`output/after-market-stability-20261009/`。
