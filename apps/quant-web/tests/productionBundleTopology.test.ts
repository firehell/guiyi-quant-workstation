import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { findStaticImportCycles } from '../scripts/checkProductionBundleTopology.mjs'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const viteEntry = join(projectRoot, 'node_modules', 'vite', 'bin', 'vite.js')
const routerSource = readFileSync(join(projectRoot, 'src/app/router.ts'), 'utf8')

test('router registers only Market workspace routes', () => {
  const retiredRouteNames = [
    'dashboard',
    'signal',
    'strategy',
    'review',
    'data',
    'runtime',
    'settings',
    'trade-records',
    'backtests',
  ]
  for (const routeName of retiredRouteNames) {
    assert.equal(routerSource.includes(`name: '${routeName}'`), false, `router still registers ${routeName}`)
    assert.equal(routerSource.includes(`pages/${routeName}`), false, `router still imports pages/${routeName}`)
  }
  assert.match(routerSource, /name: 'market'/)
  assert.match(routerSource, /name: 'market-chart'/)
  assert.match(routerSource, /redirect: '\/market'/)
})

test('production charting vendor chunks have no static import cycle', () => {
  const outputRoot = join(tmpdir(), `guiyi-web-bundle-${process.pid}-${Date.now()}`)
  try {
    execFileSync(process.execPath, [viteEntry, 'build', '--outDir', outputRoot, '--emptyOutDir'], {
      cwd: projectRoot,
      stdio: 'pipe',
    })

    const cycles = findStaticImportCycles(join(outputRoot, 'assets'))
    assert.deepEqual(cycles, [], `charting vendor static import cycles:\n${JSON.stringify(cycles)}`)
  } finally {
    rmSync(outputRoot, { recursive: true, force: true })
  }
})
