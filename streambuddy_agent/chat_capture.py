"""
Chat Stream Capture Module

This module implements chat message stream capture from YouTube Live streams with
disconnection detection, reconnection logic, and forwarding to Chat Monitor.

Validates: Requirements 1.3, 1.5
"""

import logging
import time
import uuid
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from threading import Thread, Event, Lock
from queue import Queue, Empty
from googleapiclient.errors import HttpError

from streambuddy_agent.models import ChatMessage, Priority
from streambuddy_agent.youtube_connection import YouTubeConnection, ConnectionState

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class ChatConfig:
    """Configuration for chat capture"""
    poll_interval_ms: int = 2000  # Polling interval in milliseconds
    max_results: int = 200  # Maximum messages per poll
    buffer_size: int = 100  # Maximum messages to buffer
    reconnect_delay_ms: int = 5000  # Delay before reconnection attempt


@dataclass
class ChatMetrics:
    """Metrics for chat capture monitoring"""
    messages_captured: int = 0
    messages_forwarded: int = 0
    messages_dropped: int = 0
    polls_executed: int = 0
    poll_errors: int = 0
    disconnections: int = 0
    reconnections: int = 0
    total_poll_time: float = 0.0
    total_forwarding_time: float = 0.0
    last_capture_time: Optional[float] = None
    last_disconnection_time: Optional[float] = None


