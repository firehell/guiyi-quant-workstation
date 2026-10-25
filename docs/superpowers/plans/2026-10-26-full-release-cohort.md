# 全量发布与整组升级

Owner已批准：审计当前develop所有未发布合格内容；权威休市窗口短暂停止全部10服务，统一升级到下一个正式补丁；切换验收后保留develop及唯一正式发布树，清理已合并且无引用任务树。初始基线7ed0a2f2b，随后纳入已合入PR480的209ef8ecc；正式为v1.16.1与v1.16.4混合。

实现范围：闭市时Canonical-only纯预热（不造Redis订阅，不改实际信号路径），已知非交易区间支持（未知Calendar/Session仍失败），`--plan-cohort/--apply-cohort-plan`受测入口。冻结旧绑定、配置、Scope、启用、日历、状态；单次attempt与15分钟计划有效期，停机预算600秒。旧所有者全部排空、退出，持OS/维护锁后一次CAS提交全部新绑定，随后消费者先于Feed，最后仅注册日历。保留已有逐服务混合合同限制，不弱化指纹；本次不支持schema migration。

发布集：参考面板、MACD展示、SimNow只读/受控执行工程代码和监控、已有清理及必要部署修复。auto_order=false；无Broker连接、账户创建、真实报撤单或策略阶段晋升。无监控数据保留not_connected/金额未知。

验证：相关后端+执行边界；完整Web/unit/type/build；参考/消息/MACD/监控/首页浏览器；整组切换/超时/CAS前恢复/CAS后未知禁重试/闭市质量与前缀；独立高风险Review；OpenSpec、离线锁、secret、diff。原有旧fixture以现行合同修复，不改产品行为掩盖测试失败。

发布后exact tag/commit/root/gen读回、进程/heartbeat/HTTP/游标/Scope与至少60秒PID稳定。闭市空闲生命周期证明与自然业务证据分开；不声明自然Event/送达或整体RuntimeReady。失败结果未知不自动回滚/重试；预CAS只在old registry明确未变时恢复旧定义。全部服务成功、精确无引用及原件保全后non-force清理旧release树和完成任务树，保留tag/Release。

Implementation ledger:
- Closed预热23项及相关组合287 passed/10 skipped。3个原多周期失败在HEAD内存源码复现，为fixture缺quality-rewarm接口，已只修fixture。
- Cohort状态机16项通过，覆盖预热后过期、安装超预算及postCAS日志IO失败仍停止新工作。六常驻缺启用显式不支持；主机故障58项通过并经独立Review，整组Runtime相关163项通过。
- 未发布执行边界/参考面板223 passed；Runtime+消息+预热133 passed。完整Web1237 passed/3 skipped，type/build/topology通过；OpenSpec12/12、secret0。浏览器旧合同断言按现行入口修复中；旧SuBing/Free金图与本轮未改产品源码失配，保留原阈值及失败原件。32项原生只读与8项SDK宿主无网络smoke通过。
- 运行操作、发布、清理均未开始；需先完成全部Review与检查。
