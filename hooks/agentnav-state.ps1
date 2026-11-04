# AgentNav — reporta el estado real de Claude Code al panel de Herdr que lo aloja, lleva el diario y avisa al teléfono.
# Vive al lado de herdr-agent-state.ps1 (que Herdr gestiona y sólo reporta el id de sesión).
# Uso (desde ~/.claude/settings.json):  agentnav-state.ps1 prompt|stop|end|notify|unblock
#   prompt   UserPromptSubmit → working (mensaje = el pedido)      + diario + marca "working\<sid>"
#   notify   Notification     → blocked (permission_prompt) / idle  + marca "blocked\<sid>" + aviso ntfy
#   unblock  PostToolUse      → si había marca "blocked", vuelve a working (agentnav-unblock.cmd sólo lo lanza si existe
#                               la marca de ESA sesión, por CLAUDE_CODE_SESSION_ID; blocked.flag es el respaldo sin env)
#   stop     Stop             → idle                                 + diario + aviso ntfy si el turno fue largo
# En prompt, stop y notify también pone la etiqueta del panel ("<agente> · <tarea>", ver Pane-Label); SessionEnd la borra.
#   end      SessionEnd       → release-agent                        + limpia marcas (no en /clear: el panel sigue vivo)
# Siempre sale con 0 y nunca escribe en stdout: un hook que falla no debe molestar a Claude.
# Archivo guardado como UTF-8 CON BOM: PowerShell 5.1 lee UTF-8 sin BOM como Windows-1252 y rompe los acentos.
# Usa API .NET en vez de cmdlets de proveedor (Test-Path, Get-ChildItem, Add-Content…): inicializar el proveedor
# cuesta ~35 ms por invocación y el hook corre en cada prompt.
# Límites conocidos (no son bugs del hook):
#   - Stop no dispara si interrumpís el turno con Esc: queda "working" hasta el idle_prompt (~60 s).
#   - Denegar un permiso no genera PostToolUse: queda "blocked" hasta el Stop de ese turno.

param([string]$Action = "")

if ($env:HERDR_ENV -ne "1") { exit 0 }
if ([string]::IsNullOrWhiteSpace($env:HERDR_PANE_ID)) { exit 0 }
if ($Action -notin @("prompt", "stop", "end", "notify", "unblock")) { exit 0 }

# El orden de los reportes lo decide el momento en que llegó el evento, no cuánto tardó el hook en procesarlo.
$seq = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$AgentNavHome = "C:\AgentNav"
$Utf8NoBom = New-Object Text.UTF8Encoding($false)

$stdinReader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$inputText = $stdinReader.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($inputText)) { exit 0 }

function Json-Field([string]$text, [string]$name) {
    # Campo string de primer nivel sin ConvertFrom-Json (~45 ms): alcanza para los ids y nombres de herramienta.
    $m = [regex]::Match($text, '"' + [regex]::Escape($name) + '"\s*:\s*"((?:[^"\\]|\\.)*)"')
    if (-not $m.Success) { return "" }
    $v = $m.Groups[1].Value
    if ($v -notmatch '\\') { return $v }
    try { return ([string]('"' + $v + '"' | ConvertFrom-Json)) } catch { return "" }
}

$payload = $null
if ($Action -ne "unblock") {
    try { $payload = $inputText | ConvertFrom-Json } catch { exit 0 }
    if ($null -eq $payload) { exit 0 }
}

if ($payload) {
    $sid = [string]$payload.session_id
    $agentId = if ($payload.PSObject.Properties.Name -ccontains "agent_id") { [string]$payload.agent_id } else { "" }
} else {
    $sid = Json-Field $inputText "session_id"
    $agentId = Json-Field $inputText "agent_id"
}
# Un subagente no cambia el estado del panel con sus prompts ni sus Stop; su PostToolUse sí desbloquea (el permiso
# pudo pedirlo una herramienta suya) y su SessionEnd no existe.
if ($Action -in @("prompt", "stop") -and $agentId) { exit 0 }

