<#
AgentNav: agente diario que mantiene el fork pablitotester/herdr (rama agentnav) rebasado sobre el último tag estable de
herdrdev/herdr, con su release compilado por GitHub Actions.

Lo corre la tarea programada "AgentNav Herdr upstream" (todos los días a las 03:40; si la PC estaba apagada, al prenderla).
1. Preflight sin Claude: actualiza el clon persistente, trae los tags de upstream y mira BASE_TAG, la última corrida del
   workflow y los assets del release. Si upstream no cambió, el build anduvo y el release está completo, termina ahí.
2. Si hay algo que hacer, lanza Claude Code sin interfaz (claude -p) con el prompt de upstream-agent.md, parado en el clon,
   con permisos sólo para git, gh y utilidades de lectura. Usa el gh y el git ya autenticados de esta PC.

A mano:
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\AgentNav\herdr-fork\upstream-agent.ps1            # corrida normal
    ... -Check          sólo el preflight (sale con 10 si el agente tendría trabajo)
    ... -ForzarAgente   lanza Claude aunque esté todo al día (para probar)
    ... -Model claude-opus-5-5   otro modelo (default claude-sonnet-5-5)

Clon:    %LOCALAPPDATA%\AgentNav\herdr-upstream\herdr
Token:   %LOCALAPPDATA%\AgentNav\herdr-upstream\claude-token.txt  (opcional: la salida de `claude setup-token`, para que el
         trabajo desatendido no dependa del login interactivo de claude.ai, que vence; sin el archivo usa ese login)
Log:     %LOCALAPPDATA%\AgentNav\herdr-upstream\upstream.log
Informe: %LOCALAPPDATA%\AgentNav\herdr-upstream\ultimo-informe.md  (la respuesta completa de la última corrida de Claude)
Salida: 0 = al día o agente terminado bien, 10 = hay trabajo (-Check), 1 = error del preflight o del agente.
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$ForzarAgente,
    [string]$Model = "claude-sonnet-5-5"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Este archivo tiene que ser UTF-8 CON BOM: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI y los acentos y rayas
# rompen el parser (una raya «—» en ANSI contiene una comilla tipográfica que cierra la cadena).
# La salida de Claude viene en UTF-8: que el log y el informe no la deformen.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$Repo = "pablitotester/herdr"
$UpstreamUrl = "https://github.com/herdrdev/herdr.git"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$claude = Join-Path $env:APPDATA "npm\claude.cmd"
$work = Join-Path $env:LOCALAPPDATA "AgentNav\herdr-upstream"
$clone = Join-Path $work "herdr"
$logFile = Join-Path $work "upstream.log"
$informe = Join-Path $work "ultimo-informe.md"
$promptFile = Join-Path $PSScriptRoot "upstream-agent.md"

New-Item -ItemType Directory -Force -Path $work | Out-Null

function Log([string]$m) {
    $line = "{0}  {1}" -f (Get-Date).ToString("s"), $m
    Write-Host $line
    try {
        if ((Test-Path -LiteralPath $logFile) -and (Get-Item -LiteralPath $logFile).Length -gt 512KB) {
            Move-Item -LiteralPath $logFile -Destination "$logFile.old" -Force
        }
        Add-Content -LiteralPath $logFile -Value $line
    } catch { }
}

# Ejecutable externo con stderr capturado como texto. Con $ErrorActionPreference = "Stop", cada línea que un programa
# escribe en stderr bajo 2>&1 sería un error terminante (git y gh escriben avisos ahí aunque salgan con 0), así que acá
# se baja a "Continue" sólo dentro de la función. El código de salida queda en $LASTEXITCODE.
function Invoke-Native([string]$exe, [string[]]$a) {
    $ErrorActionPreference = "Continue"
    $out = & $exe @a 2>&1
    return ,@($out | ForEach-Object { "$_" })
}

