#!/usr/bin/env python3
"""AgentNav — capa fina sobre Herdr para navegar proyectos y agentes.

Uso:
  agentnav                 levanta el servidor de Herdr si hace falta y abre una pestaña de Windows Terminal enganchada
  agentnav list            proyectos registrados, cuáles están abiertos y el estado de cada agente
  agentnav open <nombre>   abre el proyecto como espacio de Herdr con sus agentes adentro (o lo enfoca si ya está)
  agentnav new <nombre> [ruta] [--kind gemini]
                           crea la carpeta (en C:\\ o donde diga new_cwd de Herdr), registra el proyecto y lo abre.
                           --kind (o --gemini): con qué agente; sin la opción, claude
  agentnav close <nombre>  cierra el espacio del proyecto (los agentes salen con /exit o /quit antes)
  agentnav tab [shell|agent]
                           pestaña nueva en el espacio actual: un shell en la misma carpeta que el panel de origen,
                           sin agente (es lo que corre ctrl+b c). Con "shell": pestaña pelada en C:\\ (ctrl+b shift+c).
                           Con "agent": además arranca el mismo agente que el panel de origen (otro Claude, conversación nueva)
  agentnav adopt           lo corre el plugin de Herdr cuando nace una pestaña (el "+" de la barra) o un panel (split):
                           lo lleva a la carpeta del proyecto, como `tab`. No arranca ningún agente
  agentnav pick            selector interactivo (es lo que corre el popup de Herdr con ctrl+b alt+p)
  agentnav recent          carpetas donde usaste Claude Code o Gemini CLI y no están registradas
  agentnav hoy [ayer|AAAA-MM-DD]
                           diario del día: qué le pediste a cada proyecto y cuánto trabajó
  agentnav doctor          verifica la instalación completa (Herdr, hooks, config, shell, arranque) y si origin tiene commits nuevos
  agentnav update [--check]
                           trae lo nuevo de origin (git pull --ff-only) y re-copia hooks, arranque y config de Herdr
                           a su lugar (config con respaldo). --check sólo avisa: sale 0 al día, 10 si hay commits nuevos
  agentnav theme [nombre]  tema de colores de Herdr. Sin nombre: selector con flechas (es lo que corre el popup
                           ctrl+b alt+t; `theme list` sólo imprime). Con nombre lo aplica y recarga al instante.
                           Paletas propias en config\\themes.json: cs16, matrix, procomm; más los temas de Herdr
  agentnav herdr-sync      instala el último herdr.exe del fork con los temas de AgentNav (settings.json → herdr_fork.repo):
                           verifica el SHA-256, guarda el oficial como herdr.exe.oficial y reinicia el servidor.
                           --force lo hace aunque haya agentes trabajando
  agentnav ntfy-test       manda un aviso de prueba al teléfono (settings.json → ntfy)
  agentnav labels          pone ya la etiqueta "<agente> · <tarea>" a todos los paneles con agente (app lo hace solo)
  agentnav up              sólo levanta el servidor
  agentnav attach          sólo abre la pestaña de Windows Terminal
  agentnav app             lo que corre el acceso directo del escritorio: servidor arriba y la ventana de Herdr al frente;
                           de paso hace `update --check` y, si origin tiene commits nuevos, lo avisa dentro de Herdr

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
GEMINI_HOME = os.environ.get("GEMINI_CLI_HOME") or os.path.join(USERPROFILE, ".gemini")
GEMINI_TMP = os.path.join(GEMINI_HOME, "tmp")  # <id del proyecto>\\chats\\session-<fecha>-<8 del sid>.jsonl
GEMINI_REGISTRY = os.path.join(GEMINI_HOME, "projects.json")  # {"projects": {"<ruta en minúsculas>": "<id>"}}
GEMINI_ENV = os.path.join(GEMINI_HOME, ".env")  # GEMINI_API_KEY=… cuando el login es por clave (selectedType gemini-api-key)
GEMINI_TRUSTED = os.path.join(GEMINI_HOME, "trustedFolders.json")  # {"c:/obra": "TRUST_FOLDER" | "TRUST_PARENT" | "DO_NOT_TRUST"}
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AgentNav")
JOURNAL_DIR = os.path.join(STATE_DIR, "journal")
FOCUS_LOG = os.path.join(STATE_DIR, "focus.log")  # lo escribe plugin\focus.py en cada pane.focused: "<espacio> <panel>"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

SHELL_KIND = "shell"
DEFAULT_KIND = "claude"
# Agentes con conversación que se puede retomar y orden de salida: `continue`, "fuera de Herdr" y `close` van por tipo.
EXIT_COMMAND = {"claude": "/exit", "gemini": "/quit"}


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


def field(r, *keys):
    """r["a"]["b"] con un error legible si Herdr devolvió otra forma (un KeyError pelado no llega al aviso)."""
    cur = r
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise AgentNavError(f"respuesta de herdr sin {'.'.join(keys)}: {str(r)[:160]}")
        cur = cur[k]
    return cur


def server_running():
    code, out, err = run("status", "server", timeout=15)
    return "status: running" in (out + err)


def ensure_server(say=print):
    """Devuelve True si lo levantó, False si ya corría."""
    if server_running():
        return False
    say("levantando el servidor de Herdr…")
    try:
        # Entorno limpio: si `agentnav up` lo corre un Claude (desde su Bash), el servidor heredaría CLAUDECODE,
        # CLAUDE_CODE_SESSION_ID de una sesión muerta, CLAUDE_PID… y se los pasaría a cada panel y a cada Claude nuevo.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "HERDR_"))}
        subprocess.Popen([herdr_bin(), "server"], cwd=USERPROFILE or HOME, env=env,
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
        p_kind = str(p.get("kind") or DEFAULT_KIND)
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


def add_project(name, path, kind=DEFAULT_KIND):
    """Agrega al archivo sin tocar lo que ya había (conserva claves ajenas), escritura atómica."""
    raw = _read_projects_raw()
    if any(isinstance(p, dict) and str(p.get("name", "")).lower() == name.lower() for p in raw):
        raise AgentNavError(f"ya hay un proyecto llamado {name}")
    raw.append({"name": name, "path": path, "agents": [agent_name(name, set())], "kind": kind or DEFAULT_KIND, "continue": True})
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


def _check_project_name(name):
    if re.search(r'[\\/:*?"<>|]', name):
        raise AgentNavError(f"el nombre no puede llevar \\ / : * ? \" < > |  ({name})")
    return name


def _project_path(raw):
    """Ruta para registrar, siempre absoluta. `C:x` (relativa a la unidad) y `..\\x` (relativa al cwd) se rechazan:
    abspath las resolvía contra el directorio actual en silencio (`C:AgentNav` desde C:\\AgentNav dio C:\\AgentNav\\AgentNav)."""
    p = raw.strip().strip('"')
    drive, tail = os.path.splitdrive(p)
    if drive and tail[:1] not in ("\\", "/"):
        raise AgentNavError(f"ruta relativa a la unidad ({p}): escribila completa, {drive}\\{tail}")
    if not drive or not os.path.isabs(p):
        raise AgentNavError(f"la ruta tiene que ser completa, con unidad ({p})")
    return os.path.normpath(p)


def _new_args(argv):
    """Argumentos de `new`: (nombre, ruta o "", kind). --kind X, --kind=X o --<kind> (--gemini, --claude) en cualquier
    posición; el resto, nombre y ruta (la ruta puede llevar espacios sin comillas, como antes)."""
    words, kind = [], DEFAULT_KIND
    it = iter(argv)
    for w in it:
        low = w.lower()
        if low == "--kind":
            kind = next(it, "").strip().lower()
        elif low.startswith("--kind="):
            kind = w[7:].strip().lower()
        elif low in ("--gemini", "--claude"):
            kind = low[2:]
        elif low.startswith("--"):
            raise AgentNavError(f"opción desconocida: {w} (uso: agentnav new <nombre> [ruta] [--kind gemini])")
        else:
            words.append(w)
    if not kind or kind == SHELL_KIND or not re.fullmatch(r"[a-z][a-z0-9_-]*", kind):
        raise AgentNavError(f"--kind tiene que ser un agente que Herdr conozca (claude, gemini, codex…), no '{kind}'")
    if not words:
        raise AgentNavError("uso: agentnav new <nombre> [ruta] [--kind gemini]")
    return words[0], " ".join(words[1:]), kind


def cmd_new(argv):
    """agentnav new <nombre> [ruta] [--kind gemini]: crea la carpeta, registra el proyecto y lo abre con su agente."""
    raw_name, raw_path, kind = _new_args(argv)
    name = _check_project_name(raw_name.strip())
    path = _project_path(raw_path) if raw_path else os.path.join(new_project_base(), name)
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
    add_project(name, path, kind)
    print(f"{name}: registrado en {PROJECTS_PATH} ({kind})")
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


RECENT_SKIP = ("\\appdata\\", "\\temp\\")  # carpetas que `recent` no propone (trozos de la ruta en minúsculas)


def recent_projects(projects, limit=8):
    """Carpetas donde corrió Claude Code o Gemini CLI que no están en el registro, de la más reciente a la más vieja.
    Cada una trae "kind" (el agente que la usó; si los dos, el más reciente)."""
    known = {_norm_path(p["path"]) for p in projects}
    seen, out = set(), []
    try:
        dirs = [os.path.join(CLAUDE_PROJECTS, n) for n in os.listdir(CLAUDE_PROJECTS)]
    except OSError:
        dirs = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        cwd, when = _cwd_from_dir(d)
        if not cwd or not os.path.isdir(cwd):
            continue
        k = _norm_path(cwd)
        if k in known or k in seen or any(s in k for s in RECENT_SKIP) or k == _norm_path(USERPROFILE):
            continue
        seen.add(k)
        out.append({"path": os.path.normpath(cwd), "when": when, "kind": "claude"})
    for r in recent_gemini_projects(known, set()):  # una carpeta con los dos agentes sale una vez, con el más nuevo
        hit = next((x for x in out if _norm_path(x["path"]) == _norm_path(r["path"])), None)
        if hit is None:
            out.append(r)
        elif r["when"] > hit["when"]:
            hit.update(r)
    out.sort(key=lambda r: -r["when"])
    return out[:limit]


def last_herdr_session(path, exclude=(), kind="claude"):
    """Id de la última conversación que recibió pedidos DENTRO de un panel de Herdr en esa carpeta, según el diario,
    siempre que el agente todavía la guarde (Claude en ~/.claude/projects, Gemini en ~/.gemini/tmp). El diario no
    anota el tipo: una sesión es de Claude o de Gemini según quién tenga el archivo. Herdr retoma lo de Herdr: lo que
    corre en otra terminal no se toca."""
    want = _norm_path(path)
    skip = {str(x).lower() for x in exclude}
    if kind == "gemini":
        by_short = {s: f for f, s in reversed(gemini_sessions(path)) if s}  # ante un choque de 8, el más nuevo
        if not by_short:
            return None

        def stored(sid):  # el diario trae los 8 primeros (sidShort); --resume necesita el uuid entero del archivo
            f = by_short.get(sid.lower()[:8])
            return gemini_sid_of(f) if f else None
    else:
        d = _claude_project_dirs().get(claude_project_key(path).lower())
        if not d:
            return None
        try:
            files = [n for n in os.listdir(d) if n.endswith(".jsonl")]
        except OSError:
            return None

        def stored(sid):
            return next((n[:-6] for n in files if n.lower().startswith(sid.lower())), None)
    try:
        days = sorted((n[:-4] for n in os.listdir(JOURNAL_DIR) if n.endswith(".log")), reverse=True)[:60]
    except OSError:
        return None
    for day in days:
        for e in reversed(read_journal(day)):
            if e["event"] not in ("prompt", "stop") or not e["cwd"] or _norm_path(e["cwd"]) != want or not e["sid"]:
                continue
            sid = stored(e["sid"])
            if sid and sid.lower() not in skip:
                return sid
    return None


# ---------------------------------------------------------------- Gemini CLI: sesiones guardadas

def _gemini_norm(path):
    """Clave del registro de Gemini (ProjectRegistry.normalizePath): ruta absoluta y, en Windows, en minúsculas."""
    return os.path.normpath(os.path.abspath(path)).lower()


def gemini_project_hash(path):
    """Carpeta vieja de ~/.gemini/tmp (antes del registro): SHA-256 hex de la ruta tal cual la ve Node."""
    import hashlib
    return hashlib.sha256(os.path.normpath(path).encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=1)
def _gemini_registry():
    """{ruta normalizada: id corto} de ~/.gemini/projects.json (Gemini CLI 0.68: tmp/<id corto>, ya no el hash)."""
    data = _read_json_file(GEMINI_REGISTRY, "projects.json de Gemini") if os.path.isfile(GEMINI_REGISTRY) else None
    projects = (data or {}).get("projects") if isinstance(data, dict) else None
    return {str(k).lower(): str(v) for k, v in (projects or {}).items() if v} if isinstance(projects, dict) else {}


def gemini_project_dir(path):
    """Carpeta de ~/.gemini/tmp de ese proyecto: la del registro; si no está, la que tenga un .project_root con esa
    ruta; si tampoco, la del hash viejo. None si Gemini nunca corrió ahí."""
    key = _gemini_norm(path)
    try:
        slug = _gemini_registry().get(key)
    except AgentNavError:
        slug = None
    cands = [slug] if slug else []
    if not cands:
        for d, owner in gemini_project_markers():
            if owner == key:
                cands.append(os.path.basename(d))
    cands += [gemini_project_hash(c) for c in (os.path.normpath(path), os.path.realpath(path))]
    for c in cands:
        d = os.path.join(GEMINI_TMP, c)
        if os.path.isdir(d):
            return d
    return None


def gemini_project_markers():
    """[(carpeta de tmp, ruta dueña normalizada)] según los .project_root que Gemini deja en cada tmp/<id>."""
    out = []
    try:
        names = os.listdir(GEMINI_TMP)
    except OSError:
        return out
    for n in names:
        d = os.path.join(GEMINI_TMP, n)
        try:
            with open(os.path.join(d, ".project_root"), encoding="utf-8", errors="replace") as f:
                owner = f.read().strip()
        except OSError:
            continue
        if owner:
            out.append((d, _gemini_norm(owner)))
    return out


_GEMINI_CHAT_RE = re.compile(r"^session-.*-([0-9a-f]{8})\.jsonl?$", re.I)


def gemini_sessions(path):
    """Sesiones que Gemini CLI guardó para esa carpeta (tmp/<id>/chats/session-<fecha>-<8 del sid>.jsonl; las .json son
    del formato viejo), nuevas primero: [(archivo, 8 primeros del sid en minúsculas o "")]."""
    d = gemini_project_dir(path)
    if not d:
        return []
    chats = os.path.join(d, "chats")
    try:
        files = [os.path.join(chats, n) for n in os.listdir(chats) if n.lower().endswith((".json", ".jsonl"))]
    except OSError:
        return []
    files.sort(key=lambda f: -os.path.getmtime(f))
    out = []
    for f in files:
        m = _GEMINI_CHAT_RE.match(os.path.basename(f))
        out.append((f, m.group(1).lower() if m else ""))
    return out


def has_gemini_conversation(path):
    return bool(gemini_sessions(path))


def gemini_session_file(path, sid):
    """El archivo de la sesión con ese id (por los 8 del nombre; el id entero está en el primer registro)."""
    short = str(sid).lower()[:8]
    for f, s in gemini_sessions(path):
        if s == short:
            return f
    return None


def gemini_sid_of(file):
    """Id entero de una sesión, leído de su primer registro ({"sessionId": …}); None si no se puede."""
    try:
        with open(file, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return None
    m = re.search(r'"sessionId"\s*:\s*"([^"]+)"', head)
    return m.group(1).lower() if m else None


def _gemini_newest_sid(path):
    """Id entero de la sesión más nueva de la carpeta (la que `--resume latest` elige)."""
    for f, _ in gemini_sessions(path)[:1]:
        return gemini_sid_of(f)
    return None


def recent_gemini_projects(known, seen):
    """Carpetas con sesiones de Gemini que no están en el registro, por los .project_root de ~/.gemini/tmp."""
    out = []
    for d, owner in gemini_project_markers():
        chats = os.path.join(d, "chats")
        try:
            when = max(os.path.getmtime(os.path.join(chats, n)) for n in os.listdir(chats))
        except (OSError, ValueError):
            continue
        if not os.path.isdir(owner):
            continue
        real = os.path.normpath(os.path.realpath(owner))  # el registro guarda la ruta en minúsculas
        k = _norm_path(real)
        if k in known or k in seen or any(s in k for s in RECENT_SKIP) or k == _norm_path(USERPROFILE):
            continue
        seen.add(k)
        out.append({"path": real, "when": when, "kind": "gemini"})
    return out


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


def _process_env_names(pid):
    """Nombres de las variables de entorno de otro proceso (bloque leído del PEB; sólo Python de 64 bits).
    Lo usa doctor para ver si el servidor de Herdr heredó CLAUDE* de un Claude. None si no se pudo leer."""
    import ctypes
    from ctypes import wintypes
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    k32, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    pbi = (ctypes.c_void_p * 6)()
    h = k32.OpenProcess(0x0410, False, pid)
    if not h:
        return None
    try:
        def read(addr, size):
            buf, got = ctypes.create_string_buffer(size), ctypes.c_size_t()
            ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
            return buf.raw[:got.value] if ok and got.value else None
        if ntdll.NtQueryInformationProcess(h, 0, pbi, ctypes.sizeof(pbi), ctypes.byref(wintypes.ULONG())) != 0 or not pbi[1]:
            return None
        raw = read(pbi[1] + 0x20, 8)  # PEB.ProcessParameters
        if not raw:
            return None
        params = int.from_bytes(raw, "little")
        env_ptr, env_size = read(params + 0x80, 8), read(params + 0x3F0, 8)  # Environment, EnvironmentSize
        if not env_ptr or not env_size:
            return None
        env_ptr, env_size = int.from_bytes(env_ptr, "little"), int.from_bytes(env_size, "little")
        if not env_ptr or not 0 < env_size <= 4 * 1024 * 1024:
            return None
        block = read(env_ptr, env_size)
        if not block:
            return None
        names = []
        for entry in block.decode("utf-16-le", "replace").split("\0"):
            if entry and not entry.startswith("="):
                names.append(entry.split("=", 1)[0])
        return names
    finally:
        k32.CloseHandle(h)


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


_GEMINI_CMD_RE = re.compile(r"@google[\\/]gemini-cli[\\/]|[\\/]gemini(\.js|\.cmd)?(\"|\s|$)", re.I)


def _is_agent_proc(p, kind, by_pid=None):
    """El proceso es un agente de ese tipo (y no un hijo suyo del mismo tipo: un node bajo claude.exe, un worker
    de gemini). Claude Code es claude.exe o un node con "claude" en la línea; Gemini CLI es el node que lanza
    gemini.cmd de npm (node "…\\@google\\gemini-cli\\bundle\\gemini.js"), que se relanza a sí mismo con más memoria."""
    name, cmd = p.get("name") or "", p.get("cmd") or ""
    parent = (by_pid or {}).get(p.get("ppid")) or {}
    if kind == "claude":
        if name == "claude.exe":
            return True
        return name == "node.exe" and "claude" in cmd.lower() and parent.get("name") != "claude.exe"
    if kind == "gemini":
        return name == "node.exe" and bool(_GEMINI_CMD_RE.search(cmd)) and not (
            parent.get("name") == "node.exe" and _GEMINI_CMD_RE.search(parent.get("cmd") or ""))
    return False


def _outside_agents(path, kind):
    """Los agentes de ese tipo que corren en esa carpeta fuera de Herdr (una pestaña de Windows Terminal, por ejemplo)."""
    procs = _procs()
    by_pid = {p["pid"]: p for p in procs}
    want = _norm_path(path)
    return [p for p in procs if _is_agent_proc(p, kind, by_pid) and p["cwd"] and _norm_path(p["cwd"]) == want
            and not _under_herdr(p, by_pid)]


def agents_outside_herdr(path, kind):
    """Cuántos agentes de ese tipo corren en esa carpeta fuera de Herdr."""
    return len(_outside_agents(path, kind))


def claudes_outside_herdr(path):
    """Cuántos Claude Code corren en esa carpeta fuera de Herdr."""
    return agents_outside_herdr(path, "claude")


def newest_session(path):
    """Id de la conversación más nueva guardada para esa carpeta: la que `claude --continue` elige."""
    d = _claude_project_dirs().get(claude_project_key(path).lower())
    if not d:
        return None
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
        return os.path.basename(max(files, key=os.path.getmtime))[:-6].lower() if files else None
    except (OSError, ValueError):
        return None


def sids_outside_herdr(path, kind="claude"):
    """Conversaciones que un agente de FUERA de Herdr tiene abiertas en esa carpeta, en minúsculas: el id de
    `--resume X` / `-r X` (Gemini también `--session-id X`) de su línea de comandos; si alguno arrancó con --continue,
    `--resume latest` o sin id no se sabe cuál agarró, así que cuenta la más nueva de la carpeta (es la que esas formas
    eligen). Un --resume sobre una de éstas pondría dos agentes en el mismo archivo."""
    out = set()
    for p in _outside_agents(path, kind):
        m = re.search(r"(?:--resume|-r|--session-id)(?:=|\s+)\"?([0-9A-Za-z-]{8,})", p.get("cmd") or "")
        if m and m.group(1).lower() != "latest":
            out.add(m.group(1).lower())
        else:
            sid = _gemini_newest_sid(path) if kind == "gemini" else newest_session(path)
            if sid:
                out.add(sid)
    return out


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

def _gemini_continue_args(a, path, say, used, others_live):
    """Lo mismo que para Claude, con las sesiones de Gemini (~/.gemini/tmp/<id>/chats): la última que tuvo pedidos
    dentro de Herdr en esa carpeta (`--resume <uuid>`), que no esté viva en otro panel ni en otra terminal; sin una,
    `--resume latest` (la más nueva de la carpeta) sólo si ningún otro Gemini corre ahí. Sin sesiones guardadas, nada:
    `--resume latest` sin sesiones termina con error."""
    if not has_gemini_conversation(path):
        return []
    outside = sids_outside_herdr(path, "gemini")
    sid = last_herdr_session(path, exclude=set(used) | outside, kind="gemini")
    if sid:
        used.add(sid)
        return ["--resume", sid]
    if outside:
        say(f"  {a['name']}: la última sesión de Herdr acá está abierta en otra terminal; no la retomo.")
    if others_live:
        say(f"  {a['name']}: otro Gemini del proyecto ya está en esa carpeta; arranca una sesión nueva.")
    elif outside:
        say(f"  {a['name']}: hay un Gemini corriendo en esa carpeta fuera de Herdr; arranca una sesión nueva para no pisarla.")
    else:
        return ["--resume", "latest"]
    return []


def _continue_args(a, path, say, used, others_live):
    """Qué conversación retoma un agente con `continue`. Claude: la última que tuvo pedidos dentro de Herdr en esa
    carpeta (--resume), que no esté viva en otro panel. Sin una, --continue sólo si ningún otro Claude corre en la
    carpeta: --continue agarra la conversación MÁS NUEVA, que puede ser la que está abierta en otra terminal.
    Gemini: ver _gemini_continue_args. Otros tipos (codex…): sin reanudar."""
    if a["kind"] == "gemini":
        return _gemini_continue_args(a, path, say, used, others_live)
    if a["kind"] != "claude":
        return []
    outside = sids_outside_herdr(path)  # abiertas en una terminal ajena a Herdr: no se retoman
    sid = last_herdr_session(path, exclude=set(used) | outside)
    if sid:
        used.add(sid)
        return ["--resume", sid]
    if outside:
        say(f"  {a['name']}: la última conversación de Herdr acá está abierta en otra terminal; no la retomo.")
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
    """Arranca un agente que Herdr conoce (claude, gemini, codex…). Devuelve True si quedó listo.
    `others_live`: ya corre otro agente del mismo tipo en la carpeta del proyecto (no se retoma su conversación)."""
    args = list(a["args"])
    if a["continue"] and not any(x in args for x in ("--continue", "--resume", "-r", "-c")):
        args += _continue_args(a, path, say, used if used is not None else set(), others_live)
    extra = f" {' '.join(args)}" if args else ""
    say(f"  {a['name']}: arrancando {a['kind']}{extra} en {pane}…")
    try:
        cli = ["agent", "start", a["name"], "--kind", a["kind"], "--pane", pane, "--timeout", str(timeout_ms)]
        if args:
            cli += ["--", *args]
        api(*cli, timeout=timeout_ms / 1000 + 10)
        pane_title(pane, a["name"])
        if a["kind"] == "gemini" and "--skip-trust" not in args and gemini_folder_trusted(path) is False:
            # Gemini pregunta por la carpeta la primera vez y se reinicia al responder: Herdr lo da por listo igual.
            say(f"  {a['name']}: Gemini espera que confíes la carpeta: elegí 1 (Trust folder) en el panel; no se repite.")
        say(f"  {a['name']}: listo.")
        return True
    except AgentNavError as e:
        if "agent_not_ready" in str(e):
            say(f"  {a['name']}: espera un diálogo de {a['kind']} (confianza de carpeta, login); respondelo en el panel.")
        else:
            say(f"  {a['name']}: no arrancó ({e})")
        return False


def pane_title(pane, title):
    """Etiqueta del borde superior del panel (metadata de Herdr). El hook la completa con la tarea en cada evento;
    acá va el nombre solo para que el panel no quede sin nombre hasta el primer pedido, y "" la borra (un panel que
    pasa a ser shell no hereda la etiqueta del agente que tuvo). Nunca falla por esto."""
    try:
        what = ["--title", title] if title else ["--clear-title"]  # Herdr no acepta la forma --title=texto
        run("pane", "report-metadata", pane, "--source", "agentnav", *what, timeout=10)
    except Exception:
        pass


# Lo mismo que filtra el hook (Pane-Label): un pedido con pinta de clave no va al borde del panel.
SECRET_RE = re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]|sk-[A-Za-z0-9_-]{8}|xox[abp]-|AKIA[0-9A-Z]{8}|bearer\s+\S{8}|eyJ[A-Za-z0-9_-]{10,}"
                       r"|[A-Fa-f0-9]{32,}|-----BEGIN|authorization\s*:|(password|passwd|contrase.a|token|secret|api[_-]?key)\s*[=:])")


def agent_label(a, hint=""):
    """La etiqueta del panel con la misma regla que Pane-Label del hook: el nombre que Herdr le dio al agente (o su
    tipo), y la tarea = título que Claude Code puso a la conversación; mientras siga en "Claude Code", `hint` (el
    último pedido). Con cualquier otro agente el título no se usa nunca: Gemini CLI pone ahí sólo su estado
    ("◇ Ready (carpeta)", "✦ Working…"), así que va el último pedido o nada. Una línea, 60 caracteres, sin comillas
    dobles ni nada con pinta de clave."""
    name = str(a.get("name") or a.get("agent") or "agente")
    if a.get("agent") in (None, "", "claude"):
        task = str(a.get("terminal_title_stripped") or "").strip()
        if not task or task == "Claude Code":
            task = str(hint or "")
    else:
        task = str(hint or "")
    task = re.sub(r"[\x00-\x1f\x7f\u2028\u2029]+", " ", task).replace('"', "'").strip()
    if SECRET_RE.search(task):
        task = ""
    if len(task) > 60:
        task = task[:59].rstrip() + "…"
    return f"{name} · {task}" if task else name


def _working_hint(sid):
    """El último pedido de esa sesión según la marca working\\<sid> del hook, si está trabajando; si no, ""."""
    if not sid:
        return ""
    path = os.path.join(STATE_DIR, "working", re.sub(r"[^A-Za-z0-9_-]", "_", str(sid)))
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def label_agents(say=print):
    """Pone la etiqueta a todos los agentes vivos de una vez: lo que el hook hace evento a evento, para los paneles
    que están idle sin eventos (recién instalado el hook, servidor reiniciado). Un `agent list` y un reporte por agente."""
    try:
        agents = field(api("agent", "list", timeout=10), "agents")
    except AgentNavError as e:
        say(f"sin etiquetas: {e}")
        return 1
    n = 0
    for a in agents if isinstance(agents, list) else []:
        pane = a.get("pane_id") if isinstance(a, dict) else None
        if not pane:
            continue
        sid = ((a.get("agent_session") or {}).get("value") or "") if isinstance(a.get("agent_session"), dict) else ""
        pane_title(pane, agent_label(a, _working_hint(sid)))
        n += 1
    say(f"{n} etiqueta(s) de panel puesta(s).")
    return 0


# Prompt de pwsh / Windows PowerShell, o de un shell tipo bash, con espacio o salto de línea finales. Un prompt
# decorado (oh-my-posh, starship) se declara en settings.json → "prompt_regex" (sintaxis de regex de Rust/Herdr).
PROMPT_RE = r"(PS [^\n]*>|[A-Za-z]:\\[^\n]*>|\$) ?\s*$"  # pwsh, cmd (C:\x>) y bash


def prompt_regex():
    try:
        return str(load_settings().get("prompt_regex") or "") or PROMPT_RE
    except AgentNavError:
        return PROMPT_RE


def default_shell():
    """terminal.default_shell del config.toml de Herdr ("" si no está o no se puede leer)."""
    try:
        with open(HERDR_CFG, encoding="utf-8") as f:
            text = f.read()
        try:
            import tomllib
            return str((tomllib.loads(text).get("terminal") or {}).get("default_shell") or "")
        except Exception:
            m = re.search(r'^\s*default_shell\s*=\s*"([^"]*)"', text, re.M)
            return m.group(1) if m else ""
    except OSError:
        return ""


def _pane_shell(pane):
    """Ejecutable que atiende el panel: el proceso en primer plano según `pane process-info`; si no se sabe,
    el default_shell del config; si tampoco, pwsh."""
    try:
        info = field(api("pane", "process-info", "--pane", pane, timeout=10), "process_info")
        fg = info.get("foreground_processes") or []
        if fg and isinstance(fg[-1], dict):
            name = str(fg[-1].get("name") or fg[-1].get("argv0") or "")
            if name:
                return name
    except AgentNavError:
        pass
    return default_shell() or "pwsh"


def _cd_command(shell, path):
    """La orden de cambiar de carpeta en el shell del panel. `Set-Location` sólo existe en PowerShell: en cmd o bash
    adopt fallaba siempre. Comilla simple duplicada en pwsh y '\\'' en bash; en Windows una ruta no puede llevar comillas dobles."""
    s = os.path.basename(str(shell or "").strip().strip('"')).lower()
    if s.endswith(".exe"):
        s = s[:-4]
    if s in ("pwsh", "powershell"):
        return "Set-Location -LiteralPath '" + path.replace("'", "''") + "'"
    if s == "cmd":
        return 'cd /d "' + path + '"'
    return "cd '" + path.replace("'", "'\\''") + "'"


