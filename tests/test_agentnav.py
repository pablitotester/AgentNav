"""Tests de las funciones puras de agentnav.py: ni Herdr, ni red, ni procesos. Correr desde C:\\AgentNav:

    py -X utf8 -m unittest discover -s tests

Lo que toca disco va a carpetas temporales (JOURNAL_DIR, CLAUDE_PROJECTS se reemplazan en el módulo)."""
import json
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentnav as an  # noqa: E402


class Registro(unittest.TestCase):
    def test_norm_agent_string(self):
        a = an._norm_agent("qa", "claude", ["--model", "x"], True, "f")
        self.assertEqual(a, {"name": "qa", "kind": "claude", "args": ["--model", "x"], "continue": True,
                             "command": "", "split": None, "ratio": None})

    def test_norm_agent_objeto_anula_args_y_valida_split_ratio(self):
        a = an._norm_agent({"name": "web", "args": [], "split": "left", "ratio": "0.4"}, "claude", ["-x"], True, "f")
        self.assertEqual(a["args"], [])
        self.assertIsNone(a["split"])
        self.assertEqual(a["ratio"], 0.4)
        self.assertEqual(an._norm_agent({"split": "down", "ratio": "no"}, "claude", [], False, "f")["ratio"], None)
        self.assertEqual(an._norm_agent({"split": "down"}, "claude", [], False, "f")["split"], "down")

    def test_norm_agent_shell_no_continua_y_lleva_comando(self):
        a = an._norm_agent({"name": "srv", "kind": "shell", "command": "npm start", "continue": True}, "claude", [], True, "f")
        self.assertFalse(a["continue"])
        self.assertEqual(a["command"], "npm start")
        self.assertEqual(an._norm_agent({"name": "c", "command": "x"}, "claude", [], True, "f")["command"], "")
        self.assertIsNone(an._norm_agent(3, "claude", [], True, "f"))

    def test_project_path(self):
        self.assertEqual(an._project_path(' "C:\\Proyectos\\Uno\\" '), "C:\\Proyectos\\Uno")
        for bad in ("C:AgentNav", "..\\x", "x", "\\solo", ""):
            with self.assertRaises(an.AgentNavError, msg=bad):
                an._project_path(bad)

    def test_find_project(self):
        ps = [{"name": "MiniZelda"}, {"name": "Mini"}, {"name": "RemoteDesk"}]
        self.assertEqual(an.find_project(ps, "mini")["name"], "Mini")  # exacto gana al prefijo
        self.assertEqual(an.find_project(ps, "rem")["name"], "RemoteDesk")
        self.assertIsNone(an.find_project(ps, "zz"))
        self.assertIsNone(an.find_project(ps, "  "))
        with self.assertRaises(an.AgentNavError):
            an.find_project(ps + [{"name": "Remoto"}], "rem")

    def test_agent_name(self):
        taken = set()
        self.assertEqual(an.agent_name("QA Web!", taken), "qa-web")
        self.assertEqual(an.agent_name("qa web", taken), "qa-web-2")
        self.assertEqual(an.agent_name("3d", set()), "a3d")
        self.assertEqual(an.agent_name("---", set()), "agente")
        self.assertEqual(len(an.agent_name("x" * 50, set())), 28)
        self.assertTrue(re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", an.agent_name("Ñandú_2", set())))


class ClaudeCode(unittest.TestCase):
    def test_claude_project_key(self):
        self.assertEqual(an.claude_project_key("C:\\Nevatars\\nevatars\\"), "C--Nevatars-nevatars")
        self.assertEqual(an.claude_project_key("C:/AgentNav"), "C--AgentNav")

    def test_prompt_re(self):
        ok = ["PS C:\\x> ", "PS C:\\x>", "PS C:\\x> \n", "C:\\Users\\pablo>", "C:\\>  ", "pablo@pc MINGW64 ~\n$ ", "$"]
        no = ["❯ ", "cargando...", "PS C:\\x> dir\nsalida", "> "]
        for p in ok:
            self.assertTrue(re.search(an.PROMPT_RE, p), p)
        for p in no:
            self.assertFalse(re.search(an.PROMPT_RE, p), p)

    def test_cd_command(self):
        self.assertEqual(an._cd_command("pwsh.exe", "C:\\it's\\x"), "Set-Location -LiteralPath 'C:\\it''s\\x'")
        self.assertEqual(an._cd_command("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "C:\\a"),
                         "Set-Location -LiteralPath 'C:\\a'")
        self.assertEqual(an._cd_command("cmd.exe", "C:\\a b"), 'cd /d "C:\\a b"')
        self.assertEqual(an._cd_command("bash.exe", "C:\\it's"), "cd 'C:\\it'\\''s'")
        self.assertEqual(an._cd_command("", "C:\\a"), "cd 'C:\\a'")

    def test_tab_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "Proj")
            sub = os.path.join(proj, "src")
            other = os.path.join(tmp, "Other")
            for d in (proj, sub, other):
                os.makedirs(d)
            p = {"path": proj}
            self.assertEqual(an._tab_path(sub, p), sub)            # subcarpeta del proyecto: se hereda
            self.assertEqual(an._tab_path(other, p), proj)         # afuera: manda el proyecto
            self.assertEqual(an._tab_path(proj + "x", p), proj)    # prefijo engañoso no cuenta
            self.assertEqual(an._tab_path(other, None), other)     # sin proyecto: la del panel
            self.assertEqual(an._tab_path(os.path.join(tmp, "no"), {"path": os.path.join(tmp, "no")}),
                             an.new_project_base())                 # nada existe: donde nacen los proyectos

    def test_tab_label(self):
        self.assertEqual(an._tab_label("C:\\Proyectos\\Nevatars\\"), "Nevatars")
        self.assertEqual(an._tab_label("C:\\Proyectos\\Nevatars/src"), "src")
        self.assertEqual(an._tab_label("C:\\"), "shell")          # raíz: no hay nombre
        self.assertEqual(an._tab_label("C:\\obra\\2024"), "shell")  # numérica: al nacer la adoptaría el plugin
        self.assertEqual(an._tab_label("C:\\obra\\v2"), "v2")

    def test_adopt_origin(self):
        a = {"pane_id": "w1:p1", "cwd": "C:\\A", "rect": {"x": 0, "y": 0, "width": 50, "height": 20}}
        b = {"pane_id": "w1:p2", "cwd": "C:\\B", "rect": {"x": 50, "y": 0, "width": 50, "height": 20}}
        new = {"pane_id": "w1:p3", "cwd": "C:\\", "rect": {"x": 50, "y": 20, "width": 50, "height": 20}}
        pool = [a, b]
        layout = {"panes": [dict(pane_id=x["pane_id"], rect=x["rect"]) for x in (a, b, new)]}
        # rastro de foco: el último enfocado que no sea el nuevo y esté entre los candidatos
        self.assertIs(an._adopt_origin(pool, "w1:p3", ["w1:p3", "w1:p1", "w1:p2"]), a)
        self.assertIs(an._adopt_origin(pool, "w1:p3", ["w1:p9", "w1:p2"]), b)   # p9 ya no existe
        # sin rastro: geometría del split (el nuevo nació debajo de b)
        self.assertIs(an._adopt_origin(pool, "w1:p3", [], layout), b)
        self.assertIsNone(an._adopt_origin(pool, "w1:p3", []))                 # pestaña nueva sin rastro: nada
        self.assertIsNone(an._adopt_origin(pool, "w1:p3", [], {"panes": []}))

    def test_read_focus_trail(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = an.FOCUS_LOG
            an.FOCUS_LOG = os.path.join(tmp, "focus.log")
            try:
                self.assertEqual(an.read_focus_trail("w1"), [])             # sin archivo
                with open(an.FOCUS_LOG, "w", encoding="utf-8") as f:
                    f.write("w1 w1:p1\nw2 w2:p1\nw1 w1:p2\nw1 w1:p1\nbasura\n")
                self.assertEqual(an.read_focus_trail("w1"), ["w1:p1", "w1:p2"])  # reciente primero, sin repetir
                self.assertEqual(an.read_focus_trail("w3"), [])
            finally:
                an.FOCUS_LOG = old


class Diario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (an.JOURNAL_DIR, an.CLAUDE_PROJECTS)
        an.JOURNAL_DIR = os.path.join(self.tmp.name, "journal")
        an.CLAUDE_PROJECTS = os.path.join(self.tmp.name, "projects")
        os.makedirs(an.JOURNAL_DIR)
        os.makedirs(an.CLAUDE_PROJECTS)
        an._claude_project_dirs.cache_clear()

    def tearDown(self):
        an.JOURNAL_DIR, an.CLAUDE_PROJECTS = self.old
        an._claude_project_dirs.cache_clear()
        self.tmp.cleanup()

    def _journal(self, day, lines):
        with open(os.path.join(an.JOURNAL_DIR, day + ".log"), "w", encoding="utf-8") as f:
            f.write("\n".join("\t".join(x) for x in lines) + "\n")

    def _conv(self, path, *sids):
        d = os.path.join(an.CLAUDE_PROJECTS, an.claude_project_key(path))
        os.makedirs(d, exist_ok=True)
        for s in sids:
            open(os.path.join(d, s + ".jsonl"), "w").close()
        an._claude_project_dirs.cache_clear()

    def test_read_journal_tolera_lineas_cortas_y_bom(self):
        with open(os.path.join(an.JOURNAL_DIR, "2026-10-30.log"), "w", encoding="utf-8-sig") as f:
            f.write("10:00:00\tC:\\P\tabc\tprompt\thola\tcon\ttabs\n")
            f.write("basura\n")
            f.write("10:00:05\tC:\\P\tabc\tstop\n")
        e = an.read_journal("2026-10-30")
        self.assertEqual(len(e), 2)
        self.assertEqual(e[0]["text"], "hola\tcon\ttabs")
        self.assertEqual(e[1], {"time": "10:00:05", "cwd": "C:\\P", "sid": "abc", "event": "stop", "text": ""})
        self.assertEqual(an.read_journal("1999-01-01"), [])

    def test_has_conversation_y_last_herdr_session(self):
        path = "C:\\Proyectos\\Uno"
        self.assertFalse(an.has_conversation(path))
        self.assertIsNone(an.last_herdr_session(path))
        self._conv(path, "11111111-aaaa", "22222222-bbbb")
        self.assertTrue(an.has_conversation(path.lower()))
        self._journal("2026-10-29", [("09:00:00", path, "11111111", "prompt", "viejo")])
        self._journal("2026-10-30", [("10:00:00", path, "22222222", "prompt", "nuevo"),
                                     ("10:05:00", "C:\\Otro", "33333333", "prompt", "ajeno"),
                                     ("10:06:00", path, "99999999", "stop", "borrada por claude")])
        self.assertEqual(an.last_herdr_session(path), "22222222-bbbb")           # la última con .jsonl vivo
        self.assertEqual(an.last_herdr_session(path, exclude=["22222222-BBBB"]), "11111111-aaaa")
        self.assertIsNone(an.last_herdr_session(path, exclude=["22222222-bbbb", "11111111-aaaa"]))

    def test_secs_y_fmt_dur(self):
        self.assertEqual(an._secs("01:02:03"), 3723)
        self.assertIsNone(an._secs("x"))
        self.assertEqual(an._fmt_dur(59), "59 s")
        self.assertEqual(an._fmt_dur(3599), "59 min")
        self.assertEqual(an._fmt_dur(3723), "1 h 02 min")


class Herdr(unittest.TestCase):
    def test_field(self):
        self.assertEqual(an.field({"pane": {"pane_id": "w1:p2"}}, "pane", "pane_id"), "w1:p2")
        with self.assertRaises(an.AgentNavError):
            an.field({"pane": []}, "pane", "pane_id")

    def test_ver_tuple(self):
        self.assertEqual(an._ver_tuple("herdr 0.9.5"), (0, 9, 5))
        self.assertEqual(an._ver_tuple("agentnav-v0.10.0"), (0, 10, 0))
        self.assertGreater(an._ver_tuple("0.10.0"), an._ver_tuple("0.9.5"))
        self.assertEqual(an._ver_tuple(None), ())

    def test_parse_sha256_file(self):
        h = "a" * 63 + "F"
        self.assertEqual(an.parse_sha256_file(f"{h}  herdr.exe\n"), h.lower())
        self.assertEqual(an.parse_sha256_file(h.upper()), h.lower())
        self.assertEqual(an.parse_sha256_file(f"\ufeff {h} *herdr.exe"), h.lower())
        for bad in ("", "abc", "x" * 64, f"herdr.exe {h}"):
            with self.assertRaises(an.AgentNavError, msg=repr(bad)):
                an.parse_sha256_file(bad)

    def test_fork_sync_state(self):
        a, b = "1" * 64, "2" * 64
        self.assertEqual(an.fork_sync_state("0.9.5", a, "0.9.5", a), "al_dia")
        self.assertEqual(an.fork_sync_state("0.9.5", a, "0.9.5", a.upper()), "al_dia")
        self.assertEqual(an.fork_sync_state("0.9.5", a, "0.9.5", b), "rebuild")
        self.assertEqual(an.fork_sync_state("0.9.5", a, "0.10.0", b), "version_nueva")
        self.assertEqual(an.fork_sync_state("0.10.0", a, "0.9.5", b), "fork_atrasado")
        self.assertEqual(an.fork_sync_state("", "", "0.9.5", b), "version_nueva")  # sin exe instalado: hay que bajarlo

    def test_find_ws_y_agent_present(self):
        snap = {"workspaces": [{"workspace_id": "w1", "label": "MiniZelda"}, {"workspace_id": "w2"}]}
        self.assertEqual(an.find_ws(snap, "minizelda")["workspace_id"], "w1")
        self.assertIsNone(an.find_ws(snap, "x"))
        live = [{"agent": "claude", "name": "qa-2"}, {"agent": "shell", "name": "web"}]
        self.assertTrue(an._agent_present(live, "QA", "claude"))
        self.assertFalse(an._agent_present(live, "web", "claude"))
        self.assertFalse(an._agent_present(live, "qa-2x", "claude"))


class Temas(unittest.TestCase):
    CFG = '# arriba\n[terminal]\ndefault_shell = "pwsh"\n\n[theme]\nname = "nord"\nauto_switch = true\n\n[theme.custom]\naccent = "#111111"\n\n[keys]\nprefix = "ctrl+b"\n'

    def test_theme_sections_y_current(self):
        before, mine, after = an._theme_sections(self.CFG)
        self.assertTrue(before.startswith("# arriba") and before.endswith('default_shell = "pwsh"\n\n'))
        self.assertTrue(mine.startswith("[theme]") and "[theme.custom]" in mine)
        self.assertTrue(after.startswith("[keys]"))
        self.assertEqual(before + mine + after, self.CFG)
        self.assertEqual(an.current_theme(self.CFG), ("nord", {"accent": "#111111"}))
        self.assertEqual(an.current_theme("[theme]\nname = \"dracula\"\n")[0], "dracula")
        self.assertEqual(an.current_theme("")[0], "catppuccin")

    def test_render_theme_block(self):
        _, mine, _ = an._theme_sections(self.CFG)
        out = an.render_theme_block("terminal", {"accent": "#00ff00", "zzz": "ignorada"}, "matrix", mine)
        self.assertIn('name = "terminal"', out)
        self.assertIn("auto_switch = true", out)      # lo ajeno se conserva
        self.assertNotIn('name = "nord"', out)
        self.assertIn('accent = "#00ff00"', out)
        self.assertNotIn("zzz", out)                  # sólo tokens conocidos
        self.assertEqual(out.count("[theme.custom]"), 1)
        self.assertNotIn("[theme.custom]", an.render_theme_block("matrix", {}, "matrix", mine))


class EtiquetaPanel(unittest.TestCase):
    def test_pane_title_arma_la_orden_y_nunca_falla(self):
        calls = []
        orig = an.run
        an.run = lambda *a, **k: calls.append(a) or (0, "", "")
        try:
            an.pane_title("w1:p2", "qa · arreglar el login")
            an.pane_title("w1:p2", "")
            self.assertEqual(calls[0], ("pane", "report-metadata", "w1:p2", "--source", "agentnav", "--title", "qa · arreglar el login"))
            self.assertEqual(calls[1], ("pane", "report-metadata", "w1:p2", "--source", "agentnav", "--clear-title"))
            self.assertNotIn("--title=", " ".join(calls[0]))  # Herdr no acepta esa forma
            an.run = lambda *a, **k: (_ for _ in ()).throw(OSError("herdr caído"))
            an.pane_title("w1:p2", "x")  # se traga el error: la etiqueta nunca frena un arranque
        finally:
            an.run = orig


class EtiquetaTodos(unittest.TestCase):
    def test_agent_label(self):
        a = {"name": "qa-2", "agent": "claude", "terminal_title_stripped": "Arreglar el login"}
        self.assertEqual(an.agent_label(a), "qa-2 · Arreglar el login")
        self.assertEqual(an.agent_label({"agent": "claude", "terminal_title_stripped": "Claude Code"}, "hola\nmundo"), "claude · hola mundo")
        self.assertEqual(an.agent_label({"name": "qa", "terminal_title_stripped": ""}), "qa")
        self.assertEqual(an.agent_label({"name": "qa"}, "usá el token ghp_abcdefghijklmnop"), "qa")
        self.assertEqual(an.agent_label({"name": "qa"}, 'di "hola"'), "qa · di 'hola'")
        largo = an.agent_label({"name": "qa", "terminal_title_stripped": "x" * 80})
        self.assertEqual(len(largo), len("qa · ") + 60)
        self.assertTrue(largo.endswith("…"))

    def test_label_agents_usa_agent_list_y_marca_working(self):
        calls = []
        orig_api, orig_run, orig_state = an.api, an.run, an.STATE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "working"))
            with open(os.path.join(tmp, "working", "sid-1"), "w", encoding="utf-8") as f:
                f.write("revisá el tren")
            an.STATE_DIR = tmp
            an.api = lambda *a, **k: {"agents": [
                {"name": "qa", "pane_id": "w1:p1", "terminal_title_stripped": "Claude Code", "agent_session": {"value": "sid-1"}},
                {"agent": "claude", "pane_id": "w1:p2", "terminal_title_stripped": "Mapa nuevo"},
                {"name": "sin-panel"}]}
            an.run = lambda *a, **k: calls.append(a) or (0, "", "")
            try:
                self.assertEqual(an.label_agents(say=lambda *_: None), 0)
            finally:
                an.api, an.run, an.STATE_DIR = orig_api, orig_run, orig_state
        self.assertEqual([c[2:] for c in calls], [("w1:p1", "--source", "agentnav", "--title", "qa · revisá el tren"),
                                                  ("w1:p2", "--source", "agentnav", "--title", "claude · Mapa nuevo")])


