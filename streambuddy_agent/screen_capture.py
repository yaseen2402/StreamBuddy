"""
Screen Capture Module

Captures screen/desktop for local testing mode.
Allows streamers to test StreamBuddy with their actual game/desktop
without needing to start a YouTube Live stream.

Validates: Requirements 1.1, 1.6
"""

import logging
import time
import io
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from PIL import Image
import numpy as np
from threading import Thread, Event, Lock
from queue import Queue, Empty

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logging.warning("mss not available. Screen capture will not work. Install with: pip install mss")

from streambuddy_agent.models import VideoFrame

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class ScreenConfig:
    """Configuration for screen capture"""
    frame_rate: float = 1.0  # frames per second (default 1 fps)
    max_dimension: int = 1280  # maximum width or height in pixels
    jpeg_quality: int = 85  # JPEG compression quality (0-100)
    monitor: int = 0  # Monitor index (0 = primary, 1 = secondary, etc.)
    buffer_size: int = 10  # maximum frames to buffer


@dataclass
class ScreenMetrics:
    """Metrics for screen capture monitoring"""
    frames_captured: int = 0
    frames_forwarded: int = 0
    frames_dropped: int = 0
    frames_compressed: int = 0
    total_capture_time: float = 0.0
    total_compression_time: float = 0.0
    total_forwarding_time: float = 0.0
    average_frame_size_bytes: float = 0.0
    last_capture_time: Optional[float] = None


