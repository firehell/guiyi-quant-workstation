# 1m 主连前缀 backfill 分批清单

更新时间：2026-08-05

口径：只补 `[effective_start, 2023-01-03)`。当前 69 品种中 57 个适用，12 个因
`effective_start >= 2023-01-03` 跳过。历史 API MB 估算已失效并移除；执行前必须重新 dry-run。

## 批次

| 批次 | 文件 | 数量 | 品种 |
|---|---|---:|---|
| B01 | `products_backfill_1m_batch01.txt` | 4 | ag, au, sc, al |
| B02 | `products_backfill_1m_batch02.txt` | 4 | cu, ni, pb, sn |
| B03 | `products_backfill_1m_batch03.txt` | 5 | ss, zn, a, b, bu |
| B04 | `products_backfill_1m_batch04.txt` | 5 | c, cf, cs, eb, eg |
| B05 | `products_backfill_1m_batch05.txt` | 6 | fg, fu, hc, i, j, jm |
| B06 | `products_backfill_1m_batch06.txt` | 6 | l, m, ma, nr, oi, p |
| B07 | `products_backfill_1m_batch07.txt` | 5 | pp, rb, rm, ru, sa |
| B08 | `products_backfill_1m_batch08.txt` | 5 | sp, sr, ta, v, y |
| B09 | `products_backfill_1m_batch09.txt` | 4 | pg, lu, pf, ic |
| B10 | `products_backfill_1m_batch10.txt` | 5 | if, ih, ap, cj, jd |
| B11 | `products_backfill_1m_batch11.txt` | 8 | rs, sf, sm, ur, lh, pk, im, si |
| today | `products_backfill_1m_today.txt` | 43 | B01-B08 + pg + ap + si |
| remainder | `products_backfill_1m_remainder.txt` | 14 | lu, pf, ic, if, ih, cj, jd, rs, sf, sm, ur, lh, pk, im |

跳过：`ao, br, bz, ec, lc, pd, pl, pr, ps, pt, px, sh`。

## 执行

```bash
LAYER=dry-run BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
ALLOW_QUALITY_FAILED=1 LAYER=layer1 BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
LAYER=aggregate BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
```

上述命令只使用 69 品种活动清单；真实 RQData 下载仍需独立批准。
