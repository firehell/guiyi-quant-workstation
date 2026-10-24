import assert from 'node:assert/strict'
import test from 'node:test'
import { rangeDetectorStatusText, visibleRangeDetectorCount } from '../src/utils/rangeDetectorStatus.ts'
test('visible range state distinguishes computed empty, warmup, failure and matching historical boxes',()=>{
 assert.match(rangeDetectorStatusText('loading',0),/补充/)
 assert.match(rangeDetectorStatusText('failed',3),/读取失败/)
 assert.match(rangeDetectorStatusText('insufficient',3),/预热不足/)
 assert.match(rangeDetectorStatusText('ready',0),/可见区间未识别/)
 assert.match(rangeDetectorStatusText('ready',2),/2 段/)
 const box={visualStartAt:'2026-08-01T00:00:00Z',detectionRightAt:'2026-08-02T00:00:00Z',levelsActiveUntil:'2026-08-03T00:00:00Z'}
 assert.equal(visibleRangeDetectorCount([box],'2026-08-04T00:00:00Z','2026-08-05T00:00:00Z','2026-08-10T00:00:00Z'),0)
 assert.equal(visibleRangeDetectorCount([box],'2026-08-02T00:00:00Z','2026-08-03T00:00:00Z','2026-08-10T00:00:00Z'),1)
 assert.equal(visibleRangeDetectorCount([{...box,levelsActiveUntil:null}],'2026-08-04T00:00:00Z','2026-08-05T00:00:00Z','2026-08-10T00:00:00Z'),1)
})
