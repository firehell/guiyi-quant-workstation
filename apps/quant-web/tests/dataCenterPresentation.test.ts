import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildDataCenterOverview } from '../src/utils/dataCenterPresentation.ts'

describe('data center presentation', () => {
  it('summarizes bounded coverage and prioritizes failed quality', () => {
    const result = buildDataCenterOverview([
      {
        provider: 'rqdata',
        data_role: 'primary',
        quality_status: 'passed',
        binding_status: 'active',
        latest_bar_time: '2026-07-25T15:00:00',
        data_version: 'rqdata_jm_20260725_v2',
      },
      {
        provider: 'local_parquet',
        data_role: 'primary',
        quality_status: 'failed',
        binding_status: 'unbound',
        end_time: '2026-07-24T15:00:00',
        data_version: 'local_jm_20260724_v1',
      },
    ])

    assert.equal(result.latestDate, '2026-07-25 15:00')
    assert.equal(result.eligibleAssets, 1)
    assert.equal(result.qualitySummary, '1 passed · 1 failed')
    assert.equal(result.priority, '先处理 1 个 failed 资产')
    assert.equal(result.versionSummary, '2 个资产版本 · 最新 2026-07-25')
  })

  it('does not count validation sources as active research eligibility', () => {
    const result = buildDataCenterOverview([
      {
        provider: 'validation',
        data_role: 'primary',
        quality_status: 'passed',
        binding_status: 'active',
      },
    ])
    assert.equal(result.eligibleAssets, 0)
    assert.equal(result.latestDate, '未提供')
  })
})
