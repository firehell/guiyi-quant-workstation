# 火天大有 HTDY Golden Sample 验收

生成时间：2026-07-12

## 1. 当前结论

```text
GOLDEN_SAMPLE_PASS_VISUAL_ORACLE
```

第 4 步自动数值验收已通过；用户已提供同窗口通达信视觉截图，外部视觉 oracle Gate 已关闭。因此：

- 可以写成 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`；
- 不能写成可信指标定级已完成或通达信数值逐点 oracle pass；
- 不授权第 5 步正式候选接入；
- 不授权策略、回测、scanner、live、数据库、`signal_events` 或企业微信接入。

## 2. 固定样本

| 字段 | 固定值 |
|---|---|
| symbol / contract | `jm` / `jm.MAIN` |
| period | `15m` |
| data_version | `rqdata_jm_standard_15m_20230103_20260710_v2` |
| provider / source | `rqdata` / `rqdata` |
| data_role / quality_status | `primary` / `passed` |
| 时间范围 | `2026-06-24 22:30:00` 至 `2026-07-09 23:00:00` |
| row_count | `256` |
| source file SHA256 | `7161c515379db31f46cf115cc1cbeb7f487ce774ff8c1ab5d86a77af727bc70c` |
| sample input SHA256 | `b81abf3ad27b828738de3e6c889dd62f9887b544b6798659c17d289b8d75cc85` |

真实 RQData Parquet 不进入 Git。tracked manifest 只保存逻辑相对路径、lineage、checksum、输出摘要和 Gate 状态。

## 3. 数值验收结果

### original v0

| 字段 | 命中数 |
|---|---:|
| 黄K | 32 |
| 白K | 19 |
| 三连黄K观察 | 5 |
| 三连白K观察 | 3 |
| 回调买观察 | 13 |
| XG观察 | 1 |

Python original PoC 与 Web observation-only 对照结果：

- 256 个 datetime、所有布尔事件位置和 null 位置完全一致；
- `ZK1/ZD1/ZD2` 按 `atol=1e-8`、`rtol=1e-10` 全部一致；
- Web 生产展示仍保留 6 位小数，Golden 对照通过专用不舍入输出执行，不改变页面默认展示口径。

### strict v1

| 字段 | 命中数 |
|---|---:|
| 黄K观察 | 31 |
| 白K观察 | 69 |
| 三连黄K观察 | 5 |
| 三连白K观察 | 6 |
| 回调买观察 | 22 |
| XG观察 | 2 |

strict v1 额外通过真实样本逐 prefix/batch 一致、future-tail invariance、warm-up 和字段/能力边界。metadata 继续固定 `strict_research_candidate`、`closed_bar_only=true`，所有 backtest/live/alert/trading capability 均为 `false`。

strict v1 不要求与 original v0 数值一致；二者是不同版本和不同风险口径。

## 4. 浏览器检查

当前 worktree 前端运行于 `5174`，读取本机已有 `8000` API 数据：

| viewport | 水平溢出 | HTDY overlay | 分段 | 买多观察 | 卖空观察 | XG观察 |
|---:|---:|---:|---:|---:|---:|---:|
| 1440 | 否 | 1 | 643 | 33 | 23 | 6 |
| 1280 | 否 | 1 | 643 | 33 | 23 | 6 |
| 1024 | 否 | 1 | 643 | 33 | 23 | 6 |

- 常驻 observation-only/重绘/XG-XG2 文案正确。
- linked crosshair 可见，点击后 hover 时间更新为 `2026-05-25 13:45`。
- HTDY 未产生 console error/warn。
- 页面仍有一条已知 V1-E MACD 404：本机 `8000` API 是旧进程，缺少 `/market/indicators/macd`；不属于 HTDY Golden Sample 数值失败。
- 切换三档 viewport 时 Vite dev server 记录一次 `ResizeObserver loop completed with undelivered notifications`；未影响 overlay/linked crosshair，但浏览器 Gate 不记为 full green。
- 当前 API 最新 bar 为 `2026-07-07`，没有覆盖固定样本末端 `2026-07-09 23:00`，所以本次页面检查不能替代同窗口通达信视觉 oracle。

## 5. 外部视觉 oracle

用户提供通达信截图作为第 4 步外部视觉 oracle 证据，截图不提交到 Git，仅在本文件记录人工核对结论。

截图条件：

| 字段 | 值 |
|---|---|
| 通达信合约 | `JM8 焦煤主连` |
| 周期 | `15分钟` |
| 指标 | 火天大有原始通达信公式 |
| 截图起点 | `2026-06-22` |
| 覆盖关系 | 覆盖固定窗口 `2026-06-24 22:30:00` 至 `2026-07-09 23:00:00` |

人工核对结论：

- `ZK1 / ZD1 / ZD2` 三条线可见；
- 黄K / 白K 分段可见；
- 多个 `买多` / `卖空` 三连观察提示可见；
- `XG` / 红色观察标记在右侧连续黄K附近可见；
- 形态与自动数值验收方向一致。

限制：

- 未提供通达信指标数值导出，不能声明逐点数值 oracle pass；
- 该 Gate 只关闭第 4 步 Golden Sample 视觉验收，不授权第 5 步正式候选接入；
- 原始 XMA 版本仍是 `observation_only`，不能进入可信回测、正式信号或企业微信提醒。

## 6. 复验命令

```bash
uv run --project services/quant-api python experiments/htdy_indicator/golden_sample.py \
  --export-web-bundle /tmp/htdy_golden_web_bundle.json

HTDY_GOLDEN_BUNDLE=/tmp/htdy_golden_web_bundle.json \
  pnpm --dir apps/quant-web exec node --test tests/htdyGoldenSample.test.ts

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_golden_sample.py
```

工具只读现有 Parquet；不会下载、覆盖或注册数据。可用 `GUIYI_HTDY_GOLDEN_SOURCE` 显式指定同一 checksum 文件，或用 `GUIYI_DATA_ROOT` 指定数据仓根目录。

## 7. 后续 Gate

第 4 步已关闭为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。第 5 步正式候选接入仍须另开 Plan 和用户授权。