def wait_prompt(pane, timeout_ms):
    """Espera a que el panel muestre un prompt de shell. Devuelve False si venció el plazo (y se sigue igual)."""
    code, _, _ = run("pane", "wait-output", pane, "--regex", prompt_regex(), "--source", "visible",
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
    pane_title(pane, "")  # si el panel tuvo un agente, su etiqueta no se queda
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
        return field(r, "pane", "pane_id")
    t = api("tab", "create", "--workspace", wid, "--cwd", path, "--label", label, "--no-focus")
    return field(t, "root_pane", "pane_id")


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


def _place_agents(p, wid, agents, taken, first_pane, first_tab, start_timeout_ms, say, live_sids=(), live_kinds=()):
    """Crea paneles y arranca los agentes de la lista. Devuelve True si todos quedaron bien.
    `live_kinds`: tipos de agente que ya corren en el espacio (el nuevo del mismo tipo no retoma su conversación)."""
    all_ok, prev_pane = True, None
    live_kinds = set(live_kinds)
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
                all_ok &= _start_herdr_agent(a, p["path"], pane, start_timeout_ms, say, used, a["kind"] in live_kinds)
                live_kinds.add(a["kind"])  # el siguiente del mismo tipo no debe retomar la conversación de éste
            prev_pane = pane
        except AgentNavError as e:
            say(f"  {a['name']}: {e}")
            all_ok = False
    return all_ok


ADOPT_PAUSE = os.path.join(STATE_DIR, "adopt-pause")


_pause_depth = 0


def adopt_paused(on):
    """Mientras AgentNav arma un espacio (workspace create + agentes en sus paneles) el plugin no debe adoptar nada:
    las pestañas que nacen ahí son suyas aunque todavía tengan la etiqueta numérica de Herdr.
    Reentrante: `open` puede reponer otros proyectos (restore_projects) antes de abrir el suyo."""
    global _pause_depth
    _pause_depth = max(0, _pause_depth + (1 if on else -1))
    try:
        if on:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(ADOPT_PAUSE, "w") as f:
                f.write(str(os.getpid()))
        elif _pause_depth == 0 and os.path.isfile(ADOPT_PAUSE):
            os.remove(ADOPT_PAUSE)
    except OSError:
        pass


def adopt_is_paused(max_age=180):
    """True si hay una pausa vigente (un archivo viejo es de un proceso que murió sin limpiar: se ignora)."""
    try:
        return time.time() - os.path.getmtime(ADOPT_PAUSE) < max_age
    except OSError:
        return False


def open_project(p, say=print, start_timeout_ms=90000):
    """Abre el proyecto como espacio de Herdr, o lo enfoca y repone los agentes que falten.
    Devuelve (modo, todos_listos) con modo 'created' o 'focused'."""
    adopt_paused(True)
    try:
        return _open_project(p, say, start_timeout_ms)
    finally:
        adopt_paused(False)


def _open_project(p, say, start_timeout_ms):
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
        # Un agente que Herdr reanudó con otro nombre (o sin nombre) en la carpeta del proyecto también cuenta.
        named = {agent_name(a["name"], set()) for a in wanted}
        spare = [x for x in live if x.get("name") not in named and x.get("cwd") and _norm_path(x["cwd"]) == _norm_path(p["path"])]
        still = []
        for a in missing:
            hit = next((x for x in spare if x.get("agent") == a["kind"]), None)
            if hit:
                spare.remove(hit)
            else:
                still.append(a)
        missing = still
        if not missing:
            say(f"{p['name']}: ya estaba abierto, enfocado.")
            return "focused", True
        say(f"{p['name']}: abierto; faltan {', '.join(a['name'] for a in missing)}.")
        missing = [dict(a, split=None) for a in missing]  # cada repuesto en su pestaña
        spare_pane, spare_tab = (None, None) if live else _idle_shell_pane(snap, wid)  # el panel vacío de una restauración
        kinds = {a.get("agent") for a in live if a.get("agent")}
        return "focused", _place_agents(p, wid, missing, taken, spare_pane, spare_tab, start_timeout_ms, say, live_sids, kinds)

    if not os.path.isdir(p["path"]):
        raise AgentNavError(f"{p['name']}: la carpeta no existe: {p['path']}")
    say(f"{p['name']}: abriendo espacio en {p['path']}…")
    r = api("workspace", "create", "--cwd", p["path"], "--label", p["name"])
    wid = field(r, "workspace", "workspace_id")
    ok = _place_agents(p, wid, wanted, taken, field(r, "root_pane", "pane_id"), field(r, "tab", "tab_id"), start_timeout_ms, say, live_sids)
    return "created", ok


def _wait_agents_settled(min_wait=4.0, quiet=2.0, cap=25.0):
    """Con resume_agents_on_restore, Herdr relanza `claude --resume` en cada panel restaurado unos segundos después
    de recrear los espacios. Reponer antes de eso duplicaría cada Claude. Espera un mínimo y después a que la lista
    de agentes (y sus launch_pending) no cambie durante `quiet` segundos."""
    t0 = time.monotonic()
    last, stable_since = None, None
    while time.monotonic() - t0 < cap:
        try:
            snap = snapshot()
        except AgentNavError:
            break
        state = tuple(sorted((a.get("pane_id") or "", bool(a.get("launch_pending")), bool(a.get("interactive_ready")))
                             for a in snap["agents"]))
        pending = any(a.get("launch_pending") for a in snap["agents"])
        if state != last:
            last, stable_since = state, time.monotonic()
        if (time.monotonic() - t0 >= min_wait and not pending and stable_since is not None
                and time.monotonic() - stable_since >= quiet):
            return
        time.sleep(0.5)


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
        say(f"espacios restaurados por Herdr: {', '.join(p['name'] for p in found)}; espero a que termine de reanudar…")
        _wait_agents_settled()
        say("repongo los agentes que falten.")
    for p in found:
        try:
            open_project(p, say)
        except AgentNavError as e:
            say(f"{p['name']}: {e}")
    return found


def close_project(p, say=print, grace_ms=5000):
    """Cierra el espacio del proyecto. A los agentes que están en el prompt les manda su orden de salida primero
    (/exit a Claude, /quit a Gemini: dispara SessionEnd). A uno bloqueado o todavía arrancando no se le manda nada:
    Enter ahí concedería el permiso o el diálogo de confianza."""
    snap = snapshot()
    ws = find_ws(snap, p["name"])
    if not ws:
        say(f"{p['name']}: no estaba abierto.")
        return False
    wid = ws["workspace_id"]
    claudes = [a for a in snap["agents"] if a.get("workspace_id") == wid and a.get("agent") in EXIT_COMMAND and a.get("pane_id")]
    polite = [a for a in claudes if a.get("interactive_ready") and not a.get("launch_pending")
              and a.get("agent_status") in ("idle", "done")]
    if polite:  # releer justo antes de escribir: entre el snapshot y el /exit pudo cambiar de estado
        fresh = {a.get("pane_id"): a for a in snapshot()["agents"]}
        polite = [a for a in polite if (fresh.get(a["pane_id"]) or {}).get("agent_status") in ("idle", "done")
                  and not (fresh.get(a["pane_id"]) or {}).get("launch_pending")]
    for a in polite:
        try:
            api("pane", "send-text", a["pane_id"], EXIT_COMMAND[a["agent"]])
            api("pane", "send-keys", a["pane_id"], "enter")
        except AgentNavError:
            pass
    if polite:
        say(f"{p['name']}: saliendo de {len(polite)} agente(s)…")
        for a in polite:  # una espera bloqueante por panel en vez de sondear el snapshot
            wait_prompt(a["pane_id"], grace_ms)
    skipped = len(claudes) - len(polite)
    if skipped:
        say(f"{p['name']}: {skipped} agente(s) ocupado(s) o bloqueado(s) se cierran sin despedirse.")
    api("workspace", "close", wid)
    say(f"{p['name']}: espacio {wid} cerrado.")
    return True


def focus_herdr_window():
    """Trae al frente la ventana de Windows Terminal que aloja un cliente de Herdr. True si pudo."""
    import ctypes
    from ctypes import wintypes
    _, clients = herdr_processes()
    # El cliente puede estar dentro de una pwsh (herdr tipeado en una pestaña): la ventana es de un ancestro más arriba.
    by_pid = {p["pid"]: p for p in _procs()}
    hosts = set()
    for c in clients:
        seen, p = set(), by_pid.get(c["ppid"])
        while p and p["pid"] not in seen:
            seen.add(p["pid"])
            hosts.add(p["pid"])
            p = by_pid.get(p["ppid"])
        hosts.add(c["ppid"])
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
    """Herdr como aplicación (acceso directo del escritorio): servidor arriba, y la ventana al frente o una pestaña nueva.
    Mientras tanto consulta origin (el `update --check`) y, si hay commits nuevos de AgentNav, lo avisa dentro de Herdr."""
    check = start_update_check()  # git fetch en paralelo con el arranque: no demora la ventana
    if ensure_server(say):
        restore_projects(load_projects(), say)
    label_agents(say)  # los paneles idle no tienen eventos: la etiqueta se repone acá
    if inside_herdr():
        say("ya estás dentro de Herdr.")
    elif focus_herdr_window():
        say("ventana de Herdr al frente.")
    else:
        attach(say, force=True)
    notify_update_available(check, say)
    return 0


def in_thread(fn, name="agentnav-bg"):
    """Corre fn() en un hilo daemon. Devuelve el hilo con .result = lo que devolvió fn, o la AgentNavError que levantó."""
    import threading

    def work():
        try:
            t.result = fn()
        except AgentNavError as e:
            t.result = e

    t = threading.Thread(target=work, name=name, daemon=True)
    t.result = None
    t.start()
    return t


def start_update_check(fetch_timeout=15):
    """Lanza en un hilo el `update --check` (repo_status con fetch). Devuelve el hilo con .result = estado | AgentNavError."""
    return in_thread(lambda: repo_status(fetch_timeout=fetch_timeout), "agentnav-update-check")


def update_notice(st):
    """(título, cuerpo) del aviso de AgentNav desactualizado, o None si no hay nada que avisar: al día, sin red (fetch_error),
    sin upstream, o el estado no es un dict (AgentNavError: no es un clon, no hay git...). El acceso directo corre sin
    consola, así que el aviso tiene que valer por sí solo."""
    if not isinstance(st, dict) or st.get("fetch_error") or not st.get("upstream") or not st.get("behind"):
        return None
    n = st["behind"]
    title = f"AgentNav: {n} commit{'s' if n != 1 else ''} nuevo{'s' if n != 1 else ''} en {st['upstream']}"
    body = "agentnav update los instala (git pull y re-copia hooks, arranque y config de Herdr)"
    if st.get("dirty"):
        body = f"hay cambios locales sin commitear en {HOME}; commiteá o descartá y después agentnav update"
    elif st.get("ahead"):
        body = f"{HOME} tiene {st['ahead']} commit(s) sin pushear; git push (o rebase a mano) y después agentnav update"
    return title, body


def notify_update_available(check, say=print, wait=20.0):
    """Espera al hilo de start_update_check (como mucho `wait` s: la ventana ya está arriba) y, si hay commits nuevos,
    lo dice y muestra una notificación de Herdr. Sin red o sin clon no molesta: queda para `doctor`."""
    check.join(timeout=wait)
    st = check.result
    if isinstance(st, AgentNavError):
        say(f"no pude comparar AgentNav con origin: {st}")
        return False
    if st is None:
        say("la consulta a origin no terminó a tiempo; agentnav update --check la repite")
        return False
    if st.get("fetch_error"):
        say(f"no pude consultar origin: {st['fetch_error']}")
        return False
    notice = update_notice(st)
    if not notice:
        say(f"AgentNav al día con {st.get('upstream') or 'origin'} ({st.get('sha')})")
        return False
    title, body = notice
    say(f"{title}: {body}")
    try:
        run("notification", "show", title, "--body", body, "--sound", "none", timeout=10)
    except AgentNavError as e:
        say(f"no pude mostrar la notificación en Herdr: {e}")
    return True


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
        kind = src.get("agent") or DEFAULT_KIND
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
        except Exception as e:  # también un KeyError o similar: desde la tecla o el gancho moriría en silencio
            msg = str(e) if isinstance(e, AgentNavError) else f"{type(e).__name__}: {e}"
            try:
                run("notification", "show", "AgentNav", "--body", msg[:200], "--sound", "none", timeout=5)
            except AgentNavError:
                pass
            raise
    return wrapped


@_notify_error
def cmd_tab(mode="", say=print, start_timeout_ms=90000):
    """agentnav tab: pestaña nueva en el espacio actual, con un shell en la carpeta del panel de origen y sin agente
    (hasta el 4/11 abría otro Claude ahí; el Claude lo lanza uno a mano cuando lo quiere).
    `tab agent`: lo de antes, además arranca el mismo agente que el panel de origen; un Claude nuevo arranca una
    conversación nueva (nunca --continue: la viva ya está en la otra pestaña).
    `tab shell`: la pestaña pelada de siempre (shell en C:\\), con etiqueta "shell" para que el plugin no la adopte."""
    snap = snapshot()
    wid, ws, pane, project = _tab_source(snap, load_projects())
    if mode == "shell":
        path = new_project_base()
        say(f"{ws.get('label') or wid}: pestaña de shell en {path}")
        api("tab", "create", "--workspace", wid, "--cwd", path, "--label", "shell", "--focus")
        return 0
    path = _tab_path(pane.get("cwd") or "", project)
    a = _tab_agent(snap, wid, pane, project) if mode in ("agent", "agente") else None
    taken = {x.get("name") for x in snap["agents"] if x.get("name")}
    label = agent_name(a["name"], taken) if a else _tab_label(path)
    say(f"{ws.get('label') or wid}: pestaña {label} en {path}")
    t = api("tab", "create", "--workspace", wid, "--cwd", path, "--label", label, "--focus")
    if a is None:
        return 0
    a = dict(a, name=label)
    return 0 if _start_herdr_agent(a, path, field(t, "root_pane", "pane_id"), start_timeout_ms, say, set(), True) else 1


def _tab_label(path):
    """Etiqueta de una pestaña de shell: el nombre de su carpeta. Nunca numérica, que es la marca de las pestañas
    peladas de Herdr que el plugin adopta."""
    base = os.path.basename(path.rstrip("\\/")) or "shell"
    return "shell" if re.fullmatch(r"\d+", base) else base


def _tab_path(cwd, project):
    """Carpeta de la pestaña nueva. En un espacio de proyecto manda la carpeta del proyecto: la del panel de origen
    sólo si está adentro (una subcarpeta donde venías trabajando). Si el panel enfocado era un shell suelto en C:\\,
    no hay que heredarle eso. Sin proyecto, la del panel; sin nada, donde nacen los proyectos."""
    if project and os.path.isdir(project["path"]):
        root = _norm_path(project["path"])
        if cwd and os.path.isdir(cwd) and (_norm_path(cwd) + os.sep).startswith(root + os.sep):
            return cwd
        return project["path"]
    return cwd if cwd and os.path.isdir(cwd) else new_project_base()


def cmd_adopt(argv, say=print):
    """Ganchos `tab.created` y `pane.created` del plugin (C:\\AgentNav\\plugin). Herdr los llama con HERDR_WORKSPACE_ID,
    HERDR_TAB_ID, HERDR_PANE_ID, HERDR_PLUGIN_EVENT y HERDR_PLUGIN_CONTEXT_JSON. El "+" de la barra y el split entran
    por la misma API que los scripts (invocation_source = api en todos los casos), así que lo que distingue algo pelado
    de Herdr es: en una pestaña, la etiqueta numérica ("2", "3"…; las de AgentNav llevan nombre); en un panel, que nazca
    en el new_cwd fijo de la config (C:\\) y no en una carpeta pedida con --cwd. Mientras `open` arma un espacio hay una
    pausa para no pisar el panel donde está arrancando el agente.
    Sólo lleva el panel a la carpeta y le pone nombre a la pestaña: no arranca ningún agente (hasta el 4/11 también
    abría otro Claude ahí). El gancho vuelve enseguida: el trabajo (esperar el prompt, cd) sigue en un hijo suelto.
    La carpeta es la del panel desde donde se abrió. El evento no lo dice (tab.created y pane.created sólo traen lo
    nuevo), así que el plugin anota cada cambio de foco en focus.log y adopt toma el último panel enfocado distinto
    del nuevo; sin rastro, en un split vale la geometría (el panel que quedó pegado al nuevo) y, si no, el agente más
    reciente o cualquier panel del mismo lugar."""
    ctx, ev = {}, {}
    try:
        ctx = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
        ev = (json.loads(os.environ.get("HERDR_PLUGIN_EVENT_JSON") or "{}").get("data") or {})
    except ValueError:
        pass
    event = os.environ.get("HERDR_PLUGIN_EVENT") or ""
    wid, tid, pid = (os.environ.get(k) for k in ("HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID"))
    if not (wid and tid and pid):
        say("adopt: faltan HERDR_WORKSPACE_ID / HERDR_TAB_ID / HERDR_PANE_ID; no hago nada.")
        return 0
    if event == "pane.created":
        born = (ev.get("pane") or {}).get("cwd") or ""
        base = new_project_base()
        if born and os.path.isdir(born) and _norm_path(born) != _norm_path(base):
            say(f"adopt: {pid} nació con carpeta propia ({born}); lo dejo como está.")
            return 0
    else:
        label = str(ctx.get("tab_label") or "")
        if "tab_label" not in ctx:  # por si una versión de Herdr deja de mandarlo: preguntar antes que no hacer nada
            try:
                label = str(field(api("tab", "get", tid), "tab", "label") or "")
            except AgentNavError:
                pass
        if not re.fullmatch(r"\d+", label):
            say(f"adopt: {tid} ya tiene nombre ({label!r}); la dejo como está.")
            return 0
    if adopt_is_paused():
        say(f"adopt: {pid} nació mientras AgentNav arma un espacio; lo dejo como está.")
        return 0
    if "--run" not in argv:
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "adopt", "--run"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
        say(f"adopt: {pid} ({event}) se arma en segundo plano.")
        return 0
    return _adopt_run(event, wid, tid, pid, say)


@_notify_error
def _adopt_run(event, wid, tid, pid, say):
    snap = snapshot()
    ws = next((w for w in snap["workspaces"] if w.get("workspace_id") == wid), None)
    panes = snap.get("panes", [])
    mine = next((x for x in panes if x.get("pane_id") == pid), None)
    if not ws or not mine:
        return 0  # lo cerraron antes de que llegáramos
    if mine.get("agent") or any(x.get("pane_id") == pid for x in snap["agents"]):
        return 0  # alguien ya arrancó algo ahí
    in_tab = [x for x in panes if x.get("tab_id") == tid and x.get("pane_id") != pid]
    if event == "pane.created" and not in_tab:
        return 0  # el panel raíz de una pestaña nueva: de ése se ocupa el gancho tab.created
    # De dónde copiar la carpeta: en un split, los hermanos de la misma pestaña; en una pestaña nueva, el resto
    # del espacio. El panel de origen sale del rastro de foco; si no, de la geometría del split; si no, el agente
    # más reciente entre ellos o cualquier panel.
    pool = in_tab if event == "pane.created" else [x for x in panes if x.get("workspace_id") == wid and x.get("pane_id") != pid]
    layout = next((l for l in snap.get("layouts", []) if l.get("tab_id") == tid), None) if event == "pane.created" else None
    origin = _adopt_origin(pool, pid, read_focus_trail(wid), layout)
    if origin is None:
        ids = {x.get("pane_id") for x in pool}
        live = [x for x in snap["agents"] if x.get("pane_id") in ids]
        origin = max(live, key=lambda x: x.get("state_change_seq") or 0) if live else next((x for x in pool if x.get("cwd")), None)
    hint = (origin or {}).get("cwd") or ""
    project = next((p for p in load_projects() if p["name"].lower() == ws_label(ws)), None)
    path = _tab_path(hint, project)
    if not wait_prompt(pid, 15000):
        say(f"{pid}: no vi el prompt del shell en 15 s (¿prompt decorado? settings.json → prompt_regex); sigo igual.")
    if _norm_path(mine.get("cwd") or "") != _norm_path(path):
        say(f"{ws.get('label') or wid}: {pid} → {path}")
        code, out, err = run("pane", "run", pid, _cd_command(_pane_shell(pid), path), timeout=30)
        if code != 0:
            raise AgentNavError(f"{pid}: no pude cambiar de carpeta ({(err or out)[:160]})")
        wait_prompt(pid, 5000)
    # El nombre recién después del cd: si el cd falla, no queda un panel con nombre de carpeta y carpeta equivocada.
    label = _tab_label(path)
    try:
        if event == "pane.created":
            api("pane", "rename", pid, label)  # nombre en el borde del panel, como la pestaña
        else:
            api("tab", "rename", tid, label)
    except AgentNavError:
        pass
    return 0


def read_focus_trail(wid):
    """Paneles del espacio que tomaron el foco, del más reciente al más viejo (lo anota plugin\\focus.py)."""
    try:
        with open(FOCUS_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        parts = line.split()
        if len(parts) == 2 and parts[0] == wid and parts[1] not in out:
            out.append(parts[1])
    return out


def _adopt_origin(pool, pid, trail, layout=None):
    """El panel desde donde se abrió el nuevo (pid), entre los candidatos de `pool`: el último enfocado según el
    rastro que no sea el nuevo; si no hay rastro útil y es un split (`layout` de esa pestaña), el panel que quedó
    pegado al nuevo: comparte borde y el mismo alto (split a la derecha) o el mismo ancho (split abajo).
    None si nada lo decide."""
    by_id = {x.get("pane_id"): x for x in pool}
    for cand in trail:
        if cand != pid and cand in by_id:
            return by_id[cand]
    rects = {p.get("pane_id"): p.get("rect") or {} for p in (layout or {}).get("panes", [])}
    me = rects.get(pid)
    if not me:
        return None
    for cand, r in rects.items():
        if cand == pid or cand not in by_id or not r:
            continue
        right_of = r.get("x", -1) + r.get("width", 0) == me.get("x") and r.get("y") == me.get("y") and r.get("height") == me.get("height")
        below = r.get("y", -1) + r.get("height", 0) == me.get("y") and r.get("x") == me.get("x") and r.get("width") == me.get("width")
        if right_of or below:
            return by_id[cand]
    return None


def cmd_recent():
    for r in recent_projects(load_projects(), limit=20):
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['when']))}  {r.get('kind', 'claude'):<7} {r['path']}")
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


