@echo off
title Ğ¶ÔØĞéÄâÉù¿¨Çı¶¯
cd /d "%~dp0"
powershell -Command "Start-Process '%~dp0tools\vbcable\VBCABLE_Setup_x64.exe' -Verb RunAs"
