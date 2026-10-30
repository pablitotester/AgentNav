# Revisión a fondo de AgentNav — Fable, 30/10/2026

Revisión de sólo lectura hecha por un subagente Fable sobre el repo en `4335506`. Nada fue modificado; cada hallazgo
dice CONFIRMED (reproducido o trazado en concreto) o PLAUSIBLE. Las copias vivas de los hooks y de `config.toml` son
byte-idénticas a las versionadas (hash verificado), el BOM del `.ps1` está, el `.cmd` NO tiene BOM (correcto).

Fixes declarados en DISENO que sí están en el código: `--message=` un solo token (ps1:265), `/exit` sólo a idle/done y
no bloqueados (py:869), mutex en la bandera (ps1:126), `idle_prompt` limpia marcas (ps1:240), `--no-optional-locks` +
`porcelain=v2` (py:569), `"agents": "qa"` como string (py:212), `pane run` sin JSON (py:697), poda de marcas a 12 h (ps1:113).

## Hallazgos, del más grave al más leve

### 1. `continue` puede hacer `--resume` de una conversación abierta FUERA de Herdr — PLAUSIBLE (alto impacto)
`agentnav.py:628-631` (`_continue_args`) → `last_herdr_session` (py:407-426). Busca en el diario el último sid con
pedidos dentro de un panel y lo excluye sólo si está vivo en otro panel de Herdr (`live_sids`, py:811). El chequeo
`claudes_outside_herdr` (py:636) corre únicamente en la rama de `--continue`, nunca en la de `--resume`.
Escenario: la conversación `qa` nació en Herdr. Cerrás Herdr, en WT hacés `claude --continue` (agarra esa misma) y
seguís. Después `agentnav open Nevatars` → `--resume <ese sid>` → dos Claude sobre el mismo `.jsonl`.
Fix: antes de devolver `--resume sid`, descartar sids que aparezcan en la línea de comandos de un claude.exe fuera de
Herdr (`_procs()` ya trae `cmd`; parsear `--resume X` / `-r X`); si hay un Claude afuera en esa carpeta lanzado con
`--continue` o sin args, excluir también el sid del `.jsonl` más nuevo. Si no se puede determinar, conversación nueva
con el aviso de py:637.

### 2. `restore_projects` compite con `resume_agents_on_restore = true` de Herdr: Claudes duplicados — PLAUSIBLE
`agentnav.py:839-856` espera hasta 3 s a que aparezcan los espacios (no a que Herdr termine de reanudar agentes) y
llama `open_project`; `_open_project` (py:809) ve `live` vacío porque Herdr todavía está lanzando su `claude --resume`
→ `missing` = todos → `_place_agents` con `live_sids` vacío → `last_herdr_session` devuelve el mismo sid → dos Claude
con `--resume` del mismo id. Además `_idle_shell_pane` (py:717-730) sólo reutiliza el panel si el espacio quedó con
exactamente un panel sin agente; Nevatars hoy tiene 3 pestañas → van a pestañas nuevas y quedan 3 shells vacíos
(README:104 dice "en ese mismo panel" sin esa condición).
Fix: tras ver los espacios, esperar a que ningún panel esté `launch_pending` / sin `agent` cambiando (sondear
`pane process-info` o `agents` hasta estabilizar 1-2 s); si el panel restaurado ya tiene `claude.exe` en primer plano,
no reponer. Verificación: `herdr server stop` + `agentnav up` y contar Claude por espacio en `agentnav list`.

### 3. `Set-Location -LiteralPath '{path}'`: comilla simple en la ruta rompe o inyecta — CONFIRMED por lectura
`agentnav.py:1181`. `path` viene de `projects.json` o del `cwd` de un panel (py:1173). `C:\it's\proj` → error de
parseo en pwsh, adopt lanza "no pude cambiar de carpeta". Si el `default_shell` no es pwsh/PowerShell, `Set-Location`
no existe y adopt falla siempre.
Fix: `path.replace("'", "''")`; leer `terminal.default_shell` (o `process-info`) para emitir `cd /d "<path>"` en cmd o
`cd '<path>'` en bash.

