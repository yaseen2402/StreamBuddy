"""
Memory Management Module

This module implements memory management for stream data with automatic
eviction and cleanup to maintain stable memory usage.

Requirements: 9.2
"""

import time
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class VideoFrame:
    """Represents a video frame"""
    frame_data: bytes
    timestamp: float
    sequence_number: int
    width: int
    height: int


@dataclass
class AudioChunk:
    """Represents an audio chunk"""
    audio_data: bytes
    timestamp: float
    duration_ms: int


class StreamDataBuffer:
    """
    Manages stream data with automatic memory management.
    
    Maintains stable memory usage regardless of stream duration by
    automatically evicting old frames when size limit is reached.
    """
    
    def __init__(self, max_size_mb: int = 100):
        """
        Initialize the stream data buffer.
        
        Args:
            max_size_mb: Maximum buffer size in megabytes
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.current_size_bytes = 0
        
        self.video_frames: deque = deque()
        self.audio_chunks: deque = deque()
        
        self.metrics = {
            "total_frames_added": 0,
            "total_frames_evicted": 0,
            "total_audio_added": 0,
            "total_audio_evicted": 0,
            "peak_memory_bytes": 0,
            "eviction_count": 0
        }
        
        logger.info(f"Initialized stream data buffer: max_size={max_size_mb}MB")
    
    def add_video_frame(self, frame: VideoFrame) -> bool:
        """
        Add a video frame to the buffer.
        
        Args:
            frame: VideoFrame to add
        
        Returns:
            True if frame was added successfully
        """
        frame_size = len(frame.frame_data)
        
        # Evict old frames if necessary
        while (self.current_size_bytes + frame_size > self.max_size_bytes and
               self.video_frames):
            self._evict_oldest_video_frame()
        
        # Check if we have space
        if self.current_size_bytes + frame_size > self.max_size_bytes:
            logger.warning(
                f"Cannot add frame: would exceed max size "
                f"(current={self.current_size_bytes}, frame={frame_size}, "
                f"max={self.max_size_bytes})"
            )
            return False
        
        # Add frame
        self.video_frames.append(frame)
        self.current_size_bytes += frame_size
        self.metrics["total_frames_added"] += 1
        
        # Update peak memory
        if self.current_size_bytes > self.metrics["peak_memory_bytes"]:
            self.metrics["peak_memory_bytes"] = self.current_size_bytes
        
        logger.debug(
            f"Added video frame {frame.sequence_number}: "
            f"size={frame_size} bytes, total={self.current_size_bytes} bytes "
            f"({len(self.video_frames)} frames)"
        )
        
        return True
    
    def add_audio_chunk(self, chunk: AudioChunk) -> bool:
        """
        Add an audio chunk to the buffer.
        
        Args:
            chunk: AudioChunk to add
        
        Returns:
            True if chunk was added successfully
        """
        chunk_size = len(chunk.audio_data)
        
        # Evict old chunks if necessary
        while (self.current_size_bytes + chunk_size > self.max_size_bytes and
               self.audio_chunks):
            self._evict_oldest_audio_chunk()
        
        # Check if we have space
        if self.current_size_bytes + chunk_size > self.max_size_bytes:
            logger.warning(
                f"Cannot add audio chunk: would exceed max size "
                f"(current={self.current_size_bytes}, chunk={chunk_size}, "
                f"max={self.max_size_bytes})"
            )
            return False
        
        # Add chunk
        self.audio_chunks.append(chunk)
        self.current_size_bytes += chunk_size
        self.metrics["total_audio_added"] += 1
        
        # Update peak memory
        if self.current_size_bytes > self.metrics["peak_memory_bytes"]:
            self.metrics["peak_memory_bytes"] = self.current_size_bytes
        
        logger.debug(
            f"Added audio chunk: size={chunk_size} bytes, "
            f"total={self.current_size_bytes} bytes ({len(self.audio_chunks)} chunks)"
        )
        
        return True
    
    def _evict_oldest_video_frame(self):
        """Evict the oldest video frame"""
        if not self.video_frames:
            return
        
        old_frame = self.video_frames.popleft()
        frame_size = len(old_frame.frame_data)
        self.current_size_bytes -= frame_size
        self.metrics["total_frames_evicted"] += 1
        self.metrics["eviction_count"] += 1
        
        # Explicit cleanup
        del old_frame
        
        logger.debug(
            f"Evicted video frame: freed {frame_size} bytes, "
            f"remaining={self.current_size_bytes} bytes"
        )
    
    def _evict_oldest_audio_chunk(self):
        """Evict the oldest audio chunk"""
        if not self.audio_chunks:
            return
        
        old_chunk = self.audio_chunks.popleft()
        chunk_size = len(old_chunk.audio_data)
        self.current_size_bytes -= chunk_size
        self.metrics["total_audio_evicted"] += 1
        self.metrics["eviction_count"] += 1
        
        # Explicit cleanup
        del old_chunk
        
        logger.debug(
            f"Evicted audio chunk: freed {chunk_size} bytes, "
            f"remaining={self.current_size_bytes} bytes"
        )
    
    def get_recent_video_frames(self, count: int) -> List[VideoFrame]:
        """
        Get the most recent video frames.
        
        Args:
            count: Number of frames to retrieve
        
        Returns:
            List of recent VideoFrame objects
        """
        if count >= len(self.video_frames):
            return list(self.video_frames)
        
        return list(self.video_frames)[-count:]
    
    def get_recent_audio_chunks(self, count: int) -> List[AudioChunk]:
        """
        Get the most recent audio chunks.
        
        Args:
            count: Number of chunks to retrieve
        
        Returns:
            List of recent AudioChunk objects
        """
        if count >= len(self.audio_chunks):
            return list(self.audio_chunks)
        
        return list(self.audio_chunks)[-count:]
    
    def get_frames_in_time_window(self, window_seconds: float) -> List[VideoFrame]:
        """
        Get video frames within a time window.
        
        Args:
            window_seconds: Time window in seconds
        
        Returns:
            List of VideoFrame objects within the window
        """
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        return [
            frame for frame in self.video_frames
            if frame.timestamp >= cutoff_time
        ]
    
    def clear_old_data(self, max_age_seconds: float):
        """
        Clear data older than specified age.
        
        Args:
            max_age_seconds: Maximum age in seconds
        """
        current_time = time.time()
        cutoff_time = current_time - max_age_seconds
        
        # Clear old video frames
        while self.video_frames and self.video_frames[0].timestamp < cutoff_time:
            self._evict_oldest_video_frame()
        
        # Clear old audio chunks
        while self.audio_chunks and self.audio_chunks[0].timestamp < cutoff_time:
            self._evict_oldest_audio_chunk()
        
        logger.info(
            f"Cleared data older than {max_age_seconds}s: "
            f"{len(self.video_frames)} frames, {len(self.audio_chunks)} chunks remaining"
        )
    
    def clear_all(self):
        """Clear all buffered data"""
        frames_cleared = len(self.video_frames)
        chunks_cleared = len(self.audio_chunks)
        
        self.video_frames.clear()
        self.audio_chunks.clear()
        self.current_size_bytes = 0
        
        logger.info(
            f"Cleared all data: {frames_cleared} frames, {chunks_cleared} chunks"
        )
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """
        Get current memory usage statistics.
        
        Returns:
            Dictionary with memory usage information
        """
        video_size = sum(len(f.frame_data) for f in self.video_frames)
        audio_size = sum(len(c.audio_data) for c in self.audio_chunks)
        
        return {
            "total_bytes": self.current_size_bytes,
            "total_mb": self.current_size_bytes / (1024 * 1024),
            "max_bytes": self.max_size_bytes,
            "max_mb": self.max_size_bytes / (1024 * 1024),
            "usage_percent": (self.current_size_bytes / self.max_size_bytes) * 100,
            "video_frames_count": len(self.video_frames),
            "video_frames_bytes": video_size,
            "audio_chunks_count": len(self.audio_chunks),
            "audio_chunks_bytes": audio_size
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get buffer metrics"""
        return {
            **self.metrics,
            **self.get_memory_usage()
        }
    
    def reset_metrics(self):
        """Reset buffer metrics"""
        self.metrics = {
            "total_frames_added": 0,
            "total_frames_evicted": 0,
            "total_audio_added": 0,
            "total_audio_evicted": 0,
            "peak_memory_bytes": self.current_size_bytes,
            "eviction_count": 0
        }


