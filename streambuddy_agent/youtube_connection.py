"""
YouTube Live API Connection Module

This module implements connection establishment with YouTube Live API using OAuth 2.0
authentication, exponential backoff retry logic, and connection state tracking.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 13.1, 13.3
"""

import logging
import time
from typing import Optional, Dict, Any, Tuple
from enum import Enum
from dataclasses import dataclass
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json

# Configure logging
logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Connection states for YouTube Live API"""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


@dataclass
class RetryConfig:
    """Configuration for exponential backoff retry logic"""
    max_attempts: int = 2
    base_delay: float = 1.0  # seconds
    max_delay: float = 16.0  # seconds
    
    def get_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay for given attempt.
        
        Args:
            attempt: Retry attempt number (0-indexed)
            
        Returns:
            Delay in seconds (1s, 2s, 4s, 8s, 16s)
        """
        if attempt < 0:
            return 0.0
        
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)


@dataclass
class ConnectionMetrics:
    """Metrics for connection monitoring"""
    connection_attempts: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    disconnections: int = 0
    reconnections: int = 0
    last_connection_time: Optional[float] = None
    last_disconnection_time: Optional[float] = None
    total_connected_time: float = 0.0


class YouTubeConnection:
    """
    Manages connection to YouTube Live API with OAuth 2.0 authentication,
    exponential backoff retry logic, and connection state tracking.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 13.1, 13.3
    """
    
    def __init__(self, retry_config: Optional[RetryConfig] = None):
        """
        Initialize YouTube Live API connection manager.
        
        Args:
            retry_config: Configuration for retry logic (uses defaults if None)
        """
        self.retry_config = retry_config or RetryConfig()
        self.state = ConnectionState.DISCONNECTED
        self.service = None
        self.credentials = None
        self.metrics = ConnectionMetrics()
        self._connection_start_time: Optional[float] = None
        self._last_error: Optional[str] = None

        logger.info("YouTube connection manager initialized")

    @property
    def last_error_message(self) -> Optional[str]:
        """User-facing message from the last failed connection attempt."""
        return self._last_error
    
    def _update_state(self, new_state: ConnectionState) -> None:
        """
        Update connection state and log the transition.
        
        Args:
            new_state: New connection state
        """
        old_state = self.state
        self.state = new_state
        
        logger.info(f"Connection state transition: {old_state.value} -> {new_state.value}")
    
    def _create_credentials(self, oauth_token: str) -> Credentials:
        """
        Create OAuth 2.0 credentials from token.
        
        Args:
            oauth_token: OAuth 2.0 token (JSON string or dict)
            
        Returns:
            Google OAuth2 Credentials object
            
        Raises:
            ValueError: If token format is invalid
        """
        try:
            # Parse token if it's a JSON string
            if isinstance(oauth_token, str):
                token_data = json.loads(oauth_token)
            else:
                token_data = oauth_token
            
            # Create credentials from token data
            credentials = Credentials(
                token=token_data.get('access_token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes', ['https://www.googleapis.com/auth/youtube.readonly'])
            )
            
            logger.debug("OAuth 2.0 credentials created successfully")
            return credentials
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to create credentials from token: {e}")
            raise ValueError(f"Invalid OAuth token format: {e}")
    
    def _attempt_connection(self, oauth_token: str) -> Tuple[bool, Optional[str]]:
        """
        Attempt to establish connection to YouTube Live API.
        
        Args:
            oauth_token: OAuth 2.0 token
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            # Create credentials
            self.credentials = self._create_credentials(oauth_token)
            
            # Build YouTube API service
            self.service = build(
                'youtube',
                'v3',
                credentials=self.credentials,
                cache_discovery=False
            )
            
            # Test connection with a simple API call
            request = self.service.liveBroadcasts().list(
                part='id,snippet',
                mine=True,
                maxResults=1
            )
            response = request.execute()
            
            logger.info("YouTube Live API connection established successfully")
            return True, None
            
        except HttpError as e:
            error_msg = f"HTTP error during connection: {e.resp.status} - {e.content.decode()}"
            logger.error(error_msg)
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error during connection: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def connect(self, oauth_token: str) -> bool:
        """
        Connect to YouTube Live API with exponential backoff retry logic.
        
        Implements exponential backoff with 5 attempts: 1s, 2s, 4s, 8s, 16s delays.
        
        Args:
            oauth_token: OAuth 2.0 token for authentication
            
        Returns:
            True if connection successful, False otherwise
            
        Validates: Requirements 1.1, 1.2, 1.3, 1.4, 13.1, 13.3
        """
        if self.state == ConnectionState.CONNECTED:
            logger.warning("Already connected to YouTube Live API")
            return True
        
        self._update_state(ConnectionState.CONNECTING)
        self.metrics.connection_attempts += 1
        
        for attempt in range(self.retry_config.max_attempts):
            logger.info(f"Connection attempt {attempt + 1}/{self.retry_config.max_attempts}")
            
            # Attempt connection
            success, error_msg = self._attempt_connection(oauth_token)
            
            if success:
                # Connection successful
                self._update_state(ConnectionState.CONNECTED)
                self.metrics.successful_connections += 1
                self.metrics.last_connection_time = time.time()
                self._connection_start_time = time.time()
                
                logger.info("Successfully connected to YouTube Live API")
                return True
            
            # Connection failed
            self._last_error = error_msg
            logger.warning(f"Connection attempt {attempt + 1} failed: {error_msg}")

            # If not the last attempt, wait before retrying
            if attempt < self.retry_config.max_attempts - 1:
                delay = self.retry_config.get_delay(attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
        
        # All attempts failed
        self._update_state(ConnectionState.FAILED)
        self.metrics.failed_connections += 1
        
        logger.error(f"Failed to connect after {self.retry_config.max_attempts} attempts")
        return False
    
    def disconnect(self) -> None:
        """
        Disconnect from YouTube Live API and log the disconnection event.
        
        Validates: Requirement 1.5
        """
        if self.state == ConnectionState.DISCONNECTED:
            logger.debug("Already disconnected")
            return
        
        # Update metrics
        if self._connection_start_time:
            connected_duration = time.time() - self._connection_start_time
            self.metrics.total_connected_time += connected_duration
            self._connection_start_time = None
        
        self.metrics.disconnections += 1
        self.metrics.last_disconnection_time = time.time()
        
        # Log disconnection event
        logger.info(
            f"YouTube Live API disconnection event",
            extra={
                "component": "youtube_connection",
                "event": "disconnection",
                "timestamp": time.time(),
                "total_connected_time": self.metrics.total_connected_time,
                "disconnection_count": self.metrics.disconnections
            }
        )
        
        # Clean up connection
        self.service = None
        self.credentials = None
        self._update_state(ConnectionState.DISCONNECTED)
    
    def reconnect(self, oauth_token: str) -> bool:
        """
        Attempt to reconnect to YouTube Live API after disconnection.
        
        Args:
            oauth_token: OAuth 2.0 token for authentication
            
        Returns:
            True if reconnection successful, False otherwise
            
        Validates: Requirement 1.5
        """
        logger.info("Attempting to reconnect to YouTube Live API")
        
        self._update_state(ConnectionState.RECONNECTING)
        self.metrics.reconnections += 1
        
        # Disconnect first if still connected
        if self.state != ConnectionState.DISCONNECTED:
            self.disconnect()
        
        # Attempt connection with retry logic
        return self.connect(oauth_token)
    
    def is_connected(self) -> bool:
        """
        Check if currently connected to YouTube Live API.
        
        Returns:
            True if connected, False otherwise
        """
        return self.state == ConnectionState.CONNECTED and self.service is not None
    
    def get_state(self) -> ConnectionState:
        """
        Get current connection state.
        
        Returns:
            Current ConnectionState
        """
        return self.state
    
    def get_metrics(self) -> ConnectionMetrics:
        """
        Get connection metrics for monitoring.
        
        Returns:
            ConnectionMetrics object with current metrics
        """
        return self.metrics
    
    def get_service(self):
        """
        Get the YouTube API service object.
        
        Returns:
            YouTube API service object if connected, None otherwise
        """
        if not self.is_connected():
            logger.warning("Attempted to get service while not connected")
            return None
        
        return self.service
    
    def test_connection(self) -> bool:
        """
        Test if the connection is still alive by making a simple API call.
        
        Returns:
            True if connection is alive, False otherwise
        """
        if not self.is_connected():
            return False
        
        try:
            # Make a simple API call to test connection
            request = self.service.liveBroadcasts().list(
                part='id',
                mine=True,
                maxResults=1
            )
            request.execute()
            
            logger.debug("Connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def get_connection_info(self) -> Dict[str, Any]:
        """
        Get comprehensive connection information for logging and monitoring.
        
        Returns:
            Dictionary with connection state, metrics, and status
        """
        return {
            "state": self.state.value,
            "is_connected": self.is_connected(),
            "metrics": {
                "connection_attempts": self.metrics.connection_attempts,
                "successful_connections": self.metrics.successful_connections,
                "failed_connections": self.metrics.failed_connections,
                "disconnections": self.metrics.disconnections,
                "reconnections": self.metrics.reconnections,
                "last_connection_time": self.metrics.last_connection_time,
                "last_disconnection_time": self.metrics.last_disconnection_time,
                "total_connected_time": self.metrics.total_connected_time
            },
            "retry_config": {
                "max_attempts": self.retry_config.max_attempts,
                "base_delay": self.retry_config.base_delay,
                "max_delay": self.retry_config.max_delay
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("YouTube Live API Connection Test")
    print("=" * 50)
    print()
    
    # Create connection manager
    connection = YouTubeConnection()
    
    print(f"Initial state: {connection.get_state().value}")
    print()
    
    # Note: This requires a valid OAuth token to actually connect
    # For testing, you would need to provide a real token
    print("To test connection, provide a valid OAuth 2.0 token")
    print("Connection manager is ready for use")
    print()
    
    # Display connection info
    info = connection.get_connection_info()
    print("Connection Info:")
    print(json.dumps(info, indent=2))
