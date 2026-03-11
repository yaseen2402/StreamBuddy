"""
Audio Stream Capture Module

This module implements audio chunk capture from YouTube Live streams with 500ms
maximum buffering and forwarding to Gemini Live Client with < 500ms latency.

Validates: Requirements 1.2, 1.7
"""

import logging
import time
import io
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from threading import Thread, Event, Lock
from queue import Queue, Empty
import numpy as np

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logging.warning("PyAudio not available. Audio capture will use simulated mode.")

from streambuddy_agent.models import AudioData

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    """Configuration for audio capture"""
    sample_rate: int = 16000  # Hz (Gemini Live API requires 16kHz for INPUT)
    channels: int = 1  # Mono
    chunk_duration_ms: int = 500  # Maximum buffering duration
    encoding: str = "pcm"  # Audio encoding format
    buffer_size: int = 10  # Maximum audio chunks to buffer


@dataclass
class AudioMetrics:
    """Metrics for audio capture monitoring"""
    chunks_captured: int = 0
    chunks_forwarded: int = 0
    chunks_dropped: int = 0
    total_capture_time: float = 0.0
    total_forwarding_time: float = 0.0
    average_chunk_size_bytes: float = 0.0
    last_capture_time: Optional[float] = None
    total_audio_duration_ms: int = 0


