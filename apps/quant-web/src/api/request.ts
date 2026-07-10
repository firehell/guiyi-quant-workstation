import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { normalizeApiBaseURL } from '@/utils/network'
import { loadAppSettings } from '@/utils/settings'

function resolveBaseURL() {
  const settings = loadAppSettings()
  const configured = settings.apiBaseUrl.trim() || import.meta.env.VITE_API_BASE_URL?.trim()
  return normalizeApiBaseURL(configured)
}

const request: AxiosInstance = axios.create({
  baseURL: resolveBaseURL(),
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

request.interceptors.request.use(
  (config) => {
    const url = config.url || ''
    // Legacy routes live at /api/* (not under /api/v1); keep them site-root relative.
    config.baseURL = url.startsWith('/api/') && !url.startsWith('/api/v1/') ? '' : resolveBaseURL()
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('[API Error]', error.message)
    return Promise.reject(error)
  },
)

export default request
export type { AxiosRequestConfig }