class MemoryMonitor:
    """
    Monitors system memory usage and triggers cleanup when needed.
    """
    
    def __init__(
        self,
        buffer: StreamDataBuffer,
        check_interval_seconds: float = 5.0,
        cleanup_threshold_percent: float = 80.0
    ):
        """
        Initialize the memory monitor.
        
        Args:
            buffer: StreamDataBuffer to monitor
            check_interval_seconds: How often to check memory
            cleanup_threshold_percent: Trigger cleanup at this usage percent
        """
        self.buffer = buffer
        self.check_interval_seconds = check_interval_seconds
        self.cleanup_threshold_percent = cleanup_threshold_percent
        
        self.cleanup_count = 0
        self.last_check_time = time.time()
    
    def check_and_cleanup(self) -> bool:
        """
        Check memory usage and cleanup if needed.
        
        Returns:
            True if cleanup was performed
        """
        current_time = time.time()
        
        # Check if it's time to check
        if current_time - self.last_check_time < self.check_interval_seconds:
            return False
        
        self.last_check_time = current_time
        
        # Get memory usage
        usage = self.buffer.get_memory_usage()
        usage_percent = usage["usage_percent"]
        
        logger.debug(
            f"Memory check: {usage_percent:.1f}% used "
            f"({usage['total_mb']:.2f}MB / {usage['max_mb']:.2f}MB)"
        )
        
        # Check if cleanup is needed
        if usage_percent >= self.cleanup_threshold_percent:
            logger.warning(
                f"Memory usage high ({usage_percent:.1f}%), triggering cleanup"
            )
            
            # Clear data older than 30 seconds
            self.buffer.clear_old_data(max_age_seconds=30.0)
            self.cleanup_count += 1
            
            return True
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics"""
        return {
            "cleanup_count": self.cleanup_count,
            "last_check_time": self.last_check_time,
            "check_interval_seconds": self.check_interval_seconds,
            "cleanup_threshold_percent": self.cleanup_threshold_percent
        }


# Example usage
def example_usage():
    """Example of using the memory management module"""
    
    # Create buffer with 10MB limit
    buffer = StreamDataBuffer(max_size_mb=10)
    
    # Create monitor
    monitor = MemoryMonitor(
        buffer=buffer,
        check_interval_seconds=2.0,
        cleanup_threshold_percent=80.0
    )
    
    print("Adding video frames...")
    
    # Add frames until we hit the limit
    for i in range(100):
        # Create a 1MB frame
        frame = VideoFrame(
            frame_data=b"x" * (1024 * 1024),
            timestamp=time.time(),
            sequence_number=i,
            width=1920,
            height=1080
        )
        
        success = buffer.add_video_frame(frame)
        
        if i % 10 == 0:
            usage = buffer.get_memory_usage()
            print(
                f"Frame {i}: {usage['total_mb']:.2f}MB / {usage['max_mb']:.2f}MB "
                f"({usage['usage_percent']:.1f}%)"
            )
            
            # Check for cleanup
            if monitor.check_and_cleanup():
                print("  -> Cleanup triggered!")
        
        if not success:
            print(f"Failed to add frame {i}")
            break
        
        time.sleep(0.1)
    
    # Print final metrics
    print("\nBuffer metrics:")
    for key, value in buffer.get_metrics().items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")
    
    print("\nMonitor stats:")
    for key, value in monitor.get_stats().items():
        print(f"  {key}: {value}")
    
    # Test retrieval
    print("\nRecent frames:")
    recent = buffer.get_recent_video_frames(5)
    print(f"  Retrieved {len(recent)} recent frames")
    
    # Clear all
    buffer.clear_all()
    print("\nAfter clear:")
    usage = buffer.get_memory_usage()
    print(f"  Memory usage: {usage['total_mb']:.2f}MB")


if __name__ == "__main__":
    example_usage()
