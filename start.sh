#!/usr/bin/env bash
echo "Starting Rail Nirdeshak..."
python3 backend/seed_data.py
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

