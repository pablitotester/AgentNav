# Rama `agentnav` de este fork de Herdr

Herdr oficial más **cinco temas extra** que aparecen en Settings (`ctrl+b s → theme`) junto a los de fábrica:

| nombre    | qué es                                                                 |
|-----------|------------------------------------------------------------------------|
| `cs16`    | consola de Counter-Strike 1.6 (GoldSrc): paneles verde oliva, texto arena, naranja |
| `matrix`  | negro y fósforo verde                                                  |
| `procomm` | Procomm Plus de DOS: azul CGA, texto blanco, resaltes amarillo y cian   |
| `ambar`   | monitor retro de fósforo ámbar: fondo negro, letras ámbar             |
| `miami`   | atardecer de Vice City: violeta, púrpura, magenta, coral, naranja      |

Y un **árbol de carpetas con agentes** en la sección de agentes del sidebar (ver «Árbol de carpetas»).

Herdr no tiene temas de usuario: la lista de Settings sale de `THEME_NAMES` en `src/config/theme.rs` y cada paleta es
una función en `src/app/state.rs`. Por eso el único camino es compilar.

## Qué toca el parche (un solo commit sobre el tag de upstream)

- `src/app/palette_agentnav.rs` — **nuevo**: las cinco paletas (`impl Palette { fn cs16() … }`).
- `src/app/mod.rs` — una línea: `mod palette_agentnav;`.
- `src/config/theme.rs` — cinco nombres en `THEME_NAMES` y cinco brazos en `canonical_theme_name`.
- `src/app/state.rs` — cinco brazos en `Palette::from_name`.
- `src/update.rs` — una constante: `STABLE_UPDATE_MANIFEST_URL` apunta al manifiesto del fork (ver «Updates automáticos»).
- `src/client/shell/folder_tree.rs` — **nuevo**: el árbol de carpetas (estado, lectura de carpetas, render, clicks, tests).
- Enganches del árbol, todos marcados con `// AgentNav` y de pocas líneas:
  `src/client/shell.rs` (`mod folder_tree;`), `src/client/shell/state.rs` (un campo en `ShellHitMap`, uno en
  `ClientShellState` y su inicialización), `src/client/shell/render.rs` (un campo en `ShellRenderState`),
  `src/client/shell/composition.rs` (pasarlo en los dos `ShellRenderState`), `src/client/shell/sidebar.rs` (un `if`
  alrededor de `render_agent_panel`), `src/client/shell/agent_sidebar.rs` (el botón `tree`),
  `src/client/shell/mouse.rs` (click izquierdo, click derecho y rueda), `src/client/shell/preferences.rs` (un campo
  opcional), `src/client/shell/config.rs` (guardarlo) y `src/client/mod.rs` (`| shell.tick_folder_tree()` en el timer).
- Retención del cursor configurable (Windows), marcada con `// AgentNav`: `src/pane/cursor.rs` (las ventanas salen de un
  `OnceLock` en vez de las constantes de 20/100 ms; `settle_enabled()`), `src/pane/terminal.rs` (`cursor_position_settle_enabled()`
  en vez de `const … = cfg!(windows)`), `src/pane.rs` (re-export), `src/config/model.rs` (`[advanced] cursor_settle_ms`,
  `cursor_jump_hold_ms`), `src/main.rs` (ayuda en `--default-config`) y `src/app/mod.rs` (se fijan en `App::new` y
  `new_from_handoff`). Ver «Cursor que va atrás de las teclas».
- `.github/workflows/agentnav-build.yml` y esta carpeta.

Reglas de los tests de upstream que las paletas cumplen: `sidebar_bg = Color::Reset`, contraste fondo/fila activa ≥ 1.05,
texto/fila activa ≥ 3.0, lo mismo para la fila de selección, y selección ≠ fila activa.

## Cómo se mantiene al día

`agentnav-build.yml` corre una vez por semana (lunes, `17 6 * * 1` UTC; antes cada 6 horas, hasta que GitHub pausó
Actions en el fork por el consumo de dos builds diarios en runners Windows), con cada push del parche y a mano desde la
pestaña Actions (`gh workflow run agentnav-build.yml -R pablitotester/herdr -f force=true`):

1. Busca el último tag `vX.Y.Z` de `herdrdev/herdr`. Si es más nuevo que `agentnav/BASE_TAG`, rebasa esta rama sobre él,
   la deja como **un solo commit** encima del tag y la sube con `--force-with-lease`.
