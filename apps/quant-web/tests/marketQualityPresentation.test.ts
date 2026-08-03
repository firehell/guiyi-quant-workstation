import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildMarketQualityImpact } from '../src/utils/marketQualityPresentation.ts'

describe('buildMarketQualityImpact', () => {
  it('keeps browser warning data viewable but blocks strict research use', () => {
    assert.deepEqual(
      buildMarketQualityImpact({
        qualityStatus: 'warning',
        warningReasons: ['存在跨文件差异'],
        crossFileConflicts: 20,
        accessMode: 'browser',
        profileId: null,
        strictResearchReady: false,
        contractView: 'continuous',
        lineageReady: true,
        dataMode: 'historical',
      }),
      {
        severity: 'warning',
        title: '数据仅可观察',
        reasons: ['发现 20 个跨文件 OHLCV 冲突。', '存在跨文件差异'],
        allowed: ['浏览当前 K 线（仅供观察）', '查看质量与 lineage 证据'],
        blocked: ['严格研究', '当前 warning 数据作为正式回测或信号输入'],
        actions: ['evidence', 'profile', 'actual'],
      },
    )
  })

  it('never downgrades failed quality to a warning', () => {
    const impact = buildMarketQualityImpact({
      qualityStatus: 'failed',
      warningReasons: ['下载不完整'],
      crossFileConflicts: 0,
      accessMode: 'research',
      profileId: 'daily_v1',
      strictResearchReady: false,
      contractView: 'actual',
      lineageReady: true,
      dataMode: 'historical',
    })
    assert.equal(impact?.severity, 'error')
    assert.equal(impact?.title, '数据质量未通过')
    assert.ok(impact?.blocked.includes('当前数据用于研究、回测或信号输入'))
  })

  it('keeps missing research Profile fail-closed with only valid actions', () => {
    assert.deepEqual(
      buildMarketQualityImpact({
        qualityStatus: 'unknown',
        warningReasons: [],
        crossFileConflicts: 0,
        accessMode: 'research',
        profileId: null,
        strictResearchReady: false,
        contractView: 'actual',
        lineageReady: null,
        dataMode: 'historical',
      }),
      {
        severity: 'warning',
        title: '严格研究缺少 Profile',
        reasons: ['当前研究请求未绑定明确 Profile。'],
        allowed: ['选择 Profile 后重新校验'],
        blocked: ['K 线加载与严格研究资格'],
        actions: ['evidence', 'profile'],
      },
    )
  })

  it('redacts physical paths and secrets from backend reasons', () => {
    const impact = buildMarketQualityImpact({
      qualityStatus: 'warning',
      warningReasons: [
        '冲突文件 /Volumes/扩展盘/data/jm.parquet',
        'password=do-not-render',
      ],
      crossFileConflicts: 1,
      accessMode: 'browser',
      profileId: null,
      strictResearchReady: false,
      contractView: 'actual',
      lineageReady: true,
      dataMode: 'historical',
    })
    const rendered = JSON.stringify(impact)
    assert.doesNotMatch(rendered, /\/Volumes\/|do-not-render/)
    assert.match(rendered, /redacted/)
  })

  it('returns null for passed data with valid strict lineage', () => {
    assert.equal(
      buildMarketQualityImpact({
        qualityStatus: 'passed',
        warningReasons: [],
        crossFileConflicts: 0,
        accessMode: 'research',
        profileId: 'intraday_v1',
        strictResearchReady: true,
        contractView: 'actual',
        lineageReady: true,
        dataMode: 'historical',
      }),
      null,
    )
  })

  it('does not request a legacy Profile for canonical identity', () => {
    assert.equal(
      buildMarketQualityImpact({
        qualityStatus: 'passed',
        warningReasons: [],
        crossFileConflicts: 0,
        accessMode: 'research',
        profileId: null,
        canonicalIdentity: true,
        strictResearchReady: true,
        contractView: 'actual',
        lineageReady: true,
        dataMode: 'historical',
      }),
      null,
    )
  })
})
