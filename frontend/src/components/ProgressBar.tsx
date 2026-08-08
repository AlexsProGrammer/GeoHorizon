import { AlertTriangle, Loader2, X } from 'lucide-react'
import { useMapStore, type ViewshedStatus } from '../store/useMapStore'

const ACTIVE_STATUSES: ViewshedStatus[] = [
  'STARTED',
  'CONNECTED',
  'FETCHING_DEM',
  'BUILDING_DSM',
  'COMPUTING_VIEWSHED',
  'APPLYING_CONE',
]

export default function ProgressBar() {
  const progress = useMapStore((s) => s.progress)
  const status = useMapStore((s) => s.status)
  const step = useMapStore((s) => s.step)
  const errorMessage = useMapStore((s) => s.errorMessage)
  const resetTask = useMapStore((s) => s.resetTask)

  const isActive = ACTIVE_STATUSES.includes(status)
  const isError = status === 'FAILURE'
  const isCancelled = status === 'CANCELLED'
  const isDone = status === 'SUCCESS'

  // Nothing worth showing while idle.
  if (status === 'IDLE') return null

  return (
    <div
      className={`pointer-events-auto absolute left-1/2 top-4 z-10 w-96 -translate-x-1/2 rounded-lg border p-3 shadow-lg backdrop-blur ${
        isError
          ? 'border-red-300 bg-red-50/95'
          : isCancelled
            ? 'border-amber-300 bg-amber-50/95'
            : 'border-zinc-200 bg-white/90'
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span
          className={`flex items-center gap-2 text-sm font-medium ${
            isError ? 'text-red-700' : isCancelled ? 'text-amber-700' : 'text-zinc-700'
          }`}
        >
          {isError ? (
            <AlertTriangle size={16} />
          ) : isActive ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Loader2 size={16} />
          )}
          {isError ? 'Calculation failed' : isCancelled ? 'Cancelled' : step || status}
        </span>
        {!isError && <span className="text-sm font-semibold text-zinc-800">{progress}%</span>}
        <button
          onClick={resetTask}
          aria-label="Dismiss"
          className="ml-auto rounded p-1 text-zinc-500 hover:bg-zinc-200/60 hover:text-zinc-800"
        >
          <X size={14} />
        </button>
      </div>

      {isError && errorMessage && (
        <p className="mb-2 rounded bg-red-100 px-2 py-1.5 text-xs leading-snug text-red-700 break-words">
          {errorMessage}
        </p>
      )}
      {isCancelled && <p className="mb-2 text-xs text-amber-700">The calculation was cancelled.</p>}

      {!isError && !isCancelled && (
        <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200">
          <div
            className={`h-full rounded-full transition-all duration-300 ${isDone ? 'bg-emerald-500' : 'bg-emerald-500'}`}
            style={{ width: `${isDone ? 100 : progress}%` }}
          />
        </div>
      )}
    </div>
  )
}
