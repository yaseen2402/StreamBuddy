"""
Audio Output Service Module

This module implements the Audio Output Service for StreamBuddy, responsible for
delivering AI-generated voice responses to the stream audio mixer with low latency.

Key features:
- Audio mixer connection initialization with automatic reinitialization on failure
- Sequential response queue management with priority support
- Audio streaming playback (24kHz, PCM/Opus, mono)
- Playback state tracking and interruption support
- Voice consistency using Gemini Live API (Puck voice)

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 12.3
"""

import asyncio
import logging
import time
from typing import Optional, Callable, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import pyaudio

from streambuddy_agent.models import AudioData, AIResponse, Priority

# Configure logging
logger = logging.getLogger(__name__)


class PlaybackState(Enum):
    """Playback states for audio output"""
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class ConnectionState(Enum):
    """Connection states for audio mixer"""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


@dataclass
class MixerConfig:
    """
    Configuration for audio mixer connection.
    
    Attributes:
        sample_rate: Audio sample rate in Hz (default: 24000 for Gemini Live API)
        channels: Number of audio channels (default: 1 for mono)
        format: Audio format (default: pyaudio.paInt16 for PCM)
        chunk_size: Size of audio chunks for streaming (default: 1024)
        device_index: Audio device index (None for default device)
        max_reconnect_attempts: Maximum reconnection attempts (default: 5)
        reconnect_delay: Delay between reconnection attempts in seconds (default: 1.0)
    """
    sample_rate: int = 24000
    channels: int = 1
    format: int = pyaudio.paInt16
    chunk_size: int = 1024
    device_index: Optional[int] = None
    max_reconnect_attempts: int = 5
    reconnect_delay: float = 1.0


@dataclass
class QueueConfig:
    """
    Configuration for response queue management.
    
    Attributes:
        max_queue_size: Maximum number of responses in queue (default: 5)
        drop_policy: Policy for dropping responses when queue is full ("oldest" or "newest")
        enable_priority: Enable priority queue support (default: True)
    """
    max_queue_size: int = 5
    drop_policy: str = "oldest"
    enable_priority: bool = True
    
    def __post_init__(self):
        """Validate QueueConfig"""
        if self.max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")
        if self.drop_policy not in ["oldest", "newest"]:
            raise ValueError("drop_policy must be 'oldest' or 'newest'")


@dataclass
class QueuedResponse:
    """
    Represents a queued audio response.
    
    Attributes:
        response: The AI response to play
        priority: Priority level for queue ordering
        queued_at: Timestamp when response was queued
        audio_data: Audio data to play
    """
    response: AIResponse
    priority: Priority
    queued_at: float
    audio_data: AudioData


@dataclass
class PlaybackMetrics:
    """
    Metrics for audio playback monitoring.
    
    Attributes:
        total_responses_played: Total number of responses played
        total_responses_queued: Total number of responses queued
        total_responses_dropped: Total number of responses dropped
        total_playback_time_ms: Total playback time in milliseconds
        total_queue_time_ms: Total time responses spent in queue
        current_queue_size: Current number of responses in queue
        playback_errors: Number of playback errors
        connection_failures: Number of connection failures
        last_playback_time: Timestamp of last playback
        last_error_time: Timestamp of last error
    """
    total_responses_played: int = 0
    total_responses_queued: int = 0
    total_responses_dropped: int = 0
    total_playback_time_ms: float = 0.0
    total_queue_time_ms: float = 0.0
    current_queue_size: int = 0
    playback_errors: int = 0
    connection_failures: int = 0
    last_playback_time: Optional[float] = None
    last_error_time: Optional[float] = None


