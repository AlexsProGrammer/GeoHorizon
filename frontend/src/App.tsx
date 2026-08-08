import Sidebar from './components/Sidebar'
import MapView from './components/MapView'
import ProgressBar from './components/ProgressBar'
import { useTaskWebSocket } from './hooks/useTaskWebSocket'
import { useMapStore } from './store/useMapStore'

export default function App() {
  useTaskWebSocket()
  const status = useMapStore((s) => s.status)
  const showProgress = status !== 'IDLE'

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-100 text-zinc-900">
      <Sidebar />
      <div className="relative flex-1">
        <MapView />
        {showProgress && <ProgressBar />}
      </div>
    </div>
  )
}
