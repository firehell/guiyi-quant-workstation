# 牛哇周线数据批次与最终矩阵收尾（2026-09-26）

## 冻结身份与范围

- 计算及数据执行代码：`b64cc8dfb60e41600a0e9e7aff9b8d5ac87bc4a8`。
- 验收截点：`2026-09-26T03:07:21+00:00`，最新已完成交易日 2026-09-24。
- 正式 W1 输入策略：41 品种 V1、19 品种 V2；60 品种 × 趋势/震荡/主升浪 = 180 个唯一 W1 组合。
- 本批只收尾周线数据与同版本全量主图、辅助、页面参考交易验收；不宣称 Release、Runtime、浏览器现场或 P9 持久化构建完成。
- 旧 238 个目标包含 D1/W1，已经失效。A2611 本次无新恢复目标，未重试其旧失败请求。

## 数据修复

旧 W1 与已发布 D1 质量事实冲突：95 个合约、1,233 周、460 月分区。
逐周源证据核对后移除 1,233 根不合格旧 W1，保留 539 根正常周线；251 月发布替换候选，
209 个空月移除 Catalog 指针。旧不可变文件保留，质量修复未改 D1；维护锁下单事务提交，
独立现场 inspect 确认 460/460 candidate，D1 preimage 全部保持一致。

另按重新审计产生的新计划修复 BU2611、EB2611、NI2611、PB2611、PD2612、PG2611。
六个批次全部 passed，128 个 D1/W1 配对月目标（64 个 W1 及 64 个 D1 同源上下文）；
真实来源日志共 64 次 exchange_daily 请求，无重试、未知结果或剩余目标。
既有 9/21–24 日线保留，PD 已知价格不可用上下文显式排除。Catalog、物理文件和 MDS 读回全部通过。

证据目录：`outputs/newow-w1-closeout-20260926/`。
最终精确质量 packet：`quality-reconcile-final.prepare.json`，SHA256
`dfa7fcaca0a532d0f52d9b70726de2a03ab22bde18dd334e4e8808a3c66347dd`。
生产结果见 `quality-apply-cli.json`、六个 `w1-*-final-apply-cli.json`、相应 attempt journal 与 `execution.json`。
初始 audit 和 draft prepare 仅为诊断记录，不是最终验收；最终以 matrix 和 final packet 为准。

## 最终矩阵

完整完成、预算未耗尽；2444 DATA_READY、22 NOT_APPLICABLE 数据依赖，
DATA_UNAVAILABLE/INTEGRITY_ERROR、repair_targets、metadata_proposals 均为 0。
矩阵本身 provider_requests=0、writes=0。

| 面板 | READY | WARMING | 其他 |
| --- | ---: | ---: | --- |
| 主图 | 179 | 1 | RS 震荡正常预热 |
| 页面参考交易 | 179 | 1 | RS 震荡正常预热 |
| MACD | 123 | 57 | |
| 主力控盘 | 132 | 48 | |
| 涨跌动能 | 129 | 51 | |
| 趋势反转 | 0 | 180 | 单物理合约段 MA120 预热 |
| 照妖镜 | 117 | 63 | |
| 杯柄 | 0 | 0 | 180 NOT_APPLICABLE，W1 不适用 |
| 综合解释 | 0 | 0 | 180 UNOPENED，既有未开放范围 |
| 页面 comparator | 0 | 0 | 趋势 60 UNAVAILABLE（样本不足），另两策略 120 NOT_APPLICABLE |

辅助整体 WARMING 不能直接解释为当前不可算：最新物理合约计算段与历史短段须独立判断。
不跨物理合约或价格断点借用预热，不降低公式阈值，不强行 READY。
真实逐段诊断见 `matrix-w1-v1-warming-segment-diagnosis.json` 与
`matrix-w1-v2-warming-segment-diagnosis.json`。当前段不足：MACD 为 PD/BZ/PF/PG/PL/PR/PX/RS/SM
（分别 24/27/30/30/18/28/30/2/23 根，阈值 34）；照妖镜为 PL/RS（18/2 根，阈值 20）；
主力控盘及涨跌动能仅 RS（2 根）；趋势反转 60 品种当前段均不足 120 根。
其余整体 WARMING 来自历史短段，当前段已可算。RS2701 当前 2 根周线不足震荡 10 根要求，
保持正常待积累，不冒充参考交易或 READY。Catalog 独立回读确认 9/16 上市，9/18 与 9/24 两根周线，
当前 owner 无价格缺口；reference 通用重预热 reason 不能解释为当前 RS 缺数据。
主图诊断见 `rs-w1-main-warming-diagnosis.json`。

矩阵文件与 SHA256：

- `matrix-w1-v1.json`：`230b1f9ed686d258f9ea959f41d84f472b5e227949bf78d1de6aa60f254c16be`
- `matrix-w1-v2.json`：`c51df5ca812b0fff81411f07f6ef9e7bc0cb33021f3e6908891d8305d086dbc7`
- `matrix-summary.json`：180 唯一组合汇总，按 frequency=1w 筛选；原生 main_case_count 包含未选中周期，不能当 W1 数量。

## 验证、集成与恢复边界

高风险代码和精确质量 packet 已独立 Review；六批来源日志及质量生产回读另有独立只读复核；最终两组矩阵及全部辅助预热、RS 主图原因独立复核通过。
开发阶段定向测试组 293 passed、121 passed（两组有重叠，不相加）；集成后的直接回归命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/newow/test_pf_rs_weekly_quality_repair.py -q
```

结果 15 passed；Ruff 与 diff 检查通过。集成 develop 后，正式 reader/service、quant-core、
weekly recovery 和质量修复实现与冻结验收代码无差异，页面并行修改另行保留。

质量修复可依据 pinned packet 的旧文件 SHA、D1 preimage 和候选身份，使用既有 inspect/restore 精确恢复；
任何后续数据变化使 preimage 不符时必须停止。六批不可变旧文件与 prepared/journal 保留，
已提交结果不得以重跑 apply 代替恢复；需要回退时须先按精确旧指针确认恢复范围。
本批没有切换现役 v1.10.34 Runtime，不把修复前自然 weekly audit 当作修复后验收。
