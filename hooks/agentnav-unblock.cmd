@echo off
rem AgentNav: PostToolUse de Claude Code / AfterTool de Gemini CLI (argumento 1 = tipo de agente, "claude" si falta).
rem Solo lanza PowerShell si ESTA sesion tiene una marca de "pide permiso" pendiente. Claude Code exporta
rem CLAUDE_CODE_SESSION_ID a sus hooks y Gemini CLI GEMINI_SESSION_ID; sin esa variable se usa la bandera global
rem blocked.flag (que agentnav-state.ps1 mantiene). Se consulta un archivo y no "carpeta\*": "if exist carpeta\*" es
rem verdadero aun con la carpeta vacia. El .ps1 es el que esta al lado de este archivo.
if not "%HERDR_ENV%"=="1" exit /b 0
set "AN_KIND=%~1"
if "%AN_KIND%"=="" set "AN_KIND=claude"
set "AN_SID=%CLAUDE_CODE_SESSION_ID%"
if /i "%AN_KIND%"=="gemini" set "AN_SID=%GEMINI_SESSION_ID%"
if "%AN_SID%"=="" goto flag
if not exist "%LOCALAPPDATA%\AgentNav\blocked\%AN_SID%" exit /b 0
goto run
:flag
if not exist "%LOCALAPPDATA%\AgentNav\blocked.flag" exit /b 0
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agentnav-state.ps1" unblock %AN_KIND%
exit /b 0
