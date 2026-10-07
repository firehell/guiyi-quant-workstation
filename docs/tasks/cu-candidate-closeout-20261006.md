# CU 铜历史候选闭环

状态 **CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12**。从 develop `9dd8ed32c292233a53425620d2eb8bdec7b4ac19` 创建独立任务树，沿用已集成 CU singleton 资格；本次无生产源码修改，不重复 BU/API/Web 整体检查。代码与输入冻结在该 SHA，窗口 `2023-01-01..2026-09-24`，as_of `2026-09-24T07:00:00.000001+00:00`。1m 仅聚合，接受 5m/15m/30m/60m × 趋势/震荡/融合，均为私有 `newow_intraday_pilot_20260927` schema 的 disabled/generation0 历史候选。

## 原失败与恢复边界

原证据保留在 `/Volumes/扩展盘/guiyi-quant-evidence/deferred-worktree-cleanup-20261004-204254/cu-candidate-pilot/outputs/cu-candidate-pilot-20261001/`。旧 180 单元为 0 完成、1 已知部分失败、179 未尝试；首项 CU2302/5m 已提交 2022-02..07 的六个 1m 和六个 5m 分区。旧 attempt 不复用，不重放未知或失败提交。

原 1952 个 immutable 文件未变，旧部分提交后 1964 个，恢复前实际 1984 个；分钟 active 与旧部分提交一致。期间 20 个日周新 key、2 个日周 active 变化 producer 未知，绑定本次当前前像保持，不归因于本任务。只读原边界核对 PASS。

旧 CU2302/1m/2022-08 payload 为 10695 Bar，SHA `937bca9ae52e767177689bda78af9e4cd9dfeaf0c9d65db3b37baf2a3f90f7e3`。第 5355 行成交额 `7.450580596923828E-9` 采用既定 `rqdata-turnover-truncate-18-v1` 得到 `7.450580596E-9`，其他字段、端点和整数部分不变。真实任务 scratch publish/readback 通过；schema 未变，无新 provider 请求或生产写入。

新 forward plan SHA `a730b387d2480e5686bae5851463cad02c9ab4ad0371faff5536ebc5d2f55421`，绑定 11 份当前/原始证据、45 owner/180 单元。源请求预算 467、派生预算 1908；单元保守预算 102097920 字节，小于当时 quota 余额 1046653813 字节。总体理论预算未通过，未承诺必然完成；实际逐单元锁外/锁内 fresh quota、delta、exact preimage、旧 Bar/文件保持及失败即停校验全部通过。

前像工具首次缺必需 `--output-name`，在 argparse 读取数据前退出；原 log 保留，补参数后的唯一实际前像扫描通过，不计生产 attempt。退出命令首次身份断言因 API 相对 script 参数停止于发信号之前；核对实际精确命令与 cwd 后双重验证身份再关闭，无未知关闭结果。

## 实际结果

- 唯一 forward exit0：180/180 = 174 修复读回 + 6 NO_GAP，467 真实源请求、1908 派生、54 行成交额 18 位截断，cached source0，无失败重试。
- 当前 1984 → 4147 文件：新增 2163，扩展 212，保留 191419 个旧 Bar；本次前像中的 1193 个日周文件及 Catalog 不变，无删除。
- 原始响应独立逐值核对：467 份、3992175 行，54 行规范化、整数部分不变，全部字段/端点/交易日一致。
- 原生与独立 Decimal200 四频 full-prefix 均通过：5m 929322、15m 309774、30m 159952、60m 90106，共 1489154 Bar；每频 540 个物理合约月、45 owner、44 候选边界。
- 12 项原生 plan/apply、fresh saved manifest/checkpoint/revision/seq/source-token 读回及 8 个融合伙伴引用独审通过，全部 READY disabled/generation0。分钟趋势/震荡 coverage 均 FULL。
- API 唯一 12 项/152 GET：全部 HTTP200，128 detail + 24 identity，完整保存结果与资产/覆盖身份一致。
- 浏览器成功恢复 attempt `acceptance-recovery-01`：19 场、49 张真实原图；原生 index/audit、18 场完整数值及 cancel 原生 409 恢复校验通过。独立 Decimal200 核对 28460 笔 CLOSED、稳定 ID、公式、全部累计点及 SVG，49 原图逐张实际视觉审查通过。
- 精确任务 PID 96010/96118 与 Chrome `cu-candidate` 已退出，8012/5178 无监听，维护锁 granted/waiting0；末轮仅 12 保存态与资源读回，源前缀不重扫，资产未启用或改变 generation。

