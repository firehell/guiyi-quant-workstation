# SC 原油历史候选闭环

本地证据归档（2026-10-07）：任务工作树原始输出已移至 `.ai/worktree-cleanup-20261007-233713/sc-candidate-closeout/outputs/sc-candidate-closeout-20261005/`；主仓独立 Review 输出已移至 `.ai/develop-cleanup-20261007/outputs/sc-candidate-closeout-20261005/`。下文命令和原输出路径保留为执行时记录，证据内容未改动。

当前状态：**COMPLETED / CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12**。历史候选总数48/60，正式分钟开放45/60。仅处理SC，固定窗口2023-01-01..2026-09-24、as_of=2026-09-24T07:00:00.000001+00:00，1m仅作为聚合源，验收5m/15m/30m/60m×trend/oscillation/dual。工作树`.worktrees/sc-candidate-closeout`；真实原始证据保存于该树`outputs/sc-candidate-closeout-20261005/`，独立Review在主仓同名outputs/review。

## 数据恢复和成交额精度

[旧处理记录](sc-candidate-pilot-20260930.md)中的SC2303/5m源月SC2303/1m/2022-04 `ATOMIC_PUBLISH_FAILED → ArrowInvalid` 保持原attempt、plan hash与PENDING/retry_allowed=false，未重试。旧4完成/1失败/179未尝试、110新增分区事实保留；旧响应未捕获，原失败根因仍UNKNOWN。旧证据归档路径为`/Volumes/扩展盘/guiyi-quant-evidence/develop-cleanup-20261004-203824/worktree-cleanup-20260930/preserved/sc-candidate-pilot/outputs/sc-candidate-pilot-20260930/`。

本轮一次source-only诊断取得SC2303/1m/2022-04权威10215Bar，零publish/生产写入。当前payload成交额`1.1641532182693481E-10`需26位小数，现decimal128(38,18)拒绝无损缩放；只证明本次响应的精度阻断，不追认旧响应。decimal256 scratch实验已退出实际方案。

owner明确成交额最多18位小数，重视整数部分。采用`rqdata-turnover-truncate-18-v1`：仅turnover超过18位的小数向零截断；已有≤18位数值、整数部分、OHLC、volume、open_interest不变。原始响应先封存，非法/负数仍在截断前拒绝，NaN兼容原缺失口径；物理Canonical仍decimal128(38,18)，无schema migration。该精度实现与SC候选能力在`323e52a7fbfcae0d704852e7c8d60ceeb5e575ab`冻结并独审。

新的forward计划独立冻结并现场核验：184单元=174维护完成+10无缺口，811源=810新外部price逻辑请求+1已捕获诊断响应、3341派生目标。外部客户端内部网络次数未单独计数。每单元native预算、quota前后差、维护锁、O_EXCL intent、raw-before-validation与旧前像守卫通过；43条成交额发生截断。

独立逐字段核对811 raw共8,689,170新增1mBar，四频46物理合约×915月份：5m1,960,824、15m653,608、30m335,795、60m194,604，共3,144,831派生Bar，Decimal200与Session `(start,end]`全前缀通过。2772旧不可变文件bytes保持；217源月扩展保留304,498旧Bar，1907日周文件及Catalog不变。最终6707active中3935新增，旧数据没有被删除或改写。

## 十二个候选资产

八基础与四融合均READY、disabled/generation=0、complete_window_proven=false，完整46owner/45边界与输入身份独立回读通过。5m初始16GB预计划不足在attempt前停止，native精确byte bound为16,063,258,624。5m趋势第一次900秒构建在1,929,216/1,960,869处留下PARTIAL_INTERRUPTED；原900秒预算/hash/revision保留，仅通过native公开once resume续完剩余31,653输入，124新receipt精确读回。不是另建资产或重试未知提交。

四融合分别绑定各自基础revision/seq，最终12流独立全字段回读通过。source final/postapi/postbrowser三个报告整对象一致；旧323专属API/Web已精确停止，实际exit回读确认两PID退出、8012/5178无监听、维护锁0、12流仍disabled/generation0。

## API与页面收尾

旧323 API12/12通过：152矩阵GET+1身份GET均200；compact摘要只证明该层身份、分页/覆盖与hash，不替代完整曲线、SVG或原生409证据。旧浏览器12分钟及D1三个场景全数值/逐图通过；W1与cancel未完成，不宣称完整闭环。多轮失败及每次封存证据保留。

