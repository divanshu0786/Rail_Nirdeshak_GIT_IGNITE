@echo off
echo Starting Rail Nirdeshak...
py -3 backend/seed_data.py
py -3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
