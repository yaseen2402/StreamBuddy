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
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

# ADK imports
from google import genai
from google.genai import types

# StreamBuddy components
from streambuddy_agent.screen_capture import ScreenCapture, ScreenConfig
from streambuddy_agent.audio_capture import AudioCapture, AudioConfig
from streambuddy_agent.youtube_connection import YouTubeConnection
from streambuddy_agent.chat_capture import ChatCapture, ChatConfig
from streambuddy_agent.models import PersonalityConfig, ChatMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
REMOTE_AUDIO_MODE = os.getenv("REMOTE_AUDIO_MODE", "true").lower() == "true"
PROACTIVE_AUDIO_MODE = os.getenv("PROACTIVE_AUDIO_MODE", "false").lower() == "true"
logger.info(f"Remote audio mode: {REMOTE_AUDIO_MODE}")
logger.info(f"Proactive audio mode: {PROACTIVE_AUDIO_MODE}")

# ============================================================================
# Pydantic Models for API
# ============================================================================

class StartSessionRequest(BaseModel):
    mode: str = "local"  # "local" or "youtube"
    video_source: Optional[str] = "0"
    youtube_oauth_token: Optional[str] = None
    personality: Optional[Dict[str, Any]] = None
    client_session_id: Optional[str] = None  # Client-provided session ID for multi-user support

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
        self.client_session_id: Optional[str] = None  # Client's persistent session ID
        self.mode: Optional[str] = None
        self.is_active = False
        self.start_time: Optional[datetime] = None
        
        # Store the main event loop for thread-safe async calls
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # ADK components
        self.client: Optional[genai.Client] = None
        self.live_session = None  # Live streaming session
        self.audio_output = None  # Audio output service
        # Perception / captioning client (non-Live)
        self.caption_client: Optional[genai.Client] = None
        
        # Capture components
        self.screen_capture: Optional[ScreenCapture] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.youtube_connection: Optional[YouTubeConnection] = None
        self.chat_capture: Optional[ChatCapture] = None
        
        # Background tasks
        self.stream_task: Optional[asyncio.Task] = None
        self.commentary_task: Optional[asyncio.Task] = None
        self.chat_analysis_task: Optional[asyncio.Task] = None
        
        # Session resumption
        self.session_handle: Optional[str] = None
        
        # WebSocket connections
        self.websocket_connections = []
        
        # Status tracking
        self.status = {
            "gemini_connected": False,
            "video_capturing": False,
            "audio_capturing": False,
            "chat_capturing": False,
            "frames_captured": 0,
            "audio_chunks_captured": 0,
            "chat_messages_captured": 0,
            "responses_generated": 0
        }
        
        # Captioning / perception settings
        self.last_caption_time: float = 0.0
        # Take a screenshot less frequently for perception (free-tier friendly)
        # 30 seconds → at most ~2 caption calls per minute.
        self.caption_interval_sec: float = 30.0
        
        # Text timeline of what has been happening on screen
        # Each entry: {"timestamp": float, "summary": str}
        self.screen_timeline: list[Dict[str, Any]] = []
        # Recent chat messages timeline (raw ChatMessage objects)
        self.chat_timeline: list[ChatMessage] = []

        # High-level chat analysis for UI
        self.last_chat_summary: Optional[str] = None
        self.last_chat_mood: Optional[str] = None
        self.last_chat_topics: Optional[list[str]] = None

        # Chat analysis controls
        self.last_chat_analysis_time: float = 0.0
        # How often to run chat analysis (seconds)
        self.chat_analysis_interval_sec: float = 15.0

        # Conversation / voice timeline (what we've asked the voice model to do)
        # Each entry: {"timestamp": float, "text": str}
        self.conversation_timeline: list[Dict[str, Any]] = []
        
        # Track which chat message IDs have already been sent to the Live session
        self._sent_message_ids: set[str] = set()
        
        # Voice triggering controls
        self.last_voice_time: float = 0.0
        # Minimum spacing between voice triggers (seconds).
        # 45 seconds → at most ~1–2 decision calls per minute.
        self.min_voice_interval_sec: float = 45.0
        
        # Personality configuration
        self.personality: Dict[str, Any] = {
            "humor_level": 0.7,
            "supportiveness": 0.8,
            "playfulness": 0.6,
            "verbosity": "moderate",
            "response_frequency": "medium",
        }
        
        # Persistent session logging (captions + conversation) on disk
        self.session_log_dir: Optional[Path] = None
        self.caption_log_path: Optional[Path] = None
        self.conversation_log_path: Optional[Path] = None
    
    async def start(self, config: StartSessionRequest) -> Dict[str, Any]:
        """Start ADK streaming session"""
        if self.is_active:
            raise ValueError("Session already active")
        
        logger.info(f"Starting ADK session in {config.mode} mode")
        
        # Store the main event loop for thread-safe async calls
        self.main_loop = asyncio.get_running_loop()
        
        self.mode = config.mode
        self.client_session_id = config.client_session_id or f"guest_{int(datetime.now().timestamp())}"
        self.session_id = f"adk_session_{int(datetime.now().timestamp())}"
        self.start_time = datetime.now()
        youtube_connection_error = None
        
        # Update personality if provided
        if config.personality:
            self.personality.update(config.personality)
            logger.info(f"Personality configured: {self.personality}")

        # Create a directory for this session's persistent logs
        try:
            base_log_dir = Path("streambuddy_sessions")
            base_log_dir.mkdir(parents=True, exist_ok=True)
            # Use client_session_id for organizing user sessions
            self.session_log_dir = base_log_dir / self.client_session_id / self.session_id
            self.session_log_dir.mkdir(parents=True, exist_ok=True)
            self.caption_log_path = self.session_log_dir / "captions.jsonl"
            self.conversation_log_path = self.session_log_dir / "conversation.jsonl"
            logger.info(f"Session logs will be stored in {self.session_log_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize session log directory: {e}", exc_info=True)
        
        # Get API key
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        
        logger.info(f"API key loaded: {api_key[:10]}...")
        
        # Initialize ADK client with v1alpha API version
        # v1alpha is required for proactive audio and affective dialog features
        self.client = genai.Client(
            api_key=api_key,
            http_options={'api_version': 'v1alpha'}
        )
        logger.info("✓ ADK Client created (v1alpha API)")
        await self.broadcast_status("Client initialized")
        
        # Separate client for perception/captioning (standard Gemini API)
        # Uses default API version for gemini-2.5-flash.
        self.caption_client = genai.Client(api_key=api_key)
        
        # Initialize audio output (optional in remote mode)
        # In remote mode, audio is sent to frontend via WebSocket
        if not REMOTE_AUDIO_MODE:
            from streambuddy_agent.audio_output import AudioOutputService, MixerConfig, QueueConfig
            
            mixer_config = MixerConfig(sample_rate=24000, channels=1, chunk_size=1024)
            queue_config = QueueConfig(max_queue_size=5, drop_policy="oldest")
            self.audio_output = AudioOutputService(
                mixer_config=mixer_config,
                queue_config=queue_config
            )
            
            success = await self.audio_output.start()
            if success:
                logger.info("✓ Local audio output started")
                await self.broadcast_status("Local audio output ready")
            else:
                logger.warning("⚠ Local audio output failed to start")
        else:
            logger.info("Remote audio mode: audio will be sent to frontend via WebSocket")
            self.audio_output = None
        
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
            # YouTube mode: live chat capture (no video) from the creator's channel.
            # Prefer an explicit token from the request; otherwise fall back to a
            # session-specific token file.
            youtube_token = config.youtube_oauth_token
            if not youtube_token:
                # Use session-specific token only
                token_dir = Path("youtube_tokens")
                token_path = token_dir / f"{self.client_session_id}.json"
                
                if token_path.exists():
                    try:
                        youtube_token = token_path.read_text(encoding="utf-8")
                        logger.info(f"Loaded YouTube OAuth token from {token_path}")
                    except Exception as e:
                        logger.error(f"Failed to read {token_path}: {e}")

            if not youtube_token:
                raise ValueError(
                    "YouTube OAuth token not available. "
                    "Connect your YouTube account first via /auth/youtube/start "
                    "or provide youtube_oauth_token in the request."
                )

            # Establish YouTube API connection
            self.youtube_connection = YouTubeConnection()
            if not self.youtube_connection.connect(youtube_token):
                logger.error("✗ Failed to connect to YouTube Live API")
                await self.broadcast_status("YouTube connection failed", "error")
                raw = getattr(self.youtube_connection, "last_error_message", None) or ""
                if "liveStreamingNotEnabled" in raw or "not enabled for live streaming" in raw:
                    youtube_connection_error = (
                        "Your YouTube channel is not enabled for live streaming. "
                        "Enable it at https://www.youtube.com/features and try again."
                    )
                elif "accessNotConfigured" in raw or "has not been used" in raw:
                    youtube_connection_error = (
                        "YouTube Data API v3 is not enabled for this project. "
                        "Enable it in Google Cloud Console and try again."
                    )
                else:
                    youtube_connection_error = (
                        "Could not connect to YouTube. Check your token and channel settings."
                    )
            else:
                logger.info("✓ Connected to YouTube Live API for chat")
                await self.broadcast_status("YouTube Live chat connected", "info")

                # Start chat capture, forwarding messages into the Live session
                chat_config = ChatConfig(
                    poll_interval_ms=2000,
                    max_results=200,
                    buffer_size=200,
                    reconnect_delay_ms=5000,
                )
                self.chat_capture = ChatCapture(
                    youtube_connection=self.youtube_connection,
                    config=chat_config,
                    forward_callback=self._handle_chat_message,
                )

                if self.chat_capture.start_capture():
                    self.status["chat_capturing"] = True
                    logger.info("✓ YouTube chat capture started")
                    await self.broadcast_status("YouTube chat capture started", "info")
                    # Start background chat analysis loop
                    if self.chat_analysis_task is None or self.chat_analysis_task.done():
                        self.chat_analysis_task = asyncio.create_task(
                            self._chat_analysis_loop()
                        )
                else:
                    logger.error("✗ Failed to start YouTube chat capture")
                    await self.broadcast_status("YouTube chat capture failed", "error")
        
        # Start audio capture (only if not in remote mode)
        # In remote mode, audio comes from frontend via WebSocket
        if not REMOTE_AUDIO_MODE:
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
                logger.info("✓ Local audio capture started")
                await self.broadcast_status("Local audio capture started")
        else:
            logger.info("Remote audio mode: audio will come from frontend via WebSocket")
            await self.broadcast_status("Waiting for frontend audio connection")
        
        self.is_active = True
        
        # Start ADK streaming task
        self.stream_task = asyncio.create_task(self._run_adk_stream())
        
        # Start proactive commentary loop only if proactive mode is enabled
        # This periodically nudges the model to react to recent context
        if PROACTIVE_AUDIO_MODE:
            if self.commentary_task is None or self.commentary_task.done():
                self.commentary_task = asyncio.create_task(self._proactive_commentary_loop())
                logger.info("Proactive commentary loop enabled")
        else:
            logger.info("Proactive commentary loop disabled (responsive mode)")
        
        logger.info("✓ ADK streaming started")
        await self.broadcast_status("StreamBuddy is now active!", "success")

        out = {
            "session_id": self.session_id,
            "mode": self.mode,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
        }
        if config.mode == "youtube" and youtube_connection_error:
            out["youtube_connection_error"] = youtube_connection_error
        return out
    
    async def _run_adk_stream(self):
        """Main streaming loop using raw Live API (google.genai)"""
        try:
            logger.info("Starting Live API stream")
            
            # System instruction for StreamBuddy personality
            # Following Google's best practices: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/best-practices
            # Structure: Persona → Conversational Rules → Guardrails
            if PROACTIVE_AUDIO_MODE:
                # Proactive mode: AI decides when to speak
                system_instruction = """**Persona:**
You are StreamBuddy, a casual and friendly AI co-host for live streaming. You speak naturally and conversationally, like a real person hanging out with friends.

**Conversational Rules:**

1. **Observe the stream:**  Watch and listen to what's happening.

2. **React proactively:** When you see or hear something interesting, funny, exciting, or notable happening on screen or in the audio, speak up! Don't wait to be asked - that's what makes you a great co-host.

3. **Know when to stay quiet:** Not everything needs commentary. Stay silent during:
   - Routine/repetitive actions
   - Quiet moments where the streamer is concentrating
   - When nothing particularly interesting is happening
   - Background noise or irrelevant audio

4. **Be spontaneous but accurate:** Use natural reactions and talk like you're genuinely watching with the streamer. Don't narrate everything - avoid making up details that you can't clearly observe.
"""
            else:
                # Responsive mode: AI responds to all user input quickly
                system_instruction = """**Persona:**
You are StreamBuddy, a casual and friendly AI co-host for live streaming. You speak naturally and conversationally, like a real person hanging out with friends.

**Conversational Rules:**

1. **Respond quickly:** When the user speaks to you, respond immediately in a natural, conversational way.

2. **Be concise:** Keep responses brief and to the point (2-3 sentences max) for natural conversation flow.

3. **Be engaging:** Show enthusiasm and interest in what the user is saying or doing.

4. **Stay natural:** Talk like a friend, not a robot. Use casual language and natural reactions.
"""
            
            # Configure streaming with proactive audio
            # Proactive Audio allows the model to respond without direct prompts
            # and ignore irrelevant input (e.g., background noise)
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
            
            # Enable proactive audio only if configured
            # Proactive audio: AI decides when to speak (adds latency but more natural for streaming)
            # Responsive mode: AI responds to all input immediately (lower latency)
            if PROACTIVE_AUDIO_MODE:
                config.proactivity = types.ProactivityConfig(
                    proactive_audio=True
                )
                logger.info("Proactive audio enabled (AI decides when to speak)")
            else:
                logger.info("Responsive mode enabled (AI responds to all input)")
            
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
                
                # Send initial greeting to start conversation
                try:
                    greeting_prompt = "Say a brief friendly greeting to let me know you're ready."
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=greeting_prompt)],
                        ),
                        turn_complete=True,
                    )
                    logger.info("Sent greeting prompt to AI")
                except Exception as e:
                    logger.warning(f"Failed to send greeting prompt: {e}")
                
                # Receive and process responses continuously
                # Buffer audio chunks for each model turn for smooth playback
                current_audio_buffer = bytearray()
                last_activity_time = time.time()
                
                while self.is_active:
                    try:
                        async for response in session.receive():
                            if not self.is_active:
                                logger.info("Session marked inactive, stopping receive loop")
                                break
                            
                            # Update activity timestamp
                            last_activity_time = time.time()
                            
                            # Handle server content
                            if hasattr(response, "server_content") and response.server_content:
                                server_content = response.server_content

                                # Handle interruption
                                if server_content.interrupted:
                                    logger.info("Response interrupted by user")
                                    await self.broadcast_status("AI interrupted", "info")
                                    # Clear any partial audio for this turn
                                    current_audio_buffer.clear()
                                    continue

                                # Handle model turn (AI response)
                                if server_content.model_turn:
                                    for part in server_content.model_turn.parts:
                                        # Handle audio data parts – accumulate them for this turn
                                        if hasattr(part, "inline_data") and part.inline_data:
                                            audio_bytes = part.inline_data.data

                                            if isinstance(audio_bytes, bytes) and len(audio_bytes) > 0:
                                                current_audio_buffer.extend(audio_bytes)

                                # When generation for this turn is complete, play the full buffer once
                                if getattr(server_content, "generation_complete", False) or getattr(
                                    server_content, "turn_complete", False
                                ):
                                    if current_audio_buffer:
                                        merged = bytes(current_audio_buffer)
                                        self.status["responses_generated"] += 1
                                        logger.info(
                                            f"Playing audio response: {len(merged)} bytes"
                                        )
                                        await self._play_audio_response(merged)
                                        await self.broadcast_status("AI responded", "info")
                                        current_audio_buffer.clear()
                                        
                                        # Update activity timestamp after successful response
                                        last_activity_time = time.time()
                        
                        # Check for timeout (no activity for 60 seconds)
                        if time.time() - last_activity_time > 60:
                            logger.warning("No activity for 60 seconds, connection may be stale")
                            break
                        
                        # After each turn completes, continue to next turn if still active
                        if not self.is_active:
                            break
                    
                    except asyncio.CancelledError:
                        logger.info("Receive loop cancelled")
                        break
                    except Exception as e:
                        # Check if it's a connection closure error
                        error_str = str(e)
                        error_type = str(type(e).__name__)
                        
                        if "ConnectionClosedError" in error_type or "1006" in error_str or "no close frame" in error_str:
                            logger.warning(f"Gemini connection closed: {error_str[:100]}")
                            await self.broadcast_status("Connection lost, reconnecting...", "warning")
                            # Break out of receive loop to trigger reconnection
                            break
                        else:
                            logger.error(f"Error in receive loop: {e}", exc_info=True)
                            # Don't break on other errors, try to continue
                            await asyncio.sleep(0.5)
                
                logger.info("Exited receive loop")
        
        except asyncio.CancelledError:
            logger.info("Live API stream cancelled")
        except Exception as e:
            error_msg = str(e)
            error_type = str(type(e).__name__)
            
            if "ConnectionClosedError" in error_type or "1006" in error_msg or "no close frame" in error_msg:
                logger.info(f"Gemini connection closed, will reconnect")
                await self.broadcast_status("Reconnecting to Gemini...", "info")
            else:
                logger.error(f"Error in Live API stream: {e}", exc_info=True)
                await self.broadcast_status(f"Stream error: {error_msg[:100]}", "error")
        finally:
            self.status["gemini_connected"] = False
            self.live_session = None
            logger.info("Live API stream ended")
            
            # Attempt reconnection if session is still active
            if self.is_active:
                logger.info("Session still active, reconnecting in 2 seconds...")
                await self.broadcast_status("Reconnecting to Gemini...", "info")
                await asyncio.sleep(2)
                if self.is_active:
                    logger.info("Restarting Live API stream...")
                    # Restart the streaming task
                    self.stream_task = asyncio.create_task(self._run_adk_stream())
    
    
    

    def _forward_video(self, frame):
        """
        Forward video frame to Gemini via ADK session.
        
        Note: Audio+video sessions are limited to 2 minutes without compression.
        Context window compression extends this to unlimited duration.
        """
        self.status["frames_captured"] += 1
        
        if hasattr(self, "live_session") and self.live_session and self.is_active:
            try:
                # Send frame to Live audio session for multimodal context
                # Video format: JPEG images, optimal resolution 768x768, 1 FPS
                # Schedule in the main event loop from thread
                if hasattr(self, "main_loop") and self.main_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.live_session.send_realtime_input(
                            media=types.Blob(
                                data=frame.frame_data,
                                mime_type="image/jpeg",
                            )
                        ),
                        self.main_loop,
                    )
                    
                    # Periodically send this frame to captioning model to get a
                    # concise, grounded textual description of what's on screen.
                    now = time.time()
                    if (
                        self.caption_client
                        and now - self.last_caption_time >= self.caption_interval_sec
                    ):
                        self.last_caption_time = now
                        asyncio.run_coroutine_threadsafe(
                            self._caption_and_send(frame),
                            self.main_loop,
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
    
    def _handle_chat_message(self, message: ChatMessage) -> None:
        """
        Callback from ChatCapture for each new YouTube live chat message.
        Stores recent messages and schedules analysis; does NOT directly
        send every message to the Live session.
        """
        # Update simple metrics and in-memory chat timeline
        self.status["chat_messages_captured"] += 1
        now = time.time()
        # Normalize timestamp to "now" in case of clock skew
        message.timestamp = now
        self.chat_timeline.append(message)
        # Keep only the last ~60 seconds of chat for quick context
        cutoff = now - 60.0
        self.chat_timeline = [
            m for m in self.chat_timeline if m.timestamp >= cutoff
        ]

        # Analysis is handled by the background _chat_analysis_loop

    async def _send_chat_message_to_live(self, message: ChatMessage) -> None:
        """
        Send a selected chat message into the Gemini Live session as user text,
        so the agent can choose to respond with audio.
        """
        if not self.live_session or not self.is_active:
            return

        try:
            # Build personality-aware prompt
            humor = self.personality.get("humor_level", 0.7)
            support = self.personality.get("supportiveness", 0.8)
            playful = self.personality.get("playfulness", 0.6)
            verbosity = self.personality.get("verbosity", "moderate")
            
            # Adjust response style based on personality
            style_hints = []
            if humor > 0.7:
                style_hints.append("be witty and humorous")
            if support > 0.7:
                style_hints.append("be encouraging and supportive")
            if playful > 0.7:
                style_hints.append("be playful and energetic")
            
            length_hint = {
                "concise": "Keep it very brief (1 sentence)",
                "moderate": "Keep it short and conversational (2-3 sentences)",
                "verbose": "You can elaborate a bit (3-4 sentences)"
            }.get(verbosity, "Keep it short and conversational")
            
            style_text = ", ".join(style_hints) if style_hints else "be natural and friendly"
            
            text_turn = (
                f"Viewer {message.username} says: {message.content}\n\n"
                f"As StreamBuddy, respond out loud if this message is interesting, emotional, funny, or needs a reply. "
                f"{length_hint}. Your style: {style_text}."
            )

            await self.live_session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=text_turn)],
                ),
                turn_complete=True,
            )
            await self.broadcast_status(
                f"Chat message sent to AI from {message.username}", "info"
            )
        except Exception as e:
            logger.error(f"Error sending chat message to Live session: {e}")

    async def _chat_analysis_loop(self) -> None:
        """
        Periodically analyze recent chat messages with a lightweight LLM to:
        - Select a few high-signal messages for StreamBuddy to respond to.
        - Compute a short summary/mood/topics for the UI.
        """
        try:
            # Wait until caption_client (helper client) is ready
            while self.is_active and not self.caption_client:
                await asyncio.sleep(0.2)

            if not self.is_active:
                return

            logger.info("Starting chat analysis loop")

            while (
                self.is_active
                and self.chat_capture is not None
                and self.status.get("chat_capturing")
            ):
                await asyncio.sleep(self.chat_analysis_interval_sec)

                if not self.is_active or not self.chat_timeline:
                    continue

                # Snapshot recent messages to avoid mutation during analysis
                # Only consider messages not already sent to the Live session
                recent_messages = [
                    m for m in self.chat_timeline[-50:]
                    if m.message_id not in self._sent_message_ids
                ]
                if not recent_messages:
                    continue

                # Build JSON-like lines for the helper model
                lines = []
                for m in recent_messages:
                    # Truncate overly long content for prompt safety
                    content = m.content
                    if len(content) > 300:
                        content = content[:297] + "..."
                    lines.append(
                        {
                            "message_id": m.message_id,
                            "username": m.username,
                            "content": content,
                        }
                    )

                import json

                analysis_prompt = (
                    "You are analyzing a fast YouTube live chat. "
                    "You will receive a JSON array called messages, where each item has "
                    "message_id, username, and content.\n\n"
                    "Your job:\n"
                    "1) Choose up to 3 messages that the streamer’s AI co-host should respond to "
                    "(interesting, emotional, questions, jokes, or representative of the crowd).\n"
                    "2) Provide a short overall summary of what the chat is talking about.\n"
                    "3) Provide a one- or two-word mood label (e.g., 'hyped', 'confused', 'toxic', "
                    "'chill', 'supportive').\n"
                    "4) Provide a few short topic tags.\n\n"
                    "Respond ONLY with minified JSON in this exact schema:\n"
                    '{\"selected_ids\":[\"id1\",\"id2\"],'
                    "\"summary\":\"...\","
                    "\"mood\":\"...\","
                    "\"topics\":[\"tag1\",\"tag2\"]}"
                    "\n\nmessages:\n"
                    f"{json.dumps(lines, ensure_ascii=False)}"
                )

                try:
                    decision_resp = await self.caption_client.aio.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[types.Part.from_text(text=analysis_prompt)],
                    )
                    raw_text = (getattr(decision_resp, "text", "") or "").strip()
                except Exception as e:
                    logger.error(f"Error calling chat analysis LLM: {e}", exc_info=True)
                    continue

                try:
                    # Strip markdown code fences if model wraps response
                    clean_text = raw_text.strip()
                    if clean_text.startswith("```"):
                        clean_text = clean_text.split("```")[1]
                        if clean_text.startswith("json"):
                            clean_text = clean_text[4:]
                        clean_text = clean_text.strip()
                    parsed = json.loads(clean_text)
                    selected_ids = parsed.get("selected_ids") or []
                    summary = parsed.get("summary") or ""
                    mood = parsed.get("mood") or ""
                    topics = parsed.get("topics") or []
                except Exception as e:
                    logger.error(f"Failed to parse chat analysis JSON: {e} - {raw_text}")
                    continue

                # Update high-level chat state for UI
                self.last_chat_summary = summary.strip() or None
                self.last_chat_mood = mood.strip() or None
                self.last_chat_topics = topics if isinstance(topics, list) else None
                self.last_chat_analysis_time = time.time()

                await self.broadcast_status("Chat analysis updated", "info")

                # Map IDs to messages for quick lookup
                msg_by_id = {m.message_id: m for m in recent_messages}

                # Send selected messages into Live session
                if self.live_session and selected_ids:
                    for mid in selected_ids[:3]:
                        m = msg_by_id.get(mid)
                        if not m:
                            continue
                        try:
                            await self._send_chat_message_to_live(m)
                            self._sent_message_ids.add(mid)
                        except Exception as e:
                            logger.error(
                                f"Failed to send selected chat message {mid} to Live: {e}"
                            )
                # Prune old sent IDs to avoid unbounded growth
                if len(self._sent_message_ids) > 500:
                    self._sent_message_ids = set(list(self._sent_message_ids)[-200:])

        except asyncio.CancelledError:
            logger.info("Chat analysis loop cancelled")
        except Exception as e:
            logger.error(f"Chat analysis loop crashed: {e}", exc_info=True)
    
    async def _play_audio_response(self, audio_bytes: bytes):
        """Play audio response through audio output service and broadcast to WebSocket clients"""
        try:
            # Broadcast audio to all connected WebSocket clients (frontend)
            if self.websocket_connections:
                disconnected = []
                for ws in self.websocket_connections:
                    try:
                        await ws.send_bytes(audio_bytes)
                        logger.debug(f"Sent {len(audio_bytes)} bytes to WebSocket client")
                    except Exception as e:
                        logger.warning(f"Failed to send audio to WebSocket client: {e}")
                        disconnected.append(ws)
                
                # Clean up disconnected clients
                for ws in disconnected:
                    if ws in self.websocket_connections:
                        self.websocket_connections.remove(ws)
            
            # Also play locally if audio output service is available (for local testing)
            if self.audio_output:
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
                logger.debug(f"Playing audio locally: {len(audio_bytes)} bytes")
        
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
    
    async def _maybe_trigger_voice_comment(self):
        """
        Use a lightweight LLM decision helper to determine whether we should
        send a voice trigger to the Live audio model, based on:
        - Recent screen caption timeline
        - Recent conversation / voice history
        
        This helps avoid unnecessary or overly frequent voice comments.
        """
        if not self.is_active or not self.caption_client or not self.live_session:
            return
        
        now = time.time()
        # Enforce a minimum spacing between voice triggers
        if now - self.last_voice_time < self.min_voice_interval_sec:
            return
        
        # Need some recent visual context
        if not self.screen_timeline:
            return
        
        # Build recent screen timeline (most recent last)
        recent_screen = self.screen_timeline[-8:]
        screen_lines = [f"- {e['summary']}" for e in recent_screen]
        screen_text = "\n".join(screen_lines)
        
        # Build recent conversation history (what we've asked the voice model to do)
        recent_conv = self.conversation_timeline[-5:]
        if recent_conv:
            conv_lines = [f"- {e['text']}" for e in recent_conv]
            conv_text = "\n".join(conv_lines)
        else:
            conv_text = "none"
        
        decision_prompt = (
            "You are a decision helper for an AI co-host. "
            "You receive a recent timeline of what has been visible on the screen, "
            "and a short history of what the AI has recently said.\n\n"
            "Recent screen timeline (most recent last):\n"
            f"{screen_text}\n\n"
            "Recent AI conversation (most recent last, may be 'none'):\n"
            f"{conv_text}\n\n"
            "Decide whether the AI should speak out loud RIGHT NOW.\n"
            "Say 'YES' if there was a notable, interesting, funny, surprising, or important change "
            "on screen that deserves a comment, and it would not be redundant with what was "
            "just said. Say 'NO' if things are routine, repetitive, or nothing important changed, "
            "or if speaking would be annoying.\n\n"
            "Respond with exactly one word: YES or NO."
        )
        
        try:
            decision_resp = await self.caption_client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_text(text=decision_prompt)],
            )
            decision_text = (getattr(decision_resp, "text", "") or "").strip().upper()
        except Exception as e:
            logger.error(f"Error calling decision helper LLM: {e}", exc_info=True)
            return
        
        if decision_text not in ("YES", "NO"):
            logger.debug(f"Decision helper returned unexpected text: {decision_text}")
            return
        
        if decision_text == "NO":
            logger.debug("Decision helper chose NO: skipping voice trigger")
            return
        
        # At this point, we should trigger a voice comment.
        self.last_voice_time = now
        
        # Build a concise context for the voice model based on the latest screen state.
        latest_summary = recent_screen[-1]["summary"]
        text_turn = (
            "Here is a brief description of the current screen:\n"
            f"- {latest_summary}\n\n"
            "As StreamBuddy, respond in a natural, conversational way based on this moment on screen."
            "You can speak freely and follow the flow of the situation, but keep your comments grounded in this situation."
        )
        
        await self.live_session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text_turn)],
            ),
            turn_complete=True,
        )
        
        # Record this in conversation timeline so future decisions know we spoke
        event = {
            "timestamp": now,
            "text": text_turn,
        }
        self.conversation_timeline.append(event)
        # Persist full conversation history to disk for this session
        self._append_conversation_log(event)
    
    async def _caption_and_send(self, frame):
        """
        Every ~5 seconds:
        - Use gemini-2.5-flash to get a concise, grounded description
          of the current frame.
        - Append it to an in-memory text timeline.
        - Voice triggering is handled separately by a decision helper,
          so we do NOT directly send a voice prompt from here.
        """
        try:
            if not self.is_active or not self.caption_client:
                return
            
            # Call Gemini 2.5 Flash (multimodal, non-Live) with image + prompt
            prompt = (
                "Describe concisely what is happening in this screen image. "
                "Focus only on what you can clearly see. "
            )
            
            response = await self.caption_client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=frame.frame_data,
                        mime_type="image/jpeg",
                    ),
                    types.Part.from_text(text=prompt),
                ],
            )
            
            summary = (getattr(response, "text", "") or "").strip()
            if not summary:
                return
            
            # Record in in-memory timeline (sliding window for fast reasoning)
            now = time.time()
            self.screen_timeline.append({"timestamp": now, "summary": summary})
            # Keep only the last ~60 seconds of history
            cutoff = now - 60.0
            self.screen_timeline = [
                e for e in self.screen_timeline if e["timestamp"] >= cutoff
            ]
            
            # Persist full caption log to disk for this session
            self._append_caption_log(
                {
                    "timestamp": now,
                    "summary": summary,
                }
            )
            
            logger.info(f"Frame caption (timeline event): {summary}")
            
        except Exception as e:
            logger.error(f"Error in frame captioning pipeline: {e}", exc_info=True)
    
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
        if self.audio_capture:
            self.audio_capture.stop_capture()
            self.status["audio_capturing"] = False
        if self.chat_capture:
            self.chat_capture.stop_capture()
            self.status["chat_capturing"] = False
        if self.youtube_connection:
            self.youtube_connection.disconnect()
        
        # Stop audio output
        if self.audio_output:
            await self.audio_output.stop()
        
        # Cancel tasks
        if self.stream_task:
            self.stream_task.cancel()
        if self.commentary_task:
            self.commentary_task.cancel()
        if self.chat_analysis_task:
            self.chat_analysis_task.cancel()
        
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        
        await self.broadcast_status("StreamBuddy stopped", "success")
        
        return {
            "session_id": self.session_id,
            "duration_seconds": duration,
            "final_status": self.status,
            "logs_dir": str(self.session_log_dir) if self.session_log_dir else None,
        }
    
    # ------------------------------------------------------------------
    # Session logging helpers (persist full caption + conversation logs)
    # ------------------------------------------------------------------
    
    def _append_caption_log(self, event: Dict[str, Any]) -> None:
        """Append a caption event to the persistent JSONL log for this session."""
        if not self.caption_log_path:
            return
        try:
            payload = {
                "session_id": self.session_id,
                "type": "caption",
                **event,
            }
            with self.caption_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append caption log: {e}", exc_info=True)
    
    def _append_conversation_log(self, event: Dict[str, Any]) -> None:
        """Append a conversation event to the persistent JSONL log for this session."""
        if not self.conversation_log_path:
            return
        try:
            payload = {
                "session_id": self.session_id,
                "type": "conversation",
                **event,
            }
            with self.conversation_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append conversation log: {e}", exc_info=True)
    
    async def _proactive_commentary_loop(self):
        """
        Periodically prompt the model to provide short, co-host style reactions.
        
        Rationale:
        - In practice, relying only on proactive audio can lead to the model
          speaking once and then staying silent.
        - This loop gently asks the model to react to the last few seconds
          of audio/video, so the agent keeps engaging the streamer.
        """
        try:
            # Wait until the Live session is connected
            while self.is_active and (self.live_session is None or not self.status.get("gemini_connected")):
                await asyncio.sleep(0.2)
            
            if not self.is_active:
                return
            
            logger.info("Starting proactive commentary loop")
            
            # Main loop: every N seconds, consider asking for a brief reaction.
            # A separate decision helper LLM will decide whether we should
            # actually trigger a voice response based on the recent screen
            # timeline and conversation history.
            while self.is_active and self.live_session is not None and self.status.get("gemini_connected"):
                # Tune this interval to how chatty you want StreamBuddy to be
                await asyncio.sleep(20)
                
                if not self.is_active or self.live_session is None:
                    break
                
                try:
                    await self._maybe_trigger_voice_comment()
                except Exception as e:
                    logger.error(f"Error in proactive commentary decision loop: {e}", exc_info=True)
                    await asyncio.sleep(5)
        
        except asyncio.CancelledError:
            logger.info("Proactive commentary loop cancelled")
        except Exception as e:
            logger.error(f"Proactive commentary loop crashed: {e}", exc_info=True)
    
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
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        FRONTEND_URL,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

