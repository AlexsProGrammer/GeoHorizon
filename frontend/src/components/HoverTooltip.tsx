import { useMapStore } from '../store/useMapStore'

const ELEVATION_STEP = 5

export default function HoverTooltip() {
  const hover = useMapStore((s) => s.hoverPosition)
  if (!hover) return null

  return (
    <div
      className="pointer-events-none absolute z-20 max-w-[220px] rounded-md border border-zinc-300 bg-white/95 px-2.5 py-1.5 text-xs shadow-lg"
      style={{
        left: Math.min(hover.x + 12, window.innerWidth - 240),
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
      {hover.features.length > 0 && (
        <div className="text-zinc-600">{hover.features.join(' · ')}</div>
      )}
    </div>
  )
}