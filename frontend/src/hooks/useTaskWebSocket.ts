import { useEffect, useRef } from 'react'
import { useMapStore, type TaskResult, type ViewshedStatus } from '../store/useMapStore'
import { fetchTaskResult, getTaskStatus } from '../services/api'

// The WebSocket endpoint is served directly by the API (not through the Vite
// proxy), so it connects straight to the backend on localhost:8000.
const WS_URL = 'ws://localhost:8000/ws/progress'

// If the WebSocket misses the final frame (e.g. the worker fails before the
// client is subscribed, or the ws connection drops), poll the task state so the
// UI still stops and shows the error.
const POLL_INTERVAL_MS = 1500

interface ProgressFrame {
  task_id?: string
  status: string
  progress?: number
  step?: string
  message?: string
}

export function useTaskWebSocket() {
  const taskId = useMapStore((s) => s.taskId)
  const setProgress = useMapStore((s) => s.setProgress)
  const setResultGeoJSON = useMapStore((s) => s.setResultGeoJSON)
  const resetResult = useMapStore((s) => s.resetResult)
  const setError = useMapStore((s) => s.setError)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!taskId) return

    // Clear any previous overlay / error before starting a new task.
    resetResult()
    setError(null)

    let terminated = false
    let pollId: number | undefined

    const stopPolling = () => {
      if (pollId !== undefined) window.clearInterval(pollId)
      pollId = undefined
    }

    // Finalize the task. Only the first terminal event wins; afterwards the
    // spinner stops and, on failure, the error message is shown.
    const finish = (status: ViewshedStatus, message: string) => {
      if (terminated) return
      terminated = true
      stopPolling()
      setError(status === 'FAILURE' ? message : null)
      resetResult()
      setProgress(0, status, message)
    }

    const ws = new WebSocket(`${WS_URL}/${taskId}`)
    wsRef.current = ws

    ws.onmessage = async (event) => {
      let data: ProgressFrame
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }

      const status = data.status
      const step = data.step ?? ''
      const progress = typeof data.progress === 'number' ? data.progress : 0
      const message = data.message ?? ''

      if (status === 'SUCCESS') {
        if (terminated) return
        terminated = true
        stopPolling()
        setError(null)
        setProgress(100, 'SUCCESS', step || 'Complete')
        await fetchResult(taskId, setResultGeoJSON)
      } else if (status === 'CANCELLED') {
        finish('CANCELLED', message || 'Calculation cancelled')
      } else if (status === 'FAILURE') {
        finish('FAILURE', message || 'Calculation failed')
      } else {
        setProgress(progress, status as ViewshedStatus, step)
      }
    }

    ws.onerror = () => {
      // The connection dropped — don't finalize blindly; let the status poll
      // below determine the actual outcome.
    }

    // Fallback: poll the Celery result state. Catches worker crashes, task
    // failures that happened before the WS subscribed, and missed frames.
    pollId = window.setInterval(async () => {
      let status: { state: string; error: string | null }
      try {
        status = await getTaskStatus(taskId)
      } catch {
        return // API unreachable; keep waiting
      }

      if (status.state === 'FAILURE' || status.state === 'REVOKED') {
        finish('FAILURE', status.error || 'Calculation failed on the server')
      } else if (status.state === 'SUCCESS' && !terminated) {
        terminated = true
        stopPolling()
        setError(null)
        setProgress(100, 'SUCCESS', 'Complete')
        await fetchResult(taskId, setResultGeoJSON)
      }
    }, POLL_INTERVAL_MS)

    return () => {
      stopPolling()
      ws.close()
      wsRef.current = null
    }
  }, [taskId, setProgress, setResultGeoJSON, resetResult, setError])

  return wsRef
}

async function fetchResult(
  taskId: string,
  setResultGeoJSON: (geojson: TaskResult | null) => void,
) {
  try {
    const fc = await fetchTaskResult(taskId)
    setResultGeoJSON(fc)
  } catch {
    // ignore network/image errors
  }
}
