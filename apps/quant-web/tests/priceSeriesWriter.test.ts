import assert from 'node:assert/strict'
import test from 'node:test'
import { createPriceSeriesWriter } from '../src/utils/priceSeriesWriter.ts'

test('identical overlay refreshes do not reset the price series; latest bar updates locally', () => {
  const calls: string[] = []
  const writer = createPriceSeriesWriter<{ time: number; close: number }>()
  const series = { setData: () => calls.push('set'), update: () => calls.push('update') }
  writer.write(series, [{time:1,close:10},{time:2,close:11}])
  writer.write(series, [{time:1,close:10},{time:2,close:11}])
  writer.write(series, [{time:1,close:10},{time:2,close:12}])
  writer.write(series, [{time:1,close:10},{time:2,close:12},{time:3,close:13}])
  assert.deepEqual(calls, ['set','update','update'])
})
test('historical revision, prepend, clear and replaced chart always replace data', () => {
  const calls: string[] = []
  const writer = createPriceSeriesWriter<{time:string; value:number; color?:string}>()
  const series = { setData: () => calls.push('set'), update: () => calls.push('update') }
  writer.write(series, [{time:'2',value:1},{time:'3',value:2}])
  writer.write(series, [{time:'2',value:9},{time:'3',value:2}])
  writer.write(series, [{time:'1',value:0},{time:'2',value:9},{time:'3',value:2}])
  writer.write(series, [])
  writer.write(series, [{time:'1',value:0}])
  writer.write({...series}, [{time:'1',value:0}])
  assert.deepEqual(calls, ['set','set','set','set','set','set'])
})

test('identity change replaces equal points and volume decorations are compared', () => {
  const calls: string[] = []
  const writer = createPriceSeriesWriter<{ time: {year:number;month:number;day:number}; value:number; color:string }>()
  const series = { setData: () => calls.push('set'), update: () => calls.push('update') }
  const point = {time:{year:2026,month:10,day:1},value:1,color:'red'}
  writer.write(series, [point], 'jm:1d')
  writer.write(series, [{...point,time:{...point.time}}], 'jm:1d')
  writer.write(series, [{...point,color:'green'}], 'jm:1d')
  writer.write(series, [{...point,color:'green'}], 'rb:1d')
  assert.deepEqual(calls, ['set','update','set'])
})
