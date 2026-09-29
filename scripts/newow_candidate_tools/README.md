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
