import assert from 'node:assert/strict'
import test from 'node:test'
import { newowSimpleDualLabel, newowReferencePrice, newowReferencePercent } from '../src/utils/newowPagePresentation.ts'

test('simple dual labels retain the reference price and Decimal display preserves precision',()=>{
 assert.equal(newowSimpleDualLabel('trend',false,'3100.123456'),'建仓 3100.12')
 assert.equal(newowSimpleDualLabel('oscillation',true,'3200'),'清仓 3200.00')
 assert.equal(newowReferencePrice('9007199254740993.125'),'9007199254740993.13')
 assert.equal(newowReferencePrice(null),'—')
 assert.equal(newowReferencePercent('1.4'),'+1.40%')
 assert.equal(newowReferencePercent('0'),'0.00%')
})
