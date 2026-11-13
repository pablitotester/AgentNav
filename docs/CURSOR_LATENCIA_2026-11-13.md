# Latencia del cursor al tipear en un panel de Herdr (medición del 2026-11-13)

Pedido: un compañero ve que, tipeando rápido, el cuadrito del cursor tarda en ponerse donde corresponde. Acá va la
parte de consola (shell, ConPTY, Windows Terminal) medida en esta PC; el lado del cliente de Herdr lo miró otra sesión
(ver `herdr-fork/cursor-lag.md`).

PC: Windows 10 22H2 (19045), Windows Terminal 1.24.12741.0 (AtlasEngine; sin ajustes de render en el `settings.json`
de Pablo), pwsh 7.6.9, Windows PowerShell 5.1.19041, PSReadLine 2.4.5, Herdr 0.9.5 (build del fork) con su ConPTY
propio 1.24.260710001 (OpenConsole x64).

## 1. Ida y vuelta por ConPTY (DSR), por consola y por shell

`tools\cursor-latency.ps1`: escribe un carácter seguido de `ESC[6n` y cronometra hasta leer la respuesta `ESC[f;cR`.
La respuesta la genera el ConPTY (OpenConsole) que atiende a esa consola, así que mide **shell → ConPTY → shell**:
el tramo de eco que comparten Herdr y Windows Terminal, sin el emulador de Herdr ni el pintado en pantalla.
200 muestras por corrida.

| Dónde corre                      | Shell      | p50  | p90  | p99  | máx   |
|----------------------------------|------------|------|------|------|-------|
| panel de Herdr                   | pwsh 7.6.9 | 0,68 | 1,50 | 8,31 | 12,5  |
| panel de Herdr                   | PS 5.1     | 0,54 | 0,77 | 2,08 | 3,5   |
| panel de Herdr, vía cmd          | PS 5.1     | 0,60 | 0,88 | 2,81 | 3,9   |
| pestaña de Windows Terminal sola | pwsh 7.6.9 | 0,59 | 0,97 | 6,80 | 13,3  |
| pestaña de Windows Terminal sola | PS 5.1     | 0,53 | 0,80 | 4,09 | 6,7   |
| ventana conhost (sin WT)         | pwsh 7.6.9 | 0,87 | 1,16 | 4,17 | 11,2  |

Todo en milisegundos; 0 muestras perdidas. Lectura: el eco por ConPTY está **por debajo del milisegundo** en todos los
casos, Herdr incluido; pwsh 7 tiene una cola larga (p99 de 7-8 ms, picos de 12 ms) que PS 5.1 no tiene, pero son
picos aislados, no un retraso sostenido. Ninguna combinación de shell o consola explica un cursor que "se queda
atrás" al tipear.

## 2. Tecla → letra en pantalla, por la API de Herdr

`herdr pane send-text` de una ráfaga y muestreo de `herdr pane read` hasta ver el último carácter (8 ráfagas).
Resolución gruesa: cada `pane read` cuesta 14-15 ms.

| Métrica                                   | Resultado                 |
|-------------------------------------------|---------------------------|
| `send-text` (ida al servidor)             | 15-18 ms (un pico de 32)  |
| letra visible en el buffer del servidor   | 13-16 ms después, siempre en la primera lectura |

O sea: la **letra** está en el modelo del servidor dentro de una lectura (≤15 ms, techo de la medición). La API de
Herdr no expone la posición del cursor del panel (`pane read` es texto plano; `pane get` no la trae), así que
**tecla → cursor en su lugar no se puede medir desde afuera** sin ojos o sin el perfilado del servidor
(`HERDR_RENDER_PROF=1`, que exige reiniciarlo).

## 3. Conclusión por capa

| Capa                         | Veredicto                                                                                |
|------------------------------|------------------------------------------------------------------------------------------|
| Shell (pwsh / PS 5.1 / cmd)  | No es la causa: eco < 1 ms. pwsh 7 con picos de 8-12 ms, pero aislados.                   |
| ConPTY (OpenConsole 1.24)    | No es la causa: mismo tramo en Herdr, WT y conhost.                                      |
| Windows Terminal 1.24        | Sin ajustes de render en el `settings.json` de Pablo (AtlasEngine, lo que trae de fábrica). No hay ajuste documentado de latencia de entrada ni de cadencia de frames (`experimental.rendering.forceFullRepaint` y `experimental.rendering.software` sólo cambian el renderer; no tocar). Las notas de 1.24 no traen nada de cursor. |
| Herdr (servidor, Windows)    | **Causa más probable**: `src/pane/cursor.rs` retiene la posición del cursor 20 ms por paso normal y 100 ms por salto (otra fila o >2 columnas), contra el parpadeo de ConPTY; la letra va en el primer frame, el cursor en otro cuando vence la retención. Es consistente con lo medido: la letra aparece enseguida y el cursor llega después. Lo documentó la sesión del fork en `herdr-fork/cursor-lag.md` con un parche (`[advanced] cursor_settle_ms` / `cursor_jump_hold_ms`). `host_cursor` cambia cómo se ve, no cuánto tarda. |

## 4. Recomendación

1. Atacar la retención del cursor en el fork (parche de `cursor-lag.md`), que es el único tramo con decenas de ms.
2. No tocar Windows Terminal ni el shell: no hay nada que ganar ahí y los ajustes experimentales de render pueden empeorar.
3. Para verificar el arreglo sin ojos: `HERDR_RENDER_PROF=1` en el servidor y comparar `pty.request_render_delayed`
   contra `pty.request_render` antes y después; con ojos, tipear rápido en un panel de pwsh.
4. `tools\cursor-latency.ps1` queda para comprobar que la capa consola sigue sana tras cualquier cambio
   (`pwsh -NoProfile -File tools\cursor-latency.ps1 -N 200 -Label "lo que sea"`). Detecta la consola por
   `HERDR_ENV` / `WT_SESSION`; si se lanza desde dentro de Herdr hereda `HERDR_ENV` y dirá "herdr" aunque corra en una
   pestaña aparte, por eso la etiqueta manual.
