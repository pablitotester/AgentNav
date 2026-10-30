"""Aplica el parche de AgentNav sobre una copia del código de Herdr (para rehacer la rama `agentnav` del fork a mano).

Uso:  py -I apply_patch.py <carpeta del clon de herdr>
Antes copiá palette_agentnav.rs a src/app/ y agentnav-build.yml a .github/workflows/ (y agentnav/BASE_TAG con el tag).
Si un `assert` falla es que upstream movió ese código: ajustar el anclaje y volver a correr.
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.expandvars(r"%LOCALAPPDATA%\AgentNav\herdr-src")


def edit(rel, old, new):
    p = os.path.join(root, rel)
    s = open(p, encoding="utf-8", newline="").read()
    assert old in s, (rel, old[:50])
    assert s.count(old) == 1, (rel, "ambiguous", old[:50])
    open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))


# 1. nombres visibles en Settings y aceptados en config.toml
edit("src/config/theme.rs",
     '    "vesper",\n];\n',
     '    "vesper",\n    // AgentNav palettes (see app/palette_agentnav.rs)\n    "cs16",\n    "matrix",\n    "procomm",\n];\n')
edit("src/config/theme.rs",
     '        "vesper" => Some("vesper"),\n        _ => None,\n',
     '        "vesper" => Some("vesper"),\n'
     '        // AgentNav palettes\n'
     '        "cs16" | "cs" | "counter-strike" | "goldsrc" => Some("cs16"),\n'
     '        "matrix" => Some("matrix"),\n'
     '        "procomm" | "procomm-plus" => Some("procomm"),\n'
     '        _ => None,\n')
# 2. resolver la paleta
edit("src/app/state.rs",
     '            "vesper" => Some(Self::vesper()),\n            _ => None,\n',
     '            "vesper" => Some(Self::vesper()),\n'
     '            // AgentNav palettes\n'
     '            "cs16" => Some(Self::cs16()),\n'
     '            "matrix" => Some(Self::matrix()),\n'
     '            "procomm" => Some(Self::procomm()),\n'
     '            _ => None,\n')
# 3. el módulo
edit("src/app/mod.rs",
     'pub mod state;\n',
     'pub mod state;\nmod palette_agentnav; // AgentNav: three extra built-in themes\n')
print("herdr patched")
