# AgentNav — gancho pane.focused del plugin de Herdr: anota qué panel tomó el foco (rastro en focus.log).
# `agentnav adopt` lo lee para saber desde qué panel se abrió una pestaña o un split, porque el evento de
# creación no lo dice. Sin dependencias y sin importar agentnav.py: corre en cada cambio de foco.
import os

d = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AgentNav")
p = os.path.join(d, "focus.log")
try:
    os.makedirs(d, exist_ok=True)
    try:
        if os.path.getsize(p) > 32_000:  # poda: quedan las últimas 200 líneas
            with open(p, encoding="utf-8", errors="replace") as f:
                keep = f.readlines()[-200:]
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(keep)
    except OSError:
        pass
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{os.environ.get('HERDR_WORKSPACE_ID', '')} {os.environ.get('HERDR_PANE_ID', '')}\n")
except OSError:
    pass
