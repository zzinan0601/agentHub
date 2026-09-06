@echo off
REM 내 에이전트를 띄운다. 처음 한 번은 setup.bat 을 먼저 실행할 것.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py
