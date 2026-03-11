"""
Data models for StreamBuddy.

This module contains all core data structures used throughout the StreamBuddy system
for representing video frames, audio data, chat messages, stream events, AI responses,
conversation history, and personality configuration.

Validates: Requirements 11.1, 11.2, 11.3
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union
from enum import Enum
import time


class Priority(Enum):
    """Priority levels for chat messages"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class VideoFrame:
    """
    Represents a single video frame from the stream.
    
    Attributes:
        timestamp: Unix timestamp when frame was captured
        frame_data: JPEG or PNG encoded frame data
        width: Frame width in pixels
        height: Frame height in pixels
        sequence_number: Sequential frame number for ordering
    """
    timestamp: float
    frame_data: bytes
    width: int
    height: int
    sequence_number: int
    
    def __post_init__(self):
        """Validate VideoFrame data"""
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not self.frame_data:
            raise ValueError("frame_data cannot be empty")
        if self.width <= 0:
            raise ValueError("width must be positive")
        if self.height <= 0:
            raise ValueError("height must be positive")
        if self.sequence_number < 0:
            raise ValueError("sequence_number must be non-negative")


@dataclass
class AudioData:
    """
    Represents audio data from the stream.
    
    Attributes:
        timestamp: Unix timestamp when audio was captured
        audio_bytes: Raw audio data
        sample_rate: Sample rate in Hz (e.g., 24000)
        duration_ms: Duration of audio chunk in milliseconds
        encoding: Audio encoding format (e.g., "pcm", "opus")
    """
    timestamp: float
    audio_bytes: bytes
    sample_rate: int
    duration_ms: int
    encoding: str
    
    def __post_init__(self):
        """Validate AudioData"""
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not self.audio_bytes:
            raise ValueError("audio_bytes cannot be empty")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        if not self.encoding:
            raise ValueError("encoding cannot be empty")
        valid_encodings = ["pcm", "opus", "mp3", "aac"]
        if self.encoding.lower() not in valid_encodings:
            raise ValueError(f"encoding must be one of {valid_encodings}")


@dataclass
class ChatMessage:
    """
    Represents a chat message from a viewer.
    
    Attributes:
        message_id: Unique identifier for the message
        username: Username of the viewer who sent the message
        content: Text content of the message
        timestamp: Unix timestamp when message was received
        priority: Priority level (HIGH, MEDIUM, LOW)
        is_spam: Whether the message is identified as spam
    """
    message_id: str
    username: str
    content: str
    timestamp: float
    priority: Priority = Priority.LOW
    is_spam: bool = False
    
    def __post_init__(self):
        """Validate ChatMessage"""
        if not self.message_id:
            raise ValueError("message_id cannot be empty")
        if not self.username:
            raise ValueError("username cannot be empty")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        # Content can be empty (will be filtered), but must be a string
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        if len(self.username) > 100:
            raise ValueError("username cannot exceed 100 characters")
        if len(self.content) > 5000:
            raise ValueError("content cannot exceed 5000 characters")


