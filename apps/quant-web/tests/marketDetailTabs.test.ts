import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

const detailSource = readFileSync(new URL('../src/components/market/MarketDetailTable.vue', import.meta.url), 'utf-8')
const pageSource = readFileSync(new URL('../src/pages/market/index.vue', import.meta.url), 'utf-8')

describe('market detail sector tabs', () => {
  it('builds tabs from the backend sector_summary order with Chinese labels', () => {
    assert.match(detailSource, /const tabs = computed\(\(\) => props\.sectors\.map/)
    assert.match(detailSource, /sectorLabels\.get\(sector\.sector\) \|\| sector\.sector/)
  })

  it('selects the first sector tab by default and never invents a synthetic all tab', () => {
    assert.match(detailSource, /activeSector\.value = next\[0\]\?\.id \?\? ''/)
    assert.doesNotMatch(detailSource, /value="all"|全部板块/)
  })

  it('filters rows by the active sector inside the browser without new requests', () => {
    assert.match(detailSource, /item\.sector === activeSector\.value/)
    assert.doesNotMatch(detailSource, /getMarketRadar|fetch\(/)
  })

  it('merges the old sector overview card into the tab bar', () => {
    assert.doesNotMatch(pageSource, /MarketSectorSummary/)
    assert.match(pageSource, /:sectors="radar\.sector_summary"/)
  })

  it('keeps the watchlist mode toggle alongside sector tabs', () => {
    assert.match(detailSource, /mode === 'watchlist'/)
    assert.match(detailSource, /props\.watchlist\.includes\(item\.symbol\)/)
  })
})
