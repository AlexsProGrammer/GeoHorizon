import type { FeatureCollection } from 'geojson'

export interface CogInfo {
  name: string
  path: string
  crs: string | null
  extent: number[]
  extent_epsg4326: number[] | null
  pixel_size_m: number
  shape: number[]
  nodata: number | null
}

export interface ViewshedRequest {
  cog_path: string
  lat: number
  lng: number
  radius_km: number
  azimuth: number
  fov: number
  observer_height: number
  tree_height: number
  building_height: number
  horizon_enabled: boolean
  horizon_max_km?: number
}

export interface AreaSearchRequest {
  cog_path: string
  search_area: object // GeoJSON Polygon (WGS84)
  radius_km: number
  azimuth: number
  fov: number
  grid_step_m: number
  observer_height: number
  tree_height: number
  building_height: number
  horizon_enabled: boolean
  horizon_max_km?: number
}

const API_BASE = '/api'

export async function fetchCogBounds(): Promise<CogInfo[]> {
  const res = await fetch(`${API_BASE}/viewshed/bounds`)
  if (!res.ok) throw new Error(`Failed to fetch COG bounds: ${res.status}`)
  const data = (await res.json()) as { cogs: CogInfo[] }
  return data.cogs
}

export async function startViewshed(params: ViewshedRequest): Promise<{ task_id: string }> {
  const res = await fetch(`${API_BASE}/viewshed/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error(`Failed to start viewshed: ${res.status}`)
  return (await res.json()) as { task_id: string }
}

export async function startAreaSearch(params: AreaSearchRequest): Promise<{ task_id: string }> {
  const res = await fetch(`${API_BASE}/viewshed/area-search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error(`Failed to start area search: ${res.status}`)
  return (await res.json()) as { task_id: string }
}

export async function fetchTaskResult(taskId: string): Promise<FeatureCollection> {
  const res = await fetch(`${API_BASE}/viewshed/result/${taskId}`)
  if (!res.ok) throw new Error(`Failed to fetch result: ${res.status}`)
  return (await res.json()) as FeatureCollection
}

export async function cancelViewshed(taskId: string): Promise<void> {
  await fetch(`${API_BASE}/viewshed/cancel/${taskId}`, { method: 'POST' })
}

export interface TaskStatus {
  state: string
  error: string | null
}

/** Poll the current Celery state of a task (e.g. PENDING / STARTED / SUCCESS / FAILURE / REVOKED). */
export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const res = await fetch(`${API_BASE}/viewshed/status/${taskId}`)
  if (!res.ok) throw new Error(`Failed to fetch task status: ${res.status}`)
  return (await res.json()) as TaskStatus
}
