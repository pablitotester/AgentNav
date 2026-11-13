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
| Registro de proyectos | `C:\AgentNav\projects.json` | `projects.example.json` (el real no se versiona: rutas de cada PC) |
| Ajustes (avisos ntfy) | `C:\AgentNav\settings.json` | `settings.example.json` (el real no se versiona) |
| Hook de Claude Code | `%USERPROFILE%\.claude\hooks\agentnav-state.ps1` | `hooks/agentnav-state.ps1` |
| Puerta del desbloqueo | `%USERPROFILE%\.claude\hooks\agentnav-unblock.cmd` | `hooks/agentnav-unblock.cmd` |
| Registro de los hooks | `%USERPROFILE%\.claude\settings.json` (UserPromptSubmit, Stop, SessionEnd, Notification, PostToolUse) | ver `docs/DISENO.html` |
| Config de Herdr | `%APPDATA%\herdr\config.toml` | `config/herdr.config.toml` |
| Arranque automático | carpeta Inicio de Windows, `Herdr server.vbs` | `startup/Herdr server.vbs` |
| Alias `agentnav` | perfiles de pwsh y de Windows PowerShell | una línea: `Set-Alias agentnav C:\AgentNav\agentnav.ps1` |
| Herdr como app | `Herdr.lnk` en el escritorio → `wscript C:\AgentNav\Herdr.vbs` (sin consola) → `agentnav app` | `Herdr.vbs` |
| Plugin de Herdr | `herdr plugin link C:\AgentNav\plugin` (ganchos `tab.created` y `pane.created` → `agentnav adopt`; `pane.focused` → `plugin\focus.py`) | `plugin\herdr-plugin.toml` |
| Estado del hook | `%LOCALAPPDATA%\AgentNav\` (hook.log, journal\, working\, blocked\, blocked.flag) | no |
| Tests | `py -X utf8 -m unittest discover -s tests` (funciones puras, sin Herdr ni red) | `tests\test_agentnav.py` |

El hook **tiene que guardarse como UTF-8 con BOM**: Windows PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252.

**Actualizar:** `C:\AgentNav` es un clon de `https://github.com/pablitotester/AgentNav`; `agentnav update` trae lo nuevo (`git pull --ff-only`, no toca nada si hay cambios locales sin commitear) y vuelve a copiar a su lugar los hooks, el `.vbs` de Inicio y el `config.toml` de Herdr (con respaldo `config.toml.bak-fecha` y recarga del servidor). `doctor` avisa cuando origin tiene commits nuevos, y `agentnav app` (el acceso directo) hace el mismo chequeo al arrancar, en paralelo con el servidor, y si hay algo nuevo lo muestra como notificación dentro de Herdr (`herdr notification show`); sin red o sin clon no molesta.

## Uso

```
agentnav                     servidor arriba si hace falta + pestaña de Windows Terminal enganchada
agentnav list                proyectos, cuáles están abiertos, rama y cambios, cada agente con su estado
agentnav open <nombre>       abre el proyecto como espacio con sus agentes, o lo enfoca y repone los que falten
agentnav new <nombre> [ruta] crea la carpeta (en C:\ o donde diga new_cwd de Herdr), la registra y la abre con su agente; --kind gemini (o --gemini) para que sea un Gemini
agentnav close <nombre>      cierra el espacio; a los agentes les manda /exit (Claude) o /quit (Gemini) antes
agentnav tab [shell|agent]   pestaña nueva en el espacio actual: un shell en la misma carpeta que el panel de origen, sin agente (ctrl+b c); con shell, la pelada (ctrl+b shift+c); con agent, además el mismo agente
agentnav adopt               lo corre el plugin de Herdr cuando nace una pestaña (el "+") o un panel (split): lo lleva a la carpeta del proyecto, sin arrancar agente
agentnav pick                el selector (lo corre el popup de Herdr)
agentnav recent              carpetas donde usaste Claude Code o Gemini CLI y no están registradas (con cuál)
agentnav hoy [ayer|fecha]    diario del día: pedidos por proyecto, sesiones, tiempo trabajando
agentnav doctor              verifica Herdr, hooks, config, arranque, registro; avisa si origin tiene commits nuevos
agentnav update [--check]    git pull --ff-only de origin y re-copia hooks, arranque y config de Herdr (con respaldo); --check sólo avisa (sale 10 si hay nuevos)
agentnav theme [nombre]      tema de colores de Herdr: selector (el popup ctrl+b alt+t), `theme list`, o aplica uno (cs16, matrix, procomm, o los de Herdr)
agentnav herdr-sync          instala el herdr.exe del fork con los temas compilados (settings.json → herdr_fork.repo); compara SHA-256, así que también reinstala un rebuild del mismo tag; --force si hay agentes ocupados o para reinstalar el mismo exe
agentnav ntfy-test           aviso de prueba al teléfono
agentnav labels              pone ya la etiqueta "<agente> · <tarea>" a todos los paneles con agente (`app` lo hace solo al arrancar)
agentnav app                 lo que corre el acceso directo: servidor arriba, ventana de Herdr al frente o pestaña nueva; de paso `update --check` y aviso en Herdr si origin tiene commits nuevos
```