class AudioOutputService:
    """
    Manages audio output for StreamBuddy AI responses.
    
    Delivers AI-generated voice responses to the stream audio mixer with:
    - Low latency (< 2 seconds end-to-end)
    - Sequential playback with priority support
    - Automatic connection recovery
    - Playback state tracking and interruption support
    
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 12.3
    """
    
    def __init__(
        self,
        mixer_config: Optional[MixerConfig] = None,
        queue_config: Optional[QueueConfig] = None
    ):
        """
        Initialize Audio Output Service.
        
        Args:
            mixer_config: Configuration for audio mixer (uses defaults if None)
            queue_config: Configuration for response queue (uses defaults if None)
        """
        self.mixer_config = mixer_config or MixerConfig()
        self.queue_config = queue_config or QueueConfig()
        
        # Connection state
        self.connection_state = ConnectionState.DISCONNECTED
        self.audio = None
        self.stream = None
        self._reconnect_attempts = 0
        
        # Playback state
        self.playback_state = PlaybackState.IDLE
        self.current_response_id: Optional[str] = None
        self._stop_requested = False
        
        # Response queues (high, normal, low priority)
        self._high_priority_queue: deque = deque()
        self._normal_priority_queue: deque = deque()
        self._low_priority_queue: deque = deque()
        
        # Metrics
        self.metrics = PlaybackMetrics()
        
        # Processing task
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(
            f"Audio Output Service initialized: "
            f"sample_rate={self.mixer_config.sample_rate}Hz, "
            f"channels={self.mixer_config.channels}, "
            f"max_queue_size={self.queue_config.max_queue_size}"
        )
    
    def initialize_audio_connection(self) -> bool:
        """
        Initialize connection to audio mixer.
        
        Creates PyAudio instance and opens audio stream for playback.
        Implements connection initialization as specified in Requirements 3.3, 12.3.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.connection_state = ConnectionState.CONNECTING
            logger.info("Initializing audio mixer connection...")
            
            # Create PyAudio instance
            self.audio = pyaudio.PyAudio()
            
            # Open audio stream
            self.stream = self.audio.open(
                format=self.mixer_config.format,
                channels=self.mixer_config.channels,
                rate=self.mixer_config.sample_rate,
                output=True,
                frames_per_buffer=self.mixer_config.chunk_size,
                output_device_index=self.mixer_config.device_index
            )
            
            self.connection_state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            
            logger.info(
                f"Audio mixer connection established: "
                f"device_index={self.mixer_config.device_index}, "
                f"sample_rate={self.mixer_config.sample_rate}Hz"
            )
            
            return True
            
        except Exception as e:
            self.connection_state = ConnectionState.FAILED
            self.metrics.connection_failures += 1
            logger.error(f"Failed to initialize audio connection: {e}")
            return False
    
    def _reinitialize_connection(self) -> bool:
        """
        Reinitialize audio connection after failure.
        
        Implements connection reinitialization on failure as specified in
        Requirements 12.3.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        if self._reconnect_attempts >= self.mixer_config.max_reconnect_attempts:
            logger.error(
                f"Max reconnection attempts ({self.mixer_config.max_reconnect_attempts}) "
                f"reached, giving up"
            )
            self.connection_state = ConnectionState.FAILED
            return False
        
        self._reconnect_attempts += 1
        self.connection_state = ConnectionState.RECONNECTING
        
        logger.info(
            f"Attempting to reinitialize audio connection "
            f"(attempt {self._reconnect_attempts}/{self.mixer_config.max_reconnect_attempts})"
        )
        
        # Close existing connection if any
        self._close_connection()
        
        # Wait before reconnecting
        time.sleep(self.mixer_config.reconnect_delay)
        
        # Try to reconnect
        return self.initialize_audio_connection()

    
    def _close_connection(self) -> None:
        """Close audio connection and cleanup resources."""
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            
            if self.audio is not None:
                self.audio.terminate()
                self.audio = None
            
            logger.debug("Audio connection closed")
            
        except Exception as e:
            logger.warning(f"Error closing audio connection: {e}")
    
    def queue_response(
        self,
        audio_data: AudioData,
        response: AIResponse,
        priority: Priority = Priority.MEDIUM
    ) -> bool:
        """
        Queue an audio response for playback.
        
        Implements response queue management with priority support and maximum
        queue size as specified in Requirements 3.4.
        
        Args:
            audio_data: Audio data to play
            response: AI response metadata
            priority: Priority level for queue ordering
            
        Returns:
            True if response was queued, False if dropped
        """
        queue_start = time.time()
        
        # Create queued response
        queued_response = QueuedResponse(
            response=response,
            priority=priority,
            queued_at=queue_start,
            audio_data=audio_data
        )
        
        # Select appropriate queue based on priority
        if priority == Priority.HIGH:
            target_queue = self._high_priority_queue
        elif priority == Priority.MEDIUM:
            target_queue = self._normal_priority_queue
        else:
            target_queue = self._low_priority_queue
        
        # Check total queue size
        total_size = (
            len(self._high_priority_queue) +
            len(self._normal_priority_queue) +
            len(self._low_priority_queue)
        )
        
        # Handle queue overflow
        if total_size >= self.queue_config.max_queue_size:
            if self.queue_config.drop_policy == "oldest":
                # Drop oldest response from lowest priority non-empty queue
                if self._low_priority_queue:
                    dropped = self._low_priority_queue.popleft()
                elif self._normal_priority_queue:
                    dropped = self._normal_priority_queue.popleft()
                elif self._high_priority_queue:
                    dropped = self._high_priority_queue.popleft()
                else:
                    # Should not happen, but handle gracefully
                    logger.warning("Queue full but no responses to drop")
                    return False
                
                self.metrics.total_responses_dropped += 1
                # Recalculate total size after dropping
                total_size = (
                    len(self._high_priority_queue) +
                    len(self._normal_priority_queue) +
                    len(self._low_priority_queue)
                )
                logger.warning(
                    f"Queue full, dropped oldest response: {dropped.response.response_id} "
                    f"(priority={dropped.priority.value})"
                )
            else:  # drop_policy == "newest"
                # Drop the new response
                self.metrics.total_responses_dropped += 1
                logger.warning(
                    f"Queue full, dropping new response: {response.response_id} "
                    f"(priority={priority.value})"
                )
                return False
        
        # Add to queue
        target_queue.append(queued_response)
        self.metrics.total_responses_queued += 1
        self.metrics.current_queue_size = total_size + 1
        
        logger.debug(
            f"Queued response: {response.response_id} "
            f"(priority={priority.value}, queue_size={self.metrics.current_queue_size})"
        )
        
        return True
    
    def _get_next_response(self) -> Optional[QueuedResponse]:
        """
        Get next response from queue based on priority.
        
        Implements sequential response queuing with priority support as
        specified in Requirements 3.4.
        
        Returns:
            Next queued response or None if queue is empty
        """
        # Check high priority queue first
        if self._high_priority_queue:
            response = self._high_priority_queue.popleft()
            self.metrics.current_queue_size -= 1
            return response
        
        # Then normal priority queue
        if self._normal_priority_queue:
            response = self._normal_priority_queue.popleft()
            self.metrics.current_queue_size -= 1
            return response
        
        # Finally low priority queue
        if self._low_priority_queue:
            response = self._low_priority_queue.popleft()
            self.metrics.current_queue_size -= 1
            return response
        
        return None
    
    def has_queued_responses(self) -> bool:
        """
        Check if there are any queued responses.
        
        Returns:
            True if queue has responses, False otherwise
        """
        return (
            len(self._high_priority_queue) > 0 or
            len(self._normal_priority_queue) > 0 or
            len(self._low_priority_queue) > 0
        )
    
    def is_playing(self) -> bool:
        """
        Check if audio is currently playing.
        
        Returns:
            True if playing, False otherwise
        """
        return self.playback_state == PlaybackState.PLAYING
    
    async def play_audio(self, audio_data: AudioData) -> bool:
        """
        Play audio data through the mixer.
        
        Implements audio streaming playback (24kHz, PCM/Opus, mono) with
        playback state tracking as specified in Requirements 3.1, 3.3.
        
        Args:
            audio_data: Audio data to play
            
        Returns:
            True if playback successful, False otherwise
        """
        if self.connection_state != ConnectionState.CONNECTED:
            logger.error("Cannot play audio: not connected to mixer")
            return False
        
        try:
            self.playback_state = PlaybackState.PLAYING
            playback_start = time.time()
            
            # Stream audio in chunks
            audio_bytes = audio_data.audio_bytes
            chunk_size = self.mixer_config.chunk_size
            
            for i in range(0, len(audio_bytes), chunk_size):
                # Check if stop was requested
                if self._stop_requested:
                    logger.info("Playback stopped by interruption")
                    self._stop_requested = False
                    self.playback_state = PlaybackState.STOPPED
                    return False
                
                # Get chunk
                chunk = audio_bytes[i:i + chunk_size]
                
                # Write to stream
                self.stream.write(chunk)
                
                # Small async yield to allow other tasks to run
                await asyncio.sleep(0)
            
            # Playback completed successfully
            playback_duration = (time.time() - playback_start) * 1000
            self.metrics.total_playback_time_ms += playback_duration
            self.metrics.total_responses_played += 1
            self.metrics.last_playback_time = time.time()
            self.playback_state = PlaybackState.IDLE
            
            logger.debug(
                f"Audio playback completed: duration={playback_duration:.2f}ms, "
                f"size={len(audio_bytes)} bytes"
            )
            
            return True
            
        except Exception as e:
            self.playback_state = PlaybackState.ERROR
            self.metrics.playback_errors += 1
            self.metrics.last_error_time = time.time()
            logger.error(f"Audio playback error: {e}")
            
            # Try to reinitialize connection
            if not self._reinitialize_connection():
                logger.error("Failed to recover from playback error")
            
            return False
    
    def stop_playback(self, response_id: Optional[str] = None) -> bool:
        """
        Stop current audio playback.
        
        Implements playback stop functionality for interruptions as specified
        in Requirements 3.3, 6.2.
        
        Args:
            response_id: Optional response ID to stop (if None, stops current)
            
        Returns:
            True if stop signal sent, False otherwise
        """
        if self.playback_state != PlaybackState.PLAYING:
            logger.debug("No audio currently playing")
            return False
        
        # Check if specific response ID matches current
        if response_id is not None and response_id != self.current_response_id:
            logger.warning(
                f"Stop requested for {response_id} but currently playing "
                f"{self.current_response_id}"
            )
            return False
        
        # Set stop flag
        self._stop_requested = True
        
        logger.info(
            f"Stop playback requested: response_id={response_id or self.current_response_id}"
        )
        
        return True
    
    async def _process_queue(self) -> None:
        """
        Process response queue continuously.
        
        Implements queue processing with < 50ms overhead as specified in
        Requirements 3.4.
        """
        logger.info("Starting queue processing")
        
        while self._running:
            try:
                # Get next response from queue
                queued_response = self._get_next_response()
                
                if queued_response is None:
                    # No responses in queue, wait briefly
                    await asyncio.sleep(0.01)  # 10ms
                    continue
                
                # Calculate queue time
                queue_time = (time.time() - queued_response.queued_at) * 1000
                self.metrics.total_queue_time_ms += queue_time
                
                # Set current response ID
                self.current_response_id = queued_response.response.response_id
                
                logger.debug(
                    f"Processing response: {self.current_response_id} "
                    f"(queue_time={queue_time:.2f}ms, priority={queued_response.priority.value})"
                )
                
                # Play audio
                success = await self.play_audio(queued_response.audio_data)
                
                if not success:
                    logger.warning(
                        f"Failed to play response: {self.current_response_id}"
                    )
                
                # Clear current response ID
                self.current_response_id = None
                
                # Small delay to ensure < 50ms overhead between responses
                await asyncio.sleep(0.01)  # 10ms
                
            except Exception as e:
                logger.error(f"Error processing queue: {e}")
                await asyncio.sleep(0.1)  # Wait before retrying
        
        logger.info("Queue processing stopped")
    
    async def start(self) -> bool:
        """
        Start the Audio Output Service.
        
        Initializes audio connection and starts queue processing.
        
        Returns:
            True if started successfully, False otherwise
        """
        if self._running:
            logger.warning("Audio Output Service already running")
            return True
        
        # Initialize audio connection
        if not self.initialize_audio_connection():
            logger.error("Failed to start: audio connection initialization failed")
            return False
        
        # Start queue processing
        self._running = True
        self._processing_task = asyncio.create_task(self._process_queue())
        
        logger.info("Audio Output Service started")
        return True
    
    async def stop(self) -> None:
        """
        Stop the Audio Output Service.
        
        Stops queue processing and closes audio connection.
        """
        if not self._running:
            logger.warning("Audio Output Service not running")
            return
        
        logger.info("Stopping Audio Output Service...")
        
        # Stop queue processing
        self._running = False
        
        if self._processing_task is not None:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
            self._processing_task = None
        
        # Stop any current playback
        if self.playback_state == PlaybackState.PLAYING:
            self.stop_playback()
        
        # Close audio connection
        self._close_connection()
        self.connection_state = ConnectionState.DISCONNECTED
        
        logger.info("Audio Output Service stopped")
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics for monitoring.
        
        Returns:
            Dictionary of current metrics
        """
        return {
            "connection_state": self.connection_state.value,
            "playback_state": self.playback_state.value,
            "current_response_id": self.current_response_id,
            "total_responses_played": self.metrics.total_responses_played,
            "total_responses_queued": self.metrics.total_responses_queued,
            "total_responses_dropped": self.metrics.total_responses_dropped,
            "current_queue_size": self.metrics.current_queue_size,
            "avg_playback_time_ms": (
                self.metrics.total_playback_time_ms / self.metrics.total_responses_played
                if self.metrics.total_responses_played > 0 else 0
            ),
            "avg_queue_time_ms": (
                self.metrics.total_queue_time_ms / self.metrics.total_responses_played
                if self.metrics.total_responses_played > 0 else 0
            ),
            "playback_errors": self.metrics.playback_errors,
            "connection_failures": self.metrics.connection_failures,
            "last_playback_time": self.metrics.last_playback_time,
            "last_error_time": self.metrics.last_error_time
        }
    
    def clear_queue(self) -> int:
        """
        Clear all queued responses.
        
        Returns:
            Number of responses cleared
        """
        count = (
            len(self._high_priority_queue) +
            len(self._normal_priority_queue) +
            len(self._low_priority_queue)
        )
        
        self._high_priority_queue.clear()
        self._normal_priority_queue.clear()
        self._low_priority_queue.clear()
        
        self.metrics.current_queue_size = 0
        
        logger.info(f"Cleared {count} responses from queue")
        
        return count
