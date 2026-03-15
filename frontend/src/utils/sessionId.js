// Generate or retrieve a persistent session ID for this browser
export const getClientSessionId = () => {
  const STORAGE_KEY = 'streambuddy_session_id'
  
  // Try to get existing session ID
  let sessionId = localStorage.getItem(STORAGE_KEY)
  
  // Generate new one if doesn't exist
  if (!sessionId) {
    sessionId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    localStorage.setItem(STORAGE_KEY, sessionId)
  }
  
  return sessionId
}

// Clear session ID (for testing or logout)
export const clearClientSessionId = () => {
  localStorage.removeItem('streambuddy_session_id')
}
