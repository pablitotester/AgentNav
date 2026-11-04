"""Tests de las funciones puras de `agentnav update`: ni git, ni red, ni Herdr. Correr desde C:\\AgentNav:

    py -X utf8 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentnav as an  # noqa: E402


class AdelanteAtras(unittest.TestCase):
    def test_parse_ahead_behind(self):
        self.assertEqual(an.parse_ahead_behind("0\t3"), (0, 3))
        self.assertEqual(an.parse_ahead_behind("2\t0"), (2, 0))
        self.assertEqual(an.parse_ahead_behind(" 1 1\n"), (1, 1))  # espacios y salto final no molestan

    def test_parse_ahead_behind_basura(self):
        for bad in ("", None, "fatal: bad revision 'origin/main'", "3", "a\tb", "1\t2\t3"):
            with self.assertRaises(an.AgentNavError, msg=repr(bad)):
                an.parse_ahead_behind(bad)


class CopiasInstaladas(unittest.TestCase):
    def test_cuatro_pares_absolutos(self):
        pares = an.installed_copies()
        self.assertEqual(len(pares), 4)
        for src, dst in pares:
            self.assertTrue(os.path.isabs(src), src)
            self.assertTrue(os.path.isabs(dst), dst)
            self.assertTrue(src.startswith(an.HOME), src)  # el origen siempre vive en el repo
            self.assertFalse(dst.startswith(an.HOME), dst)  # el destino nunca
        nombres = [os.path.basename(dst) for _, dst in pares]
        self.assertEqual(nombres, ["agentnav-state.ps1", "agentnav-unblock.cmd", "Herdr server.vbs", "config.toml"])
        for src, _ in pares:
            self.assertTrue(os.path.isfile(src), f"falta en el repo: {src}")

    def test_sync_root_redirige_los_destinos(self):
        viejo = os.environ.get("AGENTNAV_SYNC_ROOT")
        with tempfile.TemporaryDirectory() as d:
            os.environ["AGENTNAV_SYNC_ROOT"] = d
            try:
                pares = an.installed_copies()
            finally:
                if viejo is None:
                    del os.environ["AGENTNAV_SYNC_ROOT"]
                else:
                    os.environ["AGENTNAV_SYNC_ROOT"] = viejo
        for src, dst in pares:
            self.assertTrue(dst.startswith(d), dst)  # nada apunta a la instalación real
            self.assertTrue(src.startswith(an.HOME), src)
        self.assertIn(os.path.join(".claude", "hooks"), pares[0][1])
        self.assertIn(os.path.join("AppData", "Roaming", "herdr", "config.toml"), pares[3][1])


class QueHacer(unittest.TestCase):
    def test_sin_check(self):
        self.assertEqual(an.update_action(dirty=False, ahead=0, behind=0), "al_dia")
        self.assertEqual(an.update_action(dirty=False, ahead=0, behind=3), "pull")
        self.assertEqual(an.update_action(dirty=True, ahead=0, behind=3), "sucio")  # hay que traer y el árbol está sucio
        self.assertEqual(an.update_action(dirty=True, ahead=0, behind=0), "al_dia")  # sucio sólo estorba al pull
        self.assertEqual(an.update_action(dirty=True, ahead=2, behind=0), "adelantado")
        self.assertEqual(an.update_action(dirty=True, ahead=2, behind=3), "sucio")
        self.assertEqual(an.update_action(dirty=False, ahead=2, behind=0), "adelantado")
        self.assertEqual(an.update_action(dirty=False, ahead=2, behind=3), "adelantado")  # divergido: tampoco hay pull

    def test_con_check_solo_informa(self):
        self.assertEqual(an.update_action(False, 0, 0, check=True), "al_dia")
        self.assertEqual(an.update_action(False, 0, 5, check=True), "nuevos")
        self.assertEqual(an.update_action(True, 2, 5, check=True), "nuevos")  # --check no se frena por sucio ni adelantado
        self.assertEqual(an.update_action(True, 2, 0, check=True), "al_dia")


REPO_CFG = '[general]\nx = 1\n\n[theme]\nname = "catppuccin"\n\n[keys]\nhelp = "prefix+f1"\n'


class ConfigConTema(unittest.TestCase):
    def test_conserva_el_tema_del_vivo(self):
        live = REPO_CFG.replace('name = "catppuccin"', 'name = "miami"')
        self.assertEqual(an.merge_config_keeping_theme(REPO_CFG, live), live)  # difiere sólo en el tema: queda igual
        repo2 = REPO_CFG.replace("x = 1", "x = 2")
        new = an.merge_config_keeping_theme(repo2, live)
        self.assertIn("x = 2", new)  # lo nuevo del repo entra
        self.assertIn('name = "miami"', new)  # el tema no se pisa
        self.assertNotIn("catppuccin", new)

    def test_conserva_theme_custom_y_sin_tema_en_el_vivo_usa_el_del_repo(self):
        live = REPO_CFG.replace('name = "catppuccin"\n', 'name = "catppuccin"\n\n[theme.custom]\naccent = "#ff00ff"\n')
        new = an.merge_config_keeping_theme(REPO_CFG.replace("x = 1", "x = 3"), live)
        self.assertIn('accent = "#ff00ff"', new)
        self.assertIn("x = 3", new)
        sin_tema = "[general]\nx = 9\n"
        self.assertEqual(an.merge_config_keeping_theme(REPO_CFG, sin_tema), REPO_CFG)

    def test_resultado_roto_no_pasa(self):
        with self.assertRaises(an.AgentNavError):
            an.merge_config_keeping_theme(REPO_CFG, '[theme]\nname = "sin cerrar\n')


if __name__ == "__main__":
    unittest.main()
