<#
AgentNav: instala Herdr con los temas de AgentNav (cs16, matrix, procomm, ambar, miami) en una PC con Windows, desde cero o sobre un
Herdr oficial ya instalado. Una línea, en PowerShell:

    irm https://raw.githubusercontent.com/pablitotester/herdr/agentnav/agentnav/install.ps1 | iex

Qué hace:
 1. Busca el último release agentnav-vX.Y.Z del fork y su manifiesto agentnav-latest.json (misma forma que herdr.dev/latest.json).
 2. Corre el instalador OFICIAL de Herdr (distribution/install.ps1 de esa misma versión) apuntándolo a ese manifiesto:
    arma %USERPROFILE%\.herdr, el junction `current`, el PATH, conpty... igual que una instalación normal.
 3. Si esa versión ya estaba instalada con el exe oficial, el instalador no baja nada: entonces cierra Herdr, pone el
    herdr.exe del fork (verificando SHA-256) y deja el marcador agentnav-build.json que `agentnav doctor` reconoce.
 4. Deja el chequeo automático de updates: copia agentnav/update.ps1 a %USERPROFILE%\.herdr\agentnav y crea la tarea
    programada "AgentNav Herdr update" (al iniciar sesión y una vez por día). Para no crearla: -NoAutoUpdate.
    Además este herdr.exe consulta el manifiesto del fork, así que el aviso de update dentro de Herdr y `herdr update`
    también se quedan con los temas.
 5. Crea el comando `agentnav` (%USERPROFILE%\.herdr\agentnav\bin\agentnav.cmd, en el PATH del usuario), que abre
    este Herdr igual que `herdr`. Si la PC ya tiene el programa AgentNav con su propio `agentnav`, no lo pisa.
Para volver al oficial: Unregister-ScheduledTask "AgentNav Herdr update" y reinstalar con irm https://herdr.dev/install.ps1 | iex
(`herdr update` desde este build trae el del fork, no el oficial).
#>
[CmdletBinding()]
param(
    [string]$Repo = "pablitotester/herdr",
    [string]$Tag = "",
    # No relanzar Herdr al final (lo usa update.ps1 desde la tarea programada).
    [switch]$NoLaunch,
    # No crear la tarea programada de updates automáticos.
    [switch]$NoAutoUpdate
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
    & $installer -Channel stable -ManifestUrl $assets["agentnav-latest.json"]
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "el instalador oficial salió con $LASTEXITCODE" }

    # 3. ¿Quedó nuestro exe? Si la versión ya existía con el oficial, el instalador no tocó nada: lo cambiamos nosotros.
    $current = Join-Path $env:USERPROFILE ".herdr\packages\standalone\current"
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

    # 4. Chequeo automático de updates
    if (-not $NoAutoUpdate) {
        try {
            $stateDir = Join-Path $env:USERPROFILE ".herdr\agentnav"
            New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
            $updater = Join-Path $stateDir "update.ps1"
            Get-File "https://raw.githubusercontent.com/$Repo/agentnav/agentnav/update.ps1" $updater
            $taskName = "AgentNav Herdr update"
            $me = "$env:USERDOMAIN\$env:USERNAME"
            $action = New-ScheduledTaskAction -Execute "powershell.exe" `
                -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$updater`" -Repo $Repo"
            $atLogon = New-ScheduledTaskTrigger -AtLogOn -User $me
            $atLogon.Delay = "PT2M"
            $daily = New-ScheduledTaskTrigger -Daily -At "13:00"
            $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
            $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $daily) -Settings $settings `
                -Principal $principal -Force `
                -Description "Chequea releases agentnav-v* de $Repo e instala el nuevo si Herdr está cerrado. Log: $stateDir\update.log" |
                Out-Null
            Step "Updates automáticos: tarea '$taskName' (al iniciar sesión y todos los días). Log: $stateDir\update.log"
        } catch {
            Write-Warning "no pude crear la tarea de updates automáticos: $($_.Exception.Message)"
        }
    }

    # 5. Comando `agentnav` (abre este Herdr, igual que `herdr`). Si en la PC ya está el programa AgentNav, que tiene su
    #    propio `agentnav` (app, doctor, herdr-sync), no lo pisamos.
    $binDir = Join-Path $env:USERPROFILE ".herdr\agentnav\bin"
    $shim = Join-Path $binDir "agentnav.cmd"
    $other = Get-Command agentnav -All -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandType -ne "Application" -or $_.Source -ne $shim } | Select-Object -First 1
    if ($null -ne $other) {
        Write-Warning "ya hay otro comando agentnav ($($other.CommandType) $($other.Source)); no creo el de Herdr. Abrilo con: herdr"
    } else {
        try {
            New-Item -ItemType Directory -Force -Path $binDir | Out-Null
            Set-Content -LiteralPath $shim -Encoding Ascii -Value @(
                "@echo off",
                "rem AgentNav: abre Herdr (lo crea agentnav/install.ps1)",
                "@`"%USERPROFILE%\.herdr\packages\standalone\current\herdr.exe`" %*",
                "@exit /b %errorlevel%"
            )
            # Nunca setx (trunca a 1024) ni [Environment]::SetEnvironmentVariable (expande los %VAR% y pasa el
            # valor a REG_SZ): se lee y escribe el registro tal cual, conservando REG_EXPAND_SZ.
            # Compara sin mayúsculas ni barra final para no duplicar.
            $norm = { param($p) [Environment]::ExpandEnvironmentVariables($p).Trim().TrimEnd('\').ToLowerInvariant() }
            $envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
            try {
                $userPath = [string]$envKey.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                $parts = @($userPath -split ";" | Where-Object { $_.Trim() })
                if (-not ($parts | Where-Object { (& $norm $_) -eq (& $norm $binDir) })) {
                    $envKey.SetValue("Path", (($parts + $binDir) -join ";"), [Microsoft.Win32.RegistryValueKind]::ExpandString)
                    # Avisa a Explorer del cambio (WM_SETTINGCHANGE), como hace SetEnvironmentVariable.
                    [Environment]::SetEnvironmentVariable("AGENTNAV_PATH_REFRESH", "1", "User")
                    [Environment]::SetEnvironmentVariable("AGENTNAV_PATH_REFRESH", $null, "User")
                }
            } finally {
                $envKey.Close()
            }
            if (-not (@($env:Path -split ";") | Where-Object { $_.Trim() -and (& $norm $_) -eq (& $norm $binDir) })) {
                $env:Path = "$env:Path;$binDir"
            }
            Step "Comando agentnav: $shim (abre Herdr; en las PowerShell que ya estaban abiertas, abrí una nueva)"
        } catch {
            Write-Warning "no pude crear el comando agentnav: $($_.Exception.Message)"
        }
    }

    if ($NoLaunch) {
        # update.ps1 desde la tarea programada: no abrir nada.
    } elseif ($null -ne $other) {
        Step "AgentNav está en esta PC: levanto Herdr de nuevo (agentnav app)"
        & $other app
    } else {
        Write-Host "    Abrí una PowerShell nueva y corré: agentnav   (o herdr; en Settings, ctrl+b s → theme, están cs16, matrix, procomm, ambar y miami)"
    }
    Write-Host "    Volver al oficial: Unregister-ScheduledTask 'AgentNav Herdr update' y después irm https://herdr.dev/install.ps1 | iex"
    Write-Host "    (y para sacar el comando agentnav: borrar $binDir y su entrada del PATH del usuario)"
    Write-Host "    (herdr update desde este build trae el del fork, con los temas)"
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
