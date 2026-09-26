import assert from 'node:assert/strict'
import test from 'node:test'
import { newowAuxiliaryPaneLayout } from '../src/components/market/detail/newow/newowAuxiliaryPaneLayout.ts'

test('toolbars leave 200 pixels for indicators across desktop and narrow layouts', () => {
  for (const height of [700, 994, 1040]) for (const toolbar of [32, 116, 156]) {
    const layout = newowAuxiliaryPaneLayout(height, toolbar)
    assert.ok(layout.auxiliaryHeight - layout.topInset - 15 >= 200)
    assert.ok(layout.mainHeight > 190)
    assert.equal(layout.mainHeight + layout.volumeHeight + layout.auxiliaryHeight, height - 30)
  }
})
