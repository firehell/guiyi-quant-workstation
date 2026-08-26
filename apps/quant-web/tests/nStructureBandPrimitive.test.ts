import test from 'node:test'
import assert from 'node:assert/strict'
import type { NStructureBand } from '../src/types/market.ts'
import {
  bandVisualStyle,
  buildNStructureBandGeometry,
  hitNStructureBandGeometry,
  NStructureBandPrimitive,
  N_STRUCTURE_BAND_RENDER_CONTRACT,
} from '../src/components/kline/NStructureBandPrimitive.ts'
import * as nStructureBandPrimitiveModule from '../src/components/kline/NStructureBandPrimitive.ts'

test('primitive geometry maps formation and post-completion expansion separately', () => {
  const geometry = buildNStructureBandGeometry(
    [band(
      'up-1',
      'up',
      '2026-08-20T01:00:00Z',
      '2026-08-21T01:00:00Z',
      { expandedUntil: '2026-08-22T01:00:00Z' },
    )],
    '2026-08-19T01:00:00Z',
    (time) => Date.parse(time) / 864_000,
    (price) => 200 - price,
  )
  assert.equal(geometry.length, 1)
  assert.deepEqual(pickGeometry(geometry[0]!), {
    x1: Date.parse('2026-08-20T01:00:00Z') / 864_000,
    completionX: Date.parse('2026-08-21T01:00:00Z') / 864_000,
    x2: Date.parse('2026-08-22T01:00:00Z') / 864_000,
    top: 98,
    bottom: 102,
    clippedLeft: false,
    completionVisible: true,
    labelVisible: true,
  })
})

test('primitive keeps an expanded observation whose completion is left of loaded bars', () => {
  const loadedStart = '2026-08-20T01:00:00Z'
  const geometry = buildNStructureBandGeometry(
    [band(
      'pre-window',
      'up',
      '2026-08-18T01:00:00Z',
      '2026-08-19T01:00:00Z',
      { expandedUntil: '2026-08-22T01:00:00Z' },
    )],
    loadedStart,
    (time) => Date.parse(time) < Date.parse(loadedStart)
      ? null
      : (Date.parse(time) - Date.parse(loadedStart)) / 3_600_000,
    (price) => 200 - price,
  )

  assert.equal(geometry.length, 1)
  assert.deepEqual(pickGeometry(geometry[0]!), {
    x1: 0,
    completionX: 0,
    x2: 48,
    top: 98,
    bottom: 102,
    clippedLeft: true,
    completionVisible: false,
    labelVisible: false,
  })
})

test('primitive clips an earlier N1 to loaded bars and keeps narrow zones label-free', () => {
  const geometry = buildNStructureBandGeometry(
    [band('down-1', 'down', '2026-08-01T01:00:00Z', '2026-08-21T01:00:00Z')],
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T01:00:00Z')) / 3_600_000,
    (price) => 200 - price,
  )
  assert.equal(geometry[0]?.x1, 0)
  assert.equal(geometry[0]?.clippedLeft, true)
  assert.equal(geometry[0]?.labelVisible, false)
})

test('direction palette uses low-opacity red for up and green for down', () => {
  assert.deepEqual(bandVisualStyle('up'), {
    fillAlpha: 0.06,
    expansionFillAlpha: 0.025,
    strokeAlpha: 0.55,
    solid: '#dc2626',
  })
  assert.deepEqual(bandVisualStyle('down'), {
    fillAlpha: 0.06,
    expansionFillAlpha: 0.025,
    strokeAlpha: 0.55,
    solid: '#16a34a',
  })
  assert.equal(bandVisualStyle('up', { up: '#aabbcc', down: '#112233' }).solid, '#aabbcc')
})

test('primitive positions first re-entry and N2 invalidation on the expanded band', () => {
  const geometry = buildNStructureBandGeometry(
    [band(
      'up-events',
      'up',
      '2026-08-20T01:00:00Z',
      '2026-08-21T01:00:00Z',
      {
        firstReenteredAt: '2026-08-22T01:00:00Z',
        invalidatedAt: '2026-08-23T01:00:00Z',
        expandedUntil: '2026-08-23T01:00:00Z',
      },
    )],
    '2026-08-20T01:00:00Z',
    (time) => Date.parse(time) / 864_000,
    (price) => 200 - price,
  )

  assert.equal(geometry[0]?.reentryX, Date.parse('2026-08-22T01:00:00Z') / 864_000)
  assert.equal(geometry[0]?.reentryY, 98)
  assert.equal(geometry[0]?.invalidationX, Date.parse('2026-08-23T01:00:00Z') / 864_000)
  assert.equal(geometry[0]?.invalidationY, 102)
})