## 浏览器失败证据与串行恢复

原 `acceptance` 首场 5m trend 的 reference 在 60003ms TIMEOUT 后取消，BLOCKED、0 截图、0 accepted，完整保留且不计通过。它与批量 API 同时执行，共用单并发 reference Gate；并发排队与冷计算耗时是支持的原因推断。API152 exit0 后，同失败 URL/同 snapshot_token 以原 60 秒限制隔离 HTTP200 READY、1.681 秒；可能 cache 命中，不能据此声称冷性能通过。

独审允许新独立 attempt 串行采集全部未完成 19 场：冻结身份及四份 preflight 原样复用，执行 fresh preview GET，原 60/65/110 限制和全部错误门禁保持；没有重跑数据、资产或 API 批量。恢复 wrapper 只增加已完成 API/独审/精确输出守卫，数值 helper 仅修改精确 evidence root；没有产品代码修改。

## 验证与证据

所有命令在 CU 任务树执行，并固定该树 `services/quant-api`、`packages/quant-core` 和根目录的 PYTHONPATH；Python 使用主工作树既有 `.venv/bin/python`，不读取凭据到输出。

- `python -m pytest outputs/cu-candidate-closeout-20261006/recovery/test_forward_guards.py -q -p no:cacheprovider`：4 passed。
- `recovery/forward_campaign.py`：唯一实际维护 exit0；`data_readback_once.py`、`independent_root_preservation.py`、`independent_raw_source.py`、`independent_root_full_prefix.py`：每项唯一执行 exit0/PASS。
- `recovery/build_assets_once.py`、`final_asset_readback.py`、`coverage_expected.py`：exit0/PASS。
- `recovery/api/readback.py --execute`：exit0、12/152；恢复 `capture_once.py`：exit0、19/49。
- `python -m scripts.newow_candidate_tools index/audit --output outputs/cu-candidate-closeout-20261006/acceptance-recovery-01`：分别唯一执行 exit0，index PASS、audit NUMERICAL_PASS_VISUAL_PENDING；独立视觉为独立证明，不改写原审计状态。
- `recovery/independent_numeric.py --root outputs/cu-candidate-closeout-20261006/acceptance-recovery-01`、`targeted_exit_readback.py`：唯一执行 exit0/PASS。

原始证据保留在 `.worktrees/cu-candidate-closeout/outputs/cu-candidate-closeout-20261006/`。最终 `recovery/independent-closeout-review.json` 为 `REVIEW_COMPLETE_CANDIDATE_CLOSED`，SHA `5cf29d263158775bea0da7b5161bf3da934842be8bd2d1dc8f66aab35ddc0af1`；已核对数据、资产、API、数值、视觉、退出和原失败证据身份，无重复采集已通过场景。

## 验收边界与下一步

历史候选 **52/60**，正式开放仍 **45/60**。W1 真实 49/120 Bar 预热、趋势/震荡/融合 CLOSED 6/0/8 保留；0 CLOSED 的统计为破折号，不能冒充 0% 盈亏证据。截图密集标记重叠、tooltip 局部遮挡、视口顶部/底部裁切及较早窗口右侧空白如实保留，没有新增 Confirmed Issue。日周预热与数据边界不因分钟候选闭环消除。

允许集成 develop；不涉及正式开放、Release、Runtime、Scope、通知、交易或 OOS 晋升。证据输出原位保留，不归档或清理任务树。下一项 **NI 镍**。
