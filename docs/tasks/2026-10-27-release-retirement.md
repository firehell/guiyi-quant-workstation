# 正式版本统一与发布树收敛

Owner交办：从已发布v1.16.21形成一个最终补丁，十服务整组切换并验收后，将旧发布树收敛至唯一现役树。
独立SimNow、数据库/Redis、行情数据、账户、Scope及auto_order=false保持既有边界。

## 实现与候选检查

历史binding使用显式历史reader和有效封存索引；活动binding、安装与进程仍执行原严格身份校验。
`runtime_retention closeout-plan`生成精确证据清单；`seal-closed --plan`在部署锁内复核并原子封存；
cleanup同时检查服务、进程及未闭合恢复引用。封存依据原件typed关闭图重推，不信任索引中的闭合集合；
正常cohort在首个effect前保存私有计划，旧attempt不补写。只封存必要.run字节，保留所有旧unknown原件。

一次集中定向组合：historical_identity、retirement、retention、bindings、cohort、cohort_host、
cohort_forward_recovery、stopped_recovery、cohort_recovery、receiving_readiness、feed_halt_recovery、
reference_trading/receiving_liveness：**409 passed, 1 skipped / 24.00s**。
跳过项要求本轮一次性Redis；本次未改变接收SQL/Redis算法，沿用上一步真实隔离PG/Redis证据，不再创建容器重复验证。
Ruff、`uv lock --check --offline --project services/quant-api`、diff检查通过；新增文件秘密模式扫描无命中。
测试完整命令与输出：`output/recovery-preflight-20261027/controller22-tests.txt`。

旧8树只读ignored清单除依赖/构建/测试缓存外，只有v10/v14的10个.run标记或历史文件，历史SHA均与当前字节相符。
清单：`output/recovery-preflight-20261027/retirement-marker-inventory.json`。
回滚按保留annotated tag/exact commit重建，禁止force删除、重写tag或复用失败attempt。

独立安全Review无未关闭Confirmed Issue，允许进入release candidate。现场Gate仍须实际执行。

## 现场结果

v1.16.22已经PR522发布，exact main/tag d2cc94382ba4158669d33ea549eb4d28d9a646b2。
一次原生计划bf91a6899a79723efb217a0e12c56ae354e3a8691ff7fbb4a8055f5c2e334f00在17:40:53
停服前预热取消，effects为空，错误CANDIDATE_WARMUP_FAILED；未重跑该attempt。
17:43独立读回十服务仍v14/gen31，六常驻原PID active/fresh、API/Web200且来源v14。
旧失败原件及全部发布树保留。

一次Reference只读分段诊断65.34秒，固定码SUBING_REFERENCE_DATA_UNAVAILABLE；只读metadata定位PD2612
10/27日线physical_contract_replay/REPLAY_ENDPOINTS_MISSING。不能倒推bf91未记录的确切失败原因。
既有canonical要求区分Session完成与18:05发布，但SuBing forward漏用Newow已有的publication边界。
后续补丁提取共享MDS publication resolver并补SuBing forward专用窗口，普通页面窗口与预热fresh/saved/seed语义不改；
旧欠期、物理数据、owner及质量仍fail-closed。固定服务/失败条件/白名单码写入新预热失败状态，预算不变。
v22 tag保持原样，修复进入v1.16.23；临近18:05时等待自然盘后任务释放窗口，不抢维护锁。

受影响组合221 passed；两项旧生命周期用例因默认日志目录不在sandbox内失败，使用隔离GUIYI_LOG_DIR后仅补跑两项，2 passed。
新增CLI诊断后仅补诊断模块8 passed。Ruff、离线锁和diff检查通过。
独立安全Review无未关闭Confirmed Issue：允许进入release candidate；publication/typed接收/预算均未放宽。
