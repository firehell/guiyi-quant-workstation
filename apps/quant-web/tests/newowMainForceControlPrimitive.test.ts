import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowMainForceCommands, buildNewowMainForceData, NEWOW_MAIN_FORCE_STYLE } from '../src/components/market/detail/newow/newowMainForceControlPrimitive.ts'

test('control points use server statuses at aligned segment indices', () => {
  const points = [0, 1, 2].map(index => ({ index, segmentId: 'a', physicalContract: 'MA2610', barEnd: `2026-09-${index + 1}`, time: index as never, value: [0, 2, 1][index]! }))
  const segments = [{ segment_id: 'a', physical_contract: 'MA2610', bar_ends: points.map(point => point.barEnd),
    data: { kongpan: [0, 2, 1], status: ['无庄控盘', '开始控盘', '高控+出货'], current_status: '高控+出货', formula_version: 'v1' } }]
  const data = buildNewowMainForceData([{ id: 'a', key: 'kongpan', label: '主力控盘', points }], segments as never)
  assert.deepEqual(data.map(item => [item.status, item.previous]), [['无庄控盘', null], ['开始控盘', 0], ['高控+出货', 2]])
  const commands = buildNewowMainForceCommands(data, 100, 200, time => Number(time) * 20 + 10)
  assert.deepEqual(commands.map(item => item.kind), ['reference', 'bar', 'start', 'bar'])
  assert.equal(commands[2]!.color, NEWOW_MAIN_FORCE_STYLE.start)
  assert.ok(commands[3]!.splitY! > commands[3]!.fromY)
  assert.ok(commands[3]!.splitY! < commands[3]!.toY)
  assert.equal(commands[0]!.fromY, commands[0]!.toY)
})

test('normalization uses the entire loaded formula window and leaves negative bars below the reference', () => {
  const data = [
    { index: 0, segmentId: 'a', time: 0 as never, value: -0.2, previous: null, status: '无庄控盘' as const },
    { index: 1, segmentId: 'a', time: 1 as never, value: 0.5, previous: -0.2, status: '有庄控盘' as const },
  ]
  const commands = buildNewowMainForceCommands(data, 100, 200, time => Number(time) * 30 + 10, 90)
  assert.ok(commands[1]!.toY > commands[0]!.fromY)
  assert.equal(commands[2]!.color, NEWOW_MAIN_FORCE_STYLE.controlled)
  assert.ok(commands[2]!.fromY < commands[0]!.fromY)
})
