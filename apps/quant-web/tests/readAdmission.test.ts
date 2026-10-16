import assert from 'node:assert/strict'
import test from 'node:test'
import { createReadAdmission, READ_PRIORITY } from '../src/utils/readAdmission.ts'

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

test('waiting GETs use explicit priority and retain FIFO within a tier', async () => {
  const admit = createReadAdmission(2)
  const first = await admit(), second = await admit()
  const order: string[] = []
  const wait = (name: string, priority: 0 | 1 | 2 | 3) => admit(undefined, priority).then(release => {
    order.push(name); release()
  })
  const history = wait('history', READ_PRIORITY.history)
  const visible = wait('visible', READ_PRIORITY.visibleDetail)
  const auxiliary = wait('auxiliary', READ_PRIORITY.selectedAuxiliary)
  const price = wait('price', READ_PRIORITY.foreground)
  const anotherPrice = wait('main', READ_PRIORITY.foreground)
  first(); second()
  await Promise.all([history, visible, auxiliary, price, anotherPrice])
  assert.deepEqual(order, ['price', 'main', 'auxiliary', 'visible', 'history'])
})

test('aborted high priority waiters leave no reservation', async () => {
  const admit = createReadAdmission(1)
  const release = await admit()
  const obsolete = new AbortController()
  const canceled = admit(obsolete.signal, READ_PRIORITY.foreground)
  const live = admit(undefined, READ_PRIORITY.history)
  obsolete.abort()
  await assert.rejects(canceled, { name: 'AbortError' })
  release()
  const next = await live; next()
  const after = await admit(); after()
})
