@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
  C:\Python312\python.exe "%~dp0gmtool.py" --help
) else (
  C:\Python312\python.exe "%~dp0gmtool.py" %*
)
echo.
pause
