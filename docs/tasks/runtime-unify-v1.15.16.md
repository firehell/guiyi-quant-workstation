# v1.15.16 正式运行版本收敛

2026-10-21，owner交办正式运行统一到一个版本。本任务执行实际恢复和冷切换，没有修改策略、收益、账户或交易阶段。

## 精确身份与执行

目标tag `v1.15.16`，commit `c559eb7a594dea5189c7a630b010a284032e89f4`，generation `22`，运行根 `.worktrees/release-v1.15.16`，schema `20261015_0052`不变。十项binding、installed/loaded配置及六常驻进程身份已经双轮只读核对；四项calendar空闲。API8000返回1.15.16，Web5173 index与该发布树dist逐字一致。研究API、Web代理与冻结snapshot身份一致，576格冻结结果可读。

原Live与Feed协作drain分别遇原进程退出及KeepAlive替代PID，原失败attempt保留。对旧PID已退出、新PID精确park/锁释放、输入原像与映射身份独立核对后，分别消费原token一次恢复；没有盲重试drain或补发通知。旧Feed未提交buffer不能证明完整，保留 `OBSERVATION_GAP_UNVERIFIED`。

冷切换plan hash `a84c49ed61c21b97c3cf685f616e522a27380198b2e4a73f625b3f68f131e3b2`；drain、stop、install完成。start十项effect各intent/committed一次，最终即时owner采样失败 `DELIVERY_SWITCH_FINAL_OWNER_NOT_FRESH`，原attempt保持失败，未重复启动。版本切换事实与最终验收分别记录。

## 实际验证

- 冷切换caller离线测试：191 passed。
- Runtime bindings/deployment/handover/fault-recovery定向：54 passed；runtime entry/handover：19 passed。
- exact发布树离线依赖安装与Web build通过；576份冻结packet按index逐项SHA核对通过，总计1,158,279,739 bytes。
- 独立Review核对十项正式身份、六PID、一次执行日志及只读验收脚本，无阻塞代码项。
- 最初两次只读验收停在 `DELIVERY_SWITCH_HISTORICAL_FIXED_DRIFT`，原失败保留。原caller只允许disabled historical active revision的五个进度字段，未包含三条既有未激活candidate的原生续接。
- 精确调查证明仅ZN 60m trend/oscillation/main-rise三条既有candidate各seq5→6、旧batch全前缀不变、expected5、pre等于旧post、manifest不变且through为空；stream仅row_version各+1。将这三组字段在内存还原后，完整stream和revision表分别与sealed哈希逐字一致，未改变health、active revision、身份或Scope。`historical_refresh.py`已有失败重建计划严格同输入续接路径；独立Review确认可用单独读回证明，不能修改原caller或将原attempt改成成功。
- 后续scan继续处理其他既有candidate，原三PK/null-only验收也按约束拒绝，失败保留。候选实际分批计算存在同manifest下历史computed_through单调前推。最终独立证明限定冻结时已存在且未激活的candidate、每条仅追加一个连续batch、旧prefix不变、manifest相同、through双方为空或双方非空且单调；按各旧endpoint逆变换后两张完整表必须匹配sealed哈希，其他所有事实仍逐字保护。此证明不修改原caller、不允许新增candidate或晋升；增量独立Review无阻塞项。
- 最终独立版本验收 `version-convergence-readback.json` 为 `VERSION_CONVERGENCE_VERIFIED`：十项精确身份、六PID双轮稳定、API/Web与研究实际读取通过；固定时点720行完整health逐字等于sealed，journal与Live原像逐字相同。
- 完整业务数据库验收未通过：后续原生候选持续推进，扩展证明仍停在两表摘要断言，尚未逐项完成全部变化解释。不得将初始三条的已验证解释推广为全量通过；保留readback001–005失败日志，不声明 `RUNTIME_SWITCH_VERIFIED` 或 `RUNTIME_READY`。版本统一完成与业务验收未完成分别报告。

## 保留边界

切换前Reference完整矩阵720 enabled：480 READY、200 DATA_CONFLICT、40 OBSERVATION_LAGGING，pending Capture0；不重建或掩盖冲突。worker瞬时blocked计数不替代完整矩阵。原盘后成功属于旧版本历史，新版本自然Bar/Event、盘后业务与手机实际送达尚未证实，不声明 `RUNTIME_READY`。

未启用持续Paper、Shadow、Broker或订单；未回填、重放、补发或增加后台监控。仅为显式冻结研究结果根增加非秘密配置键，原配置字节和权限保留；按记录的postimage校验后移除该新增键可恢复配置。旧发布树保留用于证据及回退；任何再次切换需重新核对现场，不复用本次已消费attempt。

本地证据位于 `output/runtime-unify-v11516-20261021/`，包含冻结caller、每阶段记录、配置前后哈希、输入原像、冻结结果核对及独立Review。既有output和失败证据未清理。

## 交付结论

正式运行版本统一完成；完整业务验收为PARTIAL。没有重复执行start，也没有将原失败attempt改为成功。唯一后续事项是完成既有历史候选后台推进的全量证据核对，再按自然事件独立验收业务；不新增定时监控或通知。
