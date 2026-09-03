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

test('activates generic D1 facts and mounts Trend only for the explicit Trend route', () => {
  const { source, template } = page()

  assert.match(source, /import TrendDetailWorkspace/)
  assert.match(source, /\['free',\s*'htdy',\s*'trend'\]\.includes\(explicitIdentity\.value\?\.view/)
  assert.match(source, /\['free',\s*'htdy',\s*'trend'\]\.includes\(result\.identity\.view/)
  assert.match(template, /<TrendDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'trend'"/)
  assert.match(template, /:identity="routeResult\.identity"/)
  assert.match(template, /:header="header"/)
  assert.match(template, /:bars="controller\.bars\.value"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy'"/)
  assert.doesNotMatch(template, /<HtdyDetailWorkspace\s+v-else(?:\s|>)/)
})

test('keeps SuBing unavailable and gives Trend history but no alert action or focus expansion', () => {
  const { source, template } = page()

  assert.match(template, /routeResult\.identity\.view === 'subing'/)
  assert.match(template, /新苏冰 Workspace 尚未接入统一详情页/)
  assert.match(source, /hasTrendHistory/)
  assert.match(source, /trendWorkspace\.value\?\.openHistory\(\)/)
  assert.match(template, /canOpenHistory:\s*routeResult\.identity\.view === 'trend'\s*\?\s*hasTrendHistory/s)
  assert.match(template, /canManageAlert:\s*false/)
  assert.match(template, /@history-availability="hasTrendHistory = \$event"/)
  assert.doesNotMatch(template, /<TrendDetailWorkspace[^>]+focus-bar-end/s)
  assert.doesNotMatch(template, /<TrendDetailWorkspace[^>]+open-alert/s)
})

test('keeps Free and HTDY as separate explicit workspaces', () => {
  const { template } = page()

  assert.match(template, /<FreeChartWorkspace\s+v-if="routeResult\.identity\.view === 'free'"/)
  assert.match(template, /<HtdyDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'htdy'"/)
  assert.match(template, /<TrendDetailWorkspace\s+v-else-if="routeResult\.identity\.view === 'trend'"/)
})
