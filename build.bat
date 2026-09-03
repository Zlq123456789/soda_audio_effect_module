@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在执行一键打包构建...
python build_release.py
pause
