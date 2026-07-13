# Download Queue Execution Summary (2026-07-13)

按 `download_queue_commands.md` 优先级 P0→P4 执行记录。

## P0 — 主连 1w pre-2020 ✅ 完成

- 脚本：`rqdata_weekly_pre2020_backfill.py`
- 品种：34（来自 `weekly_history_audit.csv`）
- 结果：**34/34 success**（prepend + register）
- 报告：`data/reports/download_queue_p0_weekly_20260713/`

## P1 — 主连 1d pre-2020 ✅ 完成

- 脚本：`rqdata_daily_pre2020_backfill.py`
- 品种：63（pre-2020 applicable）
- 结果：**63/63 success**（含 `allow-quality-failed` 重试后 5 个 warning 品种）
- 报告：`data/reports/download_queue_p1_daily_20260713/`

## P2 — roll 1w 缺失品种 ⚠️ 部分失败

- 脚本：`rqdata_actual_contract_bars_batch.py --roll-segments --periods 1w`
- 品种：20（ad, ao, br, bz, ec, l_f, lc, lg, op, pd, pl, pp_f, pr, ps, pt, px, sh, si, tl, v_f）
- 结果：**全部 manifest 失败**
- 主因：
  1. 短主力段（1–7 天）RQData 无周线 bar
  2. 部分品种返回 `'actual_contract'` KeyError
- 说明：新上市品种 roll 1w 需放宽「单段失败不阻断整品」或跳过极短段

## P3 — roll layer2 全品种 ⚠️ 部分完成（8/90）

- 命令：`LAYER=layer2 BAR_PERIODS=1d,1w START_DATE=2010-01-04`
- 日志：`data/reports/download_queue_p3_roll_layer2_20260713.log`
- 后台任务已结束（约 14 分钟，exit 0）
- 实际处理品种：**a, ad, ag, al, ao, ap, au, b**（8/90，停在 `b`）
- 主因失败：`trading parameter gate failed`（历史合约缺 `FuturesTradingParameter`）
- **续跑前必须先执行 layer0**：

## P4 — 主连 1m pre-2010 ✅ 完成（19/19）

- 脚本：`rqdata_1m_pre2020_backfill.py`
- 品种文件：`data/universe/products_1m_pre2010_gap_19.txt`
- 结果：**19/19 success**（多批 `traffic-budget-mb 150` 续跑）
- 报告：`data/reports/download_queue_p4_1m_20260713/`
- 注：盘点脚本仍可能显示 1m 主连缺口（primary 最宽文件 re-elect / 窗口口径差异），需后续 manifest 对齐

## 复盘后缺口（`download_pending_inventory_20260713_final`）

| 类型 | 执行前 | 执行后 |
|------|--------|--------|
| 主连缺口 | 19 | 19（1m，DB 最宽 primary 待 re-elect） |
| roll 段缺口 | 10,363 | **8,184**（↓ 2,179） |
| roll 1d 段缺口 | 2,863 | **1,386** |
| roll 1w 段缺口 | 4,122 | **3,420** |

## 流量提示

米筐账户剩余流量有限（会话初约 368 MB）。P4 全量 19 品种预估约 4.8 GB，需多轮分批或充值后继续。

## 推荐续跑顺序

1. 等 P3 后台结束或手动停止后，补 **layer0 trading_params** 再重跑 layer2
2. 循环执行 P4（`traffic-budget-mb 150`）直至 19 品种完成
3. 重跑盘点：`scripts/rqdata_download_pending_inventory.py`
