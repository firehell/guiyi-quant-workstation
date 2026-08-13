import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { alertRuntimeLabel, isCurrentAlertMutation } from '../src/utils/alertControl.ts'


const apiSource = read('../src/api/alerts.ts')
const controlSource = read('../src/components/market/ProductAlertControl.vue')
const chartSource = read('../src/pages/market/chart.vue')


describe('Product Alert server-side scope', () => {
  it('uses the exact GET and PUT server API contracts without localStorage truth', () => {
    assert.match(apiSource, /`\/api\/alerts\/products\/\$\{symbol\}`/)
    assert.match(apiSource, /`\/api\/alerts\/rules\/\$\{ruleCode\}\/scope\/\$\{symbol\}`/)
    assert.match(apiSource, /\{ enabled \}/)
    assert.doesNotMatch(apiSource, /localStorage|sessionStorage/)
    assert.doesNotMatch(chartSource, /localStorage.*alert|alert.*localStorage/i)
  })

  it('renders the switch directly from server true or false and emits the selected value', () => {
    assert.match(controlSource, /rule\?\.enabled_for_product \|\| false/)
    assert.match(controlSource, /@update:value="emit\('toggle', \$event\)"/)
    assert.match(chartSource, /alertRule\.value = updated/)
  })

  it('refetches on symbol change while series/frequency changes never invoke scope PUT', () => {
    const symbolWatcher = between(chartSource, 'watch(symbol, async () => {', 'watch([contract, seriesKind, frequency]')
    const identityWatcher = between(chartSource, 'watch([contract, seriesKind, frequency]', 'watch([symbol, seriesKind, contract]')
    assert.match(symbolWatcher, /refreshAlerts\(\)/)
    assert.doesNotMatch(identityWatcher, /setAlertProductEnabled|toggleAlert/)
    const toggle = between(chartSource, 'async function toggleAlert', 'async function loadEarlierBars')
    assert.match(toggle, /setAlertProductEnabled\(current\.rule_code, requestedSymbol, enabled\)/)
  })

  it('maps Runtime health to the three fixed labels', () => {
    assert.equal(alertRuntimeLabel('ok'), '正常')
    assert.equal(alertRuntimeLabel('disabled'), '未启用')
    assert.equal(alertRuntimeLabel('degraded'), '不可用')
    assert.equal(alertRuntimeLabel('failed'), '不可用')
  })

  it('rejects an old AG PUT response after AG to JM to AG generation changes', () => {
    assert.equal(isCurrentAlertMutation({
      requestGeneration: 1,
      currentGeneration: 3,
      requestedSymbol: 'ag',
      currentSymbol: 'ag',
      requestedRuleCode: 'htdy_original_15m',
      currentRuleCode: 'htdy_original_15m',
      updatedRuleCode: 'htdy_original_15m',
    }), false)
    assert.equal(isCurrentAlertMutation({
      requestGeneration: 3,
      currentGeneration: 3,
      requestedSymbol: 'ag',
      currentSymbol: 'ag',
      requestedRuleCode: 'htdy_original_15m',
      currentRuleCode: 'htdy_original_15m',
      updatedRuleCode: 'htdy_original_15m',
    }), true)
  })
})


function read(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), 'utf-8')
}

function between(source: string, start: string, end: string) {
  const from = source.indexOf(start)
  const to = source.indexOf(end, from + start.length)
  assert.notEqual(from, -1)
  assert.notEqual(to, -1)
  return source.slice(from, to)
}