### 4. `PROMPT_RE` sólo reconoce `PS …>` y `$ ` al final exacto de la pantalla — PLAUSIBLE
`agentnav.py:665` `(PS [^\n]*> ?|\$ ?)$`. Probado: `'PS C:\x> '` ✓, `'❯ '` ✗, `'C:\x> '` ✗, `'PS C:\x> \n\n'` ✗.
Con oh-my-posh/starship o un prompt con salto final: `wait_prompt` nunca matchea → `_adopt_run` (py:1177-1178) lanza
error y deja la pestaña sin adoptar tras 15 s; `_start_shell` espera 10 s por panel; `close` 5 s por Claude.
Fix: ampliar el regex (`[>❯$#] ?\s*$`), configurable en `settings.json`; en adopt seguir tras el timeout en vez de `raise`.

### 5. El diario y `hook.log` pierden líneas con escrituras concurrentes — CONFIRMED (bajo estrés)
`hooks/agentnav-state.ps1:103-112` (`Append-Line`). `FileMode.Append` + `FileShare.ReadWrite` en .NET Framework no es
append atómico. Reproducido con 4 `powershell.exe` 5.1 corriendo la misma función: 1145 líneas de 1600 (28 %
perdidas), 40 mutiladas. En producción necesita dos hooks en la misma milésima, raro, pero DISENO 30/10 lo declara
"a prueba de concurrencia" y no lo es. El recorte de `hook.log` (ps1:279-282, `ReadAllLines`/`WriteAllLines`) también
puede tragarse una línea de otro hook.
Fix: mutex con nombre (`Local\AgentNavJournal`) alrededor de `Append-Line`, mismo patrón que `Sync-BlockedFlag`.

### 6. `new` y `pick → a` aceptan rutas relativas a la unidad y al cwd — CONFIRMED
`agentnav.py:262`: `os.path.abspath('C:AgentNav')` desde `C:\Nevatars\nevatars` da `C:\Nevatars\nevatars\AgentNav`;
desde `C:\AgentNav` dio `C:\AgentNav\AgentNav` (lo que pasó hoy). Lo mismo `..\x`. `cmd_pick` 'a' (py:1574-1577)
igual, y no valida el nombre (`cmd_new` sí, py:260).
Fix: `drive, tail = os.path.splitdrive(p)`; si `drive and tail[:1] not in '\\/'` → rechazar "ruta relativa a la
unidad: escribila como C:\…"; si `not os.path.isabs(p)` → unir con `new_project_base()` o rechazar; reusar la
validación de nombre en `pick`.

### 7. El servidor de Herdr heredó el entorno de un Claude — CONFIRMED (herencia) / PLAUSIBLE (impacto)
`agentnav.py:126-128` lanza `herdr server` con el entorno del proceso actual. El servidor vivo (pid 8524) tiene
`CLAUDECODE=1`, `CLAUDE_CODE_SESSION_ID=2ccf2691…` (sesión muerta), `CLAUDE_CODE_MESSAGING_TOKEN`,
`CLAUDE_CODE_CHILD_SESSION=1`, `CLAUDE_PID=26412` → el último `agentnav up` lo corrió un Claude desde su Bash. Herdr
limpia `CLAUDECODE` y `CLAUDE_CODE_*` al crear paneles, pero `CLAUDE_PID` llega a todos los paneles y a cada Claude
nuevo. `doctor` no lo detecta.
Fix: `Popen(..., env={k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "HERDR_"))})` en
`ensure_server`; en `doctor`, leer el entorno del servidor (PEB `ProcessParameters+0x80`, tamaño en `+0x3F0`) y
marcar error si hay `CLAUDE*`.