YOUTUBE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
YOUTUBE_OAUTH_CLIENT_SECRET_FILE = os.getenv(
    "YOUTUBE_OAUTH_CLIENT_SECRET_FILE", "client_secret.json"
)
YOUTUBE_OAUTH_REDIRECT_URI = os.getenv(
    "YOUTUBE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/youtube/callback"
)

@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Simple landing page with links to key actions, including YouTube auth.
    """
    html = """
    <html>
      <head><title>StreamBuddy Backend</title></head>
      <body>
        <h1>StreamBuddy Backend</h1>
        <p>Use these links during development:</p>
        <ul>
          <li><a href="/auth/youtube/start">Connect your YouTube account</a></li>
          <li><a href="/docs">Open FastAPI docs</a></li>
          <li><a href="/api/status">View current session status (JSON)</a></li>
        </ul>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/api/status")
async def get_status():
    """Get current session status"""
    return session_manager.get_status()


@app.get("/api/youtube/status")
async def get_youtube_status(client_session_id: Optional[str] = None):
    """Return whether a YouTube OAuth token is stored (account connected)."""
    # Check session-specific token only
    if client_session_id:
        token_dir = Path("youtube_tokens")
        token_path = token_dir / f"{client_session_id}.json"
    else:
        # No session ID provided, can't check status
        return {"connected": False}
    
    connected = False
    if token_path.exists():
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            connected = bool(data.get("refresh_token") or data.get("access_token"))
        except Exception:
            pass
    return {"connected": connected}

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

