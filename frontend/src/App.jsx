import { useEffect } from 'react'
import Header from './components/Header'
import ModeSelector from './components/ModeSelector'
import ConfigPanel from './components/ConfigPanel'
import StatusPanel from './components/StatusPanel'
import PersonalityPanel from './components/PersonalityPanel'
import ActivityLog from './components/ActivityLog'
import useWebSocket from './hooks/useWebSocket'
import useStreamBuddyStore from './store/useStreamBuddyStore'
import { streamBuddyAPI } from './services/api'

function App() {
  // Initialize WebSocket connection
  useWebSocket()
  
  const { setSessionData } = useStreamBuddyStore()
  
  // Load initial status
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
  
  return (
    <div className="min-h-screen p-4">
      <div className="max-w-6xl mx-auto space-y-4">
        {/* Header */}
        <Header />
        
        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left: Configuration */}
          <div className="card">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
              <span>🎬</span>
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
      </div>
    </div>
  )
}

export default App
