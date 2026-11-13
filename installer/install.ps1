<#
AgentNav: instalador para otra PC con Windows 10/11, desde cero. Viene dentro de AgentNav-setup.zip junto con una
copia del repo (carpeta payload\). Lo normal es hacer doble clic en Instalar.cmd; a mano:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 [-HerdrOficial] [-SinRequisitos] [-ConGemini]

Qué hace, en orden (cada paso se saltea si ya está):
 1. Requisitos: Python 3.11+ de 64 bits con el lanzador `py`, git, PowerShell 7 (pwsh), Windows Terminal, Claude Code
    y Herdr. Usa winget; si winget no está, Python, git y pwsh se bajan de su sitio oficial / GitHub.
    Herdr se instala con los temas de AgentNav (fork pablitotester/herdr); con -HerdrOficial, el de herdr.dev.
    Con -ConGemini (apagado por defecto) también Node.js LTS (winget OpenJS.NodeJS.LTS; sin winget, el .msi de
    nodejs.org) y Gemini CLI (`npm install -g @google/gemini-cli`), y en el paso 3 registra los hooks de AgentNav en
    %USERPROFILE%\.gemini\settings.json sin tocar lo demás que haya ahí.
 2. Deja AgentNav en C:\AgentNav (la ruta es fija: la config de Herdr, el plugin y los .vbs la tienen escrita): clon de
    GitHub si hay git y acceso al repo (entonces `agentnav update` trae lo nuevo), si no la copia del zip (payload\).
    Con -SinGit siempre la copia. settings.json y projects.json existentes no se pisan.
 3. Hooks de Claude Code en %USERPROFILE%\.claude\hooks y su registro en settings.json de Claude (sin tocar lo demás).
    `herdr integration install claude` para el hook propio de Herdr (SessionStart).
 4. config.toml de Herdr (con backup del que hubiera), plugin de Herdr enlazado, arranque automático del servidor,
    alias `agentnav` en los dos perfiles de PowerShell, acceso directo "Herdr" en el escritorio.
 5. Levanta el servidor y corre `agentnav doctor`.
No necesita administrador: todo se instala para el usuario actual.
#>
[CmdletBinding()]
param(
    [switch]$HerdrOficial,
    [switch]$SinRequisitos,
    [switch]$SinGit,
    [switch]$ConGemini,
    [string]$ForkRepo = "pablitotester/herdr",
    [string]$RepoUrl = "https://github.com/pablitotester/AgentNav.git"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
Import-Module Microsoft.PowerShell.Security, Microsoft.PowerShell.Utility -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = "1"   # los mensajes con acentos de configurar.py y de agentnav doctor

$Dest = "C:\AgentNav"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = Join-Path $Here "payload"
$ClaudeHome = Join-Path $env:USERPROFILE ".claude"
$HooksDir = Join-Path $ClaudeHome "hooks"
$GeminiHome = Join-Path $env:USERPROFILE ".gemini"   # también lo usa Antigravity: su settings.json se completa, no se pisa
$Problemas = New-Object System.Collections.ArrayList

function Step([string]$m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "    [ok] $m" -ForegroundColor Green }
function Aviso([string]$m) { Write-Host "    [!] $m" -ForegroundColor Yellow; [void]$Problemas.Add($m) }

function Refresh-Path {
    # Lo que los instaladores agregaron al PATH del usuario/máquina no llega a esta sesión solo: se relee del registro.
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $extra = @(
        (Join-Path $env:USERPROFILE ".local\bin"),                              # claude
        (Join-Path $env:USERPROFILE ".herdr\packages\standalone\current"),      # herdr
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),               # py (instalación por usuario)
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),                  # wt
        (Join-Path $env:APPDATA "npm"),                                         # gemini (npm -g deja ahí el .cmd)
        "C:\Program Files\PowerShell\7", "C:\Program Files\Git\cmd", "C:\Program Files\nodejs"
    )
    $env:Path = (@($m, $u) + $extra | Where-Object { $_ }) -join ";"
}

function Have([string]$cmd) { return $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Test-Python {
    if (-not (Have "py")) { return $false }
    try {
        $out = & py -3 -I -c "import sys,struct;print(sys.version_info[:2]>=(3,11) and struct.calcsize('P')==8)" 2>$null
        return ("$out".Trim() -eq "True")
    } catch { return $false }
}

$script:Winget = $null
function Have-Winget {
    if ($null -eq $script:Winget) { $script:Winget = Have "winget" }
    return $script:Winget
}

function Winget-Install([string]$id, [string]$override) {
    $args = @("install", "-e", "--id", $id, "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity")
    if ($override) { $args += @("--override", $override) } else { $args += "--silent" }
    & winget @args | Out-Host
    # 0 = instaló; -1978335189 = ya estaba en esa versión. Cualquier otro código lo reporta el que llama.
    return ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189)
}

