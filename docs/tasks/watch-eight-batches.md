# 八批看盘优化执行记录

基线 develop d49604d24；任务分支 codex/watch-eight-batches。用户已交办全部8批，连续执行，不重复请求批准。
只做开发交付和独立只读预览；不改公式、收益窗口、历史研究资产、缓存预算，不切正式Runtime或补数据。
无关未跟踪产物保留。测试/构建/真实采样串行，浏览器单worker；Node512MiB，构建768MiB。

## 批次进度

1. MDS读取：代码/定向验收完成，最终独审通过。细分Catalog/映射/Session/文件/完整性/解码/装配及次数；消除同次查询重复身份读取和重复provenance读文件。
2. 请求生命周期/内存：代码/定向验收完成，最终独审通过。底层HTTP取消、冻结结果共享、消息300条/2MiB和缓存统计已接入。
3. 刷新/新鲜度：代码/定向验收完成，最终独审通过。首页权威reset突发合并，取消过时读取；隐藏页面不新建Live连接。
4. 首页条件请求：代码/定向验收完成，最终独审通过。稳定响应一次编码并复用ETag字节，首页增加细分耗时；无充分身份不提前304。
5. 收益/研究：代码/定向验收完成，最终独审通过。冻结hash绑定、按Tab读取、取消与明细缓存、容量提示。
6. 响应/渲染：代码/定向验收完成，最终实测/独审见第8批。主图价格投影去重/末根更新、明细有界、四种屏宽回归。
7. 消息：代码/定向验收完成，最终独审通过。扫描批量和转换合并、全结果digest核验、缓存即时预览、游标身份保护。
8. 综合验收：工程验收及独审完成；真实完整收益数值验收因既有来源身份问题待验。提交/推送/集成记录在本节末。

## 实施判断

- 第1批：store已有不可变内容解码缓存和精确Catalog校验缓存，不新增第二套缓存。
  已定位read_publication_provenance在一次调用中读同一文件两次并重复计算hash，先补回归再复用同一已验证字节快照。
- 每批记录测试和不适用项，条件性优化没有证据则不引入；不能以待优化代替当前合同错误修复。

## 第1批验收

- 新增两项回归先观察失败再实现；storage/catalog/read timings/product reader/service定向394 passed，Ruff和diff通过。
- 8003真实JM串行样本：60m两次总958/661ms，权威读取675/524ms；文件读取308/290次，热样本约5ms，
  Catalog约82ms、Session约186ms。日线总656ms，权威读取427ms。是空闲服务样本，不作为P95。
- 现有跨请求不可变内容解码缓存已命中；没有依据再增加第二层解码缓存或扩大预算。
  来源hash复核保留，不把同路径、同mtime当作当前身份。共享耗时collector移至app/read_timings.py，避免存储层依赖Newow包导致循环导入。
- Calendar/Session批量读取本来已存在；本批只消除同一窗口函数重复的exchange事实查询，不缓存跨请求目录事实。
- 分批测试日志：/private/tmp/guiyi-eight-batch1-final.log；只读采样：/private/tmp/guiyi-eight-batch1-profile.json。

## 第2批验收

- Generic行情初始/分页/edge与state、详情研究、SuBing参考、SuBing/HTDY身份资源均传递取消到底层HTTP；切换和dispose撤销。
- 会话结果入缓存时复制一次并深冻结，命中/共享订阅复用只读副本；可编辑的通用createSessionResources默认仍隔离复制。
  测试确认原调用方修改不污染缓存、消费者不可修改、失效的旧flight不借用新body。预算不提高。
- 消息每页最多保留300条、活动页面2MiB，最多8筛选且缓存总2MiB；保留真实游标和覆盖信息并明确显示容量上限，不误报历史终页。
- 开发诊断可取会话/价格/消息缓存的估算序列化字节及条目，不新建产品设置或后台服务。
- Web完整1121 passed/3 skipped；定向83项通过；类型检查通过；浏览器chart-first/reference/runtime18项通过，无截图更新。
- shared身份资源的旧实现只隔离迟到结果，现已补transport abort；冻结结果无消费者写入，18项浏览器验证渲染兼容。

## 第3批验收

- 首页reset连发原来会清空inFlight并立即启动新读取，现保留在途槽位、撤销旧transport、合并为最多一次后续核验；过时结果不接受。
- 后台挂载/手动restart不再建立Live连接，可见后恢复一次。现有hidden停定时器、断开Live、同Bar报价不触发权威刷新继续保留。
- 日周策略/收益当前身份重新验证、缓存价格预览、独立Runtime/目录刷新已在基线实现，不重复改造。
- 25项resource/live/conditional单元通过；类型通过；首页缓存及chart-first浏览器12项通过，无截图更新。
- 跨标签共享连接为条件项：当前无测量证明需要额外协议；第8批验证资源边界，不新增BroadcastChannel或后台任务。

