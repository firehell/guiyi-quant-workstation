# 新苏冰策略 V1 交付记录

规则唯一入口：[NEW_SUBING_STRATEGY.md](../NEW_SUBING_STRATEGY.md)。
本轮新增独立 `new_subing_v1`，固定参数、AL/RB/TA 各自 100000 元历史研究账户；
不晋升策略、不发布、不启用 Runtime、通知、Shadow、Broker 或自动订单。

## 身份与验证

- 基线 develop：`0d312e9ca555674c301131bf4f2727fcea0e7b58`。
- 已独立审查的实现：`2d7069b1be746cb80656f95fd3a576eb6b97ed53`。
- 核心、适配器、CLI、只读结果库/API、独立页面、旧 SuBing/Newow/JM Paper、工程合同及预览定向回归：**552 passed**。
- Web 最终 `npm test`：**1090 passed / 3 skipped / 0 failed**；`npm run build`（类型、Vite、bundle topology）通过。
- Ruff、新核心4文件与输入/CLI3文件 Mypy、`git diff --check`通过；秘密扫描0。
- 独立最终复审：**352 passed**，原非 mock 优先级失败路径复现后已关闭，无确认阻断，允许集成 develop。
- 复审记录保存于 `output/new-subing-v1-20261012/review-accepted.md`；此前两次有问题的审查记录一并保留。

实际后端回归命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit/new_subing tests/unit/paper services/quant-api/tests/research \
  services/quant-api/tests/test_subing_ths_kernel.py \
  services/quant-api/tests/test_subing_reference_projection.py \
  services/quant-api/tests/test_subing_multiperiod.py \
  services/quant-api/tests/paper/test_matrix.py \
  services/quant-api/tests/newow/test_causal_matrix_signals.py \
  services/quant-api/tests/newow/test_research_backtest.py \
  tests/engineering/test_canonical_consistency.py \
  services/quant-api/tests/newow/test_candidate_preview.py --tb=short
```

## 真实事实来源

固定窗口 2024-10-14..2026-10-09，Catalog/MainContractMap/Session/MDS 只读核对，
未缩窗、换品种、替代行情或补写 Canonical/Catalog。执行1m：AL 221475、RB 165075、TA 165075。
行情身份见 `output/new-subing-v1-20261012/preflight.json`。

RQData 逐日 instrument、交易参数、结算和日限价事实覆盖39合约（AL25/RB7/TA7），每品种483日。
成功 `facts-attempt-002` 的计划哈希
`c555170a86a6dec3a8949547a3bc120fb9dcdc76c514e13a7ec16f1ebc9a8db2`，
journal为158次 started/158次 completed。保留各合约原始响应与 al/rb/ta.json。
第一次事实采集因 SDK 不支持 exchange_daily 限价字段而失败，未写 Canonical；
修正后按新计划、新 attempt 采集日限价，不复用失败尝试。
逐日事实为回溯取得，不证明历史当天 provider 的发布时间。

两次旧研究候选发现加仓/权益/仲裁缺陷后被 SIGTERM 停止（exit143），尚未发布结果；
原停止记录保留。最终候选使用全新 `results-attempt-003`，复用成功成本事实。
最终回放命令 `scripts/research/new_subing.py --project-env <private-project-env> --facts-dir <facts-attempt-002> --out <results-attempt-003>` 返回 exit0。
9个主结果包和54个独立窗口摘要均为 COMPLETED；仍全部 `annual_eligible=false`、`oos_status=NOT_PROVEN`。

| 品种 | 基线两年收益 | 双手续费 | 双滑点 | 基线已平交易 | 基线最大回撤 |
| --- | ---: | ---: | ---: | ---: | ---: |
| AL | -0.312% | -0.324% | -0.412% | 2 | 0.359% |
| RB | -0.305% | -0.330% | -0.385% | 1 | 0.305% |
| TA | 0% | 0% | 0% | 0 | 0% |

收益为固定两年窗口累计模型净收益，不是年化。三品种后一年及四季度、所有成本场景均无成交，
零收益是完整回放的空仓事实，不是填补数据缺口。有效性证据不足；不修改阈值追求盈利或增加成交。
离线冻结包/index 位于 `output/new-subing-v1-20261012/results-attempt-003/`，
原始响应、审查和失败记录同属该任务输出根。HTTP现场读回9个同一代码身份的 COMPLETED 包。
页面读取固定结果，不启动计算；桌面/窄屏空态、模型交易、分页与权益视图实际浏览器检查已执行。
独立真实读回见 `output/new-subing-v1-20261012/actual-readback.md`：9包身份/哈希、18笔Fill、
9轮成本变体交易与117条权益的现金/费用/净PnL/最大回撤匹配，18/18严格后续成交。
54窗口仅有摘要，独立读回未逐笔重放这些窗口，也未重新读取行情mark。
后续仅修正页面动作筛选与数值显示；核心、输入适配器和研究CLI与上述计算SHA逐文件相同，
不会把后续页面/文档提交当成另一轮计算身份。

## 集成与恢复

通过测试、自审和独立审查后按批准范围集成 develop；不执行 main/tag/release/Runtime。
冻结数据和成本变体结果保留在主开发根的任务输出目录，未进入生产账本。
需要撤回工程时使用普通 revert 本轮任务提交；保留原始 provider、失败记录及冻结结果，
不反向删除或覆盖数据。恢复计算须按固定事实、新代码身份和新的结果根执行，不复用失败attempt。

## 尚未证明

原 Notion 经典案例截图尚未逐图解析，`CASE_PARITY_PENDING`；工程 fixture 不是原案例。
前后年与季度均为固定参数历史诊断，各自独立初始账户；未见性未证明，`OOS_NOT_PROVEN`。
持仓/挂单跨主力切换必须中断，部分轨迹不拼全年收益。
不会从历史回放推导持续 Paper、Shadow、Runtime 或真实账户就绪。
