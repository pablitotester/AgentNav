# Rama `agentnav` de este fork de Herdr

Herdr oficial más **tres temas extra** que aparecen en Settings (`ctrl+b s → theme`) junto a los de fábrica:

| nombre    | qué es                                                                 |
|-----------|------------------------------------------------------------------------|
| `cs16`    | consola de Counter-Strike 1.6 (GoldSrc): paneles verde oliva, texto arena, naranja |
| `matrix`  | negro y fósforo verde                                                  |
| `procomm` | Procomm Plus de DOS: azul CGA, texto blanco, resaltes amarillo y cian   |

Herdr no tiene temas de usuario: la lista de Settings sale de `THEME_NAMES` en `src/config/theme.rs` y cada paleta es
una función en `src/app/state.rs`. Por eso el único camino es compilar.

## Qué toca el parche (un solo commit sobre el tag de upstream)

- `src/app/palette_agentnav.rs` — **nuevo**: las tres paletas (`impl Palette { fn cs16() … }`).
- `src/app/mod.rs` — una línea: `mod palette_agentnav;`.
- `src/config/theme.rs` — tres nombres en `THEME_NAMES` y tres brazos en `canonical_theme_name`.
- `src/app/state.rs` — tres brazos en `Palette::from_name`.
- `.github/workflows/agentnav-build.yml` y esta carpeta.

Reglas de los tests de upstream que las paletas cumplen: `sidebar_bg = Color::Reset`, contraste fondo/fila activa ≥ 1.05,
texto/fila activa ≥ 3.0, lo mismo para la fila de selección, y selección ≠ fila activa.

## Cómo se mantiene al día

`agentnav-build.yml` corre todos los días a las 06:17 UTC (y a mano desde la pestaña Actions):

1. Busca el último tag `vX.Y.Z` de `herdrdev/herdr`. Si es más nuevo que `agentnav/BASE_TAG`, rebasa esta rama sobre él,
   la deja como **un solo commit** encima del tag y la sube con `--force-with-lease`.
2. Compila `herdr.exe` para Windows x86_64 con el mismo toolchain (`rust-toolchain.toml`), el mismo Zig y los mismos flags
   que el release oficial, corre los tests de temas y publica el release **`agentnav-vX.Y.Z`** con `herdr.exe`,
   `herdr.exe.sha256` y `agentnav-build.json`.
3. Si el rebase choca, aborta, abre un issue en este fork y no publica nada: el release anterior sigue valiendo hasta que
   alguien rehaga el parche (son cuatro archivos; el nuevo `palette_agentnav.rs` nunca choca).

En la PC: `agentnav herdr-sync` baja el último release, verifica el SHA-256, guarda el exe oficial al lado
(`herdr.exe.oficial`) y lo reemplaza con el servidor parado. `agentnav doctor` avisa cuando hay uno más nuevo o
cuando `herdr update` pisó el nuestro.

## Volver al oficial

`herdr update` (o copiar `herdr.exe.oficial` sobre `herdr.exe`) y listo. Nada más de la instalación se toca.
