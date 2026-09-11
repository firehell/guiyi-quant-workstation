# 当天中断且缺少原日 Live snapshot 的收尾方案

状态：APPROVED。owner 于 2026-09-11 明确批准本方案的代码与合同修改；不授权生产 apply、RQData、数据写入、通知、发布或 Runtime 切换。

## 已验证现场与现行阻塞

- 检查基线：develop `c073e255234c244585d1a475a937881d760d2dc4`。
- 现役：`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.5-r1`，commit `cdd72d7501227d8e7f905ea0b8a54c038b521a09`。
- 本次运行：2026-09-11 18:05:02.033270+08:00；owner 已停止 PID 15367；20:56 读回 after-market idle、维护 advisory lock 为 0。
- 原状态 SHA-256：`37d7dbd0ea7072955dd713461cc5967e653420c0bfd4efd5b6de48bf73eec1c2`，停止后保持不变，current_run 仍在。
- 2026-09-11 Session 为 60 品种/225 行；2026-09-14 Session 60 品种均缺失；原日 Live subscription snapshot 不存在。
- 正式只读 closeout 返回 `AFTER_MARKET_CLOSEOUT_BLOCKED`，status_written=false、provider_requests=0、data_writes=0。没有执行 apply，也没有完成全物理审计。
- 当前 DATA_CENTER/OpenSpec 只允许前一自然日且要求原日 snapshot 匹配；等待跨日仍不能补足缺失 snapshot，因此原五步中的第 1 步需要显式修订合同。

## 拟批准的最小变化

1. 允许同日或旧日的合法 current_run 在确认进程已停止、现役身份一致、取得既有 writer guard 与 maintenance lease 后，记录 interrupted。开始时间不得晚于当前时间，scheduled_date 必须匹配，不修改原时间戳。
2. 新状态 schema v5 明确保存 closeout 证据：原交易日、核验时点、snapshot classification 与 reconciliation 是否经过验证。原日成功读取为 None 时记录 `not_verified_missing`；不得推断从未生成或 TTL 过期。完整合法且匹配 rank1 时记录 `verified_match`。
3. 格式错误、空/部分 snapshot、额外产品、错合约、不匹配及 Redis 读取失败继续 block，不能降为 missing。
4. 保留全部现有 Catalog 已提交指针物理读取、原截止日 audit、有效子集缺口判定、配置来源/五服务/PID/启动时间核验、双锁、目录及 guard inode、状态 SHA/CAS、原子替换/fsync、不确定结果停止。缺 snapshot 不能跳过数据审计。
5. 审计时及替换前分别读取原日 snapshot；分类或内容变化即 block，本次不重试。普通 Live 初始化不受 after-market guard 约束，因此只声明核验时点证据，不能声称全窗口 Redis 已冻结。
6. 唯一生产写入仍为原状态文件。保留 last_successful_trading_day；不发送通知、不写行情/元数据、不清理 Live、不生成 snapshot、不触发运行。
7. 新公开 reader/API/Web 显示 interrupted 及未核验的 Live 对账；旧 reader 不认识 v5 时降级。后续自然运行承接中断摘要，但不能将其继承为业务成功。
8. 自然 after-market reconciliation 与 promotion 的四种通过条件保持不变。interrupted 不构成 after_market_complete；不得增加 override 或其他晋升入口。

## 实现与验收范围

- 合同：docs/DATA_CENTER.md 与 historical-data-maintenance OpenSpec。
- 实现：after_market_closeout、after_market 公共状态 reader、必要 API schema/Runtime health 与 Web 中断证据显示；复用现有状态通道，不建立第二套账本或 resolver。
- RED/GREEN：同日/旧日 match/missing；future/非法时间；invalid/mismatch/Redis error；物理审计失败；锁忙、重启、来源/目录/状态漂移；snapshot 两读之间变化；并发 closeout 与自然 writer；replace/fsync 不确定。
- 晋升回归：missing interrupted 不能变成 after_market_complete；交易开始后缺 snapshot 仍阻塞；其他合法窗口只按原有 predicate 判断。
- 兼容：旧 v1-v4 结果不被提升，新 v5 缺口可见；旧 reader 降级；后续自然状态正确承接。
- 必须独立 Spec/Standards Review、相关后端/Web/工程检查；命令登记 TESTING.md。

## 后续真实操作仍需分开准备

代码获批并验收后，对精确当前状态重新执行只读 closeout。只有 ready 后，才能请求一次匹配的状态 apply 意图；结果不确定或失败后不重试。

Session 修复先绑定当时仍缺的品种/日期与现有入口实际写入面；不能把仅补 9 月 14 日 Session 的目标默默扩为重写当天 Calendar/rank1。行情恢复候选已通过 Catalog 选择器缩到 885 个数据集/月目标、全部为 2026 年 9 月；该结果不是下载计划、物理验收或 provider 授权。

完成上述边界后再冻结精确 release candidate，分别请求发布与 Runtime promotion 意图，最后取得新版本自然运行证据。

## 独立预审

2026-09-11 独立只读审查确认：无现行替代路径；行政中断事实与业务对账必须分离；现有双锁不冻结普通 Live snapshot 初始化。该预审允许提交此 Plan 给 owner，不替代实现后的独立 Review。
