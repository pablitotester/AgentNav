# AgentNav E1 — reporta el estado real de Claude Code al panel de Herdr que lo aloja.
# Vive al lado de herdr-agent-state.ps1 (que Herdr gestiona y sólo reporta el id de sesión).
# Uso (desde ~/.claude/settings.json):  agentnav-state.ps1 prompt|stop|end|notify
# Siempre sale con 0: un hook que falla no debe molestar a Claude.
# Archivo guardado como UTF-8 CON BOM: PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252 y rompe los acentos.
# Límites conocidos (no son bugs del hook): Claude no avisa cuando se concede un permiso, así que "blocked"
# dura hasta el próximo Stop; y Stop no dispara si interrumpís el turno con Esc, queda "working" hasta el idle_prompt.

param([string]$Action = "")

if ($env:HERDR_ENV -ne "1") { exit 0 }
if ([string]::IsNullOrWhiteSpace($env:HERDR_PANE_ID)) { exit 0 }
if ($Action -notin @("prompt", "stop", "end", "notify")) { exit 0 }

$stdinReader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$inputText = $stdinReader.ReadToEnd()
try {
    $payload = if ([string]::IsNullOrWhiteSpace($inputText)) { $null } else { $inputText | ConvertFrom-Json }
} catch { exit 0 }
if ($null -eq $payload) { exit 0 }

# Subagentes no cambian el estado del panel.
$props = @($payload.PSObject.Properties.Name)
if (($props -ccontains "agent_id") -and -not [string]::IsNullOrWhiteSpace($payload.agent_id)) { exit 0 }

function Clean-Message([string]$text, [int]$max = 80) {
    if ([string]::IsNullOrWhiteSpace($text)) { return "" }
    $t = ($text -replace '[\r\n\t]+', ' ') -replace '"', "'"
    $t = $t.Trim()
    # [char]0x2026 = "…" sin depender de cómo lea el archivo PowerShell 5.1
    if ($t.Length -gt $max) { $t = $t.Substring(0, $max - 1) + [char]0x2026 }
    return $t
}

$state = $null
$message = ""
switch ($Action) {
    "prompt" {
        $state = "working"
        $message = Clean-Message ([string]$payload.prompt)
    }
    "stop" {
        $state = "idle"
    }
    "notify" {
        $kind = [string]$payload.notification_type
        if ($kind -eq "permission_prompt") {
            $state = "blocked"
            $m = Clean-Message ([string]$payload.message) 70
            $message = if ($m) { "pide permiso: $m" } else { "pide permiso" }
        } elseif ($kind -eq "idle_prompt") {
            $state = "idle"
        } else { exit 0 }
    }
    "end" {
        $state = "release"
    }
}

$seq = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$herdr = if ([string]::IsNullOrWhiteSpace($env:HERDR_BIN_PATH)) { "herdr" } else { $env:HERDR_BIN_PATH }
$logDir = Join-Path $env:LOCALAPPDATA "AgentNav"
$logPath = Join-Path $logDir "hook.log"
$result = ""
try {
    if ($state -eq "release") {
        $cli = @("pane", "release-agent", $env:HERDR_PANE_ID, "--source", "agentnav", "--agent", "claude", "--seq", "$seq")
    } else {
        $cli = @("pane", "report-agent", $env:HERDR_PANE_ID, "--source", "agentnav", "--agent", "claude", "--state", $state, "--seq", "$seq")
        # Un solo token "--message=texto": si el prompt empieza con "-" (p. ej. "--help"), separado se perdería el reporte.
        if ($message) { $cli += @("--message=$message") }
    }
    # Los errores de la CLI vienen por stderr como JSON; "$_" deja sólo el texto, sin el envoltorio de PowerShell.
    $result = ((& $herdr @cli 2>&1 | ForEach-Object { "$_" }) -join " ") -replace '\s+', ' '
    $result = $result.Trim()
    if ($result -match '"code":"pane_not_found"') { $result = "pane ya cerrado (ok)" }
    if ($result.Length -gt 160) { $result = $result.Substring(0, 160) }
} catch { $result = ("EXC " + $_.Exception.Message) -replace '\s+', ' ' }

# Traza mínima, una línea por evento. Se recorta a 200 cuando pasa de 400 para no reescribir el archivo en cada evento.
try {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $sid = [string]$payload.session_id
    if ($sid.Length -gt 8) { $sid = $sid.Substring(0, 8) }
    $line = "{0} {1} sid={2} action={3} state={4} msg=""{5}"" -> {6}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $env:HERDR_PANE_ID, $sid, $Action, $state, $message, $result
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    $lines = @(Get-Content -LiteralPath $logPath -Encoding UTF8)
    if ($lines.Count -gt 400) { Set-Content -LiteralPath $logPath -Value ($lines[-200..-1]) -Encoding UTF8 }
} catch { }
exit 0
