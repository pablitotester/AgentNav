#!/usr/bin/env python3
"""AgentNav — capa fina sobre Herdr para navegar proyectos y agentes.

Uso:
  agentnav                 levanta el servidor de Herdr si hace falta y abre una pestaña de Windows Terminal enganchada
  agentnav list            proyectos registrados, cuáles están abiertos y el estado de cada agente
  agentnav open <nombre>   abre el proyecto como espacio de Herdr con sus Claude adentro (o lo enfoca si ya está)
  agentnav pick            selector interactivo (es lo que corre el popup de Herdr con ctrl+b alt+p)
  agentnav up              sólo levanta el servidor
  agentnav attach          sólo abre la pestaña de Windows Terminal

Registro: C:\\AgentNav\\projects.json  (nombre, ruta, agentes a abrir)
Sólo stdlib. Windows.
"""
import functools
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
PROJECTS_PATH = os.path.join(HOME, "projects.json")
STANDALONE = os.path.join(os.environ.get("USERPROFILE", ""), ".herdr", "packages", "standalone", "current", "herdr.exe")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


class AgentNavError(Exception):
    pass


def inside_herdr():
    return os.environ.get("HERDR_ENV") == "1"


# ---------------------------------------------------------------- herdr CLI

@functools.lru_cache(maxsize=1)
def herdr_bin():
    p = os.environ.get("HERDR_BIN_PATH")
    if p and os.path.isfile(p):
        return p
    w = shutil.which("herdr")
    if w:
        return w
    if os.path.isfile(STANDALONE):
        return STANDALONE
    raise AgentNavError("no encuentro herdr.exe (ni HERDR_BIN_PATH, ni PATH, ni la instalación standalone)")


