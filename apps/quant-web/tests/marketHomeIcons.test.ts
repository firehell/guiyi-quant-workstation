import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MARKET_HOME_ICON_GLYPHS,
  MARKET_HOME_ICON_SIZES,
  MARKET_HOME_STATE_META,
} from '../src/utils/marketHomeIcons.ts'

test('freezes the approved Market Home icon palette and sizes', () => {
  assert.deepEqual(MARKET_HOME_ICON_SIZES, { legend: 40, table: 28, micro: 24 })
  assert.deepEqual(MARKET_HOME_STATE_META, {
    up: { color: '#E63935', label: '上行' },
    aligned: { color: '#FF9601', label: '周期同向' },
    down: { color: '#35C759', label: '下行' },
    neutral: { color: '#017AFF', label: '中性' },
    unavailable: { color: '#98A2B3', label: '数据不足' },
  })
})

test('uses the approved glyph geometry without trading semantics', () => {
  assert.equal(MARKET_HOME_ICON_GLYPHS.up, 'M12 6.5 19 17.5H5Z')
  assert.equal(MARKET_HOME_ICON_GLYPHS.aligned, 'M6.5 12.3 10.2 16 17.8 8.3')
  assert.equal(MARKET_HOME_ICON_GLYPHS.down, 'M5 6.5h14L12 17.5Z')
  assert.equal(MARKET_HOME_ICON_GLYPHS.neutral, 'm7.2 7.2 9.6 9.6m0-9.6-9.6 9.6')
  assert.equal(MARKET_HOME_ICON_GLYPHS.unavailable, 'circle:12:12:2.2')
  assert.equal(MARKET_HOME_ICON_GLYPHS.microUp, 'M6 15.5 10 11.5 13 13.5 18 8.5')
})
