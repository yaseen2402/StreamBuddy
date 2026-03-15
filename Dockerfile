# Multi-stage Dockerfile for StreamBuddy Cloud Run deployment
# Optimized for real-time AI streaming companion

# Stage 1: Build stage
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libportaudio2 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY streambuddy_agent/ ./streambuddy_agent/
COPY server.py .
COPY client_secret.json* ./

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Set Python to run in unbuffered mode for real-time logging
ENV PYTHONUNBUFFERED=1

# Environment variables will be set at deploy time via env.yaml
ENV PORT=8080

# Expose port for Cloud Run (default 8080)
EXPOSE 8080

# Run the application with proper host binding
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}