@app.post("/api/personality/update")
async def update_personality(request: UpdatePersonalityRequest):
    """Update personality settings during active session"""
    try:
        if not session_manager.is_active:
            raise HTTPException(status_code=400, detail="No active session")
        
        # Update personality settings
        updates = {}
        if request.humor_level is not None:
            updates["humor_level"] = request.humor_level
        if request.supportiveness is not None:
            updates["supportiveness"] = request.supportiveness
        if request.playfulness is not None:
            updates["playfulness"] = request.playfulness
        if request.verbosity is not None:
            updates["verbosity"] = request.verbosity
        if request.response_frequency is not None:
            updates["response_frequency"] = request.response_frequency
        
        session_manager.personality.update(updates)
        logger.info(f"Personality updated: {updates}")
        
        return {
            "success": True,
            "personality": session_manager.personality
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update personality: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates and audio streaming"""
    await websocket.accept()
    session_manager.websocket_connections.append(websocket)
    logger.info("WebSocket client connected")
    
    try:
        while True:
            try:
                # Receive data from client (can be text or binary)
                message = await websocket.receive()
                
                # Check if it's a disconnect message
                if message.get("type") == "websocket.disconnect":
                    logger.info("WebSocket disconnect message received")
                    break
                
                # Handle binary audio data from frontend microphone
                if "bytes" in message:
                    audio_bytes = message["bytes"]
                    # Forward audio to Gemini Live session
                    if session_manager.is_active and session_manager.live_session:
                        try:
                            await session_manager.live_session.send_realtime_input(
                                audio=types.Blob(
                                    data=audio_bytes,
                                    mime_type="audio/pcm;rate=16000"
                                )
                            )
                            logger.debug(f"Forwarded {len(audio_bytes)} bytes of audio from frontend")
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            error_msg = str(e)
                            if "ConnectionClosedError" in str(type(e).__name__) or "1006" in error_msg or "no close frame" in error_msg:
                                logger.debug(f"Gemini connection closed while forwarding audio (will reconnect)")
                                # Don't spam warnings - reconnection is automatic
                            else:
                                logger.error(f"Error forwarding frontend audio: {e}")
                    else:
                        logger.debug("Received audio but session not active or not connected")
                
                # Handle text messages (control messages)
                elif "text" in message:
                    data = json.loads(message["text"])
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
            
            except RuntimeError as e:
                # Handle "Cannot call receive once disconnect received" error
                if "disconnect" in str(e).lower():
                    logger.info("WebSocket disconnected")
                    break
                else:
                    raise

                    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if websocket in session_manager.websocket_connections:
            session_manager.websocket_connections.remove(websocket)


@app.get("/auth/youtube/start")
async def youtube_oauth_start(client_session_id: Optional[str] = None):
    """
    Start YouTube OAuth flow.
    Redirects the user to Google's consent screen. Requires a client_secret.json file
    or YOUTUBE_OAUTH_CLIENT_SECRET_FILE path, and YOUTUBE_OAUTH_REDIRECT_URI must
    match the redirect URI configured in the Google Cloud Console.
    
    Args:
        client_session_id: Optional session ID to associate the token with a specific user
    """
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-auth-oauthlib is not installed. "
            "Install dependencies with `pip install -r requirements.txt`.",
        )

    if not os.path.exists(YOUTUBE_OAUTH_CLIENT_SECRET_FILE):
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth client secrets file not found at "
                f"{YOUTUBE_OAUTH_CLIENT_SECRET_FILE}. "
                "Download your OAuth 2.0 client JSON from Google Cloud Console and "
                "save it as this file, or set YOUTUBE_OAUTH_CLIENT_SECRET_FILE."
            ),
        )

    flow = Flow.from_client_secrets_file(
        YOUTUBE_OAUTH_CLIENT_SECRET_FILE,
        scopes=YOUTUBE_OAUTH_SCOPES,
        redirect_uri=YOUTUBE_OAUTH_REDIRECT_URI,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",  # Don't include extra scopes
        prompt="consent",
        state=client_session_id or "default",  # Pass session ID via state parameter
    )

    return RedirectResponse(auth_url)


@app.get("/auth/youtube/callback")
async def youtube_oauth_callback(request: Request):
    """
    OAuth callback endpoint for YouTube.
    Exchanges the authorization code for tokens and returns a JSON object that
    can be pasted into the UI as youtube_oauth_token for testing.
    """
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-auth-oauthlib is not installed. "
            "Install dependencies with `pip install -r requirements.txt`.",
        )

    if "code" not in request.query_params:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Allow HTTP redirect_uri on localhost (oauthlib requires HTTPS by default)
    if "localhost" in YOUTUBE_OAUTH_REDIRECT_URI or "127.0.0.1" in YOUTUBE_OAUTH_REDIRECT_URI:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    if not os.path.exists(YOUTUBE_OAUTH_CLIENT_SECRET_FILE):
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth client secrets file not found at "
                f"{YOUTUBE_OAUTH_CLIENT_SECRET_FILE}."
            ),
        )

    flow = Flow.from_client_secrets_file(
        YOUTUBE_OAUTH_CLIENT_SECRET_FILE,
        scopes=YOUTUBE_OAUTH_SCOPES,
        redirect_uri=YOUTUBE_OAUTH_REDIRECT_URI,
    )
    
    # Disable strict scope validation - Google adds openid/profile/email automatically
    flow.oauth2session._client.scope = None

    # Use the same redirect_uri as in the auth request (localhost vs 127.0.0.1 must
    # match), and keep only the query string from the incoming request.
    from urllib.parse import urlparse
    parsed = urlparse(str(request.url))
    redirect_base = YOUTUBE_OAUTH_REDIRECT_URI.split("?")[0]
    authorization_response = f"{redirect_base}?{parsed.query}"

    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        logger.error(f"Failed to fetch YouTube OAuth token: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch OAuth tokens: {str(e)}")

    credentials = flow.credentials

    token_payload = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or []),
    }

    # Persist token payload locally for development so YouTube mode can use it
    # automatically without copy/paste.
    # Save with session ID if provided via state parameter
    try:
        client_session_id = request.query_params.get("state", "default")
        
        # Create youtube_tokens directory if it doesn't exist
        token_dir = Path("youtube_tokens")
        token_dir.mkdir(exist_ok=True)
        
        if client_session_id and client_session_id != "default":
            token_path = token_dir / f"{client_session_id}.json"
        else:
            token_path = token_dir / "default.json"
        
        token_path.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")
        logger.info(f"YouTube OAuth tokens saved to {token_path}")
    except Exception as e:
        logger.error(f"Failed to save YouTube OAuth token to file: {e}", exc_info=True)

    # Redirect back to frontend so user lands in the app
    redirect_url = f"{FRONTEND_URL.rstrip('/')}/?youtube_connected=1"
    return RedirectResponse(url=redirect_url, status_code=302)

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
