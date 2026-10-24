import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeHomeProjection } from '../src/utils/newowHomeProjection.ts'
const packet = () => ({schema_version:'newow_home_projection_v1',page_parity:true,executable:false,requested_at:'2026-10-23T08:00:00Z',generated_at:null,items:[{product:'rb',projection_status:'missing',computed_at:null,source_versions:{'1d':null,'1w':null},period_status:{'1d':'missing','1w':'missing'},strategies:Object.fromEntries(['trend','oscillation'].map(s=>[s,Object.fromEntries(['1d','1w'].map(p=>[p,{status:'unavailable',state:null}]))]))}]})
test('missing projection is an explicit display state and never invents facts',()=>{
 const value=normalizeHomeProjection(packet());assert.equal(value.items[0]!.projection_status,'missing');assert.equal(value.items[0]!.computed_at,null)
})
test('projection validation rejects duplicate products, unknown states and executable bodies',()=>{
 const duplicate=packet();duplicate.items.push(duplicate.items[0]!);assert.throws(()=>normalizeHomeProjection(duplicate))
 const unknown=packet();unknown.items[0]!.projection_status='unknown';assert.throws(()=>normalizeHomeProjection(unknown))
 const executable=packet();executable.executable=true;assert.throws(()=>normalizeHomeProjection(executable))
})
