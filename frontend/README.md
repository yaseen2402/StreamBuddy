# StreamBuddy React Frontend

Modern React frontend for StreamBuddy AI co-host.

## Tech Stack

- **React 18** - UI library
- **Vite** - Build tool & dev server
- **Tailwind CSS** - Styling
- **Zustand** - State management
- **Axios** - HTTP client
- **Lucide React** - Icons
- **WebSocket** - Real-time updates

## Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Start Development Server

```bash
npm run dev
```

Frontend will run on: **http://localhost:3000**

### 3. Start Backend

In another terminal:

```bash
cd ..
python web_ui.py
```

Backend will run on: **http://localhost:8000**

## Features

### 🎨 Modern UI
- Responsive design
- Tailwind CSS styling
- Smooth animations
- Clean, professional look

### 🔄 Real-time Updates
- WebSocket connection
- Live status monitoring
- Instant personality updates
- Activity log streaming

### 📊 State Management
- Zustand for global state
- Persistent configuration
- Optimistic updates
- Error handling

### 🎭 Personality Controls
- Interactive sliders
- Dropdown selectors
- Live preview
- Instant updates

## Project Structure

```
frontend/
├── src/
│   ├── components/          # React components
│   │   ├── Header.jsx
│   │   ├── ModeSelector.jsx
│   │   ├── ConfigPanel.jsx
│   │   ├── StatusPanel.jsx
│   │   ├── PersonalityPanel.jsx
│   │   └── ActivityLog.jsx
│   ├── hooks/              # Custom hooks
│   │   └── useWebSocket.js
│   ├── services/           # API services
│   │   └── api.js
│   ├── store/              # State management
│   │   └── useStreamBuddyStore.js
│   ├── App.jsx             # Main app component
│   ├── main.jsx            # Entry point
│   └── index.css           # Global styles
├── public/                 # Static assets
├── index.html              # HTML template
├── vite.config.js          # Vite configuration
├── tailwind.config.js      # Tailwind configuration
└── package.json            # Dependencies

```

## Available Scripts

```bash
# Development server
npm run dev

# Production build
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

## Configuration

### Vite Proxy

The dev server proxies API requests to the backend:

```javascript
proxy: {
  '/api': 'http://localhost:8000',
  '/ws': 'ws://localhost:8000',
}
```

### Environment Variables

Create `.env` file:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Components

### Header
- App branding
- WebSocket connection status
- Responsive layout

### ModeSelector
- Local Testing mode
- YouTube Live mode
- Visual mode cards

### ConfigPanel
- Video source selection
- API key input
- OAuth token input
- Start/Stop controls

### StatusPanel
- Session information
- Component health status
- Live metrics
- Uptime counter

### PersonalityPanel
- Humor slider
- Supportiveness slider
- Playfulness slider
- Response style dropdown
- Frequency dropdown
- Update button

### ActivityLog
- Real-time event stream
- Color-coded by severity
- Auto-scroll
- Timestamp display

## State Management

### Zustand Store

```javascript
{
  // Connection
  wsConnected: boolean,
  
  // Session
  sessionId: string,
  mode: 'local' | 'youtube',
  isActive: boolean,
  startTime: Date,
  
  // Status
  status: {
    gemini_connected: boolean,
    video_capturing: boolean,
    audio_capturing: boolean,
    audio_output_active: boolean,
    frames_captured: number,
    audio_chunks_captured: number,
    responses_generated: number,
  },
  
  // Configuration
  config: {
    videoSource: string,
    geminiApiKey: string,
    youtubeOAuthToken: string,
  },
  
  // Personality
  personality: {
    humor_level: number,
    supportiveness: number,
    playfulness: number,
    verbosity: string,
    response_frequency: string,
    chat_interaction_mode: string,
  },
  
  // Activity Log
  activityLog: Array<{
    timestamp: string,
    message: string,
    level: 'info' | 'success' | 'warning' | 'error',
  }>,
}
```

## API Integration

### REST Endpoints

```javascript
// Get status
GET /api/status

// Start session
POST /api/session/start
{
  mode: 'local' | 'youtube',
  gemini_api_key: string,
  youtube_oauth_token: string,
  video_source: string,
  personality: object,
}

// Stop session
POST /api/session/stop

// Update personality
POST /api/personality/update
{
  humor_level: number,
  supportiveness: number,
  playfulness: number,
  verbosity: string,
  response_frequency: string,
  chat_interaction_mode: string,
}
```

### WebSocket

```javascript
// Connect
ws://localhost:8000/ws

// Message format
{
  type: 'status' | 'connected',
  message: string,
  level: 'info' | 'success' | 'warning' | 'error',
  session_status: object,
}
```

## Styling

### Tailwind CSS

Custom theme in `tailwind.config.js`:

```javascript
colors: {
  primary: {
    50: '#eef2ff',
    100: '#e0e7ff',
    500: '#6366f1',
    600: '#4f46e5',
    700: '#4338ca',
  },
}
```

### Custom Classes

```css
.card - White card with shadow
.btn - Base button styles
.btn-primary - Primary button
.btn-danger - Danger button
.btn-secondary - Secondary button
.badge - Badge styles
.badge-active - Active badge
.badge-inactive - Inactive badge
```

## Development

### Hot Module Replacement

Vite provides instant HMR for fast development.

### Component Development

1. Create component in `src/components/`
2. Import in `App.jsx`
3. Use Zustand store for state
4. Style with Tailwind classes

### Adding New Features

1. Update store in `useStreamBuddyStore.js`
2. Create/update components
3. Add API calls in `services/api.js`
4. Test with backend running

## Building for Production

```bash
# Build
npm run build

# Preview
npm run preview
```

Output in `dist/` directory.

## Deployment

### Static Hosting

Deploy `dist/` folder to:
- Vercel
- Netlify
- GitHub Pages
- AWS S3 + CloudFront

### Environment Variables

Set in hosting platform:
- `VITE_API_URL` - Backend API URL
- `VITE_WS_URL` - WebSocket URL

## Troubleshooting

### Port Already in Use

Change port in `vite.config.js`:

```javascript
server: {
  port: 3001,
}
```

### API Connection Failed

1. Check backend is running on port 8000
2. Verify proxy configuration
3. Check browser console for errors

### WebSocket Won't Connect

1. Ensure backend WebSocket endpoint is running
2. Check firewall settings
3. Verify WebSocket URL in code

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)

## License

See main project LICENSE file.
