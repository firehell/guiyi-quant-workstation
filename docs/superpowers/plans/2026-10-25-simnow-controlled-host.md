# SimNow前五步连续交付

Goal: 接通原生账户核验、实际费用与收益、执行事实和一次性受控入口，并完成故障回归及独立Review。

Scope: 固定第一套、专用账号、HTDY60m及既有70%规则。owner已允许SimNow盘口仅作执行报价；RQData仍是策略/历史权威。不发布/切Runtime，不启用持续自动交易。

1. Native inventory：复用只读两轮协议，完整性/逐值稳定/身份/交易日/时间/hash校验；原生资金、今昨仓、委托成交映射为账户Readback，未知/对锁/超手/无法解释事实不报空。
2. Fees/performance：仅在同日完整稳定快照差额可唯一归属一笔新成交时由原生累计Commission生成实际费用。多笔/跨日/资金重置不猜分摊，保留待核；账户收益以原生权益和外部现金流为准，与策略参考收益隔离。
3. Execution facts：在固定第一套会话中读取结算状态、合约/保证金/费用预算及盘口；权威Calendar/Session和MainContractMap由共享MarketDataService绑定；自然新完成60m信号由共享验证器生成。
4. Controlled host/CLI：默认只读preflight；明确执行参数、固定一品种一手、有界执行时长与动作预算。无合格自然信号零订单；未知结果不重试；退出保留未平/未知事实，不能自动清仓。接入现有adapter，不另建状态机或隐式晋升。
5. Fault verification：fixture end-to-end、SDK实际结构无网络smoke、原只读回归、风险/恢复/重复/资金变化测试，高风险独立Review修复后集成develop。

外部真实验收：第一套、10万元20261027生效、自然新输入和可交易Session须原生证明；尚未发生不标通过。凭据仅TTY隐藏输入，不从聊天或文件提取。代码和离线验收不等于真实订单通过。

## 完成与验证

五项工程已完成。完整定向212 passed、隔离SDK gateway8项、原只读32项通过；SDK结构smoke及SDK/API依赖同ABI导入均无网络通过。
Ruff、secret scan0和diff通过，独立高风险Review最终允许集成develop。

实施细化：
- 原生回读.at不改写为程序激活时间；只有at<=activated<valid_until才启动。
- 普通FILLED仅暂停动作等完整Fill/Readback，不误触发故障恢复；已知迟到成交先重新锁预留，费用不足仍待核。
- LOCAL_ABORTED是writer内证明未claim的本地事实，不伪造柜台REJECTED；重开可记录但不绕过恢复。
- 仅同日唯一新增成交归属累计Commission差额；跨日/多笔和现金流连续性不足保持明确待核，不引入估算收益。
- Runtime/持续全品种/监控页面不在本次前五步范围；真实first/资金生效/原生订单待现场证据，不由fixture替代。
