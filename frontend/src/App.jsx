import { useEffect } from 'react'
import { Sliders, X } from 'lucide-react'
import Header from './components/Header'
import Footer from './components/Footer'
import ModeSelector from './components/ModeSelector'
import ConfigPanel from './components/ConfigPanel'
import StatusPanel from './components/StatusPanel'
import PersonalityPanel from './components/PersonalityPanel'
import ActivityLog from './components/ActivityLog'
import useWebSocket from './hooks/useWebSocket'
import useStreamBuddyStore from './store/useStreamBuddyStore'
import { streamBuddyAPI } from './services/api'

function App() {
  useWebSocket()
  const { setSessionData, toast, clearToast } = useStreamBuddyStore()

  useEffect(() => {
    const loadStatus = async () => {
      try {
        const status = await streamBuddyAPI.getStatus()
        setSessionData(status)
      } catch (error) {
        console.error('Failed to load status:', error)
      }
    }
    loadStatus()
  }, [setSessionData])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(clearToast, 8000)
    return () => clearTimeout(t)
  }, [toast, clearToast])

  return (
    <div className="relative z-10 min-h-screen p-4">
      {/* Toast for YouTube connection errors etc. */}
      {toast && (
        <div
          role="alert"
          className="fixed top-4 left-1/2 -translate-x-1/2 z-50 max-w-lg w-full mx-4 flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg border border-red-200 bg-red-50 text-red-900"
        >
          <p className="flex-1 text-sm font-medium">{toast.message}</p>
          <button
            type="button"
            onClick={clearToast}
            className="p-1 rounded hover:bg-red-100 text-red-700"
            aria-label="Dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="max-w-6xl mx-auto space-y-4">
        {/* Header */}
        <Header />

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left: Configuration */}
          <div className="card">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
              <Sliders className="w-5 h-5 text-primary-600" />
              <span>Controls</span>
            </h2>

            <ModeSelector />
            <ConfigPanel />
          </div>

          {/* Middle: Status */}
          <StatusPanel />

          {/* Right: Personality */}
          <PersonalityPanel />
        </div>

        {/* Activity Log */}
        <ActivityLog />
        
        {/* Footer */}
        <Footer />
      </div>
    </div>
  )
}

export default App
