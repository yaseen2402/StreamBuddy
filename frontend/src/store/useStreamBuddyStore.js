import { create } from 'zustand'

const useStreamBuddyStore = create((set, get) => ({
  // Connection state
  wsConnected: false,
  
  // Session state
  sessionId: null,
  mode: 'youtube', // 'local' commented out in UI for now
  isActive: false,
  startTime: null,
  
  // Component status
  status: {
    gemini_connected: false,
    video_capturing: false,
    audio_capturing: false,
    audio_output_active: false,
    frames_captured: 0,
    audio_chunks_captured: 0,
    responses_generated: 0,
  },
  
  // Configuration
  config: {
    videoSource: '0',
    youtubeOAuthToken: '',
  },
  
  // Personality
  personality: {
    humor_level: 0.7,
    supportiveness: 0.8,
    playfulness: 0.6,
    verbosity: 'moderate',
    response_frequency: 'medium',
    chat_interaction_mode: 'responsive',
  },
  
  // Activity log
  activityLog: [
    {
      timestamp: new Date().toISOString(),
      message: 'StreamBuddy ready to start. Configure settings and click Start.',
      level: 'info',
    },
  ],

  // Toast notification (e.g. YouTube connection error)
  toast: null,

  // Actions
  setWsConnected: (connected) => set({ wsConnected: connected }),

  setToast: (message, level = 'error') => set({
    toast: message ? { message, level } : null,
  }),

  clearToast: () => set({ toast: null }),
  
  setMode: (mode) => set({ mode }),
  
  setConfig: (config) => set((state) => ({
    config: { ...state.config, ...config },
  })),
  
  setPersonality: (personality) => set((state) => ({
    personality: { ...state.personality, ...personality },
  })),
  
  setSessionData: (data) => set({
    sessionId: data.session_id,
    mode: data.mode,
    isActive: data.is_active,
    startTime: data.start_time ? new Date(data.start_time) : null,
    status: data.status || get().status,
  }),
  
  updateStatus: (status) => set((state) => ({
    status: { ...state.status, ...status },
  })),
  
  addLogEntry: (message, level = 'info') => set((state) => ({
    activityLog: [
      ...state.activityLog.slice(-99), // Keep last 99 entries
      {
        timestamp: new Date().toISOString(),
        message,
        level,
      },
    ],
  })),
  
  clearSession: () => set({
    sessionId: null,
    isActive: false,
    startTime: null,
    toast: null,
    status: {
      gemini_connected: false,
      video_capturing: false,
      audio_capturing: false,
      audio_output_active: false,
      frames_captured: 0,
      audio_chunks_captured: 0,
      responses_generated: 0,
    },
  }),
}))

export default useStreamBuddyStore
