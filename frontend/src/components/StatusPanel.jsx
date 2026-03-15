import { useEffect, useState } from 'react'
import { Bot, Video, Mic, Volume2, BarChart2 } from 'lucide-react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const StatusPanel = () => {
  const { sessionId, mode, isActive, startTime, status } = useStreamBuddyStore()
  const [uptime, setUptime] = useState('0s')
  
  // Update uptime every second
  useEffect(() => {
    if (!isActive || !startTime) {
      setUptime('0s')
      return
    }
    
    const interval = setInterval(() => {
      const seconds = Math.floor((Date.now() - new Date(startTime).getTime()) / 1000)
      setUptime(formatUptime(seconds))
    }, 1000)
    
    return () => clearInterval(interval)
  }, [isActive, startTime])
  
  const formatUptime = (seconds) => {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60
    
    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`
    } else if (minutes > 0) {
      return `${minutes}m ${secs}s`
    } else {
      return `${secs}s`
    }
  }
  
  const ComponentStatus = ({ icon: Icon, label, active }) => (
    <div className="flex items-center justify-between p-2 bg-gray-50 rounded">
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-gray-600" />
        <span className="text-sm font-medium text-gray-900">{label}</span>
      </div>
      <span className={`badge text-xs ${active ? 'badge-active' : 'badge-inactive'}`}>
        {active ? 'On' : 'Off'}
      </span>
    </div>
  )
  
  const MetricCard = ({ value, label }) => (
    <div className="text-center p-2 bg-gray-50 rounded">
      <div className="text-xl font-bold text-primary-600">{value}</div>
      <div className="text-xs text-gray-600">{label}</div>
    </div>
  )
  
  return (
    <div className="card">
      <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
        <BarChart2 className="w-5 h-5 text-primary-600" />
        <span>Status</span>
      </h2>
      
      {/* Session Info */}
      <div className="bg-gray-50 rounded-lg p-3 mb-4 space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">Mode:</span>
          <span className="font-semibold text-gray-900 capitalize">
            {isActive ? mode : '-'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Uptime:</span>
          <span className="font-semibold text-gray-900">{uptime}</span>
        </div>
      </div>
      
      {/* Component Status */}
      <div className="space-y-2 mb-4">
        <ComponentStatus icon={Bot} label="AI" active={status.gemini_connected} />
        <ComponentStatus icon={Video} label="Video" active={status.video_capturing} />
        <ComponentStatus icon={Mic} label="Audio In" active={status.audio_capturing} />
        <ComponentStatus icon={Volume2} label="Audio Out" active={status.audio_output_active} />
      </div>
      
      {/* Metrics */}
      <div className="grid grid-cols-3 gap-2">
        <MetricCard value={status.frames_captured || 0} label="Frames" />
        <MetricCard value={status.audio_chunks_captured || 0} label="Audio" />
        <MetricCard value={status.responses_generated || 0} label="Responses" />
      </div>
    </div>
  )
}

export default StatusPanel