test('primitive stores only geometry intersecting the current viewport', () => {
  const geometry = buildNStructureBandGeometry(
    [
      band('fully-left', 'up', '2026-08-20T01:00:00Z', '2026-08-20T02:00:00Z'),
      band('intersecting', 'down', '2026-08-20T09:00:00Z', '2026-08-20T13:00:00Z'),
      band('fully-right', 'up', '2026-08-21T01:00:00Z', '2026-08-21T02:00:00Z'),
    ],
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T10:00:00Z')) / 3_600_000 * 10,
    (price) => 200 - price,
    { left: 0, right: 100 },
  )

  assert.deepEqual(geometry.map((item) => item.band.band_id), ['intersecting'])
})

test('primitive draws on the normal background layer so candles stay above a visible band', () => {
  assert.deepEqual(N_STRUCTURE_BAND_RENDER_CONTRACT, {
    zOrder: 'normal',
    drawLayer: 'background',
  })
})

test('overlap hit selects the visually topmost latest completion', () => {
  const geometry = buildNStructureBandGeometry(
    [
      band('older', 'up', '2026-08-20T01:00:00Z', '2026-08-21T01:00:00Z'),
      band('newer', 'down', '2026-08-20T01:00:00Z', '2026-08-22T01:00:00Z'),
    ],
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T01:00:00Z')) / 3_600_000,
    (price) => 200 - price,
  )
  assert.equal(hitNStructureBandGeometry(geometry, 12, 100)?.band.band_id, 'newer')
  assert.equal(hitNStructureBandGeometry(geometry, 500, 500), null)
  assert.deepEqual(buildNStructureBandGeometry([], '', () => null, () => null), [])
})

