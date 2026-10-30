# AgentNav — reporta el estado real de Claude Code al panel de Herdr que lo aloja, lleva el diario y avisa al teléfono.
# Vive al lado de herdr-agent-state.ps1 (que Herdr gestiona y sólo reporta el id de sesión).
# Uso (desde ~/.claude/settings.json):  agentnav-state.ps1 prompt|stop|end|notify|unblock
#   prompt   UserPromptSubmit → working (mensaje = el pedido)      + diario + marca "working\<sid>"
#   notify   Notification     → blocked (permission_prompt) / idle  + marca "blocked\<sid>" + aviso ntfy
#   unblock  PostToolUse      → si había marca "blocked", vuelve a working (lo lanza agentnav-unblock.cmd sólo si hay marcas)
#   stop     Stop             → idle                                 + diario + aviso ntfy si el turno fue largo
#   end      SessionEnd       → release-agent                        + limpia marcas
# Siempre sale con 0: un hook que falla no debe molestar a Claude.
# Archivo guardado como UTF-8 CON BOM: PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252 y rompe los acentos.
# Límite conocido: Stop no dispara si interrumpís el turno con Esc, queda "working" hasta el idle_prompt (~60 s).

param([string]$Action = "")

if ($env:HERDR_ENV -ne "1") { exit 0 }
if ([string]::IsNullOrWhiteSpace($env:HERDR_PANE_ID)) { exit 0 }
if ($Action -notin @("prompt", "stop", "end", "notify", "unblock")) { exit 0 }

$AgentNavHome = "C:\AgentNav"

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

$sid = [string]$payload.session_id
if ([string]::IsNullOrWhiteSpace($sid)) { $sid = "sin-sesion" }
$sidShort = if ($sid.Length -gt 8) { $sid.Substring(0, 8) } else { $sid }
$sidFile = ($sid -replace '[^A-Za-z0-9_-]', '_')
$cwd = [string]$payload.cwd
$projectName = if ($cwd) { Split-Path -Leaf $cwd } else { "Claude" }