## 第4批验收

- 核对authority_identity只有指标版本、品种/名称/板块及目标日，没有数据修订/映射/质量/Session完整版本。
  因此提前304的条件不成立，继续完整权威核验。目录/能力已共享24小时/5分钟的版本命名空间，无新增60品种逐个请求。
- conditional_json的无volatile响应从构造stable深副本+两次JSON编码改为一次canonical编码，200直接复用同一字节。
  强ETag对应实际响应字节；编码版本前缀使旧表示重新取200；volatile仍使用弱ETag，不能用旧body冒充新读数。
- 首页接入Server-Timing，含读取、缓存、指标计算、投影、编码及Catalog/Session/文件阶段；真实性能在第8批统一采样。
- conditional/home API/projection/overview/timings定向58 passed；Ruff/diff通过；新测试先失败后通过。
- 更新基线遗留CORS用例，使其精确校验既有ETag和Server-Timing两个暴露头，而非遗漏上一轮新增头。

## 第5批验收

- 冻结目录一次读取索引并逐包完整校验；不引入128MiB包的第二层服务端缓存。新回归确认2包由3次索引读取降为1次。
- 初始研究请求由摘要+3类明细改为摘要+当前Tab；摘要新增同次读取的sha256，与明细/完整权益一致才接受。其他Tab/翻页按来源、run_id、sha256、kind和cursor复用现有32MiB预算，切换/离开取消HTTP。
- 研究单类明细1000条、参考记录10000条显示上限，保留服务端真实游标并明确提示，不能冒充历史终页。完整摘要及权益不依赖明细。
- 页面曲线已按panel分部、完整统计和准确交易对象定位（基线已有）；未证实大体积重复交易，暂不新增一套详情API或移除导航所需事实。
- Store/API48项通过；研究/分页18项通过；typecheck通过。浏览器23项初次通过，遗留旧标题/入口选择器已更新；发现并移除重复错误提示后，苏冰8项及受影响6项补跑通过。最终完整矩阵第8批执行。

## 第6批验收

- 盘点主图/辅助/解释/收益：基线已有section拆分、收益可见读取、解释展开读取，研究本轮按Tab懒读取。页面曲线不嵌整笔交易；已完成交易曲线带准确交易事实供定位，未新增无收益的详情接口。大JSON已有gzip，不重复中间件。
- 牛哇结构/比较等显示变化不再重设相同蜡烛、成交量和辅助时间轴；仅最新末根变化或单根追加使用update。历史修订、prepend、清空、策略/周期/品种或chart实例变化使用setData。仅保留每个series一个投影，无增长缓存。
- writer3项覆盖相同价格、末根、追加、历史修订、prepend、清空、身份、BusinessDay和成交量颜色；先失败后通过。typecheck通过。
- chart-first/panes/统一UI浏览器26项通过，覆盖1440/1280/1024/390、正式策略/融合/四实验/通用页面/研究和离线预览；无截图阈值或基线调整。
- 长列表已通过第2/5批有界分页处理，不引入通用虚拟表格。真实响应体积及资源分布留第8批统一测量。

## 第7批验收

- Alert内部读取每批100改为至多500（总上限仍5000），附加Rule/Alignment事实由每批一次改为同请求合并一次。155条用例由两批读取/转换降为一批，各来源实际扫描量随响应披露。
- 不新增绕过来源验证的服务端消息缓存：无独立事实版本能安全避免全部有界重读。保留来源cutoff、高水位、revision/digest、混合排序、服务端搜索和部分失败合同。
- 首屏返回dataset_hash，复用既有cursor中的全查询结果digest。返回先显示5分钟有界缓存，同时重新核验；全digest一致保留已加载旧页/游标/滚动，不用仅首50条相同推导全历史不变。变化替换首屏，失败保留旧快照并明确失败。
- 翻页在合并前校验snapshot和digest，变更拒绝。Web14项、消息后端15项通过；类型/Ruff/diff通过。新鲜度及身份回归先失败后通过。
- 消息浏览器5项通过，返回两页/滚动单项补跑通过；fixture曾每页伪造新cutoff，已修为与正式API相同的冻结快照，并等待异步核验请求。没有降低身份校验。

## 第8批验收与交付边界

