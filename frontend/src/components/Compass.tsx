import { useEffect, useState } from 'react'
import type maplibregl from 'maplibre-gl'

type MapRef = React.MutableRefObject<maplibregl.Map | null>

export default function Compass({ mapRef }: { mapRef: MapRef }) {
  const [bearing, setBearing] = useState(0)

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const update = () => setBearing(map.getBearing())
    update()
    map.on('rotate', update)
    map.on('moveend', update)
    return () => {
      map.off('rotate', update)
      map.off('moveend', update)
    }
  }, [mapRef])

  function resetNorth() {
    mapRef.current?.easeTo({ bearing: 0, duration: 400 })
  }

  // Rotate the compass rose opposite the bearing so N points to true north.
  const rotation = -bearing
  const isNorth = Math.abs(((bearing % 360) + 360) % 360) < 0.5

  return (
    <button
      onClick={resetNorth}
      title={isNorth ? 'Click to reset north' : 'North — click to snap back to north'}
      aria-label="Reset view to north"
      className="pointer-events-auto absolute right-3 top-3 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/95 shadow-lg transition-shadow hover:shadow-xl"
    >
      <div
        className="relative h-9 w-9 rounded-full"
        style={{ transform: `rotate(${rotation}deg)`, transition: 'transform 0.2s ease' }}
      >
        <span className="absolute left-1/2 top-0 -translate-x-1/2 text-[11px] font-bold leading-none text-red-600">
          N
        </span>
        <span className="absolute bottom-0 left-1/2 -translate-x-1/2 text-[10px] font-semibold leading-none text-zinc-500">
          S
        </span>
        <span className="absolute left-0 top-1/2 -translate-y-1/2 text-[10px] font-semibold leading-none text-zinc-400">
          W
        </span>
        <span className="absolute right-0 top-1/2 -translate-y-1/2 text-[10px] font-semibold leading-none text-zinc-400">
          E
        </span>
        <div className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-zinc-800" />
      </div>
    </button>
  )
}