### 8. Respuesta de Herdr con forma inesperada → traceback sin aviso — PLAUSIBLE
`api()` (py:111-112) devuelve `{}` si `result` no es dict, y los llamadores indexan a ciegas: `r["pane"]["pane_id"]`
(py:712), `t["root_pane"]` (py:714, 1108), `r["workspace"]` (py:834). Un `KeyError` no es `AgentNavError`, así que
`_notify_error` (py:1077-1088) no lo atrapa: desde `ctrl+b c` o el plugin muere en silencio; desde `pick` cierra el
popup con traceback.
Fix: `_notify_error` captura `Exception`; `api()` acepta `need=("pane.pane_id",)` y lanza `AgentNavError` si falta.

### 9. `close`: snapshot único y texto a medio escribir en el input — bajo
`agentnav.py:862-876`. `polite` se decide con un snapshot y los `/exit` se mandan después; `send-text` agrega al input:
"revisá el tren" a medio escribir → se envía "revisá el tren/exit" como pedido real y `workspace close` lo mata a los
5 s. ¿Puede caer en un diálogo de permiso/confianza? Con el `hook.log` no: en el bloqueo de 15:32:21→15:40:32 no hubo
ningún `notify idle`, o sea `idle_prompt` no dispara con permiso pendiente, y el de confianza queda fuera por
`interactive_ready`/`launch_pending`. Queda la carrera de milisegundos entre snapshot y envío.
Fix: re-leer `agent get` justo antes de cada `send-text`; `send-keys ctrl+u`/`escape` antes de `/exit` (verificar qué
hace Esc en el prompt vacío de Claude Code).

### 10. `focus_herdr_window` sólo mira al padre directo del cliente — PLAUSIBLE, bajo
`agentnav.py:893-894`. Si el cliente corre dentro de una pwsh (`herdr` tipeado en una pestaña), el padre es pwsh sin
ventana → `attach(force=True)` abre otra pestaña aunque ya haya una.
Fix: subir la cadena de ancestros hasta un pid con ventana visible.

### 11. `.vbs` de inicio: el cwd del servidor depende de dónde lo lance explorer — PLAUSIBLE, bajo
`startup/Herdr server.vbs:5`. Fix: `sh.CurrentDirectory = sh.ExpandEnvironmentStrings("%USERPROFILE%")` antes del `Run`.

### 12. `adopt` depende de `tab_label` en `HERDR_PLUGIN_CONTEXT_JSON` — PLAUSIBLE, bajo
`agentnav.py:1143-1146`: si falta la clave, `label = ""` → "ya tiene nombre ('')" y el `+` deja de hacer algo sin aviso.
Fix: si falta, consultar `herdr tab get <tid>`.

### 13. Presupuesto de tiempo del hook en el peor caso — bajo
`agentnav-state.ps1:185` (herdr 4 s) + `Notify-Phone` (3 s + 3 s, ps1:158) + ~120 ms > el `timeout: 10` de
`settings.json` sólo si Herdr y ntfy cuelgan a la vez. Hoy 390-426 ms. Bajar ntfy a 2 s, nada más.

### 14. Datos sensibles en reposo — informativo
Cada pedido queda 300 caracteres en `working\<sid>` y en el diario para siempre (ps1:206, 138), 80 en `hook.log` y 80
van a Herdr (persiste en `session.json`). Una clave pegada en un prompt queda en tres lugares. Documentarlo junto al
aviso de ntfy; poda del diario a N días.

## Doctor: lo que no cubre
- Deriva entre copias: no compara `%USERPROFILE%\.claude\hooks\*` con `C:\AgentNav\hooks\*` ni `config.toml` con
  `config\herdr.config.toml`. Hash y listo.
- BOM al revés en el `.cmd`: `agentnav-unblock.cmd` NO debe tener BOM (`'@echo' no se reconoce`, error en cada
  herramienta). Doctor sólo chequea existencia (py:1386). Chequear `!= EF BB BF` y primera línea `@echo off`.
- Matcher de `Notification` (`permission_prompt|idle_prompt`): sólo se busca el comando (py:1391-1401).
- Python de 64 bits: `_process_table` devuelve `[]` en 32 bits (py:439-440) → `claudes_outside_herdr` = 0 siempre →
  `--continue` pisa conversaciones. Doctor no mira `struct.calcsize('P')`. README:112 pide "Python 3" a secas.
