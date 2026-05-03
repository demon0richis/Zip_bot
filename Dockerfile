# ─────────────────────────────────────────────
#  Dockerfile — Telegram ZIP Bot + MKV Converter
#  Railway compatible | ffmpeg included
# ─────────────────────────────────────────────

FROM python:3.11-slim

# Install ffmpeg (needed for MKV→MP4 conversion)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY main.py .

# Run bot
CMD ["python", "-u", "main.py"]
