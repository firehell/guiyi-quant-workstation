import assert from 'node:assert/strict'
import test from 'node:test'
import { newowWaitingReference } from '../src/utils/newowWaitingReference.ts'
import type { NewowPageReferenceRecord } from '../src/types/newowProduct.ts'
const owner = {physical_contract:'JM2701',segment_id:'segment-a',calculation_segment_id:'calc-a',bar_end:'2026-10-20T07:00:00Z'}
const row = (overrides: Partial<NewowPageReferenceRecord> = {}): NewowPageReferenceRecord => ({buyDate:'2026-10-09T07:00:00Z',sellDate:'2026-10-16T07:00:00Z',buyPrice:'1491.48',sellPrice:'1499.20',pct:'0.52',forceClose:false,segment_id:'JM2701|segment-a|calc-a',...overrides})
test('waiting uses latest completed paired record in exact physical and calculation owner',()=>{
 const older=row({sellDate:'2026-10-10T07:00:00Z'}),latest=row()
 assert.equal(newowWaitingReference([latest,older],owner),latest)
 assert.equal(newowWaitingReference([older,latest],owner),latest)
})
test('waiting excludes rollover, calculation mismatch, future, open and invalid exits',()=>{
 const invalid=[row({segment_id:'JM2609|segment-a|calc-a'}),row({segment_id:'JM2701|segment-a|calc-b'}),row({sellDate:'2026-10-21T07:00:00Z'}),row({forceClose:true}),row({sellDate:'invalid'})]
 assert.equal(newowWaitingReference(invalid,owner),null)
 assert.equal(newowWaitingReference([],owner),null)
})
