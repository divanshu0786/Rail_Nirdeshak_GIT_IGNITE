# Rail Nirdeshak Production Container
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy source code and frontend assets
COPY . /app

# Expose server port
EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0
ENV DATABASE_URL=sqlite:///./rail_nirdeshak.db

# Pre-seed realistic demo dataset and start uvicorn
CMD ["sh", "-c", "python backend/seed_data.py && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
