"""
Cloud Monitoring integration for StreamBuddy.

Provides metric recording functions for latency, API duration, and error rates
with efficient batching for uploads to Google Cloud Monitoring.

Requirements: 10.1, 10.6
"""

import os
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
from queue import Queue, Empty


class MetricType(Enum):
    """Types of metrics tracked by StreamBuddy."""
    RESPONSE_LATENCY = "response_latency"
    API_CALL_DURATION = "api_call_duration"
    ERROR_RATE = "error_rate"
    FRAME_PROCESSING_TIME = "frame_processing_time"
    CHAT_MESSAGE_LATENCY = "chat_message_latency"
    AUDIO_OUTPUT_LATENCY = "audio_output_latency"


@dataclass
class MetricPoint:
    """
    A single metric data point.
    
    Attributes:
        metric_type: Type of metric
        value: Metric value (float)
        labels: Additional labels for the metric
        timestamp: When the metric was recorded
    """
    metric_type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class CloudMonitoringClient:
    """
    Client for recording metrics to Google Cloud Monitoring.
    
    Supports both local development (console output) and production
    (Cloud Monitoring) with automatic batching for efficient uploads.
    """
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        batch_size: int = 10,
        batch_interval: float = 5.0,
        use_cloud_monitoring: Optional[bool] = None
    ):
        """
        Initialize Cloud Monitoring client.
        
        Args:
            project_id: GCP project ID (auto-detected if None)
            batch_size: Number of metrics to batch before upload
            batch_interval: Maximum seconds to wait before uploading batch
            use_cloud_monitoring: Force Cloud Monitoring on/off (auto-detect if None)
        """
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID')
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        
        # Auto-detect environment if not specified
        if use_cloud_monitoring is None:
            use_cloud_monitoring = bool(
                os.getenv('K_SERVICE') or  # Cloud Run
                os.getenv('GAE_ENV') or    # App Engine
                os.getenv('FUNCTION_NAME')  # Cloud Functions
            )
        
        self.use_cloud_monitoring = use_cloud_monitoring
        self._metric_queue: Queue[MetricPoint] = Queue()
        self._batch: List[MetricPoint] = []
        self._last_upload_time = time.time()
        self._lock = threading.Lock()
        self._running = False
        self._upload_thread: Optional[threading.Thread] = None
        
        # Initialize Cloud Monitoring client if in production
        self._monitoring_client = None
        if self.use_cloud_monitoring:
            self._setup_cloud_monitoring()
        
        # Start background upload thread
        self.start()
    
    def _setup_cloud_monitoring(self):
        """Set up Google Cloud Monitoring client."""
        try:
            from google.cloud import monitoring_v3
            
            if not self.project_id:
                raise ValueError(
                    "GCP_PROJECT_ID environment variable must be set for Cloud Monitoring"
                )
            
            self._monitoring_client = monitoring_v3.MetricServiceClient()
            self._project_name = f"projects/{self.project_id}"
            
            print(f"Cloud Monitoring initialized for project: {self.project_id}")
            
        except ImportError:
            print(
                "WARNING: google-cloud-monitoring not installed, "
                "metrics will only be logged to console"
            )
            self.use_cloud_monitoring = False
        except Exception as e:
            print(
                f"WARNING: Failed to initialize Cloud Monitoring: {e}, "
                "metrics will only be logged to console"
            )
            self.use_cloud_monitoring = False
    
    def start(self):
        """Start the background metric upload thread."""
        if not self._running:
            self._running = True
            self._upload_thread = threading.Thread(
                target=self._upload_worker,
                daemon=True,
                name="CloudMonitoringUploader"
            )
            self._upload_thread.start()
    
    def stop(self):
        """Stop the background upload thread and flush remaining metrics."""
        self._running = False
        if self._upload_thread:
            self._upload_thread.join(timeout=5.0)
        
        # Flush any remaining metrics
        self._flush_batch()
    
    def record_metric(
        self,
        metric_type: MetricType,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ):
        """
        Record a metric value.
        
        Metrics are queued and uploaded in batches for efficiency.
        
        Args:
            metric_type: Type of metric to record
            value: Metric value
            labels: Additional labels for the metric (e.g., {"type": "chat", "api": "gemini"})
        """
        metric_point = MetricPoint(
            metric_type=metric_type,
            value=value,
            labels=labels or {}
        )
        
        self._metric_queue.put(metric_point)
    
    def record_latency(
        self,
        latency_ms: float,
        operation_type: str,
        **labels
    ):
        """
        Record response latency metric.
        
        Args:
            latency_ms: Latency in milliseconds
            operation_type: Type of operation (e.g., "chat", "commentary", "video_analysis")
            **labels: Additional labels
        """
        all_labels = {"type": operation_type}
        all_labels.update(labels)
        
        self.record_metric(
            MetricType.RESPONSE_LATENCY,
            latency_ms,
            all_labels
        )
    
    def record_api_duration(
        self,
        duration_ms: float,
        api_name: str,
        **labels
    ):
        """
        Record API call duration metric.
        
        Args:
            duration_ms: Duration in milliseconds
            api_name: Name of the API (e.g., "gemini", "youtube")
            **labels: Additional labels
        """
        all_labels = {"api": api_name}
        all_labels.update(labels)
        
        self.record_metric(
            MetricType.API_CALL_DURATION,
            duration_ms,
            all_labels
        )
    
    def record_error(
        self,
        component: str,
        error_type: str,
        **labels
    ):
        """
        Record an error occurrence.
        
        Args:
            component: Component where error occurred
            error_type: Type of error
            **labels: Additional labels
        """
        all_labels = {"component": component, "error_type": error_type}
        all_labels.update(labels)
        
        self.record_metric(
            MetricType.ERROR_RATE,
            1.0,  # Count of 1 for each error
            all_labels
        )
    
    def _upload_worker(self):
        """Background worker thread for uploading metrics."""
        while self._running:
            try:
                # Try to get metrics from queue with timeout
                try:
                    metric = self._metric_queue.get(timeout=1.0)
                    with self._lock:
                        self._batch.append(metric)
                except Empty:
                    pass
                
                # Check if we should upload the batch
                with self._lock:
                    should_upload = (
                        len(self._batch) >= self.batch_size or
                        (len(self._batch) > 0 and 
                         time.time() - self._last_upload_time >= self.batch_interval)
                    )
                
                if should_upload:
                    self._flush_batch()
                    
            except Exception as e:
                print(f"Error in metric upload worker: {e}")
    
    def _flush_batch(self):
        """Upload the current batch of metrics."""
        with self._lock:
            if not self._batch:
                return
            
            batch_to_upload = self._batch.copy()
            self._batch.clear()
            self._last_upload_time = time.time()
        
        if self.use_cloud_monitoring and self._monitoring_client:
            self._upload_to_cloud_monitoring(batch_to_upload)
        else:
            self._log_metrics_to_console(batch_to_upload)
    
    def _upload_to_cloud_monitoring(self, metrics: List[MetricPoint]):
        """
        Upload metrics to Google Cloud Monitoring.
        
        Args:
            metrics: List of metric points to upload
        """
        try:
            from google.cloud import monitoring_v3
            
            time_series_list = []
            
            for metric in metrics:
                series = monitoring_v3.TimeSeries()
                
                # Set metric type
                series.metric.type = (
                    f"custom.googleapis.com/streambuddy/{metric.metric_type.value}"
                )
                
                # Set metric labels
                for key, value in metric.labels.items():
                    series.metric.labels[key] = str(value)
                
                # Set resource (generic_task for Cloud Run)
                series.resource.type = "generic_task"
                series.resource.labels["project_id"] = self.project_id
                series.resource.labels["location"] = os.getenv("CLOUD_RUN_REGION", "us-central1")
                series.resource.labels["namespace"] = "streambuddy"
                series.resource.labels["job"] = os.getenv("K_SERVICE", "streambuddy")
                series.resource.labels["task_id"] = os.getenv("K_REVISION", "local")
                
                # Create data point
                point = monitoring_v3.Point()
                point.value.double_value = metric.value
                
                # Set timestamp
                point.interval.end_time.seconds = int(metric.timestamp)
                point.interval.end_time.nanos = int((metric.timestamp % 1) * 1e9)
                
                series.points = [point]
                time_series_list.append(series)
            
            # Upload batch
            if time_series_list:
                self._monitoring_client.create_time_series(
                    name=self._project_name,
                    time_series=time_series_list
                )
                print(f"Uploaded {len(time_series_list)} metrics to Cloud Monitoring")
                
        except Exception as e:
            print(f"Failed to upload metrics to Cloud Monitoring: {e}")
            # Fall back to console logging
            self._log_metrics_to_console(metrics)
    
    def _log_metrics_to_console(self, metrics: List[MetricPoint]):
        """
        Log metrics to console (for local development).
        
        Args:
            metrics: List of metric points to log
        """
        for metric in metrics:
            timestamp = datetime.fromtimestamp(metric.timestamp).isoformat()
            labels_str = ", ".join(f"{k}={v}" for k, v in metric.labels.items())
            print(
                f"[METRIC] {timestamp} | {metric.metric_type.value}={metric.value:.2f} | {labels_str}"
            )


