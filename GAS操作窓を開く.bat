@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0ws_window.py" %*) || (start "" pythonw "%~dp0ws_window.py" %*)
