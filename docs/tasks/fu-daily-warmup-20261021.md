# FU2701 日线物理预热修复（2026-10-21）

状态：COMPLETED；仅日线输入修复与开发页面消费者验收，不代表全周期完整或自然 Runtime 验收。

## 范围与执行

owner交办补齐燃料油综合判断所缺的FU2701日线。复用正式release树
`.worktrees/release-v1.15.16` / `c559eb7a594dea5189c7a630b010a284032e89f4`
原生 `HistoricalDataManager.contract_warmup`，仅 `fu / FU2701 / 1d`，从上市日
2026-01-05至最近完整交易日2026-10-21。10个月分区191个预期端点，原缺190个。
冻结计划hash为 `ad3de885e6849222c814e6f5c094ac30bdbdfad2656559a8f865de8acd7b644a`。

独立Review核对精确范围、10请求预算与恢复边界后，执行前重新规划校验hash，保存现有Catalog前像、
旧文件SHA256及单次intent；原生维护锁内再次匹配hash。真实RQData请求10次，10分区发布，
failed=0、blocked=0。各月独立提交，不声明整批原子；本次无失败或未知提交，无重试。
未改变其他频率、品种、主力映射、Rule/Scope、运行配置或应用源码，未重启、发布、创建Event或发送通知。

## 实际验证

- `services/quant-api/.venv/bin/python output/fu-daily-warmup-20261021/verify.py`：
  独立只读事务、原生重规划零目标/零诊断，MDS质量并集191根日线，首末端点分别为
  2026-01-05 07:00 UTC、2026-10-21 07:00 UTC；0 quality facts，全部收盘价为正。
- `services/quant-api/.venv/bin/python output/fu-daily-warmup-20261021/api-readback.py`：
  新鲜API8002主图及同token/as-of的60m综合判断HTTP200；趋势/震荡的日线与60m事实均ready，
  物理合约均FU2701。周线两项仍unavailable，不补分、不跨合约替代，不宣称全周期完整。
- 独立Review重算10个新文件与1个旧文件哈希，核对publication evidence与当前文件一致，
  旧十月文件保留，plan/intent/result身份一致，无阻塞项。
- 实际开发浏览器刷新后日线读取至10月21日，当前合约FU2701、收盘4815；不跨换月计算涨跌。

## 证据与恢复

本地证据：`output/fu-daily-warmup-20261021/`，包括plan、attempt001前像/intent/result/
publication-evidence、verification及API读回。`attempt001`已消费，不得重跑。
旧不可变文件及精确前像保留；如需回退必须重新核对当前Catalog与并发变更，按正式维护合同生成精确恢复操作，
不得覆盖后续更新或直接整批回滚。输出目录不随Git发布。

下一步：继续当前开发页面验看；周线未知状态与自然Runtime验收保持独立，不新增后台任务。
