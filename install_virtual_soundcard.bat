@echo off
title °²×°ĞéÄâÉù¿¨Çı¶¯
cd /d "%~dp0"
powershell -Command "Start-Process '%~dp0tools\vbcable\VBCABLE_Setup_x64.exe' -Verb RunAs"
