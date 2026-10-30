@echo off
rem AgentNav: PostToolUse. Solo lanza PowerShell si ESTA sesion tiene una marca de "pide permiso" pendiente.
rem Claude Code exporta CLAUDE_CODE_SESSION_ID a sus hooks; sin esa variable se usa la bandera global blocked.flag
rem (que agentnav-state.ps1 mantiene). Se consulta un archivo y no "carpeta\*": "if exist carpeta\*" es verdadero
rem aun con la carpeta vacia.
if not "%HERDR_ENV%"=="1" exit /b 0
if "%CLAUDE_CODE_SESSION_ID%"=="" goto flag
if not exist "%LOCALAPPDATA%\AgentNav\blocked\%CLAUDE_CODE_SESSION_ID%" exit /b 0
goto run
:flag
if not exist "%LOCALAPPDATA%\AgentNav\blocked.flag" exit /b 0
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude\hooks\agentnav-state.ps1" unblock
exit /b 0
