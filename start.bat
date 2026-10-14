@echo off
cd /d "%~dp0"
echo Installing dependencies ...
python -m pip install -r requirements.txt
echo Starting AI Trader ...
python run.py
pause
