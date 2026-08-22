import { useMapStore, type LegendColor } from '../store/useMapStore'

const POINT_ROWS: { key: LegendColor; label: string; color: string }[] = [
  { key: 'green', label: 'Clear', color: '#22c55e' },
  { key: 'yellow', label: 'Grazing', color: '#eab308' },
  { key: 'red', label: 'Blocked', color: '#ef4444' },
]

const AREA_ROWS: { key: LegendColor; label: string; color: string }[] = [
  { key: 'green', label: 'Excellent (70–100%)', color: '#22c55e' },
  { key: 'yellow', label: 'Moderate (30–70%)', color: '#eab308' },
  { key: 'red', label: 'Poor (0–30%)', color: '#ef4444' },
]

export default function Legend() {
  const searchMode = useMapStore((s) => s.searchMode)
  const legendVisibility = useMapStore((s) => s.legendVisibility)
  const toggleLegendColor = useMapStore((s) => s.toggleLegendColor)
  const rows = searchMode === 'point' ? POINT_ROWS : AREA_ROWS

  return (
    <section className="rounded-lg border border-zinc-200 bg-zinc-50 p-3">
      <h2 className="mb-2 text-sm font-semibold text-zinc-700">
        Legend — {searchMode === 'point' ? 'Line of Sight' : 'View Quality'}
      </h2>
      <div className="flex flex-col gap-1.5">
        {rows.map((row) => {
          const enabled = legendVisibility[row.key]
          return (
            <label
              key={row.key}
              className="flex cursor-pointer items-center gap-2.5 text-sm text-zinc-800"
            >
              <input
                type="checkbox"
                checked={enabled}
                onChange={() => toggleLegendColor(row.key)}
                className="h-4 w-4 accent-emerald-600"
              />
              <span
                className="h-3 w-3 shrink-0 rounded-sm ring-1 ring-black/10"
                style={{ backgroundColor: row.color, opacity: enabled ? 1 : 0.25 }}
              />
              <span className={enabled ? '' : 'text-zinc-400'}>{row.label}</span>
            </label>
          )
        })}
      </div>
    </section>
  )
}
