# Local Backup and Isolated Restore

## Status

```text
LOCAL_BACKUP_ARTIFACT_CODE_COMPLETE
PRODUCTION_BACKUP_NOT_EXECUTED
ISOLATED_RESTORE_SMOKE_NOT_RUN
```

W7 implements a create-only local backup artifact. W8 implements the fail-closed isolated restore tool, but
no real restore smoke has been run because no W7 full artifact is available. No production database,
canonical Parquet, Profile binding, Runtime configuration, Redis state, notification, or trading path is
modified.

## Backup modes

The command is dry-run unless `--execute` is present. Exactly one mode is required:

```bash
PYTHONPATH=services/quant-api:. \
uv run --project services/quant-api \
python -m scripts.backup.create \
  --full \
  --source-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-root /Volumes/扩展盘/GuiyiBackup
```

`--database-only`, `--data-only`, and `--full` are mutually exclusive. Raw RQData is excluded unless
`--include-raw` is supplied with a data mode. The output root must already exist on a different mounted
device from the source root. The filesystem root is rejected as an output mount, so a missing external
volume cannot silently fall back to a residual directory on the system volume.

S6-10 has one explicit degraded exception:

```bash
--full \
--retention-class milestone \
--same-device-milestone-snapshot \
--approved-external-profile-root /Volumes/扩展盘/GuiyiApprovals/s607/4d05370f-20260727-materializerfix/retry-service
```

This flag is rejected for database-only/data-only, non-milestone retention, or
when raw data is included. It records
`storage_scope=same_device_snapshot`,
`independent_device_backup=false`, and
`disaster_recovery_ready=false` in the manifest. The default remains
fail-closed for same-device output.

The external Profile root option is separately fail-closed: only active
`market_data_files.file_path` values physically contained by an explicitly
listed absolute root are copied. They are stored under a safe synthetic
artifact-relative path while the original registered path is frozen for
isolated DB identity verification. Relative traversal, symlinks, missing
files, unapproved roots, checksum drift, and path collisions are rejected.

Database/full mode uses one PostgreSQL `REPEATABLE READ READ ONLY` exported snapshot and official
`pg_dump --format=custom --no-owner --no-acl --snapshot`. `--pg-tool-mode auto` prefers a host `pg_dump`
and otherwise uses the official tool inside `guiyi-postgres`. Passwords remain in the child environment and
are never placed in argv, manifest, or logs.

## Artifact and boundaries

The tool stages the artifact under the output root, verifies dump/file/inventory/manifest SHA-256, makes the
completed tree read-only, and atomically renames it to the backup ID. Existing IDs are never overwritten.
An exclusive create-only lock serializes the same backup ID; a stale lock fails closed and requires an
operator to inspect it rather than being deleted automatically. Failure cleanup restores permissions only
inside the staging directory created by that invocation, removes that partial tree, and never removes an
existing artifact.

Critical data includes canonical Parquet, manifests, processed provenance, versioned reports, Profile/OOS
config, universe config, and non-secret environment/launchd templates. Secrets, Redis, logs, cache, market
cache, worktrees, virtual environments, and Runtime checkouts are excluded. Full backup also proves that
every active Profile binding file is present in the artifact and that frozen report 14 remains MD5
`ae807ef77f7d9a4ce3067996558b57e8` with 155 trades and 239 orders. Active Profile evidence uses a left join
and records each binding identity, Profile config, canonical file, size, and SHA-256; null or dangling rows,
path traversal, missing files, and checksum/size drift all fail closed.

Retention metadata is recorded as 7 daily, 4 weekly, 12 monthly, and indefinite milestone backups. W7 never
deletes backups automatically; pruning requires a future independent task and explicit approval.

## Restore boundary

Production restore is forbidden. W8 provides an isolated-only command:

```bash
PYTHONPATH=services/quant-api:. \
uv run --project services/quant-api \
python -m scripts.restore.isolated \
  --backup-root /path/to/w7-full-artifact \
  --isolated \
  --target-database guiyi_restore_smoke_001 \
  --target-data-root /private/tmp/guiyi-restore-smoke-001 \
  --confirm-isolated-restore
```

Only a verified W7 `full` artifact is accepted. The target database must use the `guiyi_restore_*`
namespace and is created in a disposable `postgres:16` container; the target data root must be absent or
empty and must not overlap the backup, production project, or production data roots. The container and its
volume are removed before the create-only receipt is published.

The verifier compares the restored Alembic revision, all manifest table counts, report 14, Profile binding
and config identity, and every restored file checksum. Market/Backtest/Signal/Review smoke uses only GET in
a PostgreSQL read-only transaction. Absolute production file registrations are rebound only in the
SQLAlchemy identity map with no flush or commit; table content hashes must remain unchanged. No Redis,
worker, scheduler, WeCom, migration, Profile switch, or production restore path is invoked.

Fake-tool tests do not count as an isolated restore smoke. No real W7 full artifact currently exists, so the
current W8 gate remains `ISOLATED_RESTORE_SMOKE_NOT_RUN`.
For HTDY S6-10, the approved snapshot root is exactly
`/Volumes/扩展盘/GuiyiBackup`. It must be a real directory on the already
mounted `/Volumes/扩展盘` filesystem, must not be a symlink, and must have at
least 10 GiB free before creating any Approval C artifact. The resulting
artifact proves file/DB/Profile consistency and isolated restoreability, but
does not protect against loss of the expansion disk. Do not reuse an older
W7/W8 test result as the S6-10 receipt.
S6-10 `prepare` does not trust that receipt alone: after validating the source
artifact it performs a second fresh disposable postgres:16 restore audit under
`/private/tmp/guiyi-restore-s610-audit-*` and binds that audit receipt into the
parent packet. The audit is still an isolated restore and never targets the
production database.
