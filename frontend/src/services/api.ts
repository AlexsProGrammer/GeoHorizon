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

export async function cancelViewshed(taskId: string): Promise<void> {
  await fetch(`${API_BASE}/viewshed/cancel/${taskId}`, { method: 'POST' })
}

export function getResultImageUrl(taskId: string): string {
  return `${API_BASE}/viewshed/result/${taskId}/image`
}
