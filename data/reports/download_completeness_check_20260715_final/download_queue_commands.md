# Download Queue Commands

Generated from `download_pending_inventory` audit_end=`2026-07-10`.

## P0 — Dominant 1w pre-2020

Products (0): ``

```bash
uv run --project services/quant-api python scripts/rqdata_weekly_pre2020_backfill.py \
  --weekly-history-csv data/reports/download_pending_inventory_YYYYMMDD/pending_download_matrix.csv \
  --run-write --register
```

## P1 — Dominant 1d pre-2020

Products (0): ``

```bash
uv run --project services/quant-api python scripts/rqdata_daily_pre2020_backfill.py \
  --run-write --register
```

## P2 — Roll 1w missing products

Products (1): `pd`

```bash
# Example for one product; repeat for each in the list above
uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_batch.py \
  --product pd \
  --start-date 2020-01-02 --end-date 2026-07-10 \
  --periods 1w --roll-segments --run-write
```

## P3 — Roll segment gaps (1m/1d/1w)

Products with any roll segment gap (90): `a, ad, ag, al, ao, ap, au, b, bb, bc, br, bu, bz, c, cf, cj, cs, cu, cy, eb, ec, eg, fb, fg, fu, hc, i, ic, if, ih, im, j, jd, jm, jr, l, l_f, lc, lg, lh...`

```bash
PRODUCTS_FILE=data/universe/full_products_90.txt \
START_DATE=2020-01-02 END_DATE=2026-07-10 BAR_PERIODS=1m,1d,1w LAYER=layer2 \
./scripts/rqdata_full_universe_download.sh
```

## P4 — Dominant 1m pre-2020 (traffic heavy)

Products (0): ``

```bash
uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \
  --traffic-budget-mb 800 --run-write --register
```
