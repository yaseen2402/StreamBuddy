import { useEffect, useRef } from 'react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const useWebSocket = () => {
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  
  const { isActive, setWsConnected, updateStatus, addLogEntry } = useStreamBuddyStore()
  
  const connect = () => {
    // Don't connect if session is not active
    if (!isActive) {
      return
    }
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.hostname}:8000/ws`
    
    wsRef.current = new WebSocket(wsUrl)
    
    wsRef.current.onopen = () => {
      console.log('WebSocket connected')
      setWsConnected(true)
      
      // Clear reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }
    
    wsRef.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleMessage(data)
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }
    
    wsRef.current.onclose = () => {
      console.log('WebSocket disconnected')
      setWsConnected(false)
      
      // Only reconnect if session is still active
      if (isActive) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('Reconnecting WebSocket...')
          connect()
        }, 3000)
      }
    }
    
    wsRef.current.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }
  
  const disconnect = () => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    setWsConnected(false)
  }
  
  const handleMessage = (data) => {
    switch (data.type) {
      case 'status':
        addLogEntry(data.message, data.level)
        if (data.session_status) {
          updateStatus(data.session_status)
        }
        break
        
      case 'connected':
        addLogEntry(data.message, 'success')
        if (data.session_status) {
          updateStatus(data.session_status)
        }
        break
        
      default:
        console.log('Unknown message type:', data.type)
    }
  }
  
  useEffect(() => {
    if (isActive) {
      // Connect when session becomes active
      connect()
    } else {
      // Disconnect when session becomes inactive
      disconnect()
    }
    
    return () => {
      disconnect()
    }
  }, [isActive])
  
  return wsRef.current
}

export default useWebSocket