# ---------------------------------------------------------------- herdr propio (fork con los temas de AgentNav)

def fork_repo():
    """owner/herdr del fork en GitHub (settings.json → herdr_fork.repo); vacío si no está configurado."""
    try:
        return str((load_settings().get("herdr_fork") or {}).get("repo") or "").strip().strip("/")
    except AgentNavError:
        return ""


def herdr_release_dir():
    """Carpeta real a la que apunta packages/standalone/current (ahí viven herdr.exe y conpty)."""
    return os.path.realpath(os.path.join(USERPROFILE, ".herdr", "packages", "standalone", "current"))


def file_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def installed_herdr_version():
    code, out, err = run("--version", timeout=15)
    m = re.search(r"herdr\s+(\d+\.\d+\.\d+\S*)", out + err)
    return m.group(1) if m else ""


def _http_json(url, timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "AgentNav"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _http_text(url, timeout=15, limit=1 << 16):
    """Cuerpo de una URL como texto (hasta `limit` bytes), para archivos chicos como el .sha256."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "AgentNav"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", "replace")


def _http_download(url, dest, timeout=120):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "AgentNav"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def fork_latest_release(repo):
    """El release agentnav-vX.Y.Z más nuevo del fork, o None. API pública de GitHub, sin token."""
    try:
        data = _http_json(f"https://api.github.com/repos/{repo}/releases?per_page=20")
    except Exception as e:
        raise AgentNavError(f"no pude consultar los releases de {repo}: {e}")
    rels = [r for r in data if str(r.get("tag_name") or "").startswith("agentnav-v") and not r.get("draft")]
    if not rels:
        return None
    r = max(rels, key=lambda x: _ver_tuple(x["tag_name"]))
    return {"tag": r["tag_name"], "version": r["tag_name"][len("agentnav-v"):], "url": r.get("html_url") or "",
            "assets": {a["name"]: a["browser_download_url"] for a in r.get("assets") or []}}


def parse_sha256_file(text):
    """Primer token de un .sha256 ("hash  nombre" o el hash solo), en minúsculas. AgentNavError si no son 64 hex."""
    tok = (str(text or "").lstrip("\ufeff").split() or [""])[0].lower()  # PowerShell 5 escribe con BOM
    if not re.fullmatch(r"[0-9a-f]{64}", tok):
        raise AgentNavError(f"sha256 inválido: {tok[:24]!r}")
    return tok


def fork_release_sha(rel):
    """SHA-256 del herdr.exe que publica el release (asset herdr.exe.sha256), ya validado."""
    url = (rel.get("assets") or {}).get("herdr.exe.sha256")
    if not url:
        raise AgentNavError(f"al release {rel['tag']} le falta herdr.exe.sha256 (¿el workflow sigue corriendo?)")
    try:
        text = _http_text(url, timeout=20)
    except Exception as e:
        raise AgentNavError(f"no pude bajar el sha256 de {rel['tag']}: {e}")
    return parse_sha256_file(text)


def fork_sync_state(installed_version, installed_sha, release_version, release_sha):
    """Qué hay entre el exe instalado y el último build del fork. Manda el SHA-256, no el tag: el workflow puede republicar
    el mismo agentnav-vX.Y.Z con otro parche de temas.
      "al_dia"         mismo exe que el release
      "version_nueva"  el fork va por una versión más nueva que la instalada
      "rebuild"        misma versión, otro exe: republicaron el tag
      "fork_atrasado"  lo instalado es más nuevo que el último build del fork"""
    have, want = str(installed_sha or "").lower(), str(release_sha or "").lower()
    if have and have == want:
        return "al_dia"
    iv, rv = _ver_tuple(installed_version), _ver_tuple(release_version)
    if rv > iv:
        return "version_nueva"
    if rv < iv:
        return "fork_atrasado"
    return "rebuild"


HERDR_UPDATE_TASK = "AgentNav Herdr update"


def herdr_update_task_registered(name=HERDR_UPDATE_TASK):
    """True/False según exista la tarea programada que deja herdr-fork/install.ps1; None si schtasks no contestó."""
    try:
        cp = subprocess.run(["schtasks", "/query", "/tn", name], capture_output=True, timeout=10,
                            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.returncode == 0


def herdr_build_marker_path():
    return os.path.join(herdr_release_dir(), "agentnav-build.json")


def herdr_is_ours(sha=None):
    """(True si el herdr.exe instalado es el build del fork, False si es el oficial, None si no se sabe; detalle).
    `sha`: SHA-256 del exe si ya se calculó, para no hashearlo dos veces."""
    exe = os.path.join(herdr_release_dir(), "herdr.exe")
    marker = _read_json_file(herdr_build_marker_path(), "agentnav-build.json")
    if not os.path.isfile(exe):
        return None, "no encuentro herdr.exe"
    if not marker:
        return False, "sin marcador: herdr.exe oficial"
    try:
        same = (sha or file_sha256(exe)) == str(marker.get("sha256") or "").lower()
    except OSError as e:
        return None, str(e)
    return (True, f"build del fork {marker.get('tag')}") if same else (False, f"herdr.exe no coincide con el marcador {marker.get('tag')}: lo pisó herdr update")


def _herdr_pids():
    """PIDs de todos los herdr.exe vivos, con tasklist (sin leer memoria de procesos que están muriendo)."""
    try:
        cp = subprocess.run(["tasklist", "/FI", "IMAGENAME eq herdr.exe", "/FO", "CSV", "/NH"], capture_output=True,
                            text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in cp.stdout.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "herdr.exe" and parts[1].isdigit():
            out.append(int(parts[1]))
    return out


def _stop_all_herdr(say=print, timeout=30.0):
    """Para el servidor y cierra también los clientes. Un cliente vivo retiene herdr.exe y, apenas ve caer al servidor,
    relanza uno nuevo desde su propia carpeta: por eso los dos primeros intentos de hoy no pudieron copiar el exe."""
    if server_running():
        say("parando el servidor de Herdr (los Claude se reanudan al volver)…")
        try:
            run("server", "stop", timeout=30)
        except AgentNavError as e:
            say(f"server stop: {e}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        pids = _herdr_pids()
        if not pids:
            return True
        if time.monotonic() - t0 > 3:  # 3 s para que salgan por las buenas; después, a la fuerza
            for pid in pids:
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                                   creationflags=CREATE_NO_WINDOW)
                    say(f"cerrado herdr.exe {pid}")
                except (OSError, subprocess.TimeoutExpired):
                    pass
        time.sleep(0.5)
    return False


def cmd_herdr_sync(argv, say=print):
    import faulthandler
    faulthandler.enable()
    repo = fork_repo()
    if not repo:
        raise AgentNavError("falta settings.json → herdr_fork.repo (por ejemplo \"pablo/herdr\")")
    rel = fork_latest_release(repo)
    if not rel:
        raise AgentNavError(f"{repo} todavía no publicó ningún release agentnav-v*: lanzá el workflow 'AgentNav build' en GitHub → Actions")
    if "herdr.exe" not in rel["assets"] or "herdr.exe.sha256" not in rel["assets"]:
        raise AgentNavError(f"el release {rel['tag']} no tiene herdr.exe y su .sha256 ({rel['url']})")
    inst = installed_herdr_version()
    say(f"instalado: herdr {inst or '?'} · fork: {rel['tag']}")
    if _ver_tuple(rel["version"]) > _ver_tuple(inst):
        say("el fork va por una versión más nueva que la instalada: primero el instalador oficial (herdr update)…")
        code, out, err = run("update", timeout=900)
        if code != 0:
            raise AgentNavError(f"herdr update falló: {(err or out)[-300:]}")
        inst = installed_herdr_version()
        if _ver_tuple(rel["version"]) != _ver_tuple(inst):
            raise AgentNavError(f"tras herdr update quedó {inst} y el fork tiene {rel['version']}; probá de nuevo más tarde")
    elif _ver_tuple(rel["version"]) < _ver_tuple(inst):
        raise AgentNavError(f"tu Herdr ({inst}) es más nuevo que el último build del fork ({rel['version']}): el workflow corre a diario a las 06:17 UTC, o lanzalo a mano en GitHub → Actions")
    # Misma versión: decide el SHA-256 del exe instalado contra el publicado. El workflow puede republicar el mismo tag
    # con otro parche de temas, así que comparar tags no alcanza; con el mismo exe, sólo --force reinstala.
    exe = os.path.join(herdr_release_dir(), "herdr.exe")
    have = file_sha256(exe) if os.path.isfile(exe) else ""
    want = fork_release_sha(rel)
    state = fork_sync_state(inst, have, rel["version"], want)
    if state == "al_dia" and "--force" not in argv:
        marker_now = _read_json_file(herdr_build_marker_path(), "agentnav-build.json") or {}
        if str(marker_now.get("sha256") or "").lower() != have:  # exe del fork sin marcador (lo puso el instalador oficial)
            with open(herdr_build_marker_path(), "w", encoding="utf-8") as f:
                json.dump({"tag": rel["tag"], "sha256": have, "repo": repo, "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=2)
            say("marcador agentnav-build.json actualizado")
        say(f"ya está instalado {rel['tag']} (sha {have[:8]}); --force para reinstalar")
        return 0
    if state == "rebuild":
        say(f"el fork republicó {rel['tag']} con otro build (sha {want[:8]}, instalado {have[:8] or '-'}): lo instalo")
    # Descarga y verificación
    dl = os.path.join(STATE_DIR, "herdr-download")
    os.makedirs(dl, exist_ok=True)
    new_exe = os.path.join(dl, "herdr.exe")
    say(f"bajando {rel['tag']}…")
    try:
        _http_download(rel["assets"]["herdr.exe"], new_exe, timeout=600)
    except Exception as e:
        raise AgentNavError(f"descarga fallida: {e}")
    got = file_sha256(new_exe)
    if got != want:  # want: el sha256 que publica el release, ya bajado y validado arriba
        raise AgentNavError(f"SHA-256 no coincide (esperado {want[:12]}…, bajado {got[:12]}…); no instalo nada")
    marker = {"tag": rel["tag"], "sha256": got, "repo": repo, "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # Nadie trabajando
    snap = _snapshot_or_none()
    busy = [a.get("name") or a.get("pane_id") for a in (snap or {}).get("agents", []) if a.get("agent_status") in ("working", "blocked")]
    if busy and "--force" not in argv:
        raise AgentNavError(f"hay agentes ocupados ({', '.join(map(str, busy))}); reinstalar reinicia todos los Claude. Cuando terminen, o agentnav herdr-sync --force")
    ours, _ = herdr_is_ours(have)
    official = exe + ".oficial"
    if ours is False and not os.path.isfile(official):
        shutil.copy2(exe, official)
        say(f"oficial guardado en {official}")
    if not _stop_all_herdr(say):
        raise AgentNavError("todavía hay procesos herdr.exe vivos; cerrá la pestaña de Herdr y repetí")
    last = None
    for _ in range(10):
        try:
            shutil.copy2(new_exe, exe)
            last = None
            break
        except PermissionError as e:
            last = e
            time.sleep(1)
    if last:
        raise AgentNavError(f"no pude reemplazar {exe}: {last}")
    with open(herdr_build_marker_path(), "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    say(f"herdr.exe reemplazado por {rel['tag']} (herdr {installed_herdr_version() or '?'}).")
    shutil.rmtree(dl, ignore_errors=True)
    return cmd_app(say)


# ---------------------------------------------------------------- temas

HERDR_THEMES = ("catppuccin", "catppuccin-latte", "terminal", "tokyo-night", "dracula", "nord", "gruvbox", "one-dark",
                "solarized", "kanagawa", "rose-pine", "vesper")
THEME_TOKENS = ("accent", "panel_bg", "sidebar_bg", "active_row_bg", "selection_bg", "surface0", "surface1", "surface_dim",
                "overlay0", "overlay1", "text", "subtext0", "mauve", "green", "yellow", "red", "blue", "teal", "peach")
THEMES_PATH = os.path.join(HOME, "config", "themes.json")
HERDR_CFG = os.path.join(os.environ.get("APPDATA", ""), "herdr", "config.toml")
REPO_CFG = os.path.join(HOME, "config", "herdr.config.toml")


def load_themes():
    data = _read_json_file(THEMES_PATH, "themes.json") or {}
    out = {}
    for name, t in data.items():
        if name.startswith("_") or not isinstance(t, dict):
            continue
        custom = {k: str(v) for k, v in (t.get("custom") or {}).items() if k in THEME_TOKENS}
        out[name.lower()] = {"title": str(t.get("title") or ""), "base": str(t.get("base") or "catppuccin"), "custom": custom}
    return out


def _theme_sections(text):
    """Divide el config.toml en (antes, [theme] y [theme.custom*], después) respetando comentarios ajenos."""
    lines = text.splitlines(keepends=True)
    head = re.compile(r"^\s*\[+\s*([^\]]*?)\s*\]+")
    before, mine, after, where = [], [], [], 0  # 0 = antes, 1 = adentro de theme, 2 = después
    for line in lines:
        m = head.match(line)
        if m:
            sec = m.group(1).strip()
            if sec == "theme" or sec.startswith("theme."):
                where = 1
            elif where == 1:
                where = 2
        (before, mine, after)[where].append(line)
    return "".join(before), "".join(mine), "".join(after)


def current_theme(text):
    """(nombre base, dict de [theme.custom]) según el TOML; sin tomllib, por regex."""
    try:
        import tomllib
        t = tomllib.loads(text).get("theme") or {}
        return str(t.get("name") or "catppuccin"), dict(t.get("custom") or {})
    except Exception:
        m = re.search(r'^\s*name\s*=\s*"([^"]*)"', text, re.M)
        return (m.group(1) if m else "catppuccin"), {}


def render_theme_block(base, custom, label, keep):
    """Sección [theme] nueva: nombre base, las claves que no son nuestras (auto_switch, dark_name…) y el [theme.custom]."""
    out = ["[theme]\n", f'name = "{base}"\n']
    for line in keep.splitlines(keepends=True):
        if re.match(r"^\s*(name\s*=|\[)", line):
            continue
        out.append(line)
    if out[-1].strip():
        out.append("\n")
    if custom:
        out.append(f"# AgentNav theme: {label} (agentnav theme {label}). Tokens sobre el tema base; editables en config\\themes.json.\n")
        out.append("[theme.custom]\n")
        for k in THEME_TOKENS:
            if k in custom:
                out.append(f'{k} = "{custom[k]}"\n')
        out.append("\n")
    return "".join(out)


def apply_theme(name, say=print):
    themes = load_themes()
    low = name.strip().lower()
    if low in themes and herdr_is_ours()[0]:
        base, custom, label = low, {}, low  # el herdr.exe del fork trae la paleta compilada: queda como tema nativo
    elif low in themes:
        base, custom, label = themes[low]["base"], themes[low]["custom"], low
    elif low in HERDR_THEMES:
        base, custom, label = low, {}, low
    else:
        raise AgentNavError(f"no conozco el tema '{name}'. Probá: agentnav theme")
    try:
        with open(HERDR_CFG, encoding="utf-8") as f:
            live = f.read()
    except OSError as e:
        raise AgentNavError(f"no puedo leer {HERDR_CFG}: {e}")
    before, mine, after = _theme_sections(live)
    if not mine:
        mine, after = "[theme]\n", ("\n" + before + after)  # sin sección: va al principio
        before = ""
    # De lo que había, conservar lo que no es nuestro: todo menos name y el bloque [theme.custom*]
    keep_lines, skipping = [], False
    for line in mine.splitlines(keepends=True):
        m = re.match(r"^\s*\[\s*([^\]]*?)\s*\]", line)
        if m:
            skipping = m.group(1).strip().startswith("theme.custom")
            continue
        if skipping or line.lstrip().startswith("# AgentNav theme:"):
            continue
        keep_lines.append(line)
    new = before + render_theme_block(base, custom, label, "".join(keep_lines)) + after
    try:
        import tomllib
        tomllib.loads(new)
    except ImportError:
        pass
    except Exception as e:
        raise AgentNavError(f"el config.toml resultante no parsea, no lo escribo: {e}")
    for path in (HERDR_CFG, REPO_CFG):
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
        except OSError as e:
            raise AgentNavError(f"no pude escribir {path}: {e}")
    try:
        api("server", "reload-config", timeout=15)
        say(f"tema {label}: aplicado y recargado" + (f" ({themes[low]['title']})" if low in themes else "") + ".")
    except AgentNavError as e:
        say(f"tema {label}: escrito en config.toml; el servidor no recargó ({e}). Se toma al reiniciar o con herdr server reload-config.")
    return 0


def theme_entries():
    """Lo que se puede elegir: las paletas de AgentNav y después los temas propios de Herdr."""
    themes = load_themes()
    out = [(n, t["title"]) for n, t in themes.items()]
    out += [(n, "tema de Herdr") for n in HERDR_THEMES]
    return out, themes


def theme_now(themes):
    try:
        with open(HERDR_CFG, encoding="utf-8") as f:
            base, custom = current_theme(f.read())
    except OSError:
        return "?"
    return next((n for n, t in themes.items() if t["base"] == base and t["custom"] == custom),
                base if not custom else f"{base} + custom")


def cmd_theme(name="", interactive=None):
    """Sin nombre: lista (o, en una consola, el selector con flechas y Enter: es lo que corre el popup ctrl+b alt+t).
    Con nombre: lo aplica."""
    if name:
        return apply_theme(name)
    entries, themes = theme_entries()
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        print(f"tema actual: {theme_now(themes)}")
        print("paletas de AgentNav (config\\themes.json):")
        for n, title in entries:
            if n in themes:
                print(f"  {n:<12} {title}")
        print("temas de Herdr:")
        print("  " + ", ".join(HERDR_THEMES))
        print("aplicar: agentnav theme <nombre>")
        return 0
    cur = theme_now(themes)
    sel = next((i for i, (n, _) in enumerate(entries) if n == cur), 0)
    msg = ""
    while True:
        sys.stdout.write("\x1b[2J\x1b[H")
        print(paint(" AgentNav · temas de Herdr ", "7"))
        print()
        for i, (n, title) in enumerate(entries):
            if i == len(themes):
                print()
            cursor = "▶" if i == sel else " "
            mark = "●" if n == cur else " "
            line = f" {cursor} {mark} {n:<16} {title}"
            print(paint(line, "7") if i == sel else line)
        print()
        print(paint("  ↑↓ mover · Enter aplicar (se ve al instante) · q salir", "2"))
        if msg:
            print("  " + msg)
        k = _getkey()
        if k in ("q", "esc"):
            return 0
        if k in ("up", "k"):
            sel = max(0, sel - 1)
        elif k in ("down", "j"):
            sel = min(len(entries) - 1, sel + 1)
        elif k == "enter":
            out = []
            try:
                apply_theme(entries[sel][0], say=out.append)
                cur = entries[sel][0]
            except AgentNavError as e:
                out.append(str(e))
            msg = " ".join(out)


def cmd_ntfy_test():
    err = ntfy_send("AgentNav", "aviso de prueba: si lo ves en el teléfono, los avisos funcionan.")
    if err:
        raise AgentNavError(err)
    print("aviso enviado.")
    return 0


# ---------------------------------------------------------------- update (el repo frente a origin, y las copias instaladas)

def _same_file(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def installed_copies():
    """[(origen en el repo, destino instalado)] de lo que vive fuera de C:\\AgentNav: doctor compara y update copia.

    Para tests: si existe AGENTNAV_SYNC_ROOT, los destinos se arman bajo esa carpeta (<root>\\.claude\\hooks\\…,
    <root>\\AppData\\Roaming\\…) en vez de USERPROFILE/APPDATA, así `update` no pisa la instalación viva."""
    root = os.environ.get("AGENTNAV_SYNC_ROOT")
    if root:
        claude_home, appdata = os.path.join(root, ".claude"), os.path.join(root, "AppData", "Roaming")
    else:
        claude_home, appdata = CLAUDE_HOME, os.environ.get("APPDATA", "")
    startup = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    return [
        (os.path.join(HOME, "hooks", "agentnav-state.ps1"), os.path.join(claude_home, "hooks", "agentnav-state.ps1")),
        (os.path.join(HOME, "hooks", "agentnav-unblock.cmd"), os.path.join(claude_home, "hooks", "agentnav-unblock.cmd")),
        (os.path.join(HOME, "startup", "Herdr server.vbs"), os.path.join(startup, "Herdr server.vbs")),
        (os.path.join(HOME, "config", "herdr.config.toml"), os.path.join(appdata, "herdr", "config.toml")),
    ]


def _git(args, timeout=30):
    """git en el repo de AgentNav. (código, stdout, stderr); AgentNavError si no hay git, no arranca o se cuelga."""
    git = shutil.which("git")
    if not git:
        raise AgentNavError("no encuentro git en el PATH")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # sin consola no hay quien conteste un pedido de credenciales
    try:
        cp = subprocess.run([git, "--no-optional-locks", "-C", HOME, *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, env=env, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise AgentNavError(f"git {' '.join(args)}: sin respuesta en {timeout} s")
    except OSError as e:
        raise AgentNavError(f"no pude ejecutar git: {e}")
    return cp.returncode, cp.stdout.strip(), cp.stderr.strip()


def parse_ahead_behind(text):
    """Salida de `git rev-list --left-right --count HEAD...origin/main` ("2\\t3") → (adelante, atrás)."""
    m = re.fullmatch(r"\s*(\d+)\s+(\d+)\s*", text or "")
    if not m:
        raise AgentNavError(f"salida inesperada de git rev-list: {(text or '')[:80]!r}")
    return int(m.group(1)), int(m.group(2))


def update_action(dirty, ahead, behind, check=False):
    """Qué hace `update` con el repo: "al_dia" | "nuevos" (sólo --check, hay commits que traer) | "sucio" (hay que
    traer pero el árbol tiene cambios locales: no se toca nada) | "adelantado" (commits locales sin pushear: no se
    hace pull) | "pull". Los cambios locales sólo estorban al pull: sin nada que traer se sigue y se sincronizan las copias."""
    if check:
        return "nuevos" if behind else "al_dia"
    if behind and dirty:
        return "sucio"
    if ahead:
        return "adelantado"
    return "pull" if behind else "al_dia"


def merge_config_keeping_theme(repo_text, live_text):
    """Texto del config.toml del repo con la sección [theme] (y [theme.custom*]) del archivo vivo: el tema se elige
    dentro de Herdr y sólo queda escrito ahí, así que una copia cruda lo pisaría. Si el vivo no tiene sección de tema,
    queda la del repo. AgentNavError si el resultado no parsea."""
    before, mine, after = _theme_sections(repo_text)
    _, live_theme, _ = _theme_sections(live_text)
    new = before + (live_theme or mine) + after
    try:
        import tomllib
        tomllib.loads(new)
    except ImportError:
        pass
    except Exception as e:
        raise AgentNavError(f"el config.toml resultante no parsea, no lo escribo: {e}")
    return new


def repo_status(fetch_timeout=30):
    """Estado del clon de AgentNav frente a origin: {"sha", "upstream", "dirty", "ahead", "behind", "fetch_error"}.
    AgentNavError si HOME no es un clon con remoto origin. Si el fetch falla (sin red), fetch_error lo cuenta y
    adelante/atrás salen de lo último que se trajo."""
    sin_clon = (f"{HOME} no es un clon de git: reinstalá con el zip o cloná https://github.com/pablitotester/AgentNav "
                "(git clone https://github.com/pablitotester/AgentNav.git C:\\AgentNav)")
    if not os.path.exists(os.path.join(HOME, ".git")):
        raise AgentNavError(sin_clon)
    code, _, _ = _git(["rev-parse", "--is-inside-work-tree"], timeout=10)
    if code != 0:
        raise AgentNavError(sin_clon)
    code, _, _ = _git(["remote", "get-url", "origin"], timeout=10)
    if code != 0:
        raise AgentNavError(f"{HOME} no tiene remoto origin: " + sin_clon.split(": ", 1)[1])
    fetch_error = None
    try:
        code, out, err = _git(["fetch", "origin"], timeout=fetch_timeout)
        if code != 0:
            lines = [l.strip() for l in (err or out).splitlines() if l.strip()]
            # git explica en varias líneas; la útil es la primera "fatal:" (la última es "and the repository exists.")
            fetch_error = next((l for l in lines if l.startswith("fatal:")), lines[0] if lines else f"salió con {code}")
    except AgentNavError as e:
        fetch_error = str(e)
    _, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)  # "HEAD" = suelto
    code, up, _ = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], timeout=10)
    if code == 0 and up.startswith("origin/"):
        upstream = up
    elif branch == "main":
        upstream = "origin/main"  # clon recién hecho sin tracking: main sigue a origin/main
    else:
        upstream = None  # HEAD suelto o rama propia sin upstream: no hay con qué comparar ni a qué hacer pull
    _, sha, _ = _git(["rev-parse", "--short", "HEAD"], timeout=10)
    # Sólo cambios en archivos versionados: uno sin seguimiento no estorba al pull (y si estorbara, git lo dice).
    _, status, _ = _git(["status", "--porcelain", "--untracked-files=no"], timeout=10)
    st = {"sha": sha, "branch": branch, "upstream": upstream, "dirty": bool(status), "ahead": 0, "behind": 0,
          "fetch_error": fetch_error}
    if upstream:
        code, out, err = _git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], timeout=10)
        if code != 0:
            raise AgentNavError(f"no pude comparar HEAD con {upstream}: {err or out}")
        st["ahead"], st["behind"] = parse_ahead_behind(out)
    return st


def _sin_upstream(st):
    """Texto del aviso cuando no hay rama remota con qué comparar, o None si la hay."""
    if st["upstream"]:
        return None
    que = "HEAD suelto" if st["branch"] == "HEAD" else f"rama {st['branch']} sin upstream"
    return f"{que} en {HOME}: no comparo con origin ni hago pull (git checkout main)"


def sync_installed_copies(say=print):
    """Copia a su lugar las copias instaladas que difieran del repo (bytes exactos: el .ps1 lleva BOM, el .cmd no).
    Al config.toml de Herdr lo respalda antes y le pide al servidor que lo recargue. Devuelve los destinos que cambiaron."""
    changed = []
    for src, dst in installed_copies():
        if not os.path.isfile(src) or (os.path.isfile(dst) and _same_file(src, dst)):
            continue
        es_cfg = os.path.basename(src) == "herdr.config.toml"
        habia = os.path.isfile(dst)
        try:
            new = None
            if es_cfg and habia:
                # El tema se elige dentro de Herdr y sólo queda en el config vivo: se conserva su sección [theme].
                with open(src, encoding="utf-8") as f, open(dst, encoding="utf-8") as g:
                    repo_text, live_text = f.read(), g.read()
                new = merge_config_keeping_theme(repo_text, live_text)
                if new == live_text:
                    continue  # difería sólo en el tema propio: no hay nada que traer
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if es_cfg and habia:
                bak = dst + ".bak-" + time.strftime("%Y-%m-%d-%H%M%S")
                shutil.copyfile(dst, bak)
                say(f"respaldo: {bak}")
            if new is not None:
                with open(dst, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new)
            else:
                shutil.copyfile(src, dst)
        except OSError as e:
            raise AgentNavError(f"no pude copiar {src} → {dst}: {e}")
        say(f"{'actualizado' if habia else 'instalado'}: {dst}" + (" (tema propio conservado)" if new is not None else ""))
        changed.append(dst)
        if es_cfg and dst == HERDR_CFG:  # el servidor lee el config real, no el de AGENTNAV_SYNC_ROOT
            try:
                if server_running():
                    api("server", "reload-config", timeout=15)
                    say("servidor de Herdr: config recargado")
            except AgentNavError as e:
                say(f"el servidor de Herdr no recargó el config ({e}); se toma al reiniciar o con herdr server reload-config")
    if not changed:
        say("nada que sincronizar: hooks, arranque y config de Herdr iguales al repo")
    return changed


def cmd_update(argv, say=print):
    check = "--check" in argv
    st = repo_status(fetch_timeout=30)
    if st["fetch_error"]:
        raise AgentNavError(f"git fetch origin falló: {st['fetch_error']}")
    if _sin_upstream(st):
        raise AgentNavError(_sin_upstream(st))
    action = update_action(st["dirty"], st["ahead"], st["behind"], check)
    if action == "nuevos":
        say(f"hay {st['behind']} commit(s) nuevos en {st['upstream']}: agentnav update")
        return 10
    if action == "al_dia":
        say(f"al día en {st['sha']}" + (f" (hay cambios locales sin commitear en {HOME})" if st["dirty"] else ""))
        if check:
            return 0
    elif action == "sucio":
        say(f"hay {st['behind']} commit(s) para traer pero cambios locales sin commitear en {HOME}; no toco nada "
            "(git status, y commiteá o descartá)")
        return 1
    elif action == "adelantado":
        say(f"{HOME} tiene {st['ahead']} commit(s) locales sin pushear"
            + (f" y {st['upstream']} {st['behind']} nuevos" if st["behind"] else "") + ": no hago pull (git push, o rebase a mano)")
    elif action == "pull":
        remote, _, branch = st["upstream"].partition("/")
        code, out, err = _git(["pull", "--ff-only", remote, branch], timeout=60)
        if code != 0:
            raise AgentNavError(f"git pull --ff-only falló:\n{err or out}")
        _, sha, _ = _git(["rev-parse", "--short", "HEAD"], timeout=10)
        say(f"actualizado: {st['sha']} → {sha} ({st['behind']} commit(s))")
    sync_installed_copies(say)
    say("listo; agentnav doctor para verificar la instalación.")
    return 0


# ---------------------------------------------------------------- doctor

# Hooks nuestros en el settings.json de Gemini CLI: evento → fragmento del "command" (lo registra el instalador
# -ConGemini, con el mismo hook agentnav-state.ps1 que Claude, parametrizado por tipo).
GEMINI_HOOK_EVENTS = (("SessionStart", 'agentnav-state.ps1" start gemini'), ("BeforeAgent", 'agentnav-state.ps1" prompt gemini'),
                      ("AfterAgent", 'agentnav-state.ps1" stop gemini'), ("SessionEnd", 'agentnav-state.ps1" end gemini'),
                      ("Notification", 'agentnav-state.ps1" notify gemini'), ("AfterTool", 'agentnav-unblock.cmd" gemini'))


def gemini_version(timeout=20):
    """(ruta del lanzador, versión) de Gemini CLI, o (None, "") si no está en el PATH. La versión sale del package.json
    que npm deja al lado del lanzador (%APPDATA%\\npm\\node_modules\\@google\\gemini-cli); `gemini --version` levanta node
    (1-2 s) y queda sólo de respaldo."""
    exe = shutil.which("gemini")
    if not exe:
        return None, ""
    pkg = os.path.join(os.path.dirname(exe), "node_modules", "@google", "gemini-cli", "package.json")
    try:
        with open(pkg, encoding="utf-8") as f:
            ver = str(json.load(f).get("version") or "")
        if ver:
            return exe, ver
    except (OSError, ValueError, AttributeError):
        pass
    try:
        cp = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return exe, ""
    lines = (cp.stdout or cp.stderr).strip().splitlines()
    return exe, (lines[-1].strip() if lines else "")


def gemini_hook_status(settings):
    """Qué eventos de GEMINI_HOOK_EVENTS tienen nuestro hook en un settings.json de Gemini (misma lectura que para
    el de Claude: hooks.<Evento>[].hooks[].command). Devuelve (registrados, faltantes)."""
    hooks = (settings or {}).get("hooks") or {}
    have, missing = [], []
    for ev, needle in GEMINI_HOOK_EVENTS:
        blocks = hooks.get(ev) or []
        found = any(needle in str(h.get("command", "")) for b in blocks if isinstance(b, dict)
                    for h in (b.get("hooks") or []) if isinstance(h, dict))
        (have if found else missing).append(ev)
    return have, missing


def gemini_api_key_present(env_path=None):
    """Hay clave de Gemini: GEMINI_API_KEY o GOOGLE_API_KEY en el entorno, o una línea así en ~/.gemini/.env."""
    if any(os.environ.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY")):
        return True
    try:
        with open(env_path or GEMINI_ENV, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*(\S+)", line)
                if m and m.group(2).strip("\"'"):
                    return True
    except OSError:
        pass
    return False


def _gemini_trust_key(path):
    """Cómo Gemini escribe las rutas en trustedFolders.json (normalizePath): real, minúsculas y con barras normales."""
    return os.path.normpath(os.path.realpath(path)).replace("\\", "/").lower().rstrip("/")


def gemini_folder_trusted(path, rules=None, settings=None):
    """Si Gemini CLI va a arrancar en esa carpeta sin preguntar: True (confiada), False (va a mostrar el diálogo
    "Trust folder / Trust parent / Don't trust"), None (no se sabe o el chequeo está apagado). Misma regla que
    checkPathTrust: manda la regla más larga cuyo alcance (la carpeta, o su padre con TRUST_PARENT) contiene a path;
    sin regla, no confiada. security.folderTrust.enabled = false en settings.json apaga el diálogo."""
    try:
        if settings is None:
            settings = _read_json_file(os.path.join(GEMINI_HOME, "settings.json"), "settings.json de Gemini") or {}
        if (((settings or {}).get("security") or {}).get("folderTrust") or {}).get("enabled") is False:
            return None
        if rules is None:
            rules = _read_json_file(GEMINI_TRUSTED, "trustedFolders.json de Gemini") or {}
    except AgentNavError:
        return None
    if not isinstance(rules, dict):
        return None
    want = _gemini_trust_key(path)
    best_len, best = -1, None
    for rule, level in rules.items():
        scope = str(rule).replace("\\", "/").lower().rstrip("/")
        if level == "TRUST_PARENT":
            scope = scope.rsplit("/", 1)[0] if "/" in scope else scope
        if (want == scope or want.startswith(scope + "/")) and len(str(rule)) > best_len:
            best_len, best = len(str(rule)), level
    return best in ("TRUST_FOLDER", "TRUST_PARENT")


def gemini_auth_note(settings, env_path=None):
    """Aviso (None, texto) si Gemini no va a poder autenticarse: login por clave (security.auth.selectedType
    gemini-api-key) sin clave en el entorno ni en ~/.gemini/.env, o ningún tipo de login elegido y tampoco clave
    (el primer arranque pide elegir). Con oauth u otro tipo elegido no se opina. None si está bien."""
    auth = ((settings or {}).get("security") or {}).get("auth") or {}
    sel = str(auth.get("selectedType") or "")
    if sel and sel != "gemini-api-key":
        return None
    if gemini_api_key_present(env_path):
        return None
    where = os.path.dirname(env_path or GEMINI_ENV)
    if sel == "gemini-api-key":
        return None, f"Gemini sin API key: login por clave elegido pero no hay GEMINI_API_KEY (ni en {where}\\.env ni en el entorno)"
    return None, f"Gemini sin login configurado: ni API key en {where}\\.env ni security.auth.selectedType en settings.json (lo pide al arrancar)"


def gemini_checks(projects=None):
    """Bloque "Gemini CLI" de doctor: sólo si algún proyecto/agente es gemini o gemini está en el PATH. Lista de
    (ok, texto) como las demás comprobaciones."""
    try:
        projects = load_projects() if projects is None else projects
    except AgentNavError:
        projects = []
    uses = sorted({p["name"] for p in projects for a in p["agents"] if a["kind"] == "gemini"})
    exe, ver = gemini_version()
    if not exe and not uses:
        return []
    out = []
    if exe:
        out.append((True, f"Gemini CLI: {exe} ({ver or 'versión desconocida'})"))
    else:
        out.append((False, f"Gemini CLI no está en el PATH y lo usan {', '.join(uses)}: npm install -g @google/gemini-cli"))
    settings_path = os.path.join(GEMINI_HOME, "settings.json")
    try:
        settings = _read_json_file(settings_path, "settings.json de Gemini") or {}
        have, missing = gemini_hook_status(settings)
        if not missing:
            out.append((True, f"settings.json de Gemini: hooks {', '.join(have)}"))
        else:
            out.append((None if not uses else False,
                        f"settings.json de Gemini: faltan los hooks {', '.join(missing)} (el estado de cada Gemini no llega a Herdr): installer\\install.ps1 -ConGemini"))
        note = gemini_auth_note(settings)
        if note:
            out.append(note)
    except AgentNavError as e:
        out.append((None if not uses else False, str(e)))
    if uses:
        out.append((None, f"proyectos con Gemini: {', '.join(uses)} ('continue' retoma por --resume la sesión de ~/.gemini/tmp)"))
    return out


def shell_versions(exe, timeout=15):
    """(versión de PowerShell, versión de PSReadLine) de ese pwsh.exe/powershell.exe; "" lo que no se pueda leer.
    Un arranque sin perfil (~0,3 s), sólo en doctor."""
    try:
        cp = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command",
                             '"$($PSVersionTable.PSVersion)|$((Get-Module PSReadLine -ListAvailable | Sort-Object Version -Descending | Select-Object -First 1).Version)"'],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
        parts = (cp.stdout or "").strip().splitlines()[-1].split("|") if (cp.stdout or "").strip() else []
    except (OSError, subprocess.TimeoutExpired):
        parts = []
    return (parts[0].strip() if parts else ""), (parts[1].strip() if len(parts) > 1 else "")


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def shell_check(shell, exe, versions=("", "")):
    """Comprobación de doctor del shell que abre cada panel (terminal.default_shell): que exista (si pide pwsh y
    falta, Herdr abre lo que haya: Windows PowerShell 5.1) y, en PowerShell, qué PSReadLine tiene. Devuelve (ok, texto).
    Lo medido: el eco de las teclas no depende de PSReadLine ni de sus opciones (ver README), así que una versión vieja
    es sólo un aviso."""
    s = os.path.basename(str(shell or "").strip().strip('"')).lower()
    if s.endswith(".exe"):
        s = s[:-4]
    if not s:
        return None, "config.toml sin terminal.default_shell: Herdr abre su shell por defecto"
    if not exe:
        if s == "pwsh":
            return False, "default_shell = pwsh pero pwsh no está en el PATH: Herdr abre Windows PowerShell 5.1 en su lugar (winget install Microsoft.PowerShell)"
        return False, f"default_shell = {shell} pero no está en el PATH"
    if s not in ("pwsh", "powershell"):
        return True, f"shell de los paneles: {shell} ({exe})"
    ps, psrl = versions
    text = f"shell de los paneles: {s} {ps or '?'} (PSReadLine {psrl or '?'})"
    if psrl and _ver_tuple(psrl) < (2, 3):
        return None, text + ": PSReadLine viejo; el actual (2.4) trae predicción y vista en lista, opcional: Install-Module PSReadLine -Scope CurrentUser"
    return True, text


def cmd_doctor():
    results = []  # (True|False|None, texto)  None = aviso, no cuenta como problema

    def check(ok, text):
        results.append((ok, text))

    # Lo que tarda (git fetch a origin ~1 s, un pwsh para las versiones ~0,4 s) arranca ya en hilos, en paralelo con
    # el resto de las comprobaciones, y se recoge donde se informa.
    origin_t = start_update_check(fetch_timeout=10) if shutil.which("git") else None
    sh = default_shell()
    sh_exe = shutil.which(sh) if sh else None
    shell_t = (in_thread(lambda: shell_versions(sh_exe), "agentnav-shell-versions")
               if sh_exe and os.path.basename(sh_exe).lower() in ("pwsh.exe", "powershell.exe") else None)
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
    # Copias instaladas fuera del repo, en el orden de installed_copies()
    (_, hook), (_, unblock), (repo_vbs, vbs), (repo_cfg, cfg_path) = installed_copies()
    # Config de Herdr
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = f.read()
        check("agentnav.py pick" in cfg, "config.toml: popup del selector (prefix+alt+p)")
        check("agentnav.py tab\"" in cfg and 'new_tab = ""' in cfg,
              "config.toml: ctrl+b c abre la pestaña de AgentNav (shell en la misma carpeta, sin agente)")
        check("agentnav.py tab shell" in cfg, "config.toml: ctrl+b shift+c abre la pestaña pelada por la API")
        check("agentnav.py theme" in cfg, "config.toml: popup de temas (prefix+alt+t)")
        check('help = "prefix+f1"' in cfg, "config.toml: ayuda en prefix+F1 (el teclado en español no entrega '?')")
        try:
            import tomllib
            parsed = tomllib.loads(cfg)
            check(bool((parsed.get("session") or {}).get("resume_agents_on_restore")), "config.toml: agentes se reanudan al restaurar")
        except Exception as e:  # tomllib falta (Python < 3.11) o el TOML está roto
            check(False, f"config.toml no parsea: {e}")
        if os.path.isfile(repo_cfg):
            same = _same_file(repo_cfg, cfg_path)
            if same:
                check(True, "config.toml igual a la copia del repo")
            else:
                try:  # ¿difiere sólo en la sección de tema (elegido dentro de Herdr)? Entonces no hay nada que traer.
                    with open(repo_cfg, encoding="utf-8") as f:
                        solo_tema = merge_config_keeping_theme(f.read(), cfg) == cfg
                except (OSError, AgentNavError):
                    solo_tema = False
                check(solo_tema, f"config.toml igual a la copia del repo (tema propio: {current_theme(cfg)[0]})" if solo_tema
                      else f"config.toml difiere de {repo_cfg} (agentnav update lo copia, con respaldo y conservando el tema)")
    except OSError:
        check(False, f"no encuentro {cfg_path}")
    # El shell de cada panel: que exista el que pide el config y qué PSReadLine trae
    if shell_t:
        shell_t.join(20)
    versions = shell_t.result if shell_t and isinstance(shell_t.result, tuple) else ("", "")
    check(*shell_check(sh, sh_exe, versions))
    # Plugin de Herdr (gancho tab.created → agentnav adopt)
    try:
        plugins = api("plugin", "list", "--json").get("plugins") or []
        mine = next((x for x in plugins if x.get("plugin_id") == "agentnav"), None)
        if mine and mine.get("enabled"):
            hooks = {e.get("on") for e in (mine.get("events") or [])}
            need = {"tab.created", "pane.created", "pane.focused"}
            check(need <= hooks,
                  'plugin de Herdr "agentnav" enlazado: el "+" y el split abren un shell en la carpeta del panel de origen' if need <= hooks
                  else f"plugin de Herdr enlazado pero con ganchos viejos ({', '.join(sorted(hooks))}): herdr plugin unlink agentnav; herdr plugin link C:\\AgentNav\\plugin")
        else:
            check(False, "plugin de Herdr sin enlazar o apagado: herdr plugin link C:\\AgentNav\\plugin")
    except AgentNavError as e:
        check(False, f"plugin de Herdr: {e}")
    # Hooks de Claude Code
    if os.path.isfile(hook):
        with open(hook, "rb") as f:
            bom = f.read(3) == b"\xef\xbb\xbf"
        check(bom, f"hook {os.path.basename(hook)} guardado como UTF-8 con BOM" if bom else f"hook {hook} SIN BOM: PowerShell 5.1 va a romper los acentos")
    else:
        check(False, f"falta el hook {hook}")
    if os.path.isfile(unblock):
        with open(unblock, "rb") as f:
            head = f.read(16)
        ok = not head.startswith(b"\xef\xbb\xbf") and head.lstrip().lower().startswith(b"@echo")
        check(ok, f"hook de desbloqueo {os.path.basename(unblock)} sin BOM y con @echo off" if ok
              else f"{unblock}: tiene BOM o no empieza con @echo off (cmd fallaría en cada herramienta)")
    else:
        check(False, f"falta {unblock}")
    for a, b in installed_copies()[:2]:
        name = os.path.basename(a)
        if os.path.isfile(a) and os.path.isfile(b):
            same = _same_file(a, b)
            check(same, f"{name} igual a la copia del repo" if same else f"{name} difiere entre {a} y {b} (agentnav update)")
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
        matchers = [str(block.get("matcher") or "") for block in hooks.get("Notification") or []
                    if any("agentnav-state.ps1" in str(h.get("command", "")) for h in block.get("hooks") or [])]
        okm = any("permission_prompt" in m and "idle_prompt" in m for m in matchers)
        check(okm, "settings.json de Claude: Notification con matcher permission_prompt|idle_prompt" if okm
              else f"settings.json de Claude: el hook Notification no filtra permission_prompt|idle_prompt (matcher: {matchers or 'ninguno'})")
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
        if server:
            names = _process_env_names(server["pid"])
            leaked = sorted(n for n in (names or []) if n.upper().startswith("CLAUDE"))
            if leaked:
                check(False, "el servidor de Herdr heredó variables de un Claude (" + ", ".join(leaked[:4])
                      + ("…" if len(leaked) > 4 else "") + ") y se las pasa a cada panel: herdr server stop, después agentnav up")
            elif names is not None:
                check(True, "servidor de Herdr con entorno limpio (sin CLAUDE*)")
        for p in projects:
            for kind in sorted({a["kind"] for a in p["agents"] if a["kind"] in EXIT_COMMAND and a.get("continue")}):
                if agents_outside_herdr(p["path"], kind):
                    check(None, f"  {p['name']}: hay un {kind} corriendo en esa carpeta fuera de Herdr; 'continue' no lo va a pisar, arranca uno nuevo")
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
    for ok, text in gemini_checks():
        check(ok, text)
    # Arranque, Python, Windows Terminal
    check(os.path.isfile(vbs), "arranque automático del servidor (Herdr server.vbs en Inicio)" if os.path.isfile(vbs) else f"falta {vbs}")
    if os.path.isfile(vbs) and os.path.isfile(repo_vbs) and not _same_file(vbs, repo_vbs):
        check(False, f"Herdr server.vbs de Inicio difiere de {repo_vbs} (agentnav update)")
    check(bool(shutil.which("wt.exe") or shutil.which("wt")), "Windows Terminal (wt.exe)")
    import struct
    bits = struct.calcsize("P") * 8
    check(bits == 64, f"Python {sys.version.split()[0]} de {bits} bits en {sys.executable}" if bits == 64
          else f"Python de {bits} bits: el escaneo de procesos no funciona y 'continue' podría pisar una conversación abierta afuera")
    check(bool(shutil.which("git")), "git (para rama y cambios en el selector)")
    # El repo frente a origin (sin red no demora más que el timeout del fetch, y nunca es ✖)
    if origin_t:
        origin_t.join(15)
        st = origin_t.result
        if isinstance(st, AgentNavError):
            check(None, str(st))
        elif st is None:
            check(None, "no pude consultar origin: el fetch no terminó a tiempo")
        else:
            if st["fetch_error"]:
                check(None, f"no pude consultar origin: {st['fetch_error']}")
            elif _sin_upstream(st):
                check(None, _sin_upstream(st))
            elif st["behind"]:
                check(None, f"hay {st['behind']} commit(s) nuevos en origin: agentnav update")
            else:
                check(True, f"repo al día con origin ({st['sha']})")
            if st["ahead"]:
                check(None, f"{st['ahead']} commit(s) locales en {HOME} sin pushear a origin")
            if st["dirty"]:
                check(None, f"cambios locales sin commitear en {HOME}")
    # Herdr propio (fork con temas)
    repo = fork_repo()
    if repo:
        exe = os.path.join(herdr_release_dir(), "herdr.exe")
        try:
            have = file_sha256(exe) if os.path.isfile(exe) else ""  # un solo hash para el marcador y para el release
        except OSError:
            have = ""
        ours, detail = herdr_is_ours(have or None)
        rel, want, state, net_error = None, "", "", None
        try:
            rel = fork_latest_release(repo)
            inst = installed_herdr_version()
            if rel:
                want = fork_release_sha(rel)
                state = fork_sync_state(inst, have, rel["version"], want)
        except AgentNavError as e:
            net_error = str(e)
        if ours:
            check(True, f"Herdr con los temas de AgentNav: {detail}")
        elif state == "al_dia":  # el exe es el del fork pero lo puso el instalador oficial: no hay marcador (o es viejo)
            check(None, "exe del fork sin marcador agentnav-build.json: agentnav herdr-sync lo anota")
        elif ours is False and "pisó" in detail:
            check(False, f"{detail}: agentnav herdr-sync lo vuelve a poner")
        else:
            check(None, f"Herdr oficial ({detail}); agentnav herdr-sync instala el del fork {repo}")
        if net_error:
            check(None, net_error)
        elif not rel:
            check(None, f"el fork {repo} no publicó releases todavía")
        elif state == "al_dia":
            check(True, f"fork {repo}: {rel['tag']} al día (sha {want[:8]})")
        elif state == "version_nueva":
            check(None, f"el fork tiene {rel['tag']} y está instalado {inst}: agentnav herdr-sync")
        elif state == "rebuild":
            check(None, f"el fork republicó {rel['tag']} con otro build (sha {want[:8]}, instalado {have[:8] or '-'}): agentnav herdr-sync")
        else:
            check(None, f"Herdr {inst} es más nuevo que el último build del fork ({rel['tag']}); el workflow lo alcanza en su próxima corrida")
        task = herdr_update_task_registered()
        if task:
            check(True, f"tarea '{HERDR_UPDATE_TASK}' registrada (chequeo automático de Herdr)")
        elif task is None:
            check(None, f"no pude consultar schtasks por la tarea '{HERDR_UPDATE_TASK}'")
        else:
            check(None, f"sin la tarea '{HERDR_UPDATE_TASK}' (chequeo automático): la crea {os.path.join(HOME, 'herdr-fork', 'install.ps1')} -NoLaunch, "
                        "que además reinstala el build del fork y puede cerrar Herdr; correrlo sin agentes trabajando")

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
            name = _ask("  nombre: ").strip()
            path = _ask("  ruta:   ")
            try:
                if not name:
                    raise AgentNavError("no agregado: falta el nombre")
                path = _project_path(path)
                if not os.path.isdir(path):
                    raise AgentNavError(f"no agregado: la ruta no existe ({path})")
                add_project(_check_project_name(name), path)
                projects, sel, snap, msg = load_projects(), len(projects), None, f"agregado {name}"
            except AgentNavError as e:
                msg = str(e)
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
    if cmd in ("update", "actualizar"):
        return cmd_update(argv[1:])
    if cmd in ("herdr-sync", "herdr"):
        return cmd_herdr_sync(argv[1:])
    if cmd in ("theme", "tema"):
        arg = rest.strip()
        return cmd_theme("" if arg in ("pick", "list") else arg, interactive=(True if arg == "pick" else False if arg == "list" else None))
    if cmd in ("ntfy-test", "ntfy"):
        return cmd_ntfy_test()
    if cmd in ("labels", "etiquetas"):
        return label_agents()
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
        return cmd_new(argv[1:])
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
        if [a.lower() for a in sys.argv[1:3]] not in (["pick"], ["theme"], ["theme", "pick"], ["tema"], ["tema", "pick"]):
            _restore()  # el popup muere con su consola; a una pwsh ajena le devolvemos su code page
    sys.exit(code)
