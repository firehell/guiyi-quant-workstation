export interface PagedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface PageRequest {
  limit?: number
  offset?: number
}
