import type { Feature, Polygon } from 'geojson'

const EARTH_RADIUS_KM = 6371
const METERS_PER_KM = 1000

/**
 * Build a GeoJSON Polygon feature from an ordered list of vertices.
 * The polygon ring is closed automatically if not already.
 */
export function buildPolygonFeature(
  vertices: [number, number][],
): Feature<Polygon> {
  const ring = vertices.length >= 3 ? [...vertices] : [[0, 0]]
  const first = ring[0]
  const last = ring[ring.length - 1]
  if (last[0] !== first[0] || last[1] !== first[1]) {
    ring.push(first)
  }
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [ring] },
  }
}

/**
 * Build a wedge/cone polygon representing the directional viewshed preview.
 *
 * The cone originates at `(lng, lat)`, points toward `azimuth` (0 = North,
 * 90 = East, 270 = West) and spans `fov` degrees wide, extending `radiusKm`
 * out. Returns a GeoJSON Polygon feature suitable for a Deck.gl GeoJsonLayer.
 */
export function buildConePolygon(
  lng: number,
  lat: number,
  radiusKm: number,
  azimuth: number,
  fov: number,
  numPoints = 64,
): Feature<Polygon> {
  const radiusMeters = radiusKm * 1000
  const metersPerDegLat = 111320
  const metersPerDegLng = 111320 * Math.cos((lat * Math.PI) / 180)

  // A 360° (panoramic) view sweeps the full circle; center the sweep on North
  // so the polygon closes cleanly regardless of the stored azimuth.
  const isPanoramic = fov >= 360
  const sweepFrom = isPanoramic ? -180 : azimuth - fov / 2
  const sweepTo = isPanoramic ? 180 : azimuth + fov / 2

  const coords: [number, number][] = [[lng, lat]]
  for (let i = 0; i <= numPoints; i++) {
    const angle = sweepFrom + ((sweepTo - sweepFrom) * i) / numPoints
    const rad = (angle * Math.PI) / 180
    const dx = Math.sin(rad) * radiusMeters
    const dy = Math.cos(rad) * radiusMeters
    coords.push([lng + dx / metersPerDegLng, lat + dy / metersPerDegLat])
  }
  coords.push([lng, lat])

  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [coords] },
  }
}

/**
 * Compute the area (in km²) of a GeoJSON polygon on the WGS84 sphere using
 * spherical excess. Returns the absolute area of the outer ring.
 */
export function polygonAreaKm2(polygon: Feature<Polygon>): number {
  const ring = polygon.geometry.coordinates[0]
  if (!ring || ring.length < 3) return 0

  let total = 0
  const n = ring.length
  for (let i = 0; i < n; i++) {
    const [lng1, lat1] = ring[i]
    const [lng2, lat2] = ring[(i + 1) % n]
    total +=
      ((lng2 - lng1) * Math.PI) / 180 *
      (2 + Math.sin((lat1 * Math.PI) / 180) + Math.sin((lat2 * Math.PI) / 180))
  }
  return Math.abs((total * EARTH_RADIUS_KM * EARTH_RADIUS_KM) / 2)
}

/**
 * Estimate how many grid points a grid-step area search will sample.
 * ``points = area_km2 * 1e6 / (grid_step_m ^ 2)``; returns 0 when no polygon
 * or step is available.
 */
export function estimateGridPointCount(
  polygon: Feature<Polygon> | null,
  gridStepM: number,
): number {
  if (!polygon || gridStepM <= 0) return 0
  const areaKm2 = polygonAreaKm2(polygon)
  return Math.round((areaKm2 * METERS_PER_KM * METERS_PER_KM) / (gridStepM * gridStepM))
}
