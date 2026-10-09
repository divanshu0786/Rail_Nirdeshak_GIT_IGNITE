@echo off
echo Starting Rail Nirdeshak Server...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" backend/main.py
) else if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" backend/main.py
) else (
    py -3 backend/main.py
)
pause

