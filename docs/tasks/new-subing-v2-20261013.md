# 新苏冰V2修正与重测

Owner交办：修改已定位的来源语义问题并重新测；本金选择10万元主结果、100万元单独诊断。
V1保留；V2合同见[NEW_SUBING_STRATEGY_V2.md](../NEW_SUBING_STRATEGY_V2.md)。不发布或修改Runtime。

## 实现及验证

- 首仓试探与后续三根确认分离，取消远离均线一刀切；小周期切入、盈利后日线持仓，分层保护加仓点。
- 独立版本、两本金Profile、只读结果库及页面筛选；prepared指标跨账户复用，账户与窗口独立。
- 独立Review修复：空头日线减仓、日线MACD、首次ATR冻结、日线warm-up、BOLL条件同Bar绑定、旧回调失效。
- e321回放时再次核对源笔记，发现柱弱止盈被误译为亏损止损；attempt001停止并保留，旧Review漏检明确记录。
  后续修正版分开MACD反向与柱缩弱，使用新代码SHA及attempt002，不能沿用旧收益。
- 修复MACD来源映射后定向核心加研究服务/CLI/苏冰/Paper/一致性200 passed；Web1092 passed/3 skipped，build通过。
- Ruff、mypy、diff检查通过；secret_scan 0 finding。正式回放及独立账目读回已完成，研究未晋升。
- 新精确代码8f40783af74bf5dec317552e79b452b08b18d031，独立88 tests及实际事件复核通过，允许attempt002。

## 同输入只读预检

通过安全私有配置加载器和repeatable-read READ ONLY事务读取MDS；未下载provider、未修改Canonical/Catalog。
三品种与V1 `output/new-subing-v1-20261012/results-attempt-003`的已索引 baseline 完全匹配：

| 品种 | input_snapshot_hash | execution_facts_hash |
|---|---|---|
| AL | 3ab9f701aa1cab5a481968a35bad6b86a2f090eb382fe0fb320dfb7133584308 | 6ded4cedd1761efd02759708d2df605341a72f54d09b7d451715df43fd5dd51a |
| RB | 01b72a725d8adf8f716327a4bcb243d87dfdd6d3bd173d87c7b80c2e7dee0aaa | eec4db9316e3b970a160f89e3b4d70da310948904055e47fa9c0bdb9e76f847b |
| TA | 4bf82aaa1869be1982acf855e015b84a1a07b381025ba854f529a8d898fe46c5 | 4ff26fed959b71603782513eb975fd68b257afab5d0a8681f50f797f8dd40aa2 |

固定窗口2024-10-14..2026-10-09；同baseline、double_commission、double_slippage。
前后年及四季度均重新初始化账户，已参与规则研究，不能称为未见OOS；原案例图片未读取，CASE_PARITY_PENDING。

## 可复跑入口

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/unit/new_subing_v2 tests/unit/new_subing services/quant-api/tests/research \
  tests/unit/paper services/quant-api/tests/test_subing_ths_kernel.py \
  tests/engineering/test_canonical_consistency.py
```

实际回放使用`scripts/research/new_subing_v2.py`、原facts-attempt-002及原results-attempt-003作为比较身份，
新attempt独立结果根，要求输入/事实哈希相等与代码已提交。保留中断和缺口，无缩窗拼年或替代成本。

## 实际结果与结论

最终 `output/new-subing-v2-20261013/results-attempt-002` 的18包及108窗口摘要生成成功，CLI exit0。
主包7 COMPLETED/11 ROLLOVER_INTERRUPTED；窗口85完成/23中断，每窗独立本金，不拼年。

| 品种 | V1 10万基线 | V2 10万基线 | V2 100万诊断 |
|---|---|---|---|
| AL | -0.312%，2轮 | 持仓换月中断，45轮已平/余1手 | 持仓换月中断，26轮已平/余5手 |
| RB | -0.30498%，1轮 | -21.194398%，204轮 | -24.4244632%，208轮 |
| TA | 0%，0轮 | 待执行意图跨主力中断，36轮已平/余0手 | 同类中断，37轮已平/余0手 |

AL仅10万double_slippage完整窗口完成，-6.103%；不能拿该成本变体代替基线或填补其他中断。
AL10万development独立窗口-4.633%，对应V1 -0.312%，这是一年同窗口，不是完整两年收益。
AL10万基准87次MIN_LOT_BUDGET、无加仓，45轮中3轮盈利/30次五根不盈利；100万实际2次加仓、
2次分层保护撤回、8次TREND记录。RB两本金都亏损，说明放大资金没有提供方法有效证据。
原文中周期选图、宏观技术同向、60日线大行情判断与原案例标注仍未验证，不造主观事实补齐。

独立脚本与结果 `output/new-subing-v2-20261013/independent-readback.{py,json}`：
18主包、4850 Fill、1771已平轮的哈希、逐层费用/平今平昨/FIFO/指定层/现金/净PnL/剩余层及当前pending
strict-before通过。108窗口只核摘要；未独立重新读取每条行情mark，不夸大为126账户逐笔二次回放。
V1保留9包；`comparison-results`只索引复制原9与新18包，run_id/hash不改。详细比较见同目录comparison.md。

结论：允许研究代码集成develop，**当前候选未提供盈利优势，不晋升策略**。
未发布/切换Runtime、通知、持续Paper、Shadow、Broker或真实订单。
最小下一步：以原案例逐笔标注入场、退出和持仓周期，核对主观选时与本候选的对应关系。
