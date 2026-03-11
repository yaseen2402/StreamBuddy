import { Mic2, Wifi, WifiOff } from 'lucide-react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const Header = () => {
  const { wsConnected } = useStreamBuddyStore()
  
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Mic2 className="w-8 h-8 text-primary-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-900">StreamBuddy</h1>
            <p className="text-sm text-gray-600">AI Co-host</p>
          </div>
        </div>
        
        <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${
          wsConnected ? 'bg-green-100' : 'bg-gray-100'
        }`}>
          {wsConnected ? (
            <Wifi className="w-4 h-4 text-green-600" />
          ) : (
            <WifiOff className="w-4 h-4 text-gray-600" />
          )}
        </div>
      </div>
    </div>
  )
}

export default Header
