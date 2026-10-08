@echo off
title PharmaVigil Regulatory Backend
echo ======================================================================
echo   PharmaVigil - Automated Regulatory Safety Engine (FastAPI Backend)
echo ======================================================================
echo.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    echo Starting server with virtualenv on http://localhost:8000 ...
    .venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
) else (
    echo Starting server with system Python on http://localhost:8000 ...
    python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
)
pause
