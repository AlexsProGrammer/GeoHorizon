import { useEffect } from 'react'
import { Ban, MapPin, Mountain, Play } from 'lucide-react'
import { useMapStore, type ViewshedStatus } from '../store/useMapStore'
import { cancelViewshed, startViewshed } from '../services/api'

const ACTIVE_STATUSES: ViewshedStatus[] = [
  'STARTED',
  'CONNECTED',
  'FETCHING_DEM',
  'BUILDING_DSM',
  'COMPUTING_VIEWSHED',
  'APPLYING_CONE',
]

export default function Sidebar() {
  const observerLat = useMapStore((s) => s.observerLat)
  const observerLng = useMapStore((s) => s.observerLng)
  const radiusKm = useMapStore((s) => s.radiusKm)
  const azimuth = useMapStore((s) => s.azimuth)
  const fov = useMapStore((s) => s.fov)
  const treeOffset = useMapStore((s) => s.treeOffset)
  const buildingOffset = useMapStore((s) => s.buildingOffset)
  const observerHeight = useMapStore((s) => s.observerHeight)
  const selectedCog = useMapStore((s) => s.selectedCog)
  const availableCogs = useMapStore((s) => s.availableCogs)
  const taskId = useMapStore((s) => s.taskId)
  const status = useMapStore((s) => s.status)

  const setRadius = useMapStore((s) => s.setRadius)
  const setAzimuth = useMapStore((s) => s.setAzimuth)
  const setFov = useMapStore((s) => s.setFov)
  const setTreeOffset = useMapStore((s) => s.setTreeOffset)
  const setBuildingOffset = useMapStore((s) => s.setBuildingOffset)
  const setObserverHeight = useMapStore((s) => s.setObserverHeight)
  const setCog = useMapStore((s) => s.setCog)
  const setTaskId = useMapStore((s) => s.setTaskId)
  const setProgress = useMapStore((s) => s.setProgress)
  const setError = useMapStore((s) => s.setError)
  const resetTask = useMapStore((s) => s.resetTask)
  const resetResult = useMapStore((s) => s.resetResult)
  const fetchAvailableCogs = useMapStore((s) => s.fetchAvailableCogs)

  useEffect(() => {
    fetchAvailableCogs()
  }, [fetchAvailableCogs])

  const isProcessing = ACTIVE_STATUSES.includes(status)
  const canCalculate =
    observerLat != null && observerLng != null && !!selectedCog && !isProcessing

  async function handleCalculate() {
    if (!canCalculate || observerLat == null || observerLng == null || !selectedCog) return
    resetResult()
    setError(null)
    setProgress(0, 'STARTED', 'Dispatching task...')
    try {
      const { task_id } = await startViewshed({
        cog_path: selectedCog,
        lat: observerLat,
        lng: observerLng,
        radius_km: radiusKm,
        azimuth,
        fov,
        observer_height: observerHeight,
        tree_height: treeOffset,
        building_height: buildingOffset,
      })
      setTaskId(task_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setProgress(0, 'FAILURE', 'Failed to start calculation')
      setTaskId(null)
    }
  }

  async function handleCancel() {
    if (!taskId) return
    try {
      await cancelViewshed(taskId)
    } finally {
      resetTask()
      resetResult()
    }
  }

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col gap-5 overflow-y-auto border-r border-zinc-200 bg-white p-4">
      <h1 className="text-2xl font-bold text-zinc-800">HorizonVista</h1>

      <section>
        <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-zinc-700">
          <MapPin size={16} className="text-zinc-500" /> Observer Position
        </h2>
        {observerLat != null && observerLng != null ? (
          <p className="text-sm text-zinc-600">
            {observerLat.toFixed(5)}, {observerLng.toFixed(5)}
          </p>
        ) : (
          <p className="text-sm text-zinc-500">Click on the map to set the observer position.</p>
        )}
      </section>

      <section>
        <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-zinc-700">
          <Mountain size={16} className="text-zinc-500" /> Elevation Dataset
        </h2>
        <select
          value={selectedCog ?? ''}
          onChange={(e) => e.target.value && setCog(e.target.value)}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-800"
        >
          <option value="" disabled>
            {availableCogs.length ? 'Select a COG…' : 'No COGs available'}
          </option>
          {availableCogs.map((cog) => (
            <option key={cog.path} value={cog.path}>
              {cog.name}
            </option>
          ))}
        </select>
      </section>

      <Slider label="Radius" value={radiusKm} display={`${radiusKm} km`} min={1} max={50} step={1} onChange={setRadius} />
      <Slider label="Azimuth" value={azimuth} display={`${azimuth}°`} min={0} max={359} step={1} onChange={setAzimuth} />
      <Slider label="Field of View" value={fov} display={`${fov}°`} min={10} max={360} step={5} onChange={setFov} />
      <Slider label="Tree Offset" value={treeOffset} display={`${treeOffset} m`} min={0} max={100} step={1} onChange={setTreeOffset} />
      <Slider label="Building Offset" value={buildingOffset} display={`${buildingOffset} m`} min={0} max={100} step={1} onChange={setBuildingOffset} />

      <section>
        <label className="mb-1 flex items-center justify-between text-sm font-semibold text-zinc-700">
          <span>Observer Height</span>
          <span className="font-normal text-zinc-500">{observerHeight} m</span>
        </label>
        <input
          type="number"
          value={observerHeight}
          min={0}
          max={500}
          step={0.1}
          onChange={(e) => setObserverHeight(Number(e.target.value))}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-800"
        />
      </section>

      {isProcessing ? (
        <button
          onClick={handleCancel}
          className="flex items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-700"
        >
          <Ban size={16} /> Cancel
        </button>
      ) : (
        <button
          onClick={handleCalculate}
          disabled={!canCalculate}
          className="flex items-center justify-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Play size={16} /> Calculate
        </button>
      )}
    </aside>
  )
}

function Slider({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  display: string
  min: number
  max: number
  step: number
  onChange: (v: number) => void
}) {
  return (
    <section>
      <label className="mb-1 flex items-center justify-between text-sm font-semibold text-zinc-700">
        <span>{label}</span>
        <span className="font-normal text-zinc-500">{display}</span>
      </label>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-emerald-600"
      />
    </section>
  )
}
