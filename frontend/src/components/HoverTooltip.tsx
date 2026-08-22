import { useMapStore } from '../store/useMapStore'

const ELEVATION_STEP = 5

export default function HoverTooltip() {
  const hover = useMapStore((s) => s.hoverPosition)
  if (!hover) return null

  return (
    <div
      className="pointer-events-none absolute z-20 max-w-[240px] rounded-md border border-zinc-300 bg-white/95 px-2.5 py-1.5 text-xs shadow-lg"
      style={{
        left: Math.min(hover.x + 12, window.innerWidth - 260),
        top: hover.y + 14,
      }}
    >
      <div className="font-medium text-zinc-800">
        {hover.lat.toFixed(5)}, {hover.lng.toFixed(5)}
      </div>
      {hover.elevation != null && (
        <div className="text-zinc-600">
          Elevation:{' '}
          {Math.round(hover.elevation / ELEVATION_STEP) * ELEVATION_STEP} m
        </div>
      )}
      {hover.state && (
        <div className="text-zinc-600 capitalize">State: {hover.state}</div>
      )}
      {hover.distanceM != null && (
        <div className="text-zinc-600">Distance: {hover.distanceM.toFixed(0)} m</div>
      )}
      {hover.azimuth != null && (
        <div className="text-zinc-600">Azimuth: {hover.azimuth.toFixed(0)}°</div>
      )}
      {hover.clearanceM != null && (
        <div className="text-zinc-600">Clearance: {hover.clearanceM.toFixed(1)} m</div>
      )}
      {hover.features.length > 0 && (
        <div className="text-zinc-600">{hover.features.join(' · ')}</div>
      )}
    </div>
  )
}