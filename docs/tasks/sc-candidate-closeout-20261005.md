# SC 原油历史候选恢复取证

状态：**PARTIAL / DATA_BLOCKED / OWNER_DECISION_PENDING，0/12**。本轮只处理SC，历史候选总数仍47/60，正式分钟开放45/60。用户交办完成原油历史候选闭环；固定窗口2023-01-01..2026-09-24、as_of=2026-09-24T07:00:00.000001+00:00，Canonical1m仅聚合，目标5m/15m/30m/60m×trend/oscillation/dual共12组合。任务产品源码冻结`5f9cfd9117362648d9824a880d4e61e9da768eb9`，工作树`.worktrees/sc-candidate-closeout`。

## 原停止边界与当前前像

旧SC记录见[2026-09-30处理记录](sc-candidate-pilot-20260930.md)。旧唯一campaign已完成SC2302四单元；SC2303/5m的源SC2303/1m/2022-04发布ATOMIC_PUBLISH_FAILED→ArrowInvalid停止，4完成/1失败/179未尝试、110新增分区。旧parent/unit PENDING/retry_allowed=false、plan hash及已提交事实保持，不重试。失败响应与Arrow正文当时没有捕获，**原失败根因仍不能追认**。

旧证据已归档到`/Volumes/扩展盘/guiyi-quant-evidence/develop-cleanup-20261004-203824/worktree-cleanup-20260930/preserved/sc-candidate-pilot/outputs/sc-candidate-pilot-20260930/`。本轮fresh只读Catalog基线确认46主力owner/184依赖、候选0stream、provider_start2018-03-26。七频328dataset/2772active分区。所有2772旧after引用文件bytes仍存在且SHA相同，当前2758partitionfacts精确相同；14个MAIN/SC2611的2026-09活动指针在本任务前延伸至9月30日，旧Bar逐字段仍相同。不把该既有延伸归因本任务，旧110发布保持。

## 一次精确来源诊断，零生产写入

当前原生plan及Session确认失败源月无active、10215个expected端点全部缺失，边界与旧计划一致；SC2303物理完整前缀仍自2020-03-02起，不缩到页面窗口。独立审查后，仅执行一次新的**source-only诊断**，不调用maintenance apply、publish或Catalog写入，不复用旧attempt。

冻结诊断请求SHA `1846d388056fb829826601cf03c91e12032399748a09ec2da42777bdcdd0a4be`，诊断脚本SHA `a1004a5ca18608be0aa0af2cd6821d1ae68836cfcd0aaf80041bf1720b2238b8`：SC2303/1m，权威交易日2022-04-01..29，10215Bar，1024bytes/Bar预算10460160bytes；请求前末hash/bounds/budget严格绑定，O_EXCL诊断intent、禁止重跑。实际nativeadapter仅一次price逻辑调用，完整Session/identity/domain/storage业务校验PASS。账户额度1073741824，before used0、after2576409、账户delta2576409<=10460160，quota_guard=PASS；账户级delta不证明供应商内部网络次数或单请求精确消费。

原生payload SHA `419ff9875eb7fcae0f351b4eb12fe0a3eec4696b4509155d1f0c5b4bfefe530b`。整月只有一条不能无损表示为当前decimal128(38,18)：row1664、trading_day2022-04-08、bar_end2022-04-07T18:30:00+00:00，turnover=`1.1641532182693481E-10`，Decimal exponent=-26。内存原生pa.Table全月复现`ArrowInvalid: Rescaling Decimal value would cause data loss`。因此**当前精确来源的精度阻断已证明**，不是推测为AO/CU同因；新响应不证明旧失败响应相同。

diagnostic-attempt原PENDING作为单次intent保留，diagnostic-result另记DIAGNOSIS_COMPLETE，不能把诊断成功算为维护成功。provider/raw rows和native完整payload在任务outputs保存，原失败attempt不动。

## 无损方案的离线可行性与待定方向

只在任务scratch将turnover改为decimal256(76,38)，其他字段类型保持，10215行逐字段CanonicalBar数值精确roundtrip、Parquet物理table相等通过。该实验不是新Canonical合同或生产schema，不修改源码、Catalog或primary数据。

当前唯一读取器严格要求CANONICAL_SCHEMA，已有Runtime读取新格式会拒绝；因此不能先把scratch编码用于primary发布。后续要继续原油闭环，需决定是否无损扩展共同存储精度、兼容现存旧分区并先验证消费者就绪，再制定独立新恢复计划；不通过舍入/归零、缩窗、删除旧数据或复用失败attempt绕过。已向owner提出“无损扩展并兼容旧分区（推荐）”与“保持当前格式、原油安全暂缓”两项取舍，等待答复。原油闭环目标保留，未启动其他品种、候选build/API/Chrome。

## 实际验证与边界

- `baseline_readonly_v2.py`、`diagnostic_prepare_v2.py`：host只读权威基线及10215端点计划PASS，provider0/生产写入0。
- `diagnostic_capture.py`：实际一次price，native校验PASS、quota_guard PASS、Arrow精度失败复现，生产写入0。
- `lossless_feasibility.py`：离线现格式失败复现及替代scratch10215行无损读回PASS；不启用新格式。
- `seven_frequency_snapshot_readonly.py --output-name seven-frequency-before.json/after.json`：两次实际只读PASS，整文件bytes相等SHA `07eadfb554080e868ebe05da18594117f8dfc83fc859ee6b196aa9464b9d90ee`；2772active事实/文件及1907日周保持。
- `old_preimage_review.py`：2772旧不可变bytes/2758相同pointerfacts/14旧Bar不变的既有延伸PASS。

root最初readonly模板误将execution_options替换、Plan误传Result序列化，以及after尚未完成时的早读，原失败文件/日志和工具输出均保留；均零provider/production mutation，修正后fresh读取通过。独立调查的受限环境DB探针OperationalError不代表生产DB故障，host核验正常。文档变更按引用、diff及secret检查，不机械重复无代码变化的全量测试。

本轮原始证据在隔离树`outputs/sc-candidate-closeout-20261005/`；独立调查及Review在主仓同名outputs的investigation/review。仅历史候选恢复取证，不声明CANDIDATE_CLOSED、正式发布、Runtime Ready、OOS或账户事实。唯一最小下一步：owner决定是否采用无损精度扩展兼容方向；确认后再完成共同格式/消费者验证与SC精确恢复。
