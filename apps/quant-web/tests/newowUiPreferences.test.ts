import assert from 'node:assert/strict'
import test from 'node:test'
import { readNewowUiPreferences, rememberNewowUiPreferences } from '../src/utils/newowUiPreferences.ts'
test('preferences are identity scoped, patch only display choices and evict older visits', () => {
  rememberNewowUiPreferences('rb:trend', { auxiliary: 'zhaoyao_mirror', scrollTop: 100 })
  rememberNewowUiPreferences('rb:trend', { scrollTop: 250 })
  assert.deepEqual(readNewowUiPreferences('rb:trend'), { auxiliary: 'zhaoyao_mirror', scrollTop: 250 })
  assert.deepEqual(readNewowUiPreferences('jm:trend'), {})
  for (let i = 0; i < 16; i++) rememberNewowUiPreferences(`identity:${i}`, { scrollTop: i })
  assert.deepEqual(readNewowUiPreferences('rb:trend'), {})
})
