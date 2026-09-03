import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MARKET_DETAIL_ICON_NAMES,
  marketDetailIconDefinition,
} from '../src/utils/marketDetailIcons.ts'

test('detail icon registry is finite and labeled', () => {
  assert.equal(new Set(MARKET_DETAIL_ICON_NAMES).size, MARKET_DETAIL_ICON_NAMES.length)

  for (const name of MARKET_DETAIL_ICON_NAMES) {
    const icon = marketDetailIconDefinition(name)

    assert.equal(icon.name, name)
    assert.ok(icon.label.length > 0)
    assert.ok(icon.paths.length + icon.circles.length > 0)
  }
})

test('detail icons preserve the frozen clean-room drawing contract', () => {
  const more = marketDetailIconDefinition('more')
  const history = marketDetailIconDefinition('history')

  assert.equal(more.mode, 'fill')
  assert.deepEqual(more.circles, [
    { cx: 6, cy: 12, r: 1.5 },
    { cx: 12, cy: 12, r: 1.5 },
    { cx: 18, cy: 12, r: 1.5 },
  ])
  assert.equal(history.mode, 'stroke')
  assert.deepEqual(history.paths, ['M4 5v5h5', 'M4.7 9.5A8 8 0 1 0 7 5.3', 'M12 8v4l3 2'])
})
