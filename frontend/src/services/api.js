import axios from 'axios'
import { getClientSessionId } from '../utils/sessionId'

// Use VITE_BACKEND_URL from environment, fallback to relative /api
const baseURL = import.meta.env.VITE_BACKEND_URL 
  ? `${import.meta.env.VITE_BACKEND_URL}/api`
  : '/api'

const api = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const streamBuddyAPI = {
  // Get current status
  getStatus: async () => {
    const response = await api.get('/status')
    return response.data
  },

  // Check if YouTube account is connected (token stored on backend)
  getYouTubeStatus: async () => {
    const sessionId = getClientSessionId()
    const response = await api.get('/youtube/status', {
      params: { client_session_id: sessionId }
    })
    return response.data
  },
  
  // Start session
  startSession: async (config) => {
    const sessionId = getClientSessionId()
    const response = await api.post('/session/start', {
      mode: config.mode,
      youtube_oauth_token: config.youtubeOAuthToken || null,
      video_source: config.videoSource,
      personality: config.personality,
      client_session_id: sessionId,
    })
    return response.data
  },
  
  // Stop session
  stopSession: async () => {
    const response = await api.post('/session/stop')
    return response.data
  },
  
  // Update personality
  updatePersonality: async (personality) => {
    const response = await api.post('/personality/update', personality)
    return response.data
  },
  
  // Get YouTube OAuth URL
  getYouTubeAuthUrl: () => {
    const sessionId = getClientSessionId()
    const backendUrl = import.meta.env.VITE_BACKEND_URL || window.location.origin
    return `${backendUrl}/auth/youtube/start?client_session_id=${sessionId}`
  },
}

export default api
