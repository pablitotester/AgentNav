# AgentNav

Capa fina sobre [Herdr](https://herdr.dev) para navegar proyectos y agentes Claude Code en Windows.
Herdr es la interfaz, tal cual viene. AgentNav agrega lo que Herdr no trae:

1. **Estado exacto de cada Claude** por hooks de Claude Code (`hooks/agentnav-state.ps1`), que reportan
   working / blocked / idle al panel de Herdr que aloja la sesión.
2. **Registro de proyectos** (`projects.json`) y un **selector** como popup de Herdr: `ctrl+b`, soltar, `alt+p`.
3. **Arranque de un comando**: `agentnav` levanta el servidor y abre la pestaña de Windows Terminal.

Diseño completo y decisiones: `docs/DISENO.html`.

## Archivos

| Qué | Dónde vive en uso | Copia versionada acá |
|---|---|---|
| Script principal | `C:\AgentNav\agentnav.py` (+ `agentnav.ps1`) | mismo |
| Registro de proyectos | `C:\AgentNav\projects.json` | mismo |
| Hook de Claude Code | `%USERPROFILE%\.claude\hooks\agentnav-state.ps1` | `hooks/agentnav-state.ps1` |
| Registro del hook | `%USERPROFILE%\.claude\settings.json` (eventos UserPromptSubmit, Stop, SessionEnd, Notification) | ver `docs/DISENO.html` |
| Config de Herdr | `%APPDATA%\herdr\config.toml` | `config/herdr.config.toml` |
| Arranque automático | carpeta Inicio de Windows, `Herdr server.vbs` | `startup/Herdr server.vbs` |
| Alias `agentnav` | perfiles de pwsh y de Windows PowerShell | una línea: `Set-Alias agentnav C:\AgentNav\agentnav.ps1` |

El hook **tiene que guardarse como UTF-8 con BOM**: Windows PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252.

## Uso

```
agentnav                 servidor arriba si hace falta + pestaña de Windows Terminal enganchada
agentnav list            proyectos, cuáles están abiertos, cada agente con su estado
agentnav open <nombre>   abre el proyecto como espacio con sus Claude, o lo enfoca y repone los que falten
agentnav pick            el selector (lo corre el popup de Herdr)
```

Dentro de Herdr: `ctrl+b F1` muestra todas las teclas (en Herdr es `?`, que el teclado en español no entrega).

## Requisitos

Windows 10/11, Herdr 0.9.5 o superior (canal estable), Python 3 con el lanzador `py`, Claude Code, Windows Terminal.
