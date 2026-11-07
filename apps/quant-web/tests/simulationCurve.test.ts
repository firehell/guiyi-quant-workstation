import test from 'node:test'
import assert from 'node:assert/strict'
import { selectCurvePoints, focusCurvePoints, curveGeometry } from '../src/utils/simulationPresentation.ts'
import type { MonitorOverview } from '../src/api/simulationMonitor.ts'
const point = (at: string, equity = '100', day = '20261107', net: string | null = null): MonitorOverview['curve'][number] => ({ at, equity, net_profit: net, trading_day: day })

test('7/30/all select Shanghai calendar days and exclude future points without changing source', () => {
  const now = Date.parse('2026-11-07T03:00:00Z')
  const dates = ['2026-09-01T01:00:00Z', '2026-10-08T15:59:59Z', '2026-10-08T16:00:00Z', '2026-10-31T15:59:59Z', '2026-10-31T16:00:00Z', '2026-11-07T03:00:00Z', '2026-11-07T03:00:01Z']
  const points = dates.map(at => point(at))
  assert.deepEqual(selectCurvePoints(points, '7d', now).map(p => p.at), dates.slice(4, 6))
  assert.deepEqual(selectCurvePoints(points, '30d', now).map(p => p.at), dates.slice(2, 6))
  assert.equal(selectCurvePoints(points, 'all', now).length, 6)
  assert.equal(points.length, 7)
})

test('focus removes only unchanged suffix, preserves plateau before changes and exact decimal differences', () => {
  const points = ['100', '100.00', '110', '105', '105.0', '105'].map((v, i) => point(`2026-11-07T01:0${i}:00Z`, v))
  const focus = focusCurvePoints(points, 'equity')
  assert.equal(focus.length, 4)
  assert.equal(curveGeometry(focus, 'equity').dots.at(-1)!.x, 970)
  assert.equal(points.length, 6)
  const exact = [point('2026-11-07T01:00:00Z', '1000000.00000000001'), point('2026-11-07T01:01:00Z', '1000000.00000000002')]
  assert.equal(focusCurvePoints(exact, 'equity').length, 2)
})

test('empty, one point and all flat remain explicit; net gaps and day resets are never hidden', () => {
  assert.deepEqual(focusCurvePoints([], 'equity'), [])
  const flat = [0, 1, 2].map(i => point(`2026-11-07T01:0${i}:00Z`))
  assert.equal(focusCurvePoints(flat, 'equity').length, 1)
  assert.equal(curveGeometry(focusCurvePoints(flat, 'equity'), 'equity').dots.length, 1)
  const net = [point('2026-11-06T01:00:00Z', '100', '20261106', '1'), point('2026-11-07T01:00:00Z', '100', '20261107', '1'), point('2026-11-07T01:01:00Z', '100', '20261107', null)]
  assert.equal(focusCurvePoints(net, 'net_profit').length, 3)
  assert.equal(focusCurvePoints(net.slice(0, 2), 'net_profit').length, 2)
  assert.equal(curveGeometry(net, 'net_profit').segments.length, 2)
})