test('three highly overlapping same-direction bands emphasize the latest active N', () => {
  const geometry = overlappingGeometry([
    band('older-active', 'up', '2026-08-20T01:00:00Z', '2026-08-21T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('latest-active', 'up', '2026-08-20T01:00:00Z', '2026-08-22T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('latest-invalidated', 'up', '2026-08-20T01:00:00Z', '2026-08-23T01:00:00Z', {
      invalidatedAt: '2026-08-24T01:00:00Z',
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
  ])
  const byId = new Map(geometry.map((item) => [item.band.band_id, item]))

  assert.equal(byId.get('latest-active')?.isOverlapPrimary, true)
  assert.equal(byId.get('latest-active')?.overlapCount, 3)
  assert.equal(byId.get('latest-active')?.overlapPosition, 1)
  assert.equal(byId.get('latest-active')?.overlapLabel, 'N↑ ×3')
  assert.equal(byId.get('older-active')?.isOverlapSuppressed, true)
  assert.equal(byId.get('older-active')?.overlapPosition, 2)
  assert.equal(byId.get('latest-invalidated')?.isOverlapSuppressed, true)
  assert.equal(byId.get('latest-invalidated')?.overlapPosition, 3)
})

test('overlap grouping keeps dense up and down directions independent', () => {
  const geometry = overlappingGeometry([
    ...['up-1', 'up-2', 'up-3'].map((id, index) => band(
      id,
      'up',
      '2026-08-20T01:00:00Z',
      `2026-08-${21 + index}T01:00:00Z`,
      { expandedUntil: '2026-08-24T01:00:00Z' },
    )),
    ...['down-1', 'down-2', 'down-3'].map((id, index) => band(
      id,
      'down',
      '2026-08-20T01:00:00Z',
      `2026-08-${21 + index}T01:00:00Z`,
      { expandedUntil: '2026-08-24T01:00:00Z' },
    )),
  ])
  const up = geometry.filter((item) => item.band.direction === 'up')
  const down = geometry.filter((item) => item.band.direction === 'down')

  assert.equal(new Set(up.map((item) => item.overlapGroupId)).size, 1)
  assert.ok(up.every((item) => item.overlapCount === 3))
  assert.equal(new Set(down.map((item) => item.overlapGroupId)).size, 1)
  assert.ok(down.every((item) => item.overlapCount === 3))
  assert.notEqual(up[0]?.overlapGroupId, down[0]?.overlapGroupId)
})

test('three bands without sixty-percent screen overlap remain individually visible', () => {
  const prices = [[80, 84], [90, 94], [100, 104]] as const
  const items = prices.map(([lower, upper], index) => ({
    ...band(
      `separate-${index}`,
      'up',
      '2026-08-20T01:00:00Z',
      `2026-08-${21 + index}T01:00:00Z`,
      { expandedUntil: '2026-08-24T01:00:00Z' },
    ),
    completion_level: lower,
    lower,
    upper,
  }))
  const geometry = overlappingGeometry(items)

  assert.ok(geometry.every((item) => item.overlapGroupId === null))
  assert.ok(geometry.every((item) => item.isOverlapSuppressed === false))
})

test('dense groups use a deterministic sixty-percent priority anchor', () => {
  const source = [
    band('wide-latest', 'up', hour(0), hour(90), { expandedUntil: hour(100) }),
    band('left-older', 'up', hour(0), hour(50), { expandedUntil: hour(60) }),
    band('right-middle', 'up', hour(40), hour(80), { expandedUntil: hour(100) }),
  ]
  const build = (items: NStructureBand[]) => buildNStructureBandGeometry(
    items,
    hour(0),
    (time) => (Date.parse(time) - Date.parse(hour(0))) / 3_600_000,
    (price) => 200 - price,
  )

  assert.ok(build(source).every((item) => item.overlapCount === 3))
  assert.deepEqual(
    build([...source].reverse()).map((item) => [item.band.band_id, item.overlapGroupId]),
    build(source).map((item) => [item.band.band_id, item.overlapGroupId]),
  )
})

test('priority-anchor grouping includes three hops but excludes a fourth-hop chain', () => {
  const geometry = buildNStructureBandGeometry(
    [
      band('primary', 'up', hour(0), hour(90), { expandedUntil: hour(100) }),
      band('right-neighbor', 'up', hour(60), hour(80), { expandedUntil: hour(120) }),
      band('two-hop-distant', 'up', hour(84), hour(85), { expandedUntil: hour(144) }),
      band('left-neighbor', 'up', hour(0), hour(75), { expandedUntil: hour(60) }),
      band('three-hop-invalidated', 'up', hour(108), hour(109), {
        invalidatedAt: hour(170),
        expandedUntil: hour(170),
      }),
      band('four-hop-invalidated', 'up', hour(132), hour(133), {
        invalidatedAt: hour(194),
        expandedUntil: hour(194),
      }),
    ],
    hour(0),
    (time) => (Date.parse(time) - Date.parse(hour(0))) / 3_600_000,
    (price) => 200 - price,
    { left: 0, right: 200 },
  )
  const byId = new Map(geometry.map((item) => [item.band.band_id, item]))

  assert.equal(byId.get('primary')?.overlapCount, 5)
  assert.equal(byId.get('right-neighbor')?.overlapGroupId, byId.get('primary')?.overlapGroupId)
  assert.equal(byId.get('left-neighbor')?.overlapGroupId, byId.get('primary')?.overlapGroupId)
  assert.equal(byId.get('two-hop-distant')?.overlapGroupId, byId.get('primary')?.overlapGroupId)
  assert.equal(byId.get('three-hop-invalidated')?.overlapGroupId, byId.get('primary')?.overlapGroupId)
  assert.equal(byId.get('four-hop-invalidated')?.overlapGroupId, null)
})

test('screen overlap uses viewport-clipped rectangles instead of offscreen tails', () => {
  const geometry = buildNStructureBandGeometry(
    [
      band('wide-latest', 'up', hour(-100), hour(90), { expandedUntil: hour(100) }),
      band('left-older', 'up', hour(-100), hour(10), { expandedUntil: hour(20) }),
      band('right-middle', 'up', hour(0), hour(80), { expandedUntil: hour(100) }),
    ],
    hour(-100),
    (time) => (Date.parse(time) - Date.parse(hour(0))) / 3_600_000,
    (price) => 200 - price,
    { left: 0, right: 100 },
  )

  assert.ok(geometry.every((item) => item.overlapCount === 3))
  assert.ok(geometry.every((item) => item.visibleX1 >= 0 && item.visibleX2 <= 100))
})

test('dense group badge stays visible and hittable when every completion is before the viewport', () => {
  const geometry = buildNStructureBandGeometry(
    [
      band('pre-1', 'up', hour(-200), hour(-150), { expandedUntil: hour(100) }),
      band('pre-2', 'up', hour(-190), hour(-140), { expandedUntil: hour(100) }),
      band('pre-3', 'up', hour(-180), hour(-130), { expandedUntil: hour(100) }),
    ],
    hour(-100),
    (time) => (Date.parse(time) - Date.parse(hour(0))) / 3_600_000,
    (price) => 200 - price,
    { left: 0, right: 100 },
  )
  const primary = geometry.find((item) => item.isOverlapPrimary)!
  const hitLabel = (
    nStructureBandPrimitiveModule as unknown as {
      hitNStructureBandOverlapLabel?: (
        value: typeof geometry,
        x: number,
        y: number,
      ) => typeof primary | null
    }
  ).hitNStructureBandOverlapLabel

  assert.equal(primary.completionVisible, false)
  assert.equal(primary.labelVisible, true)
  assert.equal(primary.labelX, 6)
  assert.equal(hitLabel?.(geometry, 8, primary.top + 8)?.band.band_id, primary.band.band_id)
})

test('group selection advances through the priority order without changing facts', () => {
  const source = [
    band('oldest', 'up', '2026-08-20T01:00:00Z', '2026-08-21T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('middle', 'up', '2026-08-20T01:00:00Z', '2026-08-22T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('latest', 'up', '2026-08-20T01:00:00Z', '2026-08-23T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
  ]
  const geometry = overlappingGeometry(source)
  const groupId = geometry.find((item) => item.isOverlapPrimary)?.overlapGroupId ?? ''
  const nextSelection = (
    nStructureBandPrimitiveModule as unknown as {
      nextNStructureBandGroupSelection?: (
        value: typeof geometry,
        selectedGroupId: string,
      ) => string | null
    }
  ).nextNStructureBandGroupSelection?.(geometry, groupId)

  assert.equal(nextSelection, 'middle')
  assert.deepEqual(source.map((item) => item.band_id), ['oldest', 'middle', 'latest'])
})

test('suppressed overlap members render only faint rails while the primary keeps facts visible', () => {
  const geometry = overlappingGeometry([
    band('oldest', 'up', '2026-08-20T01:00:00Z', '2026-08-21T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('middle', 'up', '2026-08-20T01:00:00Z', '2026-08-22T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('latest', 'up', '2026-08-20T01:00:00Z', '2026-08-23T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
  ])
  const primary = geometry.find((item) => item.isOverlapPrimary)!
  const suppressed = geometry.find((item) => item.isOverlapSuppressed)!
  const renderStyle = (
    nStructureBandPrimitiveModule as unknown as {
      nStructureBandRenderStyle?: (item: typeof primary) => unknown
    }
  ).nStructureBandRenderStyle

  assert.deepEqual(renderStyle?.(primary), {
    drawFullBand: true,
    drawEvents: true,
    railAlpha: 0,
    opacityMultiplier: 1,
    label: 'N↑ ×3',
  })
  assert.deepEqual(renderStyle?.(suppressed), {
    drawFullBand: false,
    drawEvents: false,
    railAlpha: 0.15,
    opacityMultiplier: 1,
    label: '',
  })
})

test('an all-invalidated overlap group lowers the primary emphasis', () => {
  const geometry = overlappingGeometry(['oldest', 'middle', 'latest'].map((id, index) => band(
    id,
    'down',
    '2026-08-20T01:00:00Z',
    `2026-08-${21 + index}T01:00:00Z`,
    {
      invalidatedAt: '2026-08-24T01:00:00Z',
      expandedUntil: '2026-08-24T01:00:00Z',
    },
  )))
  const primary = geometry.find((item) => item.isOverlapPrimary)!
  const suppressed = geometry.find((item) => item.isOverlapSuppressed)!
  const renderStyle = (
    nStructureBandPrimitiveModule as unknown as {
      nStructureBandRenderStyle?: (item: typeof primary) => { opacityMultiplier: number }
    }
  ).nStructureBandRenderStyle

  assert.equal(primary.overlapGroupAllInvalidated, true)
  assert.equal(renderStyle?.(primary).opacityMultiplier, 0.65)
  assert.equal((renderStyle?.(suppressed) as unknown as { railAlpha: number }).railAlpha, 0.0975)
})

test('overlap badge hit and selected map expose the next member as two-of-three', () => {
  const source = ['oldest', 'middle', 'latest'].map((id, index) => band(
    id,
    'up',
    '2026-08-20T01:00:00Z',
    `2026-08-${21 + index}T01:00:00Z`,
    { expandedUntil: '2026-08-24T01:00:00Z' },
  ))
  const initial = overlappingGeometry(source)
  const primary = initial.find((item) => item.isOverlapPrimary)!
  const groupId = primary.overlapGroupId!
  const hitLabel = (
    nStructureBandPrimitiveModule as unknown as {
      hitNStructureBandOverlapLabel?: (
        geometry: typeof initial,
        x: number,
        y: number,
      ) => typeof primary | null
    }
  ).hitNStructureBandOverlapLabel

  assert.equal(hitLabel?.(initial, primary.x1 + 8, primary.top + 8)?.overlapGroupId, groupId)
  assert.equal(hitLabel?.(initial, primary.x2 + 20, primary.bottom + 20), null)

  const selected = buildNStructureBandGeometry(
    source,
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T01:00:00Z')) / 3_600_000,
    (price) => 200 - price,
    undefined,
    new Map([[groupId, 'middle']]),
  )
  const cycledPrimary = selected.find((item) => item.isOverlapPrimary)!
  assert.equal(cycledPrimary.band.band_id, 'middle')
  assert.equal(cycledPrimary.overlapPosition, 2)
  assert.equal(cycledPrimary.overlapLabel, 'N↑ 2/3')
})

test('cycling keeps a dense badge at one stable group coordinate even for a narrow member', () => {
  const source = [
    band('wide-latest', 'up', hour(0), hour(90), { expandedUntil: hour(100) }),
    band('narrow-middle', 'up', hour(70), hour(80), { expandedUntil: hour(90) }),
    band('narrow-oldest', 'up', hour(70), hour(75), { expandedUntil: hour(90) }),
  ]
  const build = (selection?: ReadonlyMap<string, string>) => buildNStructureBandGeometry(
    source,
    hour(0),
    (time) => (Date.parse(time) - Date.parse(hour(0))) / 3_600_000,
    (price) => 200 - price,
    { left: 0, right: 100 },
    selection,
  )
  const initial = build()
  const initialPrimary = initial.find((item) => item.isOverlapPrimary)!
  const selected = build(new Map([[initialPrimary.overlapGroupId!, 'narrow-middle']]))
  const selectedPrimary = selected.find((item) => item.isOverlapPrimary)!

  assert.equal(selectedPrimary.band.band_id, 'narrow-middle')
  assert.equal(selectedPrimary.visibleX2 - selectedPrimary.visibleX1, 20)
  assert.equal(selectedPrimary.labelVisible, true)
  assert.deepEqual(
    [selectedPrimary.labelX, selectedPrimary.labelY],
    [initialPrimary.labelX, initialPrimary.labelY],
  )
})

test('primitive cycles a group external id and reset restores the latest active member', () => {
  const primitive = new NStructureBandPrimitive()
  let requestedUpdates = 0
  let coordinateScale = 1
  primitive.attached({
    chart: {
      timeScale: () => ({
        timeToCoordinate: (time: number) => (
          time * 1000 - Date.parse('2026-08-20T01:00:00Z')
        ) / 3_600_000 * coordinateScale,
        width: () => 500,
      }),
    },
    series: { priceToCoordinate: (price: number) => 200 - price },
    requestUpdate: () => { requestedUpdates += 1 },
  } as never)
  primitive.setData([
    band('oldest', 'up', '2026-08-20T01:00:00Z', '2026-08-21T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('middle', 'up', '2026-08-20T01:00:00Z', '2026-08-22T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
    band('latest', 'up', '2026-08-20T01:00:00Z', '2026-08-23T01:00:00Z', {
      expandedUntil: '2026-08-24T01:00:00Z',
    }),
  ], '2026-08-20T01:00:00Z')
  const groupId = primitive.currentGeometry().find((item) => item.isOverlapPrimary)!.overlapGroupId!
  const externalId = `n-structure-band-group:${groupId}`
  const cycle = (
    primitive as unknown as {
      cycleOverlapGroupByExternalId?: (value: string) => boolean
      resetOverlapSelection?: () => boolean
      overlapInfoByExternalId?: (value: string) => { groupId: string; count: number; position: number } | null
    }
  )

  assert.equal(primitive.bandByExternalId(externalId)?.band_id, 'latest')
  assert.equal(cycle.cycleOverlapGroupByExternalId?.(externalId), true)
  assert.equal(primitive.bandByExternalId(externalId)?.band_id, 'middle')
  assert.deepEqual(cycle.overlapInfoByExternalId?.(externalId), { groupId, count: 3, position: 2 })
  coordinateScale = 2
  primitive.updateAllViews()
  assert.equal(primitive.bandByExternalId(externalId)?.band_id, 'latest')
  assert.equal(cycle.cycleOverlapGroupByExternalId?.(externalId), true)
  assert.equal(cycle.resetOverlapSelection?.(), true)
  assert.equal(primitive.bandByExternalId(externalId)?.band_id, 'latest')
  assert.ok(requestedUpdates >= 3)
})

test('a cycled group primary keeps hover ownership over suppressed newer members', () => {
  const source = ['oldest', 'middle', 'latest'].map((id, index) => band(
    id,
    'up',
    '2026-08-20T01:00:00Z',
    `2026-08-${21 + index}T01:00:00Z`,
    { expandedUntil: '2026-08-24T01:00:00Z' },
  ))
  const initial = overlappingGeometry(source)
  const groupId = initial.find((item) => item.isOverlapPrimary)!.overlapGroupId!
  const selected = buildNStructureBandGeometry(
    source,
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T01:00:00Z')) / 3_600_000,
    (price) => 200 - price,
    undefined,
    new Map([[groupId, 'middle']]),
  )

  assert.equal(hitNStructureBandGeometry(selected, 48, 100)?.band.band_id, 'middle')
})

function band(
  id: string,
  direction: 'up' | 'down',
  n1At: string,
  completedAt: string,
  lifecycle: {
    firstReenteredAt?: string | null
    invalidatedAt?: string | null
    expandedUntil?: string
  } = {},
): NStructureBand {
  return {
    band_id: id,
    contract: 'AU2610',
    segment_start_trading_day: '2026-08-01',
    completion_trading_day: completedAt.slice(0, 10),
    direction,
    role: direction === 'up' ? 'support_reference' : 'resistance_reference',
    n1_at: n1At,
    completed_at: completedAt,
    completion_level: 100,
    lower: 98,
    upper: 102,
    first_reentered_at: lifecycle.firstReenteredAt ?? null,
    invalidated_at: lifecycle.invalidatedAt ?? null,
    expanded_until: lifecycle.expandedUntil ?? completedAt,
  }
}

function pickGeometry(value: ReturnType<typeof buildNStructureBandGeometry>[number]) {
  return {
    x1: value.x1,
    completionX: value.completionX,
    x2: value.x2,
    top: value.top,
    bottom: value.bottom,
    clippedLeft: value.clippedLeft,
    completionVisible: value.completionVisible,
    labelVisible: value.labelVisible,
  }
}

function overlappingGeometry(items: NStructureBand[]) {
  return buildNStructureBandGeometry(
    items,
    '2026-08-20T01:00:00Z',
    (time) => (Date.parse(time) - Date.parse('2026-08-20T01:00:00Z')) / 3_600_000,
    (price) => 200 - price,
  )
}

function hour(offset: number): string {
  return new Date(Date.parse('2026-08-20T00:00:00Z') + offset * 3_600_000).toISOString()
}
