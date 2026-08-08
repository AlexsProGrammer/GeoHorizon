import { useEffect, useRef } from 'react'
import { useMapStore, type ViewshedStatus } from '../store/useMapStore'
import { getResultImageUrl } from '../services/api'

// The WebSocket endpoint is served directly by the API (not through the Vite
// proxy), so it connects straight to the backend on localhost:8000.
const WS_URL = 'ws://localhost:8000/ws/progress'

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
  const setResult = useMapStore((s) => s.setResult)
  const resetResult = useMapStore((s) => s.resetResult)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!taskId) return

    // Clear any previous overlay before starting a new task.
    resetResult()

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

      if (status === 'SUCCESS') {
        setProgress(100, 'SUCCESS', step || 'Complete')
        await fetchResult(taskId, setResult)
      } else if (status === 'CANCELLED') {
        resetResult()
        setProgress(0, 'CANCELLED', data.message || 'Cancelled')
      } else if (status === 'FAILURE') {
        resetResult()
        setProgress(0, 'FAILURE', data.message || 'Failed')
      } else {
        setProgress(progress, status as ViewshedStatus, step)
      }
    }

    ws.onerror = () => {
      setProgress(0, 'FAILURE', 'WebSocket connection error')
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [taskId, setProgress, setResult, resetResult])

  return wsRef
}

async function fetchResult(
  taskId: string,
  setResult: (imageUrl: string, bbox: [number, number, number, number]) => void,
) {
  try {
    const res = await fetch(getResultImageUrl(taskId))
    if (!res.ok) return
    const bbox = JSON.parse(res.headers.get('X-Bounds') ?? '[]') as [number, number, number, number]
    if (bbox.length !== 4) return
    const blobUrl = URL.createObjectURL(await res.blob())
    setResult(blobUrl, bbox)
  } catch {
    // ignore network/image errors
  }
}
