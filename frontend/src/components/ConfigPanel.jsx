import { useState } from 'react'
import { Play, Square } from 'lucide-react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'
import { streamBuddyAPI } from '../services/api'

const ConfigPanel = () => {
  const {
    mode,
    config,
    setConfig,
    personality,
    isActive,
    setSessionData,
    clearSession,
    addLogEntry,
  } = useStreamBuddyStore()
  
  const [loading, setLoading] = useState(false)
  
  const handleStart = async () => {
    setLoading(true)
    addLogEntry('Starting StreamBuddy...', 'info')
    
    try {
      const result = await streamBuddyAPI.startSession({
        mode,
        ...config,
        personality,
      })
      
      setSessionData({
        session_id: result.session_id,
        mode: result.mode,
        is_active: true,
        start_time: result.start_time,
        status: result.status,
      })
      
      addLogEntry('StreamBuddy started successfully!', 'success')
    } catch (error) {
      console.error('Failed to start session:', error)
      addLogEntry(`Error: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }
  
  const handleStop = async () => {
    setLoading(true)
    addLogEntry('Stopping StreamBuddy...', 'info')
    
    try {
      const result = await streamBuddyAPI.stopSession()
      clearSession()
      addLogEntry(`Session stopped. Duration: ${Math.round(result.duration_seconds)}s`, 'success')
    } catch (error) {
      console.error('Failed to stop session:', error)
      addLogEntry(`Error: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }
  
  return (
    <div className="space-y-3">
      {/* Screen Monitor (Local Mode) */}
      {mode === 'local' && (
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">Screen Monitor</label>
          <select
            value={config.videoSource}
            onChange={(e) => setConfig({ videoSource: e.target.value })}
            disabled={isActive}
            className="w-full px-3 py-2 text-sm border-2 border-gray-200 rounded-lg focus:border-primary-600 focus:outline-none disabled:opacity-50"
          >
            <option value="0">Primary</option>
            <option value="1">Secondary</option>
            <option value="2">Third</option>
          </select>
        </div>
      )}
      
      {/* YouTube OAuth Token (YouTube Mode) */}
      {mode === 'youtube' && (
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">YouTube OAuth</label>
          <input
            type="password"
            value={config.youtubeOAuthToken}
            onChange={(e) => setConfig({ youtubeOAuthToken: e.target.value })}
            disabled={isActive}
            placeholder="Enter token"
            className="w-full px-3 py-2 text-sm border-2 border-gray-200 rounded-lg focus:border-primary-600 focus:outline-none disabled:opacity-50"
          />
        </div>
      )}
      
      {/* Control Buttons */}
      <div className="pt-2">
        {!isActive ? (
          <button
            onClick={handleStart}
            disabled={loading}
            className="w-full btn btn-primary py-3 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Play className="w-4 h-4" />
            {loading ? 'Starting...' : 'Start'}
          </button>
        ) : (
          <button
            onClick={handleStop}
            disabled={loading}
            className="w-full btn btn-danger py-3 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Square className="w-4 h-4" />
            {loading ? 'Stopping...' : 'Stop'}
          </button>
        )}
      </div>
    </div>
  )
}

export default ConfigPanel
