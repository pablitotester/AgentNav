"""Ayudante del instalador de AgentNav: lo que es más seguro hacer con JSON real que con PowerShell 5.1.

    py -I configurar.py claude-hooks <settings.json de Claude> <carpeta de hooks>
        Registra los cinco hooks de AgentNav (UserPromptSubmit, Stop, SessionEnd, Notification, PostToolUse)
        sin tocar lo demás que haya en el archivo. Idempotente: lo que ya está registrado no se repite.

    py -I configurar.py agentnav-settings <settings.json de AgentNav> <settings.example.json> <repo del fork>
        Crea settings.json desde el ejemplo si no existe, y deja herdr_fork.repo apuntando al fork con los temas.
        Si ya existe sólo completa herdr_fork.repo cuando está vacío; ntfy y lo demás no se tocan.

Sin dependencias fuera de la biblioteca estándar. Las funciones puras se prueban en tests\\test_installer.py."""
import json
import os
import shutil
import sys
from datetime import date

HOOK_EVENTS = (
    # (evento, matcher o None, archivo, argumento)
    ("UserPromptSubmit", None, "agentnav-state.ps1", "prompt"),
    ("Stop", None, "agentnav-state.ps1", "stop"),
    ("SessionEnd", None, "agentnav-state.ps1", "end"),
    ("Notification", "permission_prompt|idle_prompt", "agentnav-state.ps1", "notify"),
    ("PostToolUse", None, "agentnav-unblock.cmd", ""),
)


def hook_command(hooks_dir, script, arg):
    path = os.path.join(hooks_dir, script)
    if script.endswith(".ps1"):
        return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{path}" {arg}'.rstrip()
    return f'"{path}"'


def _registered(blocks, needle):
    for block in blocks or []:
        for h in (block.get("hooks") or []) if isinstance(block, dict) else []:
            if needle in str(h.get("command", "")):
                return True
    return False


def merge_claude_hooks(settings, hooks_dir):
    """Devuelve (settings nuevo, lista de eventos agregados). No muta el dict de entrada."""
    out = json.loads(json.dumps(settings)) if isinstance(settings, dict) else {}
    hooks = out.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = out["hooks"] = {}
    added = []
    for event, matcher, script, arg in HOOK_EVENTS:
        needle = f'{script}" {arg}' if arg else script
        blocks = hooks.setdefault(event, [])
        if not isinstance(blocks, list):
            blocks = hooks[event] = []
        if _registered(blocks, needle):
            continue
        block = {}
        if matcher:
            block["matcher"] = matcher
        block["hooks"] = [{"type": "command", "command": hook_command(hooks_dir, script, arg), "timeout": 10}]
        blocks.append(block)
        added.append(event)
    return out, added


def ensure_agentnav_settings(current, example, fork_repo):
    """Devuelve (settings, cambió). `current` es None cuando el archivo no existe."""
    if not isinstance(current, dict):
        data = json.loads(json.dumps(example)) if isinstance(example, dict) else {}
        changed = True
    else:
        data = json.loads(json.dumps(current))
        changed = False
    fork = data.get("herdr_fork")
    if not isinstance(fork, dict):
        fork = data["herdr_fork"] = {}
        changed = True
    if fork_repo and not str(fork.get("repo") or "").strip():
        fork["repo"] = fork_repo
        changed = True
    return data, changed


def _read(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.isfile(path):
        shutil.copy2(path, f"{path}.bak-agentnav-{date.today().isoformat()}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main(argv):
    if len(argv) >= 3 and argv[0] == "claude-hooks":
        settings_path, hooks_dir = argv[1], argv[2]
        try:
            current = _read(settings_path)
        except json.JSONDecodeError as e:
            print(f"ERROR: {settings_path} no es JSON válido ({e}); no lo toco", file=sys.stderr)
            return 2
        new, added = merge_claude_hooks(current, hooks_dir)
        if added:
            _write(settings_path, new)
            print("hooks registrados en settings.json de Claude: " + ", ".join(added))
        else:
            print("settings.json de Claude ya tenía los cinco hooks de AgentNav")
        return 0
    if len(argv) >= 4 and argv[0] == "agentnav-settings":
        settings_path, example_path, repo = argv[1], argv[2], ("" if argv[3] == "-" else argv[3])
        try:
            current = _read(settings_path)
        except json.JSONDecodeError as e:
            print(f"ERROR: {settings_path} no es JSON válido ({e}); no lo toco", file=sys.stderr)
            return 2
        new, changed = ensure_agentnav_settings(current, _read(example_path) or {}, repo)
        if changed:
            _write(settings_path, new)
            print(f"settings.json de AgentNav {'creado' if current is None else 'completado'} (herdr_fork.repo = {new['herdr_fork'].get('repo') or '-'})")
        else:
            print("settings.json de AgentNav ya estaba")
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
