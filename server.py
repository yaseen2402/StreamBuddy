"""
StreamBuddy Backend Server - ADK Implementation

Uses Google's Agent Development Kit (ADK) for robust real-time streaming:
- Automatic tool execution
- Transparent reconnection handling  
- Session persistence
- Typed events with LiveRequestQueue
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ADK imports
from google import genai
from google.genai import types

# StreamBuddy components
from streambuddy_agent.screen_capture import ScreenCapture, ScreenConfig
from streambuddy_agent.video_capture import VideoCapture, VideoConfig
from streambuddy_agent.audio_capture import AudioCapture, AudioConfig
from streambuddy_agent.models import PersonalityConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models for API
# ============================================================================

class StartSessionRequest(BaseModel):
    mode: str = "local"  # "local" or "youtube"
    video_source: Optional[str] = "0"
    youtube_oauth_token: Optional[str] = None
    personality: Optional[Dict[str, Any]] = None

class UpdatePersonalityRequest(BaseModel):
    humor_level: Optional[float] = None
    supportiveness: Optional[float] = None
    playfulness: Optional[float] = None
    verbosity: Optional[str] = None
    response_frequency: Optional[str] = None

# ============================================================================
# ADK StreamBuddy Session Manager
# ============================================================================

class ADKStreamBuddySession:
    """Manages StreamBuddy session using ADK"""
    
    def __init__(self):
        self.session_id: Optional[str] = None
        self.mode: Optional[str] = None
        self.is_active = False
        self.start_time: Optional[datetime] = None
        
        # Store the main event loop for thread-safe async calls
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # ADK components
        self.client: Optional[genai.Client] = None
        self.live_session = None  # Live streaming session
        self.audio_output = None  # Audio output service
        
        # Capture components
        self.screen_capture: Optional[ScreenCapture] = None
        self.video_capture: Optional[VideoCapture] = None
        self.audio_capture: Optional[AudioCapture] = None
        
        # Background tasks
        self.stream_task: Optional[asyncio.Task] = None
        self.commentary_task: Optional[asyncio.Task] = None
        
        # Session resumption
        self.session_handle: Optional[str] = None
        
        # WebSocket connections
        self.websocket_connections = []
        
        # Status tracking
        self.status = {
            "gemini_connected": False,
            "video_capturing": False,
            "audio_capturing": False,
            "frames_captured": 0,
            "audio_chunks_captured": 0,
            "responses_generated": 0
        }
    
    async def start(self, config: StartSessionRequest) -> Dict[str, Any]:
        """Start ADK streaming session"""
        if self.is_active:
            raise ValueError("Session already active")
        
        logger.info(f"Starting ADK session in {config.mode} mode")
        
        # Store the main event loop for thread-safe async calls
        self.main_loop = asyncio.get_running_loop()
        
        self.mode = config.mode
        self.session_id = f"adk_session_{int(datetime.now().timestamp())}"
        self.start_time = datetime.now()
        
        # Get API key
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        
        logger.info(f"API key loaded: {api_key[:10]}...")
        
        # Initialize ADK client
        self.client = genai.Client(api_key=api_key)
        logger.info("✓ ADK Client created")
        await self.broadcast_status("Client initialized")
        
        # Initialize audio output
        from streambuddy_agent.audio_output import AudioOutputService, MixerConfig, QueueConfig
        
        mixer_config = MixerConfig(sample_rate=24000, channels=1, chunk_size=1024)
        queue_config = QueueConfig(max_queue_size=5, drop_policy="oldest")
        self.audio_output = AudioOutputService(
            mixer_config=mixer_config,
            queue_config=queue_config
        )
        
        success = await self.audio_output.start()
        if success:
            logger.info("✓ Audio output started")
            await self.broadcast_status("Audio output ready")
        else:
            logger.warning("⚠ Audio output failed to start")
        
        # Start video capture based on mode
        if config.mode == "local":
            # Local mode: Screen capture for games/desktop
            screen_config = ScreenConfig(
                frame_rate=1.0,
                max_dimension=768,  # Optimal for Live API
                jpeg_quality=85,
                buffer_size=50
            )
            self.screen_capture = ScreenCapture(
                config=screen_config,
                forward_callback=self._forward_video
            )
            
            monitor = 0
            if config.video_source and config.video_source.isdigit():
                monitor = int(config.video_source)
            
            if self.screen_capture.start_capture(monitor):
                self.status["video_capturing"] = True
                logger.info(f"✓ Screen capture started (monitor {monitor})")
                await self.broadcast_status(f"Screen capture started (monitor {monitor})")
            else:
                logger.error("✗ Screen capture failed")
                await self.broadcast_status("Screen capture failed", "error")
        
        elif config.mode == "youtube":
            # YouTube mode: Video capture from YouTube Live stream
            from streambuddy_agent.video_capture import VideoCapture, VideoConfig
            
            video_config = VideoConfig(
                frame_rate=1.0,
                max_dimension=768,
                jpeg_quality=85,
                buffer_size=50
            )
            self.video_capture = VideoCapture(
                config=video_config,
                forward_callback=self._forward_video
            )
            
            # For YouTube Live, we'd need the stream URL
            # For now, fallback to webcam as placeholder
            video_source = config.video_source or "0"
            
            if self.video_capture.start_capture(video_source):
                self.status["video_capturing"] = True
                logger.info(f"✓ Video capture started (source: {video_source})")
                await self.broadcast_status(f"Video capture started (YouTube mode)")
            else:
                logger.error("✗ Video capture failed")
                await self.broadcast_status("Video capture failed", "error")
        
        # Start audio capture
        audio_config = AudioConfig(
            sample_rate=16000,
            channels=1,
            chunk_duration_ms=100,  # 100ms chunks for low latency
            buffer_size=50
        )
        self.audio_capture = AudioCapture(
            config=audio_config,
            forward_callback=self._forward_audio
        )
        
        if self.audio_capture.start_capture():
            self.status["audio_capturing"] = True
            logger.info("✓ Audio capture started")
            await self.broadcast_status("Audio capture started")
        
        self.is_active = True
        
        # Start ADK streaming task
        self.stream_task = asyncio.create_task(self._run_adk_stream())
        
        logger.info("✓ ADK streaming started")
        await self.broadcast_status("StreamBuddy is now active!", "success")
        
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "status": self.status,
            "start_time": self.start_time.isoformat()
        }
    
    async def _run_adk_stream(self):
        """Main streaming loop using raw Live API (google.genai)"""
        try:
            logger.info("Starting Live API stream")
            
            # System instruction for StreamBuddy personality
            system_instruction = """You are StreamBuddy, a casual and friendly AI co-host for live streaming.