- 完整Web：1136 tests / 1133 passed / 3 skipped / 0 failed，命令 `NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test`。原公式/窗口回归保留。
- 精确受影响后端612 passed，覆盖read_timings、product_reader/service/resource_gate/inflight/snapshot_cache、reference_parts/socket_http/page_performance、storage/catalog/homeoverview、home/projection/conditional/messages和冻结研究store/API；工程能力合同3 passed。日志`/private/tmp/guiyi-eight-backend-affected.log`及`guiyi-eight-engineering-final.log`。
- 曾扩大到整个Newow研究目录，720项通过后在无关长时Fraction研究计算中优雅中断；不计为全后端通过，测试RSS约178–182MiB。随后上述受影响集合完整通过。
- `NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build`通过（含vue-tsc、能力生成和bundle topology）。保留既有大chunk警告，不放宽阈值。Ruff、OpenSpec strict11项通过，secret/diff检查及集成记录见末尾。
- 浏览器矩阵62 passed：`ui-unification / market-runtime / market-home-cache / hide-continuous / chart-first-loading / newow-chart-panes / subing-reference / reference-split`，单worker。另按1440×900、1280×720、1024×768及390×844精确视口补跑统一UI矩阵，结果见末尾、正式/融合/四实验、苏冰/HTDY/自由、研究V1/V2、离线/切换/返回与偏好；未更新截图基线或阈值。
- 消息六项浏览器另行通过（首轮5项及返回/滚动补跑1项）；返回页面重新核验、digest不变保留已加载两页和原游标。
- 独立Astra整分支Review确认1项P2：研究分页在途切未读Tab不恢复。已补成功/失败两条回归并修复；复核允许集成develop，无新增Confirmed Issue。完整Web还识别legacy参考适配器依赖空cursor表达容量，已接独立referenceCapped，保留真实cursor且停止超额读取；独审复核无遗漏active UI消费者。
- 能力工程测试原来仅接受JSONResponse；一次编码现返回标准Response，测试改为解码实际Response body后仍交真实Web严格validator，没有删去合同校验。

### 真实只读预览

- 开发API8003（PID29652）与Web5176独立，核对root cwd和单workeruvicorn后重启；未触碰8000/8002或正式Runtime。仅本地只读请求；无RQData、Canonical、DB写入、补齐、重算资产或通知。
- 真实4项通过：JM/RB切换瀑布、20次新浏览器存储价格、手动刷新、12次SPA切换缓存/订阅释放。另1项通过：收益无法核验时展示错误、无收益摘要、保留真实价格图。
- 20次新存储价格P95约1453ms；这是现有开发API样本，并非服务器冷启动/P95长期保证。缓存日线预览样本从挂载到显示约24–34ms；正式60m图仍有4930ms样本，不能称全部秒开。
- 约73.76秒、0.5秒间隔API RSS采样峰值362.8MiB。12次SPA的JS堆样本峰值70.3MiB；会话缓存最高约1.0MiB/32MiB、pending最多2，价格约174KiB/8MiB；离开后共享pending回到0。这不是全天资源保证。原始记录`/private/tmp/guiyi-eight-real-{browser.log,memory.json}`。
- 真实首页bulk 200约5324ms、gzip8041B/原JSON37390B；带匹配缓存体的304约4425ms、body0B。主要时间仍是权威读取5119/4422ms，JSON编码约0.21ms。保留读取验证，不用缺少修订/质量/Session证明的scope identity提前304。记录`/private/tmp/guiyi-eight-home-profile.json`。

### 明确未通过的真实数值验收

- 真实JM及RB完整参考接口都返回503。JM公开错误为`SOURCE_IDENTITY_UNVERIFIED`。同环境、同数据根、未修改develop d49604d24基线源码的临时TestClient复现：chart200、reference503同错误码（`/private/tmp/guiyi-eight-baseline-check.log`）。首次临时路径未绑定repo root的409不可比，已纠正后才作结论。
- 因而本轮**不宣称真实完整收益数值对比通过**；严格对比测试保留失败，没有放宽断言/隐藏为成功。真实页面的不可用状态已独立验证；固定输入数值回归在612项中通过。源身份问题属于既有事实/物化结果核对，按本轮“不补数据/不改历史资产”边界保留EXTERNAL_GATE_PENDING。
- Review已核对此边界，允许工程集成develop；不代表发布、Runtime Ready或数据就绪。

### 收尾校验

- 精确视口统一UI补跑14 passed；最终消息6项+实验2项合计8 passed（`/private/tmp/guiyi-eight-final-target-browser.log`）。
- `python3 scripts/engineering/secret_scan.py --json`及新只读资源测试显式扫描均finding_count=0；全diff检查通过。
- 独立Review最终结论：允许集成develop；SOURCE_IDENTITY_UNVERIFIED的真实数值Gate不阻断本次工程集成，不表示该Gate通过。
- `git fetch origin develop`后远端/本地develop仍为d49604d24，未发现需要合并的其他develop提交。正式发布、Runtime切换与数据处理不在交付范围。
