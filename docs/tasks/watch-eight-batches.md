# 八批看盘优化执行记录

基线 develop d49604d24；任务分支 codex/watch-eight-batches。用户已交办全部8批，连续执行，不重复请求批准。
只做开发交付和独立只读预览；不改公式、收益窗口、历史研究资产、缓存预算，不切正式Runtime或补数据。
无关未跟踪产物保留。测试/构建/真实采样串行，浏览器单worker；Node512MiB，构建768MiB。

## 批次进度

1. MDS读取：代码/定向验收完成，最终独审待第8批。细分Catalog/映射/Session/文件/完整性/解码/装配及次数；消除同次查询重复身份读取和重复provenance读文件。
2. 请求生命周期/内存：代码/定向验收完成，最终独审待第8批。底层HTTP取消、冻结结果共享、消息300条/2MiB和缓存统计已接入。
3. 刷新/新鲜度：代码/定向验收完成，最终独审待第8批。首页权威reset突发合并，取消过时读取；隐藏页面不新建Live连接。
4. 首页条件请求：代码/定向验收完成，最终独审待第8批。稳定响应一次编码并复用ETag字节，首页增加细分耗时；无充分身份不提前304。
5. 收益/研究：待做。投影复用、准确记录定位、冻结元数据/摘要/明细和分页读取。
6. 响应/渲染：待做。消费者字段盘点、详情懒读取、局部更新、长列表与窄屏测量。
7. 消息：待做。扫描量/分页、来源游标与搜索覆盖、首屏核验及缓存限制。
8. 综合验收：待做。跨页面/尺寸/异常、长时资源、测试/Review/commit/push/develop/预览。

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
