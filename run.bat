@echo off
title Sentinel - Centralizador de Automacoes
echo Iniciando o Sentinel Monitor...
cd /d "%~dp0"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8050 --reload
pause
