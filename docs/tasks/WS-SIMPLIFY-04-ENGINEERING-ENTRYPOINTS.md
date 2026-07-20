# WS-SIMPLIFY-04-ENGINEERING-ENTRYPOINTS

| Field | Value |
|---|---|
| Task ID | WS-SIMPLIFY-04-ENGINEERING-ENTRYPOINTS |
| Status | `DELIVERY_READY` |
| Date | 2026-07-20 |

## Deliverables

- `scripts/engineering/{preflight,test,check-secrets,runtime-health,production-write-check}.sh`
- `tests/engineering/test_engineering_entrypoints.py`
- Deprecated hints on `dispatch_task.sh` / `workbuddy_task.sh` / `route_task.sh` (behavior unchanged)

## Verification

```bash
bash -n scripts/engineering/*.sh
python3 -m pytest -q tests/engineering
bash scripts/engineering/preflight.sh --json
bash scripts/engineering/production-write-check.sh --action smoke  # exit 3
git diff --check
```
