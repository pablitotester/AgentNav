@echo off
rem AgentNav: PostToolUse. Solo lanza PowerShell si hay una marca de "pide permiso" pendiente (y estamos dentro de Herdr).
rem La bandera la mantiene agentnav-state.ps1 (Sync-BlockedFlag); se consulta un archivo y no "carpeta\*" porque
rem "if exist carpeta\*" es verdadero aun con la carpeta vacia.
if not "%HERDR_ENV%"=="1" exit /b 0
if not exist "%LOCALAPPDATA%\AgentNav\blocked.flag" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude\hooks\agentnav-state.ps1" unblock
exit /b 0