def run(*args, timeout=120):
    try:
        cp = subprocess.run([herdr_bin(), *args], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise AgentNavError(f"herdr {' '.join(args)}: sin respuesta en {timeout} s")
    except OSError as e:
        raise AgentNavError(f"no pude ejecutar herdr: {e}")
    return cp.returncode, cp.stdout.strip(), cp.stderr.strip()


def _parse_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def api(*args, timeout=120):
    """Comando de la CLI que devuelve JSON. Lanza AgentNavError con el código del error de Herdr."""
    code, out, err = run(*args, timeout=timeout)
    data = _parse_json(out)
    if data is None:
        data = _parse_json(err)
    if not isinstance(data, dict):
        raise AgentNavError(f"respuesta inesperada de herdr {' '.join(args)}: {(out or err)[:200]}")
    if "error" in data:
        e = data["error"] if isinstance(data["error"], dict) else {}
        raise AgentNavError(f"{e.get('code', 'error')}: {e.get('message', '')}")
    if code != 0:
        raise AgentNavError(f"herdr {' '.join(args)} salió con {code}: {err[:200]}")
    r = data.get("result", data)
    return r if isinstance(r, dict) else {}


def server_running():
    code, out, err = run("status", "server", timeout=15)
    return "status: running" in (out + err)


def ensure_server(say=print):
    """Devuelve True si lo levantó, False si ya corría."""
    if server_running():
        return False
    say("levantando el servidor de Herdr…")
    try:
        subprocess.Popen([herdr_bin(), "server"], cwd=os.environ.get("USERPROFILE", HOME),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        raise AgentNavError(f"no pude lanzar el servidor: {e}")
    import time
    for _ in range(40):
        time.sleep(0.25)
        if server_running():
            return True
    raise AgentNavError("el servidor de Herdr no respondió en 10 s (mirá %APPDATA%\\herdr\\herdr-server.log)")


def snapshot():
    snap = api("api", "snapshot").get("snapshot") or {}
    snap.setdefault("workspaces", [])
    snap.setdefault("agents", [])
    return snap


# ---------------------------------------------------------------- registro

def _read_projects_raw():
    if not os.path.isfile(PROJECTS_PATH):
        return []
    try:
        with open(PROJECTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise AgentNavError(f"projects.json inválido: {e}")
    if not isinstance(data, list):
        raise AgentNavError("projects.json tiene que ser una lista de proyectos")
    return data


def load_projects():
    out = []
    for p in _read_projects_raw():
        if not isinstance(p, dict) or not p.get("name") or not p.get("path"):
            continue
        agents = p.get("agents") or []
        out.append({"name": str(p["name"]), "path": str(p["path"]),
                    "agents": [str(a) for a in agents if a],
                    "kind": str(p.get("kind") or "claude")})
    return out


def add_project(name, path):
    """Agrega al archivo sin tocar lo que ya había (conserva claves ajenas), escritura atómica."""
    raw = _read_projects_raw()
    raw.append({"name": name, "path": path, "agents": [agent_name(name, set())], "kind": "claude"})
    tmp = PROJECTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PROJECTS_PATH)


def find_project(projects, name):
    low = name.strip().lower()
    if not low:
        return None
    for p in projects:
        if p["name"].lower() == low:
            return p
    hits = [p for p in projects if p["name"].lower().startswith(low)]
    if len(hits) > 1:
        raise AgentNavError("ambiguo: " + ", ".join(p["name"] for p in hits))
    return hits[0] if hits else None


def agent_name(base, taken):
    """Nombre válido para Herdr ([a-z][a-z0-9_-]{0,31}) y único entre los vivos."""
    n = re.sub(r"[^a-z0-9_-]", "-", str(base).lower()).strip("-") or "agente"
    if not n[0].isalpha():
        n = "a" + n
    n = n[:28]
    cand, i = n, 2
    while cand in taken:
        cand, i = f"{n}-{i}", i + 1
    taken.add(cand)
    return cand


def ws_label(ws):
    return (ws.get("label") or "").lower()


# ---------------------------------------------------------------- acciones

def _start_agent(p, name, pane, timeout_ms, say):
    """Devuelve True si el agente quedó listo."""
    say(f"  {name}: arrancando {p['kind']} en {pane}…")
    try:
        api("agent", "start", name, "--kind", p["kind"], "--pane", pane, "--timeout", str(timeout_ms),
            timeout=timeout_ms / 1000 + 10)
        say(f"  {name}: listo.")
        return True
    except AgentNavError as e:
        if "agent_not_ready" in str(e):
            say(f"  {name}: espera el diálogo de confianza de carpeta de Claude; respondelo en el panel.")
        else:
            say(f"  {name}: no arrancó ({e})")
        return False


def open_project(p, say=print, start_timeout_ms=90000):
    """Abre el proyecto como espacio de Herdr, o lo enfoca y repone los agentes que falten.
    Devuelve (modo, todos_listos) con modo 'created' o 'focused'."""
    ensure_server(say)
    snap = snapshot()
    taken = {a.get("name") for a in snap["agents"] if a.get("name")}
    wanted = p["agents"] or [p["name"]]
    all_ok = True

    ws = next((w for w in snap["workspaces"] if ws_label(w) == p["name"].lower()), None)
    if ws:
        wid = ws["workspace_id"]
        api("workspace", "focus", wid)
        live = {a.get("name") for a in snap["agents"] if a.get("workspace_id") == wid}
        # El nombre "deseado" es el base saneado; falta si no hay un agente vivo con ese nombre en el espacio.
        missing = [n for n in (agent_name(b, set()) for b in wanted) if n not in live]
        if not missing:
            say(f"{p['name']}: ya estaba abierto, enfocado.")
            return "focused", True
        say(f"{p['name']}: abierto; faltan {', '.join(missing)}.")
        for desired in missing:
            name = agent_name(desired, taken)  # sufijo sólo si otro espacio ya usa ese nombre
            try:
                t = api("tab", "create", "--workspace", wid, "--cwd", p["path"], "--label", name, "--no-focus")
                all_ok &= _start_agent(p, name, t["root_pane"]["pane_id"], start_timeout_ms, say)
            except AgentNavError as e:
                say(f"  {name}: {e}")
                all_ok = False
        return "focused", all_ok

    if not os.path.isdir(p["path"]):
        raise AgentNavError(f"{p['name']}: la carpeta no existe: {p['path']}")
    say(f"{p['name']}: abriendo espacio en {p['path']}…")
    r = api("workspace", "create", "--cwd", p["path"], "--label", p["name"])
    wid = r["workspace"]["workspace_id"]
    root_pane = r["root_pane"]["pane_id"]
    root_tab = r["tab"]["tab_id"]

    for i, base in enumerate(wanted):
        name = agent_name(base, taken)
        try:
            if i == 0:
                pane = root_pane
                try:
                    api("tab", "rename", root_tab, name)
                except AgentNavError:
                    pass
            else:
                t = api("tab", "create", "--workspace", wid, "--cwd", p["path"], "--label", name, "--no-focus")
                pane = t["root_pane"]["pane_id"]
            all_ok &= _start_agent(p, name, pane, start_timeout_ms, say)
        except AgentNavError as e:
            say(f"  {name}: {e}")
            all_ok = False
    return "created", all_ok


def attach(say=print):
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if not wt:
        raise AgentNavError("no encuentro wt.exe (Windows Terminal)")
    try:
        subprocess.Popen([wt, "-w", "0", "new-tab", "--title", "Herdr", herdr_bin()],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        raise AgentNavError(f"no pude abrir Windows Terminal: {e}")
    say("pestaña de Windows Terminal abierta con Herdr.")


STATUS_GLYPH = {"blocked": "✖", "working": "◐", "done": "✔", "idle": "○", "unknown": "?"}
STATUS_COLOR = {"blocked": "31", "working": "33", "done": "32", "idle": "2", "unknown": "2"}


def paint(text, code):
    return f"\x1b[{code}m{text}\x1b[0m"


def describe(snap, projects):
    """Devuelve filas [(proyecto, ws_id|None, [agentes])] y los agentes sueltos."""
    ws_by_label = {ws_label(ws): ws for ws in snap["workspaces"]}
    rows, used = [], set()
    for p in projects:
        ws = ws_by_label.get(p["name"].lower())
        agents = []
        if ws:
            used.add(ws["workspace_id"])
            agents = [a for a in snap["agents"] if a.get("workspace_id") == ws["workspace_id"]]
        rows.append((p, ws["workspace_id"] if ws else None, agents))
    loose = [a for a in snap["agents"] if a.get("workspace_id") not in used]
    return rows, loose


def agent_line(a):
    st = a.get("agent_status") or "unknown"
    label = a.get("name") or a.get("agent") or "?"
    title = a.get("terminal_title_stripped") or ""
    return paint(STATUS_GLYPH.get(st, "?"), STATUS_COLOR.get(st, "0")) + f" {label} {st}" + (f"  {title[:50]}" if title else "")


def cmd_list():
    projects = load_projects()
    if not server_running():
        print("servidor de Herdr: no corre (agentnav up)")
        for p in projects:
            print(f"  {p['name']:<14} {p['path']}")
        return 0
    snap = snapshot()
    rows, loose = describe(snap, projects)
    for p, wid, agents in rows:
        state = f"abierto {wid}" if wid else "cerrado"
        print(f"{p['name']:<14} {state:<12} {p['path']}")
        for a in agents:
            print("    " + agent_line(a))
    if loose:
        print("fuera de proyectos:")
        for a in loose:
            ws = next((w for w in snap["workspaces"] if w.get("workspace_id") == a.get("workspace_id")), {})
            print(f"    {ws.get('label') or a.get('workspace_id')}: " + agent_line(a))
    return 0


def cmd_open(name):
    p = find_project(load_projects(), name)
    if not p:
        raise AgentNavError(f"no hay un proyecto '{name}' en {PROJECTS_PATH}")
    open_project(p)
    if not inside_herdr():
        attach()
    return 0


# ---------------------------------------------------------------- selector (popup)

def _console_utf8():
    """Pasa la consola a UTF-8 y VT. Devuelve una función que restaura las code pages de antes."""
    restore = lambda: None
    try:
        import ctypes
        k = ctypes.windll.kernel32
        old_out, old_in = k.GetConsoleOutputCP(), k.GetConsoleCP()
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING

        def restore():
            k.SetConsoleOutputCP(old_out)
            k.SetConsoleCP(old_in)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return restore


def _getkey():
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(code, "")
    if ch == "\r":
        return "enter"
    if ch in ("\x1b", "\x03"):
        return "esc"
    return ch.lower()


def _ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def cmd_pick():
    projects = load_projects()
    sel, msg = 0, ""
    snap = None
    while True:
        if snap is None:
            try:
                snap = snapshot()
            except AgentNavError as e:
                snap, msg = {"workspaces": [], "agents": []}, str(e)
        rows, loose = describe(snap, projects)
        sel = min(sel, max(0, len(rows) - 1))
        sys.stdout.write("\x1b[2J\x1b[H")
        print(paint(" AgentNav · proyectos ", "7"))
        print()
        if not rows:
            print("  (sin proyectos: 'a' para agregar uno, o editá projects.json)")
        for i, (p, wid, agents) in enumerate(rows):
            cursor = "▶" if i == sel else " "
            dot = paint("●", "32") if wid else paint("○", "2")
            line = f" {cursor} {dot} {p['name']:<14} {p['path']}"
            print(paint(line, "7") if i == sel else line)
            for a in agents:
                print("        " + agent_line(a))
        if loose:
            print()
            print(paint("  fuera de proyectos:", "2"))
            for a in loose:
                print("        " + agent_line(a))
        print()
        print(paint("  ↑↓ mover · Enter abrir o ir · a agregar · r refrescar · q salir", "2"))
        if msg:
            print("  " + msg)
        k = _getkey()
        if k in ("q", "esc"):
            return 0
        if k in ("up", "k"):
            sel = max(0, sel - 1)
        elif k in ("down", "j"):
            sel = min(max(0, len(rows) - 1), sel + 1)
        elif k == "r":
            projects, snap, msg = load_projects(), None, ""
        elif k == "a":
            print()
            name = _ask("  nombre: ")
            path = _ask("  ruta:   ").strip('"')
            if name and os.path.isdir(path):
                try:
                    add_project(name, os.path.abspath(path))
                    projects, sel, snap, msg = load_projects(), len(projects), None, f"agregado {name}"
                except AgentNavError as e:
                    msg = str(e)
            else:
                msg = "no agregado: falta el nombre o la ruta no existe"
        elif k == "enter" and rows:
            p = rows[sel][0]
            print()
            try:
                # Timeout corto: el popup es modal y el usuario no puede responder nada mientras esperamos.
                _, ok = open_project(p, say=lambda s: print("  " + s), start_timeout_ms=20000)
                if not ok:
                    print(paint("  (alguna tecla para cerrar el selector)", "2"))
                    _getkey()
                return 0
            except AgentNavError as e:
                msg, snap = str(e), None


# ---------------------------------------------------------------- main

def main(argv):
    cmd = (argv[0] if argv else "").lower()
    if cmd in ("", "go"):
        ensure_server()
        if inside_herdr():
            print("ya estás dentro de Herdr.")
        else:
            attach()
        return 0
    if cmd == "list":
        return cmd_list()
    if cmd == "open":
        if len(argv) < 2:
            raise AgentNavError("uso: agentnav open <nombre>")
        return cmd_open(" ".join(argv[1:]))
    if cmd == "pick":
        return cmd_pick()
    if cmd == "up":
        print("servidor arriba." if ensure_server() else "servidor ya corría.")
        return 0
    if cmd == "attach":
        attach()
        return 0
    print(__doc__)
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    # La consola de Windows arranca en cp1252 y los glifos de estado no entran ahí.
    _restore = _console_utf8()
    try:
        code = main(sys.argv[1:])
    except AgentNavError as e:
        print(f"agentnav: {e}", file=sys.stderr)
        code = 2 if str(e).startswith("uso:") else 1
    except KeyboardInterrupt:
        code = 130
    finally:
        if (sys.argv[1:2] or [""])[0].lower() != "pick":
            _restore()  # el popup muere con su consola; a una pwsh ajena le devolvemos su code page
    sys.exit(code)
