# 全品种 1d 下载起点（自 2020 首个交易日）

生成口径：2020 首个交易日 = **2020-01-02**（RQData `get_trading_dates`）

`effective_1d_start = max(2020-01-02, product_listed_date)`

品种池：`data/universe/active_products.txt`（69 个）

## 汇总

| 分类 | 数量 |
|------|------|
| 从 2020-01-02 全窗可拉 | 50 |
| 上市日晚于 2020，需从上市日开始 | 19 |
| 未匹配 instrument，暂按 2020-01-02 | 0 |

## 从 2020-01-02 开始的品种

a, ag, al, ap, au, b, bu, c, cf, cj, cs, cu, eb, eg, fg, fu, hc, i, ic, if, ih, j, jd, jm, l, m, ma, ni, nr, oi, p, pb, pp, rb, rm, rs, ru, sa, sc, sf, sm, sn, sp, sr, ss, ta, ur, v, y, zn

## 需从更晚日期开始的品种

| product | product_listed_date | effective_1d_start |
|---------|---------------------|--------------------|
| pg | 2020-03-30 | 2020-03-30 |
| lu | 2020-06-22 | 2020-06-22 |
| pf | 2020-10-12 | 2020-10-12 |
| lh | 2021-01-08 | 2021-01-08 |
| pk | 2021-02-01 | 2021-02-01 |
| im | 2022-07-22 | 2022-07-22 |
| si | 2022-12-22 | 2022-12-22 |
| ao | 2023-06-19 | 2023-06-19 |
| lc | 2023-07-21 | 2023-07-21 |
| br | 2023-07-28 | 2023-07-28 |
| ec | 2023-08-18 | 2023-08-18 |
| px | 2023-09-15 | 2023-09-15 |
| sh | 2023-09-15 | 2023-09-15 |
| pr | 2024-08-30 | 2024-08-30 |
| ps | 2024-12-26 | 2024-12-26 |
| bz | 2025-07-08 | 2025-07-08 |
| pl | 2025-07-22 | 2025-07-22 |
| pd | 2025-11-27 | 2025-11-27 |
| pt | 2025-11-27 | 2025-11-27 |

## 全表

