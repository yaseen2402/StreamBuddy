"""
Video Stream Capture Module

This module implements video frame capture from YouTube Live streams at configurable
frame rates, with frame compression, resizing, and forwarding to Gemini Live Client.

Validates: Requirements 1.1, 1.6
"""

import logging
import time
import io
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from PIL import Image
import cv2
import numpy as np
from threading import Thread, Event, Lock
from queue import Queue, Empty

try:
    # yt_dlp is used to resolve YouTube URLs to direct stream URLs
    import yt_dlp  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yt_dlp = None

from streambuddy_agent.models import VideoFrame

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class VideoConfig:
    """Configuration for video capture"""
    frame_rate: float = 1.0  # frames per second (default 1 fps)
    max_dimension: int = 1280  # maximum width or height in pixels
    jpeg_quality: int = 85  # JPEG compression quality (0-100)
    buffer_size: int = 10  # maximum frames to buffer


@dataclass
class VideoMetrics:
    """Metrics for video capture monitoring"""
    frames_captured: int = 0
    frames_forwarded: int = 0
    frames_dropped: int = 0
    frames_compressed: int = 0
    total_capture_time: float = 0.0
    total_compression_time: float = 0.0
    total_forwarding_time: float = 0.0
    average_frame_size_bytes: float = 0.0
    last_capture_time: Optional[float] = None


