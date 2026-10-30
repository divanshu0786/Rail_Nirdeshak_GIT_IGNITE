# Rail Nirdeshak Production Container
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source code, frontend assets, and datasets
COPY . /app

# Expose server port
EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0
ENV DATABASE_URL=sqlite:///./rail_nirdeshak.db

# Launch server (database auto-seeds on initial startup if empty)
CMD ["python", "backend/main.py"]
