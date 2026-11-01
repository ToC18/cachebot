@echo off
chcp 65001 > nul
title CacheBot Full Service
cd /d "%~dp0"
echo ======================================================
echo       Запуск CacheBot + Cloudflare Mini App
echo ======================================================
call .venv\Scripts\activate.bat
python start_all.py
pause
