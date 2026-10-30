#!/usr/bin/env python3
"""AgentNav — capa fina sobre Herdr para navegar proyectos y agentes.

Uso:
  agentnav                 levanta el servidor de Herdr si hace falta y abre una pestaña de Windows Terminal enganchada
  agentnav list            proyectos registrados, cuáles están abiertos y el estado de cada agente
  agentnav open <nombre>   abre el proyecto como espacio de Herdr con sus agentes adentro (o lo enfoca si ya está)
  agentnav new <nombre> [ruta]
                           crea la carpeta (en C:\\ o donde diga new_cwd de Herdr), registra el proyecto y lo abre
  agentnav close <nombre>  cierra el espacio del proyecto (los Claude salen con /exit antes)
  agentnav tab [shell]     pestaña nueva en el espacio actual: misma carpeta que el panel de origen y el mismo agente
                           (es lo que corre ctrl+b c). Con "shell": pestaña pelada en C:\\ (ctrl+b shift+c)
  agentnav adopt           lo corre el plugin de Herdr al crearse una pestaña desde la interfaz (el "+" de la barra):
                           la lleva a la carpeta del proyecto y arranca el mismo agente, como `tab`
  agentnav pick            selector interactivo (es lo que corre el popup de Herdr con ctrl+b alt+p)
  agentnav recent          carpetas donde usaste Claude Code y no están registradas
  agentnav hoy [ayer|AAAA-MM-DD]
                           diario del día: qué le pediste a cada proyecto y cuánto trabajó
  agentnav doctor          verifica la instalación completa (Herdr, hooks, config, arranque)
  agentnav ntfy-test       manda un aviso de prueba al teléfono (settings.json → ntfy)
  agentnav up              sólo levanta el servidor
  agentnav attach          sólo abre la pestaña de Windows Terminal
  agentnav app             lo que corre el acceso directo del escritorio: servidor arriba y la ventana de Herdr al frente

Registro: C:\\AgentNav\\projects.json   (nombre, ruta, agentes a abrir)
Ajustes:  C:\\AgentNav\\settings.json   (avisos ntfy)
Sólo stdlib. Windows.
"""
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
PROJECTS_PATH = os.path.join(HOME, "projects.json")
SETTINGS_PATH = os.path.join(HOME, "settings.json")
USERPROFILE = os.environ.get("USERPROFILE", "")
STANDALONE = os.path.join(USERPROFILE, ".herdr", "packages", "standalone", "current", "herdr.exe")
CLAUDE_HOME = os.path.join(USERPROFILE, ".claude")
CLAUDE_PROJECTS = os.path.join(CLAUDE_HOME, "projects")
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AgentNav")
JOURNAL_DIR = os.path.join(STATE_DIR, "journal")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

SHELL_KIND = "shell"


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
        subprocess.Popen([herdr_bin(), "server"], cwd=USERPROFILE or HOME,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        raise AgentNavError(f"no pude lanzar el servidor: {e}")
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

def _read_json_file(path, what):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise AgentNavError(f"{what} inválido: {e}")


def _read_projects_raw():
    data = _read_json_file(PROJECTS_PATH, "projects.json")
    if data is None:
        return []
    if not isinstance(data, list):
        raise AgentNavError("projects.json tiene que ser una lista de proyectos")
    return data


def load_settings():
    data = _read_json_file(SETTINGS_PATH, "settings.json")
    return data if isinstance(data, dict) else {}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v if x is not None and str(x) != ""]


def _norm_agent(raw, p_kind, p_args, p_continue, fallback_name):
    """Un agente del registro: string ("qa") u objeto ({name, kind, args, continue, command, split, ratio})."""
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or fallback_name)
    kind = str(raw.get("kind") or p_kind)
    a = {"name": name, "kind": kind,
         # "args": [] en el agente anula los del proyecto; sin la clave, hereda.
         "args": _as_list(raw["args"]) if "args" in raw else list(p_args),
         "continue": bool(raw.get("continue", p_continue)) if kind != SHELL_KIND else False,
         "command": str(raw.get("command") or "") if kind == SHELL_KIND else "",
         "split": str(raw.get("split") or "") or None,
         "ratio": raw.get("ratio")}
    if a["split"] not in (None, "right", "down"):
        a["split"] = None
    try:
        a["ratio"] = float(a["ratio"]) if a["ratio"] is not None else None
    except (TypeError, ValueError):
        a["ratio"] = None
    return a


def load_projects():
    out = []
    for p in _read_projects_raw():
        if not isinstance(p, dict) or not p.get("name") or not p.get("path"):
            continue
        p_kind = str(p.get("kind") or "claude")
        p_args = _as_list(p.get("args"))
        p_cont = bool(p.get("continue", False))
        raw_agents = p.get("agents")
        raw_agents = (raw_agents if isinstance(raw_agents, list) else _as_list(raw_agents)) or [str(p["name"])]
        agents = [a for a in (_norm_agent(r, p_kind, p_args, p_cont, str(p["name"])) for r in raw_agents) if a]
        out.append({"name": str(p["name"]), "path": str(p["path"]), "agents": agents,
                    "kind": p_kind, "continue": p_cont})
    return out


def _write_projects_raw(raw):
    tmp = PROJECTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PROJECTS_PATH)


def add_project(name, path):
    """Agrega al archivo sin tocar lo que ya había (conserva claves ajenas), escritura atómica."""
    raw = _read_projects_raw()
    if any(isinstance(p, dict) and str(p.get("name", "")).lower() == name.lower() for p in raw):
        raise AgentNavError(f"ya hay un proyecto llamado {name}")
    raw.append({"name": name, "path": path, "agents": [agent_name(name, set())], "kind": "claude", "continue": True})
    _write_projects_raw(raw)


def new_project_base():
    """Dónde nacen los proyectos nuevos: el `new_cwd` fijo de la config de Herdr si lo hay, si no C:\\."""
    cfg = os.path.join(os.environ.get("APPDATA", ""), "herdr", "config.toml")
    try:
        with open(cfg, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*new_cwd\s*=\s*"([^"]*)"', line)
                if m:
                    v = m.group(1).replace("\\\\", "\\")
                    if v == "home":
                        return USERPROFILE
                    if v not in ("follow", "current", ""):
                        return os.path.expanduser(v)
    except OSError:
        pass
    return "C:\\"


