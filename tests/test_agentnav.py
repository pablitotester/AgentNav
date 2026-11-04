"""Tests de las funciones puras de agentnav.py: ni Herdr, ni red, ni procesos. Correr desde C:\\AgentNav:

    py -X utf8 -m unittest discover -s tests

Lo que toca disco va a carpetas temporales (JOURNAL_DIR, CLAUDE_PROJECTS se reemplazan en el módulo)."""
import os
import re
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
