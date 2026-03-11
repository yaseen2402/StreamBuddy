import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'
import { streamBuddyAPI } from '../services/api'

const PersonalityPanel = () => {
  const { personality, setPersonality, isActive, addLogEntry } = useStreamBuddyStore()
  const [loading, setLoading] = useState(false)
  
  const handleUpdate = async () => {
    setLoading(true)
    
    try {
      await streamBuddyAPI.updatePersonality(personality)
      addLogEntry('Personality updated successfully', 'success')
    } catch (error) {
      console.error('Failed to update personality:', error)
      addLogEntry(`Error: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }
  
  const SliderControl = ({ label, value, onChange, min = 0, max = 1, step = 0.1 }) => (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <label className="text-xs font-semibold text-gray-700">{label}</label>
        <span className="text-xs font-bold text-primary-600">{value.toFixed(1)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary-600"
      />
    </div>
  )
  
  return (
    <div className="card">
      <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-primary-600" />
        <span>Personality</span>
      </h2>
      
      <div className="space-y-4">
        {/* Sliders */}
        <SliderControl label="Humor" value={personality.humor_level} onChange={(value) => setPersonality({ humor_level: value })} />
        <SliderControl label="Support" value={personality.supportiveness} onChange={(value) => setPersonality({ supportiveness: value })} />
        <SliderControl label="Playful" value={personality.playfulness} onChange={(value) => setPersonality({ playfulness: value })} />
        
        {/* Dropdowns */}
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">Style</label>
          <select
            value={personality.verbosity}
            onChange={(e) => setPersonality({ verbosity: e.target.value })}
            className="w-full px-3 py-2 text-sm border-2 border-gray-200 rounded-lg focus:border-primary-600 focus:outline-none"
          >
            <option value="concise">Brief</option>
            <option value="moderate">Natural</option>
            <option value="verbose">Detailed</option>
          </select>
        </div>
        
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">Frequency</label>
          <select
            value={personality.response_frequency}
            onChange={(e) => setPersonality({ response_frequency: e.target.value })}
            className="w-full px-3 py-2 text-sm border-2 border-gray-200 rounded-lg focus:border-primary-600 focus:outline-none"
          >
            <option value="low">Selective</option>
            <option value="medium">Balanced</option>
            <option value="high">Active</option>
          </select>
        </div>
        
        {/* Update Button */}
        <button
          onClick={handleUpdate}
          disabled={!isActive || loading}
          className="w-full btn btn-secondary text-sm py-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Updating...' : 'Update'}
        </button>
      </div>
    </div>
  )
}

export default PersonalityPanel
