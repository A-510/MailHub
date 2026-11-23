@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MailHub 启动器

if exist "MailHubLauncher.exe" (
    start "" "MailHubLauncher.exe"
    exit /b 0
)

if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" "launcher.py"
) else (
    python "launcher.py"
)

if errorlevel 1 (
    echo MailHub 启动失败，请检查环境配置。
    pause
)