@dataclass
class StreamEvent:
    """
    Represents a significant event detected in the stream.
    
    Attributes:
        event_id: Unique identifier for the event
        event_type: Type of event (e.g., "visual_change", "emotional_shift", "chat_message", "game_event")
        timestamp: Unix timestamp when event occurred
        description: Human-readable description of the event
        significance: Significance score from 0.0 to 1.0
        related_data: Additional event-specific data
    """
    event_id: str
    event_type: str
    timestamp: float
    description: str
    significance: float
    related_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate StreamEvent"""
        if not self.event_id:
            raise ValueError("event_id cannot be empty")
        if not self.event_type:
            raise ValueError("event_type cannot be empty")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not 0.0 <= self.significance <= 1.0:
            raise ValueError("significance must be between 0.0 and 1.0")
        valid_event_types = ["visual_change", "emotional_shift", "chat_message", "game_event", "other"]
        if self.event_type not in valid_event_types:
            raise ValueError(f"event_type must be one of {valid_event_types}")


@dataclass
class AIResponse:
    """
    Represents a response generated by the AI.
    
    Attributes:
        response_id: Unique identifier for the response
        audio_data: Optional audio data for voice response
        text_content: Text content of the response
        timestamp: Unix timestamp when response was generated
        latency_ms: Latency in milliseconds from trigger to response
        triggered_by: ID of the event or message that triggered this response
    """
    response_id: str
    text_content: str
    timestamp: float
    latency_ms: int
    triggered_by: str
    audio_data: Optional[AudioData] = None
    
    def __post_init__(self):
        """Validate AIResponse"""
        if not self.response_id:
            raise ValueError("response_id cannot be empty")
        if not self.text_content:
            raise ValueError("text_content cannot be empty")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if not self.triggered_by:
            raise ValueError("triggered_by cannot be empty")


@dataclass
class Interaction:
    """
    Represents a single interaction (trigger + response).
    
    Attributes:
        timestamp: Unix timestamp of the interaction
        trigger: The chat message or stream event that triggered the response
        response: The AI response generated
    """
    timestamp: float
    trigger: Union[ChatMessage, StreamEvent]
    response: AIResponse
    
    def __post_init__(self):
        """Validate Interaction"""
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not isinstance(self.trigger, (ChatMessage, StreamEvent)):
            raise ValueError("trigger must be ChatMessage or StreamEvent")
        if not isinstance(self.response, AIResponse):
            raise ValueError("response must be AIResponse")


@dataclass
class ConversationHistory:
    """
    Maintains conversation history for a streaming session.
    
    Attributes:
        interactions: List of recent interactions (max 50, FIFO)
        recent_events: List of recent significant events (max 10, FIFO)
        session_start: Unix timestamp when session started
        total_interactions: Total number of interactions in session
    """
    session_start: float
    interactions: List[Interaction] = field(default_factory=list)
    recent_events: List[StreamEvent] = field(default_factory=list)
    total_interactions: int = 0
    
    def __post_init__(self):
        """Validate ConversationHistory"""
        if self.session_start <= 0:
            raise ValueError("session_start must be positive")
        if self.total_interactions < 0:
            raise ValueError("total_interactions must be non-negative")
        if len(self.interactions) > 50:
            raise ValueError("interactions list cannot exceed 50 items")
        if len(self.recent_events) > 10:
            raise ValueError("recent_events list cannot exceed 10 items")
    
    def add_interaction(self, interaction: Interaction) -> None:
        """
        Add an interaction to history, maintaining max size of 50.
        
        Args:
            interaction: The interaction to add
        """
        if not isinstance(interaction, Interaction):
            raise ValueError("interaction must be an Interaction instance")
        
        self.interactions.append(interaction)
        self.total_interactions += 1
        
        # Maintain FIFO with max 50 items
        if len(self.interactions) > 50:
            self.interactions.pop(0)
    
    def add_event(self, event: StreamEvent) -> None:
        """
        Add a significant event to recent events, maintaining max size of 10.
        
        Args:
            event: The stream event to add
        """
        if not isinstance(event, StreamEvent):
            raise ValueError("event must be a StreamEvent instance")
        
        self.recent_events.append(event)
        
        # Maintain FIFO with max 10 items
        if len(self.recent_events) > 10:
            self.recent_events.pop(0)
    
    def get_session_duration(self) -> float:
        """
        Get the duration of the current session in seconds.
        
        Returns:
            Session duration in seconds
        """
        return time.time() - self.session_start


@dataclass
class PersonalityConfig:
    """
    Configuration for StreamBuddy's personality and behavior.
    
    Attributes:
        humor_level: Humor level from 0.0 (serious) to 1.0 (very humorous)
        supportiveness: Supportiveness level from 0.0 (neutral) to 1.0 (very supportive)
        playfulness: Playfulness level from 0.0 (formal) to 1.0 (very playful)
        verbosity: Response length ("concise", "moderate", "verbose")
        response_frequency: How often to respond ("low", "medium", "high")
        chat_interaction_mode: Chat interaction style ("selective", "responsive", "active")
    """
    humor_level: float = 0.5
    supportiveness: float = 0.7
    playfulness: float = 0.6
    verbosity: str = "moderate"
    response_frequency: str = "medium"
    chat_interaction_mode: str = "responsive"
    
    def __post_init__(self):
        """Validate PersonalityConfig"""
        if not 0.0 <= self.humor_level <= 1.0:
            raise ValueError("humor_level must be between 0.0 and 1.0")
        if not 0.0 <= self.supportiveness <= 1.0:
            raise ValueError("supportiveness must be between 0.0 and 1.0")
        if not 0.0 <= self.playfulness <= 1.0:
            raise ValueError("playfulness must be between 0.0 and 1.0")
        
        valid_verbosity = ["concise", "moderate", "verbose"]
        if self.verbosity not in valid_verbosity:
            raise ValueError(f"verbosity must be one of {valid_verbosity}")
        
        valid_frequency = ["low", "medium", "high"]
        if self.response_frequency not in valid_frequency:
            raise ValueError(f"response_frequency must be one of {valid_frequency}")
        
        valid_interaction_modes = ["selective", "responsive", "active"]
        if self.chat_interaction_mode not in valid_interaction_modes:
            raise ValueError(f"chat_interaction_mode must be one of {valid_interaction_modes}")
    
    def update(self, **kwargs) -> None:
        """
        Update configuration parameters.
        
        Args:
            **kwargs: Configuration parameters to update
        
        Raises:
            ValueError: If invalid parameter values are provided
        """
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise ValueError(f"Invalid configuration parameter: {key}")
            setattr(self, key, value)
        
        # Re-validate after update
        self.__post_init__()
