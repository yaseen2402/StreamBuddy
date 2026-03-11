import { useEffect, useRef } from 'react'
import { ScrollText, Info, CheckCircle, AlertTriangle, XCircle } from 'lucide-react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const ActivityLog = () => {
  const { activityLog } = useStreamBuddyStore()
  const logEndRef = useRef(null)
  
  // Auto-scroll to bottom when new entries are added
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activityLog])
  
  const getIcon = (level) => {
    switch (level) {
      case 'success':
        return <CheckCircle className="w-4 h-4 text-green-600" />
      case 'warning':
        return <AlertTriangle className="w-4 h-4 text-yellow-600" />
      case 'error':
        return <XCircle className="w-4 h-4 text-red-600" />
      default:
        return <Info className="w-4 h-4 text-blue-600" />
    }
  }
  
  const getLevelClass = (level) => {
    switch (level) {
      case 'success':
        return 'bg-green-50 border-green-200'
      case 'warning':
        return 'bg-yellow-50 border-yellow-200'
      case 'error':
        return 'bg-red-50 border-red-200'
      default:
        return 'bg-blue-50 border-blue-200'
    }
  }
  
  const formatTime = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }
  
  return (
    <div className="card">
      <h2 className="text-xl font-bold mb-3 flex items-center gap-2">
        <ScrollText className="w-5 h-5 text-primary-600" />
        <span>Activity Log</span>
      </h2>
      
      <div className="bg-gray-900 rounded-lg p-3 h-64 overflow-y-auto font-mono text-xs">
        <div className="space-y-1">
          {activityLog.map((entry, index) => (
            <div key={index} className={`flex items-start gap-2 p-2 rounded border ${getLevelClass(entry.level)}`}>
              <div className="flex-shrink-0 mt-0.5">{getIcon(entry.level)}</div>
              <div className="flex-1 min-w-0">
                <span className="text-xs text-gray-500 font-semibold">[{formatTime(entry.timestamp)}]</span>
                <p className="text-gray-900">{entry.message}</p>
              </div>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  )
}

export default ActivityLog
