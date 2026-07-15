# VOID-NUKE WEB - Render Free Tier Optimized Dockerfile
# Uses Python 3.11 to avoid audioop issue, but also supports 3.13 via audioop-lts shim

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000

WORKDIR /app

COPY requirements.txt .
# Install with no cache to save space + ensure audioop-lts for compatibility
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "import sys; sys.path.insert(0,'.'); try:\
 import audioop; print('audioop ok');\
 except ModuleNotFoundError:\
  import audioop_lts as audioop; sys.modules['audioop']=audioop; print('audioop-lts shim ok')\
 " && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . .

# Remove pycache to save RAM
RUN find . -type d -name __pycache__ -exec rm -rf {} + || true

EXPOSE 10000

# 1 worker + 2 threads = ~250MB RAM fits 512MB free tier
# run.py --prod handles gunicorn with preload + audioop fix
CMD ["python", "run.py", "--prod"]
