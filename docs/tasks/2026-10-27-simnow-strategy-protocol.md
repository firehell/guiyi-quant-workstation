# HTDY输入复核与普通策略协议修复

## 目标与现场边界

从develop `2147ff8470d6afd3532d47424b3709427918bfa2`隔离开发。现役十服务
v1.16.24/gen33，开盘期间不重启、不改配置、不发布/切换，不启用自动开仓。
原managed工作区被外部清理移除，尚无代码丢失；改在独立/tmp工作区继续。

## 实现

普通策略关联成交独立版本、原生Session身份核验、首笔资金45秒、持久待核及保守预留重锁。
复用旧关联算法，旧NativeFill/人工恢复和v2账户身份不变；普通有界及manage接入，observe仍只读。
准入v3增加当前自然1m独立核验，并修复闭市订阅缺失时诊断异常，仍据实阻断。

## 本地只读证据

21:30与21:47全60轮次分别保留于独立临时诊断目录，未写生产数据、未发provider请求。
第二轮历史32根60m为60/60；当前1m为45连续通过/15闭市等待；60m尚未到本夜首完成端点。
15个旧日Live缺失阻断为AP/CJ/EC/JD/LC/LH/PD/PK/PS/PT/RS/SF/SI/SM/UR。
原始Live不可重建为自然观察；该组下一交易时段的新输入另验。
不得以整体Alert degraded或其他策略完整前缀不足推断HTDY窗口32不合格。

## 验收与验证

22:00:47完成第三轮：45个夜盘品种自然1m连续、22:00完成60m完整，合并计算窗口32根及
逐值1m聚合一致，无恢复隔离；60/60历史32根预热合格。上述15个闭市品种原始Live不可用仍阻断，
等待下一交易时段新输入。三个轮次provider_requests/production_writes均0，first_seen_proven=false。
本地完整清单和原件位于`output/htdy-strategy-protocol-20261027/`，不作为可重放信号。

扩大回归659 passed（包括共享MDS reader）；独立固定SDK真实结构/假API零网络25 passed；
Ruff、secret0、diff通过。高风险独立Review固定代码候选4116abcfd，另跑457项，无Confirmed Issue，允许集成。
后续仅补SQLite实际关闭/重开恢复与持续OPEN禁令两个测试，生产代码未变。

21:55及22:00跨轮保留gen33和原Feed/Live/Alert/Reference PID；行情端点持续推进。
Reference的126个OBSERVATION_GAP与Alert其他策略的warming/lag保留，不能宣称整体健康全清。
新增reader只读验证既有账户完整journal，前后字节相同；没有原生账户查询或账户命令写入。

CODE_COMPLETE/TEST_COMPLETE/REVIEW_COMPLETE；集成以Git记录为准。本次不发布、不切Runtime、
不启用持续开仓、不确认结算或报撤单。自然策略首次观察、真实策略订单闭环及15品种日盘输入另验。

## 可重复验证入口

见TESTING.md“普通策略原生关联成交与当前分钟准入”，以及上述659项组合覆盖的
simnow_supervisor/credentials/host/execution/monitor、htdy_execution、API输入桥/监控和共享reader测试。
