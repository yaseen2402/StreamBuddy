# StreamBuddy

StreamBuddy is a real-time AI companion for live streamers that provides natural, voice-based interaction during YouTube Live broadcasts. Built with Google's Gemini Live API and Agent Development Kit (ADK), StreamBuddy processes multimodal inputs (video, audio, and chat) to deliver contextually relevant voice responses that enhance stream entertainment and viewer engagement.

## Features

- **Real-time Multimodal Processing**: Analyzes video frames, audio streams, and live chat simultaneously
- **Natural Voice Responses**: Generates voice responses with sub-2-second latency using Gemini Live API
- **Contextual Commentary**: Provides intelligent commentary on gameplay and stream events
- **Interactive Chat Processing**: Responds to viewer messages with personality and context awareness
- **Graceful Interruption Handling**: Allows natural conversation flow with interruption support
- **Customizable Personality**: Configure humor level, supportiveness, playfulness, and response style
- **Cloud-Native Deployment**: Runs on Google Cloud Platform with automatic scaling

## Technology Stack

- **AI Processing**: Google Gemini Live API (multimodal understanding and voice generation)
- **Agent Framework**: Google Agent Development Kit (ADK)
- **Cloud Infrastructure**: Google Cloud Platform (Cloud Run, Cloud Logging, Cloud Monitoring, Secret Manager)
- **Stream Integration**: YouTube Live API
- **Programming Language**: Python 3.11+

## Prerequisites

- Python 3.11 or higher
- Google Cloud Platform account with billing enabled
- YouTube Live API OAuth credentials
- Gemini API key from Google AI Studio
- Docker (for containerized deployment)

## Quick Start

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd StreamBuddy
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure credentials**
   ```
   python server.py
   ```

5. **frontend**  
   ```
   cd frontend
   npm install  # First time only
   npm run dev
   ```


