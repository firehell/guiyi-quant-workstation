# v1.12.0：59品种历史分钟发布

## 已验收候选

2026-10-08，RELEASE_CANDIDATE / TEST_COMPLETE / REVIEW_COMPLETE。冻结代码 `88aa1a654f235ab5b7d41a9ccc1c538bce163fb6`，版本1.12.0、capability v30。main/tag/GitHub Release尚未执行；实际发布身份由后续交付记录补充。

新增RS、SI、SC、AO、RU、BU、CU、NI、PB、SN、AL、ZN、FU、SS，正式候选范围45→59，新增168、合计708个5m/15m/30m/60m×趋势/震荡/双策略组合。PP不纳入本版；并行PP纠偏提交不进入本冻结候选。固定截至2026-09-24 15:00北京时间；AO起点2023-06-19，其余新增品种2023-01-01。1m仅聚合，分钟主升浪与持续更新保持关闭。

## 实际验证

- 后端定向首次694通过、2个旧FU拒绝断言失败；修正后只补验受影响3项，全部通过。API批次首次79通过、2个旧FU拒绝断言失败，修正后只补验2项通过。原失败记录保留，没有重复整批。日志为backend-targeted-once、backend-affected-recheck、backend-api-once、backend-api-affected-recheck。
- Web实际`node --test tests/newowCapabilities.test.ts tests/newowProductTypes.test.ts tests/newowFusionPanel.test.ts tests/newowExplanationPanel.test.ts`：106通过；最后仅`node --test --test-name-pattern='v30' tests/newowCapabilities.test.ts`：3通过。原始CommandExecution封存于original-command-evidence.json，未重跑。vue-tsc/Vite build/bundle topology通过，原动态import warning保留。
- 工程一致性29通过，OpenSpec10通过，Ruff、diff、secret scan零发现。
- 唯一fresh原生只读资产读回通过：56源窗口、168完整保存态、112真实融合伙伴边，source fingerprint匹配既有manifest，全部READY、disabled/generation0，complete_window_proven=false保持；零provider/零写入，未重聚合。
- 唯一正式API读回121次：114 HTTP200、6精确409、1精确422；112基础与56融合共168组合。389859 CLOSED完整原响应Decimal200累计/价格回报/稳定身份独审通过；基础覆盖108 FULL、4 PARTIAL按真实区段保留。API v2本地重复retry参数在GET前失败，原件保留；v3初始化定向测试后执行，不重业务请求。
- 正式Chrome：首脚本错用未注册/market/detail，实际零业务请求，失败原件和现存notfound DOM保存。修正为原生/market/chart并强制workspace/frequency/chart-ready/自然capability就绪，原110秒首屏与65秒曲线门禁不变。新精确导航意图13自然响应全部HTTP200，错误0/失败0，SS正式5m与已完成累计、PP仅日周按钮通过；30分块完整封存与三原图独审通过，没有额外GET或mock。SS/PP顶部截图未包含价格图或周期按钮视口，其ready/controls由实际DOM及自然响应证明；累计曲线截图7847 CLOSED、708.44%可见，不冒称逐品种全图重采或完整状态机/年化审计。
- 专属Chrome已关闭exit0；API/Web仅严格PID+argv+cwd+唯一监听验证后SIGTERM，exit143，8013/5179空闲；临时13字节npm配置按SHA删除。首退出guard因lsof附带f字段在信号前停止，typed FD修正后唯一发送，原零信号失败保留。现役服务与PP任务未触碰。

## 证据和边界

证据根：`.worktrees/release-59-products/outputs/release-59-products-20261008/`。登记historical-14-asset-registry.json、fresh-14-source-assets.json、api-full-v3/summary.json、chrome-full-v2/smoke-complete.json、cleanup-exact-result.json及各independent审查报告。原逐品种闭环仍绑定各自exact code；SC差分收尾、SN-v2、legacy预热/零CLOSED/PARTIAL/视口限制保持，不冒充本版重跑全部页面。

page_parity=true/executable=false，仅历史页面参考；不证明因果/OOS、Paper、账户收益、自然Runtime业务或完整融合状态机。此次仅发布，未切换运行；现役仍v1.11.2，保留被服务引用的旧发布树。Scope、operational、Rule/audience、auto_order=false及reference worker关闭保持。
