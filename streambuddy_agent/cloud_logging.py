"""
Cloud Logging integration for StreamBuddy.

Provides structured logging with component tagging that works both locally
(console output) and in production (Google Cloud Logging).

Requirements: 7.6, 10.2, 10.5
"""

import logging
import os
import sys
import json
from typing import Any, Dict, Optional
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log levels for StreamBuddy."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StreamBuddyLogger:
    """
    Structured logger with component tagging for StreamBuddy.
    
    Supports both local development (console) and production (Cloud Logging).
    Automatically detects environment and configures appropriate handler.
    """
    
    def __init__(
        self,
        component: str,
        log_level: LogLevel = LogLevel.INFO,
        use_cloud_logging: Optional[bool] = None
    ):
        """
        Initialize StreamBuddy logger.
        
        Args:
            component: Component name for tagging (e.g., "chat_monitor", "gemini_client")
            log_level: Minimum log level to output
            use_cloud_logging: Force Cloud Logging on/off. If None, auto-detect based on environment
        """
        self.component = component
        self.log_level = log_level
        
        # Auto-detect environment if not specified
        if use_cloud_logging is None:
            # Use Cloud Logging if running on GCP (detected by environment variables)
            use_cloud_logging = bool(
                os.getenv('K_SERVICE') or  # Cloud Run
                os.getenv('GAE_ENV') or    # App Engine
                os.getenv('FUNCTION_NAME')  # Cloud Functions
            )
        
        self.use_cloud_logging = use_cloud_logging
        self._setup_logger()
    
    def _setup_logger(self):
        """Set up the logger with appropriate handler."""
        self.logger = logging.getLogger(f'streambuddy.{self.component}')
        self.logger.setLevel(getattr(logging, self.log_level.value))
        
        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        if self.use_cloud_logging:
            self._setup_cloud_logging()
        else:
            self._setup_console_logging()
    
    def _setup_cloud_logging(self):
        """Set up Google Cloud Logging handler."""
        try:
            from google.cloud import logging as cloud_logging
            
            # Initialize Cloud Logging client
            client = cloud_logging.Client()
            
            # Use Cloud Logging handler
            handler = cloud_logging.handlers.CloudLoggingHandler(client)
            handler.setLevel(getattr(logging, self.log_level.value))
            
            self.logger.addHandler(handler)
            self.logger.info(f"Cloud Logging initialized for component: {self.component}")
            
        except ImportError:
            # Fall back to console logging if Cloud Logging not available
            self.logger.warning(
                "google-cloud-logging not installed, falling back to console logging"
            )
            self._setup_console_logging()
        except Exception as e:
            # Fall back to console logging on any error
            self.logger.warning(
                f"Failed to initialize Cloud Logging: {e}, falling back to console"
            )
            self._setup_console_logging()
    
    def _setup_console_logging(self):
        """Set up console logging with structured format."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, self.log_level.value))
        
        # Use JSON format for structured logging
        formatter = StructuredFormatter(self.component)
        handler.setFormatter(formatter)
        
        self.logger.addHandler(handler)
    
    def _log(
        self,
        level: LogLevel,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False
    ):
        """
        Internal logging method with structured data.
        
        Args:
            level: Log level
            message: Log message
            extra: Additional structured data to include
            exc_info: Include exception information
        """
        log_data = {
            "component": self.component,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if extra:
            log_data.update(extra)
        
        log_method = getattr(self.logger, level.value.lower())
        log_method(message, extra=log_data, exc_info=exc_info)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log(LogLevel.DEBUG, message, extra=kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log(LogLevel.INFO, message, extra=kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log(LogLevel.WARNING, message, extra=kwargs)
    
    def error(self, message: str, exc_info: bool = False, **kwargs):
        """Log error message."""
        self._log(LogLevel.ERROR, message, extra=kwargs, exc_info=exc_info)
    
    def critical(self, message: str, exc_info: bool = False, **kwargs):
        """Log critical message."""
        self._log(LogLevel.CRITICAL, message, extra=kwargs, exc_info=exc_info)


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter for structured JSON logging.
    
    Formats log records as JSON with component tagging and structured data.
    """
    
    def __init__(self, component: str):
        """
        Initialize formatter.
        
        Args:
            component: Component name for tagging
        """
        super().__init__()
        self.component = component
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "severity": record.levelname,
            "component": self.component,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, 'component'):
            log_data["component"] = record.component
        
        # Add any additional structured data
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName',
                          'relativeCreated', 'thread', 'threadName', 'exc_info',
                          'exc_text', 'stack_info', 'component', 'timestamp']:
                try:
                    # Only include JSON-serializable values
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def get_logger(
    component: str,
    log_level: Optional[LogLevel] = None,
    use_cloud_logging: Optional[bool] = None
) -> StreamBuddyLogger:
    """
    Get a logger instance for a component.
    
    Args:
        component: Component name for tagging
        log_level: Minimum log level (defaults to INFO or LOG_LEVEL env var)
        use_cloud_logging: Force Cloud Logging on/off (auto-detect if None)
        
    Returns:
        Configured StreamBuddyLogger instance
    """
    # Get log level from environment if not specified
    if log_level is None:
        env_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        try:
            log_level = LogLevel[env_level]
        except KeyError:
            log_level = LogLevel.INFO
    
    return StreamBuddyLogger(
        component=component,
        log_level=log_level,
        use_cloud_logging=use_cloud_logging
    )
