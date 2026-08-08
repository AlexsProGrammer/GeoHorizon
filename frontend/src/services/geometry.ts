import type { Feature, Polygon } from 'geojson'

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
