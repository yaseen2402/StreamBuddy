"""
Adaptive Quality Controller Module

This module implements adaptive quality adjustment based on latency metrics
to maintain functionality under varying network conditions.

Requirements: 9.3, 9.4
"""

import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class QualityLevel(Enum):
    """Quality level settings"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class QualitySettings:
    """Quality configuration settings"""
    video_fps: float
    video_quality: int  # JPEG quality 0-100
    audio_quality: str  # "high", "medium", "low"
    chat_filter_threshold: float  # 0.0-1.0
    max_video_dimension: int


@dataclass
class LatencyMeasurement:
    """Represents a latency measurement"""
    timestamp: float
    latency_ms: float
    operation_type: str  # "chat", "video", "audio"


class AdaptiveQualityController:
    """
    Adjusts processing quality based on latency metrics.
    
    Maintains functionality under poor network conditions by automatically
    switching between high/medium/low quality settings based on performance.
    """
    
    # Quality presets
    QUALITY_PRESETS = {
        QualityLevel.HIGH: QualitySettings(
            video_fps=3.0,
            video_quality=85,
            audio_quality="high",
            chat_filter_threshold=0.3,
            max_video_dimension=1280
        ),
        QualityLevel.MEDIUM: QualitySettings(
            video_fps=1.0,
            video_quality=70,
            audio_quality="medium",
            chat_filter_threshold=0.5,
            max_video_dimension=960
        ),
        QualityLevel.LOW: QualitySettings(
            video_fps=0.5,
            video_quality=50,
            audio_quality="low",
            chat_filter_threshold=0.8,
            max_video_dimension=640
        )
    }
    
    def __init__(
        self,
        target_latency_ms: float = 2000.0,
        latency_window_size: int = 10,
        adjustment_threshold: float = 0.7
    ):
        """
        Initialize the adaptive quality controller.
        
        Args:
            target_latency_ms: Target latency threshold
            latency_window_size: Number of recent measurements to consider
            adjustment_threshold: Threshold for quality adjustment (0.0-1.0)
        """
        self.target_latency_ms = target_latency_ms
        self.latency_window_size = latency_window_size
        self.adjustment_threshold = adjustment_threshold
        
        self.current_quality = QualityLevel.HIGH
        self.recent_latencies: List[LatencyMeasurement] = []
        self.last_adjustment_time = time.time()
        self.adjustment_cooldown_seconds = 10.0
        
        self.metrics = {
            "total_adjustments": 0,
            "quality_upgrades": 0,
            "quality_downgrades": 0,
            "time_in_high": 0.0,
            "time_in_medium": 0.0,
            "time_in_low": 0.0,
            "avg_latency_ms": 0.0,
            "latency_violations": 0
        }
        
        self._quality_start_time = time.time()
        
        logger.info(
            f"Initialized adaptive quality controller: "
            f"target_latency={target_latency_ms}ms, "
            f"initial_quality={self.current_quality.value}"
        )
    
    def record_latency(
        self,
        latency_ms: float,
        operation_type: str = "general"
    ):
        """
        Record a latency measurement.
        
        Args:
            latency_ms: Latency in milliseconds
            operation_type: Type of operation measured
        """
        measurement = LatencyMeasurement(
            timestamp=time.time(),
            latency_ms=latency_ms,
            operation_type=operation_type
        )
        
        self.recent_latencies.append(measurement)
        
        # Maintain sliding window
        if len(self.recent_latencies) > self.latency_window_size:
            self.recent_latencies.pop(0)
        
        # Update metrics
        total_measurements = sum(
            1 for _ in self.recent_latencies
        )
        if total_measurements > 0:
            self.metrics["avg_latency_ms"] = (
                sum(m.latency_ms for m in self.recent_latencies) / total_measurements
            )
        
        # Check for latency violation
        if latency_ms > self.target_latency_ms:
            self.metrics["latency_violations"] += 1
        
        logger.debug(
            f"Recorded latency: {latency_ms:.2f}ms ({operation_type}), "
            f"avg={self.metrics['avg_latency_ms']:.2f}ms"
        )
        
        # Check if quality adjustment is needed
        self._check_and_adjust_quality()
    
    def _check_and_adjust_quality(self):
        """Check if quality adjustment is needed and apply it"""
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_adjustment_time < self.adjustment_cooldown_seconds:
            return
        
        # Need enough measurements
        if len(self.recent_latencies) < self.latency_window_size:
            return
        
        # Calculate average latency
        avg_latency = sum(m.latency_ms for m in self.recent_latencies) / len(self.recent_latencies)
        
        # Calculate percentage of measurements exceeding threshold
        violations = sum(
            1 for m in self.recent_latencies
            if m.latency_ms > self.target_latency_ms
        )
        violation_rate = violations / len(self.recent_latencies)
        
        logger.debug(
            f"Quality check: avg_latency={avg_latency:.2f}ms, "
            f"violation_rate={violation_rate:.2%}, "
            f"current_quality={self.current_quality.value}"
        )
        
        # Determine if adjustment is needed
        if violation_rate > self.adjustment_threshold:
            # Latency too high, downgrade quality
            self._downgrade_quality()
        elif violation_rate < self.adjustment_threshold * 0.5 and avg_latency < self.target_latency_ms * 0.7:
            # Latency good, try upgrading quality
            self._upgrade_quality()
    
    def _downgrade_quality(self):
        """Downgrade to lower quality setting"""
        previous_quality = self.current_quality
        
        if self.current_quality == QualityLevel.HIGH:
            self.current_quality = QualityLevel.MEDIUM
        elif self.current_quality == QualityLevel.MEDIUM:
            self.current_quality = QualityLevel.LOW
        else:
            # Already at lowest quality
            logger.warning("Already at lowest quality, cannot downgrade further")
            return
        
        self._apply_quality_change(previous_quality)
        self.metrics["quality_downgrades"] += 1
        
        logger.warning(
            f"Quality downgraded: {previous_quality.value} -> {self.current_quality.value}"
        )
    
    def _upgrade_quality(self):
        """Upgrade to higher quality setting"""
        previous_quality = self.current_quality
        
        if self.current_quality == QualityLevel.LOW:
            self.current_quality = QualityLevel.MEDIUM
        elif self.current_quality == QualityLevel.MEDIUM:
            self.current_quality = QualityLevel.HIGH
        else:
            # Already at highest quality
            return
        
        self._apply_quality_change(previous_quality)
        self.metrics["quality_upgrades"] += 1
        
        logger.info(
            f"Quality upgraded: {previous_quality.value} -> {self.current_quality.value}"
        )
    
    def _apply_quality_change(self, previous_quality: QualityLevel):
        """Apply quality change and update metrics"""
        current_time = time.time()
        time_in_previous = current_time - self._quality_start_time
        
        # Update time in quality metrics
        if previous_quality == QualityLevel.HIGH:
            self.metrics["time_in_high"] += time_in_previous
        elif previous_quality == QualityLevel.MEDIUM:
            self.metrics["time_in_medium"] += time_in_previous
        elif previous_quality == QualityLevel.LOW:
            self.metrics["time_in_low"] += time_in_previous
        
        self.metrics["total_adjustments"] += 1
        self.last_adjustment_time = current_time
        self._quality_start_time = current_time
    
    def get_current_settings(self) -> QualitySettings:
        """
        Get current quality settings.
        
        Returns:
            QualitySettings for current quality level
        """
        return self.QUALITY_PRESETS[self.current_quality]
    
    def get_quality_level(self) -> QualityLevel:
        """
        Get current quality level.
        
        Returns:
            Current QualityLevel
        """
        return self.current_quality
    
    def force_quality_level(self, quality: QualityLevel):
        """
        Force a specific quality level.
        
        Args:
            quality: QualityLevel to set
        """
        previous_quality = self.current_quality
        self.current_quality = quality
        
        if previous_quality != quality:
            self._apply_quality_change(previous_quality)
            logger.info(f"Quality manually set to: {quality.value}")
    
    def get_latency_statistics(self) -> Dict[str, Any]:
        """
        Get latency statistics.
        
        Returns:
            Dictionary with latency statistics
        """
        if not self.recent_latencies:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p95_ms": 0.0
            }
        
        latencies = [m.latency_ms for m in self.recent_latencies]
        latencies_sorted = sorted(latencies)
        
        # Calculate p95
        p95_index = int(len(latencies_sorted) * 0.95)
        p95 = latencies_sorted[p95_index] if p95_index < len(latencies_sorted) else latencies_sorted[-1]
        
        return {
            "count": len(latencies),
            "avg_ms": sum(latencies) / len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
            "p95_ms": p95,
            "target_ms": self.target_latency_ms,
            "violation_rate": self.metrics["latency_violations"] / len(latencies) if latencies else 0.0
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get controller metrics"""
        # Update current quality time
        current_time = time.time()
        time_in_current = current_time - self._quality_start_time
        
        metrics = self.metrics.copy()
        
        if self.current_quality == QualityLevel.HIGH:
            metrics["time_in_high"] += time_in_current
        elif self.current_quality == QualityLevel.MEDIUM:
            metrics["time_in_medium"] += time_in_current
        elif self.current_quality == QualityLevel.LOW:
            metrics["time_in_low"] += time_in_current
        
        return {
            **metrics,
            "current_quality": self.current_quality.value,
            "latency_stats": self.get_latency_statistics()
        }
    
    def reset_metrics(self):
        """Reset controller metrics"""
        self.metrics = {
            "total_adjustments": 0,
            "quality_upgrades": 0,
            "quality_downgrades": 0,
            "time_in_high": 0.0,
            "time_in_medium": 0.0,
            "time_in_low": 0.0,
            "avg_latency_ms": 0.0,
            "latency_violations": 0
        }
        self._quality_start_time = time.time()


