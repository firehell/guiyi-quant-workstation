# BU 沥青历史候选恢复

状态 CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；历史51/60、正式45/60。从已闭环 RU 的 develop 92ba31aa0 创建独立任务区，BU 单品种准入代码冻结 12e97e9c96ea40983718e48b0b73990a58435818。窗口 2023-01-01..2026-09-24，as_of 2026-09-24T07:00:00.000001+00:00；1m 仅聚合，验收 5m/15m/30m/60m × trend/oscillation/dual，12 个私有历史候选组合。不开放正式产品，不改 Release、Runtime、Scope、通知或交易。

旧 BU attempt 保留：120=4 完成/1 已知失败/115 未尝试。1712 旧文件完整保留；BU2306 已提交 95 新文件、BU2307 已提交 July/Aug 1m+5m 四文件，当前前像 1811 文件。失败 BU2307/1m/2022-09 原始 payload 7125 行，两条 turnover 超过 18 位小数；按既定 rqdata-turnover-truncate-18-v1 向零截断，真实 scratch publish/readback 通过，价格、量、持仓和端点保持。

120 单元原生 dry-run 通过。冻结计划 SHA 9984cbab7542b82cb38723bfbea7ba4610329a90cfd41df277773d2efd797f63，11 份引用；30 物理合约，最多 396 源请求、1623 派生目标，最大单元估算 159974400 字节。总体理论预算 2707568640 字节超过账户剩余 1064259979 字节，不能保证整轮完成；逐单元锁外/锁内实时配额、实际增量、精确前像、旧 Bar 保持、异常停止与禁重试守卫不变。独立 forward 审查 PASS 后执行唯一新 attempt，不复用旧失败。

准入定向 API 5 passed/220 deselected，Web 1 passed，任务守卫 4 passed；一次 Web 类型/Vite/production bundle topology 通过。输出保存在 outputs/bu-candidate-closeout-20261006/，旧证据保留。仅补验本次新增、修复和必要候选证据，不重复已完成的全量检查。

## 实际修复与一次数据验收

唯一 forward exit0，120/120=111 修复读回+9 NO_GAP，396 真实源请求/1623 派生目标/84 行截断，无失败重试。账户读取从9481845到27088011字节；账户级增量不冒充任务归属，所有单元估算守卫通过。1811→3697 文件，1886 新增/133 扩展/0 删除，1678 active 不变；161272 旧 Bar 和1052 日周文件/Catalog保持。396 raw、2522340 行与真实物理1m全部字段、端点、交易日独立一致；整数部分不变。

唯一 data_readback_once.py exit0，四频原生聚合全部通过；独立 Decimal200 全物理前缀一次 exit0：5m622806、15m207602、30m108356、60m63288，共1002052 Bar，每频484物理合约月/30owner。已封存来源前缀和保留证据，后续最终状态/API/浏览器只绑定这些证明，不重复全源扫描。候选构建与页面验收已全部完成。

## 候选资产

独立数据整体准入 SHA b15e14a8864b7405d283d2a39150805d013b1142108c837a787147aa38e2e1d3，REVIEW_COMPLETE_ALLOW_BU_CANDIDATE_ASSET_BUILD。build_assets_once.py 唯一串行12 native plan/apply exit0，无失败/resume。final_asset_readback.py exit0，12 READY disabled/generation0；完整 saved manifest/source hash/native plan、stream/revision/seq/cutoff及四对融合依赖一致。source_prefix_revalidated=false，复用封存数据验收证明。API与真实页面验收已全部完成。


## 最终页面、数值与退出验收

独立资产审查 SHA 9e6b9bd2b2a5a78e4384537a1271a8c3826ba5d1709437e695078506802d9704 通过。API readback.py --execute 唯一 exit0，12/12 READY、152 保存 HTTP200（128 detail/24 identity），请求前完整BU矩阵、分页、coverage、曲线与融合依赖通过；独审 SHA 8c6df095f372fcf663e9b37387e7db2003b6d1a89b697ee32e286fc546fbb68e。native preflight --execute-get exit0。

真实Chrome capture_once.py 唯一 exit0，19/19 场景、49原图，无失败重采。native index PASS/audit NUMERICAL_PASS_VISUAL_PENDING；独立 numeric 唯一 exit0，18完整数值场景+1真实取消/clienttimeout/错频409/fresh恢复，22179 CLOSED 逐笔价格/稳定ID/收益、Decimal200全部累计与SVG一致，whole SHA 6be4675bec7e6e6c7dfb175e59a9d23ea1f3859255aa22c8595f93b1704ef416。49 actual PNG 每张一次 view_image 全部通过，visual SHA 6ed15dfc3d9c2ee9cb170bce05dab82ebb59757a148bef20fc7155c8c7db95c4。

W1真实44/120 Bar预热、趋势/震荡/双策略分别7/1/10 CLOSED，保持实际边界；task-only W1 dual等待沿已审SC/RU readiness（initial/return110秒、原65秒按钮/稳定门槛），无错误标准放宽。OPEN/换月中断浮动不计完成收益，密集标签、earlier右空白、视口裁切与legacy OHLC悬浮遮挡如实保留。日周为真实封存XHR；页面零成本参考不代表OOS、可执行收益、完整状态机或自然TTL证明。

API71983/Web72114停止前两次核对command/cwd/独占端口，精确SIGTERM；专属Chrome bu-candidate close exit0。targeted_exit_readback.py 唯一PASS：两PIDgone、8012/5178free、维护锁granted/waiting0、12完整stream/revision/seq与final相同，disabled/generation0。source_prefix_revalidated=false，末轮仅12状态与资源，不重扫全源。

最终独审 SHA 7ec961cc429161ba5132f6812734aea3552c519e6c0aaaf54b249c87c3fa76b2，REVIEW_COMPLETE_CANDIDATE_CLOSED。全部验收通过，无未完成外部Gate；旧失败与部分提交完整保留，无回滚或生产重试。允许集成develop，未正式开放、发布或晋升Runtime。下一最小步骤 CU 铜。
