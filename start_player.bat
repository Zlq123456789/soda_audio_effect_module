@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动【音效管理】...
start "" pythonw.exe soda_player_gui_qt.py
exit
