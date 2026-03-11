# Implementation Plan: StreamBuddy

## Overview

StreamBuddy is a real-time AI companion for live streamers that processes multimodal inputs (video, audio, chat) from YouTube Live and provides natural voice responses through Google's Gemini Live API. The implementation uses Google's Agent Development Kit (ADK) as the core framework, with the agent defined in `agent.py` and supporting infrastructure in separate modules.

This plan breaks down the implementation into sequential, incremental tasks that build upon each other, ensuring continuous integration and early validation of core functionality.

**Key Architecture Notes:**
- The ADK agent (in `agent.py`) is the central intelligence, with tools for video analysis, chat processing, commentary generation, and interruption handling
- Supporting services (Stream Ingestion, Audio Output, etc.) are implemented as separate modules that feed data to and receive responses from the ADK agent
- The ADK CLI (`adk run`) and Web UI (`adk web`) are used for development and testing
- Production deployment wraps the ADK agent in a FastAPI application for Cloud Run

## Tasks

- [ ] 1. Project setup and infrastructure foundation
  - [x] 1.1 Create ADK agent project
    - Install google-adk: `pip install google-adk`
    - Create agent project: `adk create streambuddy_agent`
    - Explore generated structure (agent.py, .env, __init__.py)
    - _Requirements: 8.1_
  
  - [x] 1.2 Configure API credentials
    - Obtain Gemini API key from Google AI Studio
    - Obtain YouTube Live API OAuth credentials from Google Cloud Console
    - Add GOOGLE_API_KEY to .env file
    - Add YOUTUBE_OAUTH_TOKEN to .env file
    - _Requirements: 13.1, 13.2_
  
  - [x] 1.3 Set up additional dependencies
    - Install google-cloud-logging, google-cloud-monitoring, google-cloud-secret-manager
    - Install pytest, hypothesis for testing
    - Install youtube-api-client, opencv-python for stream processing
    - Create requirements.txt with all dependencies
    - _Requirements: 7.1, 7.2, 7.3_
  
  - [x] 1.4 Configure Google Cloud Platform
    - Create GCP project and enable required APIs (Gemini, YouTube Live, Cloud Run, Secret Manager, Logging, Monitoring)
    - Set up service account with appropriate permissions
    - Store credentials in Secret Manager
    - _Requirements: 7.1, 7.2, 7.3_
  
  - [x] 1.5 Create deployment infrastructure
    - Create Dockerfile for Cloud Run deployment
    - Set up .gitignore and basic project documentation
    - _Requirements: 7.1, 7.2_

- [ ] 2. Core data models and configuration
  - [x] 2.1 Implement data model classes
    - Create VideoFrame, AudioData, ChatMessage, StreamEvent, AIResponse, ConversationHistory, PersonalityConfig dataclasses
    - Implement validation logic for each data model
    - _Requirements: 11.1, 11.2, 11.3_
  
  - [ ]* 2.2 Write unit tests for data models
    - Test data model initialization and validation
    - Test edge cases (empty fields, invalid values, boundary conditions)
    - _Requirements: 11.1, 11.2, 11.3_

