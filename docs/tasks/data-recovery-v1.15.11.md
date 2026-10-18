# 全历史、计算与参考交易恢复及统一发布

目标：修复本轮确认的数据/运行阻断，包含 v1.15.10 已发布改动，形成一个新的正式运行发布树。用户2026-10-18交办覆盖必要数据修复、发布、切换及旧发布树清理；不改变策略公式、Scope、受众、交易阶段或 auto_order=false，不补发历史通知，不删除 tag/Release 历史。

基线：develop 7731bcd81；现役 v1.15.7/b84e723a8/gen19/schema0051；已发布 v1.15.10/79c6ed573。原工作区未跟踪研究/恢复证据保留。任务分支 codex/data-recovery-v11511 独立工作树。

顺序与验收：
1. 原生只读定位 weekly audit 19/60失败，修复根因及不透明诊断；完整60品种审计输出精确缺口，不用 finding_count=0冒充完整。
2. 按新鲜精确计划串行修复物理合约历史；重算hash、质量、维护锁、原值/不可变文件保护、已提交与未知attempt分类和独立MDS读回。旧过期/disabled准备不能直接执行。
3. 恢复 historical source、fusion依赖和212 forward冲突，保留旧观察/Event/发送事实；核对全720就绪和策略逐路覆盖，缺失自然信号不得伪造。
4. 定向测试、高风险独立Review、secret/diff/build/必要集成和真实页面/API回读；只集成已验证修复。
5. 新补丁版包含v1.15.10；验证后main/tag/Release、schema0052迁移与正式服务切换分别留证；自然验收未发生时如实保留。
6. exact binding/plist/loaded/PID引用全清零后，按原生retention cleanup-plan清理旧发布工作树，只保留新现役树；不删除行情、DB、研究证据或Git发布历史。

实际执行结果随进展补充；本文件不是完成声明。

## 10/18 数据修复与定位进度

原生contract_warmup真实执行49个精确scope全部COMPLETE，919个目标分区、443次逻辑provider请求；每个scope独立postplan零目标，旧文件不可变hash保持。证据位于主工作区output/data-recovery-v11511-20261018，各apply目录保留intent/provider/request/result/complete；无stopped mutation attempt。随后发起原生60品种全历史审计full-history-audit-001，运行中不计完整通过。当前主力七周期final dry-run独立扫描同时进行。

weekly audit原来吞异常且零finding易误读。补齐findings_complete、partial_finding_count、failed_symbol、error_stage及安全分类error_type；旧schema读取兼容。定向56+126测试通过，Ruff/secret/diff通过，OpenSpec strict11通过；独立Review无Confirmed Issue。旧I单品种审计44.29秒通过，原19/60失败技术原因尚未复现，不虚报修复历史失败。

额外定位historical refresh 240 blocked：177 H1 SOURCE_CHANGED为旧冻结plan与当前输入漂移，3 LH scope drift，60 D1 fusion为saved基础manifest与新鲜输入不符。独立只读A复现十项trend/osc公共lineage相同，但SavedFusionSources保存的base在四项输入/Session/rank1不符；不移除边界或源校验。恢复须native fresh advance/COW基础资产后再fusion，并保留旧refresh前像。当前active revision中original-conflict typed凭据为0；旧output49产品计数不可当当前已完成。新archive seal只读验证672个H1原始观察/60品种完整hash、length、tail、原始字节，未导入或replay。任何新Transfer仍须实际四writer与Canonical fence及apply内重新核验。
