# 苏冰输入修复与预热核实（2026-10-21）

状态：COMPLETED。范围为owner交办的前四步：四品种16路分钟物理预热、PR/PX/SF/ZN四路日线窗口、十路warming核实。未扩展为Reference冲突修复或全历史审计。

## 已完成

1. **精确根因**：AL2612、FU2701、ZN2612、PX2612缺少完整上市生命周期分钟前缀；daily维护只补映射主力范围，不能替代lifecycle warm-up。通过最新completed交易日2026-10-21的原生只读计划冻结symbol/physical/frequency/窗口/hash，执行前经独立Review。
2. **分钟修复**：四合约43个月1m目标、320025根输入完成真实RQData下载、质量校验与Canonical/Catalog发布。独立重规划1m零目标后，重新冻结并完成5m/15m/30m/60m共172个月派生发布，派生真实provider请求0。最终20份分钟scope后验计划全为零目标；16路完整物理前缀MDS coverage与共享subing_ths_15m_v3内核重算均valid/ready。
3. **日线修复**：PX2612/ZN2612缺少全生命周期D1，真实补齐22个月、407个预期端点。PR2612/SF2701日期覆盖虽完整，仍含39/1条零收盘价普通Bar；PX补齐后另发现21条同类记录。三次新鲜RQData exchange_daily原始响应逐合约、日期、重复和七数值核对后，使用既有NonpositiveCloseFact候选及原生原子apply转换9个分区共61条事实，保留原时间身份、七数值和其他Bar。四日线原生quality window/evaluator重算均通过，有效段分别PR121、PX157、SF178、ZN203根；旧质量断点不进入新段计算。
4. **十路warming核实**：完整typed生命周期及质量并集读取通过，内核valid=true/ready=false。九路周线BZ25、EC21、PD27、PF33、PG33、PL19、PR31、PX33、RS5根，均截至10/16；RS日线20根截至10/21。它们属于真实有效段不足，不补造、不延用断点前状态，不标READY。

## 实际验证

- 原生warmup定向：`pytest .../data_foundation/test_historical_data_manager.py -k warmup`，75 passed /142 deselected。
- D1 quality plan/candidates/apply及SuBing quality rewarm：46 passed。
- `output/subing-input-repair-20261021/verify.py` 实际只读exit0，结果 `REPAIR_INPUTS_VERIFIED`：20路重算通过、10路真实warming、61条质量事实、20份分钟零缺口计划。
- 独立Review实际复核两个质量plan/manifest及候选Parquet/sidecar哈希，并核对最终30个唯一symbol/frequency与数量，无阻塞项。
- 最终独立核对61条fact.bar_end与原Bar完全一致，原文件哈希未变、其余Bar完整对象逐值一致、原日期端点完整保留。正式API身份仍十项matched，v1.15.16，整体health仍degraded。
- 实际数据维护：基础65分区发布、派生172分区发布、质量9分区替换；其中部分D1分区先补齐再质量替换，不将次数相加冒充唯一分区数。原生基础provider_requests65，质量来源查询3，派生0。

## 执行与恢复边界

全部执行沿用exact Runtime树 `.worktrees/release-v1.15.16` / `c559eb7a594dea5189c7a630b010a284032e89f4` 的原生维护和质量模块。基础与派生每单元保存精确plan、前像和一次intent；维护锁内重算hash后执行，显式频率失败即停。质量两个scope分别preflight后单事务切换全部目标，严格MDS及独立postcommit读回均通过。没有失败或未知提交，没有重试已消费attempt；旧不可变文件及前像保留。生产数据回退需要重新核对精确对象与质量合同，不能盲目恢复旧零价普通Bar。

本轮未改策略公式、收益口径、Rule/Scope或运行配置，没有修改应用源码，因此没有新版本发布或Runtime切换。没有重启、手工创建Event、重放历史观察、补发通知或候选晋升。自然Runtime处理与手机送达不由独立重算证明，保留 `PENDING_NEXT_NATURAL_TRIGGER`，未人为清除既有失败状态。

盘后18:05自然任务已passed不等于本次输入问题原本不存在；它的消费者失败报告保留。盘后Live已自然清理，不能把无subscription的Live专用诊断报错当作新生产故障；最终分钟验收使用MDS完整物理Canonical前缀及权威expected endpoints。

本地完整证据：`output/subing-input-repair-20261021/`。`base-attempt001`、`derived-attempt001`、两组`quality-apply-attempt001`均已消费，不得直接重跑。原始来源响应只在本地证据目录保留，不随Git发布。

唯一下一步：由下一次自然completed observation确认受影响分钟Runtime恢复；D1由下一次自然Canonical触发确认。未新增监控、后台任务或通知。Reference积压及冲突仍属后续独立工作。
