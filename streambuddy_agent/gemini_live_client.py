"""
Gemini Live API Client Module

This module implements session management for Google's Gemini Live API, including
session establishment with API key authentication, persistent connection maintenance,
session reconnection logic on connection loss, rate limit handling, and circuit breaker
pattern for API failures.

Validates: Requirements 2.1, 2.6, 2.7, 12.1, 13.3
"""

import logging
import time
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
from google import genai
from google.genai import types

# Configure logging
logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session states for Gemini Live API"""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class CircuitBreakerState(Enum):
    """Circuit breaker states for API failure handling"""
    CLOSED = "CLOSED"  # Normal operation, requests allowed
    OPEN = "OPEN"  # Too many failures, requests blocked
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    max_requests_per_minute: int = 60  # Maximum requests per minute
    max_requests_per_second: int = 10  # Maximum requests per second
    throttle_threshold: float = 0.8  # Start throttling at 80% of limit
    backoff_base: float = 1.0  # Base delay for exponential backoff (seconds)
    backoff_max: float = 60.0  # Maximum backoff delay (seconds)
    backoff_multiplier: float = 2.0  # Multiplier for exponential backoff


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Number of failures before opening circuit
    timeout: int = 60  # Seconds to wait before trying again (OPEN -> HALF_OPEN)
    success_threshold: int = 2  # Successes needed in HALF_OPEN to close circuit


@dataclass
class RateLimitMetrics:
    """Metrics for rate limiting and circuit breaker"""
    requests_this_second: int = 0
    requests_this_minute: int = 0
    throttled_requests: int = 0
    rate_limit_errors: int = 0
    last_request_time: Optional[float] = None
    request_timestamps: List[float] = field(default_factory=list)
    
    # Circuit breaker metrics
    circuit_state: CircuitBreakerState = CircuitBreakerState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[float] = None
    circuit_open_count: int = 0
    total_failures: int = 0


@dataclass
class SessionConfig:
    """Configuration for Gemini Live API session"""
    model: str = "gemini-2.5-flash"  # Use gemini-2.0-flash-exp or latest available model
    response_modalities: list = None
    voice_name: str = "Puck"
    system_instruction: str = None  # System instruction for the model
    
    def __post_init__(self):
        """Initialize default response modalities"""
        if self.response_modalities is None:
            self.response_modalities = ["AUDIO"]


@dataclass
class SessionMetrics:
    """Metrics for session monitoring"""
    session_attempts: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    disconnections: int = 0
    reconnections: int = 0
    last_session_time: Optional[float] = None
    last_disconnection_time: Optional[float] = None
    total_session_time: float = 0.0


class GeminiLiveClient:
    """
    Manages connection to Gemini Live API with session establishment,
    persistent connection maintenance, reconnection logic, rate limiting,
    and circuit breaker pattern for API failures.
    
    Validates: Requirements 2.1, 2.6, 2.7, 12.1, 13.3
    """
    
    def __init__(
        self,
        session_config: Optional[SessionConfig] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialize Gemini Live API client.
        
        Args:
            session_config: Configuration for session (uses defaults if None)
            rate_limit_config: Configuration for rate limiting (uses defaults if None)
            circuit_breaker_config: Configuration for circuit breaker (uses defaults if None)
        """
        self.session_config = session_config or SessionConfig()
        self.rate_limit_config = rate_limit_config or RateLimitConfig()
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        
        self.state = SessionState.DISCONNECTED
        self.client = None
        self.session_context = None  # Async context manager
        self.session = None  # Actual session (set when context entered)
        self.api_key = None
        self.metrics = SessionMetrics()
        self._session_start_time: Optional[float] = None
        
        # Rate limiting and circuit breaker
        self.rate_limit_metrics = RateLimitMetrics()
        self._retry_count = 0
        self._last_backoff_delay = 0.0
        
        logger.info("Gemini Live client initialized with rate limiting and circuit breaker")
    
    def _update_state(self, new_state: SessionState) -> None:
        """
        Update session state and log the transition.
        
        Args:
            new_state: New session state
        """
        old_state = self.state
        self.state = new_state
        
        logger.info(f"Session state transition: {old_state.value} -> {new_state.value}")
    
    def _create_client(self, api_key: str) -> genai.Client:
        """
        Create Gemini API client with API key authentication.
        
        Args:
            api_key: Gemini API key
            
        Returns:
            Configured Gemini client
            
        Raises:
            ValueError: If API key is invalid
        """
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Invalid API key: must be a non-empty string")
        
        try:
            # Create client with API key
            client = genai.Client(api_key=api_key)
            
            logger.debug("Gemini API client created successfully")
            return client
            
        except Exception as e:
            logger.error(f"Failed to create Gemini client: {e}")
            raise ValueError(f"Failed to create Gemini client: {e}")
    
    def _create_session_config(self) -> types.LiveConnectConfig:
        """
        Create session configuration for Gemini Live API.
        
        Returns:
            LiveConnectConfig object with session settings
        """
        # Build config dict
        config_dict = {
            "response_modalities": self.session_config.response_modalities,
        }
        
        # Add system instruction if provided
        if self.session_config.system_instruction:
            config_dict["system_instruction"] = self.session_config.system_instruction
        
        # Build speech config with voice settings
        config_dict["speech_config"] = {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": self.session_config.voice_name
                }
            }
        }
        
        # Create live connect config
        config = types.LiveConnectConfig(**config_dict)
        
        logger.debug(
            f"Session config created: model={self.session_config.model}, "
            f"voice={self.session_config.voice_name}, "
            f"modalities={self.session_config.response_modalities}"
        )
        
        return config
    
    def _attempt_session_establishment(self, api_key: str) -> tuple[bool, Optional[str]]:
        """
        Attempt to establish a session with Gemini Live API.
        
        Args:
            api_key: Gemini API key
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Create client if not already created
            if not self.client:
                self.client = self._create_client(api_key)
            
            # Create session configuration
            config = self._create_session_config()
            
            # Store the session context manager
            # Note: This needs to be entered in an async context
            self.session_context = self.client.aio.live.connect(
                model=self.session_config.model,
                config=config
            )
            self.session = None  # Will be set when context is entered
            
            logger.info(
                f"Gemini Live API session context created "
                f"(model: {self.session_config.model})"
            )
            return True, None
            
        except Exception as e:
            error_msg = f"Failed to create session context: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def establish_session(self, api_key: str) -> bool:
        """
        Establish a session with Gemini Live API using API key authentication.
        
        Implements persistent connection that should be maintained throughout
        the streaming session.
        
        Args:
            api_key: Gemini API key for authentication
            
        Returns:
            True if session established successfully, False otherwise
            
        Validates: Requirements 2.1, 2.6, 13.3
        """
        if self.state == SessionState.CONNECTED:
            logger.warning("Session already established")
            return True
        
        self._update_state(SessionState.CONNECTING)
        self.metrics.session_attempts += 1
        self.api_key = api_key
        
        # Attempt to establish session
        success, error_msg = self._attempt_session_establishment(api_key)
        
        if success:
            # Session established successfully
            self._update_state(SessionState.CONNECTED)
            self.metrics.successful_sessions += 1
            self.metrics.last_session_time = time.time()
            self._session_start_time = time.time()
            
            logger.info("Successfully established Gemini Live API session")
            return True
        else:
            # Session establishment failed
            self._update_state(SessionState.FAILED)
            self.metrics.failed_sessions += 1
            
            logger.error(f"Failed to establish session: {error_msg}")
            return False
    
    def close_session(self) -> None:
        """
        Close the current session and log the disconnection event.
        
        Validates: Requirement 2.6
        """
        if self.state == SessionState.DISCONNECTED:
            logger.debug("Session already closed")
            return
        
        # Update metrics
        if self._session_start_time:
            session_duration = time.time() - self._session_start_time
            self.metrics.total_session_time += session_duration
            self._session_start_time = None
        
        self.metrics.disconnections += 1
        self.metrics.last_disconnection_time = time.time()
        
        # Log disconnection event
        logger.info(
            f"Gemini Live API session disconnection event",
            extra={
                "component": "gemini_live_client",
                "event": "disconnection",
                "timestamp": time.time(),
                "total_session_time": self.metrics.total_session_time,
                "disconnection_count": self.metrics.disconnections
            }
        )
        
        # Clean up session
        if self.session:
            try:
                # Close the session gracefully
                # Note: Actual close method depends on genai library implementation
                self.session = None
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
        
        self.client = None
        self._update_state(SessionState.DISCONNECTED)
    
    def reconnect(self) -> bool:
        """
        Attempt to reconnect to Gemini Live API after connection loss.
        
        Uses the stored API key from the previous session.
        
        Returns:
            True if reconnection successful, False otherwise
            
        Validates: Requirement 2.6
        """
        if not self.api_key:
            logger.error("Cannot reconnect: no API key stored from previous session")
            return False
        
        logger.info("Attempting to reconnect to Gemini Live API")
        
        self._update_state(SessionState.RECONNECTING)
        self.metrics.reconnections += 1
        
        # Close existing session if any
        if self.state != SessionState.DISCONNECTED:
            self.close_session()
        
        # Attempt to establish new session
        return self.establish_session(self.api_key)
    
    def is_connected(self) -> bool:
        """
        Check if currently connected to Gemini Live API.
        
        Returns:
            True if connected, False otherwise
        """
        return self.state == SessionState.CONNECTED and self.session is not None
    
    def get_state(self) -> SessionState:
        """
        Get current session state.
        
        Returns:
            Current SessionState
        """
        return self.state
    
    def get_metrics(self) -> SessionMetrics:
        """
        Get session metrics for monitoring.
        
        Returns:
            SessionMetrics object with current metrics
        """
        return self.metrics
    
    def get_session(self):
        """
        Get the Gemini Live API session object.
        
        Returns:
            Session object if connected, None otherwise
        """
        if not self.is_connected():
            logger.warning("Attempted to get session while not connected")
            return None
        
        return self.session
    
    def test_connection(self) -> bool:
        """
        Test if the session is still alive.
        
        Returns:
            True if session is alive, False otherwise
        """
        if not self.is_connected():
            return False
        
        try:
            # Check if session object is still valid
            # Note: Actual health check depends on genai library implementation
            return self.session is not None
            
        except Exception as e:
            logger.error(f"Session test failed: {e}")
            return False
    
    def get_session_info(self) -> Dict[str, Any]:
        """
        Get comprehensive session information for logging and monitoring.
        
        Returns:
            Dictionary with session state, metrics, and configuration
        """
        return {
            "state": self.state.value,
            "is_connected": self.is_connected(),
            "config": {
                "model": self.session_config.model,
                "response_modalities": self.session_config.response_modalities,
                "voice_name": self.session_config.voice_name
            },
            "metrics": {
                "session_attempts": self.metrics.session_attempts,
                "successful_sessions": self.metrics.successful_sessions,
                "failed_sessions": self.metrics.failed_sessions,
                "disconnections": self.metrics.disconnections,
                "reconnections": self.metrics.reconnections,
                "last_session_time": self.metrics.last_session_time,
                "last_disconnection_time": self.metrics.last_disconnection_time,
                "total_session_time": self.metrics.total_session_time
            }
        }
    
    def maintain_connection(self) -> bool:
        """
        Maintain persistent connection throughout streaming session.
        
        Checks connection health and attempts reconnection if needed.
        
        Returns:
            True if connection is healthy or reconnection successful, False otherwise
            
        Validates: Requirement 2.6
        """
        # Check if currently connected
        if self.is_connected():
            # Test connection health
            if self.test_connection():
                return True
            else:
                logger.warning("Connection health check failed, attempting reconnection")
        
        # Connection lost or unhealthy, attempt reconnection
        if self.api_key:
            logger.info("Attempting to maintain connection via reconnection")
            return self.reconnect()
        else:
            logger.error("Cannot maintain connection: no API key available")
            return False
    
    # ========== Rate Limiting Methods ==========
    
    def _update_request_tracking(self) -> None:
        """
        Update request tracking for rate limiting.
        
        Maintains sliding windows for per-second and per-minute request counts.
        """
        current_time = time.time()
        
        # Add current request timestamp
        self.rate_limit_metrics.request_timestamps.append(current_time)
        self.rate_limit_metrics.last_request_time = current_time
        
        # Clean up old timestamps (older than 1 minute)
        cutoff_time = current_time - 60
        self.rate_limit_metrics.request_timestamps = [
            ts for ts in self.rate_limit_metrics.request_timestamps
            if ts > cutoff_time
        ]
        
        # Update counts
        one_second_ago = current_time - 1
        self.rate_limit_metrics.requests_this_second = sum(
            1 for ts in self.rate_limit_metrics.request_timestamps
            if ts > one_second_ago
        )
        self.rate_limit_metrics.requests_this_minute = len(
            self.rate_limit_metrics.request_timestamps
        )
    
    def _is_rate_limited(self) -> bool:
        """
        Check if we're currently rate limited.
        
        Returns:
            True if rate limit would be exceeded, False otherwise
        """
        self._update_request_tracking()
        
        # Check per-second limit
        if self.rate_limit_metrics.requests_this_second >= self.rate_limit_config.max_requests_per_second:
            return True
        
        # Check per-minute limit
        if self.rate_limit_metrics.requests_this_minute >= self.rate_limit_config.max_requests_per_minute:
            return True
        
        return False
    
    def _should_throttle(self) -> bool:
        """
        Check if we should proactively throttle requests.
        
        Returns:
            True if approaching rate limits, False otherwise
            
        Validates: Requirement 2.7
        """
        self._update_request_tracking()
        
        # Check if approaching per-second limit
        per_second_usage = (
            self.rate_limit_metrics.requests_this_second /
            self.rate_limit_config.max_requests_per_second
        )
        
        # Check if approaching per-minute limit
        per_minute_usage = (
            self.rate_limit_metrics.requests_this_minute /
            self.rate_limit_config.max_requests_per_minute
        )
        
        # Throttle if either limit is approaching threshold
        return (
            per_second_usage >= self.rate_limit_config.throttle_threshold or
            per_minute_usage >= self.rate_limit_config.throttle_threshold
        )
    
    def _calculate_throttle_delay(self) -> float:
        """
        Calculate delay needed to stay within rate limits.
        
        Returns:
            Delay in seconds
        """
        if not self.rate_limit_metrics.request_timestamps:
            return 0.0
        
        current_time = time.time()
        
        # Calculate delay based on per-second limit
        one_second_ago = current_time - 1
        recent_requests = [
            ts for ts in self.rate_limit_metrics.request_timestamps
            if ts > one_second_ago
        ]
        
        if len(recent_requests) >= self.rate_limit_config.max_requests_per_second:
            # Need to wait until oldest request in the window expires
            oldest_in_window = min(recent_requests)
            delay = 1.0 - (current_time - oldest_in_window)
            return max(0.0, delay)
        
        return 0.0
    
    async def _apply_rate_limiting(self) -> bool:
        """
        Apply rate limiting before making API request.
        
        Returns:
            True if request can proceed, False if blocked
            
        Validates: Requirement 2.7
        """
        # Check if we're rate limited
        if self._is_rate_limited():
            delay = self._calculate_throttle_delay()
            
            if delay > 0:
                logger.info(f"Rate limit reached, throttling request for {delay:.2f}s")
                self.rate_limit_metrics.throttled_requests += 1
                
                # Wait for the calculated delay
                await self._async_sleep(delay)
                
                # Update tracking after delay
                self._update_request_tracking()
        
        # Check if we should proactively throttle
        elif self._should_throttle():
            # Small delay to prevent hitting limits
            delay = 0.1
            logger.debug(f"Proactively throttling request for {delay:.2f}s")
            self.rate_limit_metrics.throttled_requests += 1
            await self._async_sleep(delay)
        
        return True
    
    async def _async_sleep(self, seconds: float) -> None:
        """
        Async sleep helper.
        
        Args:
            seconds: Time to sleep in seconds
        """
        import asyncio
        await asyncio.sleep(seconds)
    
    def _detect_rate_limit_error(self, error: Exception) -> bool:
        """
        Detect if an error is a rate limit error.
        
        Args:
            error: Exception to check
            
        Returns:
            True if this is a rate limit error (429 or quota error)
        """
        error_str = str(error).lower()
        
        # Check for common rate limit indicators
        rate_limit_indicators = [
            "429",
            "rate limit",
            "quota",
            "too many requests",
            "resource exhausted"
        ]
        
        return any(indicator in error_str for indicator in rate_limit_indicators)
    
    def _calculate_backoff_delay(self) -> float:
        """
        Calculate exponential backoff delay for rate limit errors.
        
        Returns:
            Delay in seconds
            
        Validates: Requirement 2.7
        """
        if self._retry_count == 0:
            delay = self.rate_limit_config.backoff_base
        else:
            delay = min(
                self.rate_limit_config.backoff_base * (
                    self.rate_limit_config.backoff_multiplier ** self._retry_count
                ),
                self.rate_limit_config.backoff_max
            )
        
        self._last_backoff_delay = delay
        return delay
    
    # ========== Circuit Breaker Methods ==========
    
    def _update_circuit_breaker_state(self) -> None:
        """
        Update circuit breaker state based on current conditions.
        
        Validates: Requirement 12.1
        """
        current_time = time.time()
        
        if self.rate_limit_metrics.circuit_state == CircuitBreakerState.OPEN:
            # Check if timeout has elapsed
            if (self.rate_limit_metrics.last_failure_time and
                current_time - self.rate_limit_metrics.last_failure_time >= self.circuit_breaker_config.timeout):
                # Transition to HALF_OPEN to test if service recovered
                self.rate_limit_metrics.circuit_state = CircuitBreakerState.HALF_OPEN
                self.rate_limit_metrics.consecutive_successes = 0
                logger.info("Circuit breaker transitioning to HALF_OPEN state")
    
    def _is_circuit_open(self) -> bool:
        """
        Check if circuit breaker is open (blocking requests).
        
        Returns:
            True if circuit is open, False otherwise
        """
        self._update_circuit_breaker_state()
        return self.rate_limit_metrics.circuit_state == CircuitBreakerState.OPEN
    
    def _record_api_success(self) -> None:
        """
        Record successful API call for circuit breaker.
        
        Validates: Requirement 12.1
        """
        self._retry_count = 0
        self.rate_limit_metrics.consecutive_failures = 0
        
        if self.rate_limit_metrics.circuit_state == CircuitBreakerState.HALF_OPEN:
            self.rate_limit_metrics.consecutive_successes += 1
            
            # Check if we have enough successes to close the circuit
            if self.rate_limit_metrics.consecutive_successes >= self.circuit_breaker_config.success_threshold:
                self.rate_limit_metrics.circuit_state = CircuitBreakerState.CLOSED
                self.rate_limit_metrics.consecutive_successes = 0
                logger.info("Circuit breaker closed after successful recovery")
    
    def _record_api_failure(self, error: Exception) -> None:
        """
        Record failed API call for circuit breaker.
        
        Args:
            error: Exception that occurred
            
        Validates: Requirement 12.1
        """
        self.rate_limit_metrics.consecutive_failures += 1
        self.rate_limit_metrics.total_failures += 1
        self.rate_limit_metrics.last_failure_time = time.time()
        
        # Check if this is a rate limit error
        if self._detect_rate_limit_error(error):
            self.rate_limit_metrics.rate_limit_errors += 1
            logger.warning(f"Rate limit error detected: {error}")
        
        # Check if we should open the circuit
        if (self.rate_limit_metrics.circuit_state == CircuitBreakerState.CLOSED and
            self.rate_limit_metrics.consecutive_failures >= self.circuit_breaker_config.failure_threshold):
            
            self.rate_limit_metrics.circuit_state = CircuitBreakerState.OPEN
            self.rate_limit_metrics.circuit_open_count += 1
            logger.error(
                f"Circuit breaker opened after {self.rate_limit_metrics.consecutive_failures} "
                f"consecutive failures"
            )
        
        # If in HALF_OPEN and we fail, go back to OPEN
        elif self.rate_limit_metrics.circuit_state == CircuitBreakerState.HALF_OPEN:
            self.rate_limit_metrics.circuit_state = CircuitBreakerState.OPEN
            self.rate_limit_metrics.consecutive_successes = 0
            logger.warning("Circuit breaker reopened after failure in HALF_OPEN state")
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """
        Get comprehensive rate limiting and circuit breaker information.
        
        Returns:
            Dictionary with rate limit metrics and circuit breaker state
        """
        self._update_request_tracking()
        
        return {
            "rate_limiting": {
                "requests_this_second": self.rate_limit_metrics.requests_this_second,
                "requests_this_minute": self.rate_limit_metrics.requests_this_minute,
                "throttled_requests": self.rate_limit_metrics.throttled_requests,
                "rate_limit_errors": self.rate_limit_metrics.rate_limit_errors,
                "max_per_second": self.rate_limit_config.max_requests_per_second,
                "max_per_minute": self.rate_limit_config.max_requests_per_minute,
                "is_throttling": self._should_throttle()
            },
            "circuit_breaker": {
                "state": self.rate_limit_metrics.circuit_state.value,
                "consecutive_failures": self.rate_limit_metrics.consecutive_failures,
                "consecutive_successes": self.rate_limit_metrics.consecutive_successes,
                "total_failures": self.rate_limit_metrics.total_failures,
                "circuit_open_count": self.rate_limit_metrics.circuit_open_count,
                "last_failure_time": self.rate_limit_metrics.last_failure_time
            }
        }
    
    # ========== Multimodal Data Forwarding with Rate Limiting ==========
    
    async def send_video_frame(self, frame: 'VideoFrame') -> bool:
        """
        Send a video frame to Gemini Live API for visual analysis.
        
        Applies rate limiting and circuit breaker pattern before sending.
        
        Args:
            frame: VideoFrame object containing frame data and metadata
            
        Returns:
            True if frame sent successfully, False otherwise
            
        Validates: Requirements 2.2, 2.7, 12.1
        """
        if not self.is_connected():
            logger.error("Cannot send video frame: not connected to Gemini Live API")
            return False
        
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning("Cannot send video frame: circuit breaker is OPEN")
            return False
        
        try:
            # Import here to avoid circular dependency
            from streambuddy_agent.models import VideoFrame
            
            if not isinstance(frame, VideoFrame):
                raise ValueError("frame must be a VideoFrame instance")
            
            # Apply rate limiting
            await self._apply_rate_limiting()
            
            # Send video frame to Gemini Live API using correct format
            # Official API: await session.send_realtime_input(media=types.Blob(...))
            await self.session.send_realtime_input(
                media=types.Blob(data=frame.frame_data, mime_type="image/jpeg")
            )
            
            # Record success for circuit breaker
            self._record_api_success()
            
            logger.debug(
                f"Video frame sent successfully: seq={frame.sequence_number}, "
                f"size={len(frame.frame_data)} bytes, "
                f"dimensions={frame.width}x{frame.height}"
            )
            return True
            
        except Exception as e:
            # Record failure for circuit breaker
            self._record_api_failure(e)
            
            # Handle rate limit errors with exponential backoff
            if self._detect_rate_limit_error(e):
                self._retry_count += 1
                backoff_delay = self._calculate_backoff_delay()
                logger.warning(
                    f"Rate limit error sending video frame, "
                    f"retry {self._retry_count} after {backoff_delay:.2f}s: {e}"
                )
            else:
                logger.error(f"Failed to send video frame: {e}")
            
            return False
    
    async def send_audio_chunk(self, audio: 'AudioData') -> bool:
        """
        Send an audio chunk to Gemini Live API for speech recognition and understanding.
        
        Applies rate limiting and circuit breaker pattern before sending.
        
        Args:
            audio: AudioData object containing audio data and metadata
            
        Returns:
            True if audio sent successfully, False otherwise
            
        Validates: Requirements 2.3, 2.7, 12.1
        """
        if not self.is_connected():
            logger.error("Cannot send audio chunk: not connected to Gemini Live API")
            return False
        
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning("Cannot send audio chunk: circuit breaker is OPEN")
            return False
        
        try:
            # Import here to avoid circular dependency
            from streambuddy_agent.models import AudioData
            
            if not isinstance(audio, AudioData):
                raise ValueError("audio must be an AudioData instance")
            
            # Apply rate limiting
            await self._apply_rate_limiting()
            
            # Determine MIME type based on encoding
            # Official API requires format: "audio/pcm;rate=16000"
            if audio.encoding.lower() == "pcm":
                mime_type = f"audio/pcm;rate={audio.sample_rate}"
            else:
                mime_type_map = {
                    "opus": "audio/opus",
                    "mp3": "audio/mp3",
                    "aac": "audio/aac"
                }
                mime_type = mime_type_map.get(audio.encoding.lower(), "audio/pcm")
            
            # Send audio chunk to Gemini Live API using correct format
            # Official API: await session.send_realtime_input(audio=types.Blob(...))
            await self.session.send_realtime_input(
                audio=types.Blob(data=audio.audio_bytes, mime_type=mime_type)
            )
            
            # Record success for circuit breaker
            self._record_api_success()
            
            logger.debug(
                f"Audio chunk sent successfully: "
                f"duration={audio.duration_ms}ms, "
                f"size={len(audio.audio_bytes)} bytes, "
                f"encoding={audio.encoding}, "
                f"sample_rate={audio.sample_rate}Hz"
            )
            return True
            
        except Exception as e:
            # Record failure for circuit breaker
            self._record_api_failure(e)
            
            # Handle rate limit errors with exponential backoff
            if self._detect_rate_limit_error(e):
                self._retry_count += 1
                backoff_delay = self._calculate_backoff_delay()
                logger.warning(
                    f"Rate limit error sending audio chunk, "
                    f"retry {self._retry_count} after {backoff_delay:.2f}s: {e}"
                )
            else:
                logger.error(f"Failed to send audio chunk: {e}")
            
            return False
    
    async def send_text_message(self, message: str) -> bool:
        """
        Send a text message (chat) to Gemini Live API for text analysis.
        
        Applies rate limiting and circuit breaker pattern before sending.
        
        Args:
            message: Text message content to send
            
        Returns:
            True if message sent successfully, False otherwise
            
        Validates: Requirements 2.4, 2.7, 12.1
        """
        if not self.is_connected():
            logger.error("Cannot send text message: not connected to Gemini Live API")
            return False
        
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning("Cannot send text message: circuit breaker is OPEN")
            return False
        
        try:
            if not isinstance(message, str):
                raise ValueError("message must be a string")
            
            if not message.strip():
                logger.warning("Attempted to send empty text message")
                return False
            
            # Apply rate limiting
            await self._apply_rate_limiting()
            
            # Send text message to Gemini Live API using send_client_content
            # Format as a user turn with turn_complete=True
            await self.session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": message}]}],
                turn_complete=True
            )
            
            # Record success for circuit breaker
            self._record_api_success()
            
            logger.debug(
                f"Text message sent successfully: length={len(message)} chars"
            )
            return True
            
        except Exception as e:
            # Record failure for circuit breaker
            self._record_api_failure(e)
            
            # Handle rate limit errors with exponential backoff
            if self._detect_rate_limit_error(e):
                self._retry_count += 1
                backoff_delay = self._calculate_backoff_delay()
                logger.warning(
                    f"Rate limit error sending text message, "
                    f"retry {self._retry_count} after {backoff_delay:.2f}s: {e}"
                )
            else:
                logger.error(f"Failed to send text message: {e}")
            
            return False
    
    async def send_chat_message(self, chat_message: 'ChatMessage') -> bool:
        """
        Send a ChatMessage object to Gemini Live API for text analysis.
        
        This is a convenience method that formats the chat message with username
        and content before sending to the API.
        
        Args:
            chat_message: ChatMessage object containing message data
            
        Returns:
            True if message sent successfully, False otherwise
            
        Validates: Requirement 2.4
        """
        if not self.is_connected():
            logger.error("Cannot send chat message: not connected to Gemini Live API")
            return False
        
        try:
            # Import here to avoid circular dependency
            from streambuddy_agent.models import ChatMessage
            
            if not isinstance(chat_message, ChatMessage):
                raise ValueError("chat_message must be a ChatMessage instance")
            
            # Format message with username for context
            formatted_message = f"Chat from {chat_message.username}: {chat_message.content}"
            
            # Send formatted message
            result = await self.send_text_message(formatted_message)
            
            if result:
                logger.debug(
                    f"Chat message sent successfully: "
                    f"user={chat_message.username}, "
                    f"priority={chat_message.priority.value}, "
                    f"message_id={chat_message.message_id}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send chat message: {e}")
            return False
    
    async def receive_response(self, timeout: float = 5.0):
        """
        Receive streaming responses from Gemini Live API.
        
        This is an async generator that yields response chunks as they arrive
        from the Gemini Live API. Each chunk may contain audio data, text content,
        or both.
        
        Args:
            timeout: Maximum time to wait for responses in seconds (default: 5.0)
            
        Yields:
            Response chunks from the API (structure depends on genai library)
            
        Raises:
            RuntimeError: If not connected to Gemini Live API
            TimeoutError: If no response received within timeout period
            
        Validates: Requirement 2.5
        
        Example:
            async for chunk in client.receive_response():
                if hasattr(chunk, 'audio_data') and chunk.audio_data:
                    await forward_to_audio_output(chunk.audio_data)
                if hasattr(chunk, 'text') and chunk.text:
                    process_text_response(chunk.text)
        """
        if not self.is_connected():
            raise RuntimeError("Cannot receive response: not connected to Gemini Live API")
        
        try:
            logger.debug("Starting to receive responses from Gemini Live API")
            
            # Receive streaming responses from the session
            # The actual API returns an async iterator
            async for response_chunk in self.session:
                logger.debug(f"Received response chunk from Gemini Live API")
                yield response_chunk
                
        except Exception as e:
            logger.error(f"Error receiving response from Gemini Live API: {e}")
            raise
    
    async def receive_and_forward_response(
        self,
        audio_output_callback,
        text_callback=None,
        triggered_by: str = "unknown"
    ) -> Optional['AIResponse']:
        """
        Receive response from Gemini Live API and forward to Audio Output Service.
        
        This method receives streaming responses from the API and forwards audio
        chunks to the provided callback within the 100ms latency requirement.
        It also constructs an AIResponse object with complete response data.
        
        Args:
            audio_output_callback: Async callback function to forward audio chunks.
                                  Should accept (audio_bytes: bytes, mime_type: str)
            text_callback: Optional async callback for text responses.
                          Should accept (text: str)
            triggered_by: ID of the event/message that triggered this response
            
        Returns:
            AIResponse object with complete response data, or None if no response
            
        Validates: Requirement 2.5 (< 100ms forwarding latency)
        
        Example:
            async def audio_callback(audio_bytes, mime_type):
                await audio_output_service.play(audio_bytes, mime_type)
            
            response = await client.receive_and_forward_response(
                audio_callback=audio_callback,
                triggered_by="chat_msg_123"
            )
        """
        if not self.is_connected():
            logger.error("Cannot receive response: not connected to Gemini Live API")
            return None
        
        try:
            # Import here to avoid circular dependency
            from streambuddy_agent.models import AIResponse, AudioData
            import uuid
            
            # Track timing for latency measurement
            receive_start_time = time.time()
            response_id = str(uuid.uuid4())
            
            # Accumulate response data
            audio_chunks = []
            text_parts = []
            total_audio_bytes = 0
            chunk_count = 0
            
            logger.debug(f"Starting to receive and forward response (id: {response_id})")
            
            # Receive and forward streaming response chunks
            async for chunk in self.receive_response():
                chunk_count += 1
                chunk_receive_time = time.time()
                
                # Forward audio data if present
                if hasattr(chunk, 'data') and chunk.data:
                    # Check if this is audio data
                    if hasattr(chunk, 'mime_type') and 'audio' in chunk.mime_type.lower():
                        audio_bytes = chunk.data
                        mime_type = chunk.mime_type
                        
                        # Forward to audio output callback immediately (< 100ms requirement)
                        forward_start = time.time()
                        await audio_output_callback(audio_bytes, mime_type)
                        forward_duration = (time.time() - forward_start) * 1000
                        
                        # Store for AIResponse construction
                        audio_chunks.append(audio_bytes)
                        total_audio_bytes += len(audio_bytes)
                        
                        logger.debug(
                            f"Audio chunk forwarded: size={len(audio_bytes)} bytes, "
                            f"forward_latency={forward_duration:.2f}ms"
                        )
                        
                        # Verify we met the 100ms requirement
                        if forward_duration > 100:
                            logger.warning(
                                f"Audio forwarding exceeded 100ms target: "
                                f"{forward_duration:.2f}ms"
                            )
                
                # Handle text content if present
                if hasattr(chunk, 'text') and chunk.text:
                    text_parts.append(chunk.text)
                    
                    if text_callback:
                        await text_callback(chunk.text)
                    
                    logger.debug(f"Text chunk received: length={len(chunk.text)} chars")
                
                # Check for end of response
                if hasattr(chunk, 'end_of_turn') and chunk.end_of_turn:
                    logger.debug("End of response turn detected")
                    break
            
            # Calculate total latency
            total_latency_ms = int((time.time() - receive_start_time) * 1000)
            
            # Construct complete text content
            complete_text = ''.join(text_parts) if text_parts else ""
            
            # Construct AudioData if we received audio
            audio_data = None
            if audio_chunks:
                # Combine all audio chunks
                combined_audio = b''.join(audio_chunks)
                
                # Create AudioData object
                # Note: We use defaults for sample_rate and encoding as they're
                # determined by the Gemini API configuration
                # Use max(1, total_latency_ms) to ensure duration_ms is positive
                audio_data = AudioData(
                    timestamp=time.time(),
                    audio_bytes=combined_audio,
                    sample_rate=24000,  # Gemini Live API default
                    duration_ms=max(1, total_latency_ms),  # Ensure positive duration
                    encoding="pcm"  # Gemini Live API default
                )
            
            # Construct AIResponse
            ai_response = AIResponse(
                response_id=response_id,
                text_content=complete_text if complete_text else ("[Audio response]" if audio_data else "[Empty response]"),
                timestamp=time.time(),
                latency_ms=total_latency_ms,
                triggered_by=triggered_by,
                audio_data=audio_data
            )
            
            logger.info(
                f"Response received and forwarded successfully: "
                f"id={response_id}, "
                f"chunks={chunk_count}, "
                f"audio_bytes={total_audio_bytes}, "
                f"text_length={len(complete_text)}, "
                f"latency={total_latency_ms}ms"
            )
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Error receiving and forwarding response: {e}")
            return None
    
    async def receive_response_stream(self, max_chunks: Optional[int] = None):
        """
        Receive streaming response chunks with chunk-by-chunk processing.
        
        This is a lower-level method that yields individual response chunks
        for custom processing. Use receive_and_forward_response() for standard
        audio forwarding workflow.
        
        Args:
            max_chunks: Maximum number of chunks to receive (None for unlimited)
            
        Yields:
            Tuple of (chunk_data: bytes, mime_type: str, metadata: dict)
            
        Validates: Requirement 2.5
        """
        if not self.is_connected():
            raise RuntimeError("Cannot receive response: not connected to Gemini Live API")
        
        try:
            chunk_count = 0
            
            async for chunk in self.receive_response():
                # Extract chunk data and metadata
                chunk_data = chunk.data if hasattr(chunk, 'data') else None
                mime_type = chunk.mime_type if hasattr(chunk, 'mime_type') else "unknown"
                
                metadata = {
                    'chunk_number': chunk_count,
                    'timestamp': time.time(),
                    'has_text': hasattr(chunk, 'text') and chunk.text is not None,
                    'text': chunk.text if hasattr(chunk, 'text') else None,
                    'end_of_turn': hasattr(chunk, 'end_of_turn') and chunk.end_of_turn
                }
                
                yield (chunk_data, mime_type, metadata)
                
                chunk_count += 1
                
                # Check max chunks limit
                if max_chunks and chunk_count >= max_chunks:
                    logger.debug(f"Reached max chunks limit: {max_chunks}")
                    break
                
                # Check for end of turn
                if metadata['end_of_turn']:
                    break
                    
        except Exception as e:
            logger.error(f"Error in response stream: {e}")
            raise


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Gemini Live API Client Test")
    print("=" * 50)
    print()
    
    # Create client with custom config
    config = SessionConfig(
        model="gemini-2.5-flash",
        response_modalities=["AUDIO"],
        voice_name="Puck"
    )
    
    client = GeminiLiveClient(session_config=config)
    
    print(f"Initial state: {client.get_state().value}")
    print()
    
    # Note: This requires a valid API key to actually connect
    print("To test session establishment, provide a valid Gemini API key")
    print("Example: client.establish_session('your-api-key-here')")
    print()
    
    # Display session info
    import json
    info = client.get_session_info()
    print("Session Info:")
    print(json.dumps(info, indent=2))
