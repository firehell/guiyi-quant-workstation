# Quant Chart

`@guiyi/quant-chart` owns native chart resources, display catalog, profiles and display-only volume policies. The application supplies completed market facts, previews, trusted indicator results and business markers. Native panes share the Lightweight Charts timeline and keep independent scales.

From this directory, run `pnpm install --frozen-lockfile` and `pnpm test`. Run `pnpm pack --pack-destination <absolute-output-directory>` to build the standalone tarball. The Web app pins the versioned tarball in `artifacts/` and its SHA-512 integrity in its own `pnpm-lock.yaml`. Releasing a package version and upgrading the Web dependency are separate steps.

Run the catalog contract check against the installed Quant Core package after building Quant Chart.

```sh
python -m guiyi_quant.compute.manifest | node scripts/validate-compute-catalog.mjs
```
