@echo off
REM 최초 1회: 가상환경을 만들고 의존성을 설치하고 .env 를 만든다.
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo 준비 끝. manifest.yaml 과 agent.py 를 채운 뒤 run.bat 을 실행하세요.
