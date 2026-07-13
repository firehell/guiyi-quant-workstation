# Download Pending Inventory

- mode: `download_pending_inventory`
- audit_end: `2026-07-10`
- products: `90`
- rqdata_start_policy: `max(product_listed_date, 2000-01-04)`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Gap Summary

| metric | count |
|---|---:|
| dominant gaps (product×period) | 19 |
| roll gap segments | 8184 |
| product-period worst-status gaps | 233 |

## Dominant Main Gaps By Period

| period | gap_count |
|---|---:|
| `1m` | 19 |
| `1d` | 0 |
| `1w` | 0 |

## Roll Gap Segments By Period

| period | gap_count |
|---|---:|
| `1m` | 3378 |
| `1d` | 1386 |
| `1w` | 3420 |

## Dominant Main Pending (first 30)

- `a` `1m` `partial_start` gap `2002-03-15`..`2010-01-03` action `minute_pre2020_backfill`
- `al` `1m` `partial_start` gap `2000-01-04`..`2010-01-03` action `minute_pre2020_backfill`
- `au` `1m` `partial_start` gap `2008-01-09`..`2010-01-03` action `minute_pre2020_backfill`
- `b` `1m` `partial_start` gap `2004-12-22`..`2010-01-03` action `minute_pre2020_backfill`
- `c` `1m` `partial_start` gap `2004-09-22`..`2010-01-03` action `minute_pre2020_backfill`
- `cf` `1m` `partial_start` gap `2004-06-01`..`2010-01-03` action `minute_pre2020_backfill`
- `cu` `1m` `partial_start` gap `2000-01-04`..`2010-01-03` action `minute_pre2020_backfill`
- `fu` `1m` `partial_start` gap `2004-08-25`..`2010-01-03` action `minute_pre2020_backfill`
- `l` `1m` `partial_start` gap `2007-07-31`..`2010-01-03` action `minute_pre2020_backfill`
- `m` `1m` `partial_start` gap `2000-07-17`..`2010-01-03` action `minute_pre2020_backfill`
- `p` `1m` `partial_start` gap `2007-10-29`..`2010-01-03` action `minute_pre2020_backfill`
- `rb` `1m` `partial_start` gap `2009-03-27`..`2010-01-03` action `minute_pre2020_backfill`
- `ru` `1m` `partial_start` gap `2000-01-04`..`2010-01-03` action `minute_pre2020_backfill`
- `sr` `1m` `partial_start` gap `2006-01-06`..`2010-01-03` action `minute_pre2020_backfill`
- `ta` `1m` `partial_start` gap `2006-12-18`..`2010-01-03` action `minute_pre2020_backfill`
- `v` `1m` `partial_start` gap `2009-05-25`..`2010-01-03` action `minute_pre2020_backfill`
- `wr` `1m` `partial_start` gap `2009-03-27`..`2010-01-03` action `minute_pre2020_backfill`
- `y` `1m` `partial_start` gap `2006-01-09`..`2010-01-03` action `minute_pre2020_backfill`
- `zn` `1m` `partial_start` gap `2007-03-26`..`2010-01-03` action `minute_pre2020_backfill`

## Roll Product-Period Worst Status (first 30)

- `cu` `1m` `missing_segment` gaps `217/258`
- `al` `1m` `missing_segment` gaps `210/252`
- `al` `1w` `missing_segment` gaps `195/252`
- `zn` `1d` `missing_segment` gaps `194/230`
- `cu` `1w` `missing_segment` gaps `189/258`
- `zn` `1m` `missing_segment` gaps `188/230`
- `zn` `1w` `missing_segment` gaps `182/230`
- `if` `1m` `missing_segment` gaps `153/195`
- `pb` `1m` `missing_segment` gaps `134/176`
- `pb` `1w` `missing_segment` gaps `130/176`
- `fu` `1m` `missing_segment` gaps `109/126`
- `cu` `1d` `missing_segment` gaps `106/258`
- `al` `1d` `missing_segment` gaps `100/252`
- `fu` `1w` `missing_segment` gaps `94/126`
- `b` `1m` `missing_segment` gaps `93/119`
- `ic` `1m` `missing_segment` gaps `93/135`
- `ih` `1m` `missing_segment` gaps `93/135`
- `if` `1w` `missing_segment` gaps `80/195`
- `ru` `1m` `missing_segment` gaps `80/90`
- `b` `1w` `missing_segment` gaps `79/119`
- `sc` `1w` `missing_segment` gaps `78/93`
- `fu` `1d` `missing_segment` gaps `72/126`
- `sn` `1w` `missing_segment` gaps `72/90`
- `ru` `1w` `missing_segment` gaps `70/90`
- `cf` `1m` `missing_segment` gaps `68/78`
- `ta` `1w` `missing_segment` gaps `68/71`
- `cf` `1w` `missing_segment` gaps `64/78`
- `sr` `1w` `missing_segment` gaps `62/67`
- `ta` `1d` `missing_segment` gaps `62/71`
- `wr` `1w` `missing_segment` gaps `62/74`
