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
| Plugin de Herdr | `herdr plugin link C:\AgentNav\plugin` (ganchos `tab.created` y `pane.created` → `agentnav adopt`) | `plugin\herdr-plugin.toml` |
| Estado del hook | `%LOCALAPPDATA%\AgentNav\` (hook.log, journal\, working\, blocked\, blocked.flag) | no |
| Tests | `py -X utf8 -m unittest discover -s tests` (funciones puras, sin Herdr ni red) | `tests\test_agentnav.py` |

El hook **tiene que guardarse como UTF-8 con BOM**: Windows PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252.

## Uso

```
agentnav                     servidor arriba si hace falta + pestaña de Windows Terminal enganchada
agentnav list                proyectos, cuáles están abiertos, rama y cambios, cada agente con su estado
agentnav open <nombre>       abre el proyecto como espacio con sus agentes, o lo enfoca y repone los que falten
agentnav new <nombre> [ruta] crea la carpeta (en C:\ o donde diga new_cwd de Herdr), la registra y la abre con su Claude
agentnav close <nombre>      cierra el espacio; a los Claude les manda /exit antes
agentnav tab [shell]         pestaña nueva en el espacio actual: misma carpeta que el panel de origen y el mismo agente (ctrl+b c); con shell, la pelada (ctrl+b shift+c)
agentnav adopt               lo corre el plugin de Herdr cuando nace una pestaña (el "+") o un panel (split): lo lleva al proyecto y arranca el agente
agentnav pick                el selector (lo corre el popup de Herdr)
agentnav recent              carpetas donde usaste Claude Code y no están registradas
agentnav hoy [ayer|fecha]    diario del día: pedidos por proyecto, sesiones, tiempo trabajando
agentnav doctor              verifica Herdr, hooks, config, arranque, registro
agentnav theme [nombre]      tema de colores de Herdr: selector (el popup ctrl+b alt+t), `theme list`, o aplica uno (cs16, matrix, procomm, o los de Herdr)
agentnav herdr-sync          instala el herdr.exe del fork con los temas compilados (settings.json → herdr_fork.repo); --force si hay agentes ocupados o para reinstalar el mismo tag
agentnav ntfy-test           aviso de prueba al teléfono
agentnav app                 lo que corre el acceso directo: servidor arriba, ventana de Herdr al frente o pestaña nueva
```

Temas: `ctrl+b`, soltar, `alt+t` abre el selector dentro de Herdr (flechas, Enter aplica y se ve al instante). La lista propia de Herdr (`ctrl+b s`) está compilada en el programa y no admite entradas nuevas; para tenerlas ahí hay un **Herdr propio** (ver abajo) y, con ése instalado, el selector escribe el nombre del tema como cualquier otro, sin bloque `custom`. Desde consola: `agentnav theme` lista y `agentnav theme matrix` aplica. Las paletas propias viven en `config\themes.json` (cs16 = consola de Counter-Strike 1.6, matrix, procomm = Procomm Plus de DOS) y se escriben como `[theme.custom]` sobre el tema base en el `config.toml`, con recarga inmediata. Pintan la interfaz de Herdr (barra lateral, pestañas, bordes, popup); el texto dentro de cada panel lo pinta el programa que corre ahí.

Dentro de Herdr: `ctrl+b F1` muestra todas las teclas (en Herdr es `?`, que el teclado en español no entrega).

Si tu prompt de shell es decorado (oh-my-posh, starship), poné en `settings.json` un `prompt_regex` que lo reconozca (el de fábrica entiende pwsh, cmd y bash); si no, `adopt` y `close` esperan 15 s y 5 s de más.

`ctrl+b c` y el `+` de la barra abren la pestaña nueva en la carpeta del panel actual y con el mismo agente: si venías en un Claude, arranca otro Claude ahí (conversación nueva, nunca `--continue`). Si el panel era un shell, toma el último agente vivo del espacio; si no hay, el agente registrado del proyecto; si tampoco, un shell. La pestaña pelada (shell en `new_cwd`) quedó en `ctrl+b shift+c`.

El `+` pasa por el plugin local `plugin\herdr-plugin.toml` (enlazado con `herdr plugin link C:\AgentNav\plugin`): Herdr dispara `agentnav adopt` en cada `tab.created`; `adopt` toma sólo las pestañas con la etiqueta numérica de Herdr (las del `+`), espera el prompt, cambia a la carpeta con la orden del shell que atiende el panel (`Set-Location` en pwsh, `cd /d` en cmd, `cd` en bash; lo mira con `pane process-info`) y arranca el agente en ese mismo panel. Las que ya traen nombre (las de `tab`, `open`, o `shell`) se dejan como están, y mientras `open` arma un espacio la adopción queda en pausa. `doctor` avisa si el plugin no está enlazado.

Los splits (`ctrl+b v`, `ctrl+b -` o el menú del panel) pasan por el mismo gancho con `pane.created`: un panel que nace en el `new_cwd` fijo (C:\) dentro de una pestaña que ya tenía otros se lleva a la carpeta del proyecto y arranca el mismo agente que el hermano más reciente de esa pestaña. Un panel creado con `--cwd` propio, o el panel raíz de una pestaña nueva (de ése se ocupa `tab.created`), se deja como está.

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
después pisa el exe. `doctor` dice si el exe instalado es el del fork, si `herdr update` lo pisó y si el fork tiene un
build más nuevo. Para volver al oficial: `herdr update`, o copiar `herdr.exe.oficial` sobre `herdr.exe`.

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
