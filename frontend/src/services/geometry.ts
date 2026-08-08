import type { Feature, Polygon } from 'geojson'

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

  const startAngle = azimuth - fov / 2
  const endAngle = azimuth + fov / 2

  const coords: [number, number][] = [[lng, lat]]
  for (let i = 0; i <= numPoints; i++) {
    const angle = startAngle + ((endAngle - startAngle) * i) / numPoints
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
