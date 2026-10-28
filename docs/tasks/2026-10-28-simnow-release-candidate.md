# 独立SimNow运行候选发布准备

Owner交办第二步：固定并发布候选、无Broker预检；不切正式十服务，不连接柜台或读取Keychain，不启用trade。

候选从v1.16.28隔离，仅纳入冻结f2e6cf347的76项SimNow功能、测试、监控及必要输入依赖；不合入其他develop变化。Reference发布优先，版本号在其完成后按最新远端补丁确定。

精确准备候选Python568 passed（38.96秒）；固定Mac SDK假API无网络25 passed；前端10 passed；type/build/topology通过。独立安全Review另跑313项Python及前端10项，通过；无Confirmed Issue。旧账本/模式限制/未知订单和trade双开关保留。

本机plist仍指向旧continuous.private.json，该文件不存在。原state_root仅保留STOPPED监控文件，未定位原账号四库。生成enabled=false且保留原账号指纹/状态根的候选诊断配置；schema2既有账户校验直接拒绝，--check/render/preflight均未通过，不创建或复制四库，不初始化账户、不改权限或现有配置来绕过。

这是独立关闭的SimNow候选，不是Market Runtime自动交易能力。代码发布与部署阻断分别记录。发布后仍需原配置/四库有来源恢复及新鲜只读核验，才能进入第三步；不从旧空仓记录推断当前柜台。

本记录只证明准备候选。Reference新main完成后必须再次检查依赖交集、最终版本和精确候选验证，再合并/tag/Release。运行、自然信号及交易均未验收。
