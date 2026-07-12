# Source Interval Provenance Repair Apply

- mode: `source_interval_provenance_repair_apply`
- operation: `apply`
- output_dir: `data/reports/source_interval_provenance_repair_apply_pilot_20260712`
- selected_candidate_count: `5`
- processed_candidate_count: `5`
- applied_candidate_count: `5`
- skipped_candidate_count: `0`
- blocked_candidate_count: `0`
- writes_database: `True`
- writes_parquet: `True`
- writes_manifest: `True`
- writes_processed_summary: `False`
- calls_rqdata: `False`

## Boundary

- Only `source_interval=1m` provenance and checksum/file_size synchronization are in scope.
- This task does not change `row_count`, `data_version`, `data_role`, `quality_status`, DB registration scope, failed quality assets, strategy, signal, live runtime, scheduler or trading execution.

## Candidate Results

| candidate_id | product | period | applied | skipped | blocked_reason |
|---|---|---|---|---|---|
| `source_interval_0001` | `ic` | `15m` | `True` | `False` | `` |
| `source_interval_0002` | `if` | `15m` | `True` | `False` | `` |
| `source_interval_0003` | `ih` | `15m` | `True` | `False` | `` |
| `source_interval_0004` | `im` | `15m` | `True` | `False` | `` |
| `source_interval_0005` | `ap` | `15m` | `True` | `False` | `` |
