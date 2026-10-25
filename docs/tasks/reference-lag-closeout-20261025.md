# 48路观察滞后：闭市可处理部分收尾

Owner交办先完成当前能处理的部分：11品种44路Canonical历史续算，以及L四路旧滞后判定。苏冰全量资产继续后置，不扩公式、Scope、Rule、受众、交易阶段或auto_order；不重放观察、不补发通知。

## 根因及代码

33路基础历史刷新保存NEWOW_INVALID_AS_OF、无plan/resume；11融合等待基础。已结束周五夜盘归属周一交易日，历史预算错误要求周一全天结束，实际读取也先整交易日校验、再裁剪as_of，因未来日盘尚未发布而失败。

ActualDominantTradingDayQuery新增仅限aware分钟周期的as_of；MDS仍由同一Session/owner解析构造SeriesQuery，只裁剪end，真实已完成缺口照常拒绝，默认整日/D1/W1不变。Newow预算与实际读取共同遵守截止，不建立第二resolver。L四路已有后续正常观察，持久旧health被直接返回；健康读取现按真实post-start observed端点重评，seed/gap不能清除滞后，冲突/隔离/预热及其他失败优先级保持。没有生产改写持久health。

代码72d0d5c2b；版本候选a96d54146；PR469合main/tag/Release v1.16.1为bc2c43dab2a8ce67038ca3998e74ac6b4a16b3c9，完整tree与已验证候选一致。宿主首次拒绝main merge后，owner明确批准main/tag/Release/Runtime promotion，随后按新增授权执行；未绕过拒绝。

## 实际44路维护与验收

精确AG/AL/AO/AU/CU/NI/PB/SC/SN/SS/ZN × trend/oscillation/main_rise/dual_fusion，60m historical_replay，不含L或forward写入。004维护计划SHA 09217bd1e1e03ecff5b9a7c004b7660019873664d3724c199338fb1134e945ea，绑定代码、当前revision、预算与闭市/下一Session边界。

attempt001在任何drain/intent/写入前因gen23旧控制标记停止；原生should_drain明确只认当前generation，已核对现役gen24/loaded owner后在新004封印旧控制，新独占attempt002执行。正常park Reference原PID96093，刷新线程退出、owner锁空闲；独占native刷新控制锁，33基础先、11融合后逐路fresh plan/hash、commit回调和独立checkpoint。44/44 completed，零provider、零forward写入、零通知。16组全行摘要（4 App表、48 forward的8表、44历史全部旧revision的4类事实）及4组journal/index/cursor完全保持；旧历史revision保留。33项明确纯前置失败控制项在成功后原生移除，完整旧文件保存，其余74项逐项保持，未把它们当作本任务已处理。原PID/gen24恢复active。

另一个新进程44路逐项重读完整来源计划，核对manifest digest、checkpoint及正式API保存指标的夜盘最终端点，44/44 VERIFIED。新健康逻辑独立读取L四路READY，持久旧health仍保留。

证据：output/reference-lag-closeout-20261025/historical-attempt002/completed.json、preimage.json、protected-verified.json、same-owner-restored.json；independent-source-001/completed.json。

## v1.16.1正式运行

原生mixed计划因reference指纹不同拒绝顺序混跑，未执行。独立全停计划4393784dff58d1bc33b87d32052b2a24a3890af141b241dbecb1f1c51b236b72完成正常park、旧PID退出、十plist安装及整registry CAS至gen25。保留retained-only旧盘后历史及失败，不造新current盘后状态。

cold-attempt001最终NEW_OWNER_TIMEOUT：遗漏新树Vite运行依赖，五常驻已active、Web在运行前明确缺入口退出。没有重跑cold、stop/install/CAS；仅pnpm frozen/offline安装144个既有缓存包，downloaded0，由既有KeepAlive启动Web。旧failed记录保留，不补completed；另立独立只读收尾证据。首次两次checker因通用1MiB上限拒绝既有1,475,785字节generation8记录，沿用原计划已审2MiB预算后003通过，未改变该记录。

final-readback-003.json证明10项exact v1.16.1/gen25/bc2c43d、六active/四calendar idle、旧PID退出、Web实际index逐字等于dist。Runtime切换的business摘要只覆盖forward选定字段，明确排除seed_chunk_text/source_evidence/dependency_manifest三类大字段；Scope/Rule/Policy、私有配置及旧文件另由protected核验，不宣称全部历史全列扫描。原journal/index/cursors保持。7次60秒连续样本PID稳定，至少一次Reference健康cycle，既有刷新/通知线程存活；六stdout/stderr均匹配当前日志inode。

正式API676 READY/44 OBSERVATION_LAGGING；L4 READY、44对应独立Canonical历史CURRENT；pending Capture0、各消费者积压0、PG维护占用0、deployment/after-market锁空闲。全局仍degraded：旧原件缺失、暖机、旧盘后失败和自然业务尚待各自验收。

## 实际验证

- 来源/Newow/Reference关联回归：1153 passed、81 skipped；日志测试环境使用隔离GUIYI_LOG_DIR，完整重跑通过，跳过不计通过。
- 夜盘/HTDY闭市来源分类/盘后定向：183 passed。
- exact正式候选来源、健康、Runtime和版本测试：339 passed；独立代码Review定向291 passed。
- 维护操作器15 passed；全停/类型化Feed/单次stop/unknown边界14 passed。
- Web类型/build/topology、UV离线锁、Ruff、OpenSpec strict12、secret scan0、diff通过。代码与实际结果均做独立Review。

## 保留边界

本任务闭市可处理部分完成，未恢复611/2565实时原件，也未把历史计算当实时观察。剩余44路真实观察接续、10/26首H1、自然Event/Push、18:05增量和完整夜盘仍须实际验收；7路真实有效历史不足继续warming_up。苏冰全量历史资产仍后置，不新增定时或后台任务。

旧v1.16.0发布树在新的binding/plist/loaded/进程/cwd引用归零后，按原生retention精确计划b0c077241b6defc5749c720b10027df193304c440f16dd022ff8fe233e73d7c0执行前再次核对，保留5个.run原件及逐SHA，再non-force移除；tag/Release保留，其他任务树未动。证据output/runtime-v1161-20261025/retirement-completed.json。最终独立Review确认所有实际读回通过；不将历史停用的147个DATA_CONFLICT记录混作新增active故障，也不清除旧记录。
