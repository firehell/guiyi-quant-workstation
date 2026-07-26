import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildHtDyFirstSeenPresentation,
  type HtDyFirstSeenRecord,
} from '../src/utils/htdyFirstSeenPresentation.ts'

const record: HtDyFirstSeenRecord = {
  source_mode: 'live_realtime_repainting',
  strategy_name: 'htdy_original_realtime_first_seen',
  strategy_version: 'v1.0',
  actual_contract: 'JM2609',
  period: '15m',
  signal_time: '2026-07-27T01:04:00+00:00',
  bar_start: '2026-07-24T14:45:00+08:00',
  bar_end: '2026-07-24T15:00:00+08:00',
  payload: {
    htdy_first_seen: {
      observation_only: true,
      future_looking: true,
      repainting_accepted: true,
      first_seen_no_retraction: true,
      notification_ready: false,
      auto_order: false,
    },
    formal_lineage: {
      schema_version: 'signal_review_lineage_v2',
      contract: {
        actual_contract: 'JM2609',
      },
      bar: {
        bar_start: '2026-07-24T14:45:00+08:00',
        bar_end: '2026-07-24T15:00:00+08:00',
      },
    },
  },
}

describe('HTDY first-seen presentation', () => {
  it('exposes exact immutable observation evidence without trading capability', () => {
    assert.deepEqual(buildHtDyFirstSeenPresentation(record), {
      isHtDyFirstSeen: true,
      identity: 'htdy_original_realtime_first_seen / v1.0',
      sourceMode: 'live_realtime_repainting',
      actualContract: 'JM2609',
      period: '15m',
      firstSeenAt: '2026-07-27T01:04:00+00:00',
      bucketStart: '2026-07-24T14:45:00+08:00',
      bucketEnd: '2026-07-24T15:00:00+08:00',
      lineageSchema: 'signal_review_lineage_v2',
      observationOnly: true,
      futureLooking: true,
      repaintingAccepted: true,
      firstSeenNoRetraction: true,
      notificationReady: false,
      autoOrder: false,
    })
  })

  it('rejects lookalike records missing the exact strategy or safety contract', () => {
    assert.equal(
      buildHtDyFirstSeenPresentation({
        ...record,
        strategy_name: 'other_strategy',
      }),
      null,
    )
    assert.equal(
      buildHtDyFirstSeenPresentation({
        ...record,
        payload: {
          ...record.payload,
          htdy_first_seen: {
            ...(record.payload?.htdy_first_seen as Record<string, unknown>),
            notification_ready: true,
          },
        },
      }),
      null,
    )
  })
})
