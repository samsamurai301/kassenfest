import type { components } from './schema'

// Types come from the backend's OpenAPI spec: run `make api-types` after changing API models.
export type Health = components['schemas']['Health']

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

export const api = {
  health: () => get<Health>('/api/health'),
}
