import { create } from 'zustand'
import { fetchCogBounds, type CogInfo } from '../services/api'

export type ViewshedStatus =
  | 'IDLE'
  | 'STARTED'
  | 'CONNECTED'
  | 'FETCHING_DEM'
  | 'BUILDING_DSM'
  | 'COMPUTING_VIEWSHED'
  | 'APPLYING_CONE'
  | 'SUCCESS'
  | 'CANCELLED'
  | 'FAILURE'

interface MapState {
  // Observer position (set by map click)
  observerLat: number | null
  observerLng: number | null

  // Viewshed parameters
  radiusKm: number
  azimuth: number
  fov: number
  treeOffset: number
  buildingOffset: number
  observerHeight: number

  // Available COGs (from /api/viewshed/bounds)
  selectedCog: string | null
  availableCogs: CogInfo[]

  // Task state
  taskId: string | null
  progress: number
  status: ViewshedStatus
  step: string

  // Result (PNG overlay + its geographic bounding box)
  resultImageUrl: string | null
  resultBbox: [number, number, number, number] | null

  // Actions
  setObserver: (lat: number, lng: number) => void
  setRadius: (km: number) => void
  setAzimuth: (deg: number) => void
  setFov: (deg: number) => void
  setTreeOffset: (m: number) => void
  setBuildingOffset: (m: number) => void
  setObserverHeight: (m: number) => void
  setCog: (path: string) => void
  setTaskId: (id: string | null) => void
  setProgress: (progress: number, status: ViewshedStatus, step: string) => void
  setResult: (imageUrl: string, bbox: [number, number, number, number]) => void
  resetTask: () => void
  resetResult: () => void
  fetchAvailableCogs: () => Promise<void>
}

export const useMapStore = create<MapState>((set) => ({
  observerLat: null,
  observerLng: null,

  radiusKm: 10,
  azimuth: 270,
  fov: 40,
  treeOffset: 30,
  buildingOffset: 15,
  observerHeight: 1.8,

  selectedCog: null,
  availableCogs: [],

  taskId: null,
  progress: 0,
  status: 'IDLE',
  step: '',

  resultImageUrl: null,
  resultBbox: null,

  setObserver: (lat, lng) => set({ observerLat: lat, observerLng: lng }),
  setRadius: (radiusKm) => set({ radiusKm }),
  setAzimuth: (azimuth) => set({ azimuth }),
  setFov: (fov) => set({ fov }),
  setTreeOffset: (treeOffset) => set({ treeOffset }),
  setBuildingOffset: (buildingOffset) => set({ buildingOffset }),
  setObserverHeight: (observerHeight) => set({ observerHeight }),
  setCog: (selectedCog) => set({ selectedCog }),
  setTaskId: (taskId) => set({ taskId }),
  setProgress: (progress, status, step) => set({ progress, status, step }),
  setResult: (resultImageUrl, resultBbox) =>
    set((state) => {
      if (state.resultImageUrl && state.resultImageUrl !== resultImageUrl) {
        URL.revokeObjectURL(state.resultImageUrl)
      }
      return { resultImageUrl, resultBbox }
    }),
  resetTask: () => set({ taskId: null, progress: 0, status: 'IDLE', step: '' }),
  resetResult: () =>
    set((state) => {
      if (state.resultImageUrl) {
        URL.revokeObjectURL(state.resultImageUrl)
      }
      return { resultImageUrl: null, resultBbox: null }
    }),
  fetchAvailableCogs: async () => {
    try {
      const cogs = await fetchCogBounds()
      set({ availableCogs: cogs, selectedCog: cogs[0]?.path ?? null })
    } catch {
      set({ availableCogs: [] })
    }
  },
}))
