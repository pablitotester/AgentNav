"""El hook de estado (hooks\\agentnav-state.ps1 + agentnav-unblock.cmd) corrido de verdad, con un herdr falso que anota
lo que le piden y con LOCALAPPDATA en una carpeta temporal: no toca el estado real ni habla con Herdr. Sólo en Windows.

    py -X utf8 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "agentnav-state.ps1")
UNBLOCK = os.path.join(ROOT, "hooks", "agentnav-unblock.cmd")
PANE = "t:p1"

FAKE_HERDR_PY = r'''
import json, os, sys
with open(os.environ["AN_FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
if sys.argv[1:2] == ["agent"]:
    print(open(os.environ["AN_FAKE_AGENTS"], encoding="utf-8").read())
elif sys.argv[1:3] != ["pane", "report-metadata"]:
    print('{"type":"agent_reported"}')
'''
AGENTS = {"result": {"agents": [
    {"pane_id": PANE, "name": "gem-1", "agent": "gemini", "terminal_title_stripped": "✦ demo"},
    {"pane_id": "t:p2", "name": "qa", "agent": "claude", "terminal_title_stripped": "Claude Code"}]}}


def _ntfy_on():
    try:
        with open(r"C:\AgentNav\settings.json", encoding="utf-8-sig") as f:
            return bool((json.load(f).get("ntfy") or {}).get("topic"))
    except (OSError, ValueError):
        return False


@unittest.skipUnless(sys.platform == "win32", "el hook es PowerShell 5.1")
class HookDeEstado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.log = os.path.join(d, "herdr.log")
        cls.state = os.path.join(d, "AgentNav")
        fake_py = os.path.join(d, "fake_herdr.py")
        fake_cmd = os.path.join(d, "herdr.cmd")
        agents = os.path.join(d, "agents.json")
        with open(fake_py, "w", encoding="utf-8") as f:
            f.write(FAKE_HERDR_PY)
        with open(fake_cmd, "w", encoding="ascii") as f:
            f.write(f'@py -X utf8 -I "{fake_py}" %*\r\n')
        with open(agents, "w", encoding="utf-8") as f:
            json.dump(AGENTS, f, ensure_ascii=False)
        cls.env = dict(os.environ, HERDR_ENV="1", HERDR_PANE_ID=PANE, HERDR_BIN_PATH=fake_cmd, LOCALAPPDATA=d,
                       AN_FAKE_LOG=cls.log, AN_FAKE_AGENTS=agents)
        cls.env.pop("CLAUDE_CODE_SESSION_ID", None)
        cls.env.pop("GEMINI_SESSION_ID", None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _calls(self):
        """Las llamadas a herdr desde la última vez que se miró."""
        try:
            with open(self.log, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            lines = []
        try:
            os.remove(self.log)
        except FileNotFoundError:
            pass
        return [json.loads(x) for x in lines if x.strip()]

    def _run(self, action, kind, payload, env=None, via_cmd=False):
        if via_cmd:
            cmd = [UNBLOCK] + ([kind] if kind else [])
        else:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", HOOK, action] + ([kind] if kind else [])
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        p = subprocess.run(cmd, input=data, capture_output=True, env=dict(self.env, **(env or {})), timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.assertEqual(p.stdout, b"", "el hook nunca escribe en stdout")
        return self._calls()

    def _marker(self, kind, sid):
        try:
            with open(os.path.join(self.state, kind, sid), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def _flag(self):
        return os.path.exists(os.path.join(self.state, "blocked.flag"))

    def _report(self, calls, state):
        """La llamada report-agent de `calls`, sin el --seq (varía)."""
        r = [c for c in calls if c[:2] == ["pane", "report-agent"]]
        self.assertEqual(len(r), 1, calls)
        c = r[0]
        i = c.index("--seq")
        self.assertTrue(c[i + 1].isdigit())
        del c[i:i + 2]
        self.assertEqual(c[:9], ["pane", "report-agent", PANE, "--source", "agentnav", "--agent", "gemini", "--state", state])
        return c[9:]

    def _title(self, calls):
        t = [c for c in calls if c[:2] == ["pane", "report-metadata"]]
        self.assertEqual(len(t), 1, calls)
        return t[0][5:]

    def test_vida_de_una_sesion_gemini(self):
        sid = "sid-g1"
        base = {"session_id": sid, "cwd": r"C:\proj\demo", "transcript_path": r"C:\proj\t.json", "timestamp": "2026-11-13T10:00:00Z"}
        # SessionStart: idle + id de sesión; sin pedido todavía, la etiqueta cae al título de la terminal
        calls = self._run("start", "gemini", dict(base, hook_event_name="SessionStart", source="startup"))
        self.assertEqual(self._report(calls, "idle"), ["--agent-session-id", sid, "--agent-session-path", r"C:\proj\t.json",
                                                       "--", "gemini", "--resume", sid])
        self.assertIn(["agent", "list"], calls)
        self.assertEqual(self._title(calls), ["--title", "gem-1 · ✦ demo"])
        # BeforeAgent: working con el pedido; la etiqueta lleva el pedido aunque el título de terminal diga otra cosa
        calls = self._run("prompt", "gemini", dict(base, hook_event_name="BeforeAgent", prompt="arreglá el login\ncon ñ"))
        self.assertEqual(self._report(calls, "working"), ["--message=arreglá el login con ñ"])
        self.assertEqual(self._title(calls), ["--title", "gem-1 · arreglá el login con ñ"])
        self.assertEqual(self._marker("working", sid), "arreglá el login con ñ")
        self.assertFalse(self._flag())
        # Notification ToolPermission: blocked, con la herramienta de details.tool_name
        calls = self._run("notify", "gemini", dict(base, hook_event_name="Notification", notification_type="ToolPermission",
                                                   message="Gemini wants to run a command", details={"tool_name": "run_shell_command"}))
        self.assertEqual(self._report(calls, "blocked"), ["--message=pide permiso: Gemini wants to run a command"])
        self.assertEqual(self._marker("blocked", sid), "tool=run_shell_command\npide permiso: Gemini wants to run a command")
        self.assertTrue(self._flag())
        # AfterTool de otra herramienta: no desbloquea
        calls = self._run("", "gemini", dict(base, hook_event_name="AfterTool", tool_name="write_file"),
                          env={"GEMINI_SESSION_ID": sid}, via_cmd=True)
        self.assertEqual(calls, [])
        self.assertTrue(self._flag())
        # AfterTool de la herramienta que pidió permiso: vuelve a working con el último pedido
        calls = self._run("", "gemini", dict(base, hook_event_name="AfterTool", tool_name="run_shell_command"),
                          env={"GEMINI_SESSION_ID": sid}, via_cmd=True)
        self.assertEqual(self._report(calls, "working"), ["--message=arreglá el login con ñ"])
        self.assertIsNone(self._marker("blocked", sid))
        self.assertFalse(self._flag())
        # AfterAgent: idle, sin marcas
        calls = self._run("stop", "gemini", dict(base, hook_event_name="AfterAgent", prompt="x", prompt_response="y", stop_hook_active=False))
        self.assertEqual(self._report(calls, "idle"), [])
        self.assertIsNone(self._marker("working", sid))
        # SessionEnd por /clear: el panel sigue vivo, no se libera; por salida: release + se borra la etiqueta
        calls = self._run("end", "gemini", dict(base, hook_event_name="SessionEnd", reason="clear"))
        self.assertEqual(calls, [])
        calls = self._run("end", "gemini", dict(base, hook_event_name="SessionEnd", reason="exit"))
        self.assertEqual([c[:7] for c in calls], [["pane", "release-agent", PANE, "--source", "agentnav", "--agent", "gemini"],
                                                   ["pane", "report-metadata", PANE, "--source", "agentnav", "--clear-title"]])
        # diario y traza
        journal_dir = os.path.join(self.state, "journal")
        text = "".join(open(os.path.join(journal_dir, n), encoding="utf-8").read() for n in os.listdir(journal_dir))
        self.assertIn("\tstart\tstartup", text)
        self.assertIn("\tprompt\tarreglá el login con ñ", text)
        self.assertIn("\tblocked\tpide permiso", text)
        self.assertIn("\tend\texit", text)
        with open(os.path.join(self.state, "hook.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("action=prompt/gemini state=working", log)
        self.assertIn("action=unblock/gemini", log)

    def test_claude_sigue_igual(self):
        base = {"session_id": "sid-c1", "cwd": r"C:\proj\demo", "hook_event_name": "UserPromptSubmit", "prompt": "hola"}
        calls = self._run("prompt", "", base)
        r = [c for c in calls if c[:2] == ["pane", "report-agent"]][0]
        self.assertEqual(r[5:9], ["--agent", "claude", "--state", "working"])
        with open(os.path.join(self.state, "hook.log"), encoding="utf-8") as f:
            self.assertIn("sid=sid-c1 action=prompt state=working", f.read())
        self._run("stop", "", dict(base, hook_event_name="Stop"))
        # un segundo argumento que no es un tipo de agente no hace nada
        self.assertEqual(self._run("prompt", "Gem ini", base), [])
        self.assertIsNone(self._marker("working", "sid-c1"))

    def test_resume_sobre_sesion_bloqueada_limpia_la_bandera(self):
        """Gemini matado con un permiso abierto y retomado con --resume (mismo sid): start borra la marca y la bandera."""
        sid = "sid-g2"
        base = {"session_id": sid, "cwd": r"C:\proj\demo"}
        self._run("prompt", "gemini", dict(base, hook_event_name="BeforeAgent", prompt="algo"))
        self._run("notify", "gemini", dict(base, hook_event_name="Notification", notification_type="ToolPermission", message="m"))
        self.assertTrue(self._flag())
        calls = self._run("start", "gemini", dict(base, hook_event_name="SessionStart", source="resume"))
        self.assertEqual(self._report(calls, "idle")[:2], ["--agent-session-id", sid])
        self.assertIsNone(self._marker("blocked", sid))
        self.assertIsNone(self._marker("working", sid))
        self.assertFalse(self._flag())

    @unittest.skipIf(_ntfy_on(), "settings.json tiene topic de ntfy: no se manda un aviso de prueba desde el test")
    def test_claude_permiso_sin_details(self):
        base = {"session_id": "sid-c2", "cwd": r"C:\proj\demo", "hook_event_name": "Notification",
                "notification_type": "permission_prompt", "message": "Claude needs your permission to use Bash"}
        self._run("prompt", "", dict(base, hook_event_name="UserPromptSubmit", prompt="hola"))
        self._run("notify", "", base)
        self.assertEqual(self._marker("blocked", "sid-c2"), "tool=Bash\npide permiso: Claude needs your permission to use Bash")
        self._run("stop", "", dict(base, hook_event_name="Stop"))


if __name__ == "__main__":
    unittest.main()