Temas: `ctrl+b`, soltar, `alt+t` abre el selector dentro de Herdr (flechas, Enter aplica y se ve al instante). La lista propia de Herdr (`ctrl+b s`) está compilada en el programa y no admite entradas nuevas; para tenerlas ahí hay un **Herdr propio** (ver abajo) y, con ése instalado, el selector escribe el nombre del tema como cualquier otro, sin bloque `custom`. Desde consola: `agentnav theme` lista y `agentnav theme matrix` aplica. Las paletas propias viven en `config\themes.json` (cs16 = consola de Counter-Strike 1.6, matrix, procomm = Procomm Plus de DOS) y se escriben como `[theme.custom]` sobre el tema base en el `config.toml`, con recarga inmediata. Pintan la interfaz de Herdr (barra lateral, pestañas, bordes, popup); el texto dentro de cada panel lo pinta el programa que corre ahí.

Dentro de Herdr: `ctrl+b F1` muestra todas las teclas (en Herdr es `?`, que el teclado en español no entrega).

Si tu prompt de shell es decorado (oh-my-posh, starship), poné en `settings.json` un `prompt_regex` que lo reconozca (el de fábrica entiende pwsh, cmd y bash); si no, `adopt` y `close` esperan 15 s y 5 s de más.

`ctrl+b c` y el `+` de la barra abren la pestaña nueva con un shell en la carpeta del panel donde estabas, con el nombre de esa carpeta como etiqueta. "Donde estabas" es la carpeta del panel de origen si está dentro del proyecto del espacio (una subcarpeta donde venías trabajando); si ese panel estaba afuera (un shell suelto en `C:\`), manda la carpeta del proyecto. No arrancan ningún agente: el Claude lo lanzás vos cuando lo querés (hasta el 4/11 abrían otro Claude ahí; `agentnav tab agent` todavía lo hace, si querés atarlo a una tecla). La pestaña pelada (shell en `new_cwd`) quedó en `ctrl+b shift+c`.

El `+` pasa por el plugin local `plugin\herdr-plugin.toml` (enlazado con `herdr plugin link C:\AgentNav\plugin`): Herdr dispara `agentnav adopt` en cada `tab.created`; `adopt` toma sólo las pestañas con la etiqueta numérica de Herdr (las del `+`), las renombra con el nombre de la carpeta, espera el prompt y cambia a la carpeta con la orden del shell que atiende el panel (`Set-Location` en pwsh, `cd /d` en cmd, `cd` en bash; lo mira con `pane process-info`). Ahí termina: el panel queda como shell, sin agente. Como los eventos `tab.created` y `pane.created` sólo describen lo nuevo, el plugin también escucha `pane.focused` y anota cada cambio de foco en `%LOCALAPPDATA%\AgentNav\focus.log` (`plugin\focus.py`, sin importar `agentnav.py`); `adopt` toma de ahí el último panel enfocado que no sea el nuevo. Tras cambiar los ganchos del plugin hay que re-enlazarlo (`herdr plugin unlink agentnav; herdr plugin link C:\AgentNav\plugin`); `doctor` lo avisa. Las que ya traen nombre (las de `tab`, `open`, o `shell`) se dejan como están, y mientras `open` arma un espacio la adopción queda en pausa. `doctor` avisa si el plugin no está enlazado.

Los splits (`ctrl+b v`, `ctrl+b -` o el menú del panel) pasan por el mismo gancho con `pane.created`: un panel que nace en el `new_cwd` fijo (C:\) dentro de una pestaña que ya tenía otros se lleva a la carpeta del panel desde donde se dividió (el último enfocado de esa pestaña según el rastro; sin rastro, el que quedó pegado al nuevo en el layout; si tampoco, el agente más reciente de la pestaña), como shell, sin agente y con el nombre de la carpeta en el borde. Un panel creado con `--cwd` propio, o el panel raíz de una pestaña nueva (de ése se ocupa `tab.created`), se deja como está.

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
  Con `kind: gemini` hace lo mismo con las sesiones de Gemini (ver **Gemini CLI**); con otros tipos no tiene efecto.
- `args`: argumentos crudos para el agente (`["--model", "opus"]`), por proyecto o por agente.
- `kind`: `claude` (default), `gemini` o cualquier agente que Herdr conozca; `shell` es un panel común.
- `command`: sólo para `shell`, se ejecuta al abrir.
- `split`: `right` o `down`, parte el panel del agente anterior; sin `split`, pestaña propia. `ratio` entre 0 y 1.

Los paneles `shell` no se reponen al reabrir un proyecto ya abierto (no se distinguen de uno abierto a mano).

## settings.json

```json
{ "ntfy": { "topic": "", "server": "https://ntfy.sh", "min_seconds": 120, "min_seconds_blocked": 0 },
  "prompt_regex": "", "journal_days": 90, "herdr_fork": { "repo": "" } }
```

`prompt_regex`: regex (sintaxis de Rust) del prompt del shell si el de fábrica no lo reconoce. `journal_days`: cuántos
días se conserva el diario de `%LOCALAPPDATA%\AgentNav\journal` (el hook borra los días más viejos al cerrar una sesión;
0 = nunca). `herdr_fork.repo`: el fork de Herdr con los temas compilados, para `herdr-sync` y `doctor`.

Con `topic` vacío no hay avisos. Con topic, el hook publica cuando un turno termina y llevaba al menos `min_seconds`,
y cuando pide permiso y llevaba al menos `min_seconds_blocked` (0: siempre, porque el permiso suele pedirse a los
pocos segundos). En el teléfono: app ntfy, suscribirse al mismo topic. **El topic de ntfy.sh es público y adivinable**:
viaja el nombre de la carpeta y los primeros 160 caracteres del pedido. Elegí un nombre largo y al azar, o usá un
servidor propio.

## Gemini CLI

### Instalar Gemini

El instalador no trae Gemini CLI salvo que se lo pidas: `install.ps1 -ConGemini` (apagado por defecto). Con eso agrega
dos requisitos, **Node.js LTS** (winget `OpenJS.NodeJS.LTS`; sin winget, el `.msi` x64 de la última LTS según
`nodejs.org/dist/index.json`) y **Gemini CLI** (`npm install -g @google/gemini-cli`, que deja `gemini.cmd` en
`%APPDATA%\npm`), y en el paso de hooks corre `configurar.py gemini-hooks` para registrar `agentnav-state.ps1` en
`%USERPROFILE%\.gemini\settings.json` sin tocar lo demás que haya ahí (Antigravity guarda lo suyo en esa carpeta), con
backup. Herdr 0.9.5 no tiene `herdr integration install gemini`, así que no hay hook propio de Herdr para Gemini. Con
`-SinRequisitos -ConGemini` sólo registra los hooks y avisa si falta `gemini`. La primera vez que corre, Gemini pide
iniciar sesión con una cuenta de Google.

### Proyectos y agentes Gemini

Un proyecto o un agente con `"kind": "gemini"` arranca Gemini CLI en vez de Claude Code (Herdr lo conoce: `agent start
--kind gemini`). `agentnav new Obra --kind gemini` (o `--gemini`) lo registra así de entrada; en `projects.json` se
puede mezclar, por ejemplo un Claude y un Gemini en el mismo proyecto:

```json
{ "name": "Obra", "path": "C:\\Obra", "continue": true,
  "agents": [ "obra", { "name": "gem", "kind": "gemini", "args": ["-m", "gemini-3.1-flash-lite"] } ] }
```

El modelo se fija con `args` en el agente (o en el proyecto): `["-m", "gemini-3.1-flash-lite"]`; sin `-m` Gemini usa su
modelo por defecto, que al 13/11 (0.68.0, `gemini-3.8-flash`) respondía 503 en bucle, y `gemini-2.5-flash` ya no existe.
`gemini --list-models` muestra los disponibles.

Gemini guarda sus sesiones por carpeta en `%USERPROFILE%\.gemini\tmp\<id>\chats\session-<fecha>-<8 del id>.jsonl`;
el `<id>` sale del registro `%USERPROFILE%\.gemini\projects.json` (ruta en minúsculas → id corto; cada carpeta `tmp\<id>`
lleva además un `.project_root` con la ruta dueña) y `GEMINI_CLI_HOME` cambia esa raíz. Con eso `continue` sigue la
misma regla que con Claude: retoma por `--resume <uuid>` la última sesión que tuvo pedidos dentro de Herdr en esa
carpeta (según el diario; el hook anota el id de sesión de Gemini igual que el de Claude) siempre que no esté viva en
otro panel ni en una terminal ajena; sin una, `--resume latest` (la más nueva de la carpeta) sólo si ningún otro Gemini
corre ahí, porque dos Gemini sobre la misma sesión se pisan. Sin sesiones guardadas no manda nada: `--resume latest`
sin sesiones termina con error. Un Gemini de afuera se reconoce por su proceso `node …\@google\gemini-cli\bundle\gemini.js`
y el id que lleve en `--resume`/`-r`/`--session-id`.

`close` le manda `/quit` a cada Gemini en el prompt (a Claude, `/exit`). `recent` lista también las carpetas con sesiones
de Gemini, con una columna que dice cuál agente las usó. `doctor` muestra un bloque "Gemini CLI" sólo cuando `gemini`
está en el PATH o algún proyecto lo usa: versión instalada y si los seis hooks nuestros están en
`%USERPROFILE%\.gemini\settings.json` (`SessionStart`, `BeforeAgent`, `AfterAgent`, `SessionEnd`, `Notification`,
`AfterTool`, todos con `agentnav-state.ps1 <acción> gemini` o `agentnav-unblock.cmd gemini`); si faltan, el estado de
cada Gemini no llega a Herdr y lo pone el instalador (`installer\install.ps1 -ConGemini`). También avisa si el login es
por clave (`security.auth.selectedType` = `gemini-api-key`) y no hay `GEMINI_API_KEY` ni en `%USERPROFILE%\.gemini\.env`
ni en el entorno, o si no hay ningún tipo de login elegido ni clave (Gemini lo pide al arrancar y el panel queda ahí).

### Hook de Gemini

El mismo `agentnav-state.ps1` atiende a Gemini CLI: se registra en `%USERPROFILE%\.gemini\settings.json` con el
segundo argumento `gemini` (`configurar.py gemini-hooks <settings.json de Gemini> <carpeta de hooks>`, que respeta
lo que ya haya en ese archivo, por ejemplo los `mcpServers` de Antigravity, y deja un `.bak-agentnav-<fecha>`).
Eventos: SessionStart → `start` (idle + id de sesión y `gemini --resume <id>` como comando de reanudación, lo que
para Claude hace el hook de Herdr), BeforeAgent → `prompt`, AfterAgent → `stop`, SessionEnd → `end`, Notification
(ToolPermission) → `notify`, AfterTool → `& agentnav-unblock.cmd gemini` (Gemini corre los comandos en PowerShell; la
puerta mira `GEMINI_SESSION_ID`). Estado, etiqueta del panel, diario y aviso ntfy
funcionan igual que con Claude; el registro de Claude no cambia. Diferencias: Gemini no manda `idle_prompt`, así que
un turno cortado con Esc queda "working" hasta el próximo evento; en el título de la terminal pone sólo su estado
("◇ Ready (carpeta)", "✦ Working… (carpeta)"), así que la etiqueta del panel lleva el último pedido o, sin pedido, el
nombre solo; el permiso llega como `ToolPermission` con `details.title` y `details.type` (`exec` = run_shell_command,
`edit` = write_file o replace, sin nombre: lo desbloquea el AfterTool siguiente); `/clear` cambia el id de sesión;
`/quit` manda SessionEnd dos veces (la segunda se ignora, marca `ended\<sid>`); y su `timeout` de hook se cuenta en
milisegundos (10000).

## Herdr propio: los temas dentro de la pantalla de settings

Herdr no tiene temas de usuario, así que las tres paletas aparecen en `ctrl+b s → theme` sólo con un `herdr.exe` compilado
desde un fork. El fork vive en GitHub (`settings.json → herdr_fork.repo`), rama `agentnav`: el código oficial del último
tag más **un solo commit** que agrega `src/app/palette_agentnav.rs` y tres líneas por archivo en `theme.rs`, `state.rs` y
`mod.rs`. Un workflow (`.github/workflows/agentnav-build.yml`) corre a diario: si upstream publicó un tag nuevo, rebasa el
commit, compila `herdr.exe` para Windows con el mismo toolchain, Zig y flags que el release oficial, corre los tests de
temas y publica un release `agentnav-vX.Y.Z`. Si el rebase choca, abre un issue en el fork y no publica.

En la PC, `agentnav herdr-sync` baja ese release, verifica el SHA-256, guarda el oficial como `herdr.exe.oficial`, para el
servidor, reemplaza el exe y levanta todo de nuevo (`agentnav app`). Si el fork va por una versión más nueva que la
instalada, antes corre `herdr update` para que el instalador oficial traiga su carpeta y sus archivos de conpty, y recién
después pisa el exe. Tanto `herdr-sync` como `doctor` comparan el SHA-256 del exe instalado con el del asset
`herdr.exe.sha256` del último release, no sólo el tag: si el workflow republicó `agentnav-vX.Y.Z` con otro parche de temas
(mismo tag, otro exe), `doctor` avisa "el fork republicó ... con otro build" y `herdr-sync` lo instala sin `--force`.
`doctor` dice además si el exe instalado es el del fork, si `herdr update` lo pisó, si el fork tiene una versión más
nueva y si está registrada la tarea programada "AgentNav Herdr update" (el chequeo automático que deja
`herdr-fork\install.ps1`). Para volver al oficial: `herdr update`, o copiar `herdr.exe.oficial` sobre `herdr.exe`.

**Otra PC desde cero (la de casa):** el release del fork trae también el zip completo con conpty y un manifiesto
`agentnav-latest.json` con la misma forma que `herdr.dev/latest.json`, así que el instalador oficial de Herdr lo instala
como si fuera una versión normal. Una línea en PowerShell:

```
irm https://raw.githubusercontent.com/pablitotester/herdr/agentnav/agentnav/install.ps1 | iex
```

Corre el instalador oficial de esa misma versión apuntado al manifiesto del fork (carpeta, junction `current`, PATH,
conpty), y si esa versión ya estaba con el exe oficial, cierra Herdr, pone el del fork verificando el SHA-256 y deja el
marcador. No instala AgentNav: para eso está el paquete de abajo.

Copias de referencia del parche, el workflow y el instalador: `herdr-fork\` en este repo.

## Instalar en otra PC (paquete para un amigo)

`installer\build.ps1` arma `dist\AgentNav-setup.zip` (~90 KB): una copia del repo sin `settings.json` (trae tu topic de
ntfy) ni `projects.json`, más `Instalar.cmd`, `install.ps1`, `configurar.py` y un `LEEME.txt`.

```
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\build.ps1
```

El que lo recibe descomprime el zip y hace doble clic en `Instalar.cmd` (sin administrador). El instalador, en orden y
salteando lo que ya esté: instala **Python 3.12 de 64 bits con `py`, git, PowerShell 7, Windows Terminal, Claude Code y
Herdr** (con winget; sin winget, Python, git y pwsh se bajan de su sitio oficial / GitHub; Herdr es el del fork con los
temas, o el oficial con `-HerdrOficial`); deja el repo en `C:\AgentNav` (ruta fija: la config de Herdr, el plugin y los
`.vbs` la tienen escrita) como clon de `github.com/pablitotester/AgentNav` si hay git y acceso, o copiando el payload del zip
(`-SinGit` fuerza la copia); crea `settings.json` desde el ejemplo con `herdr_fork.repo` y un `projects.json` vacío; pone
los hooks en `~\.claude\hooks` y los registra en el `settings.json` de Claude sin tocar lo demás (`configurar.py`, con
backup); `herdr integration install claude`; el `config.toml` de Herdr (con backup del anterior); `herdr plugin link`;
`Herdr server.vbs` en Inicio; el alias en los dos perfiles; el acceso directo del escritorio; y termina con `agentnav up`
y `agentnav doctor`. Volver a correrlo actualiza sin perder `settings.json` ni `projects.json`. Las funciones de
`configurar.py` se prueban en `tests\test_installer.py`.

Mandalo por WhatsApp, Drive o un pendrive: Gmail rechaza zips con `.cmd` adentro.

## Etiqueta de cada panel

Arriba de cada panel con agente, en el borde, Herdr muestra `<agente> · <tarea>`: el nombre que le dio Herdr al agente
(el mismo de la barra lateral) y el título que Claude Code le pone solo a la conversación a medida que avanza. Mientras
la conversación es nueva y el título sigue en "Claude Code", va el principio del último pedido. Lo escribe el hook en
cada prompt, Stop y notificación con `pane report-metadata --title` (no toca el nombre del agente ni el del panel), y
lo borra al cerrar la sesión. Al arrancar un agente desde `open` o `tab`, AgentNav pone el nombre solo hasta el primer
pedido. Un panel sin agente no lleva etiqueta; si se lanza `claude` a mano en esa consola, aparece con su primer pedido.
Herdr recorta el texto si el panel es angosto. Un panel idle no genera eventos, así que `agentnav app` (el acceso
directo) etiqueta a todos los agentes vivos al arrancar, y `agentnav labels` lo hace a mano cuando haga falta.

## Límites conocidos del estado

- `Stop` no dispara si interrumpís con Esc: queda working hasta el `idle_prompt` (~1 min) o el siguiente pedido.
- Denegar un permiso no genera `PostToolUse`: queda blocked hasta que termine ese turno.
- Claude manda la notificación de permiso recién cuando el pedido lleva un rato esperando; Herdr lo detecta por
  pantalla antes, así que el panel se pone en rojo igual.
- El hook de desbloqueo sólo lanza PowerShell si existe la marca de **esa** sesión (`CLAUDE_CODE_SESSION_ID`);
  cuesta ~60 ms por herramienta en el resto de los casos.
- Tras reiniciar el servidor (`herdr server stop` + `agentnav up`), Herdr restaura los espacios y, con
  `resume_agents_on_restore`, relanza cada Claude unos segundos después. `agentnav`, `up` y `open` esperan a que eso
  termine y reponen sólo los que falten: en el panel vacío si el espacio volvió con un solo panel sin agente, si no en
  pestañas nuevas.
- `continue` nunca retoma una conversación que esté abierta en una terminal ajena a Herdr (mira la línea de comandos
  de cada `claude.exe`); en ese caso arranca una nueva y lo dice.
- Cada pedido queda guardado en texto plano: 300 caracteres en el diario y en `working\<sid>`, 80 en `hook.log` y 80
  van a Herdr (`session.json`). Una clave pegada en un prompt queda en esos lugares; el diario se poda a `journal_days`
  días (90), el resto se recicla solo.
- `agentnav open` desde fuera de Herdr no abre otra pestaña si ya hay un cliente de Herdr abierto; `agentnav attach` sí.
- El servidor de Herdr retiene como directorio actual la carpeta desde la que se lo arrancó: levantalo con `agentnav up`
  (o el `.vbs` de inicio), nunca desde la carpeta de un proyecto. `doctor` lo verifica.

## Requisitos

Windows 10/11, Herdr 0.9.5 o superior (canal estable), Python 3.11+ de 64 bits con el lanzador `py` (en 32 bits el escaneo de procesos no funciona), Claude Code, Windows Terminal, git (opcional, para la columna de rama).
