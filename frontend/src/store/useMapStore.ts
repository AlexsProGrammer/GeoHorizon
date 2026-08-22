import { create } from 'zustand'
import { fetchCogBounds, type CogInfo } from '../services/api'
import { estimateGridPointCount } from '../services/geometry'
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

export type LegendColor = 'green' | 'yellow' | 'red'

export type TaskResult = FeatureCollection | { samples?: FeatureCollection; [key: string]: unknown }

export interface LegendVisibility {
  green: boolean
  yellow: boolean
  red: boolean
}

export interface HoverInfo {
  lng: number
  lat: number
  elevation: number | null
  features: string[]
  x: number
  y: number
  state?: string | null
  distanceM?: number | null
  azimuth?: number | null
  clearanceM?: number | null
}

interface MapState {
  // Observer position (set by map click)
  observerLat: number | null
  observerLng: number | null

  // Viewshed parameters
  radiusKm: number
  azimuth: number
  fov: number
  pointSpacingM: number
  // When true, the scoring uses a full 360° panoramic sweep (fov treated as 360);
  // when false it uses the configured directional azimuth/FOV cone.
  panoramicMode: boolean
  treeOffset: number
  buildingOffset: number
  observerHeight: number
  horizonEnabled: boolean

  // Area search state
  searchMode: SearchMode
  searchPolygon: Feature<Polygon> | null
  draftVertices: [number, number][]
  gridStepM: number
  estimatedPointCount: number
  resultGeoJSON: TaskResult | null
  legendVisibility: LegendVisibility

  // Available COGs (from /api/viewshed/bounds)
  selectedCog: string | null
  availableCogs: CogInfo[]

  // Task state
  taskId: string | null
  progress: number
  status: ViewshedStatus
  step: string
  errorMessage: string | null

  // Mouse hover info shown in the map tooltip
  hoverPosition: HoverInfo | null

  // Actions
  setObserver: (lat: number | null, lng: number | null) => void
  setRadius: (km: number) => void
  setAzimuth: (deg: number) => void
  setFov: (deg: number) => void
  setPointSpacing: (m: number) => void
  setPanoramicMode: (enabled: boolean) => void
  setTreeOffset: (m: number) => void
  setBuildingOffset: (m: number) => void
  setObserverHeight: (m: number) => void
  setHorizonEnabled: (enabled: boolean) => void
  setSearchMode: (mode: SearchMode) => void
  setSearchPolygon: (polygon: Feature<Polygon> | null) => void
  addDraftVertex: (lngLat: [number, number]) => void
  clearDraft: () => void
  setGridStep: (m: number) => void
  computeEstimatedCount: () => void
  setResultGeoJSON: (geojson: TaskResult | null) => void
  toggleLegendColor: (color: LegendColor) => void
  setCog: (path: string) => void
  setTaskId: (id: string | null) => void
  setProgress: (progress: number, status: ViewshedStatus, step: string) => void
  setError: (message: string | null) => void
  setHoverPosition: (hover: HoverInfo | null) => void
  resetTask: () => void
  resetResult: () => void
  resetAnalysis: () => void
  fetchAvailableCogs: () => Promise<void>
}

export const useMapStore = create<MapState>((set) => ({
  observerLat: null,
  observerLng: null,

  radiusKm: 10,
  azimuth: 270,
  fov: 40,
  pointSpacingM: 50,
  panoramicMode: false,
  treeOffset: 30,
  buildingOffset: 15,
  observerHeight: 1.8,
  horizonEnabled: false,

  searchMode: 'point',
  searchPolygon: null,
  draftVertices: [],
  gridStepM: 50,
  estimatedPointCount: 0,
  resultGeoJSON: null,
  legendVisibility: { green: true, yellow: true, red: true },

  selectedCog: null,
  availableCogs: [],

  taskId: null,
  progress: 0,
  status: 'IDLE',
  step: '',
  errorMessage: null,

  hoverPosition: null,

  setObserver: (lat, lng) => set({ observerLat: lat, observerLng: lng }),
  setRadius: (radiusKm) => set({ radiusKm }),
  setAzimuth: (azimuth) => set({ azimuth }),
  setFov: (fov) => set({ fov }),
  setPointSpacing: (pointSpacingM) => set({ pointSpacingM }),
  setPanoramicMode: (panoramicMode) => set({ panoramicMode }),
  setTreeOffset: (treeOffset) => set({ treeOffset }),
  setBuildingOffset: (buildingOffset) => set({ buildingOffset }),
  setObserverHeight: (observerHeight) => set({ observerHeight }),
  setHorizonEnabled: (horizonEnabled) => set({ horizonEnabled }),
  setSearchMode: (searchMode) =>
    set({ searchMode, searchPolygon: null, draftVertices: [], resultGeoJSON: null, estimatedPointCount: 0 }),
  setSearchPolygon: (searchPolygon) =>
    set((state) => ({
      searchPolygon,
      estimatedPointCount: estimateGridPointCount(searchPolygon, state.gridStepM),
    })),
  addDraftVertex: (lngLat) =>
    set((state) => ({
      draftVertices: state.draftVertices.some(
        (v) => v[0] === lngLat[0] && v[1] === lngLat[1],
      )
        ? state.draftVertices
        : [...state.draftVertices, lngLat],
    })),
  clearDraft: () => set({ draftVertices: [] }),
  setGridStep: (gridStepM) =>
    set((state) => ({
      gridStepM,
      estimatedPointCount: estimateGridPointCount(state.searchPolygon, gridStepM),
    })),
  computeEstimatedCount: () =>
    set((state) => ({
      estimatedPointCount: estimateGridPointCount(state.searchPolygon, state.gridStepM),
    })),
  setResultGeoJSON: (resultGeoJSON) => set({ resultGeoJSON }),
  toggleLegendColor: (color) =>
    set((state) => ({
      legendVisibility: { ...state.legendVisibility, [color]: !state.legendVisibility[color] },
    })),
  setCog: (selectedCog) => set({ selectedCog }),
  setTaskId: (taskId) => set({ taskId }),
  setProgress: (progress, status, step) => set({ progress, status, step }),
  setError: (errorMessage) => set({ errorMessage }),
  resetTask: () =>
    set({ taskId: null, progress: 0, status: 'IDLE', step: '', errorMessage: null }),
  setHoverPosition: (hoverPosition) => set({ hoverPosition }),
  resetResult: () => set({ resultGeoJSON: null }),
  resetAnalysis: () =>
    set({
      observerLat: null,
      observerLng: null,
      searchPolygon: null,
      draftVertices: [],
      resultGeoJSON: null,
      estimatedPointCount: 0,
      taskId: null,
      progress: 0,
      status: 'IDLE',
      step: '',
      errorMessage: null,
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
