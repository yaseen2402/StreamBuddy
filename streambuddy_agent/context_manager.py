"""
Context Manager for StreamBuddy.

This module maintains conversation state, analyzes stream context, and orchestrates
response generation. It handles conversation history, event detection, commentary
generation, chat message processing, interruption handling, and personality configuration.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 4.6, 6.3, 6.5, 11.1, 11.2, 11.3, 11.4, 11.5
"""

import time
import logging
import uuid
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
import asyncio
from collections import deque

from streambuddy_agent.models import (
    VideoFrame, AudioData, ChatMessage, StreamEvent, AIResponse,
    ConversationHistory, Interaction, PersonalityConfig, Priority
)

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class EventDetectionConfig:
    """Configuration for event detection"""
    visual_change_threshold: float = 0.7  # Significance threshold for visual changes
    emotional_shift_threshold: float = 0.6  # Threshold for emotional tone detection
    game_event_threshold: float = 0.8  # Threshold for game-specific events
    min_event_interval: float = 2.0  # Minimum seconds between events


@dataclass
class CommentaryConfig:
    """Configuration for commentary generation"""
    trigger_delay_ms: int = 1000  # Max delay to trigger commentary (1 second)
    min_commentary_interval: float = 5.0  # Minimum seconds between commentary
    context_window_size: int = 5  # Number of recent events to include in context


