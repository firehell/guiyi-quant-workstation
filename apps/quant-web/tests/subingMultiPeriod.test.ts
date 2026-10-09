import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeAlertEventFacts } from '../src/utils/alertRules.ts'
import { parseMarketDetailRoute } from '../src/utils/marketDetailRoute.ts'
for (const frequency of ['5m','15m','30m','60m','1d','1w'] as const) test(`苏冰 ${frequency} 持久信号与聚焦路由`, () => {
  assert.equal(normalizeAlertEventFacts('subing_ths_alert_15m_v1', frequency, ['sell']).ruleCode, 'subing_ths_alert_15m_v1')
  assert.equal(parseMarketDetailRoute({view:'subing',symbol:'jm',frequency,focus_bar_end:'2026-10-08T07:00:00Z'}).kind,'valid')
})

import { normalizeSubingAlignment } from '../src/utils/marketHomeTypes.ts'
const alignment = {policy_version:'ema21_alignment_v1',as_of:'2026-10-08T07:00:00Z',observed_at:'2026-10-08T07:00:10Z',status:'UNKNOWN',periods:['5m','15m','30m','60m','1d','1w'].map(frequency => ({frequency,contract:'JM2701',bar_end:null,close:null,ema21:null,direction:'UNKNOWN',reason:'DATA_INSUFFICIENT'}))}
test('保存快照读回，未知和旧记录不冒充同向', () => {
  assert.equal(normalizeSubingAlignment(alignment)?.status, 'UNKNOWN')
  assert.equal(normalizeSubingAlignment(null), null)
  assert.throws(() => normalizeSubingAlignment({...alignment,periods:alignment.periods.slice(0,5)}))
  assert.throws(() => normalizeSubingAlignment({...alignment,periods:alignment.periods.map(row=>({...row,close:12}))}))
})

test('Decimal指数字符串原样保留且拒绝非有限值', () => {
  const snapshot = {...alignment, periods: alignment.periods.map(row => ({...row,close:'1E+3',ema21:'9.99E+2'}))}
  assert.equal(normalizeSubingAlignment(snapshot)?.periods[0].close, '1E+3')
  for (const close of ['NaN','Infinity','0x10','1 2','']) assert.throws(() => normalizeSubingAlignment({...snapshot,periods:snapshot.periods.map(row=>({...row,close}))}))
})
