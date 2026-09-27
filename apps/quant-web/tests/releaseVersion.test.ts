import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readReleaseVersion } from '../scripts/readReleaseVersion.mjs'

test('release reader observes a source version change without another metadata copy', () => {
  const directory = mkdtempSync(join(tmpdir(), 'guiyi-version-'))
  const source = pathToFileURL(join(directory, 'version.py'))
  try {
    writeFileSync(source, 'APP_VERSION = "1.10.38"\n')
    assert.equal(readReleaseVersion(source), '1.10.38')
    writeFileSync(source, 'APP_VERSION = "1.10.39"\n')
    assert.equal(readReleaseVersion(source), '1.10.39')
    for (const invalid of ['', 'APP_VERSION = "unknown"\n',
      'APP_VERSION = "1.10.38"\nAPP_VERSION = "1.10.39"\n']) {
      writeFileSync(source, invalid)
      assert.throws(() => readReleaseVersion(source), /RELEASE_VERSION_INVALID/)
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