- [ ] 3. Google Cloud Platform integration layer
  - [x] 3.1 Implement Secret Manager integration
    - Create secret retrieval functions for YouTube OAuth token, Gemini API key, and stream mixer config
    - Implement credential caching with refresh logic
    - _Requirements: 13.1, 13.2_
  
  - [x] 3.2 Implement Cloud Logging integration
    - Create structured logging utility with component tagging
    - Implement log level configuration (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - _Requirements: 7.6, 10.2, 10.5_
  
  - [x] 3.3 Implement Cloud Monitoring integration
    - Create metric recording functions for latency, API duration, error rates
    - Implement metric batching for efficient uploads
    - _Requirements: 10.1, 10.6_
  
  - [ ]* 3.4 Write unit tests for GCP integration
    - Test secret retrieval with mocked Secret Manager
    - Test logging output format and structure
    - Test metric recording and batching
    - _Requirements: 13.2, 10.1, 10.2_


- [ ] 4. Stream Ingestion Service implementation
  - [x] 4.1 Implement YouTube Live API connection
    - Create connection establishment with OAuth 2.0 authentication
    - Implement exponential backoff retry logic (5 attempts: 1s, 2s, 4s, 8s, 16s)
    - Implement connection state tracking and logging
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 13.1, 13.3_
  
  - [x] 4.2 Implement video stream capture
    - Create video frame capture at configurable frame rate (default 1 fps)
    - Implement frame forwarding to Gemini Live Client with < 100ms latency
    - Add frame compression and resizing (max 1280px dimension, 85% JPEG quality)
    - _Requirements: 1.1, 1.6_
  
  - [x] 4.3 Implement audio stream capture
    - Create audio chunk capture with 500ms maximum buffering
    - Implement audio forwarding to Gemini Live Client with < 500ms latency
    - _Requirements: 1.2, 1.7_
  
  - [x] 4.4 Implement chat stream capture
    - Create chat message stream listener
    - Implement disconnection detection and reconnection logic
    - _Requirements: 1.3, 1.5_
  
  - [ ]* 4.5 Write property test for connection retry
    - **Property 2: Connection Retry with Exponential Backoff**
    - **Validates: Requirements 1.4**
    - Test that connection failures trigger exactly 5 retries with exponential delays
  
  - [ ]* 4.6 Write property test for video frame rate
    - **Property 4: Video Frame Rate Constraint**
    - **Validates: Requirements 1.6**
    - Test that video frames are forwarded at >= 1 fps for any stream duration
  
  - [ ]* 4.7 Write property test for audio buffering latency
    - **Property 5: Audio Buffering Latency**
    - **Validates: Requirements 1.7**
    - Test that audio chunks are forwarded within 500ms
  
  - [ ]* 4.8 Write unit tests for Stream Ingestion Service
    - Test initialization with various configurations
    - Test disconnection handling and logging
    - Test partial stream availability (e.g., chat only)
    - _Requirements: 1.4, 1.5, 12.2_

- [ ] 5. Checkpoint - Verify Stream Ingestion Service
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 6. Gemini Live Client implementation
  - [x] 6.1 Implement Gemini Live API session management
    - Create session establishment with API key authentication
    - Implement persistent connection maintenance throughout streaming session
    - Implement session reconnection logic on connection loss
    - _Requirements: 2.1, 2.6, 13.3_
  
  - [x] 6.2 Implement multimodal data forwarding
    - Create methods to send video frames to Gemini Live API
    - Create methods to send audio chunks to Gemini Live API
    - Create methods to send text messages (chat) to Gemini Live API
    - _Requirements: 2.2, 2.3, 2.4_
  
  - [x] 6.3 Implement response receiving and forwarding
    - Create async response receiver from Gemini Live API
    - Implement response forwarding to Audio Output Service within 100ms
    - _Requirements: 2.5_
  
  - [ ] 6.4 Implement rate limit handling
    - Create rate limit detection logic
    - Implement request throttling to stay within quota limits
    - Add circuit breaker pattern for API failures
    - _Requirements: 2.7, 12.1_
  
  - [ ]* 6.5 Write property test for API response forwarding
    - **Property 7: API Response Forwarding Latency**
    - **Validates: Requirements 2.5**
    - Test that responses are forwarded within 100ms of API response
  
  - [ ]* 6.6 Write property test for persistent connection
    - **Property 8: Persistent API Connection**
    - **Validates: Requirements 2.6**
    - Test that connection remains active from session start to end
  
  - [ ]* 6.7 Write property test for rate limit throttling
    - **Property 9: Rate Limit Throttling**
    - **Validates: Requirements 2.7**
    - Test that requests are throttled when approaching rate limits
  
  - [ ]* 6.8 Write unit tests for Gemini Live Client
    - Test session establishment with valid/invalid credentials
    - Test API error retry logic (up to 3 attempts)
    - Test circuit breaker behavior
    - _Requirements: 2.1, 12.1_

- [x] 7. Chat Monitor implementation
  - [x] 7.1 Implement chat message parsing
    - Create parser to extract username and content from raw messages
    - Implement structured ChatMessage creation
    - _Requirements: 4.1, 4.2_
  
  - [x] 7.2 Implement spam filtering
    - Create spam detection for high message rate (> 5 per second from same user)
    - Implement content pattern matching (excessive caps, repeated characters, spam phrases)
    - Add minimum message length validation (2 characters)
    - _Requirements: 4.4, 13.6_
  
  - [x] 7.3 Implement message prioritization
    - Create priority detection for messages mentioning "StreamBuddy" or containing questions
    - Implement priority levels (HIGH, MEDIUM, LOW)
    - _Requirements: 4.5_
  
  - [x] 7.4 Implement message forwarding
    - Create forwarding to Context Manager within 200ms
    - Implement message queue for high-throughput scenarios
    - _Requirements: 4.3_
  
  - [ ]* 7.5 Write property test for chat message parsing
    - **Property 13: Chat Message Parsing**
    - **Validates: Requirements 4.1, 4.2**
    - Test that all valid chat messages are parsed with username and content
  
  - [ ]* 7.6 Write property test for spam filtering
    - **Property 15: Spam Message Filtering**
    - **Validates: Requirements 4.4**
    - Test that messages matching spam patterns are filtered
  
  - [ ]* 7.7 Write property test for message forwarding latency
    - **Property 14: Chat Message Forwarding Latency**
    - **Validates: Requirements 4.3**
    - Test that messages are forwarded within 200ms
  
  - [ ]* 7.8 Write unit tests for Chat Monitor
    - Test empty message handling
    - Test extremely long messages (> 1000 characters)
    - Test malformed message inputs
    - _Requirements: 4.1, 4.4, 13.6_


- [x] 8. Context Manager implementation
  - [x] 8.1 Implement conversation history management
    - Create sliding window storage for last 50 interactions
    - Implement recent events buffer for last 10 significant events
    - Create methods to add and retrieve history
    - _Requirements: 5.4_
  
  - [x] 8.2 Implement event detection
    - Create video frame analysis for significant visual changes
    - Implement audio analysis for emotional tone detection
    - Create event significance scoring (0.0 to 1.0)
    - Add game-specific event recognition (if applicable)
    - _Requirements: 5.1, 5.2, 5.6_
  
  - [x] 8.3 Implement commentary generation
    - Create prompt builder with personality configuration
    - Implement commentary trigger logic (within 1 second of event detection)
    - Add contextual relevance checking using recent events and history
    - Implement tone variation (supportive, playful, humorous)
    - _Requirements: 5.3, 5.5, 5.7_
  
  - [x] 8.4 Implement chat message processing
    - Create response decision logic based on priority and personality config
    - Implement username reference in generated responses
    - _Requirements: 4.6_
  
  - [x] 8.5 Implement interruption handling
    - Create interruption context processing
    - Implement acknowledgment response generation
    - _Requirements: 6.3, 6.5_
  
  - [x] 8.6 Implement personality configuration
    - Create configuration application for humor, supportiveness, playfulness
    - Implement response frequency and verbosity settings
    - Add chat interaction mode configuration (selective, responsive, active)
    - Implement configuration update within 10 seconds without restart
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_
  
  - [ ]* 8.7 Write property test for event detection latency
    - **Property 19: Commentary Generation Latency**
    - **Validates: Requirements 5.3**
    - Test that commentary is triggered within 1 second of event detection
  
  - [ ]* 8.8 Write property test for conversation history maintenance
    - **Property 20: Conversation History Maintenance**
    - **Validates: Requirements 5.4**
    - Test that all interactions are stored and available for context
  
  - [ ]* 8.9 Write property test for configuration updates
    - **Property 36: Configuration Update Application**
    - **Validates: Requirements 11.5**
    - Test that configuration changes apply within 10 seconds
  
  - [ ]* 8.10 Write unit tests for Context Manager
    - Test history sliding window behavior (max 50 items)
    - Test event buffer behavior (max 10 items)
    - Test personality configuration validation
    - Test context persistence during temporary failures (< 30 seconds)
    - _Requirements: 5.4, 11.1, 12.6_


- [ ] 10. Interruption Handler implementation
  - [x] 10.1 Implement audio monitoring during response
    - Create continuous audio input monitoring during AI response playback
    - Implement voice activity detection (VAD) for speech detection
    - _Requirements: 6.1_
  
  - [x] 10.2 Implement interruption detection
    - Create speech detection with 300ms sustained speech requirement
    - Implement false positive prevention logic
    - _Requirements: 6.1, 6.2_
  
  - [x] 10.3 Implement interruption signaling
    - Create signal to Audio Output Service to stop playback within 300ms
    - Implement signal to Context Manager with interruption context
    - Create interrupted response discarding logic
    - _Requirements: 6.2, 6.3, 6.4_
  
  - [ ]* 10.4 Write property test for audio monitoring
    - **Property 21: Audio Monitoring During Response**
    - **Validates: Requirements 6.1**
    - Test that audio is continuously monitored during active response
  
  - [ ]* 10.5 Write property test for interruption response time
    - **Property 22: Interruption Response Time**
    - **Validates: Requirements 6.2**
    - Test that audio stops within 300ms of speech detection
  
  - [ ]* 10.6 Write property test for interrupted response discarding
    - **Property 24: Interrupted Response Discarding**
    - **Validates: Requirements 6.4**
    - Test that remaining audio is discarded after interruption
  
  - [ ]* 10.7 Write unit tests for Interruption Handler
    - Test false positive prevention (brief noises)
    - Test interruption during various response stages
    - _Requirements: 6.1, 6.2, 6.4_

- [x] 11. Audio Output Service implementation
  - [x] 11.1 Implement audio connection initialization
    - Create audio mixer connection setup
    - Implement connection reinitialization on failure
    - _Requirements: 3.3, 12.3_
  
  - [x] 11.2 Implement response queue management
    - Create sequential response queue with priority support
    - Implement maximum queue size (5 responses, drop oldest)
    - Add queue processing with < 50ms overhead
    - _Requirements: 3.4_
  
  - [x] 11.3 Implement audio playback
    - Create audio streaming playback (24kHz, PCM/Opus, mono)
    - Implement playback state tracking
    - Add playback stop functionality for interruptions
    - _Requirements: 3.1, 3.3_
  
  - [x] 11.4 Implement voice consistency
    - Configure Gemini Live API voice settings (Puck voice)
    - Ensure consistent voice characteristics throughout session
    - _Requirements: 3.5_
  
  - [ ]* 11.5 Write property test for end-to-end latency
    - **Property 10: End-to-End Audio Response Latency**
    - **Validates: Requirements 3.2**
    - Test that audio is delivered within 2 seconds of input reception
  
  - [ ]* 11.6 Write property test for sequential queuing
    - **Property 12: Sequential Response Queuing**
    - **Validates: Requirements 3.4**
    - Test that multiple simultaneous responses are delivered sequentially without overlap
  
  - [ ]* 11.7 Write unit tests for Audio Output Service
    - Test audio connection initialization and reinitialization
    - Test queue overflow behavior (drop oldest)
    - Test playback error handling
    - Test audio format conversion
    - _Requirements: 3.3, 3.4, 12.3_


- [ ] 12. ADK Agent implementation (in agent.py)
  - [x] 12.1 Define ADK tools for StreamBuddy
    - Implement analyze_video_event tool with significance scoring
    - Implement process_chat_message tool with priority logic and spam filtering
    - Implement generate_commentary tool with prompt building and personality config
    - Implement handle_interruption tool with acknowledgment generation
    - Each tool should be a Python function with proper docstring and type hints
    - _Requirements: 8.1, 8.3_
  
  - [x] 12.2 Configure root_agent in agent.py
    - Update root_agent definition with model='gemini-3.0-flash'
    - Set agent name='streambuddy_agent'
    - Write comprehensive instruction for StreamBuddy's personality and behavior
    - Add all tools to the tools list
    - Configure response modalities for audio output
    - _Requirements: 8.1, 8.2, 8.3_
  
  - [x] 12.3 Implement state management within agent
    - Create conversation history tracking (last 50 interactions)
    - Implement recent events buffer (last 10 significant events)
    - Add session state tracking (session_id, start_time, personality_config)
    - Implement connection state tracking for external services
    - _Requirements: 8.3_
  
  - [-] 12.4 Test agent with ADK CLI
    - Run agent with `adk run streambuddy_agent` to test basic functionality
    - Test each tool individually through CLI prompts
    - Verify agent responds appropriately to different inputs
    - _Requirements: 8.1, 8.2_
  
  - [ ] 12.5 Test agent with ADK Web UI
    - Start web interface with `adk web --port 8000`
    - Test agent interactions through web UI
    - Verify tool execution and response generation
    - Test personality configuration variations
    - _Requirements: 8.1, 8.2, 8.3_
  
  - [ ]* 12.6 Write unit tests for ADK Agent
    - Test agent initialization with various personality configs
    - Test tool method execution
    - Test state management and history tracking
    - Test session lifecycle
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 13. System integration and orchestration
  - [x] 13.1 Create main application wrapper (app.py)
    - Create FastAPI application separate from ADK agent
    - Implement streaming session management that calls ADK agent
    - Create endpoints for starting/stopping streaming sessions
    - Wire Stream Ingestion Service to feed data to ADK agent tools
    - _Requirements: 1.6, 1.7, 4.3_
  
  - [x] 13.2 Integrate Stream Ingestion with ADK agent
    - Connect video stream output to agent's analyze_video_event tool
    - Connect audio stream output to agent's audio processing
    - Connect chat stream output to agent's process_chat_message tool
    - Implement async data flow from ingestion to agent
    - _Requirements: 1.6, 1.7, 4.3_
  
  - [x] 13.3 Integrate Audio Output with ADK agent responses
    - Connect agent's audio responses to Audio Output Service
    - Implement response streaming from agent to audio mixer
    - Handle response queuing and playback
    - _Requirements: 3.2_
  
  - [x] 13.4 Integrate Interruption Handler with ADK agent
    - Connect interruption signals to stop agent response generation
    - Feed interruption context back to agent's handle_interruption tool
    - Implement graceful response cancellation
    - _Requirements: 6.2, 6.3_
  
  - [x] 13.5 Implement health and readiness endpoints
    - Create /health endpoint for liveness probe
    - Create /ready endpoint with component checks (YouTube connection, Gemini connection, audio output)
    - Add graceful degradation for component failures
    - _Requirements: 7.5, 12.4_
  
  - [ ]* 13.6 Write integration tests
    - Test end-to-end flow from chat message to audio response
    - Test end-to-end flow from video event to commentary
    - Test interruption flow
    - Test graceful degradation scenarios
    - _Requirements: 9.1, 9.2, 12.4_


- [x] 15. Performance optimization implementation
  - [x] 15.1 Implement pipeline parallelization
    - Create async parallel processing for video, audio, and chat
    - Implement result combination logic
    - _Requirements: 9.1, 9.2_
  
  - [x] 15.2 Implement adaptive frame rate controller
    - Create dynamic frame rate adjustment based on stream activity
    - Implement activity level calculation from recent events
    - Configure base rate (1 fps) and high activity rate (3 fps)
    - _Requirements: 1.6, 9.2_
  
  - [x] 15.3 Implement audio streaming
    - Create streaming audio output (play chunks as generated)
    - Implement chunk-by-chunk playback without full buffering
    - _Requirements: 3.2, 9.1_
  
  - [x] 15.4 Implement message batching
    - Create message batcher with batch_size=5 and max_wait=200ms
    - Implement batch processing with prioritization
    - _Requirements: 9.5_
  
  - [x] 15.5 Implement memory management
    - Create StreamDataBuffer with max size (100 MB)
    - Implement automatic frame eviction
    - Add explicit memory cleanup
    - _Requirements: 9.2_
  
  - [x] 15.6 Implement adaptive quality controller
    - Create quality adjustment based on latency metrics
    - Implement high/medium/low quality settings
    - Add automatic quality switching logic
    - _Requirements: 9.3, 9.4_
  
## Notes

- The project uses ADK's standard structure: `adk create streambuddy_agent` generates the base project
- The `agent.py` file contains the root_agent definition and all ADK tools
- Supporting services (Stream Ingestion, Audio Output, etc.) are separate Python modules that integrate with the ADK agent
- Use `adk run streambuddy_agent` for CLI testing and `adk web --port 8000` for web UI testing during development
- Tasks marked with `*` are optional and can be skipped for faster MVP development
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at key milestones
- Property tests validate universal correctness properties across randomized inputs
- Unit tests validate specific examples, edge cases, and error conditions
- The implementation follows ADK-first approach: agent tools → supporting services → integration → optimization → deployment
- All property tests should run with minimum 100 iterations using Hypothesis framework
- Each property test includes a comment tag: `# Feature: stream-buddy, Property N: [Property Title]`
- Testing tasks are sub-tasks to ensure they're implemented alongside the code they test
- The plan prioritizes early integration and continuous validation to catch issues quickly
