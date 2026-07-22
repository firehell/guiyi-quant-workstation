import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const apiProxyTarget = process.env.VITE_PROXY_API_TARGET || 'http://127.0.0.1:8000'
const wsProxyTarget = process.env.VITE_PROXY_WS_TARGET || apiProxyTarget.replace(/^http/, 'ws')

// https://vite.dev/config/
export default defineConfig({
  envDir: fileURLToPath(new URL('../../', import.meta.url)),
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'charting-vendor',
              test: /node_modules[\\/](echarts|zrender)[\\/]/,
              priority: 20,
              maxSize: 450 * 1024,
            },
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
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
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
})