class AvisoDeUpdate(unittest.TestCase):
    AL_DIA = {"sha": "abc1234", "branch": "main", "upstream": "origin/main", "dirty": False, "ahead": 0, "behind": 0,
              "fetch_error": None}

    def test_sin_aviso_al_dia_sin_red_sin_upstream_o_con_error(self):
        self.assertIsNone(an.update_notice(self.AL_DIA))
        self.assertIsNone(an.update_notice(dict(self.AL_DIA, behind=3, fetch_error="fatal: sin red")))
        self.assertIsNone(an.update_notice(dict(self.AL_DIA, behind=3, upstream=None)))
        self.assertIsNone(an.update_notice(an.AgentNavError("no es un clon")))
        self.assertIsNone(an.update_notice(None))

    def test_aviso_cuenta_commits_y_dice_que_hacer(self):
        title, body = an.update_notice(dict(self.AL_DIA, behind=1))
        self.assertEqual(title, "AgentNav: 1 commit nuevo en origin/main")
        self.assertIn("agentnav update", body)
        title, body = an.update_notice(dict(self.AL_DIA, behind=4))
        self.assertEqual(title, "AgentNav: 4 commits nuevos en origin/main")

    def test_aviso_con_cambios_locales_o_commits_sin_pushear(self):
        _, body = an.update_notice(dict(self.AL_DIA, behind=2, dirty=True))
        self.assertIn("sin commitear", body)
        _, body = an.update_notice(dict(self.AL_DIA, behind=2, ahead=1))
        self.assertIn("sin pushear", body)

    def test_notify_muestra_notificacion_de_herdr_solo_si_hay_nuevos(self):
        calls, said = [], []
        orig_run = an.run
        an.run = lambda *a, **k: calls.append(a) or (0, "", "")

        class Hilo:
            def __init__(self, result):
                self.result = result

            def join(self, timeout=None):
                pass

        try:
            self.assertFalse(an.notify_update_available(Hilo(self.AL_DIA), say=said.append))
            self.assertFalse(an.notify_update_available(Hilo(an.AgentNavError("sin git")), say=said.append))
            self.assertFalse(an.notify_update_available(Hilo(None), say=said.append))
            self.assertEqual(calls, [])
            self.assertTrue(an.notify_update_available(Hilo(dict(self.AL_DIA, behind=2)), say=said.append))
        finally:
            an.run = orig_run
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ("notification", "show", "AgentNav: 2 commits nuevos en origin/main"))
        self.assertIn("--body", calls[0])
        self.assertTrue(any("al día" in s for s in said))