$stateDir = Join-Path $env:LOCALAPPDATA "AgentNav"
$workingDir = Join-Path $stateDir "working"
$blockedDir = Join-Path $stateDir "blocked"
$journalDir = Join-Path $stateDir "journal"
$workingFile = Join-Path $workingDir $sidFile
$blockedFile = Join-Path $blockedDir $sidFile
try { foreach ($d in @($stateDir, $workingDir, $blockedDir, $journalDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } } catch { }

function Read-Marker([string]$path) {
    try { if (Test-Path -LiteralPath $path) { return [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) } } catch { }
    return ""
}
function Write-Marker([string]$path, [string]$text) {
    try { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false))) } catch { }
}
function Remove-Marker([string]$path) {
    try { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } } catch { }
}
# Una sola bandera "blocked.flag" resume si hay marcas: agentnav-unblock.cmd la consulta con "if exist", que para una
# carpeta vacía con "\*" daría verdadero igual (el comodín matchea "." y "..") y lanzaría PowerShell en cada herramienta.
$blockedFlag = Join-Path $stateDir "blocked.flag"
function Sync-BlockedFlag() {
    try {
        $any = @(Get-ChildItem -LiteralPath $blockedDir -File -ErrorAction SilentlyContinue).Count -gt 0
        if ($any) { if (-not (Test-Path -LiteralPath $blockedFlag)) { [IO.File]::WriteAllText($blockedFlag, "") } }
        elseif (Test-Path -LiteralPath $blockedFlag) { Remove-Item -LiteralPath $blockedFlag -Force }
    } catch { }
}
function Elapsed-Seconds([string]$path) {
    try { if (Test-Path -LiteralPath $path) { return [int]((Get-Date) - (Get-Item -LiteralPath $path).LastWriteTime).TotalSeconds } } catch { }
    return -1
}
function Journal([string]$event, [string]$text) {
    try {
        $line = "{0}`t{1}`t{2}`t{3}`t{4}" -f (Get-Date -Format "HH:mm:ss"), $cwd, $sidShort, $event, (Clean-Message $text 300)
        $path = Join-Path $journalDir ((Get-Date -Format "yyyy-MM-dd") + ".log")
        [IO.File]::AppendAllText($path, $line + "`r`n", (New-Object Text.UTF8Encoding($false)))
    } catch { }
}
# Aviso al teléfono por ntfy (settings.json de AgentNav). Sólo si el turno llevaba al menos min_seconds.
function Notify-Phone([string]$title, [string]$body, [int]$elapsed) {
    try {
        $cfgPath = Join-Path $AgentNavHome "settings.json"
        if (-not (Test-Path -LiteralPath $cfgPath)) { return "" }
        $cfg = ([IO.File]::ReadAllText($cfgPath, [Text.Encoding]::UTF8) | ConvertFrom-Json).ntfy
        if ($null -eq $cfg -or [string]::IsNullOrWhiteSpace($cfg.topic)) { return "" }
        $min = 120
        if ($null -ne $cfg.min_seconds) { $min = [int]$cfg.min_seconds }
        if ($elapsed -lt $min) { return "" }
        $server = if ([string]::IsNullOrWhiteSpace($cfg.server)) { "https://ntfy.sh" } else { ([string]$cfg.server).TrimEnd("/") }
        $titleHdr = "=?UTF-8?B?" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($title)) + "?="
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        Invoke-RestMethod -Uri "$server/$($cfg.topic)" -Method Post -Body $bytes -ContentType "text/plain; charset=utf-8" `
            -Headers @{ "Title" = $titleHdr; "Tags" = "robot" } -TimeoutSec 5 | Out-Null
        return " ntfy=ok"
    } catch { return " ntfy=ERR " + ($_.Exception.Message -replace '\s+', ' ') }
}

$state = $null
$message = ""
$extra = ""
switch ($Action) {
    "prompt" {
        $state = "working"
        $full = [string]$payload.prompt
        $message = Clean-Message $full
        Write-Marker $workingFile $full
        Remove-Marker $blockedFile
        Journal "prompt" $full
    }
    "unblock" {
        if (-not (Test-Path -LiteralPath $blockedFile)) { exit 0 }
        Remove-Marker $blockedFile
        $state = "working"
        $message = Clean-Message (Read-Marker $workingFile)
    }
    "stop" {
        $state = "idle"
        $elapsed = Elapsed-Seconds $workingFile
        $extra = Notify-Phone "$projectName terminó" ("listo (" + [math]::Max($elapsed, 0) + " s): " + (Clean-Message (Read-Marker $workingFile) 160)) $elapsed
        Remove-Marker $workingFile
        Remove-Marker $blockedFile
        Journal "stop" ("$elapsed")
    }
    "notify" {
        $kind = [string]$payload.notification_type
        if ($kind -eq "permission_prompt") {
            $state = "blocked"
            $m = Clean-Message ([string]$payload.message) 70
            $message = if ($m) { "pide permiso: $m" } else { "pide permiso" }
            Write-Marker $blockedFile $message
            Journal "blocked" $message
            $extra = Notify-Phone "$projectName espera" $message (Elapsed-Seconds $workingFile)
        } elseif ($kind -eq "idle_prompt") {
            $state = "idle"
        } else { exit 0 }
    }
    "end" {
        $state = "release"
        Remove-Marker $workingFile
        Remove-Marker $blockedFile
        Journal "end" ""
        # Marcas de sesiones que murieron sin avisar.
        try { Get-ChildItem -LiteralPath $workingDir, $blockedDir -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-2) } | Remove-Item -Force } catch { }
    }
}
Sync-BlockedFlag

$seq = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$herdr = if ([string]::IsNullOrWhiteSpace($env:HERDR_BIN_PATH)) { "herdr" } else { $env:HERDR_BIN_PATH }
$logPath = Join-Path $stateDir "hook.log"
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
    $line = "{0} {1} sid={2} action={3} state={4} msg=""{5}"" -> {6}{7}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $env:HERDR_PANE_ID, $sidShort, $Action, $state, $message, $result, $extra
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    $lines = @(Get-Content -LiteralPath $logPath -Encoding UTF8)
    if ($lines.Count -gt 400) { Set-Content -LiteralPath $logPath -Value ($lines[-200..-1]) -Encoding UTF8 }
} catch { }
exit 0
