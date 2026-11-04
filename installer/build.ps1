<#
AgentNav: arma el paquete para instalar en otra PC. Desde C:\AgentNav:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\build.ps1

Deja dist\AgentNav-setup.zip con:
    Instalar.cmd, install.ps1, configurar.py, LEEME.txt      (esta carpeta)
    payload\                                                 copia del repo sin settings.json (trae tu ntfy),
                                                             projects.json, .git, __pycache__, installer\ ni dist\
El que lo recibe descomprime y hace doble clic en Instalar.cmd.
#>
[CmdletBinding()]
param([string]$Out = "")

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Installer = Join-Path $Repo "installer"
if (-not $Out) { $Out = Join-Path $Repo "dist\AgentNav-setup.zip" }
$Excluir = @("settings.json", "projects.json", ".git", ".gitignore", ".claude", "__pycache__", "installer", "dist", "*.pyc", "*.tmp", "*.bak*")

$stage = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-build-" + [Guid]::NewGuid().ToString("N"))
$payload = Join-Path $stage "payload"
New-Item -ItemType Directory -Force -Path $payload | Out-Null
try {
    foreach ($item in Get-ChildItem -LiteralPath $Repo -Force) {
        $skip = $false
        foreach ($pat in $Excluir) { if ($item.Name -like $pat) { $skip = $true; break } }
        if ($skip) { continue }
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $payload $item.Name) -Recurse -Force
    }
    Get-ChildItem -LiteralPath $payload -Recurse -Force -Directory | Where-Object { $_.Name -eq "__pycache__" } |
        Remove-Item -Recurse -Force
    foreach ($leak in @("settings.json", "projects.json")) {
        if (Test-Path -LiteralPath (Join-Path $payload $leak)) { throw "$leak quedó en el payload" }
    }
    foreach ($f in @("Instalar.cmd", "install.ps1", "configurar.py", "LEEME.txt")) {
        Copy-Item -LiteralPath (Join-Path $Installer $f) -Destination (Join-Path $stage $f)
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    if (Test-Path -LiteralPath $Out) { Remove-Item -LiteralPath $Out -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $Out -CompressionLevel Optimal
    $mb = [math]::Round((Get-Item -LiteralPath $Out).Length / 1MB, 2)
    $n = (Get-ChildItem -LiteralPath $payload -Recurse -File).Count
    Write-Host "Listo: $Out ($mb MB, $n archivos en payload)"
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
