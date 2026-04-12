@echo off
cd /d "%~dp0"
set IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4 Address"') do (
    set IP=%%a
)
set IP=%IP: =%
echo Starting Current Link Driver Payroll...
echo.
echo Local: http://127.0.0.1:5000
if not "%IP%"=="" echo Network: http://%IP%:5000
echo.
start "" http://127.0.0.1:5000
py serve.py
