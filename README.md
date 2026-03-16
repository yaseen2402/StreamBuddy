# StreamBuddy

**Never stream alone, never miss a chat - Your AI co-host for Live streaming**

StreamBuddy is a real-time AI companion for live streamers that provides natural, voice-based interaction during YouTube Live broadcasts. Built with Google's Gemini Live API and GenAI SDK, StreamBuddy processes multimodal inputs (video(future), audio, and chat) to deliver contextually relevant voice responses that enhance stream entertainment and viewer engagement.

## Architecture

View the complete system architecture diagram: [StreamBuddy Architecture](https://yaseen2402.github.io/StreamBuddy/)

## Features

- **Real-time Multimodal Processing**: Analyzes audio streams and live chat simultaneously
- **Natural Voice Responses**: Generates voice responses with sub-2-second latency using Gemini Live API
- **Contextual Commentary**: Provides intelligent commentary 
- **Interactive Chat Processing**: Responds to viewer messages with personality and context awareness
- **Graceful Interruption Handling**: Allows natural conversation flow with interruption support
- **Customizable Personality**: Configure humor level, supportiveness, playfulness, and response style
- **Cloud-Native Deployment**: Runs on Google Cloud Platform with automatic scaling

## Technology Stack

- **AI Processing**: Google Gemini Live API (multimodal understanding and voice generation)
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
   git clone https://github.com/yaseen2402/StreamBuddy
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

4. **Set up environment variables**
   
   Create `.env` file in the root directory:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your credentials:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key_here
   REMOTE_AUDIO_MODE=true
   PROACTIVE_AUDIO_MODE=false
   ```
   
   Create `env.yaml` for Cloud Run deployment:
   ```bash
   cp env.yaml.example env.yaml
   ```
   
   Edit `env.yaml`:
   ```yaml
   GOOGLE_API_KEY: your_gemini_api_key_here
   REMOTE_AUDIO_MODE: "true"
   PROACTIVE_AUDIO_MODE: "false"
   FRONTEND_URL: "http://localhost:3000"
   ```

5. **Set up YouTube OAuth credentials**
   
   a. Go to [Google Cloud Console](https://console.cloud.google.com/)
   
   b. Create a new project or select existing one
   
   c. Enable YouTube Data API v3:
      - Navigate to "APIs & Services" → "Library"
      - Search for "YouTube Data API v3"
      - Click "Enable"
   
   d. Create OAuth 2.0 credentials:
      - Go to "APIs & Services" → "Credentials"
      - Click "Create Credentials" → "OAuth client ID"
      - Application type: "Web application"
      - Click "Create"
   
   copy the example and fill in your credentials:
   ```bash
   cp client_secret_example.json client_secret.json
   ```
   
   Edit `client_secret.json` with your OAuth client ID and secret from Google Console.

6. **Start the backend server**
   ```bash
   python server.py
   ```

7. **Start the frontend** (in a new terminal)
   ```bash
   cd frontend
   npm install  # First time only
   npm run dev
   ```

8. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000


