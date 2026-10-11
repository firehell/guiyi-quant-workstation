import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { detectNewowPublicPatterns, NEWOW_PUBLIC_PATTERNS_METADATA } from '../src/utils/newowPublicPatterns.ts'
import { publicPatternOracle } from './helpers/newowPatternOracle.mjs'
const fixture=JSON.parse(readFileSync(new URL('./fixtures/newowPublicPatterns.v3379.json',import.meta.url),'utf8'))
for (const c of fixture.goldens) for (const frequency of ['day','week']) test(`public golden ${c.name} ${frequency}`,()=> {
 assert.deepEqual(detectNewowPublicPatterns(c.bars,frequency),c[frequency])
})
test('display-only metadata is explicit',()=>assert.deepEqual(NEWOW_PUBLIC_PATTERNS_METADATA,{version:'newow_public_patterns_v3379_v1',pageParity:true,executable:false,repainting:true}))
test('all seven have nonempty source goldens',()=> {
 const types = new Set(fixture.goldens.flatMap(c=>c.week.map(p=>p.type)))
 assert.deepEqual([...types].sort(),['ascending-base','consolidation','cup-handle','double-bottom','flat-base','saucer','tight-area'].sort())
})
test('cup week/day scores follow source period conversion',()=> {
 const c=fixture.goldens.find(c=>c.name==='cup and saucer')
 assert.notDeepEqual(c.week,c.day)
})
test('source ties retain seven-type order and earliest equal-score window',()=> {
 const c=fixture.goldens.find(c=>c.name==='constant declining volume')
 const patterns=detectNewowPublicPatterns(c.bars,'day')
 assert.deepEqual(patterns.map(p=>p.type),['flat-base','consolidation','tight-area'])
 assert.equal(patterns[0].params.endIdx,59)
 assert.equal(patterns[0].params.startIdx,40)
 assert.equal(patterns[1].params.startIdx,0)
 assert.equal(patterns[1].params.length,40)
 assert.equal(patterns[2].params.startIdx,0)
 assert.equal(patterns[2].params.length,25)
})
test('consolidation volume bonus requires strictly decreasing half totals',()=> {
 const score=(step:number)=>fixture.goldens.find(c=>c.name===`volume step ${step}`).week.find(p=>p.type==='consolidation').score
 assert.equal(score(1),80);assert.equal(score(0),60);assert.equal(score(-1),60)
})
test('invalid nonfinite/negative price and volume fail closed',()=> {
 const c=fixture.goldens.find(c=>c.name==='constant declining volume')
 for(const patch of [{low:0},{volume:-1},{high:NaN},{close:Infinity}])assert.throws(()=>detectNewowPublicPatterns(c.bars.map((b,i)=>i===0?{...b,...patch}:b)),/Invalid/)
})
test('optional live frozen-source verification', {skip:!process.env.NEWOW_PUBLIC_SOURCE},()=> {
 for(const c of fixture.goldens)for(const frequency of ['week','day'])assert.deepEqual(c[frequency],publicPatternOracle(process.env.NEWOW_PUBLIC_SOURCE,c.bars,frequency))
})
