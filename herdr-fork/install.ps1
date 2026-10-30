<#
AgentNav: instala Herdr con los temas de AgentNav (cs16, matrix, procomm) en una PC con Windows, desde cero o sobre un
Herdr oficial ya instalado. Una línea, en PowerShell:

    irm https://raw.githubusercontent.com/pablitotester/herdr/agentnav/agentnav/install.ps1 | iex

Qué hace:
 1. Busca el último release agentnav-vX.Y.Z del fork y su manifiesto agentnav-latest.json (misma forma que herdr.dev/latest.json).
 2. Corre el instalador OFICIAL de Herdr (distribution/install.ps1 de esa misma versión) apuntándolo a ese manifiesto:
    arma %USERPROFILE%\.herdr, el junction `current`, el PATH, conpty... igual que una instalación normal.
 3. Si esa versión ya estaba instalada con el exe oficial, el instalador no baja nada: entonces cierra Herdr, pone el
    herdr.exe del fork (verificando SHA-256) y deja el marcador agentnav-build.json que `agentnav doctor` reconoce.
Para volver al oficial: `herdr update`.
#>
[CmdletBinding()]
param(
    [string]$Repo = "pablitotester/herdr",
    [string]$Tag = "",
    [string]$InstallDir = ""   # sólo para probar en una carpeta aparte; vacío = la instalación normal (%USERPROFILE%\.herdr)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Step([string]$m) { Write-Host "==> $m" }
function Get-Json([string]$url) {
    Invoke-RestMethod -Uri $url -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install"; "Accept" = "application/vnd.github+json" }
}
function Get-File([string]$url, [string]$dest) {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install" }
}
function Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

if ($env:OS -ne "Windows_NT") { throw "Sólo Windows." }

# 1. Release del fork
if ([string]::IsNullOrWhiteSpace($Tag)) {
    $rels = Get-Json "https://api.github.com/repos/$Repo/releases?per_page=20"
    $rel = $rels | Where-Object { $_.tag_name -like "agentnav-v*" -and -not $_.draft } |
        Sort-Object { [version]($_.tag_name -replace '^agentnav-v', '') } -Descending | Select-Object -First 1
    if ($null -eq $rel) { throw "$Repo no tiene releases agentnav-v*." }
    $Tag = $rel.tag_name
} else {
    $rel = Get-Json "https://api.github.com/repos/$Repo/releases/tags/$Tag"
}
$version = $Tag -replace '^agentnav-v', ''
$assets = @{}
foreach ($a in $rel.assets) { $assets[$a.name] = $a.browser_download_url }
foreach ($need in @("agentnav-latest.json", "herdr.exe", "herdr.exe.sha256")) {
    if (-not $assets.ContainsKey($need)) { throw "al release $Tag le falta $need (¿el workflow terminó?)" }
}
Step "Herdr $version con temas AgentNav, desde $Repo ($Tag)"

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-herdr-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    # 2. Instalador oficial de esa versión, apuntado a nuestro manifiesto
    $installer = Join-Path $tmp "install.ps1"
    Get-File "https://raw.githubusercontent.com/$Repo/agentnav/distribution/install.ps1" $installer
    Step "Instalador oficial de Herdr con el manifiesto del fork"
    $extra = @{}
    if (-not [string]::IsNullOrWhiteSpace($InstallDir)) { $extra["InstallDir"] = $InstallDir }
    & $installer -Channel stable -ManifestUrl $assets["agentnav-latest.json"] @extra
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "el instalador oficial salió con $LASTEXITCODE" }

    # 3. ¿Quedó nuestro exe? Si la versión ya existía con el oficial, el instalador no tocó nada: lo cambiamos nosotros.
    $root = if ([string]::IsNullOrWhiteSpace($InstallDir)) { Join-Path $env:USERPROFILE ".herdr" } else { $InstallDir }
    $current = Join-Path $root "packages\standalone\current"
    $exe = Join-Path $current "herdr.exe"
    if (-not (Test-Path -LiteralPath $exe)) { throw "no encuentro $exe después de instalar" }
    $shaFile = Join-Path $tmp "herdr.exe.sha256"
    Get-File $assets["herdr.exe.sha256"] $shaFile
    $want = ((Get-Content -LiteralPath $shaFile -Raw) -split '\s+')[0].ToLowerInvariant()
    if ($want -notmatch '^[0-9a-f]{64}$') { throw "sha256 inválido en el release" }
    if ((Sha256 $exe) -ne $want) {
        Step "Esa versión ya estaba instalada con el exe oficial: pongo el del fork"
        $new = Join-Path $tmp "herdr.exe"
        Get-File $assets["herdr.exe"] $new
        if ((Sha256 $new) -ne $want) { throw "el herdr.exe bajado no coincide con su SHA-256; no instalo" }
        $official = "$exe.oficial"
        if (-not (Test-Path -LiteralPath $official)) { Copy-Item -LiteralPath $exe -Destination $official }
        try { & $exe server stop *> $null } catch { }
        Start-Sleep -Seconds 3
        Get-Process herdr -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Copy-Item -LiteralPath $new -Destination $exe -Force
    }
    @{ tag = $Tag; sha256 = $want; repo = $Repo; installed = (Get-Date).ToString("s") } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $current "agentnav-build.json")
    $v = (& $exe --version | Out-String).Trim()
    Step "Listo: $v con temas AgentNav en $current"
    $agentnav = Get-Command agentnav -ErrorAction SilentlyContinue
    if ($null -ne $agentnav -and [string]::IsNullOrWhiteSpace($InstallDir)) {
        Step "AgentNav está en esta PC: levanto Herdr de nuevo (agentnav app)"
        & agentnav app
    } else {
        Write-Host "    Abrí una PowerShell nueva y corré: herdr   (en Settings, ctrl+b s → theme, están cs16, matrix y procomm)"
    }
    Write-Host "    Volver al oficial: herdr update"
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
