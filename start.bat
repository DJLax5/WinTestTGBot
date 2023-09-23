@echo off
setlocal enabledelayedexpansion
set conda_env_path=%~dp0env
call "%conda_env_path%\Scripts\activate.bat" WT-TGBot-env
python %~dp0WinTestTGBot.py
call "%conda_env_path%\Scripts\deactivate.bat"
endlocal
