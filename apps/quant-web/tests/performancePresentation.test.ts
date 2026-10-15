import assert from 'node:assert/strict'
import test from 'node:test'
import { annualizedReference, metricUnit, performanceDrawdownLabel } from '../src/utils/performancePresentation.ts'

test('annualization has explicit starting baseline and duration and never fabricates values', () => {
  assert.equal(annualizedReference({start:0,end:10,days:365}),10.000000000000009)
  assert.equal(annualizedReference({start:10,end:21,days:365}),10.000000000000009)
  for (const args of [{start:0,end:1,days:0},{start:-100,end:1,days:365},{start:0,end:-100,days:365},{start:NaN,end:1,days:2}]) assert.equal(annualizedReference(args),null)
})
test('metric labels distinguish percentage point drawdown from normalized equity and loss', () => {
  assert.equal(metricUnit('percentage_points'),'百分点')
  assert.equal(performanceDrawdownLabel('page'),'页面曲线回撤（百分点）')
  assert.equal(performanceDrawdownLabel('reference'),'参考权益比例回撤')
  assert.equal(performanceDrawdownLabel('account'),'模型账户回撤')
  assert.equal(performanceDrawdownLabel('loss'),'单笔最大亏损')
})

test('small nonzero returns retain a visible bound rather than rounding to zero', async () => {
  const { newowReferencePercent, newowReferencePoints } = await import('../src/utils/newowPagePresentation.ts')
  assert.equal(newowReferencePercent('0.001'),'<0.01%')
  assert.equal(newowReferencePoints('-0.001'),'>-0.01 百分点')
  assert.equal(newowReferencePoints('0'),'0.00 百分点')
})
