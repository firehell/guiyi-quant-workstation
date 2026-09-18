import { defineConfig } from 'vite'
import base from './vite.config.ts'

/** Overflow candidate: 5175 -> 8011. Does not bind PD/PT 5174/8010. */
export default defineConfig((env) => {
  process.env.GUIYI_PREVIEW_CANDIDATE_ORIGIN = 'http://127.0.0.1:8011'
  return (base as (env: { mode?: string, command?: 'serve' | 'build' }) => unknown)({
    ...env,
    mode: 'candidate-preview',
  })
})
