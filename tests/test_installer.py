"""Tests de installer\\configurar.py (funciones puras + el main contra archivos temporales).

    py -X utf8 -m unittest discover -s tests
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("configurar", os.path.join(ROOT, "installer", "configurar.py"))
cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfg)

HOOKS = r"C:\Users\amigo\.claude\hooks"


def _main(argv):
    """configurar.main sin su salida por pantalla (informa al usuario del instalador, no al test)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return cfg.main(argv)


def _commands(settings, event):
    return [h["command"] for b in settings["hooks"][event] for h in b["hooks"]]


class HooksDeClaude(unittest.TestCase):
    def test_desde_cero(self):
        new, added = cfg.merge_claude_hooks(None, HOOKS)
        self.assertEqual(added, ["UserPromptSubmit", "Stop", "SessionEnd", "Notification", "PostToolUse"])
        self.assertEqual(_commands(new, "UserPromptSubmit"),
                         [f'powershell -NoProfile -ExecutionPolicy Bypass -File "{HOOKS}\\agentnav-state.ps1" prompt'])
        self.assertEqual(_commands(new, "PostToolUse"), [f'"{HOOKS}\\agentnav-unblock.cmd"'])
        self.assertEqual(new["hooks"]["Notification"][0]["matcher"], "permission_prompt|idle_prompt")
        self.assertNotIn("matcher", new["hooks"]["Stop"][0])
        for ev in new["hooks"]:
            for b in new["hooks"][ev]:
                for h in b["hooks"]:
                    self.assertEqual((h["type"], h["timeout"]), ("command", 10))

    def test_idempotente_y_respeta_lo_ajeno(self):
        base = {
            "model": "opus",
            "hooks": {
                "SessionStart": [{"matcher": "^(startup)$", "hooks": [{"type": "command", "command": "powershell -File \"x\\herdr-agent-state.ps1\" session"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "echo otro"}]}],
            },
        }
        once, added1 = cfg.merge_claude_hooks(base, HOOKS)
        twice, added2 = cfg.merge_claude_hooks(once, HOOKS)
        self.assertEqual(len(added1), 5)
        self.assertEqual(added2, [])
        self.assertEqual(once, twice)
        self.assertEqual(once["model"], "opus")
        self.assertEqual(len(once["hooks"]["SessionStart"]), 1)
        self.assertEqual(_commands(once, "Stop")[0], "echo otro")
        self.assertEqual(len(once["hooks"]["Stop"]), 2)
        # el de entrada no se muta
        self.assertEqual(len(base["hooks"]["Stop"]), 1)
        self.assertNotIn("UserPromptSubmit", base["hooks"])

    def test_como_lo_lee_doctor(self):
        """Mismo criterio que cmd_doctor: el comando contiene `agentnav-state.ps1" prompt`, etc."""
        new, _ = cfg.merge_claude_hooks({}, HOOKS)
        for ev, needle in (("UserPromptSubmit", 'agentnav-state.ps1" prompt'), ("Stop", 'agentnav-state.ps1" stop'),
                           ("SessionEnd", 'agentnav-state.ps1" end'), ("Notification", 'agentnav-state.ps1" notify'),
                           ("PostToolUse", "agentnav-unblock.cmd")):
            self.assertTrue(any(needle in c for c in _commands(new, ev)), ev)

    def test_hooks_roto_se_reemplaza(self):
        new, added = cfg.merge_claude_hooks({"hooks": "basura"}, HOOKS)
        self.assertEqual(len(added), 5)
        self.assertIsInstance(new["hooks"], dict)


