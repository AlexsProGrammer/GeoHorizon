import type { Feature, LineString, Polygon } from 'geojson'

const EARTH_RADIUS_KM = 6371
const METERS_PER_KM = 1000
const EARTH_RADIUS_M = 6371000

function destinationPoint(
  lng: number,
  lat: number,
  distanceMeters: number,
  bearingDeg: number,
): [number, number] {
  const radLat = (lat * Math.PI) / 180
  const radLng = (lng * Math.PI) / 180
  const bearing = (bearingDeg * Math.PI) / 180
  const angularDistance = distanceMeters / EARTH_RADIUS_M

  const lat2 = Math.asin(
    Math.sin(radLat) * Math.cos(angularDistance) +
      Math.cos(radLat) * Math.sin(angularDistance) * Math.cos(bearing),
  )
  const lon2 =
    radLng +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(radLat),
      Math.cos(angularDistance) - Math.sin(radLat) * Math.sin(lat2),
    )

  return [(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]
}

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
  const isPanoramic = fov >= 360
  const sweepFrom = isPanoramic ? -180 : azimuth - fov / 2
  const sweepTo = isPanoramic ? 180 : azimuth + fov / 2

  const coords: [number, number][] = [[lng, lat]]
  for (let i = 0; i <= numPoints; i++) {
    const angle = sweepFrom + ((sweepTo - sweepFrom) * i) / numPoints
    const point = destinationPoint(lng, lat, radiusMeters, angle)
    coords.push(point)
  }
  coords.push([lng, lat])

  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [coords] },
  }
}

export function buildArcSegment(
  lng: number,
  lat: number,
  radiusKm: number,
  startAzimuth: number,
  endAzimuth: number,
  numPoints = 64,
): Feature<LineString> {
  const radiusMeters = radiusKm * 1000
  const start = destinationPoint(lng, lat, radiusMeters, startAzimuth)
  const end = destinationPoint(lng, lat, radiusMeters, endAzimuth)
  const coords: [number, number][] = [start]

  for (let i = 1; i < numPoints; i++) {
    const t = i / numPoints
    const angle = startAzimuth + (endAzimuth - startAzimuth) * t
    coords.push(destinationPoint(lng, lat, radiusMeters, angle))
  }
  coords.push(end)

  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'LineString', coordinates: coords },
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

/**
 * Build a circular GeoJSON Polygon centred on ``(lng, lat)`` extending
 * ``radiusKm`` metres/kilometres out. Used by point mode to auto-generate its
 * search area so it runs through the same multi-point polygon scoring as area
 * mode. ``numPoints`` (default 64) controls the smoothness of the circle.
 */
export function buildCirclePolygon(
  lng: number,
  lat: number,
  radiusKm: number,
  numPoints = 64,
): Feature<Polygon> {
  const radiusMeters = radiusKm * 1000
  const coords: [number, number][] = []
  for (let i = 0; i < numPoints; i++) {
    const angle = (360 * i) / numPoints
    coords.push(destinationPoint(lng, lat, radiusMeters, angle))
  }
  coords.push(coords[0])

  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [coords] },
  }
}