class VideoCapture:
    """
    Manages video frame capture from YouTube Live streams with configurable
    frame rate, compression, and resizing.
    
    Validates: Requirements 1.1, 1.6
    """
    
    def __init__(
        self,
        config: Optional[VideoConfig] = None,
        forward_callback: Optional[Callable[[VideoFrame], None]] = None
    ):
        """
        Initialize video capture manager.
        
        Args:
            config: Video capture configuration (uses defaults if None)
            forward_callback: Callback function to forward frames to Gemini Live Client
        """
        self.config = config or VideoConfig()
        self.forward_callback = forward_callback
        self.metrics = VideoMetrics()
        
        # Threading components
        self._capture_thread: Optional[Thread] = None
        self._stop_event = Event()
        self._frame_queue: Queue = Queue(maxsize=self.config.buffer_size)
        self._sequence_number = 0
        self._sequence_lock = Lock()
        
        # Video source
        self._video_source: Optional[cv2.VideoCapture] = None
        self._is_capturing = False
        
        logger.info(
            f"Video capture initialized: {self.config.frame_rate} fps, "
            f"max dimension {self.config.max_dimension}px, "
            f"JPEG quality {self.config.jpeg_quality}%"
        )
    
    def _get_next_sequence_number(self) -> int:
        """
        Get next sequence number for frame ordering.
        
        Returns:
            Next sequence number
        """
        with self._sequence_lock:
            seq = self._sequence_number
            self._sequence_number += 1
            return seq
    
    def _resize_frame(self, image: np.ndarray) -> np.ndarray:
        """
        Resize frame to fit within max dimension while maintaining aspect ratio.
        
        Args:
            image: Input image as numpy array
            
        Returns:
            Resized image as numpy array
        """
        height, width = image.shape[:2]
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
        
        # Resize using high-quality interpolation
        resized = cv2.resize(
            image,
            (new_width, new_height),
            interpolation=cv2.INTER_AREA
        )
        
        logger.debug(f"Resized frame from {width}x{height} to {new_width}x{new_height}")
        return resized
    
    def _compress_frame(self, image: np.ndarray) -> bytes:
        """
        Compress frame to JPEG format with configured quality.
        
        Args:
            image: Input image as numpy array (BGR format from OpenCV)
            
        Returns:
            JPEG-encoded frame data as bytes
        """
        start_time = time.time()
        
        # Convert BGR to RGB for PIL
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL Image
        pil_image = Image.fromarray(rgb_image)
        
        # Compress to JPEG
        buffer = io.BytesIO()
        pil_image.save(
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
    
    def _process_frame(self, frame: np.ndarray) -> Optional[VideoFrame]:
        """
        Process a raw video frame: resize, compress, and create VideoFrame object.
        
        Args:
            frame: Raw video frame as numpy array
            
        Returns:
            Processed VideoFrame object, or None if processing fails
        """
        try:
            # Resize frame
            resized_frame = self._resize_frame(frame)
            
            # Compress frame
            compressed_data = self._compress_frame(resized_frame)
            
            # Get dimensions
            height, width = resized_frame.shape[:2]
            
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
        Captures frames at configured frame rate and forwards them.
        """
        logger.info("Video capture loop started")
        
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
                
                # Capture frame from video source
                if not self._video_source or not self._video_source.isOpened():
                    logger.warning("Video source not available")
                    time.sleep(0.1)
                    continue
                
                capture_start = time.time()
                ret, frame = self._video_source.read()
                capture_time = time.time() - capture_start
                self.metrics.total_capture_time += capture_time
                
                if not ret or frame is None:
                    logger.warning("Failed to capture frame from video source")
                    continue
                
                # Process frame (resize and compress)
                video_frame = self._process_frame(frame)
                if not video_frame:
                    continue
                
                # Try to add to queue (non-blocking)
                try:
                    self._frame_queue.put_nowait(video_frame)
                except:
                    # Queue full, drop frame
                    self.metrics.frames_dropped += 1
                    logger.warning(
                        f"Frame queue full, dropped frame {video_frame.sequence_number}"
                    )
                
                # Forward frame immediately (in same thread for low latency)
                self._forward_frame(video_frame)
                
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                time.sleep(0.1)
        
        logger.info("Video capture loop stopped")
    
    def _resolve_youtube_source(self, url: str) -> Optional[str]:
        """
        Resolve a YouTube (or youtu.be) URL to a direct video stream URL
        using yt_dlp. Returns None on failure.
        """
        if yt_dlp is None:
            logger.error(
                "yt_dlp is not installed. Install it to enable YouTube URL capture "
                "(e.g. pip install yt-dlp)."
            )
            return None

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "nocheckcertificate": True,
            "noplaylist": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get("url")
                if not stream_url:
                    logger.error("yt_dlp did not return a stream URL for YouTube link")
                    return None
                logger.info("Resolved YouTube URL to direct stream URL via yt_dlp")
                return stream_url
        except Exception as e:
            logger.error(f"Failed to resolve YouTube URL with yt_dlp: {e}")
            return None

    def start_capture(self, video_source: str) -> bool:
        """
        Start video capture from specified source.
        
        Args:
            video_source: Video source (URL, file path, or device index)
            
        Returns:
            True if capture started successfully, False otherwise
            
        Validates: Requirements 1.1, 1.6
        """
        if self._is_capturing:
            logger.warning("Video capture already running")
            return True
        
        try:
            source_to_open = video_source

            # If this looks like a YouTube URL, resolve it first
            lower_src = str(video_source).lower()
            if lower_src.startswith("http") and (
                "youtube.com" in lower_src or "youtu.be" in lower_src
            ):
                logger.info(f"Resolving YouTube video source via yt_dlp: {video_source}")
                resolved = self._resolve_youtube_source(video_source)
                if not resolved:
                    logger.error("Unable to resolve YouTube URL to a direct stream")
                    return False
                source_to_open = resolved

            # Open video source (URL, file path, or device index)
            logger.info(f"Opening video source: {source_to_open}")
            self._video_source = cv2.VideoCapture(source_to_open)
            
            if not self._video_source.isOpened():
                logger.error(f"Failed to open video source: {video_source}")
                return False
            
            # Get video properties
            width = int(self._video_source.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self._video_source.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self._video_source.get(cv2.CAP_PROP_FPS)
            
            logger.info(
                f"Video source opened: {width}x{height} @ {fps} fps "
                f"(capturing at {self.config.frame_rate} fps)"
            )
            
            # Start capture thread
            self._stop_event.clear()
            self._capture_thread = Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            self._is_capturing = True
            logger.info("Video capture started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start video capture: {e}")
            if self._video_source:
                self._video_source.release()
                self._video_source = None
            return False
    
    def stop_capture(self) -> None:
        """
        Stop video capture and clean up resources.
        """
        if not self._is_capturing:
            logger.debug("Video capture not running")
            return
        
        logger.info("Stopping video capture...")
        
        # Signal stop
        self._stop_event.set()
        
        # Wait for capture thread to finish
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        
        # Release video source
        if self._video_source:
            self._video_source.release()
            self._video_source = None
        
        self._is_capturing = False
        logger.info("Video capture stopped")
    
    def is_capturing(self) -> bool:
        """
        Check if video capture is currently running.
        
        Returns:
            True if capturing, False otherwise
        """
        return self._is_capturing
    
    def get_metrics(self) -> VideoMetrics:
        """
        Get video capture metrics for monitoring.
        
        Returns:
            VideoMetrics object with current metrics
        """
        return self.metrics
    
    def get_frame_rate(self) -> float:
        """
        Get configured frame rate.
        
        Returns:
            Frame rate in frames per second
        """
        return self.config.frame_rate
    
    def set_frame_rate(self, frame_rate: float) -> None:
        """
        Update frame rate dynamically.
        
        Args:
            frame_rate: New frame rate in frames per second
        """
        if frame_rate <= 0:
            raise ValueError("frame_rate must be positive")
        
        old_rate = self.config.frame_rate
        self.config.frame_rate = frame_rate
        
        logger.info(f"Frame rate updated: {old_rate} fps -> {frame_rate} fps")
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get comprehensive video capture information.
        
        Returns:
            Dictionary with configuration, state, and metrics
        """
        return {
            "is_capturing": self._is_capturing,
            "config": {
                "frame_rate": self.config.frame_rate,
                "max_dimension": self.config.max_dimension,
                "jpeg_quality": self.config.jpeg_quality,
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
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Video Stream Capture Test")
    print("=" * 50)
    print()
    
    # Example forward callback
    def forward_frame(frame: VideoFrame):
        print(f"Frame {frame.sequence_number}: {len(frame.frame_data)} bytes, "
              f"{frame.width}x{frame.height}")
    
    # Create video capture with custom config
    config = VideoConfig(
        frame_rate=1.0,
        max_dimension=1280,
        jpeg_quality=85
    )
    
    capture = VideoCapture(config=config, forward_callback=forward_frame)
    
    print(f"Video capture ready")
    print(f"Configuration: {config.frame_rate} fps, max {config.max_dimension}px, "
          f"{config.jpeg_quality}% quality")
    print()
    print("To test capture, call start_capture() with a video source")
    print("Example: capture.start_capture('test_video.mp4')")
    print("         capture.start_capture(0)  # for webcam")
