import assert from 'node:assert/strict'
import test from 'node:test'
import { homeProjectionSummary, homeRecoveryNotice } from '../src/utils/homeProjectionNotice.ts'
import type { CardDelivery } from '../src/utils/newowHomeCards.ts'
const delivery = (status: CardDelivery['projectionStatus'], recovery?: CardDelivery['recovery']): CardDelivery => ({ card:null, stale:true, loading:false, failed:false, projectionStatus:status, recovery })
test('current sector status excludes other sectors while cold request failures remain visible', () => {
 const entries = { rb: delivery('ready'), sf:delivery('failed', {status:'blocked',category:'program',code:'HOME_BUILD_FAILED'}) }
 assert.equal(homeProjectionSummary(['rb'], entries, null), '')
 assert.match(homeProjectionSummary(['sf'], entries, null), /SF/)
 assert.match(homeProjectionSummary(['rb'], {}, 'transport'), /读取失败.*暂无已验证摘要/)
 assert.match(homeProjectionSummary(['rb'], {}, 'protocol'), /响应校验失败/)
 assert.match(homeProjectionSummary(['rb'], {}, 'access'), /访问受限/)
})
test('pending does not claim running and blocked details retain attempt and no-cache semantics', () => {
 assert.match(homeRecoveryNotice(delivery('updating', {status:'pending'})), /^待更新/)
 assert.match(homeRecoveryNotice(delivery('updating', {status:'running'})), /^计算中/)
 assert.match(homeRecoveryNotice(delivery('failed', {status:'retry_wait'})), /^重试等待/)
 assert.match(homeRecoveryNotice(delivery('failed', {status:'blocked',category:'program',code:'HOME_BUILD_FAILED',last_attempt_at:'2026-11-06T08:00:00Z'})), /program.*HOME_BUILD_FAILED.*暂无已验证摘要.*最近尝试/)
})

test('rebuild progress counts disjoint running queued failures and waits over the whole product set', () => {
 const entries={
  a:delivery('ready'),b:delivery('updating',{status:'running'}),c:delivery('stale',{status:'pending'}),
  d:delivery('failed',{status:'blocked',category:'program',code:'HOME_BUILD_FAILED'}),
  e:delivery('failed',{status:'retry_wait'}),f:delivery('stale',{status:'dependency_wait'}),
 }
 entries.c.periodReasons={'1d':'SOURCE_VERSION_CHANGED'}
 const text=homeProjectionSummary(['a','b','c','d','e','f','g'],entries,null)
 assert.match(text,/新版摘要正在重建，已完成1\/7/)
 for (const label of ['排队1','计算中1','失败1','重试等待1','等待依赖1','待读取1'])assert.ok(text.includes(label))
 assert.match(text,/阻塞：D/)
 assert.equal(homeProjectionSummary(['a'],entries,null),'')
})