def cmd_new(rest):
    """agentnav new <nombre> [ruta]: crea la carpeta, registra el proyecto y lo abre con su Claude."""
    parts = rest.split(None, 1)
    if not parts:
        raise AgentNavError("uso: agentnav new <nombre> [ruta]")
    name = parts[0].strip()
    if re.search(r'[\\/:*?"<>|]', name):
        raise AgentNavError(f"el nombre no puede llevar \\ / : * ? \" < > |  ({name})")
    path = os.path.abspath(parts[1].strip().strip('"')) if len(parts) > 1 else os.path.join(new_project_base(), name)
    projects = load_projects()
    taken = next((p for p in projects if _norm_path(p["path"]) == _norm_path(path)), None)
    if taken:
        raise AgentNavError(f"{path} ya está registrada como {taken['name']}")
    if os.path.isfile(path):
        raise AgentNavError(f"{path} es un archivo")
    if os.path.isdir(path):
        print(f"{name}: la carpeta ya existía, la registro: {path}")
    else:
        try:
            os.makedirs(path)
        except OSError as e:
            raise AgentNavError(f"no pude crear {path}: {e}")
        print(f"{name}: carpeta creada en {path}")
    add_project(name, path)
    print(f"{name}: registrado en {PROJECTS_PATH}")
    open_project(_project_or_die(name))
    if not inside_herdr():
        attach()
    return 0


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


def _norm_path(p):
    return os.path.normcase(os.path.normpath(p))


# ---------------------------------------------------------------- Claude Code: conversaciones previas, recientes