class ChatCapture:
    """
    Manages chat message stream capture from YouTube Live with disconnection
    detection and automatic reconnection.
    
    Validates: Requirements 1.3, 1.5
    """
    
    def __init__(
        self,
        youtube_connection: YouTubeConnection,
        config: Optional[ChatConfig] = None,
        forward_callback: Optional[Callable[[ChatMessage], None]] = None
    ):
        """
        Initialize chat capture manager.
        
        Args:
            youtube_connection: YouTube connection instance
            config: Chat capture configuration (uses defaults if None)
            forward_callback: Callback function to forward messages to Chat Monitor
        """
        self.youtube_connection = youtube_connection
        self.config = config or ChatConfig()
        self.forward_callback = forward_callback
        self.metrics = ChatMetrics()
        
        # Threading components
        self._capture_thread: Optional[Thread] = None
        self._stop_event = Event()
        self._message_queue: Queue = Queue(maxsize=self.config.buffer_size)
        self._queue_lock = Lock()
        
        # Chat stream state
        self._live_chat_id: Optional[str] = None
        self._next_page_token: Optional[str] = None
        self._is_capturing = False
        
        logger.info(
            f"Chat capture initialized: poll interval {self.config.poll_interval_ms}ms, "
            f"max results {self.config.max_results}"
        )
    
    def _get_live_chat_id(self) -> Optional[str]:
        """
        Get the live chat ID for the active broadcast.
        
        Returns:
            Live chat ID if found, None otherwise
        """
        try:
            service = self.youtube_connection.get_service()
            if not service:
                logger.error("YouTube service not available")
                return None
            
            # Get active live broadcasts
            # Note: broadcastStatus and mine cannot be used together in the API
            # Use broadcastType='all' with mine=True, then filter by status
            request = service.liveBroadcasts().list(
                part='snippet,status',
                broadcastType='all',
                mine=True,
                maxResults=10
            )
            response = request.execute()
            
            # Filter to only active broadcasts
            items = [
                item for item in response.get('items', [])
                if item.get('status', {}).get('lifeCycleStatus') == 'live'
            ]
            
            if not items:
                logger.warning("No active live broadcasts found")
                return None
            
            # Get the live chat ID from the first active broadcast
            broadcast = items[0]
            live_chat_id = broadcast['snippet'].get('liveChatId')
            
            if not live_chat_id:
                logger.warning("Active broadcast has no live chat")
                return None
            
            logger.info(f"Found live chat ID: {live_chat_id}")
            return live_chat_id
            
        except HttpError as e:
            logger.error(f"HTTP error getting live chat ID: {e.resp.status} - {e.content.decode()}")
            return None
        except Exception as e:
            logger.error(f"Error getting live chat ID: {e}")
            return None
    
    def _parse_chat_message(self, item: Dict[str, Any]) -> Optional[ChatMessage]:
        """
        Parse a raw chat message from YouTube API response.
        
        Args:
            item: Raw message item from API
            
        Returns:
            Parsed ChatMessage object, or None if parsing fails
        """
        try:
            snippet = item.get('snippet', {})
            author_details = item.get('authorDetails', {})
            
            # Extract message data
            message_id = item.get('id', str(uuid.uuid4()))
            username = author_details.get('displayName', 'Unknown')
            content = snippet.get('displayMessage', '')
            published_at = snippet.get('publishedAt', '')
            
            # Convert published_at to timestamp
            # For now, use current time (in production, parse ISO 8601 timestamp)
            timestamp = time.time()
            
            # Create ChatMessage with default priority (will be set by Chat Monitor)
            chat_message = ChatMessage(
                message_id=message_id,
                username=username,
                content=content,
                timestamp=timestamp,
                priority=Priority.LOW,
                is_spam=False
            )
            
            logger.debug(f"Parsed message from {username}: {content[:50]}...")
            return chat_message
            
        except Exception as e:
            logger.error(f"Failed to parse chat message: {e}")
            return None
    
    def _poll_chat_messages(self) -> List[ChatMessage]:
        """
        Poll for new chat messages from YouTube Live API.
        
        Returns:
            List of new ChatMessage objects
        """
        if not self._live_chat_id:
            logger.warning("No live chat ID available")
            return []
        
        try:
            service = self.youtube_connection.get_service()
            if not service:
                logger.error("YouTube service not available")
                return []
            
            poll_start = time.time()
            
            # Build request
            request = service.liveChatMessages().list(
                liveChatId=self._live_chat_id,
                part='snippet,authorDetails',
                maxResults=self.config.max_results,
                pageToken=self._next_page_token
            )
            
            # Execute request
            response = request.execute()
            
            poll_time = time.time() - poll_start
            self.metrics.total_poll_time += poll_time
            self.metrics.polls_executed += 1
            
            logger.debug(f"Poll completed in {poll_time*1000:.2f}ms")
            
            # Update next page token
            self._next_page_token = response.get('nextPageToken')
            
            # Parse messages
            messages = []
            items = response.get('items', [])
            
            for item in items:
                message = self._parse_chat_message(item)
                if message:
                    messages.append(message)
                    self.metrics.messages_captured += 1
                    self.metrics.last_capture_time = message.timestamp
            
            if messages:
                logger.info(f"Captured {len(messages)} chat messages")
            
            return messages
            
        except HttpError as e:
            self.metrics.poll_errors += 1
            logger.error(f"HTTP error polling chat: {e.resp.status} - {e.content.decode()}")
            
            # Check if this is a disconnection error
            if e.resp.status in [403, 404, 410]:
                logger.warning("Chat stream may be disconnected")
                self._handle_disconnection()
            
            return []
            
        except Exception as e:
            self.metrics.poll_errors += 1
            logger.error(f"Error polling chat messages: {e}")
            return []
    
    def _forward_message(self, message: ChatMessage) -> bool:
        """
        Forward chat message to Chat Monitor via callback.
        
        Args:
            message: ChatMessage to forward
            
        Returns:
            True if forwarding successful, False otherwise
        """
        if not self.forward_callback:
            logger.warning("No forward callback configured, message not forwarded")
            return False
        
        try:
            start_time = time.time()
            
            # Call forward callback
            self.forward_callback(message)
            
            forwarding_time = time.time() - start_time
            self.metrics.total_forwarding_time += forwarding_time
            self.metrics.messages_forwarded += 1
            
            # Check latency requirement (< 200ms per message)
            if forwarding_time > 0.2:
                logger.warning(
                    f"Message forwarding exceeded 200ms latency: {forwarding_time*1000:.2f}ms"
                )
            else:
                logger.debug(
                    f"Message forwarded in {forwarding_time*1000:.2f}ms "
                    f"(from {message.username})"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to forward message: {e}")
            return False
    
    def _handle_disconnection(self) -> None:
        """
        Handle chat stream disconnection event.
        
        Logs the disconnection and prepares for reconnection attempt.
        
        Validates: Requirement 1.5
        """
        self.metrics.disconnections += 1
        self.metrics.last_disconnection_time = time.time()
        
        # Log disconnection event
        logger.warning(
            f"Chat stream disconnection detected",
            extra={
                "component": "chat_capture",
                "event": "disconnection",
                "timestamp": time.time(),
                "live_chat_id": self._live_chat_id,
                "disconnection_count": self.metrics.disconnections
            }
        )
        
        # Clear chat state
        self._live_chat_id = None
        self._next_page_token = None
    
    def _attempt_reconnection(self) -> bool:
        """
        Attempt to reconnect to chat stream.
        
        Returns:
            True if reconnection successful, False otherwise
            
        Validates: Requirement 1.5
        """
        logger.info("Attempting to reconnect to chat stream...")
        self.metrics.reconnections += 1
        
        # Check YouTube connection
        if not self.youtube_connection.is_connected():
            logger.warning("YouTube connection not available for reconnection")
            return False
        
        # Try to get new live chat ID
        self._live_chat_id = self._get_live_chat_id()
        
        if self._live_chat_id:
            logger.info("Successfully reconnected to chat stream")
            self._next_page_token = None  # Reset page token
            return True
        else:
            logger.warning("Failed to reconnect to chat stream")
            return False
    
    def _capture_loop(self):
        """
        Main capture loop running in separate thread.
        Polls for chat messages at configured interval and forwards them.
        """
        logger.info("Chat capture loop started")
        
        poll_interval = self.config.poll_interval_ms / 1000.0
        next_poll_time = time.time()
        
        while not self._stop_event.is_set():
            try:
                # Wait until next poll time
                current_time = time.time()
                if current_time < next_poll_time:
                    sleep_time = next_poll_time - current_time
                    if self._stop_event.wait(timeout=sleep_time):
                        break
                    continue
                
                # Update next poll time
                next_poll_time = current_time + poll_interval
                
                # Check if we need to reconnect
                if not self._live_chat_id:
                    if not self._attempt_reconnection():
                        # Wait before next reconnection attempt
                        reconnect_delay = self.config.reconnect_delay_ms / 1000.0
                        if self._stop_event.wait(timeout=reconnect_delay):
                            break
                        continue
                
                # Poll for new messages
                messages = self._poll_chat_messages()
                
                # Process and forward each message
                for message in messages:
                    # Try to add to queue (non-blocking)
                    try:
                        self._message_queue.put_nowait(message)
                    except:
                        # Queue full, drop message
                        self.metrics.messages_dropped += 1
                        logger.warning(
                            f"Message queue full, dropped message from {message.username}"
                        )
                    
                    # Forward message immediately (in same thread for low latency)
                    self._forward_message(message)
                
            except Exception as e:
                logger.error(f"Error in capture loop: {e}")
                time.sleep(1.0)
        
        logger.info("Chat capture loop stopped")
    
    def start_capture(self) -> bool:
        """
        Start chat message capture from YouTube Live stream.
        
        Returns:
            True if capture started successfully, False otherwise
            
        Validates: Requirements 1.3, 1.5
        """
        if self._is_capturing:
            logger.warning("Chat capture already running")
            return True
        
        # Check YouTube connection
        if not self.youtube_connection.is_connected():
            logger.error("YouTube connection not available")
            return False
        
        try:
            # Get live chat ID
            logger.info("Getting live chat ID...")
            self._live_chat_id = self._get_live_chat_id()
            
            if not self._live_chat_id:
                logger.error("Failed to get live chat ID")
                return False
            
            # Start capture thread
            self._stop_event.clear()
            self._capture_thread = Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            self._is_capturing = True
            logger.info("Chat capture started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start chat capture: {e}")
            return False
    
    def stop_capture(self) -> None:
        """
        Stop chat capture and clean up resources.
        """
        if not self._is_capturing:
            logger.debug("Chat capture not running")
            return
        
        logger.info("Stopping chat capture...")
        
        # Signal stop
        self._stop_event.set()
        
        # Wait for capture thread to finish
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        
        # Clear state
        self._live_chat_id = None
        self._next_page_token = None
        
        self._is_capturing = False
        logger.info("Chat capture stopped")
    
    def is_capturing(self) -> bool:
        """
        Check if chat capture is currently running.
        
        Returns:
            True if capturing, False otherwise
        """
        return self._is_capturing
    
    def get_metrics(self) -> ChatMetrics:
        """
        Get chat capture metrics for monitoring.
        
        Returns:
            ChatMetrics object with current metrics
        """
        return self.metrics
    
    def get_config(self) -> ChatConfig:
        """
        Get chat capture configuration.
        
        Returns:
            ChatConfig object
        """
        return self.config
    
    def set_poll_interval(self, interval_ms: int) -> None:
        """
        Update poll interval dynamically.
        
        Args:
            interval_ms: New poll interval in milliseconds
        """
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        
        old_interval = self.config.poll_interval_ms
        self.config.poll_interval_ms = interval_ms
        
        logger.info(f"Poll interval updated: {old_interval}ms -> {interval_ms}ms")
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get comprehensive chat capture information.
        
        Returns:
            Dictionary with configuration, state, and metrics
        """
        return {
            "is_capturing": self._is_capturing,
            "live_chat_id": self._live_chat_id,
            "youtube_connected": self.youtube_connection.is_connected(),
            "config": {
                "poll_interval_ms": self.config.poll_interval_ms,
                "max_results": self.config.max_results,
                "buffer_size": self.config.buffer_size,
                "reconnect_delay_ms": self.config.reconnect_delay_ms
            },
            "metrics": {
                "messages_captured": self.metrics.messages_captured,
                "messages_forwarded": self.metrics.messages_forwarded,
                "messages_dropped": self.metrics.messages_dropped,
                "polls_executed": self.metrics.polls_executed,
                "poll_errors": self.metrics.poll_errors,
                "disconnections": self.metrics.disconnections,
                "reconnections": self.metrics.reconnections,
                "total_poll_time": self.metrics.total_poll_time,
                "total_forwarding_time": self.metrics.total_forwarding_time,
                "last_capture_time": self.metrics.last_capture_time,
                "last_disconnection_time": self.metrics.last_disconnection_time
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Chat Stream Capture Test")
    print("=" * 50)
    print()
    
    # Example forward callback
    def forward_message(message: ChatMessage):
        print(f"Message from {message.username}: {message.content}")
    
    # Create YouTube connection (would need real credentials)
    youtube_connection = YouTubeConnection()
    
    # Create chat capture with custom config
    config = ChatConfig(
        poll_interval_ms=2000,
        max_results=200
    )
    
    capture = ChatCapture(
        youtube_connection=youtube_connection,
        config=config,
        forward_callback=forward_message
    )
    
    print(f"Chat capture ready")
    print(f"Configuration: poll interval {config.poll_interval_ms}ms, "
          f"max {config.max_results} messages per poll")
    print()
    print("To test capture, first connect to YouTube:")
    print("  youtube_connection.connect(oauth_token)")
    print("Then start capture:")
    print("  capture.start_capture()")
