// StreamBuddy Web UI JavaScript

class StreamBuddyUI {
    constructor() {
        this.ws = null;
        this.currentMode = 'local';
        this.isActive = false;
        this.uptimeInterval = null;
        this.startTime = null;
        
        this.initializeElements();
        this.attachEventListeners();
        this.connectWebSocket();
        this.loadStatus();
    }
    
    initializeElements() {
        // Mode buttons
        this.localModeBtn = document.getElementById('localModeBtn');
        this.youtubeModeBtn = document.getElementById('youtubeModeBtn');
        
        // Settings panels
        this.localSettings = document.getElementById('localSettings');
        this.youtubeSettings = document.getElementById('youtubeSettings');
        
        // Form inputs
        this.videoSource = document.getElementById('videoSource');
        this.youtubeToken = document.getElementById('youtubeToken');
        this.geminiKey = document.getElementById('geminiKey');
        
        // Control buttons
        this.startBtn = document.getElementById('startBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.updatePersonalityBtn = document.getElementById('updatePersonalityBtn');
        
        // Status elements
        this.connectionStatus = document.getElementById('connectionStatus');
        this.sessionId = document.getElementById('sessionId');
        this.sessionMode = document.getElementById('sessionMode');
        this.sessionUptime = document.getElementById('sessionUptime');
        
        // Component status
        this.geminiStatus = document.getElementById('geminiStatus');
        this.videoStatus = document.getElementById('videoStatus');
        this.audioStatus = document.getElementById('audioStatus');
        this.outputStatus = document.getElementById('outputStatus');
        
        // Metrics
        this.framesCount = document.getElementById('framesCount');
        this.audioCount = document.getElementById('audioCount');
        this.responsesCount = document.getElementById('responsesCount');
        
        // Personality controls
        this.humorSlider = document.getElementById('humorSlider');
        this.supportSlider = document.getElementById('supportSlider');
        this.playSlider = document.getElementById('playSlider');
        this.verbositySelect = document.getElementById('verbositySelect');
        this.frequencySelect = document.getElementById('frequencySelect');
        
        // Slider value displays
        this.humorValue = document.getElementById('humorValue');
        this.supportValue = document.getElementById('supportValue');
        this.playValue = document.getElementById('playValue');
        
        // Activity log
        this.activityLog = document.getElementById('activityLog');
    }
    
    attachEventListeners() {
        // Mode selection
        this.localModeBtn.addEventListener('click', () => this.switchMode('local'));
        this.youtubeModeBtn.addEventListener('click', () => this.switchMode('youtube'));
        
        // Control buttons
        this.startBtn.addEventListener('click', () => this.startSession());
        this.stopBtn.addEventListener('click', () => this.stopSession());
        this.updatePersonalityBtn.addEventListener('click', () => this.updatePersonality());
        
        // Personality sliders
        this.humorSlider.addEventListener('input', (e) => {
            this.humorValue.textContent = e.target.value;
        });
        this.supportSlider.addEventListener('input', (e) => {
            this.supportValue.textContent = e.target.value;
        });
        this.playSlider.addEventListener('input', (e) => {
            this.playValue.textContent = e.target.value;
        });
    }
    
    switchMode(mode) {
        this.currentMode = mode;
        
        // Update button states
        if (mode === 'local') {
            this.localModeBtn.classList.add('active');
            this.youtubeModeBtn.classList.remove('active');
            this.localSettings.style.display = 'block';
            this.youtubeSettings.style.display = 'none';
        } else {
            this.youtubeModeBtn.classList.add('active');
            this.localModeBtn.classList.remove('active');
            this.youtubeSettings.style.display = 'block';
            this.localSettings.style.display = 'none';
        }
    }
    
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus(true);
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.updateConnectionStatus(false);
            // Reconnect after 3 seconds
            setTimeout(() => this.connectWebSocket(), 3000);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleWebSocketMessage(data) {
        if (data.type === 'status') {
            this.addLogEntry(data.message, data.level);
            
            if (data.session_status) {
                this.updateStatus(data.session_status);
            }
        }
    }
    
    updateConnectionStatus(connected) {
        if (connected) {
            this.connectionStatus.classList.add('connected');
            this.connectionStatus.querySelector('.text').textContent = 'Connected';
        } else {
            this.connectionStatus.classList.remove('connected');
            this.connectionStatus.querySelector('.text').textContent = 'Disconnected';
        }
    }
    
    async loadStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            if (data.is_active) {
                this.isActive = true;
                this.startTime = new Date(data.start_time);
                this.sessionId.textContent = data.session_id;
                this.sessionMode.textContent = data.mode;
                this.updateStatus(data.status);
                this.updateUIForActiveSession();
                this.startUptimeCounter();
                
                // Update personality controls
                if (data.personality) {
                    this.humorSlider.value = data.personality.humor_level;
                    this.humorValue.textContent = data.personality.humor_level;
                    this.supportSlider.value = data.personality.supportiveness;
                    this.supportValue.textContent = data.personality.supportiveness;
                    this.playSlider.value = data.personality.playfulness;
                    this.playValue.textContent = data.personality.playfulness;
                    this.verbositySelect.value = data.personality.verbosity;
                    this.frequencySelect.value = data.personality.response_frequency;
                }
            }
        } catch (error) {
            console.error('Failed to load status:', error);
        }
    }
    
    async startSession() {
        const config = {
            mode: this.currentMode,
            gemini_api_key: this.geminiKey.value || null,
            video_source: this.videoSource.value,
            personality: {
                humor_level: parseFloat(this.humorSlider.value),
                supportiveness: parseFloat(this.supportSlider.value),
                playfulness: parseFloat(this.playSlider.value),
                verbosity: this.verbositySelect.value,
                response_frequency: this.frequencySelect.value
            }
        };
        
        if (this.currentMode === 'youtube') {
            config.youtube_oauth_token = this.youtubeToken.value || null;
        }
        
        this.startBtn.disabled = true;
        this.addLogEntry('Starting StreamBuddy...', 'info');
        
        try {
            const response = await fetch('/api/session/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to start session');
            }
            
            const data = await response.json();
            
            this.isActive = true;
            this.startTime = new Date(data.start_time);
            this.sessionId.textContent = data.session_id;
            this.sessionMode.textContent = data.mode;
            
            this.updateUIForActiveSession();
            this.startUptimeCounter();
            this.addLogEntry('StreamBuddy started successfully!', 'success');
            
        } catch (error) {
            console.error('Failed to start session:', error);
            this.addLogEntry(`Error: ${error.message}`, 'error');
            this.startBtn.disabled = false;
        }
    }
    
    async stopSession() {
        this.stopBtn.disabled = true;
        this.addLogEntry('Stopping StreamBuddy...', 'info');
        
        try {
            const response = await fetch('/api/session/stop', {
                method: 'POST'
            });
            
            if (!response.ok) {
                throw new Error('Failed to stop session');
            }
            
            const data = await response.json();
            
            this.isActive = false;
            this.stopUptimeCounter();
            
            this.updateUIForInactiveSession();
            this.addLogEntry(`Session stopped. Duration: ${Math.round(data.duration_seconds)}s`, 'success');
            
        } catch (error) {
            console.error('Failed to stop session:', error);
            this.addLogEntry(`Error: ${error.message}`, 'error');
            this.stopBtn.disabled = false;
        }
    }
    
    async updatePersonality() {
        const updates = {
            humor_level: parseFloat(this.humorSlider.value),
            supportiveness: parseFloat(this.supportSlider.value),
            playfulness: parseFloat(this.playSlider.value),
            verbosity: this.verbositySelect.value,
            response_frequency: this.frequencySelect.value
        };
        
        try {
            const response = await fetch('/api/personality/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });
            
            if (!response.ok) {
                throw new Error('Failed to update personality');
            }
            
            this.addLogEntry('Personality updated successfully', 'success');
            
        } catch (error) {
            console.error('Failed to update personality:', error);
            this.addLogEntry(`Error: ${error.message}`, 'error');
        }
    }
    
    updateStatus(status) {
        // Update component status badges
        this.updateComponentBadge(this.geminiStatus, status.gemini_connected);
        this.updateComponentBadge(this.videoStatus, status.video_capturing);
        this.updateComponentBadge(this.audioStatus, status.audio_capturing);
        this.updateComponentBadge(this.outputStatus, status.audio_output_active);
        
        // Update metrics
        this.framesCount.textContent = status.frames_captured || 0;
        this.audioCount.textContent = status.audio_chunks_captured || 0;
        this.responsesCount.textContent = status.responses_generated || 0;
    }
    
    updateComponentBadge(element, isActive) {
        const badge = element.querySelector('.badge');
        
        if (isActive) {
            badge.classList.remove('badge-inactive', 'badge-error');
            badge.classList.add('badge-active');
            badge.textContent = 'Active';
        } else {
            badge.classList.remove('badge-active', 'badge-error');
            badge.classList.add('badge-inactive');
            badge.textContent = 'Inactive';
        }
    }
    
    updateUIForActiveSession() {
        this.startBtn.style.display = 'none';
        this.stopBtn.style.display = 'block';
        this.stopBtn.disabled = false;
        this.updatePersonalityBtn.disabled = false;
        
        // Disable configuration inputs
        this.localModeBtn.disabled = true;
        this.youtubeModeBtn.disabled = true;
        this.videoSource.disabled = true;
        this.youtubeToken.disabled = true;
        this.geminiKey.disabled = true;
    }
    
    updateUIForInactiveSession() {
        this.stopBtn.style.display = 'none';
        this.startBtn.style.display = 'block';
        this.startBtn.disabled = false;
        this.updatePersonalityBtn.disabled = true;
        
        // Enable configuration inputs
        this.localModeBtn.disabled = false;
        this.youtubeModeBtn.disabled = false;
        this.videoSource.disabled = false;
        this.youtubeToken.disabled = false;
        this.geminiKey.disabled = false;
        
        // Reset session info
        this.sessionId.textContent = 'Not started';
        this.sessionMode.textContent = '-';
        this.sessionUptime.textContent = '0s';
        
        // Reset status
        this.updateStatus({
            gemini_connected: false,
            video_capturing: false,
            audio_capturing: false,
            audio_output_active: false,
            frames_captured: 0,
            audio_chunks_captured: 0,
            responses_generated: 0
        });
    }
    
    startUptimeCounter() {
        this.uptimeInterval = setInterval(() => {
            if (this.startTime) {
                const uptime = Math.floor((Date.now() - this.startTime) / 1000);
                this.sessionUptime.textContent = this.formatUptime(uptime);
            }
        }, 1000);
    }
    
    stopUptimeCounter() {
        if (this.uptimeInterval) {
            clearInterval(this.uptimeInterval);
            this.uptimeInterval = null;
        }
    }
    
    formatUptime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        
        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }
    
    addLogEntry(message, level = 'info') {
        const entry = document.createElement('div');
        entry.className = `log-entry log-${level}`;
        
        const timestamp = document.createElement('span');
        timestamp.className = 'timestamp';
        timestamp.textContent = `[${new Date().toLocaleTimeString()}]`;
        
        const messageSpan = document.createElement('span');
        messageSpan.className = 'message';
        messageSpan.textContent = message;
        
        entry.appendChild(timestamp);
        entry.appendChild(messageSpan);
        
        this.activityLog.appendChild(entry);
        
        // Auto-scroll to bottom
        this.activityLog.scrollTop = this.activityLog.scrollHeight;
        
        // Keep only last 100 entries
        while (this.activityLog.children.length > 100) {
            this.activityLog.removeChild(this.activityLog.firstChild);
        }
    }
}

// Initialize UI when page loads
document.addEventListener('DOMContentLoaded', () => {
    window.streamBuddyUI = new StreamBuddyUI();
});
