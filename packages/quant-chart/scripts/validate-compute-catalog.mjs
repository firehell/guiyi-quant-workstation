import { readFileSync } from 'node:fs'
import { validateDisplayCatalog } from '../dist/index.js'

validateDisplayCatalog(JSON.parse(readFileSync(0, 'utf8')))