| product | product_listed_date | effective_1d_start | note |
|---------|---------------------|--------------------|------|
| a | 2002-03-15 | 2020-01-02 | full_window_from_2020 |
| ag | 2012-05-10 | 2020-01-02 | full_window_from_2020 |
| al | 1999-01-04 | 2020-01-02 | full_window_from_2020 |
| ap | 2017-12-22 | 2020-01-02 | full_window_from_2020 |
| au | 2008-01-09 | 2020-01-02 | full_window_from_2020 |
| b | 2004-12-22 | 2020-01-02 | full_window_from_2020 |
| bu | 2013-10-09 | 2020-01-02 | full_window_from_2020 |
| c | 2004-09-22 | 2020-01-02 | full_window_from_2020 |
| cf | 2004-06-01 | 2020-01-02 | full_window_from_2020 |
| cj | 2019-04-30 | 2020-01-02 | full_window_from_2020 |
| cs | 2014-12-19 | 2020-01-02 | full_window_from_2020 |
| cu | 1999-01-04 | 2020-01-02 | full_window_from_2020 |
| eb | 2019-09-26 | 2020-01-02 | full_window_from_2020 |
| eg | 2018-12-10 | 2020-01-02 | full_window_from_2020 |
| fg | 2012-12-03 | 2020-01-02 | full_window_from_2020 |
| fu | 2004-08-25 | 2020-01-02 | full_window_from_2020 |
| hc | 2014-03-21 | 2020-01-02 | full_window_from_2020 |
| i | 2013-10-18 | 2020-01-02 | full_window_from_2020 |
| ic | 2015-04-16 | 2020-01-02 | full_window_from_2020 |
| if | 2010-04-16 | 2020-01-02 | full_window_from_2020 |
| ih | 2015-04-16 | 2020-01-02 | full_window_from_2020 |
| j | 2011-04-15 | 2020-01-02 | full_window_from_2020 |
| jd | 2013-11-08 | 2020-01-02 | full_window_from_2020 |
| jm | 2013-03-22 | 2020-01-02 | full_window_from_2020 |
| l | 2007-07-31 | 2020-01-02 | full_window_from_2020 |
| m | 2000-07-17 | 2020-01-02 | full_window_from_2020 |
| ma | 2014-06-17 | 2020-01-02 | full_window_from_2020 |
| ni | 2015-03-27 | 2020-01-02 | full_window_from_2020 |
| nr | 2019-08-12 | 2020-01-02 | full_window_from_2020 |
| oi | 2012-07-16 | 2020-01-02 | full_window_from_2020 |
| p | 2007-10-29 | 2020-01-02 | full_window_from_2020 |
| pb | 2011-03-24 | 2020-01-02 | full_window_from_2020 |
| pp | 2014-02-28 | 2020-01-02 | full_window_from_2020 |
| rb | 2009-03-27 | 2020-01-02 | full_window_from_2020 |
| rm | 2012-12-28 | 2020-01-02 | full_window_from_2020 |
| rs | 2012-12-28 | 2020-01-02 | full_window_from_2020 |
| ru | 1999-01-04 | 2020-01-02 | full_window_from_2020 |
| sa | 2019-12-06 | 2020-01-02 | full_window_from_2020 |
| sc | 2018-03-26 | 2020-01-02 | full_window_from_2020 |
| sf | 2014-08-08 | 2020-01-02 | full_window_from_2020 |
| sm | 2014-08-08 | 2020-01-02 | full_window_from_2020 |
| sn | 2015-03-27 | 2020-01-02 | full_window_from_2020 |
| sp | 2018-11-27 | 2020-01-02 | full_window_from_2020 |
| sr | 2006-01-06 | 2020-01-02 | full_window_from_2020 |
| ss | 2019-09-25 | 2020-01-02 | full_window_from_2020 |
| ta | 2006-12-18 | 2020-01-02 | full_window_from_2020 |
| ur | 2019-08-09 | 2020-01-02 | full_window_from_2020 |
| v | 2009-05-25 | 2020-01-02 | full_window_from_2020 |
| y | 2006-01-09 | 2020-01-02 | full_window_from_2020 |
| zn | 2007-03-26 | 2020-01-02 | full_window_from_2020 |
| pg | 2020-03-30 | 2020-03-30 | product_listed_after_2020 |
| lu | 2020-06-22 | 2020-06-22 | product_listed_after_2020 |
| pf | 2020-10-12 | 2020-10-12 | product_listed_after_2020 |
| lh | 2021-01-08 | 2021-01-08 | product_listed_after_2020 |
| pk | 2021-02-01 | 2021-02-01 | product_listed_after_2020 |
| im | 2022-07-22 | 2022-07-22 | product_listed_after_2020 |
| si | 2022-12-22 | 2022-12-22 | product_listed_after_2020 |
| ao | 2023-06-19 | 2023-06-19 | product_listed_after_2020 |
| lc | 2023-07-21 | 2023-07-21 | product_listed_after_2020 |
| br | 2023-07-28 | 2023-07-28 | product_listed_after_2020 |
| ec | 2023-08-18 | 2023-08-18 | product_listed_after_2020 |
| px | 2023-09-15 | 2023-09-15 | product_listed_after_2020 |
| sh | 2023-09-15 | 2023-09-15 | product_listed_after_2020 |
| pr | 2024-08-30 | 2024-08-30 | product_listed_after_2020 |
| ps | 2024-12-26 | 2024-12-26 | product_listed_after_2020 |
| bz | 2025-07-08 | 2025-07-08 | product_listed_after_2020 |
| pl | 2025-07-22 | 2025-07-22 | product_listed_after_2020 |
| pd | 2025-11-27 | 2025-11-27 | product_listed_after_2020 |
| pt | 2025-11-27 | 2025-11-27 | product_listed_after_2020 |

机器可读清单：`data/universe/product_1d_start_from_2020.csv`
