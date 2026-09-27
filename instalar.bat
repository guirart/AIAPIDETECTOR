@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando o Monitor de EPI (pode levar alguns minutos)...
py -m venv .venv || python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Pronto! Configure a chave do Roboflow (veja o README) e rode iniciar_monitor.bat
pause
