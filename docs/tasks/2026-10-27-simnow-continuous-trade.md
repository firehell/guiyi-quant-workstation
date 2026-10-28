# 全品种持续trade代码交付

从develop de921797c0c7919b2e486cdecefe2f2e15885ca0隔离开发；当前任务只交付代码、验证、Review、
部署准备及develop集成，不连接柜台或读取凭据、不改正式配置、不安装服务、不发布或切Runtime。
原运行工作区源码未修改。主develop目录同时有其他研究修改，保持其文件和本地提交不动，集成通过任务PR。

## 实现与合同

共用排序、ContinuousTradeTickV1、schema2已有四库身份校验、双锁和原根接管、
费率→账户刷新→盘口、单未决提交/永久资金拒绝、持久对账及监控最后绑定保留。
observe/manage禁开仓保持，trade必须配置及启动参数同时匹配；不新建账户、不复制账本/清空预算。
具体规则、只读部署命令及收盘后切换/停用步骤统一见docs/SIMNOW_EXECUTION.md持续交易候选章节。

## 实际验证

- TESTING.md“持续trade隔离验收与部署预检”的完整Python组合：568 passed，36.43秒。
- 固定openctp-ctp 6.7.7.1的native_gateway_smoke.py：25 passed；真实结构、假API、零网络。
- node --test apps/quant-web/tests/simnowMonitor.test.ts：10 passed。
- pnpm -C apps/quant-web build：类型、构建、bundle拓扑通过；仅既有大chunk提示。
- PLAYWRIGHT_PORT=5198的simnow-monitor.spec.mjs：4 passed，桌面/移动端、空态、筛选、刷新暂停。
  首次沙箱监听端口被EPERM阻止，按宿主审批流程取得本地测试权限后成功；未触碰正式端口。
- Ruff、git diff --check及显式变更路径秘密扫描：通过，findings=0。

新增持续场景使用隔离假柜台、虚拟时钟与真实队列/状态机/适配器/费用核验/监控；
覆盖RB/JM顺序开仓、RB反手、重启不补旧JM目标、trade/manage接管与每日attempt累加。
零对手量、闭市和非tick首候选不饿死后续；冷启动无新报价/费率仍可按原身份撤单；
WAL预检拒绝且零sidecar。既有模块覆盖多空/今昨/跨日、迟到重复乱序、未知发送、撤单竞态及换月失败。
fixture不是自然输入或真实柜台验收，不把假成交计入正式账户。

## 独立执行安全Review

基线de921797c，未参与实现的代理检查全候选并实跑477项相关回归通过，允许集成develop。
确认修复首候选饥饿、冷缓存撤单及WAL只读副作用三类问题；复核共享全局锁、监控资格和旧codec恢复边界。
最终仅删未使用import并补70%边界测试/文档，独立快速复核结论保持。
未分类原生柜台错误继续全账户fail-closed；不能无证据清除gateway故障或降级为品种负结果。

CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；集成结果看Git/PR。
尚缺全部相关品种收盘后的部署/切换，以及真实持续策略开平、撤单成交、断线/重启/跨日/换月自然验收。
不开自动交易；本次不改变上一轮45夜盘合格/15闭市阻断的历史证据，也不更新为当前现场结论。
