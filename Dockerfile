# Multi-stage optimized Python Dockerfile for PharmaVigil PADER Regulatory Engine
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ENVIRONMENT=production

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/
COPY app.py .
COPY sample_data/ ./sample_data/
COPY Bisoprolol_icsr_sample_1068rows.xlsx .

# Create non-root user and set ownership
RUN useradd -m -u 1000 pharmavigil && \
    mkdir -p outputs && \
    chown -R pharmavigil:pharmavigil /app

# Switch to non-root user
USER pharmavigil

# Expose port (Render/Cloud providers dynamically set PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Start FastAPI application with Uvicorn
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
