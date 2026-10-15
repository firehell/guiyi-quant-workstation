import assert from 'node:assert/strict'
import test from 'node:test'
import { createReadAdmission } from '../src/utils/readAdmission.ts'

test('foreground budget is two; abort removes queued requests and releases are idempotent', async () => {
  const admit = createReadAdmission(2), cancelled = new AbortController()
  const first = await admit(), second = await admit()
  const obsolete = admit(cancelled.signal)
  let accepted = false
  const next = admit().then(release => { accepted = true; return release })
  await Promise.resolve(); assert.equal(accepted, false)
  cancelled.abort(); await assert.rejects(obsolete, { name: 'AbortError' })
  first(); first(); const release = await next
  second(); release()
  const a = await admit(), b = await admit(); a(); b()
})
