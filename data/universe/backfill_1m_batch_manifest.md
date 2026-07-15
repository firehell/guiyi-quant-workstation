# 1m 主连前缀 backfill 分批清单

口径：只补 `[effective_start, 2023-01-03)`，API 预估 = 前缀行数 × 25.9 B/行 × 3。

- 需补品种：**71**
- 跳过品种：**19**（`effective_start >= 2023-01-03`：ad ao br bz ec l_f lc lg op pd pl pp_f pr pt px sh tl v_f）
- 全量 API 预估：**~1205 MB**

## 批次

| 批次 | 文件 | 预估 API MB | 品种 |
|------|------|-------------|------|
| B01 | `products_backfill_1m_batch01.txt` | 113.3 | ag, au, sc, al |
| B02 | `products_backfill_1m_batch02.txt` | 99.2 | cu, ni, pb, sn |
| B03 | `products_backfill_1m_batch03.txt` | 105.1 | ss, zn, a, b, bu |
| B04 | `products_backfill_1m_batch04.txt` | 111.0 | c, cf, cs, cy, eb, eg |
| B05 | `products_backfill_1m_batch05.txt` | 111.0 | fg, fu, hc, i, j, jm |
| B06 | `products_backfill_1m_batch06.txt` | 111.0 | l, m, ma, nr, oi, p |
| B07 | `products_backfill_1m_batch07.txt` | 111.0 | pp, rb, rm, rr, ru, sa |
| B08 | `products_backfill_1m_batch08.txt` | 111.0 | sp, sr, ta, v, y, zc |
| B09 | `products_backfill_1m_batch09.txt` | 118.2 | bc, pg, lu, t, tf, ts, pf, ic |
| B10 | `products_backfill_1m_batch10.txt` | 111.4 | if, ih, ap, bb, cj, fb, jd, jr, pm |
| B11 | `products_backfill_1m_batch11.txt` | 103.3 | ri, rs, sf, sm, ur, wh, wr, lh, pk, im, si |
| **today** | `products_backfill_1m_today.txt` | **919.4** | B01–B08 全量 + B09(bc,pg) + B10(ap) + B11(si)，共 47 品种 |
| **remainder** | `products_backfill_1m_remainder.txt` | **286.1** | B09 余 6 + B10 余 8 + B11 余 10，共 24 品种 |

## 剩余批次（remainder，~286 MB）

`lu t tf ts pf ic if ih bb cj fb jd jr pm ri rs sf sm ur wh wr lh pk im`

## 明日剩余（已完成则忽略）

`lu t tf ts pf ic if ih bb cj fb jd jr pm ri rs sf sm ur wh wr lh pk im`

## 执行

```bash
LAYER=dry-run BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
ALLOW_QUALITY_FAILED=1 LAYER=layer1 BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
LAYER=aggregate BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
```