class Gemini(unittest.TestCase):
    """Gemini CLI como tipo de agente: new --kind, sesiones en ~/.gemini/tmp, continue, procesos, doctor."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.old = (an.JOURNAL_DIR, an.CLAUDE_PROJECTS, an.GEMINI_TMP, an.GEMINI_REGISTRY, an.PROJECTS_PATH, an._outside_agents,
                    an.RECENT_SKIP)
        an.RECENT_SKIP = ()  # el directorio temporal cae en AppData\\Local\\Temp
        an.JOURNAL_DIR = os.path.join(t, "journal")
        an.CLAUDE_PROJECTS = os.path.join(t, "claude-projects")
        an.GEMINI_TMP = os.path.join(t, "gemini", "tmp")
        an.GEMINI_REGISTRY = os.path.join(t, "gemini", "projects.json")
        an.PROJECTS_PATH = os.path.join(t, "projects.json")
        an._outside_agents = lambda path, kind: []
        for d in (an.JOURNAL_DIR, an.CLAUDE_PROJECTS, an.GEMINI_TMP):
            os.makedirs(d)
        self.proj = os.path.join(t, "Obra")
        os.makedirs(self.proj)
        an._claude_project_dirs.cache_clear()
        an._gemini_registry.cache_clear()

    def tearDown(self):
        (an.JOURNAL_DIR, an.CLAUDE_PROJECTS, an.GEMINI_TMP, an.GEMINI_REGISTRY, an.PROJECTS_PATH, an._outside_agents,
         an.RECENT_SKIP) = self.old
        an._claude_project_dirs.cache_clear()
        an._gemini_registry.cache_clear()
        self.tmp.cleanup()

    def _registry(self, slug, path=None):
        with open(an.GEMINI_REGISTRY, "w", encoding="utf-8") as f:
            json.dump({"projects": {an._gemini_norm(path or self.proj): slug}}, f)
        an._gemini_registry.cache_clear()
        d = os.path.join(an.GEMINI_TMP, slug)
        os.makedirs(os.path.join(d, "chats"), exist_ok=True)
        with open(os.path.join(d, ".project_root"), "w", encoding="utf-8") as f:
            f.write(an._gemini_norm(path or self.proj) + "\n")
        return d

    def _session(self, d, stamp, sid, age=0):
        name = f"session-{stamp}-{sid[:8]}.jsonl"
        p = os.path.join(d, "chats", name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": sid, "projectHash": "x", "startTime": stamp, "kind": "main"}) + "\n")
        os.utime(p, (time.time() - age, time.time() - age))
        return p

    def test_new_args(self):
        self.assertEqual(an._new_args(["Foo"]), ("Foo", "", "claude"))
        self.assertEqual(an._new_args(["Foo", "C:\\x y", "--gemini"]), ("Foo", "C:\\x y", "gemini"))
        self.assertEqual(an._new_args(["--kind", "Gemini", "Foo"]), ("Foo", "", "gemini"))
        self.assertEqual(an._new_args(["--kind=codex", "Foo"]), ("Foo", "", "codex"))
        for bad in (["--kind", "shell", "x"], ["--raro", "x"], [], ["--kind"]):
            with self.assertRaises(an.AgentNavError, msg=bad):
                an._new_args(bad)

    def test_add_project_kind(self):
        an.add_project("Obra", self.proj, "gemini")
        an.add_project("Otra", self.proj + "2")
        ps = an.load_projects()
        self.assertEqual([(p["name"], p["kind"], p["agents"][0]["kind"], p["agents"][0]["continue"]) for p in ps],
                         [("Obra", "gemini", "gemini", True), ("Otra", "claude", "claude", True)])

    def test_is_agent_proc(self):
        gem = {"pid": 2, "ppid": 1, "name": "node.exe",
               "cmd": 'node "C:\\Users\\p\\AppData\\Roaming\\npm\\node_modules\\@google\\gemini-cli\\bundle\\gemini.js" -r latest'}
        child = dict(gem, pid=3, ppid=2)  # Gemini se relanza a sí mismo (GEMINI_CLI_NO_RELAUNCH): el hijo no cuenta
        cla = {"pid": 4, "ppid": 1, "name": "claude.exe", "cmd": "claude --continue"}
        srv = {"pid": 5, "ppid": 1, "name": "node.exe", "cmd": "node C:\\x\\patapim-browser-server.js"}
        by = {p["pid"]: p for p in (gem, child, cla, srv)}
        self.assertTrue(an._is_agent_proc(gem, "gemini", by))
        self.assertFalse(an._is_agent_proc(child, "gemini", by))
        self.assertFalse(an._is_agent_proc(gem, "claude", by))
        self.assertTrue(an._is_agent_proc(cla, "claude", by))
        self.assertFalse(an._is_agent_proc(srv, "gemini", by))
        self.assertFalse(an._is_agent_proc(srv, "claude", by))

    def test_sessions_y_project_dir(self):
        self.assertEqual(an.gemini_sessions(self.proj), [])
        self.assertIsNone(an.gemini_project_dir(self.proj))
        d = self._registry("obra")
        self.assertEqual(an.gemini_project_dir(self.proj.upper()), d)       # el registro guarda minúsculas
        old = self._session(d, "2026-11-12T10-00-00", "aaaaaaaa-1111-2222-3333-444444444444", age=100)
        new = self._session(d, "2026-11-13T10-00-00", "bbbbbbbb-1111-2222-3333-444444444444")
        self.assertEqual(an.gemini_sessions(self.proj), [(new, "bbbbbbbb"), (old, "aaaaaaaa")])
        self.assertTrue(an.has_gemini_conversation(self.proj))
        self.assertEqual(an.gemini_session_file(self.proj, "AAAAAAAA-1111"), old)
        self.assertIsNone(an.gemini_session_file(self.proj, "cccccccc"))
        self.assertEqual(an._gemini_newest_sid(self.proj), "bbbbbbbb-1111-2222-3333-444444444444")
        # sin registro, por el .project_root
        os.remove(an.GEMINI_REGISTRY)
        an._gemini_registry.cache_clear()
        self.assertEqual(an.gemini_project_dir(self.proj), d)

    def test_recent_gemini(self):
        d = self._registry("obra")
        self._session(d, "2026-11-13T10-00-00", "bbbbbbbb-1111-2222-3333-444444444444")
        rs = an.recent_projects([], 5)
        self.assertEqual([(r["path"].lower(), r["kind"]) for r in rs], [(self.proj.lower(), "gemini")])
        self.assertEqual(an.recent_projects([{"path": self.proj}], 5), [])   # registrada: no sale
        # un tmp sin sesiones no cuenta
        self._registry("vacio", self.proj + "2")
        self.assertEqual(len(an.recent_projects([], 5)), 1)

    def test_last_herdr_session_gemini(self):
        d = self._registry("obra")
        self._session(d, "2026-11-12T10-00-00", "aaaaaaaa-1111-2222-3333-444444444444", age=100)
        self._session(d, "2026-11-13T10-00-00", "bbbbbbbb-1111-2222-3333-444444444444")
        with open(os.path.join(an.JOURNAL_DIR, "2026-11-13.log"), "w", encoding="utf-8") as f:  # el hook anota 8 del sid
            f.write("\t".join(("10:00:00", self.proj, "bbbbbbbb", "prompt", "hola")) + "\n")
            f.write("\t".join(("10:01:00", self.proj, "aaaaaaaa", "prompt", "otra")) + "\n")
            f.write("\t".join(("10:02:00", self.proj, "99999999", "prompt", "de claude")) + "\n")
        # la última con pedidos en Herdr que Gemini todavía guarde, con el uuid entero del archivo; la de Claude
        # (sin archivo de Gemini) se saltea
        self.assertEqual(an.last_herdr_session(self.proj, kind="gemini"), "aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(an.last_herdr_session(self.proj, exclude={"AAAAAAAA-1111-2222-3333-444444444444"}, kind="gemini"),
                         "bbbbbbbb-1111-2222-3333-444444444444")
        self.assertIsNone(an.last_herdr_session(self.proj, kind="claude"))   # Claude no tiene esa carpeta

    def test_gemini_continue_args(self):
        a = {"name": "g", "kind": "gemini", "continue": True, "args": []}
        said = []
        self.assertEqual(an._continue_args(a, self.proj, said.append, set(), False), [])   # sin sesiones: nada
        d = self._registry("obra")
        self._session(d, "2026-11-13T10-00-00", "bbbbbbbb-1111-2222-3333-444444444444")
        self.assertEqual(an._continue_args(a, self.proj, said.append, set(), False), ["--resume", "latest"])
        self.assertEqual(an._continue_args(a, self.proj, said.append, set(), True), [])   # otro Gemini del proyecto
        self.assertTrue(any("otro Gemini" in s for s in said))
        with open(os.path.join(an.JOURNAL_DIR, "2026-11-13.log"), "w", encoding="utf-8") as f:
            f.write("\t".join(("10:00:00", self.proj, "bbbbbbbb", "stop", "")) + "\n")
        used = set()
        self.assertEqual(an._continue_args(a, self.proj, said.append, used, True), ["--resume", "bbbbbbbb-1111-2222-3333-444444444444"])
        self.assertEqual(an._continue_args(a, self.proj, said.append, used, False), ["--resume", "latest"])  # ya usada
        # uno de afuera con esa sesión: no se retoma ni por id ni por latest
        an._outside_agents = lambda path, kind: [{"cmd": "node gemini.js --resume bbbbbbbb-1111-2222-3333-444444444444"}] if kind == "gemini" else []
        said.clear()
        self.assertEqual(an._continue_args(a, self.proj, said.append, set(), False), [])
        self.assertTrue(any("otra terminal" in s for s in said))
        self.assertEqual(an.sids_outside_herdr(self.proj, "gemini"), {"bbbbbbbb-1111-2222-3333-444444444444"})
        an._outside_agents = lambda path, kind: [{"cmd": "node gemini.js -r latest"}]
        self.assertEqual(an.sids_outside_herdr(self.proj, "gemini"), {"bbbbbbbb-1111-2222-3333-444444444444"})
        # un tipo que no sabemos retomar
        self.assertEqual(an._continue_args(dict(a, kind="codex"), self.proj, said.append, set(), False), [])

    def test_gemini_hook_status(self):
        cmd = 'powershell -NoProfile -File "C:\\u\\.claude\\hooks\\agentnav-state.ps1" {} gemini'
        hooks = {ev: [{"hooks": [{"type": "command", "command": cmd.format(ac)}]}]
                 for ev, ac in (("SessionStart", "start"), ("BeforeAgent", "prompt"), ("AfterAgent", "stop"),
                                ("SessionEnd", "end"), ("Notification", "notify"))}
        have, missing = an.gemini_hook_status({"hooks": hooks})
        self.assertEqual(missing, ["AfterTool"])
        hooks["AfterTool"] = [{"hooks": [{"type": "command", "command": '"C:\\u\\.claude\\hooks\\agentnav-unblock.cmd" gemini'}]}]
        self.assertEqual(an.gemini_hook_status({"hooks": hooks}), ([ev for ev, _ in an.GEMINI_HOOK_EVENTS], []))
        self.assertEqual(an.gemini_hook_status({})[0], [])
        self.assertEqual(an.gemini_hook_status({"hooks": {"BeforeAgent": [{"hooks": [{"command": cmd.format("prompt").replace(" gemini", "")}]}]}})[0], [])

    def test_agent_label_gemini(self):
        g = {"name": "gem", "agent": "gemini", "terminal_title_stripped": "Gemini CLI"}
        self.assertEqual(an.agent_label(g, "arreglá el build"), "gem · arreglá el build")
        self.assertEqual(an.agent_label(dict(g, terminal_title_stripped="C:\\Obra"), "arreglá el build"), "gem · arreglá el build")
        self.assertEqual(an.agent_label(dict(g, terminal_title_stripped="C:\\Obra"), ""), "gem · C:\\Obra")
        self.assertEqual(an.agent_label(g, ""), "gem")
        c = {"name": "obra", "agent": "claude", "terminal_title_stripped": "Arreglo del build"}
        self.assertEqual(an.agent_label(c, "otra cosa"), "obra · Arreglo del build")   # Claude: manda su título

    def test_exit_command(self):
        self.assertEqual(an.EXIT_COMMAND, {"claude": "/exit", "gemini": "/quit"})


if __name__ == "__main__":
    unittest.main()