class ContextManager:
    """
    Manages conversation state, stream context analysis, and response orchestration.
    
    Responsibilities:
    - Maintain conversation history (last 50 interactions)
    - Maintain recent events buffer (last 10 significant events)
    - Detect significant events from video and audio
    - Generate commentary prompts with personality configuration
    - Process chat messages and determine responses
    - Handle interruptions and generate acknowledgments
    - Apply and update personality configuration
    """

    
    def __init__(
        self,
        personality_config: Optional[PersonalityConfig] = None,
        event_detection_config: Optional[EventDetectionConfig] = None,
        commentary_config: Optional[CommentaryConfig] = None,
        gemini_client_callback: Optional[Callable] = None,
        audio_output_callback: Optional[Callable] = None
    ):
        """
        Initialize Context Manager.
        
        Args:
            personality_config: Personality configuration (uses defaults if None)
            event_detection_config: Event detection configuration (uses defaults if None)
            commentary_config: Commentary configuration (uses defaults if None)
            gemini_client_callback: Callback to send prompts to Gemini Live Client
            audio_output_callback: Callback to send responses to Audio Output Service
        """
        # Configuration
        self.personality_config = personality_config or PersonalityConfig()
        self.event_detection_config = event_detection_config or EventDetectionConfig()
        self.commentary_config = commentary_config or CommentaryConfig()
        
        # Callbacks
        self.gemini_client_callback = gemini_client_callback
        self.audio_output_callback = audio_output_callback
        
        # Conversation history (max 50 interactions, FIFO)
        self.conversation_history = ConversationHistory(session_start=time.time())
        
        # Recent events buffer (max 10 significant events, FIFO)
        self.recent_events: deque[StreamEvent] = deque(maxlen=10)
        
        # Active response tracking
        self.active_response_id: Optional[str] = None
        self.last_commentary_time: float = 0.0
        self.last_event_time: float = 0.0
        
        # Configuration update tracking
        self.config_update_time: Optional[float] = None
        
        logger.info("Context Manager initialized")
    
    # ========== Conversation History Management (Task 8.1) ==========
    
    def add_to_history(self, interaction: Interaction) -> None:
        """
        Add an interaction to conversation history.
        
        Maintains sliding window of last 50 interactions (FIFO).
        
        Args:
            interaction: Interaction to add to history
            
        Validates: Requirement 5.4
        """
        if not isinstance(interaction, Interaction):
            raise ValueError("interaction must be an Interaction instance")
        
        self.conversation_history.add_interaction(interaction)
        
        logger.debug(
            f"Added interaction to history (total: {self.conversation_history.total_interactions}, "
            f"in buffer: {len(self.conversation_history.interactions)})"
        )
    
    def add_event_to_buffer(self, event: StreamEvent) -> None:
        """
        Add a significant event to recent events buffer.
        
        Maintains buffer of last 10 significant events (FIFO).
        
        Args:
            event: StreamEvent to add to buffer
            
        Validates: Requirement 5.4
        """
        if not isinstance(event, StreamEvent):
            raise ValueError("event must be a StreamEvent instance")
        
        self.recent_events.append(event)
        self.conversation_history.add_event(event)
        
        logger.debug(
            f"Added event to buffer: {event.event_type} "
            f"(significance: {event.significance:.2f}, buffer size: {len(self.recent_events)})"
        )

    
    def get_conversation_history(self) -> ConversationHistory:
        """
        Get the current conversation history.
        
        Returns:
            ConversationHistory object with interactions and events
            
        Validates: Requirement 5.4
        """
        return self.conversation_history
    
    def get_recent_events(self, count: Optional[int] = None) -> List[StreamEvent]:
        """
        Get recent significant events.
        
        Args:
            count: Number of recent events to return (None for all)
            
        Returns:
            List of recent StreamEvent objects
            
        Validates: Requirement 5.4
        """
        if count is None:
            return list(self.recent_events)
        else:
            return list(self.recent_events)[-count:]
    
    def get_recent_interactions(self, count: Optional[int] = None) -> List[Interaction]:
        """
        Get recent interactions from history.
        
        Args:
            count: Number of recent interactions to return (None for all)
            
        Returns:
            List of recent Interaction objects
        """
        if count is None:
            return self.conversation_history.interactions
        else:
            return self.conversation_history.interactions[-count:]
    
    # ========== Event Detection (Task 8.2) ==========
    
    def detect_visual_change(self, video_frames: List[VideoFrame]) -> Optional[StreamEvent]:
        """
        Analyze video frames for significant visual changes.
        
        Detects scene transitions, dramatic moments, and other visual events.
        
        Args:
            video_frames: List of recent video frames to analyze
            
        Returns:
            StreamEvent if significant change detected, None otherwise
            
        Validates: Requirements 5.1, 5.6
        """
        if not video_frames or len(video_frames) < 2:
            return None
        
        # Simple heuristic: check if frames are significantly different
        # In a real implementation, this would use computer vision techniques
        # For now, we'll use frame size changes as a proxy
        
        frame_sizes = [len(frame.frame_data) for frame in video_frames]
        avg_size = sum(frame_sizes) / len(frame_sizes)
        
        # Check for significant size variation (indicating scene change)
        max_deviation = max(abs(size - avg_size) for size in frame_sizes)
        relative_deviation = max_deviation / avg_size if avg_size > 0 else 0
        
        # Calculate significance score
        significance = min(relative_deviation * 2, 1.0)  # Scale to 0-1
        
        if significance >= self.event_detection_config.visual_change_threshold:
            event = StreamEvent(
                event_id=str(uuid.uuid4()),
                event_type="visual_change",
                timestamp=time.time(),
                description=f"Significant visual change detected (significance: {significance:.2f})",
                significance=significance,
                related_data={
                    "frame_count": len(video_frames),
                    "avg_frame_size": avg_size,
                    "max_deviation": max_deviation
                }
            )
            
            logger.info(f"Visual change detected: {event.description}")
            return event
        
        return None

    
    def detect_emotional_tone(self, audio_data: AudioData) -> Optional[StreamEvent]:
        """
        Analyze audio for emotional tone detection.
        
        Detects emotional shifts in streamer's voice (excitement, frustration, etc.).
        
        Args:
            audio_data: AudioData to analyze
            
        Returns:
            StreamEvent if emotional shift detected, None otherwise
            
        Validates: Requirements 5.2, 5.6
        """
        if not audio_data or not audio_data.audio_bytes:
            return None
        
        # Simple heuristic: use audio amplitude/energy as proxy for emotion
        # In a real implementation, this would use audio analysis techniques
        
        # Calculate simple energy metric from audio data
        audio_bytes = audio_data.audio_bytes
        if len(audio_bytes) < 100:
            return None
        
        # Sample some bytes to estimate energy
        sample_size = min(1000, len(audio_bytes))
        sample = audio_bytes[:sample_size]
        
        # Calculate average absolute value as energy proxy
        energy = sum(abs(b - 128) for b in sample) / sample_size
        normalized_energy = energy / 128.0  # Normalize to 0-1
        
        # Determine significance based on energy level
        significance = min(normalized_energy * 1.5, 1.0)
        
        if significance >= self.event_detection_config.emotional_shift_threshold:
            # Determine emotion type based on energy
            if normalized_energy > 0.7:
                emotion = "excitement"
            elif normalized_energy > 0.4:
                emotion = "engagement"
            else:
                emotion = "calm"
            
            event = StreamEvent(
                event_id=str(uuid.uuid4()),
                event_type="emotional_shift",
                timestamp=time.time(),
                description=f"Emotional tone detected: {emotion} (significance: {significance:.2f})",
                significance=significance,
                related_data={
                    "emotion": emotion,
                    "energy_level": normalized_energy,
                    "duration_ms": audio_data.duration_ms
                }
            )
            
            logger.info(f"Emotional tone detected: {event.description}")
            return event
        
        return None
    
    def score_event_significance(self, event: StreamEvent) -> float:
        """
        Calculate significance score for an event (0.0 to 1.0).
        
        Args:
            event: StreamEvent to score
            
        Returns:
            Significance score between 0.0 and 1.0
            
        Validates: Requirements 5.1, 5.2
        """
        # Event already has a significance score
        base_significance = event.significance
        
        # Adjust based on event type
        type_multipliers = {
            "visual_change": 1.0,
            "emotional_shift": 0.9,
            "game_event": 1.2,
            "chat_message": 0.8,
            "other": 0.7
        }
        
        multiplier = type_multipliers.get(event.event_type, 1.0)
        adjusted_significance = min(base_significance * multiplier, 1.0)
        
        return adjusted_significance

    
    def detect_game_event(self, video_frames: List[VideoFrame], context: Dict[str, Any]) -> Optional[StreamEvent]:
        """
        Recognize game-specific events if applicable.
        
        Args:
            video_frames: Recent video frames
            context: Additional context (game type, etc.)
            
        Returns:
            StreamEvent if game event detected, None otherwise
            
        Validates: Requirement 5.6
        """
        # This is a placeholder for game-specific event detection
        # In a real implementation, this would use game-specific recognition
        
        game_type = context.get("game_type")
        if not game_type:
            return None
        
        # For now, return None as we don't have game-specific detection
        # This would be implemented based on specific game requirements
        return None
    
    async def detect_significant_event(
        self,
        video_frames: Optional[List[VideoFrame]] = None,
        audio_data: Optional[AudioData] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[StreamEvent]:
        """
        Detect significant events from video and audio inputs.
        
        Analyzes multimodal inputs and returns the most significant event detected.
        
        Args:
            video_frames: Optional list of recent video frames
            audio_data: Optional audio data
            context: Optional additional context
            
        Returns:
            Most significant StreamEvent detected, or None
            
        Validates: Requirements 5.1, 5.2, 5.6
        """
        detected_events = []
        
        # Detect visual changes
        if video_frames:
            visual_event = self.detect_visual_change(video_frames)
            if visual_event:
                detected_events.append(visual_event)
        
        # Detect emotional tone
        if audio_data:
            emotional_event = self.detect_emotional_tone(audio_data)
            if emotional_event:
                detected_events.append(emotional_event)
        
        # Detect game events
        if video_frames and context:
            game_event = self.detect_game_event(video_frames, context)
            if game_event:
                detected_events.append(game_event)
        
        # Return most significant event
        if detected_events:
            most_significant = max(detected_events, key=lambda e: self.score_event_significance(e))
            
            # Check minimum interval between events
            current_time = time.time()
            if current_time - self.last_event_time >= self.event_detection_config.min_event_interval:
                self.last_event_time = current_time
                self.add_event_to_buffer(most_significant)
                return most_significant
        
        return None

    
    # ========== Commentary Generation (Task 8.3) ==========
    
    def build_commentary_prompt(
        self,
        trigger: Dict[str, Any],
        include_history: bool = True
    ) -> str:
        """
        Build a prompt for commentary generation with personality configuration.
        
        Args:
            trigger: The event or message that triggered commentary
            include_history: Whether to include conversation history in prompt
            
        Returns:
            Formatted prompt string for Gemini Live API
            
        Validates: Requirements 5.3, 5.5, 5.7
        """
        # Build personality description
        personality_desc = self._build_personality_description()
        
        # Build context from recent events
        recent_events_str = self._format_recent_events()
        
        # Build conversation history
        history_str = ""
        if include_history:
            history_str = self._format_conversation_history()
        
        # Build trigger description
        trigger_type = trigger.get("type", "unknown")
        trigger_data = trigger.get("data", {})
        
        if trigger_type == "event":
            if isinstance(trigger_data, StreamEvent):
                trigger_desc = f"Stream Event: {trigger_data.description}"
            else:
                trigger_desc = f"Stream Event: {trigger_data.get('description', 'Unknown event')}"
        elif trigger_type == "chat":
            message = trigger_data
            if isinstance(message, ChatMessage):
                trigger_desc = f"Chat from {message.username}: {message.content}"
            else:
                trigger_desc = f"Chat from {message.get('username', 'Unknown')}: {message.get('content', '')}"
        else:
            trigger_desc = str(trigger_data)
        
        # Determine tone based on personality and trigger
        tone = self._determine_commentary_tone(trigger)
        
        # Build complete prompt
        prompt = f"""You are StreamBuddy, an AI co-host for a live stream.

{personality_desc}

Recent Stream Events:
{recent_events_str}

{history_str}

Current Trigger:
{trigger_desc}

Generate a natural, {self.personality_config.verbosity} response that:
- Acknowledges the current trigger
- Relates to recent stream context
- Uses a {tone} tone
- Keeps the response under 30 seconds of speech
- Sounds conversational and engaging, not robotic

Response:"""
        
        return prompt
    
    def _build_personality_description(self) -> str:
        """Build personality description for prompts."""
        return f"""Personality Traits:
- Humor Level: {self.personality_config.humor_level:.1f}/1.0 ({self._describe_level(self.personality_config.humor_level, 'humor')})
- Supportiveness: {self.personality_config.supportiveness:.1f}/1.0 ({self._describe_level(self.personality_config.supportiveness, 'supportive')})
- Playfulness: {self.personality_config.playfulness:.1f}/1.0 ({self._describe_level(self.personality_config.playfulness, 'playful')})
- Verbosity: {self.personality_config.verbosity}
- Response Style: {self.personality_config.chat_interaction_mode}"""
    
    def _describe_level(self, value: float, trait: str) -> str:
        """Describe a personality level in words."""
        if value < 0.3:
            return f"low {trait}"
        elif value < 0.7:
            return f"moderate {trait}"
        else:
            return f"high {trait}"

    
    def _format_recent_events(self, count: int = 5) -> str:
        """Format recent events for prompt."""
        if not self.recent_events:
            return "No recent events"
        
        events = list(self.recent_events)[-count:]
        formatted = []
        
        for event in events:
            time_ago = time.time() - event.timestamp
            formatted.append(
                f"- [{int(time_ago)}s ago] {event.event_type}: {event.description}"
            )
        
        return "\n".join(formatted) if formatted else "No recent events"
    
    def _format_conversation_history(self, count: int = 10) -> str:
        """Format conversation history for prompt."""
        if not self.conversation_history.interactions:
            return ""
        
        interactions = self.conversation_history.interactions[-count:]
        formatted = []
        
        for interaction in interactions:
            trigger = interaction.trigger
            response = interaction.response
            
            if isinstance(trigger, ChatMessage):
                trigger_str = f"{trigger.username}: {trigger.content}"
            elif isinstance(trigger, StreamEvent):
                trigger_str = f"Event: {trigger.description}"
            else:
                trigger_str = str(trigger)
            
            response_preview = response.text_content[:50] + "..." if len(response.text_content) > 50 else response.text_content
            
            formatted.append(f"- {trigger_str} → {response_preview}")
        
        if formatted:
            return f"Recent Conversation:\n" + "\n".join(formatted)
        else:
            return ""
    
    def _determine_commentary_tone(self, trigger: Dict[str, Any]) -> str:
        """
        Determine appropriate tone for commentary based on trigger and personality.
        
        Validates: Requirement 5.7
        """
        trigger_type = trigger.get("type", "unknown")
        
        # Base tone on personality configuration
        humor = self.personality_config.humor_level
        supportiveness = self.personality_config.supportiveness
        playfulness = self.personality_config.playfulness
        
        # Determine dominant trait
        if supportiveness > humor and supportiveness > playfulness:
            base_tone = "supportive"
        elif playfulness > humor and playfulness > supportiveness:
            base_tone = "playful"
        elif humor > supportiveness and humor > playfulness:
            base_tone = "humorous"
        else:
            base_tone = "balanced"
        
        # Adjust based on trigger type
        if trigger_type == "event":
            event_data = trigger.get("data", {})
            if isinstance(event_data, StreamEvent):
                if event_data.event_type == "emotional_shift":
                    emotion = event_data.related_data.get("emotion", "")
                    if emotion == "excitement":
                        return "enthusiastic and " + base_tone
                    elif emotion == "calm":
                        return "relaxed and " + base_tone
        
        return base_tone

    
    def should_trigger_commentary(self, event: StreamEvent) -> bool:
        """
        Determine if commentary should be triggered for an event.
        
        Checks event significance, timing, and personality configuration.
        
        Args:
            event: StreamEvent to evaluate
            
        Returns:
            True if commentary should be triggered, False otherwise
            
        Validates: Requirement 5.3
        """
        # Check if enough time has passed since last commentary
        current_time = time.time()
        time_since_last = current_time - self.last_commentary_time
        
        if time_since_last < self.commentary_config.min_commentary_interval:
            logger.debug(
                f"Skipping commentary: too soon since last "
                f"({time_since_last:.1f}s < {self.commentary_config.min_commentary_interval}s)"
            )
            return False
        
        # Check event significance
        significance = self.score_event_significance(event)
        
        # Adjust threshold based on response frequency setting
        frequency_thresholds = {
            "low": 0.8,
            "medium": 0.6,
            "high": 0.4
        }
        
        threshold = frequency_thresholds.get(
            self.personality_config.response_frequency,
            0.6
        )
        
        if significance < threshold:
            logger.debug(
                f"Skipping commentary: significance {significance:.2f} < threshold {threshold:.2f}"
            )
            return False
        
        return True
    
    async def trigger_commentary(self, event: StreamEvent) -> Optional[AIResponse]:
        """
        Trigger commentary generation for a significant event.
        
        Must trigger within 1 second of event detection.
        
        Args:
            event: StreamEvent that triggered commentary
            
        Returns:
            AIResponse if commentary generated, None otherwise
            
        Validates: Requirement 5.3
        """
        start_time = time.time()
        
        if not self.should_trigger_commentary(event):
            return None
        
        # Build commentary prompt
        trigger = {
            "type": "event",
            "data": event
        }
        
        prompt = self.build_commentary_prompt(trigger)
        
        # Check if we're within 1 second trigger window
        elapsed_ms = (time.time() - event.timestamp) * 1000
        if elapsed_ms > self.commentary_config.trigger_delay_ms:
            logger.warning(
                f"Commentary trigger delayed: {elapsed_ms:.0f}ms > "
                f"{self.commentary_config.trigger_delay_ms}ms"
            )
        
        # Generate response via Gemini client callback
        if self.gemini_client_callback:
            try:
                response = await self.gemini_client_callback(prompt)
                
                # Update last commentary time
                self.last_commentary_time = time.time()
                
                # Create AIResponse object
                ai_response = AIResponse(
                    response_id=str(uuid.uuid4()),
                    text_content=response.get("text", ""),
                    timestamp=time.time(),
                    latency_ms=int((time.time() - start_time) * 1000),
                    triggered_by=event.event_id,
                    audio_data=response.get("audio_data")
                )
                
                # Add to history
                interaction = Interaction(
                    timestamp=time.time(),
                    trigger=event,
                    response=ai_response
                )
                self.add_to_history(interaction)
                
                logger.info(
                    f"Commentary generated for event {event.event_id} "
                    f"(latency: {ai_response.latency_ms}ms)"
                )
                
                return ai_response
                
            except Exception as e:
                logger.error(f"Error generating commentary: {e}")
                return None
        else:
            logger.warning("No Gemini client callback configured")
            return None

    
    def check_contextual_relevance(self, trigger: Dict[str, Any]) -> bool:
        """
        Check if a trigger is contextually relevant using recent events and history.
        
        Args:
            trigger: Trigger to check for relevance
            
        Returns:
            True if contextually relevant, False otherwise
            
        Validates: Requirement 5.5
        """
        # Always relevant if we have no history
        if not self.recent_events and not self.conversation_history.interactions:
            return True
        
        trigger_type = trigger.get("type")
        
        # Chat messages are always relevant
        if trigger_type == "chat":
            return True
        
        # Events are relevant if they're different from recent events
        if trigger_type == "event":
            event_data = trigger.get("data")
            if isinstance(event_data, StreamEvent):
                # Check if similar event occurred recently
                recent_event_types = [e.event_type for e in list(self.recent_events)[-3:]]
                
                # If same type occurred very recently, might not be relevant
                if recent_event_types.count(event_data.event_type) >= 2:
                    return False
        
        return True
    
    # ========== Chat Message Processing (Task 8.4) ==========
    
    def should_respond_to_chat(self, message: ChatMessage) -> bool:
        """
        Determine if StreamBuddy should respond to a chat message.
        
        Decision based on priority and personality configuration.
        
        Args:
            message: ChatMessage to evaluate
            
        Returns:
            True if should respond, False otherwise
            
        Validates: Requirement 4.6
        """
        # Always respond to high priority messages
        if message.priority == Priority.HIGH:
            return True
        
        # Check chat interaction mode
        mode = self.personality_config.chat_interaction_mode
        
        if mode == "active":
            # Respond to all non-spam messages
            return not message.is_spam
        elif mode == "responsive":
            # Respond to high and medium priority
            return message.priority in [Priority.HIGH, Priority.MEDIUM]
        elif mode == "selective":
            # Only respond to high priority
            return message.priority == Priority.HIGH
        else:
            # Default to responsive
            return message.priority in [Priority.HIGH, Priority.MEDIUM]
    
    async def process_chat_message(self, message: ChatMessage) -> Optional[AIResponse]:
        """
        Process a chat message and generate response if appropriate.
        
        Args:
            message: ChatMessage to process
            
        Returns:
            AIResponse if response generated, None otherwise
            
        Validates: Requirement 4.6
        """
        start_time = time.time()
        
        # Check if we should respond
        if not self.should_respond_to_chat(message):
            logger.debug(f"Skipping response to chat message from {message.username}")
            return None
        
        # Build prompt with username reference
        trigger = {
            "type": "chat",
            "data": message
        }
        
        prompt = self.build_chat_response_prompt(message)
        
        # Generate response via Gemini client callback
        if self.gemini_client_callback:
            try:
                response = await self.gemini_client_callback(prompt)
                
                # Create AIResponse object
                ai_response = AIResponse(
                    response_id=str(uuid.uuid4()),
                    text_content=response.get("text", ""),
                    timestamp=time.time(),
                    latency_ms=int((time.time() - start_time) * 1000),
                    triggered_by=message.message_id,
                    audio_data=response.get("audio_data")
                )
                
                # Add to history
                interaction = Interaction(
                    timestamp=time.time(),
                    trigger=message,
                    response=ai_response
                )
                self.add_to_history(interaction)
                
                logger.info(
                    f"Response generated for chat message from {message.username} "
                    f"(latency: {ai_response.latency_ms}ms)"
                )
                
                return ai_response
                
            except Exception as e:
                logger.error(f"Error processing chat message: {e}")
                return None
        else:
            logger.warning("No Gemini client callback configured")
            return None

    
    def build_chat_response_prompt(self, message: ChatMessage) -> str:
        """
        Build prompt for chat message response with username reference.
        
        Args:
            message: ChatMessage to respond to
            
        Returns:
            Formatted prompt string
            
        Validates: Requirement 4.6
        """
        personality_desc = self._build_personality_description()
        recent_events_str = self._format_recent_events()
        history_str = self._format_conversation_history()
        
        prompt = f"""You are StreamBuddy, an AI co-host for a live stream.

{personality_desc}

Recent Stream Events:
{recent_events_str}

{history_str}

Chat Message from {message.username}:
"{message.content}"

Generate a natural, {self.personality_config.verbosity} response that:
- Addresses {message.username} by name
- Responds directly to their message
- Relates to recent stream context if relevant
- Keeps the response under 30 seconds of speech
- Sounds conversational and friendly

Response:"""
        
        return prompt
    
    # ========== Interruption Handling (Task 8.5) ==========
    
    async def handle_interruption(
        self,
        interrupted_response_id: str,
        interruption_input: str
    ) -> Optional[AIResponse]:
        """
        Handle an interruption and generate acknowledgment response.
        
        Args:
            interrupted_response_id: ID of the response that was interrupted
            interruption_input: The input that caused the interruption
            
        Returns:
            AIResponse with acknowledgment, or None
            
        Validates: Requirements 6.3, 6.5
        """
        start_time = time.time()
        
        logger.info(
            f"Processing interruption (interrupted response: {interrupted_response_id})"
        )
        
        # Build interruption context
        interruption_context = {
            "interrupted_response_id": interrupted_response_id,
            "interruption_input": interruption_input,
            "timestamp": time.time()
        }
        
        # Generate acknowledgment prompt
        prompt = self.build_interruption_acknowledgment_prompt(interruption_context)
        
        # Generate response via Gemini client callback
        if self.gemini_client_callback:
            try:
                response = await self.gemini_client_callback(prompt)
                
                # Create AIResponse object
                ai_response = AIResponse(
                    response_id=str(uuid.uuid4()),
                    text_content=response.get("text", ""),
                    timestamp=time.time(),
                    latency_ms=int((time.time() - start_time) * 1000),
                    triggered_by=f"interruption_{interrupted_response_id}",
                    audio_data=response.get("audio_data")
                )
                
                # Create event for interruption
                interruption_event = StreamEvent(
                    event_id=str(uuid.uuid4()),
                    event_type="other",
                    timestamp=time.time(),
                    description=f"Interruption handled: {interruption_input[:50]}",
                    significance=0.8,
                    related_data=interruption_context
                )
                
                # Add to history
                interaction = Interaction(
                    timestamp=time.time(),
                    trigger=interruption_event,
                    response=ai_response
                )
                self.add_to_history(interaction)
                
                logger.info(
                    f"Interruption acknowledgment generated "
                    f"(latency: {ai_response.latency_ms}ms)"
                )
                
                return ai_response
                
            except Exception as e:
                logger.error(f"Error handling interruption: {e}")
                return None
        else:
            logger.warning("No Gemini client callback configured")
            return None

    
    def build_interruption_acknowledgment_prompt(
        self,
        interruption_context: Dict[str, Any]
    ) -> str:
        """
        Build prompt for interruption acknowledgment.
        
        Args:
            interruption_context: Context about the interruption
            
        Returns:
            Formatted prompt string
            
        Validates: Requirements 6.3, 6.5
        """
        interruption_input = interruption_context.get("interruption_input", "")
        
        personality_desc = self._build_personality_description()
        
        prompt = f"""You are StreamBuddy, an AI co-host for a live stream.

{personality_desc}

You were speaking when the streamer interrupted you with:
"{interruption_input}"

Generate a brief, natural acknowledgment that:
- Acknowledges the interruption gracefully
- Addresses what the streamer said
- Transitions smoothly to the new topic
- Keeps the response very brief (under 10 seconds of speech)
- Sounds natural and conversational, not apologetic

Response:"""
        
        return prompt
    
    # ========== Personality Configuration (Task 8.6) ==========
    
    def apply_personality_config(self, config: PersonalityConfig) -> None:
        """
        Apply personality configuration to the Context Manager.
        
        Args:
            config: PersonalityConfig to apply
            
        Validates: Requirements 11.1, 11.2, 11.3, 11.4
        """
        if not isinstance(config, PersonalityConfig):
            raise ValueError("config must be a PersonalityConfig instance")
        
        self.personality_config = config
        self.config_update_time = time.time()
        
        logger.info(
            f"Personality configuration applied: "
            f"humor={config.humor_level:.1f}, "
            f"supportiveness={config.supportiveness:.1f}, "
            f"playfulness={config.playfulness:.1f}, "
            f"verbosity={config.verbosity}, "
            f"frequency={config.response_frequency}, "
            f"mode={config.chat_interaction_mode}"
        )
    
    def update_personality_config(self, **kwargs) -> None:
        """
        Update specific personality configuration parameters.
        
        Configuration updates should be applied within 10 seconds without restart.
        
        Args:
            **kwargs: Configuration parameters to update
            
        Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5
        """
        try:
            # Update the configuration
            self.personality_config.update(**kwargs)
            self.config_update_time = time.time()
            
            logger.info(f"Personality configuration updated: {kwargs}")
            
        except ValueError as e:
            logger.error(f"Invalid personality configuration update: {e}")
            raise
    
    def get_personality_config(self) -> PersonalityConfig:
        """
        Get current personality configuration.
        
        Returns:
            Current PersonalityConfig
        """
        return self.personality_config
    
    def get_config_update_time(self) -> Optional[float]:
        """
        Get timestamp of last configuration update.
        
        Returns:
            Unix timestamp of last update, or None if never updated
        """
        return self.config_update_time

    
    # ========== Utility Methods ==========
    
    def get_context_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current context state.
        
        Returns:
            Dictionary with context information
        """
        return {
            "session_duration": self.conversation_history.get_session_duration(),
            "total_interactions": self.conversation_history.total_interactions,
            "interactions_in_buffer": len(self.conversation_history.interactions),
            "recent_events_count": len(self.recent_events),
            "active_response_id": self.active_response_id,
            "last_commentary_time": self.last_commentary_time,
            "last_event_time": self.last_event_time,
            "personality_config": {
                "humor_level": self.personality_config.humor_level,
                "supportiveness": self.personality_config.supportiveness,
                "playfulness": self.personality_config.playfulness,
                "verbosity": self.personality_config.verbosity,
                "response_frequency": self.personality_config.response_frequency,
                "chat_interaction_mode": self.personality_config.chat_interaction_mode
            },
            "config_update_time": self.config_update_time
        }
    
    def set_active_response(self, response_id: str) -> None:
        """
        Set the currently active response ID.
        
        Args:
            response_id: ID of the active response
        """
        self.active_response_id = response_id
        logger.debug(f"Active response set to: {response_id}")
    
    def clear_active_response(self) -> None:
        """Clear the currently active response ID."""
        self.active_response_id = None
        logger.debug("Active response cleared")
    
    def get_active_response_id(self) -> Optional[str]:
        """
        Get the currently active response ID.
        
        Returns:
            Active response ID or None
        """
        return self.active_response_id
    
    def reset_session(self) -> None:
        """
        Reset the session state (for testing or new streaming session).
        
        Clears conversation history and recent events.
        """
        self.conversation_history = ConversationHistory(session_start=time.time())
        self.recent_events.clear()
        self.active_response_id = None
        self.last_commentary_time = 0.0
        self.last_event_time = 0.0
        
        logger.info("Context Manager session reset")
