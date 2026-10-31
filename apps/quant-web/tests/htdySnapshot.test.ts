import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeHtdySnapshot } from '../src/utils/htdySnapshot.ts'
const fixture=()=>({schema_version:'htdy_historical_reference_v1',product:'jm',frequency:'60m',recording_mode:'historical_replay',snapshot_id:'a'.repeat(64),source_token:'b'.repeat(64),generated_at:'2026-10-30T10:00:00Z',computed_through:'2026-10-30T07:00:00Z',formula_versions:['v1'],reference_model_version:'htdy_historical_window32_reverse_close_v1',executable:false,auto_order:false,actions:[],trades:[],signals:[],curve:[],summary:{closed:0,total:0,open:0},since:'2026-01-01',through:'2026-10-30',next_cursor:null})
test('snapshot reader binds product and immutable selection',()=>{
 const f=fixture();assert.equal(normalizeHtdySnapshot(f,'JM',f.snapshot_id).snapshot_id,f.snapshot_id)
 assert.throws(()=>normalizeHtdySnapshot(f,'rb'));assert.throws(()=>normalizeHtdySnapshot(f,'jm','c'.repeat(64)))
})
test('rejects wrong mode, model, execution flags and impossible actions',()=>{
 for(const patch of [{recording_mode:'forward_observation'},{reference_model_version:'unknown'},{executable:true},{auto_order:true},{actions:[{action_id:'x'}]}])assert.throws(()=>normalizeHtdySnapshot({...fixture(),...patch},'jm'))
})
