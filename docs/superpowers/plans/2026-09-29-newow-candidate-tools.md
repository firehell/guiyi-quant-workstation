# Newow 候选验收工具两批实施计划

> For agentic workers: 使用 executing-plans 顺序实施；任务授权按 AGENTS.md，不重复请求已交办方案批准。

Goal: 将已验证候选验收工具参数化，提前发现辅助错误，并统一真实采集、证据索引和离线验证。
Architecture: scripts/newow_candidate_tools 为轻量仓库工具，复用 native 公式、preview、资产与行情入口；不新增生产写入执行器、resolver 或自动恢复。原始历史 outputs 保持不变。
Tech Stack: Python 标准库、既有 quant-core、已有 Playwright CLI；不增加依赖。
Spec: owner 本轮明确交办前述方案第一批与第二批；P7 canonical 见 2026-09-19-newow-intraday-roadmap.md。

## Global constraints

- 一品种、固定四分钟周期三模式，1m仅聚合源；schema/窗口/源码/origins显式冻结。
- 不改变生产数据、公式、source身份、Runtime、Scope、通知；只读preview必须真实身份校验。
- 证据排他创建、限定输出目录、失败原样保留；旧attempt和原始输出不得覆盖。
- 独立数值、视觉与实际现场验收分别报告。历史保存证据验证不冒充新Chrome运行。

## Review focus

错误服务/品种/代码或微秒时点；缺前置资产/身份；输入路径逃逸或symlink；曲线内部点/交易ID篡改；null/零CLOSED、分页或恢复缺证据。

## 第一批

- [x] context.py：严格 Candidate 参数、冻结工作区与实际导入 guard。
- [x] preflight.py：实际只读preview identity/capability校验、原生日周identity准备、资产依赖门禁。
- [x] stages.py：只验证前置证据，不能自动重试或创建生产attempt。
- [x] cli.py：prepare/preflight/check 阶段入口；输出保护/缺文件自检。
- [x] RED/GREEN：错误identity、未知capability、缺依赖、timestamp精度、路径保护。
- [x] 第一批独立Review、真实原生identity和保存SM/CJ预检验证后提交。

## 第二批

- [ ] browser resources + collection.py：固定JS与JSON配置，minute组合连续采集functional/full/earlier，legacy/recovery独立场景。
- [ ] curves.py/audit.py：完整Decimal/ID/SVG、section/window/token和记录绑定，缺门禁不通过。
- [ ] evidence.py：排他写入、完整索引、SHA与identity核查、视觉待审状态保持。
- [ ] RED/GREEN：错品种、漏ID、内部曲线点、快照/窗口/source不匹配、null/空曲线负例。
- [ ] 真实历史SM/CJ保存证据离线验证；collector启动/资源语法与CLI dry-run，不执行重复生产维护。
- [ ] 独立Review修正、定向回归、diff/secret检查、commit/push/develop exact读回。

第二批实际新品种试用属于后续第三批；本任务不自启JD，不将历史证据当新版本现场验证。
