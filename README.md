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
| Herdr como app | `Herdr.lnk` en el escritorio → `wscript C:\AgentNav\Herdr.vbs` (sin consola) → `agentnav app` | `Herdr.vbs` |
| Plugin de Herdr | `herdr plugin link C:\AgentNav\plugin` (gancho `tab.created` → `agentnav adopt`) | `plugin\herdr-plugin.toml` |
| Estado del hook | `%LOCALAPPDATA%\AgentNav\` (hook.log, journal\, working\, blocked\, blocked.flag) | no |

El hook **tiene que guardarse como UTF-8 con BOM**: Windows PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252.

## Uso

```
agentnav                     servidor arriba si hace falta + pestaña de Windows Terminal enganchada
agentnav list                proyectos, cuáles están abiertos, rama y cambios, cada agente con su estado
agentnav open <nombre>       abre el proyecto como espacio con sus agentes, o lo enfoca y repone los que falten
agentnav new <nombre> [ruta] crea la carpeta (en C:\ o donde diga new_cwd de Herdr), la registra y la abre con su Claude
agentnav close <nombre>      cierra el espacio; a los Claude les manda /exit antes
agentnav tab [shell]         pestaña nueva en el espacio actual: misma carpeta que el panel de origen y el mismo agente (ctrl+b c); con shell, la pelada (ctrl+b shift+c)
agentnav adopt               lo corre el plugin de Herdr cuando el "+" de la barra crea una pestaña: la lleva al proyecto y arranca el agente
agentnav pick                el selector (lo corre el popup de Herdr)
agentnav recent              carpetas donde usaste Claude Code y no están registradas
agentnav hoy [ayer|fecha]    diario del día: pedidos por proyecto, sesiones, tiempo trabajando
agentnav doctor              verifica Herdr, hooks, config, arranque, registro
agentnav ntfy-test           aviso de prueba al teléfono
agentnav app                 lo que corre el acceso directo: servidor arriba, ventana de Herdr al frente o pestaña nueva
```

Dentro de Herdr: `ctrl+b F1` muestra todas las teclas (en Herdr es `?`, que el teclado en español no entrega).

`ctrl+b c` y el `+` de la barra abren la pestaña nueva en la carpeta del panel actual y con el mismo agente: si venías en un Claude, arranca otro Claude ahí (conversación nueva, nunca `--continue`). Si el panel era un shell, toma el último agente vivo del espacio; si no hay, el agente registrado del proyecto; si tampoco, un shell. La pestaña pelada (shell en `new_cwd`) quedó en `ctrl+b shift+c`.

El `+` pasa por el plugin local `plugin\herdr-plugin.toml` (enlazado con `herdr plugin link C:\AgentNav\plugin`): Herdr dispara `agentnav adopt` en cada `tab.created` desde la interfaz, y `adopt` espera el prompt, hace `Set-Location` a la carpeta y arranca el agente en ese mismo panel. Las pestañas creadas por la API (las de `tab`, `open` o cualquier script) se dejan como están. `doctor` avisa si el plugin no está enlazado.

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

- `continue`: retoma la última conversación que tuvo pedidos **dentro de Herdr** en esa carpeta (`--resume <id>`, según el
  diario). Si no hay ninguna, `--continue` sólo cuando ningún otro Claude corre en esa carpeta (otro agente del proyecto o
  uno en otra terminal): `--continue` agarra la conversación más nueva y pisaría la que está abierta afuera. Por proyecto o por agente.
- `args`: argumentos crudos para el agente (`["--model", "opus"]`), por proyecto o por agente.
- `kind`: `claude` (default) o cualquier agente que Herdr conozca; `shell` es un panel común.
- `command`: sólo para `shell`, se ejecuta al abrir.
- `split`: `right` o `down`, parte el panel del agente anterior; sin `split`, pestaña propia. `ratio` entre 0 y 1.

Los paneles `shell` no se reponen al reabrir un proyecto ya abierto (no se distinguen de uno abierto a mano).

## settings.json

```json
{ "ntfy": { "topic": "", "server": "https://ntfy.sh", "min_seconds": 120, "min_seconds_blocked": 0 } }
```

Con `topic` vacío no hay avisos. Con topic, el hook publica cuando un turno termina y llevaba al menos `min_seconds`,
y cuando pide permiso y llevaba al menos `min_seconds_blocked` (0: siempre, porque el permiso suele pedirse a los
pocos segundos). En el teléfono: app ntfy, suscribirse al mismo topic. **El topic de ntfy.sh es público y adivinable**:
viaja el nombre de la carpeta y los primeros 160 caracteres del pedido. Elegí un nombre largo y al azar, o usá un
servidor propio.

## Límites conocidos del estado

- `Stop` no dispara si interrumpís con Esc: queda working hasta el `idle_prompt` (~1 min) o el siguiente pedido.
- Denegar un permiso no genera `PostToolUse`: queda blocked hasta que termine ese turno.
- Claude manda la notificación de permiso recién cuando el pedido lleva un rato esperando; Herdr lo detecta por
  pantalla antes, así que el panel se pone en rojo igual.
- El hook de desbloqueo sólo lanza PowerShell si existe la marca de **esa** sesión (`CLAUDE_CODE_SESSION_ID`);
  cuesta ~60 ms por herramienta en el resto de los casos.
- Tras reiniciar el servidor (`herdr server stop` + `agentnav up`), Herdr restaura los espacios con un panel vacío;
  `agentnav`, `up` y `open` reponen los agentes de los proyectos registrados en ese mismo panel.
- `agentnav open` desde fuera de Herdr no abre otra pestaña si ya hay un cliente de Herdr abierto; `agentnav attach` sí.
- El servidor de Herdr retiene como directorio actual la carpeta desde la que se lo arrancó: levantalo con `agentnav up`
  (o el `.vbs` de inicio), nunca desde la carpeta de un proyecto. `doctor` lo verifica.

## Requisitos

Windows 10/11, Herdr 0.9.5 o superior (canal estable), Python 3 con el lanzador `py`, Claude Code, Windows Terminal, git (opcional, para la columna de rama).