已定位两处产品问题：日周decision_v2解释沿用30秒，而同一日周背景计算在分钟页已有60秒；缓存命中虽重新校验权威输入，却返回接近过期的旧token，后续融合收到GENERATION_CONFLICT并进入重建。采用同一API入口统一策略详情所有周期/section默认60秒、保留显式override（含0）和AbortSignal；缓存仅在fresh reader/fingerprint/proof完整重验后，对同身份、未过期且覆盖全部输入proof的既有token续现有300秒。普通get不续期，expired/changed/replaced token不能复活，绑定请求仍拒绝冲突；不修改公式、价格、收益或缓存预算。

采集器另修同URL已取消peer的响应绑定，并保留bounded诊断。原失败记录及日周errors门禁不变。分钟双策略仅严格初始单一partner reference真实abort时允许一次同URL采集补充XHR，标记ui_composable_received=false，不能冒充Vue已消费或页面警告消失。

最终产品修复冻结于`3f1f538c600e1565996ba36617de3bde1152d1ba`。仅Web策略详情入口的默认超时从遗漏日周section的30秒收敛为60秒；保留显式override（含0）、AbortSignal和全局普通请求30秒。与d656相比services/packages/scripts计算子树完全相同，公式、profile、源数据与12资产身份未变。新API12/12通过，152份矩阵GET全部200（128 strategy-detail + 24 identity），另一次启动identity通过守卫但未单独封wire；compact不是全数组或409证据。

owner随后明确只验证修改内容，停止重复整体采集。d656的17场完整数值/46原图保持各自旧code/raw/hash；3f1的完整重采在两场通过后按owner要求精确SIGINT停止，退出130及Chrome关闭原件保留，未把中断当成业务失败或全19通过。最终只补W1 dual与cancel两场，19个唯一场景/49张原图的差分验收完成，**不是同一新code重新跑全19场**。完整33,251笔CLOSED、全部曲线/SVG、稳定ID/价格/Decimal200以及真实取消、客户端超时、错误frequency的HTTP409与fresh snapshot恢复均独立通过。

W1初始及返回两个导航的产品请求均≤60秒，但串行加载链约90秒；原采集器在加载完成前启动按钮65秒等待，返回还继承away绑定deadline。仅任务outputs内的定向renderer修正等待顺序：initial沿用已有110秒绝对截止；return导航单独建立同长度110秒绑定/readiness阶段，非阻塞等待inFlight/bodyReads/DOM三稳后，继续原selectClosed65秒/waitStable65秒。没有加长110常数、修改产品代码、补XHR或放宽错误/ready门禁；全部失败原件保留。最终initial 89,797ms、return 77,849ms，均在各110秒内；三errors空，W1完整5笔CLOSED/7 SVG点逐值通过。cancel原生场景未修改。

新final/postapi源报告全字节相同`60180a528d5384e76905896d2b934f0bc4a4430960428affcc82ed64459eb98d`，除代码身份外与旧d656全对象一致。按owner增量验收要求，末轮未重复完整source前缀扫描；最终仅真实只读回查12候选stream全字段/revision/seq与已封基线相同、全部disabled/generation0、维护锁0。专属API36139/Web36134及8012/5178已退出，Chrome sc-targeted原生关闭成功；正式Runtime、Scope、通知和账户不变。

限制如实保留：5m dual初始partner超时/页面警告及严格补证XHR的ui_composable_received=false，不能冒充Vue消费；legacy compact未交付history_coverage，不能据此宣称FULL；W1 46<120及29区段warming、震荡0 CLOSED显示“—”，OPEN/换月中断排除已完成收益；视口裁切、密集早期标记及辅助短有效历史保持。独立数值/视觉/资源最终报告为主仓outputs/review中的`sc-differential-final-independent-review.json`、`mixed-code-sc-numeric-closeout-review.json`及`mixed-code-sc-visual-closeout-review.json`，全部原始attempt保留。

## 验证与边界

- 后端新增缓存/服务回归先13项RED，再GREEN；两模块115passed。
- Web最后遗漏回归真实RED（57通过/1失败），修复后六相关文件204passed；vue-tsc、Vite生产build与bundle topology通过，secret scan 0，diff check通过。未重复已通过的后端整体验证。
- 全部数据/候选/采集工具与缓存回归最终输出保存在`recovery/closeout-backend-final-regression.log`；最终1018passed，13.21秒；实际输出为准。
- 独立Review核对精度、forward、前缀、资产恢复、缓存与超时，最终差分19场/49图及精确资源退出全部通过。OpenSpec 10通过/0失败，原件保留。

本任务只证明固定历史窗口候选页面；不证明因果/OOS、完整可执行窗口、正式分钟开放、Runtime promotion、通知或账户交易。验收结论：允许集成develop。此闭环不授权发布main/tag或Runtime promotion。
