# El cursor va atrás de las teclas: qué hace Herdr y qué se puede tocar

Investigación del 13/11/2026 sobre Herdr 0.9.5 (fuente oficial, tag `v0.9.5`; el fork `agentnav` es ese mismo código
más el commit de temas y árbol). Síntoma: al tipear rápido en un panel, el cuadrito del cursor llega tarde a su
posición, aunque las letras aparezcan enseguida.

## Resumen

1. **La causa está en el servidor y sólo en Windows**: `src/pane/cursor.rs` + `src/pane/terminal.rs`. Desde 0.9.2
   (#2968, #4303, "the cursor no longer flickers during status redraws… on Windows") Herdr **retiene la posición del
   cursor** antes de mostrarla: 20 ms si el cursor dio un paso normal (misma fila, hasta 2 columnas) y **100 ms si
   "saltó"** (otra fila o más de 2 columnas, que es la pinta de un redibujado que estaciona el cursor). El contenido
   (la letra tipeada) se renderiza al instante; el cursor queda donde estaba hasta que vence la retención y recién
   entonces se pide otro frame. `CURSOR_POSITION_SETTLE_ENABLED = cfg!(windows)`: en macOS y Linux no existe.
2. Esa retención es **independiente de `host_cursor`** ("auto"/"native"/"drawn"): la posición ya viene retenida en el
   frame que el servidor manda al cliente, y el cliente la pinta igual sea como celda dibujada o moviendo el cursor
   del terminal exterior. Cambiar `host_cursor` cambia cómo se ve el cursor (bloque fijo dibujado vs. cursor de
   Windows Terminal, que parpadea), no cuánto tarda.
3. El resto de la cadena no agrega retraso apreciable al tipeo: el servidor limita a un frame cada 16 ms
   (`MIN_RENDER_INTERVAL`), pero un panel que recibió teclado en los últimos 32 ms (`INTERACTIVE_RENDER_WINDOW`) puede
   renderizar hasta 16 veces dentro de esa ventana (`INTERACTIVE_RENDER_BUDGET`), o sea que el eco de una tecla no
   espera el tick. No hay FPS cap del cliente ni debounce: el cliente escribe cada patch apenas llega.
4. No hay ninguna clave de configuración para la retención. Sí la hay para el aspecto (`ui.host_cursor`), y
   `experimental.reveal_hidden_cursor_for_cjk_ime` sólo aplica a apps que esconden el cursor (no cambia la latencia).

## Cómo funciona (con referencias al fuente)

- `src/pane/terminal.rs:1450-1482` (`process_pty_bytes`): tras procesar cada trozo de salida del PTY, si el app no usa
  *synchronized output* (modo 2026), toma la posición del cursor y la pasa a `CursorPositionSettleState::observe`.
  Pide render ya (`request_render`) y, si hay un candidato pendiente, agenda **otro** render para dentro de
  `render_delay` (`src/pane.rs:2601-2609`: `tokio::time::sleep(delay)` y `request_pty`).
- `src/pane/cursor.rs`: `CURSOR_POSITION_SETTLE = 20 ms`, `CURSOR_POSITION_MAX_HOLD = 100 ms`. `reported_cursor`
  devuelve la posición **asentada** mientras el candidato no cumplió su retención (`candidate_hold`: 100 ms si
  `is_jump` o si el candidato está invisible, 20 ms si no); `is_jump` = otra fila o `|Δx| > 2`. Si durante la
  retención llega otra posición distinta, `candidate_since` se reinicia (vuelve a contar), con tope de 100 ms desde
  el primer candidato (`pending_since`).
- `src/pane/terminal.rs:2540-2549` (`effective_cursor_state`): es lo que va al frame, para todos los clientes y modos.
- Por qué duele más con PowerShell: PSReadLine redibuja la línea en cada tecla (coloreado, predicción) y ConPTY entrega
  esa salida en varios trozos; entre trozos el cursor queda estacionado en otra columna o fila, lo que Herdr clasifica
  como salto y retiene 100 ms. En una ráfaga, cada tecla reinicia la cuenta: el cursor se queda clavado hasta el tope
  de 100 ms y después salta al lugar correcto. Es exactamente lo que se ve.
- `host_cursor` (`src/client/terminal_setup.rs:417`): "auto" = dibujado en Windows y WSL (`should_draw_host_cursor_by_default`
  es `true` en `platform/windows.rs`), porque ConPTY hace parpadear el cursor nativo mientras Herdr escribe el frame.
  Con "drawn" el cliente pinta el cursor como celda invertida (`patch_rows_with_drawn_cursor`,
  `frame_with_drawn_cursor`) y esconde el del terminal exterior; con "native" manda la posición y Windows Terminal
  dibuja y parpadea el suyo. Cambiarlo recarga el cliente en caliente (`reload_config_requests_client_reload_for_host_cursor_only_change`).

## Qué probar en vivo (lo que sí se puede medir a ojo)

Sólo con `host_cursor` (recarga en caliente, no cierra sesiones):

```powershell
# respaldo
Copy-Item $env:APPDATA\herdr\config.toml $env:APPDATA\herdr\config.toml.bak
# agregar bajo [ui]:   host_cursor = "native"
herdr server reload-config
# tipear ráfagas en un panel con pwsh y en uno con Claude Code; para volver:
Copy-Item $env:APPDATA\herdr\config.toml.bak $env:APPDATA\herdr\config.toml; herdr server reload-config
```

Qué mirar: (a) si el cursor "llega" igual de tarde con "native" que con "auto" (esperable por el punto 2), (b) si con
"native" parpadea o se ve doble al escribir Herdr el frame (es la razón del default), (c) en Claude Code, que esconde
el cursor y pinta el suyo, con "native" no debería verse ningún cuadrito de Windows Terminal; si se ve, es el caso de
`reveal_hidden_cursor_for_cjk_ime` (apagado por defecto, dejarlo así).

Lo que no se puede ver sin tocar el fork: la retención de 20/100 ms. Para medirla sin ojos: `HERDR_RENDER_PROF=1`
en el entorno del servidor (`src/render_prof.rs`) cuenta `pty.request_render_delayed` (renders que se agendaron por la
retención) contra `pty.request_render`; muchos "delayed" por ráfaga = la retención está activa en cada tecla.

## Propuesta para el fork: la retención, configurable

Estado al 13/11 17:05: aplicada en el fork como rama **`cursor-settle`** (commit `fdc3a233`, sobre `agentnav` =
v0.9.5 + parche de temas y árbol), pusheada. Falta llevarla a `agentnav` (el workflow sólo compila esa rama; el push a
`agentnav` dispara el build y **reemplaza** el release `agentnav-v0.9.5`, por eso lo hace Pablo a mano) y esperar el
build. `herdr-fork\cursor-settle.patch` es ahora el commit real (`git format-patch`), no un borrador. Comandos para
Pablo, cualquiera de los tres:

```powershell
# a) con un clon del fork
git checkout agentnav; git merge --ff-only cursor-settle; git push origin agentnav
# b) sin clon, moviendo la rama por la API (fast-forward)
gh api -X PATCH repos/pablitotester/herdr/git/refs/heads/agentnav -f sha=fdc3a233dfafe1e8345c72ee9f6e5c92a496116f
# c) en la web: PR cursor-settle → agentnav y merge
# Si el push no disparó el build (o para rehacerlo):
gh workflow run agentnav-build.yml -R pablitotester/herdr -f force=true
gh run list -R pablitotester/herdr --workflow agentnav-build.yml --limit 3
```

Prueba visual después del build (4 líneas; `agentnav herdr-sync` cierra sesiones, lo corre agentnav-7d cuando Pablo diga):

```powershell
agentnav herdr-sync --force                 # instala el exe del fork y reinicia el servidor (cierra sesiones)
# en %APPDATA%\herdr\config.toml, bajo [advanced]:  cursor_settle_ms = 0  /  cursor_jump_hold_ms = 40
herdr server stop; agentnav up              # se lee al arrancar; reload-config no alcanza
# tipear ráfagas en un panel pwsh: el cuadrito tiene que seguir a la letra; si algo parpadea al redibujar, subir a 40/100
```

`herdr-fork\cursor-settle.patch` agrega a `[advanced]` dos claves, `cursor_settle_ms` (default 20) y
`cursor_jump_hold_ms` (default 100); **0 en las dos apaga la retención** y deja Windows como macOS/Linux (cursor al
instante, con el parpadeo de ConPTY que motivó el cambio de 0.9.2 cuando un app redibuja). Un valor intermedio (p. ej.
`cursor_jump_hold_ms = 40`) acota lo peor sin volver al flicker. El valor se lee una vez al arrancar el servidor
(`OnceLock`), sin tocar la creación de cada panel; `herdr server reload-config` no lo recarga (hace falta
`herdr server stop` + `agentnav up`). El diff va contra `v0.9.5` y no toca los archivos del parche de temas, así que
rebasea limpio con el workflow; es otro ciclo de build (tag `agentnav-v0.9.5` republicado).

Riesgos del parche: ninguno con los defaults (mismo comportamiento byte a byte); con 0/0, vuelve el parpadeo de
#2968/#4303 en apps que estacionan el cursor durante un redibujado (Codex idle, barras de estado) y puede verse una
celda invertida "bailando" durante un redibujado de PSReadLine. Por eso la recomendación es probarlo con 0/40 primero.

## Recomendación para `config\herdr.config.toml`

Dejar `host_cursor` en "auto" (dibujado) como default, con el comentario del trade-off, y documentar "native" como la
prueba de una línea para quien perciba el retraso: no cambia la latencia de fondo pero cambia la sensación (el cursor
nativo parpadea y Windows Terminal lo mueve en el mismo frame). La mejora real es el parche del fork.
