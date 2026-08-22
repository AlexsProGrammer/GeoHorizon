import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Protocol } from 'pmtiles'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { useMapStore } from '../store/useMapStore'
import { buildConePolygon, buildPolygonFeature } from '../services/geometry'
import Compass from './Compass'
import HoverTooltip from './HoverTooltip'

// Register the pmtiles:// protocol handler for MapLibre once.
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

// Default view centered on the imported Oberbayern / Traunreut area.
const DEFAULT_CENTER: [number, number] = [12.65, 47.95]

// Empty GeoJSON used to clear native MapLibre overlay sources.
const EMPTY_FC: FeatureCollection = { type: 'FeatureCollection', features: [] }

type TaskResult = FeatureCollection | { samples?: FeatureCollection; [key: string]: unknown }

// Threshold coloring for area-search results (matches the legend: green/yellow/red).
function resultColor(score: number): string {
  if (score >= 0.7) return '#22c55e'
  if (score >= 0.3) return '#eab308'
  return '#ef4444'
}
function resultVisible(score: number, vis: { green: boolean; yellow: boolean; red: boolean }): boolean {
  if (score >= 0.7) return vis.green
  if (score >= 0.3) return vis.yellow
  return vis.red
}
function pointStateColor(state: string): string {
  if (state === 'clear') return '#22c55e'
  if (state === 'grazing') return '#eab308'
  return '#ef4444'
}
function extractResultFeatures(resultGeoJSON: TaskResult | null): FeatureCollection {
  if (!resultGeoJSON) return EMPTY_FC
  if ('samples' in resultGeoJSON && resultGeoJSON.samples) return resultGeoJSON.samples
  return resultGeoJSON as FeatureCollection
}

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

/**
 * Sample the absolute elevation (m above sea level) directly from the backend COG.
 * Unlike MapLibre's terrain read (which returns 0 whenever the hovered point's DEM
 * tile isn't in its evicted/lazily-loaded cache), this is always correct.
 */
async function fetchElevation(lng: number, lat: number): Promise<number | null> {
  try {
    const r = await fetch(`/api/viewshed/elevation?lng=${lng}&lat=${lat}`)
    if (!r.ok) return null
    const d = await r.json()
    return typeof d.elevation === 'number' && Number.isFinite(d.elevation)
      ? d.elevation
      : null
  } catch {
    return null
  }
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  // Hover bookkeeping: the current pointer state (for the tooltip) plus the last
  // successfully fetched elevation and throttling/token refs for the COG sampler.
  const hoverStateRef = useRef<{
    lng: number
    lat: number
    features: string[]
    x: number
    y: number
  } | null>(null)
  const elevRef = useRef<number | null>(null)
  const lastExpensiveRef = useRef(0)
  const expensiveTokenRef = useRef(0)

  const observerLat = useMapStore((s) => s.observerLat)
  const observerLng = useMapStore((s) => s.observerLng)
  const searchMode = useMapStore((s) => s.searchMode)
  const radiusKm = useMapStore((s) => s.radiusKm)
  const azimuth = useMapStore((s) => s.azimuth)
  const fov = useMapStore((s) => s.fov)
  const searchPolygon = useMapStore((s) => s.searchPolygon)
  const draftVertices = useMapStore((s) => s.draftVertices)
  const resultGeoJSON = useMapStore((s) => s.resultGeoJSON)
  const panoramicMode = useMapStore((s) => s.panoramicMode)
  const legendVisibility = useMapStore((s) => s.legendVisibility)
  const setObserver = useMapStore((s) => s.setObserver)
  const setSearchPolygon = useMapStore((s) => s.setSearchPolygon)
  const addDraftVertex = useMapStore((s) => s.addDraftVertex)
  const clearDraft = useMapStore((s) => s.clearDraft)
  const setHoverPosition = useMapStore((s) => s.setHoverPosition)

  // ---- Native MapLibre overlay updaters ------------------------------------
  // These render the cone, search area, draft, and scored result points as native
  // MapLibre vector layers, which MapLibre lays directly onto the 3D terrain so
  // they stay glued with no parallax when panning/rotating and never get occluded.
  function updateCone() {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource('gh-cone') as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const show = searchMode === 'point' && observerLat != null && observerLng != null
    const coneFov = panoramicMode ? 360 : fov
    src.setData(show ? (buildConePolygon(observerLng!, observerLat!, radiusKm, azimuth, coneFov) as unknown as any) : (EMPTY_FC as unknown as any))
    map.setLayoutProperty('gh-cone-fill', 'visibility', show ? 'visible' : 'none')
    map.setLayoutProperty('gh-cone-line', 'visibility', show ? 'visible' : 'none')
  }
  function updateSearch() {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource('gh-search') as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const show = searchPolygon != null
    src.setData((searchPolygon ?? EMPTY_FC) as unknown as any)
    map.setLayoutProperty('gh-search-fill', 'visibility', show ? 'visible' : 'none')
    map.setLayoutProperty('gh-search-line', 'visibility', show ? 'visible' : 'none')
  }
  function updateDraft() {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource('gh-draft') as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const show = searchMode === 'area' && draftVertices.length >= 2
    if (show) {
      const f: Feature<Geometry> =
        draftVertices.length >= 3
          ? (buildPolygonFeature(draftVertices) as unknown as Feature<Geometry>)
          : { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: draftVertices } }
      src.setData(f as unknown as any)
    } else {
      src.setData(EMPTY_FC as unknown as any)
    }
    map.setLayoutProperty('gh-draft-fill', 'visibility', show ? 'visible' : 'none')
    map.setLayoutProperty('gh-draft-line', 'visibility', show ? 'visible' : 'none')
  }
  function updateResult() {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource('gh-result') as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const sampleCollection = extractResultFeatures(resultGeoJSON)
    const feats = sampleCollection.features.filter((f: Feature<Geometry>) => {
      if (f.geometry.type !== 'Point') return false
      const state = String(f.properties?.state ?? '')
      if (state) {
        return state === 'clear' ? legendVisibility.green : state === 'grazing' ? legendVisibility.yellow : legendVisibility.red
      }
      const score = (f.properties?.score as number | undefined) ?? 0
      return resultVisible(score, legendVisibility)
    }).map((f: Feature<Geometry>) => {
      const state = String(f.properties?.state ?? '')
      const props = {
        ...f.properties,
        color: state ? pointStateColor(state) : resultColor((f.properties?.score as number | undefined) ?? 0),
      }
      return { type: 'Feature', properties: props, geometry: f.geometry } as Feature<Geometry>
    })
    src.setData({ type: 'FeatureCollection', features: feats } as unknown as any)
    map.setLayoutProperty('gh-result', 'visibility', feats.length ? 'visible' : 'none')
  }

  // Initialize the MapLibre map and Deck.gl overlay once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: '/style.json',
      center: DEFAULT_CENTER,
      zoom: 12,
      // Allow the camera to tilt down to a near-ground view. MapLibre's default
      // maxPitch is 60°, which keeps the view high above the ground; raising it
      // to the safe maximum (85°) lets you get very close to the terrain without
      // going below the horizon (which would clip through the ground).
      maxPitch: 85,
      maxZoom: 22,
      minPitch: 0,
    })
    mapRef.current = map

    // Enable 3D terrain from dynamically-rendered terrain-RGB tiles.
    map.on('load', () => {
      if (!map.getSource('terrain-dem')) {
        map.addSource('terrain-dem', {
          type: 'raster-dem',
          // ?v=2 busts browsers' stale HTTP cache of the old (buggy-encoded) tiles.
          tiles: ['/api/viewshed/terrain/{z}/{x}/{y}.png?v=2'],
          tileSize: 256,
          maxzoom: 15,
          encoding: 'mapbox',
        } as maplibregl.RasterDEMSourceSpecification)
        map.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 })
      }

      // Native overlay sources/layers (glued to the 3D terrain, no parallax).
      if (!map.getSource('gh-cone')) {
        map.addSource('gh-cone', { type: 'geojson', data: EMPTY_FC as unknown as any })
        map.addLayer({
          id: 'gh-cone-fill', type: 'fill', source: 'gh-cone',
          paint: { 'fill-color': '#64c8ff', 'fill-opacity': 0.22, 'fill-outline-color': '#1e78ff' },
        })
        map.addLayer({
          id: 'gh-cone-line', type: 'line', source: 'gh-cone',
          paint: { 'line-color': '#1e78ff', 'line-width': 2 },
        })

        map.addSource('gh-search', { type: 'geojson', data: EMPTY_FC as unknown as any })
        map.addLayer({
          id: 'gh-search-fill', type: 'fill', source: 'gh-search',
          paint: { 'fill-color': '#22c55e', 'fill-opacity': 0.16, 'fill-outline-color': '#10b981' },
        })
        map.addLayer({
          id: 'gh-search-line', type: 'line', source: 'gh-search',
          paint: { 'line-color': '#10b981', 'line-width': 2 },
        })

        map.addSource('gh-draft', { type: 'geojson', data: EMPTY_FC as unknown as any })
        map.addLayer({
          id: 'gh-draft-fill', type: 'fill', source: 'gh-draft',
          paint: { 'fill-color': '#fb923c', 'fill-opacity': 0.24, 'fill-outline-color': '#f97316' },
        })
        map.addLayer({
          id: 'gh-draft-line', type: 'line', source: 'gh-draft',
          paint: { 'line-color': '#f97316', 'line-width': 2 },
        })

        map.addSource('gh-result', { type: 'geojson', data: EMPTY_FC as unknown as any })
        map.addLayer({
          id: 'gh-result', type: 'circle', source: 'gh-result',
          paint: {
            'circle-color': ['get', 'color'],
            'circle-radius': 6,
            'circle-stroke-color': 'rgba(0,0,0,0.45)',
            'circle-stroke-width': 1,
          },
        })
      }

      // Initial population using current state.
      updateCone()
      updateSearch()
      updateDraft()
      updateResult()
    })

    // Mouse hover: capture coordinates, OSM features and elevation.
    // Position/x/y update cheaply & instantly so the tooltip follows the cursor,
    // but the expensive work (queryRenderedFeatures + elevation fetch) is:
    //   (1) SKIPPED entirely while the camera is panning/zooming/rotating, so it
    //       can never block camera movement, and
    //   (2) THROTTLED (~150ms) when hovering still.
    const onMove = (e: maplibregl.MapMouseEvent) => {
      const lng = e.lngLat.lng
      const lat = e.lngLat.lat
      const x = e.point.x
      const y = e.point.y
      const last = hoverStateRef.current

      // Instant, cheap update so the tooltip follows the cursor smoothly.
      setHoverPosition({
        lng,
        lat,
        features: last?.features ?? [],
        elevation: elevRef.current,
        x,
        y,
      })

      // Don't run expensive queries while the camera is moving (drag/zoom/rotate).
      if (map.isMoving() || map.isZooming() || map.isRotating()) return

      const now = performance.now()
      if (now - lastExpensiveRef.current < 150) return
      lastExpensiveRef.current = now
      const token = ++expensiveTokenRef.current

      // Expensive: query the rendered OSM features for this position.
      const features = collectHoverFeatures(
        map.queryRenderedFeatures(e.point) as Array<{
          layer?: { id?: string }
          properties?: Record<string, unknown>
        }>,
      )
      hoverStateRef.current = { lng, lat, features, x, y }

      // Backend COG elevation sample for the current pointer position.
      fetchElevation(lng, lat).then((elev) => {
        if (token !== expensiveTokenRef.current) return // superseded by a newer move
        elevRef.current = elev
        const hs = hoverStateRef.current
        if (hs && hs.lng === lng && hs.lat === lat) {
          setHoverPosition({ ...hs, elevation: elev })
        }
      })
    }
    const onLeave = () => {
      setHoverPosition(null)
      hoverStateRef.current = null
      elevRef.current = null
      expensiveTokenRef.current++ // invalidate any in-flight fetch/query
    }
    map.on('mousemove', onMove)
    map.on('mouseleave', onLeave)

    return () => {
      map.off('mousemove', onMove)
      map.off('mouseleave', onLeave)
      map.remove()
      mapRef.current = null
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

  // Live directional cone preview (native MapLibre layer), recomputed as params change.
  useEffect(() => {
    updateCone()
  }, [searchMode, observerLat, observerLng, radiusKm, azimuth, fov, panoramicMode])

  // The finalized search area drawn by the user (native MapLibre layer).
  useEffect(() => {
    updateSearch()
  }, [searchPolygon])

  // Live draft of vertices while drawing the search area (native MapLibre layer).
  useEffect(() => {
    updateDraft()
  }, [searchMode, draftVertices])

  // Scored viewshed results (native MapLibre circle layer). Point and area modes
  // both produce the same scored GeoJSON, so only this single layer is needed.
  useEffect(() => {
    updateResult()
  }, [resultGeoJSON, legendVisibility])

  function finishArea() {
    if (draftVertices.length < 3) return
    setSearchPolygon(buildPolygonFeature(draftVertices))
    clearDraft()
  }

  // Clear removes both the finalized search polygon and any in-progress draft.
  function clearArea() {
    setSearchPolygon(null)
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
            onClick={clearArea}
            className="rounded bg-zinc-200 px-2.5 py-1 text-xs font-semibold text-zinc-700 hover:bg-zinc-300"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}
