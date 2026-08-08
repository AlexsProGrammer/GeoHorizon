import { useEffect, useMemo, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { Protocol } from 'pmtiles'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { BitmapLayer, GeoJsonLayer } from '@deck.gl/layers'
import { useMapStore } from '../store/useMapStore'
import { buildConePolygon } from '../services/geometry'

// Register the pmtiles:// protocol handler for MapLibre once.
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

// Default view centered on the imported Oberbayern / Traunreut area.
const DEFAULT_CENTER: [number, number] = [12.65, 47.95]

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)

  const observerLat = useMapStore((s) => s.observerLat)
  const observerLng = useMapStore((s) => s.observerLng)
  const radiusKm = useMapStore((s) => s.radiusKm)
  const azimuth = useMapStore((s) => s.azimuth)
  const fov = useMapStore((s) => s.fov)
  const setObserver = useMapStore((s) => s.setObserver)
  const resultImageUrl = useMapStore((s) => s.resultImageUrl)
  const resultBbox = useMapStore((s) => s.resultBbox)

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

    map.on('click', (e) => {
      setObserver(e.lngLat.lat, e.lngLat.lng)
    })

    const overlay = new MapboxOverlay({ interleaved: true })
    overlayRef.current = overlay
    map.addControl(overlay)

    return () => {
      map.remove()
      mapRef.current = null
      overlayRef.current = null
    }
  }, [setObserver])

  // Live directional cone preview, recomputed as parameters change.
  const coneLayer = useMemo(() => {
    if (observerLat == null || observerLng == null) return null
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
  }, [observerLat, observerLng, radiusKm, azimuth, fov])

  // Hardware-accelerated viewshed result overlay.
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

  const layers = useMemo(
    () => [coneLayer, viewshedLayer].filter((l): l is NonNullable<typeof l> => l != null),
    [coneLayer, viewshedLayer],
  )

  // Push the current layers into the Deck.gl overlay whenever they change.
  useEffect(() => {
    overlayRef.current?.setProps({ layers })
  }, [layers])

  return <div ref={containerRef} className="h-full w-full" />
}
