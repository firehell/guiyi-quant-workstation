import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { candidatePreviewPlugin, candidatePreviewProxy } from './previewProxy.ts'

const apiProxyTarget = process.env.VITE_PROXY_API_TARGET || 'http://127.0.0.1:8000'
const wsProxyTarget = process.env.VITE_PROXY_WS_TARGET || apiProxyTarget.replace(/^http/, 'ws')

// https://vite.dev/config/
export default defineConfig(({ mode, command }) => {
  const candidate = mode === 'candidate-preview'
  const cutoff = process.env.GUIYI_PREVIEW_AS_OF || ''
  if (candidate && (command !== 'serve' || !/(Z|[+-]\d{2}:\d{2})$/.test(cutoff)
    || !Number.isFinite(Date.parse(cutoff)) || Date.parse(cutoff) > Date.now())) {
    throw new Error('PREVIEW_CUTOFF_INVALID_OR_NOT_DEV_SERVER')
  }
  const codeSha = candidate ? execFileSync('git', ['rev-parse', 'HEAD'], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8',
  }).trim() : ''
  if (candidate && !/^[0-9a-f]{40}$/.test(codeSha)) throw new Error('PREVIEW_CODE_IDENTITY_UNAVAILABLE')
  return {
    envDir: fileURLToPath(new URL('../../', import.meta.url)),
    plugins: [vue(), ...(candidate ? [candidatePreviewPlugin()] : [])],
    define: {
      'import.meta.env.VITE_CANDIDATE_PREVIEW': JSON.stringify(candidate ? '1' : '0'),
      'import.meta.env.VITE_PREVIEW_AS_OF': JSON.stringify(candidate ? new Date(cutoff).toISOString() : ''),
      'import.meta.env.VITE_PREVIEW_CODE_SHA': JSON.stringify(codeSha),
      ...(candidate ? {
        'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api/v1'),
        'import.meta.env.VITE_MARKET_WS_URL': JSON.stringify(''),
      } : {}),
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    build: {
      chunkSizeWarningLimit: 600,
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              {
                name: 'date-vendor',
                test: /node_modules[\\/](date-fns|date-fns-tz)[\\/]/,
                priority: 10,
                maxSize: 350 * 1024,
              },
            ],
          },
        },
      },
    },
    server: {
      host: candidate ? '127.0.0.1' : '0.0.0.0',
      port: candidate ? 5174 : 5173,
      strictPort: candidate,
      proxy: candidate ? candidatePreviewProxy() : {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          ws: true,
        },
        '/healthz': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: wsProxyTarget,
          ws: true,
        },
      },
    },
  }
})