Your Role:
- Be a supportive companion who makes streaming more fun
- You receive VIDEO FRAMES (images) and AUDIO from the stream - analyze both!
- Make casual observations about what you SEE on screen in the video
- React naturally to interesting or exciting visual moments
- Comment on what's happening in the game, app, or content being shown
- Keep the vibe relaxed and conversational

Personality:
- Talk like a real person, not a robot
- Be genuinely interested and engaged with what you're seeing
- Use natural reactions: "Whoa!", "Nice!", "That's cool!", "I see..."
- It's okay to be quiet sometimes - quality over quantity

Guidelines:
- Keep responses SHORT (5-15 seconds)
- LOOK AT THE VIDEO - describe what you see on screen
- Don't narrate everything - just react to interesting visual stuff
- Be spontaneous and authentic
- Make the stream more enjoyable for viewers

Remember: You're watching the screen through video frames. Comment on what you actually see!"""
            
            # Configure streaming
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=system_instruction,
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Puck"
                        )
                    )
                )
            )
            
            # Start bidirectional streaming using raw Live API
            async with self.client.aio.live.connect(
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                config=config
            ) as session:
                logger.info("✓ Connected to Gemini Live API")
                self.status["gemini_connected"] = True
                await self.broadcast_status("Connected to Gemini Live API", "success")
                
                # Store session for sending
                self.live_session = session
                
                # Start proactive commentary
                self.commentary_task = asyncio.create_task(self._proactive_commentary_loop())
                
                # Receive and process responses continuously
                while self.is_active:
                    try:
                        async for response in session.receive():
                            if not self.is_active:
                                logger.info("Session marked inactive, stopping receive loop")
                                break
                            
                            # Handle server content
                            if hasattr(response, 'server_content') and response.server_content:
                                server_content = response.server_content
                                
                                # Handle interruption
                                if server_content.interrupted:
                                    logger.info("Response interrupted by user")
                                    await self.broadcast_status("AI interrupted", "info")
                                    continue
                                
                                # Handle model turn (AI response)
                                if server_content.model_turn:
                                    for part in server_content.model_turn.parts:
                                        # Handle audio data
                                        if hasattr(part, 'inline_data') and part.inline_data:
                                            audio_bytes = part.inline_data.data
                                            
                                            if isinstance(audio_bytes, bytes) and len(audio_bytes) > 0:
                                                self.status["responses_generated"] += 1
                                                logger.info(f"Received audio response: {len(audio_bytes)} bytes")
                                                
                                                # Play audio through audio output
                                                await self._play_audio_response(audio_bytes)
                                                await self.broadcast_status("AI responded", "info")
                        
                        # After each turn completes, continue to next turn if still active
                        if not self.is_active:
                            break
                        
                        logger.debug("Turn completed, waiting for next turn")
                        await asyncio.sleep(0.1)  # Small delay before next receive
                    
                    except Exception as e:
                        logger.error(f"Error in receive loop: {e}", exc_info=True)
                
                logger.info("Exited receive loop")
        
        except Exception as e:
            logger.error(f"Error in Live API stream: {e}", exc_info=True)
            await self.broadcast_status(f"Stream error: {e}", "error")
        finally:
            self.status["gemini_connected"] = False
            logger.info("Live API stream ended")
    
    async def _proactive_commentary_loop(self):
        """Send proactive commentary prompts every 20 seconds"""
        try:
            import random
            
            prompts = [
                "Look at the video frames I'm sending you. What do you see on the screen right now? Make a casual, friendly comment about it.",
                "Based on the video you're seeing, share a quick observation or reaction. What's happening on screen?",
                "Check out what's on the screen in the video feed. React to it naturally - what catches your attention?",
                "Take a look at the current video frame. Make a casual remark about what you notice on screen.",
                "What do you see in the video I'm streaming to you? Comment on something interesting or notable."
            ]
            
            while self.is_active:
                await asyncio.sleep(20)
                
                if not self.is_active or not hasattr(self, 'live_session') or not self.live_session:
                    break
                
                try:
                    prompt = random.choice(prompts)
                    await self.live_session.send_client_content(
                        turns={"role": "user", "parts": [{"text": prompt}]},
                        turn_complete=True
                    )
                    logger.info("Sent proactive commentary prompt")
                    await self.broadcast_status("AI making casual comment...", "info")
                except Exception as e:
                    # Session might be closed
                    if "1000" in str(e) or "closed" in str(e).lower():
                        logger.info("Session closed, stopping commentary loop")
                        break
                    logger.error(f"Error sending commentary: {e}")
        
        except asyncio.CancelledError:
            logger.info("Commentary loop cancelled")
        except Exception as e:
            logger.error(f"Commentary loop error: {e}")
    
    def _forward_video(self, frame):
        """
        Forward video frame to Gemini via ADK session.
        
        Note: Audio+video sessions are limited to 2 minutes without compression.
        Context window compression extends this to unlimited duration.
        """
        self.status["frames_captured"] += 1
        
        if hasattr(self, 'live_session') and self.live_session and self.is_active:
            try:
                # Send frame using ADK session.send_realtime_input()
                # Video format: JPEG images, optimal resolution 768x768, 1 FPS
                # Schedule in the main event loop from thread
                if hasattr(self, 'main_loop') and self.main_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.live_session.send_realtime_input(
                            media=types.Blob(
                                data=frame.frame_data,
                                mime_type="image/jpeg"
                            )
                        ),
                        self.main_loop
                    )
                    
                    if self.status["frames_captured"] % 10 == 0:
                        logger.info(f"Sent frame {self.status['frames_captured']}")
            except Exception as e:
                logger.error(f"Error forwarding video: {e}")
    
    def _forward_audio(self, audio_data):
        """Forward audio chunk to Gemini via ADK session"""
        self.status["audio_chunks_captured"] += 1
        
        if hasattr(self, 'live_session') and self.live_session and self.is_active:
            try:
                # Send audio using ADK session.send_realtime_input()
                # Schedule in the main event loop from thread
                if hasattr(self, 'main_loop') and self.main_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.live_session.send_realtime_input(
                            audio=types.Blob(
                                data=audio_data.audio_bytes,
                                mime_type="audio/pcm;rate=16000"
                            )
                        ),
                        self.main_loop
                    )
                    
                    if self.status["audio_chunks_captured"] % 20 == 0:
                        logger.info(f"Sent audio chunk {self.status['audio_chunks_captured']}")
            except Exception as e:
                logger.error(f"Error forwarding audio: {e}")
                # Send audio using session.send() with audio blob
                # Schedule in the main event loop from thread
                if hasattr(self, 'main_loop') and self.main_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.live_session.send(
                            types.Part(
                                inline_data=types.Blob(
                                    mime_type="audio/pcm;rate=16000",
                                    data=audio_data.audio_bytes
                                )
                            ),
                            end_of_turn=False  # Don't end turn, just send audio chunk
                        ),
                        self.main_loop
                    )
                    
                    if self.status["audio_chunks_captured"] % 20 == 0:
                        logger.info(f"Sent audio chunk {self.status['audio_chunks_captured']}")
            except Exception as e:
                logger.error(f"Error forwarding audio: {e}")
    
    async def _play_audio_response(self, audio_bytes: bytes):
        """Play audio response through audio output service"""
        try:
            if not self.audio_output:
                logger.warning("No audio output service available")
                return
            
            # Create AudioData object for audio output
            from streambuddy_agent.models import AudioData
            import time
            
            audio_data = AudioData(
                timestamp=time.time(),
                audio_bytes=audio_bytes,
                sample_rate=24000,  # Gemini outputs 24kHz
                encoding="pcm",
                duration_ms=int((len(audio_bytes) / (24000 * 2)) * 1000)  # 2 bytes per sample
            )
            
            # Play through audio output service
            await self.audio_output.play_audio(audio_data)
            logger.debug(f"Playing audio: {len(audio_bytes)} bytes")
        
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
    
    async def stop(self) -> Dict[str, Any]:
        """Stop the ADK session"""
        if not self.is_active:
            raise ValueError("No active session")
        
        logger.info("Stopping ADK session")
        self.is_active = False
        
        # Stop capture
        if self.screen_capture:
            self.screen_capture.stop_capture()
            self.status["video_capturing"] = False
        if self.video_capture:
            self.video_capture.stop_capture()
            self.status["video_capturing"] = False
        if self.audio_capture:
            self.audio_capture.stop_capture()
            self.status["audio_capturing"] = False
        
        # Stop audio output
        if self.audio_output:
            await self.audio_output.stop()
        
        # Cancel tasks
        if self.stream_task:
            self.stream_task.cancel()
        if self.commentary_task:
            self.commentary_task.cancel()
        
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        
        await self.broadcast_status("StreamBuddy stopped", "success")
        
        return {
            "session_id": self.session_id,
            "duration_seconds": duration,
            "final_status": self.status
        }
    
    async def broadcast_status(self, message: str, level: str = "info"):
        """Broadcast status to WebSocket clients"""
        data = {
            "type": "status",
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat(),
            "session_status": self.status
        }
        
        for ws in self.websocket_connections:
            try:
                await ws.send_json(data)
            except:
                pass
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "is_active": self.is_active,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            "status": self.status
        }

# Global session manager
session_manager = ADKStreamBuddySession()

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(title="StreamBuddy ADK API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
async def get_status():
    """Get current session status"""
    return session_manager.get_status()

@app.post("/api/session/start")
async def start_session(request: StartSessionRequest):
    """Start streaming session"""
    try:
        result = await session_manager.start(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/session/stop")
async def stop_session():
    """Stop streaming session"""
    try:
        result = await session_manager.stop()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to stop session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    session_manager.websocket_connections.append(websocket)
    logger.info("WebSocket client connected")
    
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Echo back for now
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        if websocket in session_manager.websocket_connections:
            session_manager.websocket_connections.remove(websocket)

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("StreamBuddy ADK Server Starting")
    logger.info("=" * 60)
    logger.info("Open your browser to: http://localhost:8000")
    logger.info("=" * 60)
    
    port = int(os.getenv("PORT", "8000"))
    
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )
