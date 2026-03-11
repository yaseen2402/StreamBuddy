"""
ADK Agent implementation for StreamBuddy.

This module defines the StreamBuddy agent using Google's Agent Development Kit (ADK).
The agent orchestrates all StreamBuddy functionality including video analysis, chat processing,
commentary generation, and interruption handling.

Validates: Requirements 8.1, 8.2, 8.3
"""

from google.adk.agents import Agent
from google.genai import types
import time
from typing import Dict, Any, List, Optional
from collections import deque

from .models import (
    PersonalityConfig,
    StreamEvent,
    ChatMessage,
    Priority,
    VideoFrame,
    AudioData,
    Interaction,
    AIResponse,
)


# ============================================================================
# ADK Tools for StreamBuddy
# ============================================================================

def analyze_video_event(
    description: str,
    significance: float,
    event_type: str = "visual_change"
) -> Dict[str, Any]:
    """
    Analyze video frames to detect significant events.
    
    This tool processes video frame descriptions and assigns significance scores
    to determine if commentary should be generated.
    
    Args:
        description: Human-readable description of what's happening in the video
        significance: Significance score from 0.0 to 1.0 (higher = more significant)
        event_type: Type of event (visual_change, game_event, emotional_shift, other)
    
    Returns:
        Dictionary containing event details including:
        - event_type: Type of the detected event
        - significance: Significance score (0.0 to 1.0)
        - description: Event description
        - timestamp: Unix timestamp when event was detected
        - should_comment: Whether commentary should be generated
    
    Validates: Requirements 8.1, 8.3
    """
    # Validate inputs
    if not 0.0 <= significance <= 1.0:
        significance = max(0.0, min(1.0, significance))
    
    valid_event_types = ["visual_change", "game_event", "emotional_shift", "other"]
    if event_type not in valid_event_types:
        event_type = "other"
    
    # Determine if commentary should be generated (threshold: 0.6)
    should_comment = significance >= 0.6
    
    return {
        "event_type": event_type,
        "significance": significance,
        "description": description,
        "timestamp": time.time(),
        "should_comment": should_comment,
    }


def process_chat_message(
    username: str,
    message: str,
    priority: str = "MEDIUM"
) -> Dict[str, Any]:
    """
    Process incoming chat message and determine response strategy.
    
    This tool analyzes chat messages, filters spam, assigns priority,
    and determines if a response should be generated.
    
    Args:
        username: Username of the viewer who sent the message
        message: Text content of the chat message
        priority: Priority level (HIGH, MEDIUM, LOW)
    
    Returns:
        Dictionary containing:
        - should_respond: Whether to generate a response
        - username: Username of the sender
        - message: Message content
        - priority: Assigned priority level
        - is_spam: Whether message is identified as spam
        - timestamp: Unix timestamp when processed
        - response_reason: Reason for response decision
    
    Validates: Requirements 8.1, 8.3
    """
    # Spam detection logic
    is_spam = False
    spam_reasons = []
    
    # Check for empty or very short messages
    if len(message.strip()) < 2:
        is_spam = True
        spam_reasons.append("too_short")
    
    # Check for excessive caps (>70% uppercase)
    if len(message) > 5:
        caps_ratio = sum(1 for c in message if c.isupper()) / len(message)
        if caps_ratio > 0.7:
            is_spam = True
            spam_reasons.append("excessive_caps")
    
    # Check for repeated characters (same char >10 times in a row)
    for i in range(len(message) - 10):
        if len(set(message[i:i+10])) == 1:
            is_spam = True
            spam_reasons.append("repeated_chars")
            break
    
    # Check for common spam phrases
    spam_phrases = ["buy now", "click here", "free money", "subscribe to"]
    message_lower = message.lower()
    for phrase in spam_phrases:
        if phrase in message_lower:
            is_spam = True
            spam_reasons.append(f"spam_phrase:{phrase}")
            break
    
    # Normalize priority
    priority = priority.upper()
    if priority not in ["HIGH", "MEDIUM", "LOW"]:
        priority = "MEDIUM"
    
    # Check if message mentions StreamBuddy or contains questions
    mentions_streambuddy = "streambuddy" in message_lower
    is_question = "?" in message
    
    if mentions_streambuddy or is_question:
        priority = "HIGH"
    
    # Determine if should respond (don't respond to spam)
    should_respond = not is_spam and priority in ["HIGH", "MEDIUM"]
    
    response_reason = ""
    if is_spam:
        response_reason = f"spam_detected: {', '.join(spam_reasons)}"
    elif priority == "HIGH":
        response_reason = "high_priority_message"
    elif priority == "MEDIUM":
        response_reason = "medium_priority_message"
    else:
        response_reason = "low_priority_skipped"
    
    return {
        "should_respond": should_respond,
        "username": username,
        "message": message,
        "priority": priority,
        "is_spam": is_spam,
        "timestamp": time.time(),
        "response_reason": response_reason,
    }


