FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# - poppler-utils: PDF conversion
# - libgomp1: OpenMP for PaddleOCR
# - libgl1, libglib2.0-0: OpenCV dependencies for PaddleOCR
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Create data directories
RUN mkdir -p /data/paragony/inbox /data/paragony/processed /data/vault/paragony /data/vault/logs

# Expose port
EXPOSE 8000

# Run FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