class ScreenCapture:
    """
    Manages screen capture for local testing mode.
    Captures desktop/game screen at configurable frame rate.
    
    Validates: Requirements 1.1, 1.6
    """
    
    def __init__(
        self,
        config: Optional[ScreenConfig] = None,
        forward_callback: Optional[Callable[[VideoFrame], None]] = None
    ):
        """
        Initialize screen capture manager.
        
        Args:
            config: Screen capture configuration (uses defaults if None)
            forward_callback: Callback function to forward frames to Gemini Live Client
        """
        self.config = config or ScreenConfig()
        self.forward_callback = forward_callback
        self.metrics = ScreenMetrics()
        
        # Threading components
        self._capture_thread: Optional[Thread] = None
        self._stop_event = Event()
        self._frame_queue: Queue = Queue(maxsize=self.config.buffer_size)
        self._sequence_number = 0
        self._sequence_lock = Lock()
        
        # Screen capture
        self._sct = None
        self._is_capturing = False
        self._monitor_info = None
        
        if not MSS_AVAILABLE:
            logger.error("mss library not available. Install with: pip install mss")
        
        logger.info(
            f"Screen capture initialized: {self.config.frame_rate} fps, "
            f"max dimension {self.config.max_dimension}px, "
            f"JPEG quality {self.config.jpeg_quality}%, "
            f"monitor {self.config.monitor}"
        )
    
    def _get_next_sequence_number(self) -> int:
        """Get next sequence number for frame ordering."""
        with self._sequence_lock:
            seq = self._sequence_number
            self._sequence_number += 1
            return seq
    
    def _resize_frame(self, image: Image.Image) -> Image.Image:
        """
        Resize frame to fit within max dimension while maintaining aspect ratio.
        
        Args:
            image: Input PIL Image
            
        Returns:
            Resized PIL Image
        """
        width, height = image.size
        max_dim = self.config.max_dimension
        
        # Check if resizing is needed
        if width <= max_dim and height <= max_dim:
            return image
        
        # Calculate new dimensions maintaining aspect ratio
        if width > height:
            new_width = max_dim
            new_height = int(height * (max_dim / width))
        else:
            new_height = max_dim
            new_width = int(width * (max_dim / height))
        
        # Resize using high-quality resampling
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        logger.debug(f"Resized frame from {width}x{height} to {new_width}x{new_height}")
        return resized
    
    def _compress_frame(self, image: Image.Image) -> bytes:
        """
        Compress frame to JPEG format with configured quality.
        
        Args:
            image: Input PIL Image
            
        Returns:
            JPEG-encoded frame data as bytes
        """
        start_time = time.time()
        
        # Compress to JPEG
        buffer = io.BytesIO()
        image.save(
            buffer,
            format='JPEG',
            quality=self.config.jpeg_quality,
            optimize=True
        )
        
        jpeg_data = buffer.getvalue()
        
        compression_time = time.time() - start_time
        self.metrics.total_compression_time += compression_time
        self.metrics.frames_compressed += 1
        
        logger.debug(
            f"Compressed frame to {len(jpeg_data)} bytes in {compression_time*1000:.2f}ms"
        )
        
        return jpeg_data
    
    def _process_frame(self, screenshot) -> Optional[VideoFrame]:
        """
        Process a raw screenshot: resize, compress, and create VideoFrame object.
        
        Args:
            screenshot: mss screenshot object
            
        Returns:
            Processed VideoFrame object, or None if processing fails
        """
        try:
            # Convert to PIL Image
            image = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            
            # Resize frame
            resized_frame = self._resize_frame(image)
            
            # Compress frame
            compressed_data = self._compress_frame(resized_frame)
            
            # Get dimensions
            width, height = resized_frame.size
            
            # Create VideoFrame object
            video_frame = VideoFrame(
                timestamp=time.time(),
                frame_data=compressed_data,
                width=width,
                height=height,
                sequence_number=self._get_next_sequence_number()
            )
            
            # Update metrics
            self.metrics.frames_captured += 1
            self.metrics.last_capture_time = video_frame.timestamp
            
            # Update average frame size
            total_size = (
                self.metrics.average_frame_size_bytes * (self.metrics.frames_captured - 1) +
                len(compressed_data)
            )
            self.metrics.average_frame_size_bytes = total_size / self.metrics.frames_captured
            
            return video_frame
            
        except Exception as e:
            logger.error(f"Failed to process frame: {e}")
            return None
    
    def _forward_frame(self, frame: VideoFrame) -> bool:
        """
        Forward frame to Gemini Live Client via callback.
        
        Args:
            frame: VideoFrame to forward
            
        Returns:
            True if forwarding successful, False otherwise
        """
        if not self.forward_callback:
            logger.warning("No forward callback configured, frame not forwarded")
            return False
        
        try:
            start_time = time.time()
            
            # Call forward callback
            self.forward_callback(frame)
            
            forwarding_time = time.time() - start_time
            self.metrics.total_forwarding_time += forwarding_time
            self.metrics.frames_forwarded += 1
            
            # Check latency requirement (< 100ms)
            if forwarding_time > 0.1:
                logger.warning(
                    f"Frame forwarding exceeded 100ms latency: {forwarding_time*1000:.2f}ms"
                )
            else:
                logger.debug(
                    f"Frame forwarded in {forwarding_time*1000:.2f}ms "
                    f"(seq {frame.sequence_number})"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to forward frame: {e}")
            return False
    
    def _capture_loop(self):
        """
        Main capture loop running in separate thread.
        Captures screen at configured frame rate and forwards frames.
        """
        logger.info("Screen capture loop started")
        
        # Create mss instance in this thread (Windows threading fix)
        try:
            import mss
            self._sct = mss.mss()
        except Exception as e:
            logger.error(f"Failed to create mss instance in thread: {e}")
            return
        
        frame_interval = 1.0 / self.config.frame_rate
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
                next_capture_time = current_time + frame_interval
                
                # Capture screenshot
                if not self._sct:
                    logger.warning("Screen capture not initialized")
                    time.sleep(0.1)
                    continue
                
                capture_start = time.time()
                screenshot = self._sct.grab(self._monitor_info)
                capture_time = time.time() - capture_start
                self.metrics.total_capture_time += capture_time
                
                if not screenshot:
                    logger.warning("Failed to capture screenshot")
                    continue
                
                # Process frame (resize and compress)
                video_frame = self._process_frame(screenshot)
                if not video_frame:
                    continue
                
                # Forward frame immediately (queue not needed since we forward directly)
                self._forward_frame(video_frame)
                
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                time.sleep(0.1)
        
        # Clean up mss instance in the same thread it was created
        if self._sct:
            try:
                self._sct.close()
            except Exception as e:
                logger.debug(f"Error closing mss: {e}")
            self._sct = None
        
        logger.info("Screen capture loop stopped")
    
    def start_capture(self, monitor: Optional[int] = None) -> bool:
        """
        Start screen capture from specified monitor.
        
        Args:
            monitor: Monitor index (0 = primary, 1 = secondary, etc.)
                    None uses config default
            
        Returns:
            True if capture started successfully, False otherwise
            
        Validates: Requirements 1.1, 1.6
        """
        if self._is_capturing:
            logger.warning("Screen capture already running")
            return True
        
        if not MSS_AVAILABLE:
            logger.error("Cannot start screen capture: mss library not available")
            return False
        
        try:
            # Get monitor info (will create mss in thread)
            monitor_index = monitor if monitor is not None else self.config.monitor
            
            # Temporarily create mss to get monitor info
            import mss
            with mss.mss() as sct:
                monitors = sct.monitors
                
                if monitor_index >= len(monitors):
                    logger.error(f"Monitor {monitor_index} not found. Available: {len(monitors)-1}")
                    return False
                
                # Monitor 0 is "all monitors", 1 is primary, 2 is secondary, etc.
                self._monitor_info = monitors[monitor_index + 1] if monitor_index >= 0 else monitors[1]
            
            logger.info(
                f"Screen capture initialized: Monitor {monitor_index}, "
                f"Resolution: {self._monitor_info['width']}x{self._monitor_info['height']}, "
                f"Capturing at {self.config.frame_rate} fps"
            )
            
            # Start capture thread (mss will be created inside the thread)
            self._stop_event.clear()
            self._capture_thread = Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            self._is_capturing = True
            logger.info("Screen capture started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start screen capture: {e}")
            return False
    
    def stop_capture(self) -> None:
        """Stop screen capture and clean up resources."""
        if not self._is_capturing:
            logger.debug("Screen capture not running")
            return
        
        logger.info("Stopping screen capture...")
        
        # Signal stop
        self._stop_event.set()
        
        # Wait for capture thread to finish (it will clean up mss itself)
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        
        # Don't close mss here - it was created in the thread and will be cleaned up there
        # Just mark as not capturing
        self._is_capturing = False
        logger.info("Screen capture stopped")
    
    def is_capturing(self) -> bool:
        """Check if screen capture is currently running."""
        return self._is_capturing
    
    def get_metrics(self) -> ScreenMetrics:
        """Get screen capture metrics for monitoring."""
        return self.metrics
    
    def get_available_monitors(self) -> list:
        """Get list of available monitors."""
        if not MSS_AVAILABLE:
            return []
        
        try:
            with mss.mss() as sct:
                monitors = sct.monitors[1:]  # Skip "all monitors"
                return [
                    {
                        'index': i,
                        'width': m['width'],
                        'height': m['height'],
                        'left': m['left'],
                        'top': m['top']
                    }
                    for i, m in enumerate(monitors)
                ]
        except Exception as e:
            logger.error(f"Failed to get monitors: {e}")
            return []
    
    def get_info(self) -> Dict[str, Any]:
        """Get comprehensive screen capture information."""
        return {
            "is_capturing": self._is_capturing,
            "config": {
                "frame_rate": self.config.frame_rate,
                "max_dimension": self.config.max_dimension,
                "jpeg_quality": self.config.jpeg_quality,
                "monitor": self.config.monitor,
                "buffer_size": self.config.buffer_size
            },
            "metrics": {
                "frames_captured": self.metrics.frames_captured,
                "frames_forwarded": self.metrics.frames_forwarded,
                "frames_dropped": self.metrics.frames_dropped,
                "frames_compressed": self.metrics.frames_compressed,
                "average_frame_size_bytes": self.metrics.average_frame_size_bytes,
                "total_capture_time": self.metrics.total_capture_time,
                "total_compression_time": self.metrics.total_compression_time,
                "total_forwarding_time": self.metrics.total_forwarding_time,
                "last_capture_time": self.metrics.last_capture_time
            },
            "monitor_info": self._monitor_info if self._monitor_info else None
        }
