# Newow 单品种候选验收工具

本工具用于 P7 已交办品种的候选验收准备与只读检查。参数统一输入，公式与产品能力由原生代码/接口提供。没有生产维护、资产build/rebuild、激活或重试执行器；维护和构建仍通过既有native入口及其plan/hash/attempt合同完成。

## 第一批：准备与门禁

从冻结工作区运行，显式绑定 `services/quant-api:packages/quant-core:.`；Python使用既有quant-api环境。`--worktree`应为该工作区绝对路径；不能把editable导入当作冻结代码。示例：

```sh
PYTHONPATH=services/quant-api:packages/quant-core:. python -m scripts.newow_candidate_tools prepare \
  --product cj --worktree "$PWD" \
  --since 2023-01-01 --through 2026-09-24 \
  --as-of 2026-09-24T07:00:00.000001+00:00 \
  --schema newow_intraday_pilot_20260927 \
  --api-origin http://127.0.0.1:8012 --web-origin http://127.0.0.1:5178 \
  --output /private/tmp/cj-candidate-prepared
```

prepare取得exact HEAD、拒绝services/packages dirty，校验原生模块导入并生成D1/W1原生formula/profile/model身份；不读DB/provider。输出candidate.json/context-check.json/legacy-expected-identities.json只排他创建，旧结果不覆盖。

```sh
PYTHONPATH=services/quant-api:packages/quant-core:. python -m scripts.newow_candidate_tools preflight \
  --output /private/tmp/cj-candidate-prepared \
  --assets /absolute/path/source-assets-final-v5.json \
  --saved-preview /absolute/path/preview-preflight-v2.json
```

保存source资产报告需四频各三READY disabled/generation0、正确产品/物理owner/count/revision/seq、完整前缀与冻结as_of。该门禁不替代full native manifest/source dependency独立Review。preflight重算native日周身份，防止缺身份或旧身份被传到采集阶段。

改用`--execute-get`才实际对指定loopback API/Web执行四次GET（identity/capabilities各两次）；无redirect/retry、无生产写入。默认保存证据模式标记SAVED_PREVIEW_ONLY，不声称新现场已验收。未启动服务时不要用GET模拟通过。

只支持单品种preview：v25原生RB单品种，v26黑色品种singleton，v27其他single_product。v26的八品种旧批次服务被拒绝，不以membership扩大当前任务Scope。未知capability、非四分钟加日周、错误Web candidate_origin均fail-closed。可显式传`--web-code-sha`冻结不同Web代码；省略时必须与API代码相同。

阶段门禁绑定整个Candidate摘要（含窗口/schema/origins），只处理前置证据，不创建或复用native attempt。来源/公式/物理前缀、真实页面、独立数值、逐图视觉分别验收。

## 验证

```sh
python -m pytest --confcutdir=tests/newow_candidate_tools \
  tests/newow_candidate_tools/test_preflight.py \
  tests/newow_candidate_tools/test_evidence.py -q -p no:cacheprovider
```

原始行情、截图、配置及响应不提交。未确认/UNKNOWN生产结果停止相关mutation并原生只读核对；工具不解锁FU/NI失败attempt。

## 第二批：连续采集与离线验收

服务启动、native 数据维护与候选资产构建仍使用现有入口；本工具只采集已经通过 preflight 的单品种只读 preview。采集前再次检查冻结 HEAD。先完成相同输出目录的 prepare/preflight，再显式执行：

```sh
/Users/zhangzhao/.codex/skills/playwright/scripts/playwright_cli.sh -s=cj-candidate open http://127.0.0.1:5178/
/Users/zhangzhao/.codex/skills/playwright/scripts/playwright_cli.sh -s=cj-candidate tab-list
PYTHONPATH=services/quant-api:packages/quant-core:. python -m scripts.newow_candidate_tools capture \
  --output /private/tmp/cj-candidate-prepared \
  --cli /Users/zhangzhao/.codex/skills/playwright/scripts/playwright_cli.sh \
  --session cj-candidate --execute
python -m scripts.newow_candidate_tools index --output /private/tmp/cj-candidate-prepared
python -m scripts.newow_candidate_tools audit --output /private/tmp/cj-candidate-prepared
```

