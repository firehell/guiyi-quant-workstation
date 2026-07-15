# Download Pending Inventory

- mode: `download_pending_inventory`
- audit_end: `2026-07-10`
- products: `90`
- rqdata_start_policy: `1d/1w=max(listed, 2000-01-04); 1m=max(listed, 2010-01-04)`
- writes_database: `False`
- writes_parquet: `False`
- calls_rqdata: `False`

## Gap Summary

| metric | count |
|---|---:|
| dominant gaps (product×period) | 0 |
| roll gap segments | 3604 |
| product-period worst-status gaps | 119 |

## Dominant Main Gaps By Period

| period | gap_count |
|---|---:|
| `1m` | 0 |
| `1d` | 0 |
| `1w` | 0 |

## Roll Gap Segments By Period

| period | gap_count |
|---|---:|
| `1m` | 22 |
| `1d` | 489 |
| `1w` | 3093 |

## Roll Product-Period Worst Status (first 30)

- `al` `1w` `missing_segment` gaps `181/252`
- `cu` `1w` `missing_segment` gaps `169/258`
- `zn` `1w` `missing_segment` gaps `147/230`
- `pb` `1w` `missing_segment` gaps `124/176`
- `fu` `1w` `missing_segment` gaps `87/126`
- `if` `1w` `missing_segment` gaps `80/195`
- `b` `1w` `missing_segment` gaps `79/119`
- `ru` `1w` `missing_segment` gaps `66/90`
- `cu` `1d` `missing_segment` gaps `62/258`
- `sc` `1w` `missing_segment` gaps `60/93`
- `sn` `1w` `partial_segment` gaps `60/90`
- `al` `1d` `missing_segment` gaps `59/252`
- `c` `1w` `missing_segment` gaps `57/77`
- `ta` `1w` `missing_segment` gaps `57/71`
- `cf` `1w` `missing_segment` gaps `55/78`
- `wr` `1w` `missing_segment` gaps `54/74`
- `a` `1w` `missing_segment` gaps `53/76`
- `fu` `1d` `missing_segment` gaps `53/126`
- `sr` `1w` `missing_segment` gaps `53/67`
- `ni` `1w` `missing_segment` gaps `50/93`
- `ic` `1w` `missing_segment` gaps `47/135`
- `bb` `1w` `missing_segment` gaps `45/81`
- `m` `1w` `missing_segment` gaps `45/68`
- `pg` `1w` `partial_segment` gaps `44/66`
- `eb` `1w` `missing_segment` gaps `43/70`
- `ih` `1w` `missing_segment` gaps `41/135`
- `l` `1w` `missing_segment` gaps `41/63`
- `nr` `1w` `missing_segment` gaps `41/79`
- `y` `1w` `missing_segment` gaps `41/63`
- `ru` `1d` `missing_segment` gaps `38/90`
