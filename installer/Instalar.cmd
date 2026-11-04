@echo off
rem AgentNav: doble clic aca. Corre install.ps1 saltando la politica de ejecucion (no hace falta administrador).
title Instalar AgentNav
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
