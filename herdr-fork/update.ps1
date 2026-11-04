<#
AgentNav: chequeo automático de updates de Herdr + temas AgentNav.

Compara el SHA-256 del herdr.exe instalado con el del último release agentnav-vX.Y.Z del fork. Así detecta las dos cosas:
  - versión nueva de upstream (el workflow rebasó y compiló agentnav-vX.Y.Z nuevo), y
  - cambios del parche de AgentNav con la misma versión (el workflow reemplazó el exe del release).

Lo corre la tarea programada "AgentNav Herdr update" (al iniciar sesión y una vez por día) que deja install.ps1.
A mano:
    powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.herdr\agentnav\update.ps1" -Check
    ... -Force     instala aunque Herdr esté abierto (lo cierra)

Con Herdr abierto y sin -Force no toca nada: queda pendiente para el próximo chequeo. El aviso de versión nueva igual
aparece dentro de Herdr (el build del fork consulta nuestro manifiesto) y `herdr update` instala el del fork.
Salida: 0 = al día o actualizado, 10 = hay update (con -Check) o pendiente porque Herdr está abierto, 1 = error.
#>
[CmdletBinding()]
param(
    [string]$Repo = "pablitotester/herdr",
    [switch]$Check,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$stateDir = Join-Path $env:USERPROFILE ".herdr\agentnav"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$logFile = Join-Path $stateDir "update.log"

function Log([string]$m) {
    $line = "{0}  {1}" -f (Get-Date).ToString("s"), $m
    Write-Host $line
    try {
        if ((Test-Path -LiteralPath $logFile) -and (Get-Item -LiteralPath $logFile).Length -gt 256KB) {
            Move-Item -LiteralPath $logFile -Destination "$logFile.old" -Force
        }
        Add-Content -LiteralPath $logFile -Value $line
    } catch { }
}
function Get-Json([string]$url) {
    Invoke-RestMethod -Uri $url -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-update"; "Accept" = "application/vnd.github+json" }
}

try {
    $exe = Join-Path $env:USERPROFILE ".herdr\packages\standalone\current\herdr.exe"
    if (-not (Test-Path -LiteralPath $exe)) { throw "no encuentro $exe (¿Herdr instalado con agentnav/install.ps1?)" }

    $rels = Get-Json "https://api.github.com/repos/$Repo/releases?per_page=20"
    $rel = $rels | Where-Object { $_.tag_name -like "agentnav-v*" -and -not $_.draft -and -not $_.prerelease } |
        Sort-Object { [version]($_.tag_name -replace '^agentnav-v', '') } -Descending | Select-Object -First 1
    if ($null -eq $rel) { throw "$Repo no tiene releases agentnav-v*" }
    $shaAsset = $rel.assets | Where-Object { $_.name -eq "herdr.exe.sha256" } | Select-Object -First 1
    if ($null -eq $shaAsset) { throw "al release $($rel.tag_name) le falta herdr.exe.sha256 (¿el workflow sigue corriendo?)" }
    $shaText = Invoke-RestMethod -Uri $shaAsset.browser_download_url -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-update" }
    if ($shaText -is [byte[]]) { $shaText = [Text.Encoding]::ASCII.GetString($shaText) }
    $want = (([string]$shaText).Trim() -split '\s+')[0].ToLowerInvariant()
    if ($want -notmatch '^[0-9a-f]{64}$') { throw "sha256 inválido en $($rel.tag_name)" }

    $have = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $current = (& $exe --version | Out-String).Trim()
    if ($have -eq $want) {
        Log "al día: $current ($($rel.tag_name))"
        exit 0
    }

    Log "update disponible: $($rel.tag_name) (instalado: $current)"
    if ($Check) { exit 10 }

    $running = @(Get-Process herdr -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0 -and -not $Force) {
        Log "Herdr está abierto: no lo cierro. Queda para el próximo chequeo (o: herdr update, o este script con -Force)."
        exit 10
    }

    Log "instalando $($rel.tag_name)…"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-update-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $installer = Join-Path $tmp "install.ps1"
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$Repo/agentnav/agentnav/install.ps1" -OutFile $installer `
            -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-update" }
        & $installer -Repo $Repo -Tag $rel.tag_name -NoLaunch *>&1 | ForEach-Object { Log "  $_" }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }

    $have = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($have -ne $want) { throw "después de instalar el SHA-256 no coincide con $($rel.tag_name)" }
    Log "actualizado: $((& $exe --version | Out-String).Trim()) ($($rel.tag_name))"
    exit 0
} catch {
    Log "error: $($_.Exception.Message)"
    exit 1
}
