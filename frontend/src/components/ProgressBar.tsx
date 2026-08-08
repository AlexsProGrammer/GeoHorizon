import { Loader2 } from 'lucide-react'
import { useMapStore } from '../store/useMapStore'

export default function ProgressBar() {
  const progress = useMapStore((s) => s.progress)
  const status = useMapStore((s) => s.status)
  const step = useMapStore((s) => s.step)

  const isError = status === 'FAILURE' || status === 'CANCELLED'

  return (
    <div className="pointer-events-none absolute left-1/2 top-4 z-10 w-96 -translate-x-1/2 rounded-lg border border-zinc-200 bg-white/90 p-3 shadow-lg backdrop-blur">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium text-zinc-700">
          <Loader2 size={16} className="animate-spin" />
          {step || status}
        </span>
        <span className="text-sm font-semibold text-zinc-800">{progress}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            isError ? 'bg-red-500' : 'bg-emerald-500'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}
