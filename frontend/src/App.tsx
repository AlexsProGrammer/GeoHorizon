import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [health, setHealth] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((data) => setHealth(JSON.stringify(data)))
      .catch((err) => setHealth(`error: ${String(err)}`))
  }, [])

  return (
    <div className="App">
      <h1>GeoHorizon</h1>
      <p>Backend health: {health ?? 'checking...'}</p>
    </div>
  )
}

export default App
