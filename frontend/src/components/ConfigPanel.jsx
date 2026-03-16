import { useState, useEffect } from 'react'
import { Play, Square, CheckCircle } from 'lucide-react'
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
    setToast,
  } = useStreamBuddyStore()

  const [loading, setLoading] = useState(false)
  const [youtubeConnected, setYoutubeConnected] = useState(false)
  const [youtubeStatusLoading, setYoutubeStatusLoading] = useState(false)

  const fetchYouTubeStatus = async () => {
    if (mode !== 'youtube') return
    setYoutubeStatusLoading(true)
    try {
      const { connected } = await streamBuddyAPI.getYouTubeStatus()
      setYoutubeConnected(!!connected)
    } catch {
      setYoutubeConnected(false)
    } finally {
      setYoutubeStatusLoading(false)
    }
  }

  useEffect(() => {
    fetchYouTubeStatus()
  }, [mode])

  // When returning from OAuth redirect with ?youtube_connected=1, refresh status
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('youtube_connected') === '1') {
      fetchYouTubeStatus()
      // Clean URL without reload
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])
  
  const handleStart = async () => {
    setLoading(true)
    // Clear any stale session data before starting new session
    clearSession()
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

      if (result.youtube_connection_error) {
        setToast(result.youtube_connection_error, 'error')
      }
      
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
      {/* Local mode – Screen Monitor block commented out for now */}

      {/* YouTube OAuth (YouTube Mode) */}
      {mode === 'youtube' && (
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">
            YouTube account
          </label>

          {youtubeStatusLoading ? (
            <p className="text-xs text-gray-500 py-1">Checking...</p>
          ) : youtubeConnected ? (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200">
              <CheckCircle className="w-4 h-4 text-green-600 shrink-0" />
              <span className="text-sm font-medium text-green-800">YouTube account connected</span>
            </div>
          ) : null}

          <div className="flex flex-col gap-2 mt-2">
            {/* Optional manual token entry (fallback) */}
            <input
              type="password"
              value={config.youtubeOAuthToken}
              onChange={(e) => setConfig({ youtubeOAuthToken: e.target.value })}
              disabled={isActive}
              placeholder="Optional: paste token JSON (advanced)"
              className="w-full px-3 py-2 text-sm border-2 border-gray-200 rounded-lg focus:border-primary-600 focus:outline-none disabled:opacity-50"
            />

            {/* Connect button – show when not connected or as "Reconnect" */}
            <button
              type="button"
              disabled={isActive}
              onClick={() => {
                const authUrl = streamBuddyAPI.getYouTubeAuthUrl()
                window.location.href = authUrl
              }}
              className="w-full px-3 py-2 text-xs font-semibold border-2 border-primary-600 text-primary-700 rounded-lg hover:bg-primary-50 disabled:opacity-50"
            >
              {youtubeConnected ? 'Reconnect YouTube account' : 'Connect your YouTube account'}
            </button>

            {!youtubeConnected && (
              <p className="text-[11px] text-gray-500">
                Click once to authorize StreamBuddy. Then you can start YouTube sessions without pasting a token.
              </p>
            )}
          </div>
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
