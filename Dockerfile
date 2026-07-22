# ============================================
# Stage 1: Build React frontend
# ============================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Install dependencies (cached layer)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source and build
COPY frontend/ .
# Build with empty API URL → frontend uses same-origin relative paths
ENV VITE_API_URL=""
# Increase Node.js heap limit to avoid OOM during Vite build
ENV NODE_OPTIONS="--max-old-space-size=2048"
RUN npm run build

# ============================================
# Stage 2: Python backend + built frontend
# ============================================
FROM python:3.11-slim

WORKDIR /app

# System dependencies (gcc for potential C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/
COPY run.py .

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create data directory for SQLite persistence
RUN mkdir -p /app/data

# Disable uvicorn reload (production mode)
ENV RAILWAY_ENVIRONMENT=docker
ENV PORT=8000
ENV DATABASE_URL=sqlite:///./data/tradingbot.db

EXPOSE 8000

CMD ["python", "run.py"]
