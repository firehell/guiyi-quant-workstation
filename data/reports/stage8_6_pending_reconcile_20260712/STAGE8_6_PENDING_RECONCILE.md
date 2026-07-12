# Stage 8.6 Pending Reconcile

- matrix_file: `/Volumes/扩展盘/guiyi-quant-workstation/data/reports/stage8_6_active_gate_matrix.csv`
- pending_count: 8
- writes_database: False
- writes_parquet: False
- calls_rqdata: False

## Disposition Counts

- accepted_warning: 5
- metadata_mismatch: 0
- registration_not_needed: 3
- requires_apply_gate: 0
- blocked_needs_manual_review: 0

## Ledger

- `bb/bb.MAIN/1d` -> `accepted_warning`: dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed
- `l/L2609F/1d` -> `registration_not_needed`: Stage 8.6 snapshot uses product=l but canonical product=l_f already active_passed with DB registration; LPV dry-run eligible=0
- `pp/PP2609F/1d` -> `registration_not_needed`: Stage 8.6 snapshot uses product=pp but canonical product=pp_f already active_passed with DB registration; LPV dry-run eligible=0
- `rs/rs.MAIN/1d` -> `accepted_warning`: dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed
- `v/V2609F/1d` -> `registration_not_needed`: Stage 8.6 snapshot uses product=v but canonical product=v_f already active_passed with DB registration; LPV dry-run eligible=0
- `wh/wh.MAIN/1d` -> `accepted_warning`: dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed
- `wr/wr.MAIN/1d` -> `accepted_warning`: dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed
- `zc/zc.MAIN/1d` -> `accepted_warning`: dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed
