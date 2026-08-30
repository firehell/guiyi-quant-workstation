import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { findStaticImportCycles } from '../scripts/checkProductionBundleTopology.mjs'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const viteEntry = join(projectRoot, 'node_modules', 'vite', 'bin', 'vite.js')
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
