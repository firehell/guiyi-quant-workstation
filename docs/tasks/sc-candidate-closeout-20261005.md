# SC 原油历史候选闭环

当前状态：**PARTIAL，12/12 候选资产完成，最终页面验收进行中**。历史候选总数仍47/60，正式分钟开放45/60。仅处理SC，固定窗口2023-01-01..2026-09-24、as_of=2026-09-24T07:00:00.000001+00:00，1m仅作为聚合源，验收5m/15m/30m/60m×trend/oscillation/dual。工作树`.worktrees/sc-candidate-closeout`；真实原始证据保存于该树`outputs/sc-candidate-closeout-20261005/`，独立Review在主仓同名outputs/review。

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

冻结d656版本真实API12/12通过；fresh Chrome前17场完整数值及46张原图通过，但第18场W1双策略BLOCKED、取消场未采。三个真实initial ERR_ABORTED对应oscillation chart、trend reference、trend MACD，console分别30002/30005/30009ms TIMEOUT；explanation在35465ms实际200。第一轮仅decision_v2超时修复遗漏了日周其余section，故进一步收敛为策略详情入口统一60秒，不修改全局30秒、不改变采集65秒/110秒门禁、不绕过实际错误。失败证据及三次整对象相同的source回读保留；d656专属服务/Chrome已退出，锁0、12流仍disabled/generation0。新增日周三section回归真实RED57pass/1fail，再扩展六Web文件204passed与build通过。后续使用新的冻结代码身份重新运行API和全19场Chrome，不复用旧成功前缀证明新代码。验收包含所有12组合完整CLOSED/曲线/SVG、较早窗口、D1/W1三模式、取消恢复和49原图，W1真实warming与零CLOSED空态须按原生事实披露。当前最终验收尚未完成。

## 验证与边界

- 后端新增缓存/服务回归先13项RED，再GREEN；两模块115passed。
- Web超时回归先RED，再定向68passed，扩展六相关测试文件203passed；vue-tsc、Vite生产build与bundle topology通过，原有动态import提示不阻塞。
- 全部数据/候选/采集工具与缓存回归最终输出保存在`recovery/closeout-backend-final-regression.log`；最终1018passed，13.21秒；实际输出为准。
- 独立Review核对高风险精度、forward、全前缀、资产恢复与产品缓存边界。最终页面、source与临时资源退出证据仍需补齐。

本任务只证明固定历史窗口候选页面；不证明因果/OOS、完整可执行窗口、正式分钟开放、Runtime promotion、通知或账户交易。唯一最小下一步：按新冻结身份完成真实API/Chrome全矩阵验收和最终source/resource回读后更新完成矩阵并集成develop。