# Global monitoring client instance
_monitoring_client: Optional[CloudMonitoringClient] = None


def get_monitoring_client(
    project_id: Optional[str] = None,
    batch_size: int = 10,
    batch_interval: float = 5.0,
    use_cloud_monitoring: Optional[bool] = None
) -> CloudMonitoringClient:
    """
    Get or create the global monitoring client instance.
    
    Args:
        project_id: GCP project ID (auto-detected if None)
        batch_size: Number of metrics to batch before upload
        batch_interval: Maximum seconds to wait before uploading batch
        use_cloud_monitoring: Force Cloud Monitoring on/off (auto-detect if None)
        
    Returns:
        CloudMonitoringClient instance
    """
    global _monitoring_client
    
    if _monitoring_client is None:
        _monitoring_client = CloudMonitoringClient(
            project_id=project_id,
            batch_size=batch_size,
            batch_interval=batch_interval,
            use_cloud_monitoring=use_cloud_monitoring
        )
    
    return _monitoring_client


def record_latency(latency_ms: float, operation_type: str, **labels):
    """
    Convenience function to record latency metric.
    
    Args:
        latency_ms: Latency in milliseconds
        operation_type: Type of operation
        **labels: Additional labels
    """
    client = get_monitoring_client()
    client.record_latency(latency_ms, operation_type, **labels)


def record_api_duration(duration_ms: float, api_name: str, **labels):
    """
    Convenience function to record API duration metric.
    
    Args:
        duration_ms: Duration in milliseconds
        api_name: Name of the API
        **labels: Additional labels
    """
    client = get_monitoring_client()
    client.record_api_duration(duration_ms, api_name, **labels)


def record_error(component: str, error_type: str, **labels):
    """
    Convenience function to record error metric.
    
    Args:
        component: Component where error occurred
        error_type: Type of error
        **labels: Additional labels
    """
    client = get_monitoring_client()
    client.record_error(component, error_type, **labels)


def shutdown_monitoring():
    """Shutdown the monitoring client and flush remaining metrics."""
    global _monitoring_client
    
    if _monitoring_client:
        _monitoring_client.stop()
        _monitoring_client = None