2. Compila `herdr.exe` para Windows x86_64 con el mismo toolchain (`rust-toolchain.toml`), el mismo Zig y los mismos flags
   que el release oficial, corre los tests de temas y publica el release **`agentnav-vX.Y.Z`** con `herdr.exe`,
   `herdr.exe.sha256` y `agentnav-build.json`.
3. Si el rebase choca, aborta, abre un issue en este fork y no publica nada: el release anterior sigue valiendo hasta que
   alguien rehaga el parche. Los archivos nuevos (`palette_agentnav.rs`, `folder_tree.rs`) nunca chocan; lo que puede
   chocar son los enganches marcados con `// AgentNav`.

Un **push a esta rama** que toque `src/`, `Cargo.*`,
`build.rs` o el workflow recompila y reemplaza los archivos del release actual (misma versión, exe nuevo). El release
siempre queda marcado como *latest*: de eso depende la URL del manifiesto.

## Cursor que va atrás de las teclas

Sólo en Windows, Herdr (desde 0.9.2) retiene la posición del cursor del panel antes de mostrarla para que ConPTY no lo
haga parpadear: 20 ms si el cursor dio un paso normal (misma fila, hasta 2 columnas) y 100 ms si "saltó" (otra fila o más
de 2 columnas, la pinta de un redibujado que estaciona el cursor). La letra tipeada se ve al instante; el cuadrito recién
cuando vence la retención, y cada tecla nueva durante la espera la reinicia. PSReadLine redibuja la línea en cada tecla,
así que en una ráfaga el cursor queda clavado hasta 100 ms y después salta. Este build lo hace configurable:

```toml
[advanced]
cursor_settle_ms = 0        # paso normal (default 20)
cursor_jump_hold_ms = 40    # salto (default 100); 0 y 0 apagan la retención del todo
```

Con los defaults el exe se comporta igual que el oficial. Se lee al arrancar el servidor (`herdr server stop` y
`agentnav up`; `reload-config` no alcanza). Con 0/0 vuelve el parpadeo del cursor que motivó el cambio de upstream en apps
que estacionan el cursor durante un redibujado (Codex idle, barras de estado); 0/40 acota lo peor sin volver a eso. Para
medir sin ojos: `HERDR_RENDER_PROF=1` en el entorno del servidor cuenta `pty.request_render_delayed` (renders agendados por
la retención) contra `pty.request_render`.

## Árbol de carpetas

En la sección **agents** del sidebar, el botón `[tree]` (a la izquierda de `grouped`/`priority`; `[t]`
si el sidebar es angosto, y no aparece con `mouse_capture` apagado) cambia la lista plana por un árbol
de carpetas; `[list]` vuelve a la lista. Cada agente aparece dentro de la carpeta en la que está su pane (el `cwd` que ya
reporta Herdr), y las carpetas que contienen agentes se abren solas hasta mostrarlos.

- `▸`/`▾` o click en el nombre: abre o cierra la carpeta. Una carpeta cerrada con agentes adentro muestra `●N`.
- `+`: crea un workspace en esa carpeta.
- Click en un agente: lo enfoca.
- Click derecho en una carpeta: la fija como raíz. `..` sube un nivel. Click en la ruta de la raíz: vuelve a la raíz
  automática.
