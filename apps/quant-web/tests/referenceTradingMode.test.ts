import assert from 'node:assert/strict'
import test from 'node:test'
import { getReferenceStreams } from '../src/api/referenceTrading.ts'

test('reference stream mode is explicit and historical remains the default', async () => {
  const seen: Record<string, unknown>[] = []
  const request = async (_url: string, options: { params: Record<string, unknown> }) => {
    seen.push(options.params)
    return { items: [] }
  }
  const identity = { strategy: 'subing-reference', product: 'RB', frequency: '15m' }
  await getReferenceStreams(identity, { request })
  await getReferenceStreams({ ...identity, mode: 'forward_observation' }, { request })
  assert.equal(seen[0]?.mode, 'historical_replay')
  assert.equal(seen[1]?.mode, 'forward_observation')
})
