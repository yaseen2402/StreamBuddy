import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
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
    const response = await api.get('/youtube/status')
    return response.data
  },
  
  // Start session
  startSession: async (config) => {
    const response = await api.post('/session/start', {
      mode: config.mode,
      youtube_oauth_token: config.youtubeOAuthToken || null,
      video_source: config.videoSource,
      personality: config.personality,
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
}

export default api
