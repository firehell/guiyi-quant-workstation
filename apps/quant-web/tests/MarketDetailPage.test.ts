import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { parse } from '@vue/compiler-sfc'

const componentUrl = new URL('../src/pages/market/MarketDetailPage.vue', import.meta.url)

function page() {
  const source = readFileSync(componentUrl, 'utf8')
  const parsed = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(parsed.errors, [], 'MarketDetailPage must remain a valid Vue SFC')
  assert.ok(parsed.descriptor.scriptSetup)
  assert.ok(parsed.descriptor.template)
  return { source, template: parsed.descriptor.template.content }
}

test('activates generic D1 facts and mounts each workspace only for its explicit route', () => {
  const { source, template } = page()

  assert.match(source, /import TrendDetailWorkspace/)
  assert.match(source, /\['free',\s*'htdy',\s*'trend',\s*'subing'\]\.includes\(explicitIdentity\.value\?\.view/)
  assert.match(source, /\['free',\s*'htdy',\s*'trend',\s*'subing'\]\.includes\(result\.identity\.view/)
  assert.match(template, /<TrendDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'trend'"/)
  assert.match(template, /:identity="routeResult\.identity"/)
  assert.match(template, /:header="header"/)
  assert.match(template, /:bars="controller\.bars\.value"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy'"/)
  assert.match(template, /<SubingDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'subing'"/)
  assert.doesNotMatch(template, /<HtdyDetailWorkspace\s+v-else(?:\s|>)/)
})

test('gives SuBing and Trend history, while alert management remains unavailable', () => {
  const { source, template } = page()

  assert.match(source, /subingWorkspace\.value\?\.openHistory\(\)/)
  assert.match(source, /hasTrendHistory/)
  assert.match(source, /trendWorkspace\.value\?\.openHistory\(\)/)
  assert.match(template, /routeResult\.identity\.view === 'subing'\s*\?\s*hasSubingHistory/s)
  assert.match(template, /canManageAlert:\s*false/)
  assert.match(template, /@history-availability="hasTrendHistory = \$event"/)
  assert.match(template, /<SubingDetailWorkspace[^>]+focus-bar-end/s)
  assert.doesNotMatch(template, /<TrendDetailWorkspace[^>]+focus-bar-end/s)
  assert.doesNotMatch(template, /<TrendDetailWorkspace[^>]+open-alert/s)
})

test('keeps Free and HTDY as separate explicit workspaces', () => {
  const { template } = page()

  assert.match(template, /<FreeChartWorkspace\s+v-if="routeResult\.identity\.view === 'free'"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy'"/)
  assert.match(template, /<TrendDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'trend'"/)
  assert.match(template, /<SubingDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'subing'"/)
})
