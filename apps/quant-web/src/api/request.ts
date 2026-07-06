import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { normalizeApiBaseURL } from '@/utils/network'

const configuredBaseURL = import.meta.env.VITE_API_BASE_URL
const baseURL = normalizeApiBaseURL(configuredBaseURL)

const request: AxiosInstance = axios.create({
  baseURL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

request.interceptors.request.use(
  (config) => {
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
