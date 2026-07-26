import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildMarketQualificationPresentation,
  summarizeDataVersion,
} from '../src/utils/marketEvidencePresentation.ts'

describe('summarizeDataVersion', () => {
  it('extracts a recognized date and version token without exposing the raw value', () => {
    const raw = 'rqdata_daily_20260711_v2'
    const summary = summarizeDataVersion(raw, [raw], 1)
    assert.equal(summary, '2026-07-11 · v2')
    assert.equal(summary.includes(raw), false)
  })

  it('uses the latest valid date from underscore and Chinese path-like values', () => {
    assert.equal(
      summarizeDataVersion(
        '焦煤/归档_20260709_复核_20260712_v4',
        ['焦煤/归档_20260709_v3', '焦煤/归档_20260712_v4'],
        1,
      ),
      '2026-07-12 · v4',
    )
  })

  it('summarizes multi-asset evidence by count and latest date', () => {
    assert.equal(
      summarizeDataVersion(
        'bundle_20260710',
        ['asset_20260708_v1', 'asset_20260711_v2', 'asset_20260709_v1'],
        6,
      ),
      '6 个资产版本 · 最新 2026-07-11',
    )
  })

  it('does not invent meaning for unknown or empty versions', () => {
    assert.equal(summarizeDataVersion('legacy-final', ['legacy-final'], 1), '版本已绑定')
    assert.equal(summarizeDataVersion('', [], 0), '版本已绑定')
  })
})

describe('buildMarketQualificationPresentation', () => {
  it('only presents strict research when the backend lineage explicitly qualifies it', () => {
    assert.deepEqual(
      buildMarketQualificationPresentation({
        accessMode: 'research',
        strictResearchReady: true,
        qualityStatus: 'passed',
        profileId: 'intraday_research_v1',
      }),
      {
        label: '可严格研究',
        tone: 'success',
        summary: 'Profile 与 lineage 已通过严格研究资格校验。',
      },
    )
  })

  it('keeps browser and warning data observation-only', () => {
    assert.deepEqual(
      buildMarketQualificationPresentation({
        accessMode: 'browser',
        strictResearchReady: false,
        qualityStatus: 'warning',
        profileId: null,
      }),
      {
        label: '仅观察',
        tone: 'warning',
        summary: '当前为浏览模式且数据质量存在警告，不可作为严格研究输入。',
      },
    )
  })

  it('reports failed quality as unavailable rather than a normal warning', () => {
    assert.deepEqual(
      buildMarketQualificationPresentation({
        accessMode: 'research',
        strictResearchReady: false,
        qualityStatus: 'failed',
        profileId: 'daily_profile_v1',
      }),
      {
        label: '数据不可用',
        tone: 'error',
        summary: '数据质量未通过，不能用于当前研究。',
      },
    )
  })

  it('keeps a missing research Profile fail-closed', () => {
    assert.deepEqual(
      buildMarketQualificationPresentation({
        accessMode: 'research',
        strictResearchReady: false,
        qualityStatus: 'unknown',
        profileId: null,
      }),
      {
        label: '缺少 Profile',
        tone: 'warning',
        summary: '严格研究必须先选择明确的 Profile。',
      },
    )
  })
})
