import assert from 'node:assert/strict'
import { detailBar, mockMarketDetail, subingEvent, subingRule } from './market-detail.helpers.mjs'
export const referenceBars = Array.from({ length: 80 }, (_, index) => detailBar('jm', index, Math.round((1100 + Math.sin(index / 7) * 34 + index / 3) * 10) / 10))
export function subingReferenceFixture() {
  const at = [8, 25, 46, 64]
  const signals = at.map((index, i) => ({ signal_id: `fixture-signal-${i}`, bar_end: referenceBars[index].bar_end, trading_day: referenceBars[index].trading_day, physical_contract: 'JM2601', segment_id: 'fixture-segment', direction: i % 2 ? 'buy' : 'sell', reference_price: String(referenceBars[index].close), action: i === 0 ? 'OPEN_SHORT' : i % 2 ? 'REVERSE_TO_LONG' : 'REVERSE_TO_SHORT', entry_trade_id: `fixture-trade-${i}`, closed_trade_id: i ? `fixture-trade-${i - 1}` : null, closed_return_pct: i ? ['3.475652787579393083980239944', '2.814841893620910254066898190', '-0.5155555555555555555555555556'][i - 1] : null }))
  const items = signals.map((signal, i) => ({ reference_trade_id: `fixture-trade-${i}`, side: signal.direction === 'buy' ? 'LONG' : 'SHORT', physical_contract: 'JM2601', segment_id: 'fixture-segment', entry_signal_id: signal.signal_id, entry_bar_end: signal.bar_end, entry_trading_day: signal.trading_day, entry_reference_price: signal.reference_price, exit_signal_id: signals[i + 1]?.signal_id ?? null, exit_bar_end: signals[i + 1]?.bar_end ?? null, exit_trading_day: signals[i + 1]?.trading_day ?? null, exit_reference_price: signals[i + 1]?.reference_price ?? null, status: i === 3 ? 'OPEN' : 'CLOSED', holding_bars: (at[i + 1] ?? referenceBars.length - 1) - at[i], reference_return_pct: signals[i + 1]?.closed_return_pct ?? null, mark_bar_end: i === 3 ? referenceBars.at(-1).bar_end : null, mark_reference_price: i === 3 ? String(referenceBars.at(-1).close) : null, mark_change_pct: i === 3 ? '-3.272019808984789529536611249' : null, interrupted_at: null, initial: false })).reverse()
  const fixture = { symbol: 'jm', frequency: '15m', series_kind: 'actual_dominant', formula_version: 'subing_ths_15m_v3', reference_model_version: 'subing_reference_reverse_close_v1', as_of: '2026-09-08T16:00:00+08:00', performance_since: '2026-08-12', performance_through: '2026-09-08', reference_cutoff: '2026-09-08T15:00:00+08:00', input_snapshot_hash: 'a'.repeat(64), executable: false, auto_order: false, source: 'historical_replay', summary: { closed_count: 3, win_count: 2, loss_count: 1, flat_count: 0, open_count: 1, interrupted_count: 0, initial_count: 0, win_rate_pct: '66.67', mean_return_pct: '1.924979708548249260830527526', sum_return_percentage_points: '5.774939125644747782491582578' }, signals, items, next_before: null }
  // Fixture coherence: every displayed count and holding interval has an exact source.
  assert.equal(fixture.summary.closed_count, items.filter(item => item.status === 'CLOSED' && !item.initial).length)
  assert.equal(fixture.summary.open_count, items.filter(item => item.status === 'OPEN' && !item.initial).length)
  assert.equal(fixture.summary.initial_count, items.filter(item => item.initial).length)
  for (const item of items) {
    assert.equal(item.initial, item.entry_trading_day < fixture.performance_since)
    const entryIndex = referenceBars.findIndex(bar => bar.bar_end === item.entry_bar_end)
    const endIndex = referenceBars.findIndex(bar => bar.bar_end === (item.exit_bar_end ?? item.mark_bar_end))
    assert.equal(item.holding_bars, endIndex - entryIndex)
    assert.equal(item.entry_reference_price, String(referenceBars[entryIndex].close))
    assert.equal(item.exit_reference_price ?? item.mark_reference_price, String(referenceBars[endIndex].close))
  }
  return fixture
}
export async function mockSubingReference(page, { unavailable = false, response } = {}) {
  const facts = await mockMarketDetail(page, { barsPage: ({ url }) => url.searchParams.get('frequency') === '15m' ? { bars: referenceBars } : undefined, alertEvents: () => [{ ...subingEvent('jm'), bar_end: referenceBars[8].bar_end }], alertRules: [subingRule()] })
  await page.route('**/api/v1/market/jm/subing/reference*', (route) => unavailable ? route.fulfill({ status: 409, json: { detail: { code: 'SUBING_REFERENCE_DATA_UNAVAILABLE' } } }) : route.fulfill({ json: response ? response(new URL(route.request().url())) : subingReferenceFixture() }))
  return facts
}