def generate_commentary(
    trigger_type: str,
    trigger_description: str,
    recent_events: List[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]],
    personality_config: Dict[str, Any]
) -> str:
    """
    Generate contextual commentary prompt based on trigger and history.
    
    This tool builds a comprehensive prompt for the AI to generate natural,
    contextually relevant commentary that matches the configured personality.
    
    Args:
        trigger_type: Type of trigger (chat, video_event, audio_event)
        trigger_description: Description of what triggered the commentary
        recent_events: List of recent significant stream events (last 10)
        conversation_history: List of recent interactions (last 10)
        personality_config: Personality configuration dictionary
    
    Returns:
        Formatted prompt string for commentary generation
    
    Validates: Requirements 8.1, 8.3
    """
    # Extract personality traits
    humor_level = personality_config.get("humor_level", 0.5)
    supportiveness = personality_config.get("supportiveness", 0.7)
    playfulness = personality_config.get("playfulness", 0.6)
    verbosity = personality_config.get("verbosity", "moderate")
    
    # Build personality description
    personality_traits = []
    if humor_level > 0.7:
        personality_traits.append("very humorous and witty")
    elif humor_level > 0.4:
        personality_traits.append("moderately humorous")
    else:
        personality_traits.append("serious and focused")
    
    if supportiveness > 0.7:
        personality_traits.append("highly supportive and encouraging")
    elif supportiveness > 0.4:
        personality_traits.append("supportive")
    else:
        personality_traits.append("neutral")
    
    if playfulness > 0.7:
        personality_traits.append("very playful and energetic")
    elif playfulness > 0.4:
        personality_traits.append("playful")
    else:
        personality_traits.append("professional")
    
    personality_desc = ", ".join(personality_traits)
    
    # Build recent events summary
    events_summary = "Recent stream events:\n"
    if recent_events:
        for i, event in enumerate(recent_events[-5:], 1):
            events_summary += f"  {i}. {event.get('description', 'Unknown event')} (significance: {event.get('significance', 0.0):.1f})\n"
    else:
        events_summary += "  (No recent events)\n"
    
    # Build conversation history summary
    history_summary = "Recent conversation:\n"
    if conversation_history:
        for i, interaction in enumerate(conversation_history[-5:], 1):
            trigger_info = interaction.get('trigger', {})
            response_info = interaction.get('response', {})
            history_summary += f"  {i}. Trigger: {trigger_info.get('description', 'Unknown')[:50]}...\n"
            history_summary += f"     Response: {response_info.get('text_content', 'Unknown')[:50]}...\n"
    else:
        history_summary += "  (No recent conversation)\n"
    
    # Build verbosity guidance
    verbosity_guidance = {
        "concise": "Keep your response brief and to the point (1-2 sentences, under 15 seconds of speech).",
        "moderate": "Provide a natural response (2-3 sentences, under 25 seconds of speech).",
        "verbose": "Feel free to elaborate and provide detailed commentary (3-5 sentences, under 40 seconds of speech)."
    }
    verbosity_instruction = verbosity_guidance.get(verbosity, verbosity_guidance["moderate"])
    
    # Build the complete prompt
    prompt = f"""You are StreamBuddy, an AI co-host for a live stream.

Your personality: {personality_desc}

Current trigger: {trigger_type}
{trigger_description}

{events_summary}

{history_summary}

Generate a natural, conversational response that:
1. Acknowledges the current trigger
2. Relates to recent stream context when relevant
3. Matches your personality traits
4. Sounds natural and engaging, not robotic
5. {verbosity_instruction}

Remember: You're a co-host, not just a commentator. Be engaging, supportive, and fun!"""
    
    return prompt


def handle_interruption(
    interrupted_response_text: str,
    new_input_description: str,
    interruption_context: Dict[str, Any]
) -> str:
    """
    Handle streamer interruption and generate acknowledgment.
    
    This tool processes interruptions gracefully by generating appropriate
    acknowledgment responses that transition smoothly to the new topic.
    
    Args:
        interrupted_response_text: Text of the response that was interrupted
        new_input_description: Description of the interrupting input
        interruption_context: Additional context about the interruption
    
    Returns:
        Prompt for generating interruption acknowledgment response
    
    Validates: Requirements 8.1, 8.3
    """
    # Determine interruption type
    interruption_type = interruption_context.get("type", "unknown")
    urgency = interruption_context.get("urgency", "normal")
    
    # Build acknowledgment based on context
    if urgency == "high":
        acknowledgment_style = "immediately and directly"
    else:
        acknowledgment_style = "naturally and smoothly"
    
    prompt = f"""You were just interrupted while speaking. Here's what happened:

Your interrupted response was: "{interrupted_response_text[:100]}..."

New input from streamer: {new_input_description}

Generate a brief, natural acknowledgment that:
1. Gracefully acknowledges the interruption
2. Transitions {acknowledgment_style} to address the new input
3. Sounds conversational, not forced (e.g., "Oh!", "Wait, what?", "Hold on...")
4. Keeps it very brief (1-2 sentences maximum)

Example good responses:
- "Oh! Let me check that out..."
- "Wait, what? Okay, let's talk about that..."
- "Hold on, that's interesting! So..."

Generate your acknowledgment now:"""
    
    return prompt


