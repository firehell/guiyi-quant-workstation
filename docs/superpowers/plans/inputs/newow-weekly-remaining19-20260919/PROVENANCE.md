# W1 remaining-19 input provenance

These files were copied from the uncommitted main-worktree evidence directory
`/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining19-20260919/`
at task start. They are immutable task inputs, not new production evidence.

| Input | SHA-256 |
| --- | --- |
| `report.md` | `06d93c56d283f60bf8f65b01e1d5f9390fe78b38c2ec166822d36643b4a850ce` |
| `audit-identity.json` | `69a52ba4e32a12f2bae7183d12224eefe79a78143885bcf8aeb8b81de362bd25` |
| `unknown-diagnosis.json` | `b7503bf228731ccb9cee5caca098527298171d068bb32522ace72164d037b944` |
| `unknown-diagnosis-develop.json` | `4f89f9dbe90cea574259cc5fe343d15834e9449209bc0815c758307b3718effe` |
| `integrity-diagnosis.json` | `6075ae49680fdc676554cf78fedc2a3e463dd5b748fa69d3a99f9525110cee78` |

The large `readiness-full.json` and `summary.json` remain at the source path;
their SHA-256 values are respectively
`ca5bbedde71448eff956e32b98e693b5b342d8ffaa5f66d3ec3ac682de82da2a`
and `15b041fe0ebe478a7ac7412a5d95cce2d2e18faf15311d88799b9daa6254e2e6`.
They were read without copying so this task does not commit 5.5 MiB of
generated audit output.

## Candidate v2 implementation boundary

`weekly-d1-quality-v2` is implemented only as an explicit MarketDataService
proof primitive. It has no Newow reader, service, page, snapshot-cache or
ReferenceTrade consumer in this change. An independent review found that
exposing it through the current reader would mix v1/v2 cache, token,
calculation and reference identities. Completing that safely requires a
coordinated identity change across `ProductIdentity`, SnapshotCache and the
parallel unified-reference-trading work. Until that work is approved and
tested, v2 is not a candidate release and no remaining product is opened.

The copied plan originated at
`/Volumes/扩展盘/guiyi-quant-workstation/docs/superpowers/plans/2026-09-19-newow-w1-remaining19-repair-plan.md`
with SHA-256
`8e984f1e5f8356f4bddc596f898885040119c6e92e09d19ecc5b59f2ad86af37`.
