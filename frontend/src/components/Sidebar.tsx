import { useEffect } from 'react'
import { Ban, Crosshair, Map as MapIcon, MapPin, Mountain, Play } from 'lucide-react'
import { useMapStore, type ViewshedStatus } from '../store/useMapStore'
import { cancelViewshed, startAreaSearch } from '../services/api'
import { buildCirclePolygon } from '../services/geometry'
import Legend from './Legend'

const ACTIVE_STATUSES: ViewshedStatus[] = [
  'STARTED',
  'CONNECTED',
  'FETCHING_DEM',
  'BUILDING_DSM',
  'COMPUTING_VIEWSHED',
  'APPLYING_CONE',
  'PREPARING_AREA',
  'SAMPLING',
  'CALCULATING',
]

export default function Sidebar() {
  const observerLat = useMapStore((s) => s.observerLat)
  const observerLng = useMapStore((s) => s.observerLng)
  const searchMode = useMapStore((s) => s.searchMode)
  const searchPolygon = useMapStore((s) => s.searchPolygon)
  const gridStepM = useMapStore((s) => s.gridStepM)
  const estimatedPointCount = useMapStore((s) => s.estimatedPointCount)
  const radiusKm = useMapStore((s) => s.radiusKm)
  const azimuth = useMapStore((s) => s.azimuth)
  const fov = useMapStore((s) => s.fov)
  const panoramicMode = useMapStore((s) => s.panoramicMode)
  const treeOffset = useMapStore((s) => s.treeOffset)
  const buildingOffset = useMapStore((s) => s.buildingOffset)
  const observerHeight = useMapStore((s) => s.observerHeight)
  const horizonEnabled = useMapStore((s) => s.horizonEnabled)
  const selectedCog = useMapStore((s) => s.selectedCog)
  const availableCogs = useMapStore((s) => s.availableCogs)
  const taskId = useMapStore((s) => s.taskId)
  const status = useMapStore((s) => s.status)
  const resultGeoJSON = useMapStore((s) => s.resultGeoJSON)

  const setRadius = useMapStore((s) => s.setRadius)
  const setAzimuth = useMapStore((s) => s.setAzimuth)
  const setFov = useMapStore((s) => s.setFov)
  const setPanoramicMode = useMapStore((s) => s.setPanoramicMode)
  const setTreeOffset = useMapStore((s) => s.setTreeOffset)
  const setBuildingOffset = useMapStore((s) => s.setBuildingOffset)
  const setObserverHeight = useMapStore((s) => s.setObserverHeight)
  const setHorizonEnabled = useMapStore((s) => s.setHorizonEnabled)
  const setSearchMode = useMapStore((s) => s.setSearchMode)
  const setGridStep = useMapStore((s) => s.setGridStep)
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
    !!selectedCog &&
    !isProcessing &&
    (searchMode === 'point'
      ? observerLat != null && observerLng != null
      : searchPolygon != null)

  async function handleCalculate() {
    if (!canCalculate || !selectedCog) return
    resetResult()
    setError(null)
    setProgress(0, 'STARTED', 'Dispatching task...')
    const effectiveFov = panoramicMode ? 360 : fov
    try {
      let task_id: string
      if (searchMode === 'area' && searchPolygon) {
        const res = await startAreaSearch({
          cog_path: selectedCog,
          search_area: searchPolygon.geometry,
          radius_km: radiusKm,
          azimuth,
          fov: effectiveFov,
          grid_step_m: gridStepM,
          observer_height: observerHeight,
          tree_height: treeOffset,
          building_height: buildingOffset,
          horizon_enabled: horizonEnabled,
        })
        task_id = res.task_id
      } else if (observerLat != null && observerLng != null) {
        // Point mode: wrap the observer in a circular search area and run the
        // same multi-point polygon engine as area mode (unified result format).
        const circle = buildCirclePolygon(observerLng, observerLat, radiusKm)
        const res = await startAreaSearch({
          cog_path: selectedCog,
          search_area: circle.geometry,
          radius_km: radiusKm,
          azimuth,
          fov: effectiveFov,
          grid_step_m: gridStepM,
          observer_height: observerHeight,
          tree_height: treeOffset,
          building_height: buildingOffset,
          horizon_enabled: horizonEnabled,
        })
        task_id = res.task_id
      } else {
        return
      }
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
        <h2 className="mb-2 text-sm font-semibold text-zinc-700">Analysis Mode</h2>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-zinc-100 p-1">
          <button
            onClick={() => setSearchMode('point')}
            className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
              searchMode === 'point'
                ? 'bg-white text-emerald-700 shadow-sm'
                : 'text-zinc-600 hover:text-zinc-900'
            }`}
          >
            <Crosshair size={15} /> Point
          </button>
          <button
            onClick={() => setSearchMode('area')}
            className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
              searchMode === 'area'
                ? 'bg-white text-emerald-700 shadow-sm'
                : 'text-zinc-600 hover:text-zinc-900'
            }`}
          >
            <MapIcon size={15} /> Area
          </button>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-700">View Direction</h2>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-zinc-100 p-1">
          <button
            onClick={() => setPanoramicMode(true)}
            className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
              panoramicMode
                ? 'bg-white text-emerald-700 shadow-sm'
                : 'text-zinc-600 hover:text-zinc-900'
            }`}
          >
            360° Panoramic
          </button>
          <button
            onClick={() => setPanoramicMode(false)}
            className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
              !panoramicMode
                ? 'bg-white text-emerald-700 shadow-sm'
                : 'text-zinc-600 hover:text-zinc-900'
            }`}
          >
            Directional
          </button>
        </div>
      </section>

      <section>
        <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-zinc-700">
          {searchMode === 'point' ? (
            <>
              <MapPin size={16} className="text-zinc-500" /> Observer Position
            </>
          ) : (
            <>
              <MapIcon size={16} className="text-zinc-500" /> Search Area
            </>
          )}
        </h2>
        {searchMode === 'point' ? (
          observerLat != null && observerLng != null ? (
            <p className="text-sm text-zinc-600">
              {observerLat.toFixed(5)}, {observerLng.toFixed(5)}
            </p>
          ) : (
            <p className="text-sm text-zinc-500">Click on the map to set the observer position.</p>
          )
        ) : searchPolygon ? (
          <p className="text-sm text-zinc-600">Area ready — calculate to find the best views.</p>
        ) : (
          <p className="text-sm text-zinc-500">
            Draw a polygon on the map, then click “Finish area”.
          </p>
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
      {!panoramicMode && (
        <>
          <Slider label="Azimuth" value={azimuth} display={`${azimuth}°`} min={0} max={359} step={1} onChange={setAzimuth} />
          <Slider
            label="Field of View"
            value={fov}
            display={`${fov}°`}
            min={10}
            max={360}
            step={5}
            onChange={setFov}
          />
        </>
      )}
      {searchMode === 'area' && (
        <section>
          <Slider
            label="Grid Step"
            value={gridStepM}
            display={`${gridStepM} m`}
            min={10}
            max={500}
            step={10}
            onChange={setGridStep}
          />
          <p className="mt-1 flex items-center justify-between text-xs text-zinc-500">
            <span>≈ {estimatedPointCount.toLocaleString()} points</span>
            {gridStepM > 0 && (
              <span>Density: {Math.round(1_000_000 / (gridStepM * gridStepM)).toLocaleString()} pts/km²</span>
            )}
          </p>
        </section>
      )}
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

      <section className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={horizonEnabled}
          onChange={(e) => setHorizonEnabled(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-emerald-600"
        />
        <label className="text-sm text-zinc-700">
          <span className="font-semibold">Horizon check (100 km)</span>
          <span className="block text-xs font-normal text-zinc-500">
            Casts long rays to verify no distant mountains block the view.
          </span>
        </label>
      </section>

      {resultGeoJSON && <Legend />}

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
          <Play size={16} /> {searchMode === 'area' ? 'Search Area' : 'Calculate'}
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