class AudioCapture:
    """
    Manages audio chunk capture from YouTube Live streams with 500ms maximum
    buffering and low-latency forwarding.
    
    Validates: Requirements 1.2, 1.7
    """
    
    def __init__(
        self,
        config: Optional[AudioConfig] = None,
        forward_callback: Optional[Callable[[AudioData], None]] = None
    ):
        """
        Initialize audio capture manager.
        
        Args:
            config: Audio capture configuration (uses defaults if None)
            forward_callback: Callback function to forward audio to Gemini Live Client
        """
        self.config = config or AudioConfig()
        self.forward_callback = forward_callback
        self.metrics = AudioMetrics()
        
        # Threading components
        self._capture_thread: Optional[Thread] = None
        self._stop_event = Event()
        self._audio_queue: Queue = Queue(maxsize=self.config.buffer_size)
        self._chunk_lock = Lock()
        
        # Audio source
        self._audio_stream = None
        self._pyaudio = None
        self._is_capturing = False
        
        # Calculate chunk size in bytes
        # For PCM: bytes = sample_rate * channels * bytes_per_sample * duration_seconds
        # Assuming 16-bit (2 bytes) per sample
        self._bytes_per_sample = 2
        self._chunk_size_frames = int(
            self.config.sample_rate * (self.config.chunk_duration_ms / 1000.0)
        )
        self._chunk_size_bytes = (
            self._chunk_size_frames * self.config.channels * self._bytes_per_sample
        )
        
        logger.info(
            f"Audio capture initialized: {self.config.sample_rate} Hz, "
            f"{self.config.channels} channel(s), "
            f"{self.config.chunk_duration_ms}ms chunks, "
            f"{self._chunk_size_bytes} bytes per chunk"
        )
    
    def _process_audio_chunk(self, audio_bytes: bytes) -> Optional[AudioData]:
        """
        Process a raw audio chunk and create AudioData object.
        
        Args:
            audio_bytes: Raw audio data
            
        Returns:
            Processed AudioData object, or None if processing fails
        """
        try:
            # Create AudioData object
            audio_data = AudioData(
                timestamp=time.time(),
                audio_bytes=audio_bytes,
                sample_rate=self.config.sample_rate,
                duration_ms=self.config.chunk_duration_ms,
                encoding=self.config.encoding
            )
            
            # Update metrics
            self.metrics.chunks_captured += 1
            self.metrics.last_capture_time = audio_data.timestamp
            self.metrics.total_audio_duration_ms += self.config.chunk_duration_ms
            
            # Update average chunk size
            total_size = (
                self.metrics.average_chunk_size_bytes * (self.metrics.chunks_captured - 1) +
                len(audio_bytes)
            )
            self.metrics.average_chunk_size_bytes = total_size / self.metrics.chunks_captured
            
            return audio_data
            
        except Exception as e:
            logger.error(f"Failed to process audio chunk: {e}")
            return None
    
    def _forward_audio(self, audio_data: AudioData) -> bool:
        """
        Forward audio chunk to Gemini Live Client via callback.
        
        Args:
            audio_data: AudioData to forward
            
        Returns:
            True if forwarding successful, False otherwise
        """
        if not self.forward_callback:
            logger.warning("No forward callback configured, audio not forwarded")
            return False
        
        try:
            start_time = time.time()
            
            # Call forward callback
            self.forward_callback(audio_data)
            
            forwarding_time = time.time() - start_time
            self.metrics.total_forwarding_time += forwarding_time
            self.metrics.chunks_forwarded += 1
            
            # Check latency requirement (< 500ms)
            if forwarding_time > 0.5:
                logger.warning(
                    f"Audio forwarding exceeded 500ms latency: {forwarding_time*1000:.2f}ms"
                )
            else:
                logger.debug(
                    f"Audio forwarded in {forwarding_time*1000:.2f}ms "
                    f"({self.config.chunk_duration_ms}ms chunk)"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to forward audio: {e}")
            return False
    
    def _capture_loop(self):
        """
        Main capture loop running in separate thread.
        Captures audio chunks and forwards them with low latency.
        """
        logger.info("Audio capture loop started")
        
        while not self._stop_event.is_set():
            try:
                # Check if audio stream is available
                if not self._audio_stream:
                    logger.warning("Audio stream not available")
                    time.sleep(0.1)
                    continue
                
                # Capture audio chunk
                capture_start = time.time()
                
                try:
                    audio_bytes = self._audio_stream.read(
                        self._chunk_size_frames,
                        exception_on_overflow=False
                    )
                except Exception as e:
                    logger.error(f"Failed to read from audio stream: {e}")
                    time.sleep(0.1)
                    continue
                
                capture_time = time.time() - capture_start
                self.metrics.total_capture_time += capture_time
                
                # Process audio chunk
                audio_data = self._process_audio_chunk(audio_bytes)
                if not audio_data:
                    continue
                
                # Forward audio immediately (queue not needed since we forward directly)
                self._forward_audio(audio_data)
                
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                time.sleep(0.1)
        
        logger.info("Audio capture loop stopped")
    
    def start_capture(self, audio_source: Optional[str] = None) -> bool:
        """
        Start audio capture from specified source.
        
        Args:
            audio_source: Audio source identifier (device index, URL, or None for default)
            
        Returns:
            True if capture started successfully, False otherwise
            
        Validates: Requirements 1.2, 1.7
        """
        if self._is_capturing:
            logger.warning("Audio capture already running")
            return True
        
        try:
            if not PYAUDIO_AVAILABLE:
                logger.warning("PyAudio not available, using simulated audio capture")
                # For testing/development without PyAudio
                self._is_capturing = True
                self._stop_event.clear()
                self._capture_thread = Thread(target=self._simulated_capture_loop, daemon=True)
                self._capture_thread.start()
                return True
            
            # Initialize PyAudio
            logger.info(f"Opening audio source: {audio_source or 'default'}")
            self._pyaudio = pyaudio.PyAudio()
            
            # Determine device index
            device_index = None
            if audio_source is not None:
                try:
                    device_index = int(audio_source)
                except ValueError:
                    logger.warning(f"Invalid device index: {audio_source}, using default")
            
            # Open audio stream
            self._audio_stream = self._pyaudio.open(
                format=pyaudio.paInt16,  # 16-bit PCM
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self._chunk_size_frames
            )
            
            logger.info(
                f"Audio stream opened: {self.config.sample_rate} Hz, "
                f"{self.config.channels} channel(s), "
                f"{self.config.chunk_duration_ms}ms chunks"
            )
            
            # Start capture thread
            self._stop_event.clear()
            self._capture_thread = Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            self._is_capturing = True
            logger.info("Audio capture started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            if self._audio_stream:
                self._audio_stream.close()
                self._audio_stream = None
            if self._pyaudio:
                self._pyaudio.terminate()
                self._pyaudio = None
            return False
    
    def _simulated_capture_loop(self):
        """
        Simulated capture loop for testing without PyAudio.
        Generates silent audio chunks at the configured rate.
        """
        logger.info("Simulated audio capture loop started")
        
        chunk_interval = self.config.chunk_duration_ms / 1000.0
        next_capture_time = time.time()
        
        while not self._stop_event.is_set():
            try:
                # Wait until next capture time
                current_time = time.time()
                if current_time < next_capture_time:
                    sleep_time = next_capture_time - current_time
                    if self._stop_event.wait(timeout=sleep_time):
                        break
                    continue
                
                # Update next capture time
                next_capture_time = current_time + chunk_interval
                
                # Generate silent audio chunk
                audio_bytes = bytes(self._chunk_size_bytes)
                
                # Process audio chunk
                audio_data = self._process_audio_chunk(audio_bytes)
                if not audio_data:
                    continue
                
                # Forward audio
                self._forward_audio(audio_data)
                
            except Exception as e:
                logger.error(f"Error in simulated capture loop: {e}")
                time.sleep(0.1)
        
        logger.info("Simulated audio capture loop stopped")
    
    def stop_capture(self) -> None:
        """
        Stop audio capture and clean up resources.
        """
        if not self._is_capturing:
            logger.debug("Audio capture not running")
            return
        
        logger.info("Stopping audio capture...")
        
        # Signal stop
        self._stop_event.set()
        
        # Wait for capture thread to finish
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        
        # Close audio stream
        if self._audio_stream:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
            self._audio_stream = None
        
        # Terminate PyAudio
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None
        
        self._is_capturing = False
        logger.info("Audio capture stopped")
    
    def is_capturing(self) -> bool:
        """
        Check if audio capture is currently running.
        
        Returns:
            True if capturing, False otherwise
        """
        return self._is_capturing
    
    def get_metrics(self) -> AudioMetrics:
        """
        Get audio capture metrics for monitoring.
        
        Returns:
            AudioMetrics object with current metrics
        """
        return self.metrics
    
    def get_config(self) -> AudioConfig:
        """
        Get audio capture configuration.
        
        Returns:
            AudioConfig object
        """
        return self.config
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get comprehensive audio capture information.
        
        Returns:
            Dictionary with configuration, state, and metrics
        """
        return {
            "is_capturing": self._is_capturing,
            "config": {
                "sample_rate": self.config.sample_rate,
                "channels": self.config.channels,
                "chunk_duration_ms": self.config.chunk_duration_ms,
                "encoding": self.config.encoding,
                "buffer_size": self.config.buffer_size
            },
            "metrics": {
                "chunks_captured": self.metrics.chunks_captured,
                "chunks_forwarded": self.metrics.chunks_forwarded,
                "chunks_dropped": self.metrics.chunks_dropped,
                "average_chunk_size_bytes": self.metrics.average_chunk_size_bytes,
                "total_capture_time": self.metrics.total_capture_time,
                "total_forwarding_time": self.metrics.total_forwarding_time,
                "last_capture_time": self.metrics.last_capture_time,
                "total_audio_duration_ms": self.metrics.total_audio_duration_ms
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Audio Stream Capture Test")
    print("=" * 50)
    print()
    
    # Example forward callback
    def forward_audio(audio_data: AudioData):
        print(f"Audio chunk: {len(audio_data.audio_bytes)} bytes, "
              f"{audio_data.duration_ms}ms, {audio_data.sample_rate} Hz")
    
    # Create audio capture with custom config
    config = AudioConfig(
        sample_rate=24000,
        channels=1,
        chunk_duration_ms=500,
        encoding="pcm"
    )
    
    capture = AudioCapture(config=config, forward_callback=forward_audio)
    
    print(f"Audio capture ready")
    print(f"Configuration: {config.sample_rate} Hz, {config.channels} channel(s), "
          f"{config.chunk_duration_ms}ms chunks")
    print()
    print("To test capture, call start_capture()")
    print("Example: capture.start_capture()  # default device")
    print("         capture.start_capture('0')  # specific device")
