' AgentNav (30/10): "Herdr como app". Lo apunta el acceso directo del escritorio.
' Corre `agentnav app` sin consola: levanta el servidor si hace falta (y repone los agentes),
' trae al frente la ventana de Windows Terminal que ya tiene Herdr, o abre una pestaña nueva.
Set sh = CreateObject("WScript.Shell")
sh.Run "py -I ""C:\AgentNav\agentnav.py"" app", 0, False