class QualityAwareProcessor:
    """
    Processor that adapts its behavior based on quality settings.
    """
    
    def __init__(self, controller: AdaptiveQualityController):
        """
        Initialize the quality-aware processor.
        
        Args:
            controller: AdaptiveQualityController instance
        """
        self.controller = controller
    
    def should_process_video_frame(self, last_frame_time: float) -> bool:
        """
        Determine if a video frame should be processed.
        
        Args:
            last_frame_time: Timestamp of last processed frame
        
        Returns:
            True if frame should be processed
        """
        settings = self.controller.get_current_settings()
        current_time = time.time()
        
        time_since_last = current_time - last_frame_time
        frame_interval = 1.0 / settings.video_fps
        
        return time_since_last >= frame_interval
    
    def get_video_compression_settings(self) -> Dict[str, Any]:
        """
        Get video compression settings based on quality.
        
        Returns:
            Dictionary with compression settings
        """
        settings = self.controller.get_current_settings()
        
        return {
            "quality": settings.video_quality,
            "max_dimension": settings.max_video_dimension,
            "format": "jpeg"
        }
    
    def should_process_chat_message(self, message_priority: float) -> bool:
        """
        Determine if a chat message should be processed.
        
        Args:
            message_priority: Message priority (0.0-1.0)
        
        Returns:
            True if message should be processed
        """
        settings = self.controller.get_current_settings()
        return message_priority >= settings.chat_filter_threshold
    
    def get_audio_settings(self) -> Dict[str, Any]:
        """
        Get audio processing settings based on quality.
        
        Returns:
            Dictionary with audio settings
        """
        settings = self.controller.get_current_settings()
        
        # Map quality to specific settings
        audio_configs = {
            "high": {"bitrate": 128, "sample_rate": 24000},
            "medium": {"bitrate": 96, "sample_rate": 16000},
            "low": {"bitrate": 64, "sample_rate": 16000}
        }
        
        return audio_configs.get(settings.audio_quality, audio_configs["medium"])


