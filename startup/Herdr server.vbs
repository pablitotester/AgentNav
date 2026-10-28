' AgentNav E2 (2026-10-28): levanta el servidor de Herdr al iniciar sesión, sin ventana.
' Si ya corre, el segundo proceso termina solo. Para apagarlo: herdr server stop.
Set sh = CreateObject("WScript.Shell")
exe = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.herdr\packages\standalone\current\herdr.exe"
sh.Run """" & exe & """ server", 0, False
