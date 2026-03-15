import { Youtube } from 'lucide-react'
// import { Monitor } from 'lucide-react' // Local mode – commented out for now
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const ModeSelector = () => {
  const { mode, setMode, isActive } = useStreamBuddyStore()

  return (
    <div className="mb-3">
      <label className="block text-xs font-semibold text-gray-700 mb-2">Mode</label>

      <div className="grid grid-cols-1 gap-2">
        {/* Local mode – commented out for now
        <button
          onClick={() => setMode('local')}
          disabled={isActive}
          className={...}
        >
          <Monitor ... />
          <div>Local</div>
        </button>
        */}
        <button
          onClick={() => setMode('youtube')}
          disabled={isActive}
          className={`p-3 rounded-lg border-2 transition-all ${
            mode === 'youtube' ? 'border-primary-600 bg-primary-50' : 'border-gray-200 hover:border-primary-300'
          } ${isActive ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
          <Youtube className={`w-5 h-5 mx-auto mb-1 ${mode === 'youtube' ? 'text-primary-600' : 'text-gray-600'}`} />
          <div className="text-sm font-semibold text-gray-900">YouTube</div>
        </button>
      </div>
    </div>
  )
}

export default ModeSelector
