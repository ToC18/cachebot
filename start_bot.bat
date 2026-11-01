@echo off
chcp 65001 > nul
cd /d "C:\Users\Максим\PycharmProjects\cachebot"
".venv\Scripts\python.exe" -u start_all.py > daemon.log 2>&1