def claude_project_key(path):
    """Nombre de la carpeta de Claude Code para un cwd: todo lo que no es letra o dígito se vuelve '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(path))


@functools.lru_cache(maxsize=1)
def _claude_project_dirs():
    try:
        return {n.lower(): os.path.join(CLAUDE_PROJECTS, n) for n in os.listdir(CLAUDE_PROJECTS)}
    except OSError:
        return {}


def has_conversation(path):
    """Claude guardó alguna conversación para esa carpeta (sin distinguir mayúsculas: el cwd real puede variar)."""
    d = _claude_project_dirs().get(claude_project_key(path).lower())
    if not d:
        return False
    try:
        return any(n.endswith(".jsonl") for n in os.listdir(d))
    except OSError:
        return False


def _cwd_from_dir(d):
    """Lee el cwd real de la última conversación guardada en una carpeta de ~/.claude/projects."""
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return None, 0
    if not files:
        return None, 0
    files.sort(key=lambda f: -os.path.getmtime(f))
    cwd = None
    for path in files[:3]:  # una sesión muerta al nacer puede no traer cwd: probar las anteriores
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for _ in range(60):
                    line = f.readline()
                    if not line:
                        break
                    m = re.search(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', line)
                    if m:
                        try:
                            cwd = json.loads('"' + m.group(1) + '"')
                        except json.JSONDecodeError:
                            cwd = None
                        if cwd:
                            break
        except OSError:
            pass
        if cwd:
            break
    if not cwd:
        # Decode de respaldo: ambiguo si la ruta tenía guiones; el que llama descarta lo que no exista.
        base = os.path.basename(d)
        if re.match(r"^[A-Za-z]--", base):
            cwd = base[0] + ":\\" + base[3:].replace("-", "\\")
    return cwd, os.path.getmtime(files[0])


def recent_projects(projects, limit=8):
    """Carpetas donde corrió Claude Code que no están en el registro, de la más reciente a la más vieja."""
    known = {_norm_path(p["path"]) for p in projects}
    seen, out = set(), []
    try:
        dirs = [os.path.join(CLAUDE_PROJECTS, n) for n in os.listdir(CLAUDE_PROJECTS)]
    except OSError:
        return []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        cwd, when = _cwd_from_dir(d)
        if not cwd or not os.path.isdir(cwd):
            continue
        k = _norm_path(cwd)
        if k in known or k in seen or "\\appdata\\" in k or "\\temp\\" in k:
            continue
        if k == _norm_path(USERPROFILE):
            continue
        seen.add(k)
        out.append({"path": os.path.normpath(cwd), "when": when})
    out.sort(key=lambda r: -r["when"])
    return out[:limit]


def last_herdr_session(path, exclude=()):
    """Id de la última conversación que recibió pedidos DENTRO de un panel de Herdr en esa carpeta, según el diario,
    siempre que Claude todavía la guarde. Herdr retoma lo de Herdr: lo que corre en otra terminal no se toca."""
    want = _norm_path(path)
    d = _claude_project_dirs().get(claude_project_key(path).lower())
    if not d:
        return None
    try:
        files = [n for n in os.listdir(d) if n.endswith(".jsonl")]
        days = sorted((n[:-4] for n in os.listdir(JOURNAL_DIR) if n.endswith(".log")), reverse=True)[:60]
    except OSError:
        return None
    for day in days:
        for e in reversed(read_journal(day)):
            if e["event"] not in ("prompt", "stop") or not e["cwd"] or _norm_path(e["cwd"]) != want:
                continue
            sid = next((n[:-6] for n in files if n.lower().startswith(e["sid"].lower())), None)
            if sid and sid not in exclude:
                return sid
    return None


# ---------------------------------------------------------------- procesos de Windows (quién corre dónde)

_PROC_NAMES = frozenset(("claude.exe", "node.exe", "herdr.exe"))


def _process_table(names):
    """Todos los procesos (pid, ppid, nombre) y, para los de `names`, su cwd y línea de comando leídos del PEB con ctypes.
    WMI tarda medio segundo; esto, unos milisegundos. Sólo Python de 64 bits."""
    import ctypes
    from ctypes import wintypes
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return []
    k32, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    class PBI(ctypes.Structure):
        _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p), ("Reserved2", ctypes.c_void_p * 2),
                    ("UniqueProcessId", ctypes.c_void_p), ("Reserved3", ctypes.c_void_p)]

    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE32)]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]

    def read(h, addr, size):
        buf, got = ctypes.create_string_buffer(size), ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)) or got.value != size:
            return None
        return buf.raw

    def ustr(h, addr):  # UNICODE_STRING {Length, MaximumLength, Buffer} en la memoria del otro proceso
        raw = read(h, addr, 16)
        if not raw:
            return ""
        n, p = int.from_bytes(raw[0:2], "little"), int.from_bytes(raw[8:16], "little")
        if not n or n > 65536 or not p:
            return ""
        raw = read(h, p, n)
        return raw.decode("utf-16-le", "replace") if raw else ""

    def details(pid):
        h = k32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ
        if not h:
            return "", ""
        try:
            pbi, ret = PBI(), wintypes.ULONG()
            if ntdll.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret)) != 0 or not pbi.PebBaseAddress:
                return "", ""
            raw = read(h, pbi.PebBaseAddress + 0x20, 8)  # PEB.ProcessParameters
            if not raw:
                return "", ""
            params = int.from_bytes(raw, "little")
            return ustr(h, params + 0x38), ustr(h, params + 0x70)  # CurrentDirectory.DosPath, CommandLine
        finally:
            k32.CloseHandle(h)

    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == 2 ** 64 - 1:
        return []
    out = []
    pe = PE32()
    pe.dwSize = ctypes.sizeof(PE32)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            name = pe.szExeFile.lower()
            cwd, cmd = details(pe.th32ProcessID) if name in names else ("", "")
            out.append({"pid": pe.th32ProcessID, "ppid": pe.th32ParentProcessID, "name": name, "cwd": cwd, "cmd": cmd})
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


@functools.lru_cache(maxsize=1)
def _procs():
    try:
        return _process_table(_PROC_NAMES)
    except Exception:
        return []


def _under_herdr(proc, by_pid):
    """El proceso desciende del servidor de Herdr (es un panel) o de un cliente."""
    seen, p = set(), proc
    while p and p["pid"] not in seen:
        seen.add(p["pid"])
        p = by_pid.get(p["ppid"])
        if p and p["name"] == "herdr.exe":
            return True
    return False


def claudes_outside_herdr(path):
    """Cuántos Claude Code corren en esa carpeta fuera de Herdr (una pestaña de Windows Terminal, por ejemplo)."""
    procs = _procs()
    by_pid = {p["pid"]: p for p in procs}
    want = _norm_path(path)
    n = 0
    for p in procs:
        is_claude = p["name"] == "claude.exe" or (p["name"] == "node.exe" and "claude" in p["cmd"].lower()
                                                   and (by_pid.get(p["ppid"]) or {}).get("name") != "claude.exe")
        if is_claude and p["cwd"] and _norm_path(p["cwd"]) == want and not _under_herdr(p, by_pid):
            n += 1
    return n


def herdr_processes():
    """(servidor, [clientes]) entre los herdr.exe vivos."""
    server, clients = None, []
    for p in _procs():
        if p["name"] != "herdr.exe":
            continue
        if re.search(r'herdr(\.exe)?"?\s+server\b', p["cmd"], re.I):
            server = p
        else:
            clients.append(p)
    return server, clients


# ---------------------------------------------------------------- git

def git_info(path, timeout=4):
    """(rama, cambios pendientes) o None si no es un repo o git no contesta a tiempo."""
    # ".git" es carpeta en un clon y archivo en un worktree.
    if not os.path.exists(os.path.join(path, ".git")):
        return None
    git = shutil.which("git")
    if not git:
        return None
    try:
        # Un solo proceso: rama + cambios. --no-optional-locks no toma index.lock y no pisa a un git ajeno.
        s = subprocess.run([git, "--no-optional-locks", "-C", path, "status", "--porcelain=v2", "--branch", "-uno"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError):
        return ("…", None)
    if s.returncode != 0:
        return None
    branch, dirty = "HEAD suelto", 0
    for line in s.stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[14:].strip()
            if head != "(detached)":
                branch = head
        elif line[:1] in ("1", "2", "u"):
            dirty += 1
    return branch, dirty


def git_info_start(projects):
    """Lanza git por proyecto en hilos. Devuelve (dict que se va llenando, lista de hilos)."""
    import threading
    out = {}

    def one(p):
        out[p["name"]] = git_info(p["path"])

    threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in projects]
    for t in threads:
        t.start()
    return out, threads


def git_wait(threads, wait):
    deadline = time.monotonic() + wait
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))


def git_info_all(projects, wait=2.0):
    out, threads = git_info_start(projects)
    git_wait(threads, wait)
    return out


def git_text(info):
    if info is None:
        return ""
    branch, dirty = info
    if dirty is None:
        return branch
    return f"{branch} ±{dirty}" if dirty else f"{branch} ✓"


# ---------------------------------------------------------------- acciones

def _continue_args(a, path, say, used, others_live):
    """Qué conversación retoma un Claude con `continue`: la última que tuvo pedidos dentro de Herdr en esa carpeta
    (--resume), que no esté viva en otro panel. Sin una, --continue sólo si ningún otro Claude corre en la carpeta:
    --continue agarra la conversación MÁS NUEVA, que puede ser la que está abierta en otra terminal."""
    sid = last_herdr_session(path, exclude=used)
    if sid:
        used.add(sid)
        return ["--resume", sid]
    if not has_conversation(path):
        return []
    if others_live:
        say(f"  {a['name']}: otro Claude del proyecto ya está en esa carpeta; arranca una conversación nueva.")
    elif claudes_outside_herdr(path):
        say(f"  {a['name']}: hay un Claude corriendo en esa carpeta fuera de Herdr; arranca una conversación nueva para no pisarla.")
    else:
        return ["--continue"]
    return []


def _start_herdr_agent(a, path, pane, timeout_ms, say, used=None, others_live=False):
    """Arranca un agente que Herdr conoce (claude, codex…). Devuelve True si quedó listo."""
    args = list(a["args"])
    if a["continue"] and a["kind"] == "claude" and "--continue" not in args and "--resume" not in args:
        args += _continue_args(a, path, say, used if used is not None else set(), others_live)
    extra = f" {' '.join(args)}" if args else ""
    say(f"  {a['name']}: arrancando {a['kind']}{extra} en {pane}…")
    try:
        cli = ["agent", "start", a["name"], "--kind", a["kind"], "--pane", pane, "--timeout", str(timeout_ms)]
        if args:
            cli += ["--", *args]
        api(*cli, timeout=timeout_ms / 1000 + 10)
        say(f"  {a['name']}: listo.")
        return True
    except AgentNavError as e:
        if "agent_not_ready" in str(e):
            say(f"  {a['name']}: espera el diálogo de confianza de carpeta de Claude; respondelo en el panel.")
        else:
            say(f"  {a['name']}: no arrancó ({e})")
        return False


PROMPT_RE = r"(PS [^\n]*> ?|\$ ?)$"  # prompt de pwsh / Windows PowerShell, o de un shell tipo bash


def wait_prompt(pane, timeout_ms):
    """Espera a que el panel muestre un prompt de shell. Devuelve False si venció el plazo (y se sigue igual)."""
    code, _, _ = run("pane", "wait-output", pane, "--regex", PROMPT_RE, "--source", "visible",
                     "--timeout", str(timeout_ms), timeout=timeout_ms / 1000 + 5)
    return code == 0


def find_ws(snap, name):
    """El primer espacio cuya etiqueta coincide con el nombre del proyecto (una sola regla para todos los comandos)."""
    low = name.lower()
    return next((w for w in snap["workspaces"] if ws_label(w) == low), None)


def _agent_present(live, base, kind):
    """Un agente pedido ya está si en el espacio vive uno del mismo tipo llamado base o base-N (sufijo por colisión)."""
    pat = re.compile(r"^" + re.escape(agent_name(base, set())) + r"(-\d+)?$")
    return any(a.get("agent") == kind and pat.match(a.get("name") or "") for a in live)


def _start_shell(a, pane, say):
    """Panel de shell común: le pone nombre y, si hay comando, lo lanza."""
    try:
        api("pane", "rename", pane, a["name"])
    except AgentNavError:
        pass
    if not a["command"]:
        say(f"  {a['name']}: shell en {pane}.")
        return True
    say(f"  {a['name']}: {a['command']}  en {pane}")
    # "pane run" no devuelve JSON cuando sale bien: sólo el código de salida dice algo.
    code, out, err = run("pane", "run", pane, a["command"], timeout=30)
    if code != 0:
        say(f"  {a['name']}: no pude mandar el comando ({(err or out)[:160]})")
        return False
    return True


def _new_pane(a, wid, path, prev_pane, label):
    """Panel para el agente: split del anterior si lo pide, si no una pestaña nueva."""
    if a["split"] and prev_pane:
        cli = ["pane", "split", prev_pane, "--direction", a["split"], "--cwd", path, "--no-focus"]
        if a["ratio"]:
            cli += ["--ratio", str(a["ratio"])]
        r = api(*cli)
        return r["pane"]["pane_id"]
    t = api("tab", "create", "--workspace", wid, "--cwd", path, "--label", label, "--no-focus")
    return t["root_pane"]["pane_id"]


def _idle_shell_pane(snap, wid):
    """El panel que Herdr deja al restaurar un espacio tras reiniciar el servidor: el único del espacio, sin agente
    y con sólo el shell en primer plano. Se reutiliza en vez de dejarlo vacío al lado del agente repuesto."""
    panes = [x for x in snap.get("panes", []) if x.get("workspace_id") == wid and not x.get("agent")]
    if len(panes) != 1:
        return None, None
    try:
        info = api("pane", "process-info", "--pane", panes[0]["pane_id"]).get("process_info") or {}
    except AgentNavError:
        return None, None
    fg = info.get("foreground_processes") or []
    if len(fg) == 1 and os.path.basename(fg[0].get("name") or "").lower() in ("pwsh.exe", "powershell.exe", "cmd.exe"):
        return panes[0]["pane_id"], panes[0].get("tab_id")
    return None, None


def _place_agents(p, wid, agents, taken, first_pane, first_tab, start_timeout_ms, say, live_sids=(), others_live=False):
    """Crea paneles y arranca los agentes de la lista. Devuelve True si todos quedaron bien."""
    all_ok, prev_pane = True, None
    used = set(live_sids)  # conversaciones que ya corren en algún panel: ningún agente nuevo las retoma
    for i, a in enumerate(agents):
        a = dict(a)
        if a["kind"] != SHELL_KIND:
            a["name"] = agent_name(a["name"], taken)  # sufijo sólo si otro espacio ya usa ese nombre
        try:
            if i == 0 and first_pane:
                pane = first_pane
                if first_tab:
                    try:
                        api("tab", "rename", first_tab, a["name"])
                    except AgentNavError:
                        pass
            else:
                pane = _new_pane(a, wid, p["path"], prev_pane, a["name"])
            if a["kind"] == SHELL_KIND:
                if a["command"]:
                    wait_prompt(pane, 10000)  # pwsh en frío tarda hasta ~3 s en llegar al prompt
                all_ok &= _start_shell(a, pane, say)
            else:
                all_ok &= _start_herdr_agent(a, p["path"], pane, start_timeout_ms, say, used, others_live)
                others_live = True  # el siguiente Claude del mismo proyecto no debe hacer --continue sobre éste
            prev_pane = pane
        except AgentNavError as e:
            say(f"  {a['name']}: {e}")
            all_ok = False
    return all_ok


def open_project(p, say=print, start_timeout_ms=90000):
    """Abre el proyecto como espacio de Herdr, o lo enfoca y repone los agentes que falten.
    Devuelve (modo, todos_listos) con modo 'created' o 'focused'."""
    if ensure_server(say):
        restore_projects([q for q in load_projects() if q["name"] != p["name"]], say)
    snap = snapshot()
    taken = {a.get("name") for a in snap["agents"] if a.get("name")}
    live_sids = {(a.get("agent_session") or {}).get("value") for a in snap["agents"]} - {None, ""}
    wanted = p["agents"]

    ws = find_ws(snap, p["name"])
    if ws:
        wid = ws["workspace_id"]
        api("workspace", "focus", wid)
        live = [a for a in snap["agents"] if a.get("workspace_id") == wid]
        # Sólo se reponen agentes que Herdr conoce; los paneles de shell no se distinguen de uno abierto a mano.
        missing = [a for a in wanted if a["kind"] != SHELL_KIND and not _agent_present(live, a["name"], a["kind"])]
        if not missing:
            say(f"{p['name']}: ya estaba abierto, enfocado.")
            return "focused", True
        say(f"{p['name']}: abierto; faltan {', '.join(a['name'] for a in missing)}.")
        missing = [dict(a, split=None) for a in missing]  # cada repuesto en su pestaña
        spare_pane, spare_tab = (None, None) if live else _idle_shell_pane(snap, wid)  # el panel vacío de una restauración
        others = any(a.get("agent") == "claude" for a in live)
        return "focused", _place_agents(p, wid, missing, taken, spare_pane, spare_tab, start_timeout_ms, say, live_sids, others)

    if not os.path.isdir(p["path"]):
        raise AgentNavError(f"{p['name']}: la carpeta no existe: {p['path']}")
    say(f"{p['name']}: abriendo espacio en {p['path']}…")
    r = api("workspace", "create", "--cwd", p["path"], "--label", p["name"])
    wid = r["workspace"]["workspace_id"]
    ok = _place_agents(p, wid, wanted, taken, r["root_pane"]["pane_id"], r["tab"]["tab_id"], start_timeout_ms, say, live_sids)
    return "created", ok


def restore_projects(projects, say=print, wait=3.0):
    """Recién levantado el servidor, Herdr restaura cada espacio con un panel de shell vacío y sin agentes:
    a los que son proyectos registrados les repone los agentes en ese mismo panel."""
    deadline = time.time() + wait
    while True:
        snap = snapshot()
        found = [p for p in projects if find_ws(snap, p["name"])]
        if found or time.time() >= deadline:
            break
        time.sleep(0.3)
    if found:
        say(f"espacios restaurados por Herdr: {', '.join(p['name'] for p in found)}; repongo los agentes.")
    for p in found:
        try:
            open_project(p, say)
        except AgentNavError as e:
            say(f"{p['name']}: {e}")
    return found


def close_project(p, say=print, grace_ms=5000):
    """Cierra el espacio del proyecto. A los Claude que están en el prompt les manda /exit primero (dispara SessionEnd).
    A uno bloqueado o todavía arrancando no se le manda nada: Enter ahí concedería el permiso o el diálogo de confianza."""
    snap = snapshot()
    ws = find_ws(snap, p["name"])
    if not ws:
        say(f"{p['name']}: no estaba abierto.")
        return False
    wid = ws["workspace_id"]
    claudes = [a for a in snap["agents"] if a.get("workspace_id") == wid and a.get("agent") == "claude" and a.get("pane_id")]
    polite = [a for a in claudes if a.get("interactive_ready") and not a.get("launch_pending")
              and a.get("agent_status") in ("idle", "done")]
    for a in polite:
        try:
            api("pane", "send-text", a["pane_id"], "/exit")
            api("pane", "send-keys", a["pane_id"], "enter")
        except AgentNavError:
            pass
    if polite:
        say(f"{p['name']}: saliendo de {len(polite)} Claude…")
        for a in polite:  # una espera bloqueante por panel en vez de sondear el snapshot
            wait_prompt(a["pane_id"], grace_ms)
    skipped = len(claudes) - len(polite)
    if skipped:
        say(f"{p['name']}: {skipped} Claude ocupado(s) o bloqueado(s) se cierran sin /exit.")
    api("workspace", "close", wid)
    say(f"{p['name']}: espacio {wid} cerrado.")
    return True


def focus_herdr_window():
    """Trae al frente la ventana de Windows Terminal que aloja un cliente de Herdr. True si pudo."""
    import ctypes
    from ctypes import wintypes
    _, clients = herdr_processes()
    hosts = {c["ppid"] for c in clients}
    if not hosts:
        return False
    u32 = ctypes.windll.user32
    for fn in (u32.IsWindowVisible, u32.IsIconic, u32.SetForegroundWindow, u32.GetWindowTextLengthW):
        fn.argtypes = [wintypes.HWND]  # sin esto un HWND de 64 bits se trunca a int
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in hosts and u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
        return True

    u32.EnumWindows(proc(cb), 0)
    if not found:
        return False
    hwnd = found[0]
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Un proceso que no está al frente no puede dar el foco; una pulsación de Alt simulada le da el permiso.
    u32.keybd_event(0x12, 0, 0, 0)
    u32.keybd_event(0x12, 0, 2, 0)  # KEYEVENTF_KEYUP
    u32.SetForegroundWindow(hwnd)
    return True  # con la ventana ubicada, como mucho parpadea en la barra de tareas; abrir otra pestaña sería peor


def cmd_app(say=print):
    """Herdr como aplicación (acceso directo del escritorio): servidor arriba, y la ventana al frente o una pestaña nueva."""
    if ensure_server(say):
        restore_projects(load_projects(), say)
    if inside_herdr():
        say("ya estás dentro de Herdr.")
        return 0
    if focus_herdr_window():
        say("ventana de Herdr al frente.")
        return 0
    attach(say, force=True)
    return 0


def attach(say=print, force=False):
    """Pestaña de Windows Terminal con un cliente de Herdr. Si ya hay una, no abre otra (salvo `agentnav attach`)."""
    if not force:
        _, clients = herdr_processes()
        if clients:
            say("Herdr ya tiene una pestaña abierta en Windows Terminal; pasá a ella (agentnav attach abre otra).")
            return False
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if not wt:
        raise AgentNavError("no encuentro wt.exe (Windows Terminal)")
    try:
        subprocess.Popen([wt, "-w", "0", "new-tab", "--title", "Herdr", herdr_bin()],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        raise AgentNavError(f"no pude abrir Windows Terminal: {e}")
    say("pestaña de Windows Terminal abierta con Herdr.")
    return True


STATUS_GLYPH = {"blocked": "✖", "working": "◐", "done": "✔", "idle": "○", "unknown": "?"}
STATUS_COLOR = {"blocked": "31", "working": "33", "done": "32", "idle": "2", "unknown": "2"}


def paint(text, code):
    return f"\x1b[{code}m{text}\x1b[0m"


def describe(snap, projects):
    """Devuelve filas [(proyecto, ws_id|None, [agentes])] y los agentes sueltos."""
    rows, used = [], set()
    for p in projects:
        ws = find_ws(snap, p["name"])
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


def _snapshot_or_none():
    """Snapshot, o None si el servidor no corre (un solo spawn en vez de 'status server' + snapshot)."""
    try:
        return snapshot()
    except AgentNavError:
        if server_running():
            raise
        return None


def cmd_list():
    projects = load_projects()
    gits, threads = git_info_start(projects)  # git corre mientras hablamos con Herdr
    snap = _snapshot_or_none()
    git_wait(threads, 2.0)
    if snap is None:
        print("servidor de Herdr: no corre (agentnav up)")
        for p in projects:
            print(f"  {p['name']:<14} {git_text(gits.get(p['name'])):<18} {p['path']}")
        return 0
    rows, loose = describe(snap, projects)
    for p, wid, agents in rows:
        state = f"abierto {wid}" if wid else "cerrado"
        print(f"{p['name']:<14} {state:<12} {git_text(gits.get(p['name'])):<18} {p['path']}")
        for a in agents:
            print("    " + agent_line(a))
    if loose:
        print("fuera de proyectos:")
        for a in loose:
            ws = next((w for w in snap["workspaces"] if w.get("workspace_id") == a.get("workspace_id")), {})
            print(f"    {ws.get('label') or a.get('workspace_id')}: " + agent_line(a))
    return 0


def _project_or_die(name):
    p = find_project(load_projects(), name)
    if not p:
        raise AgentNavError(f"no hay un proyecto '{name}' en {PROJECTS_PATH}")
    return p


def cmd_open(name):
    open_project(_project_or_die(name))
    if not inside_herdr():
        attach()
    return 0


def cmd_close(name):
    p = _project_or_die(name)
    if _snapshot_or_none() is None:
        raise AgentNavError("el servidor de Herdr no corre")
    close_project(p)
    return 0


def _tab_source(snap, projects):
    """Desde dónde se pidió la pestaña: espacio y panel del entorno de Herdr (si corre dentro de un panel) o los
    enfocados en la interfaz (cuando lo dispara la tecla). Devuelve (wid, espacio, panel, proyecto registrado o None)."""
    wid = os.environ.get("HERDR_WORKSPACE_ID") or snap.get("focused_workspace_id")
    pid = os.environ.get("HERDR_PANE_ID") or snap.get("focused_pane_id")
    if not wid:
        raise AgentNavError("no hay ningún espacio enfocado donde abrir la pestaña")
    ws = next((w for w in snap["workspaces"] if w.get("workspace_id") == wid), None)
    if not ws:
        raise AgentNavError(f"el espacio {wid} ya no existe")
    pane = next((x for x in snap.get("panes", []) if x.get("pane_id") == pid), None) or {}
    project = next((p for p in projects if p["name"].lower() == ws_label(ws)), None)
    return wid, ws, pane, project


def _tab_agent(snap, wid, pane, project):
    """Qué va en la pestaña nueva: el agente del panel de origen; si ese panel es un shell, el último agente vivo del
    espacio; si no hay ninguno, el agente registrado del proyecto; y si tampoco, un shell. Devuelve None para shell."""
    live = [a for a in snap["agents"] if a.get("workspace_id") == wid]
    src = next((a for a in live if a.get("pane_id") == pane.get("pane_id")), None)
    if not src and live:
        src = max(live, key=lambda a: a.get("state_change_seq") or 0)
    registered = [a for a in (project["agents"] if project else []) if a["kind"] != SHELL_KIND]
    if src:
        kind = src.get("agent") or "claude"
        base = re.sub(r"-\d+$", "", src.get("name") or "") or kind
        # Los argumentos los hereda del agente registrado con ese nombre (o del primero de ese tipo), si lo hay.
        reg = next((a for a in registered if a["name"] == base), None) or next((a for a in registered if a["kind"] == kind), None)
        return {"name": base, "kind": kind, "args": list(reg["args"]) if reg else [], "continue": False}
    if registered:
        return dict(registered[0], **{"continue": False})
    return None


def _notify_error(fn):
    """Desde una tecla o un gancho nadie ve la consola: un error de AgentNav sale como aviso de Herdr."""
    def wrapped(*args, **kw):
        try:
            return fn(*args, **kw)
        except AgentNavError as e:
            try:
                run("notification", "show", "AgentNav", "--body", str(e)[:200], "--sound", "none", timeout=5)
            except AgentNavError:
                pass
            raise
    return wrapped


@_notify_error
def cmd_tab(mode="", say=print, start_timeout_ms=90000):
    """agentnav tab: pestaña nueva en el espacio actual, en la carpeta del panel de origen y con el mismo agente.
    Un Claude nuevo arranca una conversación nueva (nunca --continue: la viva ya está en la otra pestaña).
    `tab shell`: la pestaña pelada de siempre (shell en C:\\), creada por la API para que el plugin no la adopte."""
    snap = snapshot()
    wid, ws, pane, project = _tab_source(snap, load_projects())
    if mode == "shell":
        path = new_project_base()
        say(f"{ws.get('label') or wid}: pestaña de shell en {path}")
        api("tab", "create", "--workspace", wid, "--cwd", path, "--focus")
        return 0
    path = pane.get("cwd") or ""
    if not os.path.isdir(path):
        path = project["path"] if project and os.path.isdir(project["path"]) else new_project_base()
    a = _tab_agent(snap, wid, pane, project)
    taken = {x.get("name") for x in snap["agents"] if x.get("name")}
    label = agent_name(a["name"], taken) if a else os.path.basename(path.rstrip("\\/")) or "shell"
    say(f"{ws.get('label') or wid}: pestaña {label} en {path}")
    t = api("tab", "create", "--workspace", wid, "--cwd", path, "--label", label, "--focus")
    if a is None:
        return 0
    a = dict(a, name=label)
    return 0 if _start_herdr_agent(a, path, t["root_pane"]["pane_id"], start_timeout_ms, say, set(), True) else 1


def cmd_adopt(argv, say=print, start_timeout_ms=90000):
    """Gancho `tab.created` del plugin (C:\\AgentNav\\plugin). Herdr lo llama con HERDR_WORKSPACE_ID, HERDR_TAB_ID,
    HERDR_PANE_ID y HERDR_PLUGIN_CONTEXT_JSON. Sólo adopta pestañas abiertas desde la interfaz (el "+" o la tecla de
    Herdr): las que llegan por la API ya vienen armadas (las crea `tab`, `open`, o cualquier otro script).
    El gancho vuelve enseguida: el trabajo (esperar el prompt, cd, arrancar el Claude) sigue en un hijo suelto."""
    ctx = {}
    try:
        ctx = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
    except ValueError:
        pass
    wid, tid, pid = (os.environ.get(k) for k in ("HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID"))
    if not (wid and tid and pid):
        say("adopt: faltan HERDR_WORKSPACE_ID / HERDR_TAB_ID / HERDR_PANE_ID; no hago nada.")
        return 0
    if ctx.get("invocation_source") == "api":
        say(f"adopt: {tid} vino por la API; la dejo como está.")
        return 0
    if "--run" not in argv:
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "adopt", "--run"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
        say(f"adopt: {tid} ({ctx.get('invocation_source') or '?'}) se arma en segundo plano.")
        return 0
    return _adopt_run(wid, tid, pid, say, start_timeout_ms)


@_notify_error
def _adopt_run(wid, tid, pid, say, start_timeout_ms):
    snap = snapshot()
    ws = next((w for w in snap["workspaces"] if w.get("workspace_id") == wid), None)
    if not ws or not any(x.get("pane_id") == pid for x in snap.get("panes", [])):
        return 0  # la cerraron antes de que llegáramos
    project = next((p for p in load_projects() if p["name"].lower() == ws_label(ws)), None)
    a = _tab_agent(snap, wid, {}, project)  # sin panel de origen: el último agente vivo del espacio, o el registrado
    live = [x for x in snap["agents"] if x.get("workspace_id") == wid and x.get("pane_id") != pid]
    src = max(live, key=lambda x: x.get("state_change_seq") or 0) if live else None
    others = [x for x in snap.get("panes", []) if x.get("workspace_id") == wid and x.get("pane_id") != pid]
    path = next((c for c in ((project or {}).get("path"), (src or {}).get("cwd"), *(x.get("cwd") for x in others))
                 if c and os.path.isdir(c)), None)
    if not path and not a:
        return 0  # nada que saber del espacio: queda la pestaña tal como la abrió Herdr
    if not wait_prompt(pid, 15000):
        raise AgentNavError(f"{tid}: el shell no llegó al prompt; la pestaña queda como está")
    if path:
        say(f"{ws.get('label') or wid}: {tid} → {path}")
        code, out, err = run("pane", "run", pid, f"Set-Location -LiteralPath '{path}'", timeout=30)
        if code != 0:
            raise AgentNavError(f"{tid}: no pude cambiar de carpeta ({(err or out)[:160]})")
        wait_prompt(pid, 5000)
    if not a:
        return 0
    taken = {x.get("name") for x in snap["agents"] if x.get("name")}
    label = agent_name(a["name"], taken)
    try:
        api("tab", "rename", tid, label)
    except AgentNavError:
        pass
    return 0 if _start_herdr_agent(dict(a, name=label), path or new_project_base(), pid, start_timeout_ms, say, set(), True) else 1


def cmd_recent():
    for r in recent_projects(load_projects(), limit=20):
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['when']))}  {r['path']}")
    return 0


# ---------------------------------------------------------------- diario

def _journal_path(day):
    return os.path.join(JOURNAL_DIR, day + ".log")


def read_journal(day):
    """Líneas del hook: HH:MM:SS<TAB>cwd<TAB>sid<TAB>evento<TAB>texto."""
    path = _journal_path(day)
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\r\n").split("\t", 4)
            if len(parts) < 4:
                continue
            while len(parts) < 5:
                parts.append("")
            out.append({"time": parts[0], "cwd": parts[1], "sid": parts[2], "event": parts[3], "text": parts[4]})
    return out


def _secs(hms):
    try:
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s
    except ValueError:
        return None


def _fmt_dur(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {(seconds % 3600) // 60:02d} min"


def cmd_hoy(arg):
    arg = (arg or "").strip().lower()
    if arg in ("", "hoy"):
        day = time.strftime("%Y-%m-%d")
    elif arg == "ayer":
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", arg):
        day = arg
    else:
        raise AgentNavError("uso: agentnav hoy [ayer|AAAA-MM-DD]")
    entries = read_journal(day)
    if not entries:
        print(f"{day}: sin actividad registrada (el diario sólo anota los Claude que corren dentro de Herdr).")
        return 0
    projects = load_projects()
    by_path = {_norm_path(p["path"]): p["name"] for p in projects}

    def project_of(cwd):
        k = _norm_path(cwd) if cwd else ""
        if k in by_path:
            return by_path[k]
        for path, name in by_path.items():
            if k.startswith(path + os.sep):
                return name + " (subcarpeta)"
        return os.path.basename(k) or cwd or "?"

    groups = {}
    for e in entries:
        groups.setdefault(project_of(e["cwd"]), []).append(e)
    print(paint(f" {day} ", "7"))
    for name, evs in groups.items():
        prompts = [e for e in evs if e["event"] == "prompt"]
        blocked = [e for e in evs if e["event"] == "blocked"]
        # El hook escribe en el "stop" los segundos medidos desde el prompt (sobrevive a Esc + nuevo pedido y a la
        # medianoche); el reloj del diario es sólo el respaldo para hooks viejos.
        active, open_at = 0, {}
        for e in evs:
            t = _secs(e["time"])
            if e["event"] == "prompt":
                if t is not None:
                    open_at[e["sid"]] = t
            elif e["event"] in ("stop", "end"):
                started = open_at.pop(e["sid"], None)
                measured = int(e["text"]) if re.match(r"^\d+$", e["text"] or "") else -1
                if measured >= 0:
                    active += measured
                elif started is not None and t is not None:
                    active += max(0, t - started)
        sessions = len({e["sid"] for e in evs if e["sid"]})
        head = f"{name}: {len(prompts)} pedidos, {sessions} sesión(es), ~{_fmt_dur(active)} trabajando"
        if blocked:
            head += f", {len(blocked)} veces pidió permiso"
        print()
        print(paint(head, "1"))
        for e in prompts:
            # Un prompt puede traer escapes ANSI o controles: nunca se imprimen crudos en la consola.
            text = re.sub(r"[\x00-\x1f\x7f]", " ", e["text"])
            print(f"  {e['time'][:5]}  {text[:110]}")
    return 0


# ---------------------------------------------------------------- avisos (ntfy)

def ntfy_send(title, body, settings=None):
    """Publica en ntfy según settings.json. Devuelve None si salió, o el motivo como texto."""
    import base64
    import urllib.request
    cfg = (settings if settings is not None else load_settings()).get("ntfy") or {}
    topic = str(cfg.get("topic") or "").strip()
    if not topic:
        return "ntfy apagado: no hay topic en settings.json"
    server = str(cfg.get("server") or "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(f"{server}/{topic}", data=body.encode("utf-8"), method="POST")
    req.add_header("Title", "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?=")
    req.add_header("Tags", "robot")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read()
    except Exception as e:  # cualquier fallo de red se devuelve como texto
        return f"ntfy: {e}"
    return None


def cmd_ntfy_test():
    err = ntfy_send("AgentNav", "aviso de prueba: si lo ves en el teléfono, los avisos funcionan.")
    if err:
        raise AgentNavError(err)
    print("aviso enviado.")
    return 0


# ---------------------------------------------------------------- doctor

def cmd_doctor():
    results = []  # (True|False|None, texto)  None = aviso, no cuenta como problema

    def check(ok, text):
        results.append((ok, text))

    # Herdr
    try:
        hb = herdr_bin()
        code, out, err = run("--version", timeout=10)
        check(True, f"herdr: {hb} ({(out or err).strip() or 'versión desconocida'})")
        up = server_running()
        check(up, "servidor de Herdr corriendo" if up else "servidor de Herdr NO corre (agentnav up)")
    except AgentNavError as e:
        check(False, str(e))
    cur = os.path.join(USERPROFILE, ".herdr", "packages", "standalone", "current")
    on_path = [d for d in os.environ.get("PATH", "").split(os.pathsep) if "\\.herdr\\" in d.lower()]
    if on_path and not any(_norm_path(d) == _norm_path(cur) for d in on_path):
        check(None, f"PATH apunta a una versión fija de Herdr ({on_path[0]}); tras 'herdr update' conviene que apunte a {cur}")
    # Config de Herdr
    cfg_path = os.path.join(os.environ.get("APPDATA", ""), "herdr", "config.toml")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = f.read()
        check("agentnav.py pick" in cfg, "config.toml: popup del selector (prefix+alt+p)")
        check("agentnav.py tab\"" in cfg and 'new_tab = ""' in cfg,
              "config.toml: ctrl+b c abre la pestaña de AgentNav (misma carpeta, mismo agente)")
        check("agentnav.py tab shell" in cfg, "config.toml: ctrl+b shift+c abre la pestaña pelada por la API")
        check('help = "prefix+f1"' in cfg, "config.toml: ayuda en prefix+F1 (el teclado en español no entrega '?')")
        check("[session]" in cfg and "resume_agents_on_restore = true" in cfg, "config.toml: agentes se reanudan al restaurar")
    except OSError:
        check(False, f"no encuentro {cfg_path}")
    # Plugin de Herdr (gancho tab.created → agentnav adopt)
    try:
        plugins = api("plugin", "list", "--json").get("plugins") or []
        mine = next((x for x in plugins if x.get("plugin_id") == "agentnav"), None)
        if mine and mine.get("enabled"):
            check(True, 'plugin de Herdr "agentnav" enlazado: el "+" de la barra abre la pestaña en el proyecto con su agente')
        else:
            check(False, "plugin de Herdr sin enlazar o apagado: herdr plugin link C:\\AgentNav\\plugin")
    except AgentNavError as e:
        check(False, f"plugin de Herdr: {e}")
    # Hooks de Claude Code
    hook = os.path.join(CLAUDE_HOME, "hooks", "agentnav-state.ps1")
    unblock = os.path.join(CLAUDE_HOME, "hooks", "agentnav-unblock.cmd")
    if os.path.isfile(hook):
        with open(hook, "rb") as f:
            bom = f.read(3) == b"\xef\xbb\xbf"
        check(bom, f"hook {os.path.basename(hook)} guardado como UTF-8 con BOM" if bom else f"hook {hook} SIN BOM: PowerShell 5.1 va a romper los acentos")
    else:
        check(False, f"falta el hook {hook}")
    check(os.path.isfile(unblock), f"hook de desbloqueo {os.path.basename(unblock)}" if os.path.isfile(unblock) else f"falta {unblock}")
    try:
        settings = _read_json_file(os.path.join(CLAUDE_HOME, "settings.json"), "settings.json de Claude") or {}
        hooks = settings.get("hooks") or {}

        def registered(event, needle):
            for block in hooks.get(event) or []:
                for h in block.get("hooks") or []:
                    if needle in str(h.get("command", "")):
                        return True
            return False

        for ev, needle in (("UserPromptSubmit", "agentnav-state.ps1\" prompt"), ("Stop", "agentnav-state.ps1\" stop"),
                           ("SessionEnd", "agentnav-state.ps1\" end"), ("Notification", "agentnav-state.ps1\" notify"),
                           ("PostToolUse", "agentnav-unblock.cmd")):
            check(registered(ev, needle), f"settings.json de Claude: hook {ev}")
        check(registered("SessionStart", "herdr-agent-state.ps1"), "settings.json de Claude: hook propio de Herdr (SessionStart)")
    except AgentNavError as e:
        check(False, str(e))
    # Registro y ajustes
    try:
        projects = load_projects()
        check(True, f"projects.json: {len(projects)} proyecto(s)")
        server, _ = herdr_processes()
        if server and server["cwd"]:
            scwd = _norm_path(server["cwd"])
            hit = next((p for p in projects if _norm_path(p["path"]) == scwd), None)
            if hit:
                check(False, f"el servidor de Herdr corre desde la carpeta de {hit['name']} y la retiene: herdr server stop, después agentnav up")
            elif USERPROFILE and scwd != _norm_path(USERPROFILE):
                check(None, f"el servidor de Herdr corre desde {server['cwd']} (retiene esa carpeta hasta que se reinicie)")
            else:
                check(True, "servidor de Herdr arrancado desde tu carpeta de usuario")
        for p in projects:
            if any(a["kind"] == "claude" and a.get("continue") for a in p["agents"]) and claudes_outside_herdr(p["path"]):
                check(None, f"  {p['name']}: hay un Claude corriendo en esa carpeta fuera de Herdr; 'continue' no lo va a pisar, arranca uno nuevo")
            if not os.path.isdir(p["path"]):
                check(False, f"  {p['name']}: la carpeta no existe: {p['path']}")
            if p["agents"] and p["agents"][0]["split"]:
                check(None, f"  {p['name']}/{p['agents'][0]['name']}: 'split' en el primer agente no tiene de qué dividir; va en pestaña")
    except AgentNavError as e:
        check(False, str(e))
    try:
        st = load_settings()
        topic = str((st.get("ntfy") or {}).get("topic") or "")
        check(None, f"avisos ntfy: {'topic configurado' if topic else 'apagados (settings.json → ntfy.topic)'}")
    except AgentNavError as e:
        check(False, str(e))
    # Arranque, Python, Windows Terminal
    vbs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Herdr server.vbs")
    check(os.path.isfile(vbs), "arranque automático del servidor (Herdr server.vbs en Inicio)" if os.path.isfile(vbs) else f"falta {vbs}")
    check(bool(shutil.which("wt.exe") or shutil.which("wt")), "Windows Terminal (wt.exe)")
    check(True, f"Python {sys.version.split()[0]} en {sys.executable}")
    check(bool(shutil.which("git")), "git (para rama y cambios en el selector)")

    bad = 0
    for ok, text in results:
        if ok is True:
            print(paint("✔", "32") + " " + text)
        elif ok is None:
            print(paint("•", "33") + " " + text)
        else:
            bad += 1
            print(paint("✖", "31") + " " + text)
    print()
    print("todo en orden." if not bad else f"{bad} problema(s).")
    return 1 if bad else 0


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


def _getkey_or_change(changed):
    """Como _getkey, pero devuelve None (sin tecla) en cuanto changed() es verdadero, para repintar."""
    import msvcrt
    while not msvcrt.kbhit():
        if changed():
            return None
        time.sleep(0.05)
    return _getkey()


def _ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def cmd_pick():
    projects = load_projects()
    sel, msg = 0, ""
    snap, gits, recents = None, {}, []
    while True:
        if snap is None:
            gits, _ = git_info_start(projects)  # se pinta ya; la columna de git aparece cuando llega
            try:
                snap = snapshot()
            except AgentNavError as e:
                snap, msg = {"workspaces": [], "agents": []}, str(e)
            recents = recent_projects(projects)
        rows, loose = describe(snap, projects)
        items = [("project", r) for r in rows] + [("recent", r) for r in recents]
        sel = min(sel, max(0, len(items) - 1))
        sys.stdout.write("\x1b[2J\x1b[H")
        print(paint(" AgentNav · proyectos ", "7"))
        print()
        if not rows:
            print("  (sin proyectos: 'a' para agregar uno, o editá projects.json)")
        for i, (kind, r) in enumerate(items):
            cursor = "▶" if i == sel else " "
            if kind == "project":
                p, wid, agents = r
                dot = paint("●", "32") if wid else paint("○", "2")
                line = f" {cursor} {dot} {p['name']:<14} {git_text(gits.get(p['name'])):<16} {p['path']}"
                print(paint(line, "7") if i == sel else line)
                for a in agents:
                    print("        " + agent_line(a))
            else:
                if i == len(rows):
                    print()
                    print(paint("  recientes (Enter los registra y abre):", "2"))
                when = time.strftime("%d/%m %H:%M", time.localtime(r["when"]))
                line = f" {cursor}   {os.path.basename(r['path']):<14} {when:<16} {r['path']}"
                print(paint(line, "7") if i == sel else paint(line, "2"))
        if loose:
            print()
            print(paint("  fuera de proyectos:", "2"))
            for a in loose:
                print("        " + agent_line(a))
        print()
        print(paint("  ↑↓ mover · Enter abrir o ir · a agregar · r refrescar · q salir", "2"))
        if msg:
            print("  " + msg)
        painted = len(gits)
        k = _getkey_or_change(lambda: len(gits) != painted)
        if k is None:
            continue  # llegó un resultado de git: repintar
        if k in ("q", "esc"):
            return 0
        if k in ("up", "k"):
            sel = max(0, sel - 1)
        elif k in ("down", "j"):
            sel = min(max(0, len(items) - 1), sel + 1)
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
        elif k == "enter" and items:
            kind, r = items[sel]
            print()
            try:
                if kind == "recent":
                    name = os.path.basename(r["path"]) or r["path"]
                    add_project(name, r["path"])
                    projects = load_projects()
                    p = find_project(projects, name)
                    print(f"  registrado {name}")
                else:
                    p = r[0]
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
    rest = " ".join(argv[1:])
    if cmd in ("", "go"):
        if ensure_server():
            restore_projects(load_projects())
        if inside_herdr():
            print("ya estás dentro de Herdr.")
        else:
            attach()
        return 0
    if cmd == "list":
        return cmd_list()
    if cmd == "open":
        if not rest:
            raise AgentNavError("uso: agentnav open <nombre>")
        return cmd_open(rest)
    if cmd == "close":
        if not rest:
            raise AgentNavError("uso: agentnav close <nombre>")
        return cmd_close(rest)
    if cmd == "pick":
        return cmd_pick()
    if cmd in ("tab", "pestaña", "pestana"):
        return cmd_tab(rest.strip().lower())
    if cmd == "adopt":
        return cmd_adopt(argv[1:])
    if cmd in ("recent", "recientes"):
        return cmd_recent()
    if cmd in ("hoy", "today", "diario"):
        return cmd_hoy(rest)
    if cmd == "doctor":
        return cmd_doctor()
    if cmd in ("ntfy-test", "ntfy"):
        return cmd_ntfy_test()
    if cmd == "up":
        if ensure_server():
            print("servidor arriba.")
            restore_projects(load_projects())
        else:
            print("servidor ya corría.")
        return 0
    if cmd == "attach":
        attach(force=True)
        return 0
    if cmd == "app":
        return cmd_app()
    if cmd in ("new", "nuevo"):
        return cmd_new(rest)
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