- **Raíz automática** (si no fijaste una): el ancestro común más profundo de las carpetas de los panes (si no hay panes,
  de las carpetas de los workspaces). Si ese ancestro es justo la carpeta de un proyecto, se usa la carpeta de arriba
  para que se vean los proyectos hermanos (`C:\Proyectos\agentnav` → `C:\Proyectos`). Si da la raíz de un disco
  (`C:\Proyectos\…` y un pane en `C:\`), se usa esa raíz. Sólo si hay panes en discos distintos o no hay datos se usa
  la carpeta del usuario (`%USERPROFILE%`). En la raíz de un disco o en la carpeta del usuario, el primer nivel esconde
  las carpetas que empiezan con `.` o `$` y los links/junctions, salvo que tengan agentes adentro. Se calcula
  al entrar al modo árbol y sólo se recalcula si algún pane queda fuera de la raíz; no salta en cada cambio.
- Sólo carpetas (sin archivos ni `.git`), hasta 500 por carpeta (el resto: `+N more`). Cada carpeta se lee al abrirla
  (y se vuelve a leer cada vez que la abrís, así aparecen clones o carpetas nuevas; click en la ruta de la raíz relee
  todo), en un thread aparte y sin recursión: una ruta de red lenta muestra `loading…`/`not responding…` sin congelar
  la UI, y deja de ocupar lugar en el límite de 8 lecturas simultáneas después de 5 s.
  Symlinks y junctions se muestran con `↪` y no se abren.
- Modo, raíz fijada y carpetas abiertas/cerradas se guardan en las preferencias del cliente
  (`client-shell/*.json`). El Herdr oficial ignora y borra esos campos al guardar; el árbol arranca bien sin ellos.
- Los agentes que quedan fuera de la raíz van al final, bajo `outside root`, con su carpeta al lado
  (`claude · ytmamp`).
- No aparece con varias máquinas conectadas (ese sidebar es otro) y lee el disco de la PC donde corre el cliente.
- **Probarlo con un build de debug**: `target\debug\herdr.exe --session prueba`. El debug guarda todo en `herdr-dev`
  (separado del Herdr instalado), *pero* si lo corrés adentro de un pane de Herdr sin `--session`, hereda
  `HERDR_SOCKET_PATH` y se engancha al server real. Usá `--session` o una terminal fuera de Herdr.

## Comando `agentnav`

`install.ps1` crea `%USERPROFILE%\.herdr\agentnav\bin\agentnav.cmd` y suma esa carpeta al PATH del usuario, así que en
una PowerShell nueva `agentnav` abre este Herdr igual que `herdr` (le pasa los argumentos y devuelve su exit code:
`agentnav --version`, `agentnav --session x`...). La tarea de updates corre `install.ps1`, así que las PCs que ya
estaban instaladas lo reciben en el próximo update. Si la PC ya tiene el programa AgentNav con su propio comando
`agentnav` (`agentnav app`, `doctor`, `herdr-sync`), no se pisa: se avisa y Herdr queda como `herdr`.

## Updates automáticos en la PC

Dos caminos, que se complementan:

- **Dentro de Herdr.** El parche cambia `STABLE_UPDATE_MANIFEST_URL` en `src/update.rs` para que apunte a
  `https://github.com/pablitotester/herdr/releases/latest/download/agentnav-latest.json`. El aviso de versión nueva de
  Herdr y `herdr update` usan ese manifiesto, así que actualizar **no vuelve al oficial**: instala el zip del fork.
  Sólo ve versiones nuevas (`X.Y.Z`); un rebuild del parche con la misma versión no lo nota.
- **Tarea programada `AgentNav Herdr update`.** `install.ps1` copia `agentnav/update.ps1` a `%USERPROFILE%\.herdr\agentnav\`
  y la registra (al iniciar sesión + todos los días a las 13:00; sin admin). Compara el SHA-256 del `herdr.exe` instalado
  con `herdr.exe.sha256` del último release `agentnav-v*`, así que detecta versiones nuevas **y** cambios del parche.
  Si Herdr está abierto no lo cierra: lo deja para el próximo chequeo. Log en `%USERPROFILE%\.herdr\agentnav\update.log`.
  A mano: `... \update.ps1 -Check` (sale con 10 si hay update) o `-Force` (instala aunque Herdr esté abierto).
  `install.ps1 -NoAutoUpdate` no crea la tarea.

Con AgentNav instalado también sirven `agentnav herdr-sync` (baja el último release, verifica el SHA-256, guarda el
exe oficial como `herdr.exe.oficial` y lo reemplaza con el servidor parado) y `agentnav doctor`.

## Volver al oficial

`herdr update` ya **no** sirve para esto (trae el del fork). En su lugar:

    Unregister-ScheduledTask "AgentNav Herdr update" -Confirm:$false
    irm https://herdr.dev/install.ps1 | iex

(o copiar `herdr.exe.oficial` sobre `herdr.exe`, pero el próximo `herdr update` o la tarea vuelven a poner el fork).

Y para sacar el comando `agentnav`: borrar `%USERPROFILE%\.herdr\agentnav\bin` y su entrada del PATH del usuario:

    Remove-Item "$env:USERPROFILE\.herdr\agentnav\bin" -Recurse -Force
    $p = [Environment]::GetEnvironmentVariable("Path", "User") -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ne "$env:USERPROFILE\.herdr\agentnav\bin" }
    [Environment]::SetEnvironmentVariable("Path", ($p -join ";"), "User")