# Ojo: una función llamada "Git" taparía al git.exe (las funciones ganan a los ejecutables) y se llamaría a sí misma.
function Invoke-Git([string[]]$a) {
    $out = Invoke-Native "git.exe" (@("-C", $clone) + $a)
    if ($LASTEXITCODE -ne 0) { throw "git $($a -join ' ') falló: $(($out -join "`n").Trim())" }
    return $out
}

try {
    if (-not (Test-Path -LiteralPath $gh)) { throw "no encuentro gh.exe en $gh" }
    if (-not (Test-Path -LiteralPath $claude)) { throw "no encuentro claude.cmd en $claude" }
    if (-not (Test-Path -LiteralPath $promptFile)) { throw "no encuentro el prompt $promptFile" }

    # PATH con gh y git (la tarea arranca con el PATH del sistema) y sin variables de Claude/Herdr heredadas
    # (si alguien lo corre desde un panel de Herdr, el Claude hijo no debe creerse parte de esa sesión).
    $env:PATH = "C:\Program Files\GitHub CLI;C:\Program Files\Git\cmd;" + $env:PATH
    # ANTHROPIC_*: una ANTHROPIC_API_KEY en el entorno le gana al login de claude.ai y, si es inválida, Claude ni arranca.
    foreach ($v in (Get-ChildItem env: | Where-Object { $_.Name -like "CLAUDE*" -or $_.Name -like "HERDR_*" -or $_.Name -like "ANTHROPIC_*" })) {
        Remove-Item -LiteralPath "env:$($v.Name)" -ErrorAction SilentlyContinue
    }

    # 1) Clon persistente, limpio, en origin/agentnav, con los tags de upstream
    if (-not (Test-Path -LiteralPath (Join-Path $clone ".git"))) {
        Log "clonando $Repo en $clone…"
        $out = Invoke-Native "git.exe" @("clone", "--quiet", "https://github.com/$Repo.git", $clone)
        if ($LASTEXITCODE -ne 0) { throw "git clone falló: $(($out -join "`n").Trim())" }
    }
    $remotes = Invoke-Git @("remote")
    if ($remotes -notcontains "upstream") { Invoke-Git @("remote", "add", "upstream", $UpstreamUrl) | Out-Null }
    Invoke-Git @("fetch", "--quiet", "--prune", "origin") | Out-Null
    Invoke-Git @("fetch", "--quiet", "upstream", "refs/tags/v*:refs/tags/v*") | Out-Null
    Invoke-Native "git.exe" @("-C", $clone, "rebase", "--abort") | Out-Null   # restos de una corrida anterior cortada a la mitad
    Invoke-Git @("reset", "-q", "--hard") | Out-Null
    Invoke-Git @("clean", "-qfd") | Out-Null
    Invoke-Git @("checkout", "-q", "-B", "agentnav", "origin/agentnav") | Out-Null

    $base = (Get-Content -LiteralPath (Join-Path $clone "agentnav\BASE_TAG") -Raw).Trim()
    $latest = @(Invoke-Git @("tag", "--list", "v*")) | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
        Sort-Object { [version]($_.Substring(1)) } | Select-Object -Last 1
    if (-not $latest) { throw "no encontré tags vX.Y.Z de upstream" }

    # 2) Última corrida del workflow y assets del release
    $run = $null
    $runJson = Invoke-Native $gh @("run", "list", "-R", $Repo, "-w", "agentnav-build.yml", "-L", "1", "--json", "conclusion,status,url,createdAt")
    if ($LASTEXITCODE -eq 0) { $run = @(($runJson -join "") | ConvertFrom-Json) | Select-Object -First 1 }
    $assets = @()
    $assetsOut = Invoke-Native $gh @("release", "view", "agentnav-$latest", "-R", $Repo, "--json", "assets", "--jq", ".assets[].name")
    if ($LASTEXITCODE -eq 0) { $assets = @($assetsOut | ForEach-Object { $_.Trim() }) }
    $releaseOk = ($assets -contains "herdr.exe") -and ($assets -contains "herdr.exe.sha256")
    $runOk = ($null -ne $run) -and ($run.status -eq "completed") -and ($run.conclusion -eq "success")
    $runTxt = if ($run) { "$($run.conclusion) ($($run.createdAt))" } else { "sin datos" }
    $relTxt = if ($releaseOk) { "OK" } else { "incompleto o ausente" }
    Log "upstream $latest · base $base · release agentnav-$latest $relTxt · última corrida del workflow: $runTxt"

    $alDia = ($base -eq $latest) -and $releaseOk -and $runOk
    if ($alDia -and -not $ForzarAgente) { Log "al día: no hace falta el agente."; exit 0 }
    if ($Check) { Log "hay trabajo para el agente (-Check: no lo lanzo)."; exit 10 }

    # 3) Claude sin interfaz, parado en el clon, con permisos acotados
    $runUrl = if ($run) { "$($run.conclusion) $($run.url)" } else { "sin datos" }
    $relCtx = if ($releaseOk) { "completo" } else { "incompleto o ausente" }
    $contexto = @"
Contexto de esta corrida (lo generó upstream-agent.ps1 el $(Get-Date -Format s)):
- Clon del fork ya listo en: $clone (rama agentnav = origin/agentnav, remoto upstream agregado, tags v* traídos). Trabajá ahí con ``git -C "$clone" …``; tu directorio de trabajo ya es ese clon.
- ``gh`` está en el PATH y autenticado como pablitotester. No hay cargo ni rustc en esta PC.
- Último tag estable de upstream: $latest. BASE_TAG actual: $base. Release agentnav-$latest`: $relCtx. Última corrida del workflow: $runUrl.

"@
    $texto = $contexto + (Get-Content -LiteralPath $promptFile -Raw -Encoding UTF8)
    $allowed = @("Read", "Glob", "Grep", "Edit", "Write",
                 "Bash(git:*)", "Bash(gh:*)", "Bash(cat:*)", "Bash(ls:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(sed:*)",
                 "Bash(head:*)", "Bash(tail:*)", "Bash(diff:*)", "Bash(sleep:*)", "Bash(echo:*)", "Bash(wc:*)", "Bash(find:*)")

    # Sesión para trabajos desatendidos: el login interactivo de claude.ai vence cada tanto. Si existe el archivo con el
    # token de `claude setup-token` (una sola línea), se usa ese; si no, el login de claude.ai de este usuario.
    $tokenFile = Join-Path $work "claude-token.txt"
    if (Test-Path -LiteralPath $tokenFile) {
        $tok = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
        if ($tok) { $env:CLAUDE_CODE_OAUTH_TOKEN = $tok; Log "usando el token de claude setup-token ($tokenFile)" }
    }

    Log "lanzando Claude ($Model) sobre $clone…"
    Push-Location -LiteralPath $clone
    try {
        $ErrorActionPreference = "Continue"   # lo que Claude escriba en stderr no es un error terminante
        $salida = ($texto | & $claude -p --model $Model --output-format text --allowedTools @allowed 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
    } finally {
        Pop-Location
    }
    $encabezado = "# AgentNav Herdr upstream — $(Get-Date -Format s) — modelo $Model — exit $code`n`nupstream $latest · base $base · release agentnav-$latest $relTxt · workflow: $runTxt`n`n"
    Set-Content -LiteralPath $informe -Value ($encabezado + $salida) -Encoding UTF8
    $resumen = ($salida.Trim() -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 6) -join " | "
    Log "Claude terminó (exit $code): $resumen"
    exit $(if ($code -eq 0) { 0 } else { 1 })
} catch {
    Log "error: $($_.Exception.Message)"
    exit 1
}
