"""
Chat Monitor for StreamBuddy.

This module processes incoming chat messages from YouTube Live, including parsing,
spam filtering, prioritization, and forwarding to the Context Manager.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5
"""

import time
import re
from typing import Dict, Optional, List, Callable
from collections import defaultdict, deque
from dataclasses import dataclass
from streambuddy_agent.models import ChatMessage, Priority
import asyncio


@dataclass
class MessageRate:
    """Track message rate for spam detection"""
    timestamps: List[float]
    
    def add_message(self, timestamp: float) -> None:
        """Add a message timestamp"""
        self.timestamps.append(timestamp)
        # Keep only messages from last second
        cutoff = timestamp - 1.0
        self.timestamps = [ts for ts in self.timestamps if ts > cutoff]
    
    def get_rate(self) -> int:
        """Get messages per second"""
        return len(self.timestamps)


class ChatMonitor:
    """
    Monitors and processes chat messages from YouTube Live.
    
    Responsibilities:
    - Parse raw chat messages into structured ChatMessage objects
    - Filter spam messages based on rate and content patterns
    - Prioritize messages based on content
    - Forward processed messages to Context Manager
    """
    
    def __init__(self, context_manager_callback: Optional[Callable] = None):
        """
        Initialize Chat Monitor.
        
        Args:
            context_manager_callback: Optional callback function to forward messages
                                     to Context Manager. If None, messages are queued.
        """
        self.user_message_rates: Dict[str, MessageRate] = defaultdict(
            lambda: MessageRate(timestamps=[])
        )
        
        # Message queue for high-throughput scenarios
        self.message_queue: deque[ChatMessage] = deque(maxlen=100)
        
        # Context Manager callback
        self.context_manager_callback = context_manager_callback
        
        # Spam detection patterns
        self.spam_phrases = [
            r'buy now',
            r'click here',
            r'free money',
            r'subscribe to',
            r'check out my',
            r'visit my channel',
            r'http[s]?://',  # URLs
        ]
        
        # Question patterns for priority detection
        self.question_patterns = [
            r'\?$',  # Ends with question mark
            r'^(what|when|where|why|how|who|can|could|would|should|is|are|do|does)',
        ]
    
    def parse_message(self, raw_message: Dict) -> Optional[ChatMessage]:
        """
        Parse a raw chat message into a structured ChatMessage.
        
        Args:
            raw_message: Raw message dict from YouTube Live API with keys:
                - id: Message ID
                - author: Author info dict with 'displayName'
                - message: Message text content
                - timestamp: Message timestamp
        
        Returns:
            ChatMessage object or None if parsing fails
        
        Validates: Requirements 4.1, 4.2
        """
        try:
            # Extract fields from raw message
            message_id = raw_message.get('id', '')
            author_info = raw_message.get('author', {})
            username = author_info.get('displayName', 'Unknown')
            content = raw_message.get('message', '')
            timestamp = raw_message.get('timestamp', time.time())
            
            # Convert timestamp if it's a string
            if isinstance(timestamp, str):
                # Try to parse ISO format or use current time
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamp = dt.timestamp()
                except:
                    timestamp = time.time()
            
            # Create ChatMessage with default priority and spam status
            # These will be updated by filter and prioritize methods
            message = ChatMessage(
                message_id=message_id,
                username=username,
                content=content,
                timestamp=timestamp,
                priority=Priority.LOW,
                is_spam=False
            )
            
            return message
            
        except Exception as e:
            # Log parsing error and return None
            print(f"Error parsing chat message: {e}")
            return None
    
    def extract_username_and_content(self, message: ChatMessage) -> tuple[str, str]:
        """
        Extract username and content from a ChatMessage.
        
        Args:
            message: ChatMessage object
        
        Returns:
            Tuple of (username, content)
        
        Validates: Requirements 4.2
        """
        return (message.username, message.content)
    
    def filter_spam(self, message: ChatMessage) -> bool:
        """
        Determine if a message is spam based on rate and content patterns.
        
        Spam criteria:
        - Message rate > 5 per second from same user
        - Excessive caps (> 70% uppercase)
        - Repeated characters (same char 5+ times in a row)
        - Known spam phrases
        - Message too short (< 2 characters)
        
        Args:
            message: ChatMessage to check
        
        Returns:
            True if message is spam, False otherwise
        
        Validates: Requirements 4.4, 13.6
        """
        # Check minimum length
        if len(message.content.strip()) < 2:
            return True
        
        # Check message rate from this user
        user_rate = self.user_message_rates[message.username]
        user_rate.add_message(message.timestamp)
        
        if user_rate.get_rate() > 5:
            return True
        
        # Check for excessive caps (> 70% uppercase)
        letters = [c for c in message.content if c.isalpha()]
        if letters:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio > 0.7 and len(letters) > 5:
                return True
        
        # Check for repeated characters (5+ in a row)
        if re.search(r'(.)\1{4,}', message.content):
            return True
        
        # Check for spam phrases
        content_lower = message.content.lower()
        for pattern in self.spam_phrases:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return True
        
        return False
    
    def prioritize_message(self, message: ChatMessage) -> Priority:
        """
        Determine priority level for a message.
        
        Priority rules:
        - HIGH: Mentions "StreamBuddy" or contains question
        - MEDIUM: Reactions to recent events (contains common reaction words)
        - LOW: General chat messages
        
        Args:
            message: ChatMessage to prioritize
        
        Returns:
            Priority level (HIGH, MEDIUM, LOW)
        
        Validates: Requirements 4.5
        """
        content_lower = message.content.lower()
        
        # HIGH priority: Mentions StreamBuddy or contains question
        if 'streambuddy' in content_lower:
            return Priority.HIGH
        
        for pattern in self.question_patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return Priority.HIGH
        
        # MEDIUM priority: Reactions (common reaction words/emojis)
        reaction_words = ['lol', 'wow', 'omg', 'nice', 'cool', 'awesome', 'haha', 'lmao']
        if any(word in content_lower for word in reaction_words):
            return Priority.MEDIUM
        
        # LOW priority: Everything else
        return Priority.LOW
    
    def process_message(self, raw_message: Dict) -> Optional[ChatMessage]:
        """
        Process a raw chat message: parse, filter spam, and prioritize.
        
        Args:
            raw_message: Raw message dict from YouTube Live API
        
        Returns:
            Processed ChatMessage or None if spam/invalid
        
        Validates: Requirements 4.1, 4.2, 4.4, 4.5
        """
        # Parse message
        message = self.parse_message(raw_message)
        if message is None:
            return None
        
        # Filter spam
        is_spam = self.filter_spam(message)
        message.is_spam = is_spam
        
        if is_spam:
            return None  # Don't process spam messages
        
        # Prioritize message
        priority = self.prioritize_message(message)
        message.priority = priority
        
        return message
    
    def forward_to_context_manager(self, message: ChatMessage) -> bool:
        """
        Forward a processed message to the Context Manager.
        
        Messages are either:
        1. Forwarded immediately via callback if available
        2. Queued for later processing in high-throughput scenarios
        
        Args:
            message: ChatMessage to forward
        
        Returns:
            True if forwarding succeeded, False otherwise
        
        Validates: Requirements 4.3
        """
        start_time = time.time()
        
        try:
            if self.context_manager_callback:
                # Forward directly to Context Manager via callback
                self.context_manager_callback(message)
            else:
                # Queue message for later processing
                self.message_queue.append(message)
            
            # Verify forwarding latency (should be < 200ms)
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 200:
                print(f"Warning: Message forwarding took {latency_ms:.2f}ms (> 200ms target)")
            
            return True
            
        except Exception as e:
            print(f"Error forwarding message to Context Manager: {e}")
            return False
    
    def get_queued_messages(self) -> List[ChatMessage]:
        """
        Get all queued messages and clear the queue.
        
        Returns:
            List of queued ChatMessage objects
        """
        messages = list(self.message_queue)
        self.message_queue.clear()
        return messages
    
    def get_queue_size(self) -> int:
        """
        Get the current size of the message queue.
        
        Returns:
            Number of messages in queue
        """
        return len(self.message_queue)
    
    async def process_message_stream(self, message_stream):
        """
        Process a stream of chat messages asynchronously.
        
        This method handles high-throughput scenarios by processing
        messages as they arrive and forwarding them within 200ms.
        
        Args:
            message_stream: Async iterator of raw chat messages
        
        Validates: Requirements 4.3, 9.5
        """
        async for raw_message in message_stream:
            message = self.process_message(raw_message)
            if message:
                self.forward_to_context_manager(message)
