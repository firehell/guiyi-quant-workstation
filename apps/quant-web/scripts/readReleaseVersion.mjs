import { readFileSync } from 'node:fs'

// Shared with the API and Hatch package metadata; private package.json has no release copy.
export function readReleaseVersion(source = new URL('../../../services/quant-api/app/version.py', import.meta.url)) {
  const text = readFileSync(source, 'utf8')
  const matches = [...text.matchAll(/^APP_VERSION = "(\d+\.\d+\.\d+)"$/gm)]
  if (matches.length !== 1) throw new Error('RELEASE_VERSION_INVALID')
  return matches[0][1]
}
