# Newow W1 remaining-19 external Gate packet

Status: `PREPARED_ONLY / EXTERNAL_GATE_PENDING`

This packet records a proposed bounded recovery batch. It is not authorization and no
provider request, Canonical write, Catalog write, retry, release, or Runtime action was
performed while producing it.

## Frozen execution identity

- Code commit: `b02e37b4f8b11aad53c986f4c50b0efeb340376d`
- Execution code SHA-256: `e22897fb878cbd86b9c13e60c75de42ec4b0a9831a428e3076e1175235092313`
- Configuration SHA-256: `c9df3ef2a1a9f4b856b0fdc7a0839eaf9040fcad0eb56b6adc573b819c4ab746`
- Canonical root SHA-256: `1094b8d30a5f54593c407af265e2f3fc9bdb1655f9a9db84aeba15b74289e5ab`
- Frequency: `1w`; source requests target physical-contract exchange daily data and
  the prepared units bind the derived `1d` and `1w` targets.
- Maintenance lock was available at prepare time. Apply must revalidate every frozen
  identity and acquire the required lock; drift fails closed and requires a new prepare.

## Exact ordered batch

Run strictly in this order and stop the batch at the first non-passed unit or unknown
outcome. Do not begin a later manifest until the preceding manifest has a complete,
inspectable passed result.

| Order | Scope | Units | Provider-request ceiling | Expected-bar ceiling | Prepared SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | J, 5 physical contracts | 5 | 80 | 915 | `80e2fa2ff048b3c033c44f27143ce1c6cf93617caeeefc736c3eb4eb7bbe3e4d` |
| 2 | PG part 1, 20 physical contracts | 20 | 431 | 4,835 | `95fabe9806f7e19268def7451043e29d06039d428f527d35ef165f52c9cd0c4d` |
| 3 | PG part 2, 5 physical contracts | 5 | 107 | 1,190 | `f7059620e1b98cb733625e46bf3687a47fb7640ee52aae6aeefb8ab59c431277` |
| 4 | SI part 1, 20 physical contracts | 20 | 346 | 3,968 | `1163e7c910b472c52dd248695f691f715ca4aa865b5c819b59130b61e7b80626` |
| 5 | SI part 2, 5 physical contracts | 5 | 92 | 1,070 | `4bcb5825be15c1c244cca3145198633eee9eb98f13070de335b10deb5766b2f3` |

Total ceiling: 55 physical-contract units, 1,056 provider requests, and 11,978
expected source bars. The precise contracts, windows, expected dates, datasets, and
per-unit plan hashes are authoritative only in the five prepared manifests.

## Authorization boundary

Authorization, if granted, must separately name both of these scopes:

1. provider download for exactly the five manifests above; and
2. Canonical publication plus Catalog commit for exactly their validated results.

Authorizing provider download alone does not authorize Canonical or Catalog mutation.
Neither scope authorizes any other product, contract, period, retry, release, Runtime
promotion, notification, or broker action.

## Fail-closed and recovery contract

- Each manifest is immutable and must be supplied with its exact SHA-256. Use one new,
  unique attempt ID and an empty direct-child attempt directory for each apply.
- `retry_allowed=false`: do not automatically retry a failed, interrupted, timed-out,
  or result-unknown apply, and never reuse an attempt ID.
- Stop before source mutation if checkout, code, config, Canonical root, lock, manifest,
  request count, expected dates, contract identity, or unit plan hash differs.
- Stop after any source-quality, hard-validation, staging, commit, post-commit replan,
  Catalog, or MarketDataService readback failure. Do not continue to the next unit or
  manifest and do not synthesize or substitute source values.
- For interruption or unknown outcome, first run the read-only `inspect` operation on
  the exact attempt directory. Reconcile its invocation receipt, source evidence,
  per-unit result, committed file identities, Catalog rows, and post-commit readback.
  Do not delete, overwrite, roll back, or retry until the outcome is proven and a new
  explicit recovery authorization is obtained.
- A passed unit requires its atomic commit receipt, zero remaining targets after replan,
  and exact Catalog/MarketDataService readback. A passed manifest does not by itself
  establish the 19-product strategy or page Gate; the fixed 57-case audit must be rerun
  against the resulting frozen Catalog revision.

Prepared files:

- `j-prepared-reviewed/j-w1-v2-20260919-reviewed.prepare.json`
- `pg-prepared-reviewed/pg-w1-v2-20260919-reviewed-001.prepare.json`
- `pg-prepared-reviewed/pg-w1-v2-20260919-reviewed-002.prepare.json`
- `si-prepared-reviewed/si-w1-v2-20260919-reviewed-001.prepare.json`
- `si-prepared-reviewed/si-w1-v2-20260919-reviewed-002.prepare.json`
