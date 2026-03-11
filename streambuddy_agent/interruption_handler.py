"""
Interruption Handler Module

This module implements graceful interruption handling for StreamBuddy, detecting
streamer speech during AI response playback and stopping the response within 300ms.

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""

import logging
import time
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field
from threading import Thread, Event, Lock
from queue import Queue, Empty
import numpy as np

from streambuddy_agent.models import AudioData

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class InterruptionConfig:
    """Configuration for interruption detection"""
    vad_threshold: float = 0.5  # Voice activity detection threshold (0.0-1.0)
    sustained_speech_ms: int = 300  # Minimum speech duration to trigger interruption
    sample_rate: int = 24000  # Audio sample rate in Hz
    chunk_duration_ms: int = 100  # Audio chunk duration for VAD processing
    max_stop_latency_ms: int = 300  # Maximum time to stop playback after detection


@dataclass
class InterruptionMetrics:
    """Metrics for interruption handler monitoring"""
    interruptions_detected: int = 0
    false_positives_prevented: int = 0
    total_detection_time_ms: float = 0.0
    total_stop_latency_ms: float = 0.0
    average_stop_latency_ms: float = 0.0
    last_interruption_time: Optional[float] = None
    speech_chunks_detected: int = 0
    non_speech_chunks: int = 0


@dataclass
class InterruptionContext:
    """Context information about an interruption"""
    interruption_id: str
    timestamp: float
    interrupted_response_id: Optional[str]
    detection_latency_ms: float
    stop_latency_ms: float
    audio_data: Optional[AudioData] = None


class InterruptionHandler:
    """
    Manages graceful interruption handling for StreamBuddy.
    
    Detects streamer speech during AI response playback using voice activity
    detection (VAD) and stops audio output within 300ms.
    
    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    
    def __init__(
        self,
        config: Optional[InterruptionConfig] = None,
        stop_playback_callback: Optional[Callable[[str], None]] = None,
        notify_context_callback: Optional[Callable[[InterruptionContext], None]] = None
    ):
        """
        Initialize interruption handler.
        
        Args:
            config: Interruption detection configuration (uses defaults if None)
            stop_playback_callback: Callback to stop audio playback
            notify_context_callback: Callback to notify Context Manager of interruption
        """
        self.config = config or InterruptionConfig()
        self.stop_playback_callback = stop_playback_callback
        self.notify_context_callback = notify_context_callback
        self.metrics = InterruptionMetrics()
        
        # State management
        self._is_monitoring = False
        self._response_active = False
        self._current_response_id: Optional[str] = None
        self._state_lock = Lock()
        
        # Threading components
        self._monitor_thread: Optional[Thread] = None
        self._stop_event = Event()
        self._audio_queue: Queue = Queue(maxsize=50)
        
        # Speech detection state
        self._speech_start_time: Optional[float] = None
        self._consecutive_speech_chunks = 0
        self._speech_buffer = []
        
        # Calculate required consecutive chunks for sustained speech
        self._chunks_for_sustained_speech = int(
            self.config.sustained_speech_ms / self.config.chunk_duration_ms
        )
        
        logger.info(
            f"Interruption handler initialized: "
            f"VAD threshold={self.config.vad_threshold}, "
            f"sustained speech={self.config.sustained_speech_ms}ms, "
            f"max stop latency={self.config.max_stop_latency_ms}ms"
        )
    
    def _detect_voice_activity(self, audio_data: AudioData) -> bool:
        """
        Detect voice activity in audio chunk using simple energy-based VAD.
        
        Args:
            audio_data: Audio chunk to analyze
            
        Returns:
            True if speech detected, False otherwise
        """
        try:
            # Convert bytes to numpy array
            audio_array = np.frombuffer(audio_data.audio_bytes, dtype=np.int16)
            
            # Calculate RMS energy
            rms_energy = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            
            # Normalize to 0-1 range (assuming 16-bit audio)
            normalized_energy = rms_energy / 32768.0
            
            # Simple threshold-based VAD
            is_speech = normalized_energy > self.config.vad_threshold
            
            logger.debug(
                f"VAD: energy={normalized_energy:.4f}, "
                f"threshold={self.config.vad_threshold}, "
                f"speech={is_speech}"
            )
            
            return is_speech
            
        except Exception as e:
            logger.error(f"Failed to detect voice activity: {e}")
            return False
    
    def _process_audio_chunk(self, audio_data: AudioData) -> Optional[InterruptionContext]:
        """
        Process audio chunk and detect interruption.
        
        Args:
            audio_data: Audio chunk to process
            
        Returns:
            InterruptionContext if interruption detected, None otherwise
        """
        detection_start = time.time()
        
        # Check if response is active
        with self._state_lock:
            if not self._response_active:
                return None
            current_response_id = self._current_response_id
        
        # Detect voice activity
        is_speech = self._detect_voice_activity(audio_data)
        
        if is_speech:
            self.metrics.speech_chunks_detected += 1
            
            # Track speech start time
            if self._speech_start_time is None:
                self._speech_start_time = time.time()
                self._consecutive_speech_chunks = 1
                self._speech_buffer = [audio_data]
                logger.debug("Speech detected, starting sustained speech timer")
            else:
                self._consecutive_speech_chunks += 1
                self._speech_buffer.append(audio_data)
            
            # Check if sustained speech threshold reached
            speech_duration_ms = (time.time() - self._speech_start_time) * 1000
            
            if speech_duration_ms >= self.config.sustained_speech_ms:
                # Interruption detected!
                detection_latency_ms = (time.time() - detection_start) * 1000
                self.metrics.total_detection_time_ms += detection_latency_ms
                
                logger.info(
                    f"Interruption detected after {speech_duration_ms:.0f}ms "
                    f"of sustained speech ({self._consecutive_speech_chunks} chunks)"
                )
                
                # Create interruption context
                interruption_id = f"int_{int(time.time() * 1000)}"
                context = InterruptionContext(
                    interruption_id=interruption_id,
                    timestamp=time.time(),
                    interrupted_response_id=current_response_id,
                    detection_latency_ms=detection_latency_ms,
                    stop_latency_ms=0.0,  # Will be updated after stop
                    audio_data=audio_data
                )
                
                # Reset speech tracking
                self._speech_start_time = None
                self._consecutive_speech_chunks = 0
                self._speech_buffer = []
                
                return context
        else:
            self.metrics.non_speech_chunks += 1
            
            # Reset speech tracking if silence detected
            if self._speech_start_time is not None:
                speech_duration_ms = (time.time() - self._speech_start_time) * 1000
                
                if speech_duration_ms < self.config.sustained_speech_ms:
                    # Speech was too short, count as false positive prevention
                    self.metrics.false_positives_prevented += 1
                    logger.debug(
                        f"Speech too short ({speech_duration_ms:.0f}ms), "
                        f"prevented false positive"
                    )
                
                self._speech_start_time = None
                self._consecutive_speech_chunks = 0
                self._speech_buffer = []
        
        return None
    
    def _handle_interruption(self, context: InterruptionContext) -> None:
        """
        Handle detected interruption by stopping playback and notifying context manager.
        
        Args:
            context: Interruption context information
            
        Validates: Requirements 6.2, 6.3, 6.4
        """
        stop_start = time.time()
        
        try:
            # Stop audio playback
            if self.stop_playback_callback and context.interrupted_response_id:
                logger.info(
                    f"Stopping playback for response: {context.interrupted_response_id}"
                )
                self.stop_playback_callback(context.interrupted_response_id)
            else:
                logger.warning("No stop playback callback configured")
            
            # Calculate stop latency
            stop_latency_ms = (time.time() - stop_start) * 1000
            context.stop_latency_ms = stop_latency_ms
            
            # Update metrics
            self.metrics.interruptions_detected += 1
            self.metrics.last_interruption_time = context.timestamp
            self.metrics.total_stop_latency_ms += stop_latency_ms
            self.metrics.average_stop_latency_ms = (
                self.metrics.total_stop_latency_ms / self.metrics.interruptions_detected
            )
            
            # Check if stop latency meets requirement (< 300ms)
            if stop_latency_ms > self.config.max_stop_latency_ms:
                logger.warning(
                    f"Stop latency {stop_latency_ms:.2f}ms exceeded "
                    f"target {self.config.max_stop_latency_ms}ms"
                )
            else:
                logger.info(f"Playback stopped in {stop_latency_ms:.2f}ms")
            
            # Notify Context Manager
            if self.notify_context_callback:
                logger.info("Notifying Context Manager of interruption")
                self.notify_context_callback(context)
            else:
                logger.warning("No context notification callback configured")
            
            # Clear response active state
            with self._state_lock:
                self._response_active = False
                self._current_response_id = None
            
        except Exception as e:
            logger.error(f"Failed to handle interruption: {e}")
    
    def _monitor_loop(self):
        """
        Main monitoring loop running in separate thread.
        Continuously monitors audio input for speech during response playback.
        """
        logger.info("Interruption monitoring loop started")
        
        while not self._stop_event.is_set():
            try:
                # Get audio chunk from queue (with timeout)
                try:
                    audio_data = self._audio_queue.get(timeout=0.1)
                except Empty:
                    continue
                
                # Process audio chunk
                interruption_context = self._process_audio_chunk(audio_data)
                
                # Handle interruption if detected
                if interruption_context:
                    self._handle_interruption(interruption_context)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(0.1)
        
        logger.info("Interruption monitoring loop stopped")
    
    def start_monitoring(self) -> bool:
        """
        Start interruption monitoring.
        
        Returns:
            True if monitoring started successfully, False otherwise
            
        Validates: Requirement 6.1
        """
        if self._is_monitoring:
            logger.warning("Interruption monitoring already running")
            return True
        
        try:
            logger.info("Starting interruption monitoring...")
            
            # Start monitoring thread
            self._stop_event.clear()
            self._monitor_thread = Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            
            self._is_monitoring = True
            logger.info("Interruption monitoring started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start interruption monitoring: {e}")
            return False
    
    def stop_monitoring(self) -> None:
        """
        Stop interruption monitoring and clean up resources.
        """
        if not self._is_monitoring:
            logger.debug("Interruption monitoring not running")
            return
        
        logger.info("Stopping interruption monitoring...")
        
        # Signal stop
        self._stop_event.set()
        
        # Wait for monitoring thread to finish
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        
        # Clear state
        with self._state_lock:
            self._response_active = False
            self._current_response_id = None
        
        self._is_monitoring = False
        logger.info("Interruption monitoring stopped")
    
    def feed_audio(self, audio_data: AudioData) -> bool:
        """
        Feed audio chunk to interruption handler for monitoring.
        
        Args:
            audio_data: Audio chunk from input stream
            
        Returns:
            True if audio accepted, False if queue full
            
        Validates: Requirement 6.1
        """
        if not self._is_monitoring:
            logger.warning("Interruption monitoring not running, audio not processed")
            return False
        
        try:
            # Add to queue (non-blocking)
            self._audio_queue.put_nowait(audio_data)
            return True
        except:
            logger.warning("Audio queue full, dropping chunk")
            return False
    
    def set_response_active(self, response_id: str) -> None:
        """
        Signal that an AI response is now playing.
        
        Args:
            response_id: Unique identifier for the active response
            
        Validates: Requirement 6.1
        """
        with self._state_lock:
            self._response_active = True
            self._current_response_id = response_id
            logger.info(f"Response active: {response_id}")
    
    def set_response_inactive(self) -> None:
        """
        Signal that AI response playback has completed normally.
        """
        with self._state_lock:
            if self._response_active:
                logger.info(f"Response completed: {self._current_response_id}")
            self._response_active = False
            self._current_response_id = None
        
        # Reset speech tracking
        self._speech_start_time = None
        self._consecutive_speech_chunks = 0
        self._speech_buffer = []
    
    def is_monitoring(self) -> bool:
        """
        Check if interruption monitoring is currently running.
        
        Returns:
            True if monitoring, False otherwise
        """
        return self._is_monitoring
    
    def is_response_active(self) -> bool:
        """
        Check if an AI response is currently playing.
        
        Returns:
            True if response active, False otherwise
        """
        with self._state_lock:
            return self._response_active
    
    def get_current_response_id(self) -> Optional[str]:
        """
        Get the ID of the currently playing response.
        
        Returns:
            Response ID if active, None otherwise
        """
        with self._state_lock:
            return self._current_response_id
    
    def get_metrics(self) -> InterruptionMetrics:
        """
        Get interruption handler metrics for monitoring.
        
        Returns:
            InterruptionMetrics object with current metrics
        """
        return self.metrics
    
    def get_config(self) -> InterruptionConfig:
        """
        Get interruption handler configuration.
        
        Returns:
            InterruptionConfig object
        """
        return self.config
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get comprehensive interruption handler information.
        
        Returns:
            Dictionary with configuration, state, and metrics
        """
        with self._state_lock:
            response_active = self._response_active
            current_response_id = self._current_response_id
        
        return {
            "is_monitoring": self._is_monitoring,
            "response_active": response_active,
            "current_response_id": current_response_id,
            "config": {
                "vad_threshold": self.config.vad_threshold,
                "sustained_speech_ms": self.config.sustained_speech_ms,
                "sample_rate": self.config.sample_rate,
                "chunk_duration_ms": self.config.chunk_duration_ms,
                "max_stop_latency_ms": self.config.max_stop_latency_ms
            },
            "metrics": {
                "interruptions_detected": self.metrics.interruptions_detected,
                "false_positives_prevented": self.metrics.false_positives_prevented,
                "average_stop_latency_ms": self.metrics.average_stop_latency_ms,
                "total_detection_time_ms": self.metrics.total_detection_time_ms,
                "total_stop_latency_ms": self.metrics.total_stop_latency_ms,
                "last_interruption_time": self.metrics.last_interruption_time,
                "speech_chunks_detected": self.metrics.speech_chunks_detected,
                "non_speech_chunks": self.metrics.non_speech_chunks
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Interruption Handler Test")
    print("=" * 50)
    print()
    
    # Example callbacks
    def stop_playback(response_id: str):
        print(f"STOP PLAYBACK: {response_id}")
    
    def notify_context(context: InterruptionContext):
        print(f"INTERRUPTION: {context.interruption_id} at {context.timestamp}")
        print(f"  Interrupted response: {context.interrupted_response_id}")
        print(f"  Detection latency: {context.detection_latency_ms:.2f}ms")
        print(f"  Stop latency: {context.stop_latency_ms:.2f}ms")
    
    # Create interruption handler
    config = InterruptionConfig(
        vad_threshold=0.5,
        sustained_speech_ms=300,
        max_stop_latency_ms=300
    )
    
    handler = InterruptionHandler(
        config=config,
        stop_playback_callback=stop_playback,
        notify_context_callback=notify_context
    )
    
    print(f"Interruption handler ready")
    print(f"Configuration: VAD threshold={config.vad_threshold}, "
          f"sustained speech={config.sustained_speech_ms}ms")
    print()
    print("To test interruption detection:")
    print("1. handler.start_monitoring()")
    print("2. handler.set_response_active('response_123')")
    print("3. handler.feed_audio(audio_data)  # Feed audio chunks")
    print("4. handler.set_response_inactive()  # When response completes")
