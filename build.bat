@echo off
rem Builds Banana.exe into this folder. Run from anywhere: build.bat
cd /d "%~dp0"

rem a running Banana.exe locks the file and makes the build fail
taskkill /IM Banana.exe /F >nul 2>&1

python -m PyInstaller --noconfirm --onefile --windowed ^
    --icon assets\banana.ico ^
    --add-data "assets\banana.ico;assets" ^
    --add-data "assets\banana.png;assets" ^
    --hidden-import pystray._win32 ^
    --exclude-module numpy ^
    --name Banana --distpath . ^
    Banana.py