function Get-File([string]$url, [string]$dest) {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install" }
}

function GitHub-LatestAsset([string]$repo, [string]$pattern) {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install"; "Accept" = "application/vnd.github+json" }
    $a = $rel.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if ($null -eq $a) { throw "en el último release de $repo no hay un archivo $pattern" }
    return $a.browser_download_url
}

function Run-Installer([string]$url, [string[]]$arguments, [string]$ext) {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-req-" + [Guid]::NewGuid().ToString("N") + $ext)
    Get-File $url $tmp
    try {
        if ($ext -eq ".msi") {
            $p = Start-Process msiexec.exe -ArgumentList (@("/i", "`"$tmp`"") + $arguments) -Wait -PassThru
        } else {
            $p = Start-Process $tmp -ArgumentList $arguments -Wait -PassThru
        }
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "el instalador salió con código $($p.ExitCode)" }
    } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
}

function NodeJs-LatestLtsMsi {
    # nodejs.org/dist/index.json lista todas las versiones; "lts" es false o el nombre de la línea LTS. La primera con
    # nombre es la LTS más nueva. Instalador x64 .msi: node-vX.Y.Z-x64.msi.
    $idx = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json" -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install" }
    $lts = $idx | Where-Object { $_.lts } | Select-Object -First 1
    if ($null -eq $lts) { throw "no encontré una versión LTS en nodejs.org/dist/index.json" }
    return "https://nodejs.org/dist/$($lts.version)/node-$($lts.version)-x64.msi"
}

function Requisito([string]$nombre, [scriptblock]$presente, [scriptblock]$instalar) {
    if (& $presente) { Ok "$nombre ya está"; return }
    Step "Instalando $nombre"
    try {
        & $instalar
        Refresh-Path
        if (& $presente) { Ok "$nombre instalado" } else { Aviso "$nombre se instaló pero no lo veo en esta sesión; abrí una PowerShell nueva y volvé a correr Instalar.cmd" }
    } catch {
        Aviso "$nombre no se pudo instalar: $($_.Exception.Message)"
    }
}

function Invoke-RemoteScript([string]$url, [string[]]$arguments) {
    # Equivalente a `irm url | iex` pero con argumentos y sin ensuciar el ámbito del instalador.
    $code = Invoke-RestMethod -Uri $url -UseBasicParsing -Headers @{ "User-Agent" = "AgentNav-install" }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-remote-" + [Guid]::NewGuid().ToString("N") + ".ps1")
    [IO.File]::WriteAllText($tmp, [string]$code, (New-Object Text.UTF8Encoding $true))
    try { & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp @arguments | Out-Host }
    finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
}

# ------------------------------------------------------------------------------------------------ comprobaciones
if ($env:OS -ne "Windows_NT") { throw "Sólo Windows." }
if (-not (Test-Path -LiteralPath (Join-Path $Payload "agentnav.py"))) { throw "no encuentro payload\agentnav.py al lado de este script; descomprimí el zip entero" }
Write-Host "AgentNav: instalación en $Dest para $env:USERNAME" -ForegroundColor White
Refresh-Path

# ------------------------------------------------------------------------------------------------ 1. requisitos
if (-not $SinRequisitos) {
    Step "Requisitos"
    if (-not (Have-Winget)) { Write-Host "    winget no está: Python, git y pwsh se bajan de sus sitios; Windows Terminal queda para la tienda." }

    Requisito "Python 3.11+ (64 bits, con py)" { Test-Python } {
        $flags = "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0"
        if (Have-Winget) {
            if (-not (Winget-Install "Python.Python.3.12" $flags)) { throw "winget devolvió $LASTEXITCODE" }
        } else {
            Run-Installer "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" ($flags -split " ") ".exe"
        }
    }

    Requisito "git" { Have "git" } {
        if (Have-Winget) {
            if (-not (Winget-Install "Git.Git" "")) { throw "winget devolvió $LASTEXITCODE" }
        } else {
            Run-Installer (GitHub-LatestAsset "git-for-windows/git" "Git-*-64-bit.exe") @("/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-") ".exe"
        }
    }

    Requisito "PowerShell 7 (pwsh)" { Have "pwsh" } {
        if (Have-Winget) {
            if (-not (Winget-Install "Microsoft.PowerShell" "")) { throw "winget devolvió $LASTEXITCODE" }
        } else {
            Run-Installer (GitHub-LatestAsset "PowerShell/PowerShell" "PowerShell-*-win-x64.msi") @("/qn", "/norestart", "ADD_PATH=1") ".msi"
        }
    }

    Requisito "Windows Terminal" { Have "wt" } {
        if (Have-Winget) {
            if (-not (Winget-Install "Microsoft.WindowsTerminal" "")) { throw "winget devolvió $LASTEXITCODE" }
        } else {
            throw "sin winget: instalalo desde Microsoft Store (Windows Terminal) y volvé a correr Instalar.cmd"
        }
    }

    Requisito "Claude Code" { Have "claude" } {
        Invoke-RemoteScript "https://claude.ai/install.ps1" @()
    }

    Requisito "Herdr" { Have "herdr" } {
        if ($HerdrOficial) {
            Invoke-RemoteScript "https://herdr.dev/install.ps1" @()
        } else {
            Invoke-RemoteScript "https://raw.githubusercontent.com/$ForkRepo/agentnav/agentnav/install.ps1" @("-Repo", $ForkRepo)
        }
    }

    if ($ConGemini) {
        Requisito "Node.js LTS (node y npm)" { (Have "node") -and (Have "npm") } {
            if (Have-Winget) {
                if (-not (Winget-Install "OpenJS.NodeJS.LTS" "")) { throw "winget devolvió $LASTEXITCODE" }
            } else {
                Run-Installer (NodeJs-LatestLtsMsi) @("/qn", "/norestart") ".msi"
            }
        }
        Requisito "Gemini CLI" { Have "gemini" } {
            if (-not (Have "npm")) { throw "sin npm (Node.js) no puedo instalar Gemini CLI" }
            & npm install -g @google/gemini-cli 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "npm install -g @google/gemini-cli devolvió $LASTEXITCODE" }
        }
    }

    if (-not (Test-Python)) { throw "sin Python 3.11+ de 64 bits no puedo seguir (ver avisos arriba)" }
    if (-not (Have "herdr")) { throw "sin Herdr no puedo seguir (ver avisos arriba)" }
} else {
    if (-not (Test-Python)) { throw "falta Python 3.11+ de 64 bits con py" }
    if (-not (Have "herdr")) { throw "falta Herdr" }
    if ($ConGemini -and -not (Have "gemini")) { Write-Host "    -ConGemini con -SinRequisitos: falta Gemini CLI; registro los hooks igual" }
}

# ------------------------------------------------------------------------------------------------ 2. archivos
Step "Copiando AgentNav a $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

function Copy-Tree([string]$from) {
    # Copia item por item (también .git) conservando settings.json y projects.json del destino.
    foreach ($item in Get-ChildItem -LiteralPath $from -Force) {
        if ($item.Name -in @("settings.json", "projects.json")) { continue }
        $target = Join-Path $Dest $item.Name
        if ($item.PSIsContainer) {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

function Install-FromGit {
    # Preferimos que C:\AgentNav sea un clon: así `agentnav update` puede traer lo nuevo y doctor avisa cuando hay.
    # Devuelve $true si quedó resuelto por git; $false para caer al payload del zip (sin git, sin red, repo privado).
    if (-not (Have "git")) { return $false }
    $env:GIT_TERMINAL_PROMPT = "0"   # un repo privado o sin red falla enseguida en vez de pedir usuario y clave
    if (Test-Path -LiteralPath (Join-Path $Dest ".git")) {
        $dirty = (& git -C $Dest status --porcelain 2>$null | Out-String).Trim()
        if ($dirty) { Write-Host "    $Dest tiene cambios locales sin commitear: no hago pull"; return $true }
        & git -C $Dest pull --ff-only 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) { Aviso "git pull en $Dest falló; sigo con lo que ya había" }
        return $true
    }
    & git ls-remote --exit-code --heads $RepoUrl main *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("agentnav-clone-" + [Guid]::NewGuid().ToString("N"))
    & git clone --quiet --branch main $RepoUrl $tmp 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $tmp "agentnav.py"))) {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }
    try { Copy-Tree $tmp } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    return $true
}

$porGit = $false
if (-not $SinGit) {
    try { $porGit = Install-FromGit } catch { Write-Host "    git: $($_.Exception.Message)"; $porGit = $false }
}
if ($porGit) {
    Ok "AgentNav desde $RepoUrl (clon en $Dest; se actualiza con: agentnav update)"
} else {
    Copy-Tree $Payload
    Ok "archivos copiados del zip (sin git o sin acceso a $RepoUrl; para actualizar, volver a correr un zip nuevo)"
}
# Lo que salió de un zip bajado de internet queda "bloqueado" (Zone.Identifier) y PowerShell no lo ejecuta.
Get-ChildItem -LiteralPath $Dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

$configurar = Join-Path $Here "configurar.py"
# PowerShell 5.1 se come los argumentos vacíos: "-" significa "sin fork".
$repoArg = if ($HerdrOficial) { "-" } else { $ForkRepo }
& py -3 -I -X utf8 $configurar agentnav-settings (Join-Path $Dest "settings.json") (Join-Path $Dest "settings.example.json") $repoArg | Out-Host
if ($LASTEXITCODE -ne 0) { Aviso "no pude preparar settings.json de AgentNav" }
$projects = Join-Path $Dest "projects.json"
if (-not (Test-Path -LiteralPath $projects)) {
    [IO.File]::WriteAllText($projects, "[]`n", (New-Object Text.UTF8Encoding $false))
    Ok "projects.json vacío (los proyectos se agregan con: agentnav new <nombre>)"
}

# Política de ejecución del usuario: el alias corre agentnav.ps1 y en Windows 10 viene Restricted.
try {
    # Esta sesión corre con Bypass; lo que importa es la política que verá el alias en una PowerShell normal:
    # la primera definida entre MachinePolicy, UserPolicy, CurrentUser y LocalMachine (sin ninguna: Restricted).
    $pol = "Restricted"
    foreach ($scope in @("MachinePolicy", "UserPolicy", "CurrentUser", "LocalMachine")) {
        $p = [string](Get-ExecutionPolicy -Scope $scope)
        if ($p -ne "Undefined") { $pol = $p; break }
    }
    if ($pol -in @("Restricted", "AllSigned")) {
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
        Ok "política de ejecución del usuario: RemoteSigned (antes $pol)"
    } else {
        Ok "política de ejecución: $pol"
    }
} catch { Aviso "no pude cambiar la política de ejecución: $($_.Exception.Message). Corré: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" }

# ------------------------------------------------------------------------------------------------ 3. hooks de Claude Code
Step "Hooks de Claude Code"
New-Item -ItemType Directory -Force -Path $HooksDir | Out-Null
foreach ($h in @("agentnav-state.ps1", "agentnav-unblock.cmd")) {
    Copy-Item -LiteralPath (Join-Path $Dest "hooks\$h") -Destination (Join-Path $HooksDir $h) -Force
    Unblock-File -LiteralPath (Join-Path $HooksDir $h) -ErrorAction SilentlyContinue
}
Ok "hooks copiados a $HooksDir"
& py -3 -I -X utf8 $configurar claude-hooks (Join-Path $ClaudeHome "settings.json") $HooksDir | Out-Host
if ($LASTEXITCODE -ne 0) { Aviso "no pude registrar los hooks en el settings.json de Claude" }
try {
    & herdr integration install claude | Out-Host
    Ok "integración de Herdr con Claude Code (hook SessionStart)"
} catch { Aviso "herdr integration install claude falló: $($_.Exception.Message)" }

# ------------------------------------------------------------------------------------------------ 3b. hooks de Gemini CLI
if ($ConGemini) {
    Step "Hooks de Gemini CLI"
    # Los mismos agentnav-state.ps1 y agentnav-unblock.cmd (ya copiados a $HooksDir) atienden a Gemini con sus seis
    # eventos (SessionStart, BeforeAgent, AfterAgent, SessionEnd, Notification y AfterTool, el desbloqueo tras un permiso).
    # configurar.py gemini-hooks los registra en el settings.json de Gemini sin tocar lo demás (Antigravity guarda lo
    # suyo ahí), con backup. Gemini corre los comandos de hook en PowerShell. Herdr 0.9.5 no tiene `integration install gemini`.
    New-Item -ItemType Directory -Force -Path $GeminiHome | Out-Null
    & py -3 -I -X utf8 $configurar gemini-hooks (Join-Path $GeminiHome "settings.json") $HooksDir | Out-Host
    if ($LASTEXITCODE -ne 0) { Aviso "no pude registrar los hooks en el settings.json de Gemini CLI" }
    if (Have "gemini") {
        Write-Host "    la primera vez, `gemini` pide iniciar sesión con tu cuenta de Google"
    } else {
        Aviso "los hooks de Gemini quedaron registrados, pero falta el comando gemini: npm install -g @google/gemini-cli"
    }
}

# ------------------------------------------------------------------------------------------------ 4. Herdr y Windows
Step "Config de Herdr"
$herdrCfgDir = Join-Path $env:APPDATA "herdr"
$herdrCfg = Join-Path $herdrCfgDir "config.toml"
New-Item -ItemType Directory -Force -Path $herdrCfgDir | Out-Null
$repoCfg = Join-Path $Dest "config\herdr.config.toml"
if (Test-Path -LiteralPath $herdrCfg) {
    $same = [Linq.Enumerable]::SequenceEqual([IO.File]::ReadAllBytes($herdrCfg), [IO.File]::ReadAllBytes($repoCfg))
    if (-not $same) {
        $bak = "$herdrCfg.bak-" + (Get-Date).ToString("yyyy-MM-dd-HHmmss")
        Copy-Item -LiteralPath $herdrCfg -Destination $bak
        Write-Host "    el config.toml que había quedó en $bak"
    }
}
Copy-Item -LiteralPath $repoCfg -Destination $herdrCfg -Force
Ok "config.toml de Herdr (selector alt+p, temas alt+t, ctrl+b c, F1)"

Step "Servidor de Herdr y plugin"
try {
    & py -3 -I -X utf8 (Join-Path $Dest "agentnav.py") up | Out-Host
} catch { Aviso "agentnav up falló: $($_.Exception.Message)" }
try {
    & herdr server reload-config *> $null
} catch { }
try {
    $list = & herdr plugin list --json 2>$null | Out-String
    if ($list -match '"plugin_id"\s*:\s*"agentnav"') { & herdr plugin unlink agentnav *> $null }
    & herdr plugin link (Join-Path $Dest "plugin") | Out-Null
    Ok "plugin de Herdr enlazado (el + de la barra abre en el proyecto con su agente)"
} catch { Aviso "herdr plugin link falló: $($_.Exception.Message)" }

Step "Arranque automático, alias y acceso directo"
$startup = [Environment]::GetFolderPath("Startup")
Copy-Item -LiteralPath (Join-Path $Dest "startup\Herdr server.vbs") -Destination (Join-Path $startup "Herdr server.vbs") -Force
Ok "Herdr server.vbs en Inicio"

$docs = [Environment]::GetFolderPath("MyDocuments")
$aliasLine = "Set-Alias -Name agentnav -Value C:\AgentNav\agentnav.ps1"
foreach ($prof in @((Join-Path $docs "WindowsPowerShell\Microsoft.PowerShell_profile.ps1"), (Join-Path $docs "PowerShell\Microsoft.PowerShell_profile.ps1"))) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $prof) | Out-Null
    $has = (Test-Path -LiteralPath $prof) -and ((Get-Content -LiteralPath $prof -Raw -ErrorAction SilentlyContinue) -match "agentnav\.ps1")
    if (-not $has) { Add-Content -LiteralPath $prof -Value $aliasLine -Encoding UTF8 }
}
Ok "alias agentnav en los perfiles de Windows PowerShell y pwsh"

try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut((Join-Path $desktop "Herdr.lnk"))
    $lnk.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
    $lnk.Arguments = "`"$Dest\Herdr.vbs`""
    $lnk.WorkingDirectory = $env:USERPROFILE
    $wt = Get-Command wt -ErrorAction SilentlyContinue
    if ($wt) { $lnk.IconLocation = "$($wt.Source),0" } else { $lnk.IconLocation = (Get-Command herdr).Source + ",0" }
    $lnk.Description = "Herdr con AgentNav"
    $lnk.Save()
    Ok "acceso directo Herdr en el escritorio"
} catch { Aviso "no pude crear el acceso directo: $($_.Exception.Message)" }

# ------------------------------------------------------------------------------------------------ 5. doctor
Step "agentnav doctor"
try { & py -3 -I -X utf8 (Join-Path $Dest "agentnav.py") doctor | Out-Host } catch { Aviso "doctor falló: $($_.Exception.Message)" }

Write-Host ""
if ($Problemas.Count -eq 0) {
    Write-Host "Listo. Doble clic en 'Herdr' del escritorio, o en una PowerShell NUEVA: agentnav" -ForegroundColor Green
} else {
    Write-Host "Terminó con $($Problemas.Count) aviso(s):" -ForegroundColor Yellow
    foreach ($p in $Problemas) { Write-Host "  - $p" -ForegroundColor Yellow }
}
Write-Host "Primer proyecto:  agentnav new <nombre>      (crea C:\<nombre>, lo registra y abre su Claude)"
Write-Host "Ya existente:     agentnav new <nombre> <ruta>"
Write-Host "Teclas en Herdr:  ctrl+b, soltar, alt+p = selector de proyectos; alt+t = temas; F1 = ayuda"
