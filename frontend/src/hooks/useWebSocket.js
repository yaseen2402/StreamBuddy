import { useEffect, useRef } from 'react'
import useStreamBuddyStore from '../store/useStreamBuddyStore'

const useWebSocket = () => {
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const audioContextRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const audioWorkletNodeRef = useRef(null)
  const shouldReconnectRef = useRef(true) // Flag to control reconnection
  
  const { isActive, setWsConnected, updateStatus, addLogEntry } = useStreamBuddyStore()
  
  const startAudioCapture = async () => {
    try {
      console.log('Requesting microphone access...')
      addLogEntry('Requesting microphone access...', 'info')
      
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        } 
      })
      
      console.log('Microphone access granted')
      mediaStreamRef.current = stream
      
      // Verify stream is active
      const audioTracks = stream.getAudioTracks()
      if (audioTracks.length === 0) {
        throw new Error('No audio tracks available')
      }
      
      console.log(`Audio track: ${audioTracks[0].label}, enabled: ${audioTracks[0].enabled}`)
      
      // Create AudioContext for processing
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      })
      
      // Resume AudioContext if suspended (browser autoplay policy)
      if (audioContextRef.current.state === 'suspended') {
        console.log('AudioContext suspended, resuming...')
        await audioContextRef.current.resume()
      }
      
      console.log(`AudioContext state: ${audioContextRef.current.state}`)
      
      const source = audioContextRef.current.createMediaStreamSource(stream)
      
      // Use ScriptProcessorNode for audio capture
      // Buffer size 2048 = ~128ms at 16kHz (within recommended 40-100ms range)
      const bufferSize = 2048
      const processor = audioContextRef.current.createScriptProcessor(bufferSize, 1, 1)
      
      let chunksSent = 0
      processor.onaudioprocess = (e) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0)
          
          // Convert Float32Array to Int16Array (PCM 16-bit)
          const pcmData = new Int16Array(inputData.length)
          for (let i = 0; i < inputData.length; i++) {
            const s = Math.max(-1, Math.min(1, inputData[i]))
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
          }
          
          // Send as binary data
          wsRef.current.send(pcmData.buffer)
          chunksSent++
          
          // Log first few chunks to confirm it's working
          if (chunksSent <= 3) {
            console.log(`Sent audio chunk ${chunksSent}: ${pcmData.buffer.byteLength} bytes`)
          }
        }
      }
      
      source.connect(processor)
      processor.connect(audioContextRef.current.destination)
      audioWorkletNodeRef.current = processor
      
      // Update status
      updateStatus({ audio_capturing: true })
      
      console.log('✓ Audio capture started successfully (~128ms chunks)')
      addLogEntry('✓ Microphone active - recording indicator should appear', 'success')
      
      // Monitor stream status
      audioTracks[0].onended = () => {
        console.log('Audio track ended')
        updateStatus({ audio_capturing: false })
        addLogEntry('Microphone stopped', 'warning')
      }
      
    } catch (error) {
      console.error('Failed to start audio capture:', error)
      
      let errorMessage = error.message
      if (error.name === 'NotAllowedError') {
        errorMessage = 'Microphone permission denied. Please allow microphone access.'
      } else if (error.name === 'NotFoundError') {
        errorMessage = 'No microphone found. Please connect a microphone.'
      } else if (error.name === 'NotReadableError') {
        errorMessage = 'Microphone is already in use by another application.'
      }
      
      addLogEntry(`Microphone error: ${errorMessage}`, 'error')
      updateStatus({ audio_capturing: false })
    }
  }
  
  const stopAudioCapture = () => {
    if (audioWorkletNodeRef.current) {
      audioWorkletNodeRef.current.disconnect()
      audioWorkletNodeRef.current = null
    }
    
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
    }
    
    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }
    
    // Update status
    updateStatus({ audio_capturing: false })
    
    console.log('Audio capture stopped')
  }
  
  const playAudioResponse = async (audioData) => {
    try {
      // Update status to show audio is playing
      updateStatus({ audio_output_active: true })
      
      // Create AudioContext for playback if not exists
      if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
        audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 24000 // Gemini outputs 24kHz
        })
      }
      
      // Resume context if suspended (browser autoplay policy)
      if (audioContextRef.current.state === 'suspended') {
        await audioContextRef.current.resume()
      }
      
      // Convert ArrayBuffer to AudioBuffer
      // Gemini sends PCM 16-bit mono at 24kHz
      const int16Array = new Int16Array(audioData)
      const float32Array = new Float32Array(int16Array.length)
      
      // Convert Int16 to Float32
      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / (int16Array[i] < 0 ? 0x8000 : 0x7FFF)
      }
      
      // Create AudioBuffer
      const audioBuffer = audioContextRef.current.createBuffer(
        1, // mono
        float32Array.length,
        24000 // sample rate
      )
      audioBuffer.getChannelData(0).set(float32Array)
      
      // Play the audio
      const source = audioContextRef.current.createBufferSource()
      source.buffer = audioBuffer
      source.connect(audioContextRef.current.destination)
      
      // Reset status when audio finishes
      source.onended = () => {
        updateStatus({ audio_output_active: false })
      }
      
      source.start(0)
      
      console.log(`Playing AI audio response: ${audioData.byteLength} bytes`)
      addLogEntry('AI responded with audio', 'success')
    } catch (error) {
      console.error('Failed to play audio:', error)
      addLogEntry(`Audio playback error: ${error.message}`, 'error')
      updateStatus({ audio_output_active: false })
    }
  }
  
  const connect = () => {
    // Don't connect if session is not active
    if (!isActive) {
      return
    }
    
    // Enable reconnection when explicitly connecting
    shouldReconnectRef.current = true
    
    // Use environment variable for backend URL, fallback to current host
    const backendHost = import.meta.env.VITE_BACKEND_HOST || window.location.hostname
    const backendPort = import.meta.env.VITE_BACKEND_PORT || '8000'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${backendHost}:${backendPort}/ws`
    
    console.log(`Connecting to WebSocket: ${wsUrl}`)
    
    wsRef.current = new WebSocket(wsUrl)
    wsRef.current.binaryType = 'arraybuffer' // Important for receiving binary audio
    
    wsRef.current.onopen = async () => {
      console.log('WebSocket connected')
      setWsConnected(true)
      
      // Start audio capture when connected
      await startAudioCapture()
      
      // Clear reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }
    
    wsRef.current.onmessage = async (event) => {
      // Handle binary audio data (AI responses)
      if (event.data instanceof ArrayBuffer) {
        await playAudioResponse(event.data)
      }
      // Handle text messages (status updates)
      else if (typeof event.data === 'string') {
        try {
          const data = JSON.parse(event.data)
          handleMessage(data)
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }
    }
    
    wsRef.current.onclose = () => {
      console.log('WebSocket disconnected')
      setWsConnected(false)
      stopAudioCapture()
      
      // Only reconnect if explicitly allowed and session is still active
      if (shouldReconnectRef.current && isActive) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('Reconnecting WebSocket...')
          connect()
        }, 3000)
      } else {
        console.log('Not reconnecting (shouldReconnect:', shouldReconnectRef.current, ', isActive:', isActive, ')')
      }
    }
    
    wsRef.current.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }
  
  const disconnect = () => {
    // Disable reconnection when explicitly disconnecting
    shouldReconnectRef.current = false
    
    stopAudioCapture()
    
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
          // In remote audio mode, preserve frontend audio status
          // Backend doesn't know about frontend audio capture/playback
          const currentStatus = useStreamBuddyStore.getState().status
          const mergedStatus = {
            ...data.session_status,
            // Keep frontend audio status, don't let backend override
            audio_capturing: currentStatus.audio_capturing,
            audio_output_active: currentStatus.audio_output_active
          }
          updateStatus(mergedStatus)
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
