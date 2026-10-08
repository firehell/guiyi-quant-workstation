# v1.12.0 Runtime 切换与页面验收

2026-10-08，RUNTIME_SWITCH_COMPLETE / PAGE_SCOPE_VERIFIED / REVIEW_COMPLETE。用户明确交办运行切换，使已发布14品种在运行页面开放。正式运行根`.worktrees/release-v1.12.0`，exact annotated tag v1.12.0 / commit `2a31a76b414ef607488bd2e2e8131a3ee469b003`，detached/clean；不移动tag、不将develop并行PP代码晋升。

## 实际执行与验收

- 现役原7个应用label和共享log rotator核对，reference worker=false、既有Alert受众2不变。Python/Node依赖冻结文件与旧树相同，复制依赖并绑定新editable/bin路径；复用此前真实build通过的22文件产物，逐SHA相同，没有重复build。
- PP并行真实维护与12个候选资产构建结束、已知mutation进程0后串行切换。render-only通过。调用既有install-local-services.sh的confirm-load、confirm-market-runtime、confirm-alert-runtime、confirm-weekly-audit，各唯一执行exit0。
- Market内部维护guard、唯一promotion preflight通过：before_first_session、trading_day=2026-10-08、operational_count=60、snapshot_count=0；after-market历史交接实际retained。只迁移既有服务，没有启用reference worker或新可选任务。
- installed和loaded的API/Web/Live/after-market/late-provider-recovery/Alert/weekly共7应用label全部同一新root/commit；原调度idle不计失败。local-services-status.sh实际overall=passed，API/Web HTTP200、Runtime health=ok。
- 实际8000版本1.12.0、capability v30/59已回读；新增RS/SI/SC/AO/RU/BU/CU/NI/PB/SN/AL/ZN/FU/SS各一次合法5m trend chart全部READY，共16个成功读回（版本、capability、14chart）。首RS chart误带reference-only history_limit=200得到422，按原生ProductServiceQuery section guard定位后仅修验收请求；原错误事实保留、原响应body未留存，不盲重试或重跑完整168组合/收益检查。
- 实际5173运行页面一次真实Chrome：13自然响应全HTTP200、error/failure0，SS正式5m主图READY/已完成累计曲线及PP仅日周DOM通过；30分块完整传输、三原图真实独审。顶部截图未包含价格图/周期按钮视口，ready/过滤由真实DOM与自然响应证明，不冒称完整图形重采或年化/MDD审计。专属runtime-112 Chrome已关闭exit0，未停止正式服务。
- 旧v1.11.2 exact clean、所有服务配置/loaded迁出、lsof旧树引用0；15份.run历史状态、渲染配置、marker逐SHA归档后non-force git worktree remove唯一退休。之后仅补验受影响service/history status，overall仍passed。tag历史、用户任务树/修改、数据湖、DB、Scope、安全配置和日志保留。

## 证据和边界

证据根`outputs/runtime-v1.12.0-20261008/`（main develop工作区）。包含dependency-and-built-artifact-readback、四mode switch-result、post-switch-services-once、runtime-api-readback-result、chrome-evidence/complete、old-tree-retirement-preflight/result及15份旧运行状态、post-retirement-services。独审independent-runtime-switch-review.json：REVIEW_COMPLETE_RUNTIME_SWITCH，SHA `2ac07fd992b2f437d6035ec6ef7cef7cb7e34ef3b1a8a9713ae7ce571ec9ab2e`。

历史页面范围45→59，共708组合，固定截至2026-09-24 15:00北京时间，1m仅聚合、分钟主升浪/持续更新保持关闭，page_parity=true/executable=false。PP未在v1.12.0 tag与正式分钟范围中。

本轮证明服务版本切换与运行页面开放，不代表首根自然completed Live Bar、盘后维护、周审计或完整60消费者自然业务已经验收，不声明RUNTIME_READY。没有手工运行自然调度、补发通知或新增订单；旧BZ/EG源异常与typed quality、weekly/P9证据限制保留。下一步等待既有Runtime自然业务，按其真实证据验收。
