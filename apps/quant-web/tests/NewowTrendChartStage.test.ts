import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

import { createNewowTrendChartDisposer } from '../src/components/market/detail/newowTrendChartPrimitives.ts'

const componentUrl = new URL('../src/components/market/detail/NewowTrendChartStage.vue', import.meta.url)

test('the Trend chart stage is a valid Vue component with safe read-only diagnostics', () => {
  const source = readFileSync(componentUrl, 'utf8')
  const { descriptor, errors } = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(errors, [])
  assert.ok(descriptor.scriptSetup)
  assert.ok(descriptor.template)

  const script = compileScript(descriptor, { id: 'newow-trend-stage' })
  assert.match(script.content, /buildNewowTrendChartProjection/)
  const template = compileTemplate({
    id: 'newow-trend-stage', filename: componentUrl.pathname,
    source: descriptor.template.content,
  })
  assert.deepEqual(template.errors, [])
  assert.match(template.code, /newow-trend-chart-stage/)
  assert.match(template.code, /data-pane-count/)
  assert.match(template.code, /unavailableDisclosure/)
})

test('chart teardown unsubscribes crosshair, disconnects resize observation, and removes the chart once', () => {
  const calls: string[] = []
  const dispose = createNewowTrendChartDisposer({
    unsubscribeCrosshair: () => calls.push('unsubscribe-crosshair'),
    disconnectResizeObserver: () => calls.push('disconnect-resize'),
    removeChart: () => calls.push('remove-chart'),
  })

  dispose()
  dispose()

  assert.deepEqual(calls, ['unsubscribe-crosshair', 'disconnect-resize', 'remove-chart'])
})
