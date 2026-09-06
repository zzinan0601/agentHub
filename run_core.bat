@echo off
REM 코어(코디네이터 + 채팅 화면)를 띄운다. 처음 한 번은 setup_core.bat 을 먼저 실행할 것.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m core.main