function Clean-Message([string]$text, [int]$max = 80) {
    if ([string]::IsNullOrWhiteSpace($text)) { return "" }
    # Controles (ESC, BEL, NUL, tabs, saltos) y separadores Unicode fuera: van a una línea de comandos, al log y al diario.
    $t = ($text -replace '[\p{Cc}\u2028\u2029]+', ' ') -replace '"', "'"
    $t = $t.Trim()
    if ($t.Length -gt $max) {
        $cut = $max - 1
        if ([char]::IsHighSurrogate($t[$cut - 1])) { $cut-- }  # no partir un emoji
        $t = $t.Substring(0, $cut) + [char]0x2026  # "…" sin depender de cómo lea el archivo PowerShell 5.1
    }
    return $t
}

if ([string]::IsNullOrWhiteSpace($sid)) { $sid = "sin-sesion" }
$sidShort = if ($sid.Length -gt 8) { $sid.Substring(0, 8) } else { $sid }
$sidFile = ($sid -replace '[^A-Za-z0-9_-]', '_')
$cwd = if ($payload) { [string]$payload.cwd } else { "" }
$projectName = if ($cwd) { [IO.Path]::GetFileName($cwd.TrimEnd('\', '/')) } else { "Claude" }
if (-not $projectName) { $projectName = "Claude" }

# [IO.Path]::Combine y no Join-Path: el cmdlet cuesta ~3 ms por llamada en PowerShell 5.1.
$stateDir = [IO.Path]::Combine($env:LOCALAPPDATA, "AgentNav")
$workingDir = [IO.Path]::Combine($stateDir, "working")
$blockedDir = [IO.Path]::Combine($stateDir, "blocked")
$journalDir = [IO.Path]::Combine($stateDir, "journal")
$workingFile = [IO.Path]::Combine($workingDir, $sidFile)
$blockedFile = [IO.Path]::Combine($blockedDir, $sidFile)
$blockedFlag = [IO.Path]::Combine($stateDir, "blocked.flag")
try { foreach ($d in @($workingDir, $blockedDir, $journalDir)) { [IO.Directory]::CreateDirectory($d) | Out-Null } } catch { }

function Read-Marker([string]$path) {
    try { if ([IO.File]::Exists($path)) { return [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) } } catch { }
    return ""
}
function Write-Marker([string]$path, [string]$text) {
    try { [IO.File]::WriteAllText($path, $text, $Utf8NoBom) } catch { }
}
function Remove-Marker([string]$path) {
    try { if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) } } catch { }
}
function Elapsed-Seconds([string]$path) {
    try { if ([IO.File]::Exists($path)) { return [int]([DateTime]::Now - [IO.File]::GetLastWriteTime($path)).TotalSeconds } } catch { }
    return -1
}
function With-JournalLock([scriptblock]$body) {
    # Varios hooks pueden escribir a la vez (dos paneles, prompt + stop). FileMode.Append NO es atómico entre procesos
    # en .NET Framework: cada handle escribe en su propio puntero y se pisan (medido: 4 procesos × 400 líneas, 28 %
    # perdidas). Mutex con nombre, ~0,1 ms; si no se consigue en 500 ms se escribe igual.
    $mx = $null
    try {
        $mx = New-Object Threading.Mutex($false, "Local\AgentNavJournal")
        [void]$mx.WaitOne(500)
        & $body
    } catch { } finally { if ($mx) { try { $mx.ReleaseMutex() } catch { }; $mx.Dispose() } }
}
function Append-Line([string]$path, [string]$line) {
    With-JournalLock {
        for ($i = 0; $i -lt 3; $i++) {
            try {
                $fs = [IO.FileStream]::new($path, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
                try { $b = $Utf8NoBom.GetBytes($line + "`r`n"); $fs.Write($b, 0, $b.Length) } finally { $fs.Dispose() }
                return
            } catch { Start-Sleep -Milliseconds 10 }
        }
    }
}
function Prune-Journal {
    # El diario guarda cada pedido en texto plano: se conserva journal_days días (settings.json; 90 por defecto, 0 = siempre).
    # Sólo en SessionEnd, que es raro y no lo espera nadie. Se decide por la fecha del nombre (yyyy-MM-dd.log).
    try {
        $days = 90
        $cfgPath = [IO.Path]::Combine($AgentNavHome, "settings.json")
        if ([IO.File]::Exists($cfgPath) -and ([IO.File]::ReadAllText($cfgPath, [Text.Encoding]::UTF8) -match '"journal_days"\s*:\s*(\d+)')) { $days = [int]$Matches[1] }
        if ($days -le 0) { return }
        $limit = [DateTime]::Today.AddDays(-$days).ToString("yyyy-MM-dd")
        foreach ($f in [IO.Directory]::GetFiles($journalDir, "????-??-??.log")) {
            if ([IO.Path]::GetFileNameWithoutExtension($f) -lt $limit) { [IO.File]::Delete($f) }
        }
    } catch { }
}
function Prune-Markers([int]$hours = 12) {
    # Sesiones que murieron sin SessionEnd (panel cerrado, proceso matado) dejan marcas; se podan en cada evento, ~1 ms.
    try {
        $limit = [DateTime]::Now.AddHours(-$hours)
        foreach ($d in @($workingDir, $blockedDir)) {
            foreach ($f in [IO.Directory]::GetFiles($d)) {
                if ([IO.File]::GetLastWriteTime($f) -lt $limit) { [IO.File]::Delete($f) }
            }
        }
    } catch { }
}
# blocked.flag = "hay alguna marca blocked". Lo consulta agentnav-unblock.cmd cuando no tiene CLAUDE_CODE_SESSION_ID.
# Mutex con nombre: sin él, dos hooks a la vez podían dejar una marca sin bandera (check-then-act).
function Sync-BlockedFlag() {
    $mx = $null
    try {
        $mx = New-Object Threading.Mutex($false, "Local\AgentNavBlockedFlag")
        [void]$mx.WaitOne(500)
        $any = [IO.Directory]::GetFiles($blockedDir).Length -gt 0
        if ($any) { if (-not [IO.File]::Exists($blockedFlag)) { [IO.File]::WriteAllText($blockedFlag, "") } }
        elseif ([IO.File]::Exists($blockedFlag)) { [IO.File]::Delete($blockedFlag) }
    } catch { } finally { if ($mx) { try { $mx.ReleaseMutex() } catch { }; $mx.Dispose() } }
}
function Journal([string]$event, [string]$text) {
    try {
        $line = "{0}`t{1}`t{2}`t{3}`t{4}" -f [DateTime]::Now.ToString("HH:mm:ss"), $cwd, $sidShort, $event, (Clean-Message $text 300)
        Append-Line ([IO.Path]::Combine($journalDir, [DateTime]::Now.ToString("yyyy-MM-dd") + ".log")) $line
    } catch { }
}
# Aviso al teléfono por ntfy (settings.json de AgentNav). $kind "done" usa min_seconds (120), "blocked" min_seconds_blocked (0).
function Notify-Phone([string]$kind, [string]$title, [string]$body, [int]$elapsed) {
    try {
        $cfgPath = [IO.Path]::Combine($AgentNavHome, "settings.json")
        if (-not [IO.File]::Exists($cfgPath)) { return "" }
        $raw = [IO.File]::ReadAllText($cfgPath, [Text.Encoding]::UTF8)
        if ($raw -notmatch '"topic"\s*:\s*"[^"]+"') { return "" }  # apagado: ni se parsea el JSON
        $cfg = ($raw | ConvertFrom-Json).ntfy
        if ($null -eq $cfg -or [string]::IsNullOrWhiteSpace($cfg.topic)) { return "" }
        $min = if ($kind -eq "blocked") { 0 } else { 120 }
        if ($kind -eq "blocked" -and $null -ne $cfg.min_seconds_blocked) { $min = [int]$cfg.min_seconds_blocked }
        elseif ($kind -ne "blocked" -and $null -ne $cfg.min_seconds) { $min = [int]$cfg.min_seconds }
        if ($elapsed -lt $min) { return "" }
        $server = if ([string]::IsNullOrWhiteSpace($cfg.server)) { "https://ntfy.sh" } else { ([string]$cfg.server).TrimEnd("/") }
        [Net.ServicePointManager]::Expect100Continue = $false
        $req = [Net.HttpWebRequest]::Create("$server/$($cfg.topic)")
        $req.Method = "POST"; $req.Proxy = $null; $req.Timeout = 2000; $req.ReadWriteTimeout = 2000
        $req.ContentType = "text/plain; charset=utf-8"
        $req.Headers.Add("Title", "=?UTF-8?B?" + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($title)) + "?=")
        $req.Headers.Add("Tags", "robot")
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        $req.ContentLength = $bytes.Length
        $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
        $resp = $req.GetResponse(); $resp.Close()
        return " ntfy=ok"
    } catch { return " ntfy=ERR " + ($_.Exception.Message -replace '\s+', ' ') }
}
function Invoke-Herdr([string[]]$cli) {
    # herdr con tope de 4 s: si el servidor está colgado, UserPromptSubmit no puede esperar los 10 s del hook.
    # Devuelve stdout+stderr crudos, o $null si venció el plazo.
    $herdr = if ([string]::IsNullOrWhiteSpace($env:HERDR_BIN_PATH)) { "herdr" } else { $env:HERDR_BIN_PATH }
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $herdr; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    # herdr escribe UTF-8; sin esto .NET lee con la página OEM y una ñ o un acento del título llegan como cajas.
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    # .NET Framework no tiene ArgumentList: se arma la línea con las reglas de CommandLineToArgvW.
    $quoted = foreach ($a in $cli) {
        if ($a -match '[\s"]' -or $a -eq "") {
            '"' + ($a -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
        } else { $a }
    }
    $psi.Arguments = ($quoted -join " ")
    $p = [Diagnostics.Process]::Start($psi)
    # Primero esperar, después leer: la salida de herdr es una línea corta y entra en el buffer del pipe.
    # Leer en async costaría ~35 ms más (arranque del thread pool) en cada evento.
    if (-not $p.WaitForExit(4000)) {
        try { $p.Kill() } catch { }
        return $null  # sin leer los pipes: un hijo del proceso matado podría tenerlos abiertos
    }
    return $p.StandardOutput.ReadToEnd() + " " + $p.StandardError.ReadToEnd()
}
function Report-Herdr([string[]]$cli) {
    $raw = Invoke-Herdr $cli
    if ($null -eq $raw) { return "TIMEOUT herdr" }
    $r = ($raw -replace '\s+', ' ').Trim()
    if ($r -eq "") { return "" }  # report-metadata y pane run no imprimen nada cuando salen bien
    if ($r -match '"code":"pane_not_found"') { return "pane ya cerrado (ok)" }
    if ($r -match '"type":"(ok|pane_info|agent_reported|agent_released)"') { return "" }
    if ($r.Length -gt 160) { $r = $r.Substring(0, 160) }
    return $r
}
# Etiqueta del panel: "<agente> · <tarea>" en el borde superior (pane report-metadata --title; Herdr la recorta si no
# entra). El nombre es el que Herdr le dio al agente, el mismo de la barra lateral; la tarea es el título de terminal
# que Claude Code escribe solo a medida que avanza la conversación (terminal_title_stripped) y, mientras siga en
# "Claude Code" (conversación nueva), el principio del último pedido. Una llamada a `agent list` (~50 ms) y una al
# reporte; si Herdr todavía no detectó el agente, no se pone nada y el próximo evento lo hace.
function Pane-Label([string]$hint) {
    try {
        $raw = Invoke-Herdr @("agent", "list")
        if ([string]::IsNullOrWhiteSpace($raw)) { return "" }
        $me = ($raw | ConvertFrom-Json).result.agents | Where-Object { $_.pane_id -eq $env:HERDR_PANE_ID } | Select-Object -First 1
        if ($null -eq $me) { return "" }  # Herdr no ve agente en este panel (todavía, o ya no): no se toca nada
        $name = [string]$me.name
        if (-not $name) { $name = [string]$me.agent }
        $task = [string]$me.terminal_title_stripped
        if (-not $task -or $task -eq "Claude Code") { $task = $hint }
        # El borde se ve en cualquier captura: un pedido que traiga algo con pinta de clave no va.
        if ($task -match '(?i)(gh[pousr]_[A-Za-z0-9]|sk-[A-Za-z0-9_-]{8}|xox[abp]-|AKIA[0-9A-Z]{8}|bearer\s+\S{8}|eyJ[A-Za-z0-9_-]{10,}|[A-Fa-f0-9]{32,}|-----BEGIN|authorization\s*:|(password|passwd|contrase.a|token|secret|api[_-]?key)\s*[=:])') { $task = "" }
        $task = Clean-Message $task 60
        $title = if ($task) { "$name " + [char]0xB7 + " $task" } else { $name }
        # Herdr no entiende "--title=texto"; el título empieza por el nombre del agente (letra), nunca por "-".
        $r = Report-Herdr @("pane", "report-metadata", $env:HERDR_PANE_ID, "--source", "agentnav", "--title", $title)
        if ($r) { return " label: $r" }
        return ""
    } catch { return (" label EXC " + $_.Exception.Message) -replace '\s+', ' ' }
}

$state = $null
$message = ""
$extra = ""
$release = $false
$syncFlag = $false  # sólo cuando una marca blocked pudo aparecer o desaparecer: el prompt es el evento que espera el usuario
$taskHint = Clean-Message (Read-Marker $workingFile) 60  # último pedido, por si Claude aún no puso título a la conversación
switch ($Action) {
    "prompt" {
        $state = "working"
        $full = [string]$payload.prompt
        $message = Clean-Message $full
        $taskHint = Clean-Message $full 60
        Write-Marker $workingFile (Clean-Message $full 300)  # sólo lo que se muestra: un prompt puede traer claves
        if ([IO.File]::Exists($blockedFile)) { Remove-Marker $blockedFile; $syncFlag = $true }
        Journal "prompt" $full
    }
    "unblock" {
        if (-not [IO.File]::Exists($blockedFile)) { exit 0 }
        # Si Claude corre herramientas en paralelo, una de lectura puede terminar con el permiso aún abierto:
        # sólo desbloquea la herramienta que lo pidió (la marca guarda su nombre cuando la notificación lo trae).
        $tool = Json-Field $inputText "tool_name"
        $marked = Read-Marker $blockedFile
        if ($marked -match '^tool=(\S+)' -and $tool -and $Matches[1] -ne $tool) { exit 0 }
        Remove-Marker $blockedFile
        if (-not [IO.File]::Exists($workingFile)) { Sync-BlockedFlag; exit 0 }  # el Stop ya pasó: no revivir "working"
        $state = "working"
        $message = Clean-Message (Read-Marker $workingFile)
    }
    "stop" {
        $state = "idle"
        $elapsed = Elapsed-Seconds $workingFile
        $last = Clean-Message (Read-Marker $workingFile) 160
        Remove-Marker $workingFile
        Remove-Marker $blockedFile
        Journal "stop" ("$elapsed")
    }
    "notify" {
        $kind = [string]$payload.notification_type
        if ($kind -eq "permission_prompt") {
            $state = "blocked"
            $raw = [string]$payload.message
            $m = Clean-Message $raw 70
            $message = if ($m) { "pide permiso: $m" } else { "pide permiso" }
            $tool = if ($raw -match 'to use (\S+)') { $Matches[1] } else { "" }
            Write-Marker $blockedFile ("tool=$tool`n$message")
            Journal "blocked" $message
        } elseif ($kind -eq "idle_prompt") {
            $state = "idle"
            Remove-Marker $blockedFile  # Esc sobre un permiso no genera Stop: la marca quedaría para siempre
            Remove-Marker $workingFile
        } else { exit 0 }
    }
    "end" {
        $release = ([string]$payload.reason) -ne "clear"  # /clear reinicia la sesión en el mismo panel vivo
        Remove-Marker $workingFile
        Remove-Marker $blockedFile
        Journal "end" ([string]$payload.reason)
    }
}
if ($syncFlag -or $Action -ne "prompt") { Sync-BlockedFlag }
if ($Action -in @("stop", "end")) { Prune-Markers }  # fuera del camino del prompt, que es el que espera el usuario
if ($Action -eq "end") { Prune-Journal }

$result = ""
try {
    if ($Action -eq "end") {
        if ($release) {
            $result = Report-Herdr @("pane", "release-agent", $env:HERDR_PANE_ID, "--source", "agentnav", "--agent", "claude", "--seq", "$seq")
            $null = Report-Herdr @("pane", "report-metadata", $env:HERDR_PANE_ID, "--source", "agentnav", "--clear-title")
        }
    } else {
        $cli = @("pane", "report-agent", $env:HERDR_PANE_ID, "--source", "agentnav", "--agent", "claude", "--state", $state, "--seq", "$seq")
        # Un solo token "--message=texto": si el prompt empieza con "-" (p. ej. "--help"), separado se perdería el reporte.
        if ($message) { $cli += @("--message=$message") }
        $result = Report-Herdr $cli
        # La etiqueta va después del estado, no en unblock (corre por cada herramienta) y no si Herdr acaba de colgarse
        # (otros 4 s de espera pasarían el tope de 10 s del hook).
        if ($Action -ne "unblock" -and $result -ne "TIMEOUT herdr") { $extra += Pane-Label $taskHint }
    }
} catch { $result = ("EXC " + $_.Exception.Message) -replace '\s+', ' ' }

# El aviso al teléfono va después del reporte a Herdr: la red no puede retrasar el estado del panel.
if ($state -eq "blocked") { $extra += Notify-Phone "blocked" "$projectName espera" $message (Elapsed-Seconds $workingFile) }
elseif ($Action -eq "stop") { $extra += Notify-Phone "done" "$projectName terminó" ("listo (" + [math]::Max($elapsed, 0) + " s): " + $last) $elapsed }

# Traza mínima, una línea por evento. Se recorta a 200 líneas sólo cuando pasa de 100 KB.
try {
    $logPath = [IO.Path]::Combine($stateDir, "hook.log")
    $line = "{0} {1} sid={2} action={3} state={4} msg=""{5}"" -> {6}{7}" -f [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss"), $env:HERDR_PANE_ID, $sidShort, $Action, $state, $message, $result, $extra
    Append-Line $logPath $line
    if ([IO.File]::Exists($logPath) -and (New-Object IO.FileInfo($logPath)).Length -gt 100KB) {
        With-JournalLock {  # el recorte lee y reescribe: sin el lock se tragaba la línea que otro hook estaba agregando
            $lines = [IO.File]::ReadAllLines($logPath, [Text.Encoding]::UTF8)
            if ($lines.Length -gt 200) { [IO.File]::WriteAllLines($logPath, $lines[($lines.Length - 200)..($lines.Length - 1)], $Utf8NoBom) }
        }
    }
} catch { }
exit 0