`capture` 不启动服务，不下载、构建或激活数据。19 个串行场景为四分钟周期 × 三模式、日周 × 三模式和一个取消恢复场景。每个分钟组合连续取得功能观察、原始 XHR 全曲线数组、立即 GET 的完整数组和记录、同页面较早窗口，不再分别导航三次。保留真实辅助图、分页、SPA 回切、旧窗口可见 Marker 和稳定顶价检查。日周与取消恢复保留独立场景；250ms 请求若真实提前完成，明确记为不适用，不能假称 timeout。

先打开并核对指定 session 的本地 preview tab；`capture` 不代替 `open`。每个场景先在 CLI 会话中保存完整结果，再以不超过 1 Mi UTF-16 字符的块传输；每块校验 session nonce、顺序、字节数及 SHA-256，最终校验完整 JSON 哈希和终态。数组、closed、SVG 点与原生 409 响应均不截断。保存静态资源/实际脚本 SHA、CLI 原始输出、完整结果、传输清单与截图。`collection-start.json` 排他创建；缺块、会话丢失、CLI 部分输出或场景失败立即停止并保留现场，不把半成品计为成功。

分钟双策略首屏只有在两张真实 READY 图、原生身份一致、无在途请求，且恰有一条对应 partner reference GET 的 `net::ERR_ABORTED` 时，才允许采集器在原截止时间内一次补充同 URL 的真实 XHR。补充响应严格绑定原图的 token、公式、输入及 cutoff；记录 `ui_composable_received=false`，不能宣称 Vue 已消费或消除页面警告。已有错误响应、身份不明、第二次缺失或其他失败仍停止。

日周诊断保留每阶段等待条件、在途请求与 body 读取计数。同 URL 的已完成 `net::ERR_ABORTED` 请求不参与成功响应排序绑定，原失败记录仍完整保留；日周数值门禁仍拒绝任何真实请求失败、body 错误或页面异常。

若采集已有连续成功前缀、后续场景阻塞，可在新输出目录重新运行 prepare/preflight，然后显式传 `capture --resume-from /absolute/path/prior-blocked-output`。工具核对同一 Candidate 身份、旧 collection 的连续成功前缀、每个原始文件和截图哈希，逐字节复制成功场景；旧失败场景及其截图仍留在旧目录，新现场从该场景重新采集。新目录输出 `resume-boundary.json`。这不是自动重试；继续前须调查具体失败边界，不能以此重放 native 数据维护或资产构建。其他旧 capture 仍直接拒绝覆盖。

`index` 核验精确 19 场景、声明的原始文件 SHA/大小和截图集合；`audit` 重新计算全部索引并验原始响应、读回、DOM、完整交易 ID、Decimal 累计收益与 SVG 每个点。不同 section 使用各自 input hash，chart/reference 使用相同 snapshot；时点保留微秒。记录请求绑定实际 history_limit/cursor，错误频率 snapshot 必须返回原生 409，恢复必须使用新的正确 token。

成功的离线结果是 `NUMERICAL_PASS_VISUAL_PENDING`，不是候选闭环完成。需要逐图视觉核验和 native source manifest 独立 evidence；本工具不更新品种完成矩阵、Scope、Runtime 或正式配置。原生日周零 CLOSED 必须对应真实空态、无曲线与零/null 统计。当前分钟 collector 保留非空记录/曲线门禁，零 CLOSED 会明确阻塞；不能用空页面冒充通过。

2026-09-29 验证采用 CJ/SM 既有原始证据：每品种功能 12、完整曲线 12、较早窗口 12、日周 6、取消恢复 1。旧日周记录缺少 XHR request binding 与逐 base 的公式分组，因此历史回放明确标注这两项未重验；新 prepare/capture 强制完整身份。以上是保存证据离线回放，不是新 collector 的真实 Chrome 现场结果。首次新品种现场试用已由 JD 完成：一次真实维护、一次19场真实Chrome采集，12/12 API和49张原图的独立数值/逐图Review通过；22m49.8s 仅是本次采集耗时，旧 CJ/SM 缺完整阶段计时，不能推导整体提速。W1原生预热、报价403、较早副图短窗和标签遮挡保留；见 `docs/tasks/jd-candidate-pilot-20260929.md`。

全部定向测试：

```sh
python -m pytest tests/newow_candidate_tools -q -p no:cacheprovider
```