# Example usage
def example_usage():
    """Example of using the adaptive quality controller"""
    
    # Create controller
    controller = AdaptiveQualityController(
        target_latency_ms=2000.0,
        latency_window_size=10,
        adjustment_threshold=0.7
    )
    
    # Create processor
    processor = QualityAwareProcessor(controller)
    
    print("Simulating good latency (high quality)...")
    for i in range(15):
        controller.record_latency(latency_ms=1500.0, operation_type="chat")
        time.sleep(0.1)
    
    print(f"Current quality: {controller.get_quality_level().value}")
    print(f"Settings: {controller.get_current_settings()}")
    
    print("\nSimulating poor latency (should downgrade)...")
    for i in range(15):
        controller.record_latency(latency_ms=3000.0, operation_type="video")
        time.sleep(0.1)
    
    print(f"Current quality: {controller.get_quality_level().value}")
    print(f"Settings: {controller.get_current_settings()}")
    
    print("\nSimulating very poor latency (should downgrade further)...")
    for i in range(15):
        controller.record_latency(latency_ms=4000.0, operation_type="audio")
        time.sleep(0.1)
    
    print(f"Current quality: {controller.get_quality_level().value}")
    print(f"Settings: {controller.get_current_settings()}")
    
    print("\nSimulating improved latency (should upgrade)...")
    for i in range(15):
        controller.record_latency(latency_ms=1000.0, operation_type="chat")
        time.sleep(0.1)
    
    print(f"Current quality: {controller.get_quality_level().value}")
    print(f"Settings: {controller.get_current_settings()}")
    
    # Print metrics
    print("\nController metrics:")
    for key, value in controller.get_metrics().items():
        if key == "latency_stats":
            print(f"  {key}:")
            for stat_key, stat_value in value.items():
                print(f"    {stat_key}: {stat_value}")
        elif isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")
    
    # Test processor
    print("\nTesting quality-aware processor...")
    print(f"Video compression: {processor.get_video_compression_settings()}")
    print(f"Audio settings: {processor.get_audio_settings()}")
    print(f"Should process high priority message (0.9): {processor.should_process_chat_message(0.9)}")
    print(f"Should process low priority message (0.2): {processor.should_process_chat_message(0.2)}")


if __name__ == "__main__":
    example_usage()
