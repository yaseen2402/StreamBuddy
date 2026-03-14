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
        # Perception / captioning client (non-Live)
        self.caption_client: Optional[genai.Client] = None
        
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
        
        # Captioning / perception settings
        self.last_caption_time: float = 0.0
        # Take a screenshot less frequently for perception (free-tier friendly)
        # 30 seconds → at most ~2 caption calls per minute.
        self.caption_interval_sec: float = 30.0
        
        # Text timeline of what has been happening on screen
        # Each entry: {"timestamp": float, "summary": str}
        self.screen_timeline: list[Dict[str, Any]] = []
        
        # Conversation / voice timeline (what we've asked the voice model to do)
        # Each entry: {"timestamp": float, "text": str}
        self.conversation_timeline: list[Dict[str, Any]] = []
        
        # Voice triggering controls
        self.last_voice_time: float = 0.0
        # Minimum spacing between voice triggers (seconds).
        # 45 seconds → at most ~1–2 decision calls per minute.
        self.min_voice_interval_sec: float = 45.0
        
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
        self.session_id = f"adk_session_{int(datetime.now().timestamp())}"
        self.start_time = datetime.now()
        
        # Create a directory for this session's persistent logs
        try:
            base_log_dir = Path("streambuddy_sessions")
            base_log_dir.mkdir(parents=True, exist_ok=True)
            self.session_log_dir = base_log_dir / self.session_id
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
        
        # Start proactive commentary loop in background
        # This periodically nudges the model to react to recent context,
        # so the agent doesn't go silent after the first response.
        if self.commentary_task is None or self.commentary_task.done():
            self.commentary_task = asyncio.create_task(self._proactive_commentary_loop())
        
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
            # Following Google's best practices: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/best-practices
            # Structure: Persona → Conversational Rules → Guardrails
            # With Proactive Audio enabled, the model can initiate responses based on context
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
            
            # Enable proactive audio (requires v1alpha API version)
            # Proactive audio allows the model to initiate responses
            # based on context without explicit user prompts
            config.proactivity = types.ProactivityConfig(
                proactive_audio=True
            )
            logger.info("Proactive audio enabled")
            
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
                
                # Optional: Send a greeting prompt to have the AI initiate conversation
                # Per best practices: "To have Gemini Live API initiate the conversation, 
                # include a prompt asking it to greet the user or begin the conversation."
                try:
                    greeting_prompt = "Hey StreamBuddy! Say hi and let me know you're ready to co-host."
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
                # We buffer audio chunks for each model turn so that
                # a single spoken response is played back smoothly,
                # instead of many tiny, clipped fragments.
                current_audio_buffer = bytearray()
                while self.is_active:
                    try:
                        async for response in session.receive():
                            if not self.is_active:
                                logger.info("Session marked inactive, stopping receive loop")
                                break
                            
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
                                            f"Playing merged audio response: {len(merged)} bytes "
                                            f"(chunks_in_turn={len(current_audio_buffer)})"
                                        )
                                        await self._play_audio_response(merged)
                                        await self.broadcast_status("AI responded", "info")
                                        current_audio_buffer.clear()
                        
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
