# Optional Dockerfile for Render - optimized for 512MB
FROM python:3.11-slim

# Low RAM optimization
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .

# Render uses PORT 10000
EXPOSE 10000

# 1 worker, 2 threads = ~200-300MB RAM, fits 512MB free tier
# gthread worker is best for 0.1 CPU
CMD gunicorn app:app --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT --worker-class gthread --preload