- `[session]`/`resume_agents_on_restore` (py:1364) se buscan como substring: una línea comentada pasa.
- Entorno del servidor con `CLAUDE*` (hallazgo 7).
- Prompt del shell: nada verifica que el prompt del `default_shell` matchee `PROMPT_RE` (hallazgo 4).

## Docs que no coinciden con el código
- DISENO "Pieza 3": `wt … powershell -NoExit -Command herdr`; el código corre `wt -w 0 new-tab --title Herdr <herdr.exe>` (py:950).
- DISENO E1 "tope 200 líneas" y 28/10 "recorte al pasar de 400": el hook recorta a 200 sólo cuando pasa de 100 KB (ps1:279-281).
- DISENO 30/10 "diario a prueba de concurrencia" (hallazgo 5).
- README:104-105 "repone los agentes en ese mismo panel": sólo si el espacio volvió con exactamente una pestaña (py:721-722).
- DISENO "doctor revisa las tres claves del config.toml": son cinco.
- README:112 "Python 3": 64 bits o el escaneo de procesos es un no-op silencioso.

## Lo que está bien
El `.cmd` de desbloqueo es correcto tal cual: `%VAR%` indefinido expande a vacío, la comparación con comillas aguanta
espacios, el `if exist` apunta a un archivo, y `CLAUDE_CODE_SESSION_ID` sí llega a los hooks. El `.ps1` no escribe en
stdout, sale 0 siempre, el quoting según `CommandLineToArgvW` está bien, el tope de 4 s a herdr está y va antes del
ntfy, y los controles/ESC/NUL se sacan antes de la línea de comandos, el log y el diario. En `agentnav.py` no hay
`shell=True`: todo va por lista de argv. Escritura atómica de `projects.json`, `utf-8-sig` en lecturas, lru_cache en
el escaneo de procesos, offsets x64 del PEB correctos (`ProcessParameters` 0x20, `CurrentDirectory` 0x38,
`CommandLine` 0x70), git en hilos con `--no-optional-locks`, `_console_utf8` resuelve lo que `py -I` ignora.

## Cómo se verificó
- Lectura completa de `agentnav.py`, los dos hooks, `projects.json`, `config/herdr.config.toml`, `README.md`,
  `docs/DISENO.html`, `plugin/herdr-plugin.toml`, `agentnav.ps1`, los dos `.vbs`, `settings*.json`, `.gitignore`,
  `~/.claude/settings.json`, `~/.claude/hooks/herdr-agent-state.ps1`, ambos perfiles de PowerShell.
- Sólo lectura: `agentnav list|doctor|recent|hoy`; `herdr --help` y los de `pane/workspace/agent/tab/plugin`,
  `pane list`, `workspace list`, `api snapshot`, `status server`, `plugin list --json`, `pane process-info`, formato
  de error de `pane get nope` / `workspace focus zz`, `--default-config`.
- Hashes y primeros bytes de hooks vivos vs versionados y de `config.toml`; `git ls-files`, `rev-parse HEAD`, `log`.
- Funciones puras importando el módulo (`py -X utf8 -I`): `abspath`, `agent_name`, `claude_project_key`,
  `has_conversation`, `last_herdr_session`, `claudes_outside_herdr`, `_procs`/`_under_herdr`, `herdr_processes`,
  `new_project_base`, `PROMPT_RE` contra 7 prompts, `_norm_agent`, `_secs`, `find_project`, `_tab_path`, `read_journal`.
- Bloque de entorno (PEB) del servidor de Herdr, del cliente, de un pwsh de panel y de tres `claude.exe`.
- Concurrencia de `Append-Line` con 4 `powershell.exe` 5.1 × 400 líneas: 1145/1600 líneas, 40 mutiladas.
- `pwsh -NoLogo -c prompt` con y sin perfil; `hook.log` (sin TIMEOUT ni ERR) y `herdr-server.log`.