class HooksDeGemini(unittest.TestCase):
    EVENTS = ["SessionStart", "BeforeAgent", "AfterAgent", "SessionEnd", "Notification", "AfterTool"]

    def test_desde_cero(self):
        new, added = cfg.merge_gemini_hooks(None, HOOKS)
        self.assertEqual(added, self.EVENTS)
        self.assertEqual(_commands(new, "BeforeAgent"),
                         [f'powershell -NoProfile -ExecutionPolicy Bypass -File "{HOOKS}\\agentnav-state.ps1" prompt gemini'])
        self.assertEqual(_commands(new, "SessionStart")[0].split('" ')[1], "start gemini")
        self.assertEqual(_commands(new, "AfterTool"), [f'"{HOOKS}\\agentnav-unblock.cmd" gemini'])
        for ev in self.EVENTS:
            self.assertNotIn("matcher", new["hooks"][ev][0], ev)  # ciclo de vida: matcher exacto, queremos todos
            h = new["hooks"][ev][0]["hooks"][0]
            self.assertEqual((h["type"], h["timeout"]), ("command", 10000), ev)  # Gemini cuenta en ms
            self.assertTrue(h["name"].startswith("agentnav-"), ev)
        self.assertEqual(new["hooks"]["AfterTool"][0]["hooks"][0]["name"], "agentnav-unblock")

    def test_idempotente_y_respeta_lo_ajeno(self):
        base = {
            "mcpServers": {"x": {"command": "node"}},
            "hooks": {"BeforeTool": [{"matcher": "write_file", "hooks": [{"type": "command", "command": "node otro.js"}]}],
                      "SessionEnd": [{"matcher": "exit", "hooks": [{"type": "command", "command": "echo chau"}]}]},
        }
        once, added1 = cfg.merge_gemini_hooks(base, HOOKS)
        twice, added2 = cfg.merge_gemini_hooks(once, HOOKS)
        self.assertEqual(len(added1), 6)
        self.assertEqual(added2, [])
        self.assertEqual(once, twice)
        self.assertEqual(once["mcpServers"], base["mcpServers"])
        self.assertEqual(_commands(once, "BeforeTool"), ["node otro.js"])
        self.assertEqual(_commands(once, "SessionEnd")[0], "echo chau")
        self.assertEqual(len(once["hooks"]["SessionEnd"]), 2)
        self.assertNotIn("BeforeAgent", base["hooks"])

    def test_claude_no_cambia(self):
        """El registro de Claude sigue sin el segundo argumento: lo que doctor y los settings ya instalados esperan."""
        new, _ = cfg.merge_claude_hooks({}, HOOKS)
        for ev in new["hooks"]:
            for c in _commands(new, ev):
                self.assertFalse(c.endswith(" claude"), c)
                self.assertNotIn("name", new["hooks"][ev][0]["hooks"][0])


class SettingsDeAgentNav(unittest.TestCase):
    EX = {"ntfy": {"topic": "", "server": "https://ntfy.sh"}, "journal_days": 90, "herdr_fork": {"repo": ""}}

    def test_crea_desde_ejemplo_con_fork(self):
        data, changed = cfg.ensure_agentnav_settings(None, self.EX, "pablitotester/herdr")
        self.assertTrue(changed)
        self.assertEqual(data["herdr_fork"]["repo"], "pablitotester/herdr")
        self.assertEqual(data["ntfy"]["topic"], "")
        self.assertEqual(self.EX["herdr_fork"]["repo"], "")

    def test_sin_fork(self):
        data, changed = cfg.ensure_agentnav_settings(None, self.EX, "")
        self.assertTrue(changed)
        self.assertEqual(data["herdr_fork"]["repo"], "")

    def test_existente_no_se_pisa(self):
        cur = {"ntfy": {"topic": "mio"}, "herdr_fork": {"repo": "otro/fork"}}
        data, changed = cfg.ensure_agentnav_settings(cur, self.EX, "pablitotester/herdr")
        self.assertFalse(changed)
        self.assertEqual(data, cur)

    def test_existente_sin_fork_se_completa(self):
        data, changed = cfg.ensure_agentnav_settings({"ntfy": {"topic": "mio"}}, self.EX, "pablitotester/herdr")
        self.assertTrue(changed)
        self.assertEqual(data["ntfy"]["topic"], "mio")
        self.assertEqual(data["herdr_fork"]["repo"], "pablitotester/herdr")


class MainConArchivos(unittest.TestCase):
    def test_claude_hooks_escribe_backup_y_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"permissions": {"allow": ["Bash(ñ)"]}}, f)
            self.assertEqual(_main(["claude-hooks", p, HOOKS]), 0)
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["permissions"]["allow"], ["Bash(ñ)"])
            self.assertEqual(len(data["hooks"]), 5)
            self.assertTrue(any(n.startswith("settings.json.bak-agentnav-") for n in os.listdir(d)))
            self.assertEqual(_main(["claude-hooks", p, HOOKS]), 0)

    def test_gemini_hooks_escribe_backup_y_respeta_mcp(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"mcpServers": {"ñandú": {"command": "node"}}, "hooks": {"BeforeTool": []}}, f)
            self.assertEqual(_main(["gemini-hooks", p, HOOKS]), 0)
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["mcpServers"]["ñandú"]["command"], "node")
            self.assertEqual(len(data["hooks"]), 7)
            self.assertTrue(any(n.startswith("settings.json.bak-agentnav-") for n in os.listdir(d)))
            self.assertEqual(_main(["gemini-hooks", p, HOOKS]), 0)
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.load(f), data)

    def test_json_invalido_no_se_toca(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{ roto")
            self.assertEqual(_main(["claude-hooks", p, HOOKS]), 2)
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), "{ roto")

    def test_agentnav_settings_guion_es_sin_fork(self):
        with tempfile.TemporaryDirectory() as d:
            ex = os.path.join(d, "settings.example.json")
            with open(ex, "w", encoding="utf-8") as f:
                json.dump(SettingsDeAgentNav.EX, f)
            p = os.path.join(d, "settings.json")
            self.assertEqual(_main(["agentnav-settings", p, ex, "-"]), 0)
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["herdr_fork"]["repo"], "")

    def test_sin_argumentos(self):
        self.assertEqual(_main([]), 1)


if __name__ == "__main__":
    unittest.main()
