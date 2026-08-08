import { useEffect, useMemo, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Protocol } from 'pmtiles'
import type { Feature, Geometry } from 'geojson'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { BitmapLayer, GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers'
import { useMapStore } from '../store/useMapStore'
import { buildConePolygon, buildPolygonFeature } from '../services/geometry'
import Compass from './Compass'
import HoverTooltip from './HoverTooltip'

// Register the pmtiles:// protocol handler for MapLibre once.
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

// Default view centered on the imported Oberbayern / Traunreut area.
const DEFAULT_CENTER: [number, number] = [12.65, 47.95]

// Friendly labels for the layers in public/style.json (OpenMapTiles-like).
const FEATURE_LABELS: Record<string, string> = {
  water: 'Water',
  landcover: 'Land cover',
  landuse: 'Land use',
  roads: 'Road',
  'roads-casing': 'Road',
  transportation: 'Road',
  buildings: 'Building',
  building: 'Building',
}

function featureLabel(f: { layer?: { id?: string }; properties?: Record<string, unknown> }): string | null {
  const cls = f.properties?.class
  if (cls) {
    const c = String(cls)
    if (c.includes('wood') || c.includes('forest')) return 'Forest'
    if (c.includes('grass') || c.includes('meadow') || c.includes('grassland')) return 'Grass'
    if (c.includes('residential')) return 'Residential'
    if (c.includes('industrial')) return 'Industrial'
    if (c === 'park') return 'Park'
  }
  const name = f.properties?.name
  if (name) return String(name)
  return FEATURE_LABELS[f.layer?.id ?? ''] ?? null
}

function collectHoverFeatures(
  features: Array<{ layer?: { id?: string }; properties?: Record<string, unknown> }>,
): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const f of features) {
    const label = featureLabel(f)
    if (label && !seen.has(label)) {
      seen.add(label)
      out.push(label)
    }
    if (out.length >= 4) break
  }
  return out
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)

  const observerLat = useMapStore((s) => s.observerLat)
  const observerLng = useMapStore((s) => s.observerLng)
  const searchMode = useMapStore((s) => s.searchMode)
  const radiusKm = useMapStore((s) => s.radiusKm)
  const azimuth = useMapStore((s) => s.azimuth)
  const fov = useMapStore((s) => s.fov)
  const searchPolygon = useMapStore((s) => s.searchPolygon)
  const draftVertices = useMapStore((s) => s.draftVertices)
  const resultImageUrl = useMapStore((s) => s.resultImageUrl)
  const resultBbox = useMapStore((s) => s.resultBbox)
  const resultGeoJSON = useMapStore((s) => s.resultGeoJSON)
  const legendVisibility = useMapStore((s) => s.legendVisibility)
  const setObserver = useMapStore((s) => s.setObserver)
  const setSearchPolygon = useMapStore((s) => s.setSearchPolygon)
  const addDraftVertex = useMapStore((s) => s.addDraftVertex)
  const clearDraft = useMapStore((s) => s.clearDraft)
  const setHoverPosition = useMapStore((s) => s.setHoverPosition)

  // Initialize the MapLibre map and Deck.gl overlay once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: '/style.json',
      center: DEFAULT_CENTER,
      zoom: 12,
    })
    mapRef.current = map

    // Share the depth buffer with MapLibre terrain (fixes z-fighting between
    // the overlay layers and the 3D surface) and apply transparent blending.
    const overlay = new MapboxOverlay({
      interleaved: false,            // MAPLIBRE-compatible rendering path (was: true)
      parameters: { blend: true },   // drop depthTest: Deck.gl draws in its own top layer
    })
    overlayRef.current = overlay
    map.addControl(overlay)

    // Enable 3D terrain from dynamically-rendered terrain-RGB tiles.
    // DISABLED (ISOLATION TEST): re-enable after confirming the NaN cause.
    const enableTerrain = false
    map.on('load', () => {
      if (!enableTerrain) return
      if (map.getSource('terrain-dem')) return
      map.addSource('terrain-dem', {
        type: 'raster-dem',
        tiles: ['/api/viewshed/terrain/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 15,
        encoding: 'mapbox',
      } as maplibregl.RasterDEMSourceSpecification)
      map.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 })
    })

    // Mouse hover: capture coordinates, terrain elevation and OSM features.
    const onMove = (e: maplibregl.MapMouseEvent) => {
      let elevation: number | null = null
      try {
        const el = map.queryTerrainElevation(e.lngLat)
        if (typeof el === 'number' && isFinite(el)) elevation = el
      } catch {
        elevation = null
      }
      const features = collectHoverFeatures(
        map.queryRenderedFeatures(e.point) as Array<{
          layer?: { id?: string }
          properties?: Record<string, unknown>
        }>,
      )
      setHoverPosition({
        lng: e.lngLat.lng,
        lat: e.lngLat.lat,
        elevation,
        features,
        x: e.point.x,
        y: e.point.y,
      })
    }
    const onLeave = () => setHoverPosition(null)
    map.on('mousemove', onMove)
    map.on('mouseleave', onLeave)

    return () => {
      map.off('mousemove', onMove)
      map.off('mouseleave', onLeave)
      map.remove()
      mapRef.current = null
      overlayRef.current = null
    }
  }, [setHoverPosition])

  // Click behaviour: place the observer in point mode, add an area vertex in
  // area mode. Re-registered whenever the mode (or handler identity) changes.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const handler = (e: maplibregl.MapMouseEvent) => {
      if (searchMode === 'area') {
        addDraftVertex([e.lngLat.lng, e.lngLat.lat])
      } else {
        setObserver(e.lngLat.lat, e.lngLat.lng)
      }
    }
    map.on('click', handler)
    return () => {
      map.off('click', handler)
    }
  }, [searchMode, addDraftVertex, setObserver])

  // Live directional cone preview, recomputed as parameters change.
  // Only shown in single-point mode.
  const coneLayer = useMemo(() => {
    if (searchMode !== 'point' || observerLat == null || observerLng == null) return null
    const polygon = buildConePolygon(observerLng, observerLat, radiusKm, azimuth, fov)
    return new GeoJsonLayer({
      id: 'cone-preview',
      data: polygon,
      filled: true,
      stroked: true,
      getFillColor: [100, 200, 255, 55],
      getLineColor: [30, 120, 255, 200],
      lineWidthMinPixels: 2,
      pickable: false,
    })
  }, [searchMode, observerLat, observerLng, radiusKm, azimuth, fov])

  // The finalized search area drawn by the user.
  const searchLayer = useMemo(() => {
    if (!searchPolygon) return null
    return new GeoJsonLayer({
      id: 'search-area',
      data: searchPolygon,
      filled: true,
      stroked: true,
      getFillColor: [34, 197, 94, 40],
      getLineColor: [16, 185, 129, 230],
      lineWidthMinPixels: 2,
      pickable: false,
    })
  }, [searchPolygon])

  // Live draft of vertices while the user is drawing the search area.
  const draftLayer = useMemo(() => {
    if (searchMode !== 'area' || draftVertices.length < 2) return null
    let draftFeature: Feature<Geometry>
    if (draftVertices.length >= 3) {
      draftFeature = buildPolygonFeature(draftVertices) as unknown as Feature<Geometry>
    } else {
      draftFeature = {
        type: 'Feature',
        properties: {},
        geometry: { type: 'LineString', coordinates: draftVertices },
      }
    }
    return new GeoJsonLayer({
      id: 'area-draft',
      data: draftFeature,
      filled: true,
      stroked: true,
      getFillColor: [251, 146, 60, 60],
      getLineColor: [249, 115, 22, 230],
      lineWidthMinPixels: 2,
      pickable: false,
    })
  }, [searchMode, draftVertices])

  // Hardware-accelerated single-point viewshed overlay (PNG).
  const viewshedLayer = useMemo(() => {
    if (!resultImageUrl || !resultBbox) return null
    return new BitmapLayer({
      id: 'viewshed-result',
      image: resultImageUrl,
      bounds: resultBbox,
      opacity: 0.7,
      desaturate: 0,
      transparentColor: [0, 0, 0, 0],
    })
  }, [resultImageUrl, resultBbox])

  // Area-search result: scored positions rendered as color-coded points.
  // Colors follow the legend thresholds: green >= 70%, yellow 30-70%, red < 30%.
  const resultLayer = useMemo(() => {
    if (!resultGeoJSON?.features.length) return null
    const data = resultGeoJSON.features.filter((f) => {
      const s = (f.properties?.score as number | undefined) ?? 0
      if (s >= 0.7) return legendVisibility.green
      if (s >= 0.3) return legendVisibility.yellow
      return legendVisibility.red
    })
    return new ScatterplotLayer({
      id: 'area-result',
      data,
      getPosition: (f) =>
        f.geometry.type === 'Point' ? (f.geometry.coordinates as [number, number]) : [0, 0],
      getFillColor: (f) => {
        const s = (f.properties?.score as number | undefined) ?? 0
        if (s >= 0.7) return [34, 197, 94, 210]
        if (s >= 0.3) return [234, 179, 8, 210]
        return [239, 68, 68, 205]
      },
      getLineColor: [0, 0, 0, 110],
      getRadius: 14,
      radiusUnits: 'pixels',
      radiusMinPixels: 4,
      radiusMaxPixels: 22,
      stroked: true,
      lineWidthMinPixels: 1,
      pickable: false,
    })
  }, [resultGeoJSON, legendVisibility])

  const layers = useMemo(
    () =>
      [coneLayer, searchLayer, draftLayer, viewshedLayer, resultLayer].filter(
        (l): l is NonNullable<typeof l> => l != null,
      ),
    [coneLayer, searchLayer, draftLayer, viewshedLayer, resultLayer],
  )

  // Push the current layers into the Deck.gl overlay whenever they change.
  useEffect(() => {
    overlayRef.current?.setProps({ layers })
  }, [layers])

  function finishArea() {
    if (draftVertices.length < 3) return
    setSearchPolygon(buildPolygonFeature(draftVertices))
    clearDraft()
  }

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      <Compass mapRef={mapRef} />
      <HoverTooltip />
      {searchMode === 'area' && (
        <div className="pointer-events-auto absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-zinc-300 bg-white/95 px-3 py-2 shadow-lg">
          <span className="text-xs text-zinc-600">
            {searchPolygon
              ? 'Area set — adjust or click Calculate'
              : draftVertices.length < 3
                ? 'Click the map to add polygon vertices'
                : 'Add more vertices or finish the area'}
          </span>
          {draftVertices.length >= 3 && (
            <button
              onClick={finishArea}
              className="rounded bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700"
            >
              Finish area
            </button>
          )}
          <button
            onClick={clearDraft}
            className="rounded bg-zinc-200 px-2.5 py-1 text-xs font-semibold text-zinc-700 hover:bg-zinc-300"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}