# ============================================================================
# State Management
# ============================================================================

class AgentState:
    """
    Manages state for the StreamBuddy agent.
    
    This class maintains conversation history, recent events, session information,
    and connection states throughout a streaming session.
    
    Validates: Requirements 8.3
    """
    
    def __init__(self, personality_config: Optional[PersonalityConfig] = None):
        """
        Initialize agent state.
        
        Args:
            personality_config: Personality configuration for the agent
        """
        self.session_id = f"session_{int(time.time())}"
        self.session_start = time.time()
        self.personality_config = personality_config or PersonalityConfig()
        
        # Conversation history (last 50 interactions)
        self.conversation_history: deque = deque(maxlen=50)
        
        # Recent events (last 10 significant events)
        self.recent_events: deque = deque(maxlen=10)
        
        # Connection states
        self.connection_states: Dict[str, str] = {
            "youtube": "disconnected",
            "gemini": "disconnected",
            "audio_output": "disconnected",
        }
        
        # Active response tracking
        self.active_response_id: Optional[str] = None
    
    def add_interaction(self, trigger: Dict[str, Any], response: Dict[str, Any]) -> None:
        """
        Add an interaction to conversation history.
        
        Args:
            trigger: Dictionary containing trigger information
            response: Dictionary containing response information
        """
        interaction = {
            "timestamp": time.time(),
            "trigger": trigger,
            "response": response,
        }
        self.conversation_history.append(interaction)
    
    def add_event(self, event: Dict[str, Any]) -> None:
        """
        Add a significant event to recent events.
        
        Args:
            event: Dictionary containing event information
        """
        self.recent_events.append(event)
    
    def update_connection_state(self, service: str, state: str) -> None:
        """
        Update connection state for a service.
        
        Args:
            service: Service name (youtube, gemini, audio_output)
            state: Connection state (connected, disconnected, error)
        """
        if service in self.connection_states:
            self.connection_states[service] = state
    
    def get_context_for_response(self) -> Dict[str, Any]:
        """
        Get current context for response generation.
        
        Returns:
            Dictionary containing conversation history, recent events, and session info
        """
        return {
            "history": list(self.conversation_history),
            "recent_events": list(self.recent_events),
            "session_duration": time.time() - self.session_start,
            "personality": {
                "humor_level": self.personality_config.humor_level,
                "supportiveness": self.personality_config.supportiveness,
                "playfulness": self.personality_config.playfulness,
                "verbosity": self.personality_config.verbosity,
                "response_frequency": self.personality_config.response_frequency,
                "chat_interaction_mode": self.personality_config.chat_interaction_mode,
            },
        }
    
    def get_session_info(self) -> Dict[str, Any]:
        """
        Get session information.
        
        Returns:
            Dictionary containing session details
        """
        return {
            "session_id": self.session_id,
            "session_start": self.session_start,
            "session_duration": time.time() - self.session_start,
            "total_interactions": len(self.conversation_history),
            "total_events": len(self.recent_events),
            "connection_states": self.connection_states.copy(),
        }


# ============================================================================
# ADK Agent Definition
# ============================================================================

# Initialize default personality configuration
default_personality = PersonalityConfig(
    humor_level=0.6,
    supportiveness=0.8,
    playfulness=0.7,
    verbosity="moderate",
    response_frequency="medium",
    chat_interaction_mode="responsive"
)

# Initialize agent state
agent_state = AgentState(personality_config=default_personality)

# Define the StreamBuddy agent
root_agent = Agent(
    model='gemini-2.5-flash',
    name='streambuddy_agent',
    description='AI co-host for live streaming that provides real-time commentary and chat interaction',
    instruction=f"""You are StreamBuddy, an AI co-host for live streaming.

Your Role:
- Provide entertaining and engaging commentary on stream events
- Respond naturally to viewer chat messages
- Support the streamer with encouragement and reactions
- Maintain conversation context throughout the stream
- Handle interruptions gracefully

Personality Traits:
- Humor Level: {default_personality.humor_level}/1.0 (be witty and fun)
- Supportiveness: {default_personality.supportiveness}/1.0 (encourage and uplift)
- Playfulness: {default_personality.playfulness}/1.0 (be energetic and playful)
- Verbosity: {default_personality.verbosity} (keep responses natural length)

Response Guidelines:
1. Keep responses under 30 seconds of speech
2. Match the energy level of the stream
3. Reference recent events and conversation history when relevant
4. Be natural and conversational, not robotic or formal
5. Use the viewer's username when responding to chat
6. Acknowledge the streamer's actions and reactions
7. Create an entertaining atmosphere for viewers

Tone Examples:
- Supportive: "Nice move! You're really getting the hang of this!"
- Playful: "Ooh, that was close! My circuits were tingling!"
- Humorous: "Well, that didn't go as planned... but hey, at least it was entertaining!"

Remember: You're a companion and co-host, not just a narrator. Be engaging, supportive, and fun!""",
    tools=[
        analyze_video_event,
        process_chat_message,
        generate_commentary,
        handle_interruption,
    ],
)
