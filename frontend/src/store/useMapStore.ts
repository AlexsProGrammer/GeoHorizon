import { create } from 'zustand'
import { fetchCogBounds, type CogInfo } from '../services/api'
import type { Feature, FeatureCollection, Polygon } from 'geojson'

export type ViewshedStatus =
  | 'IDLE'
  | 'STARTED'
  | 'CONNECTED'
  | 'FETCHING_DEM'
  | 'BUILDING_DSM'
  | 'COMPUTING_VIEWSHED'
  | 'APPLYING_CONE'
  | 'PREPARING_AREA'
  | 'SAMPLING'
  | 'CALCULATING'
  | 'SUCCESS'
  | 'CANCELLED'
  | 'FAILURE'

export type SearchMode = 'point' | 'area'

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

  // Area search state
  searchMode: SearchMode
  searchPolygon: Feature<Polygon> | null
  draftVertices: [number, number][]
  gridStepM: number
  resultGeoJSON: FeatureCollection | null

  // Available COGs (from /api/viewshed/bounds)
  selectedCog: string | null
  availableCogs: CogInfo[]

  // Task state
  taskId: string | null
  progress: number
  status: ViewshedStatus
  step: string
  errorMessage: string | null

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
  setSearchMode: (mode: SearchMode) => void
  setSearchPolygon: (polygon: Feature<Polygon> | null) => void
  addDraftVertex: (lngLat: [number, number]) => void
  clearDraft: () => void
  setGridStep: (m: number) => void
  setResultGeoJSON: (geojson: FeatureCollection | null) => void
  setCog: (path: string) => void
  setTaskId: (id: string | null) => void
  setProgress: (progress: number, status: ViewshedStatus, step: string) => void
  setError: (message: string | null) => void
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

  searchMode: 'point',
  searchPolygon: null,
  draftVertices: [],
  gridStepM: 50,
  resultGeoJSON: null,

  selectedCog: null,
  availableCogs: [],

  taskId: null,
  progress: 0,
  status: 'IDLE',
  step: '',
  errorMessage: null,

  resultImageUrl: null,
  resultBbox: null,

  setObserver: (lat, lng) => set({ observerLat: lat, observerLng: lng }),
  setRadius: (radiusKm) => set({ radiusKm }),
  setAzimuth: (azimuth) => set({ azimuth }),
  setFov: (fov) => set({ fov }),
  setTreeOffset: (treeOffset) => set({ treeOffset }),
  setBuildingOffset: (buildingOffset) => set({ buildingOffset }),
  setObserverHeight: (observerHeight) => set({ observerHeight }),
  setSearchMode: (searchMode) =>
    set({ searchMode, searchPolygon: null, draftVertices: [], resultGeoJSON: null }),
  setSearchPolygon: (searchPolygon) => set({ searchPolygon }),
  addDraftVertex: (lngLat) =>
    set((state) => ({
      draftVertices: state.draftVertices.some(
        (v) => v[0] === lngLat[0] && v[1] === lngLat[1],
      )
        ? state.draftVertices
        : [...state.draftVertices, lngLat],
    })),
  clearDraft: () => set({ draftVertices: [] }),
  setGridStep: (gridStepM) => set({ gridStepM }),
  setResultGeoJSON: (resultGeoJSON) => set({ resultGeoJSON }),
  setCog: (selectedCog) => set({ selectedCog }),
  setTaskId: (taskId) => set({ taskId }),
  setProgress: (progress, status, step) => set({ progress, status, step }),
  setError: (errorMessage) => set({ errorMessage }),
  setResult: (resultImageUrl, resultBbox) =>
    set((state) => {
      if (state.resultImageUrl && state.resultImageUrl !== resultImageUrl) {
        URL.revokeObjectURL(state.resultImageUrl)
      }
      return { resultImageUrl, resultBbox }
    }),
  resetTask: () =>
    set({ taskId: null, progress: 0, status: 'IDLE', step: '', errorMessage: null }),
  resetResult: () =>
    set((state) => {
      if (state.resultImageUrl) {
        URL.revokeObjectURL(state.resultImageUrl)
      }
      return { resultImageUrl: null, resultBbox: null, resultGeoJSON: null }
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
