#!/bin/bash
# StreamBuddy Remote Deployment Setup Script

echo "🚀 StreamBuddy Remote Deployment Setup"
echo "========================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "✅ Created .env file"
    echo "⚠️  Please edit .env and add your GOOGLE_API_KEY"
    echo ""
else
    echo "✅ .env file already exists"
fi

# Check if REMOTE_AUDIO_MODE is set
if ! grep -q "REMOTE_AUDIO_MODE=true" .env; then
    echo "📝 Setting REMOTE_AUDIO_MODE=true in .env..."
    if grep -q "REMOTE_AUDIO_MODE" .env; then
        sed -i 's/REMOTE_AUDIO_MODE=.*/REMOTE_AUDIO_MODE=true/' .env
    else
        echo "REMOTE_AUDIO_MODE=true" >> .env
    fi
    echo "✅ Remote audio mode enabled"
fi

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
if command -v pip &> /dev/null; then
    pip install -r requirements.txt
    echo "✅ Python dependencies installed"
else
    echo "❌ pip not found. Please install Python and pip first."
    exit 1
fi

# Setup frontend
echo ""
echo "📦 Setting up frontend..."
cd frontend

if [ ! -f .env ]; then
    echo "📝 Creating frontend .env file..."
    cp .env.example .env
    echo "✅ Created frontend .env file"
    echo "⚠️  Edit frontend/.env to set your backend URL for production"
fi

if command -v npm &> /dev/null; then
    echo "📦 Installing frontend dependencies..."
    npm install
    echo "✅ Frontend dependencies installed"
else
    echo "❌ npm not found. Please install Node.js first."
    exit 1
fi

cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your GOOGLE_API_KEY"
echo "2. For production: Edit frontend/.env to set VITE_BACKEND_HOST"
echo "3. Start backend: python server.py"
echo "4. Start frontend: cd frontend && npm run dev"
echo ""
echo "📖 See DEPLOYMENT.md for detailed deployment instructions"
