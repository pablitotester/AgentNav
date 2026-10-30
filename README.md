# AgentNav

Capa fina sobre [Herdr](https://herdr.dev) para navegar proyectos y agentes Claude Code en Windows.
Herdr es la interfaz, tal cual viene. AgentNav agrega lo que Herdr no trae:

1. **Estado exacto de cada Claude** por hooks de Claude Code (`hooks/agentnav-state.ps1`), que reportan
   working / blocked / idle al panel de Herdr que aloja la sesión, y vuelven a working cuando concedés un permiso.
2. **Registro de proyectos** (`projects.json`) y un **selector** como popup de Herdr: `ctrl+b`, soltar, `alt+p`.
   Muestra rama y cambios de git, y las carpetas recientes donde corrió Claude.
3. **Arranque de un comando**: `agentnav` levanta el servidor y abre la pestaña de Windows Terminal.
4. **Diario** de lo que le pediste a cada proyecto, **avisos al teléfono** por ntfy y un **doctor** de la instalación.

Diseño completo y decisiones: `docs/DISENO.html`.

## Archivos

| Qué | Dónde vive en uso | Copia versionada acá |
|---|---|---|
| Script principal | `C:\AgentNav\agentnav.py` (+ `agentnav.ps1`) | mismo |
| Registro de proyectos | `C:\AgentNav\projects.json` | mismo |
| Ajustes (avisos ntfy) | `C:\AgentNav\settings.json` | `settings.example.json` (el real no se versiona) |
| Hook de Claude Code | `%USERPROFILE%\.claude\hooks\agentnav-state.ps1` | `hooks/agentnav-state.ps1` |
| Puerta del desbloqueo | `%USERPROFILE%\.claude\hooks\agentnav-unblock.cmd` | `hooks/agentnav-unblock.cmd` |
| Registro de los hooks | `%USERPROFILE%\.claude\settings.json` (UserPromptSubmit, Stop, SessionEnd, Notification, PostToolUse) | ver `docs/DISENO.html` |
| Config de Herdr | `%APPDATA%\herdr\config.toml` | `config/herdr.config.toml` |
| Arranque automático | carpeta Inicio de Windows, `Herdr server.vbs` | `startup/Herdr server.vbs` |
| Alias `agentnav` | perfiles de pwsh y de Windows PowerShell | una línea: `Set-Alias agentnav C:\AgentNav\agentnav.ps1` |
| Estado del hook | `%LOCALAPPDATA%\AgentNav\` (hook.log, journal\, working\, blocked\, blocked.flag) | no |

El hook **tiene que guardarse como UTF-8 con BOM**: Windows PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252.

## Uso

```
agentnav                     servidor arriba si hace falta + pestaña de Windows Terminal enganchada
agentnav list                proyectos, cuáles están abiertos, rama y cambios, cada agente con su estado
agentnav open <nombre>       abre el proyecto como espacio con sus agentes, o lo enfoca y repone los que falten
agentnav close <nombre>      cierra el espacio; a los Claude les manda /exit antes
agentnav pick                el selector (lo corre el popup de Herdr)
agentnav recent              carpetas donde usaste Claude Code y no están registradas
agentnav hoy [ayer|fecha]    diario del día: pedidos por proyecto, sesiones, tiempo trabajando
agentnav doctor              verifica Herdr, hooks, config, arranque, registro
agentnav ntfy-test           aviso de prueba al teléfono
```

Dentro de Herdr: `ctrl+b F1` muestra todas las teclas (en Herdr es `?`, que el teclado en español no entrega).

## projects.json

Cada proyecto: nombre, ruta y qué abrir. Un agente puede ser un string (nombre de un Claude) o un objeto.

```json
{
  "name": "Nevatars",
  "path": "C:\\Nevatars\\nevatars",
  "continue": true,
  "agents": [
    "qa",
    { "name": "logcat", "kind": "shell", "command": "adb logcat -s Unity", "split": "right", "ratio": 0.4 }
  ]
}
```

- `continue`: arranca Claude con `--continue` si hay una conversación guardada para esa carpeta. Por proyecto o por agente.
- `args`: argumentos crudos para el agente (`["--model", "opus"]`), por proyecto o por agente.
- `kind`: `claude` (default) o cualquier agente que Herdr conozca; `shell` es un panel común.
- `command`: sólo para `shell`, se ejecuta al abrir.
- `split`: `right` o `down`, parte el panel del agente anterior; sin `split`, pestaña propia. `ratio` entre 0 y 1.

Los paneles `shell` no se reponen al reabrir un proyecto ya abierto (no se distinguen de uno abierto a mano).

## settings.json

```json
{ "ntfy": { "topic": "", "server": "https://ntfy.sh", "min_seconds": 120 } }
```

Con `topic` vacío no hay avisos. Con topic, el hook publica cuando un turno termina o pide permiso y llevaba al menos
`min_seconds`. En el teléfono: app ntfy, suscribirse al mismo topic. El topic es público: elegí uno largo y raro.

## Requisitos

Windows 10/11, Herdr 0.9.5 o superior (canal estable), Python 3 con el lanzador `py`, Claude Code, Windows Terminal, git (opcional, para la columna de rama).
