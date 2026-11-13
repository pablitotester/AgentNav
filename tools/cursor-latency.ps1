<#
AgentNav: mide el camino tecla → eco de la consola donde corre, con DSR (ESC[6n).

Por cada iteración escribe un carácter, manda ESC[6n y cronometra hasta leer la respuesta ESC[fila;colR. Eso mide
la ida y vuelta por el emulador de terminal (ConPTY + Herdr o Windows Terminal + su parser), no el pintado en pantalla
ni PSReadLine: sirve para comparar consolas entre sí (dentro de Herdr vs. pestaña de WT sola vs. conhost; pwsh vs.
powershell 5.1) y antes/después de un cambio de config. Corre igual en pwsh 7 y en Windows PowerShell 5.1.

    pwsh -NoProfile -File cursor-latency.ps1 [-N 200] [-Out resultado.json] [-Label "herdr pwsh"]

Sale por pantalla (una línea) y, con -Out, un JSON con todas las muestras. Si la consola no contesta al DSR en 2 s
(no hay terminal VT detrás), lo dice y sale con 2.
#>
param(
    [int]$N = 200,
    [string]$Out = "",
    [string]$Label = ""
)

$ErrorActionPreference = "Stop"
$esc = [char]27
try { [Console]::TreatControlCAsInput = $true } catch { }

# La respuesta al DSR la genera ConPTY (OpenConsole) y la mete en la cola de entrada como secuencia VT: sólo llega a
# ReadKey si la entrada está en modo VT (ENABLE_VIRTUAL_TERMINAL_INPUT, 0x200; PSReadLine lo enciende sólo mientras
# lee una línea) y la salida interpreta VT (ENABLE_VIRTUAL_TERMINAL_PROCESSING, 0x4). Se dejan como estaban al salir.
Add-Type -Namespace AgentNav -Name ConMode -MemberDefinition @"
[DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
"@
$hIn = [AgentNav.ConMode]::GetStdHandle(-10); $hOut = [AgentNav.ConMode]::GetStdHandle(-11)
$inMode = 0; $outMode = 0
[void][AgentNav.ConMode]::GetConsoleMode($hIn, [ref]$inMode); [void][AgentNav.ConMode]::GetConsoleMode($hOut, [ref]$outMode)
[void][AgentNav.ConMode]::SetConsoleMode($hIn, ($inMode -bor 0x200) -band (-bnot 0x2) -band (-bnot 0x4))   # VT input, sin line input ni echo
[void][AgentNav.ConMode]::SetConsoleMode($hOut, $outMode -bor 0x4)
$restore = { [void][AgentNav.ConMode]::SetConsoleMode($hIn, $inMode); [void][AgentNav.ConMode]::SetConsoleMode($hOut, $outMode) }

function Read-Dsr([int]$timeoutMs) {
    # Lee teclas hasta la 'R' que cierra ESC[fila;colR. Devuelve $true si llegó, $false si venció el tiempo.
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $buf = ""
    while ($sw.ElapsedMilliseconds -lt $timeoutMs) {
        if ([Console]::KeyAvailable) {
            $k = [Console]::ReadKey($true)
            $buf += $k.KeyChar
            if ($k.KeyChar -eq 'R' -and $buf -match '\[\d+;\d+R') { return $true }
        } else {
            [Threading.Thread]::SpinWait(200)
        }
    }
    return $false
}

# Prueba de vida: ¿contesta el DSR?
[Console]::Out.Write("$esc[6n")
if (-not (Read-Dsr 2000)) {
    & $restore
    Write-Host "la consola no responde al DSR (ESC[6n): no hay terminal VT detrás, o la entrada no llega a este proceso."
    if ($Out) { [IO.File]::WriteAllText($Out, '{"label":"' + $Label + '","error":"sin respuesta al DSR"}', (New-Object Text.UTF8Encoding $false)) }
    exit 2
}

$samples = New-Object System.Collections.Generic.List[double]
$chars = "abcdefghijklmnopqrstuvwxyz0123456789"
$sw = [Diagnostics.Stopwatch]::StartNew()
$lost = 0
for ($i = 0; $i -lt $N; $i++) {
    $c = $chars[$i % $chars.Length]
    $t0 = $sw.Elapsed.TotalMilliseconds
    [Console]::Out.Write("$c$esc[6n")
    if (Read-Dsr 2000) { $samples.Add($sw.Elapsed.TotalMilliseconds - $t0) } else { $lost++ }
    if (($i + 1) % 60 -eq 0) { [Console]::Out.Write("`r`n") }
}
[Console]::Out.Write("`r`n")
& $restore

$sorted = $samples | Sort-Object
function Pct([double]$p) { if ($sorted.Count -eq 0) { return 0 }; $sorted[[Math]::Min($sorted.Count - 1, [int][Math]::Floor($p * $sorted.Count))] }
$hostName = "conhost/otro"
if ($env:HERDR_ENV) { $hostName = "herdr" } elseif ($env:WT_SESSION) { $hostName = "windows-terminal" }
$res = [ordered]@{
    label    = $Label
    host     = $hostName
    shell    = "$($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)"
    n        = $samples.Count
    lost     = $lost
    min_ms   = [Math]::Round(($sorted | Select-Object -First 1), 2)
    p50_ms   = [Math]::Round((Pct 0.50), 2)
    p90_ms   = [Math]::Round((Pct 0.90), 2)
    p99_ms   = [Math]::Round((Pct 0.99), 2)
    max_ms   = [Math]::Round(($sorted | Select-Object -Last 1), 2)
    mean_ms  = [Math]::Round((($samples | Measure-Object -Average).Average), 2)
    when     = (Get-Date).ToString("s")
}
$line = "{0,-28} {1,-16} {2,-22} n={3} perdidas={4} min={5} p50={6} p90={7} p99={8} max={9} ms" -f $res.label, $res.host, $res.shell, $res.n, $res.lost, $res.min_ms, $res.p50_ms, $res.p90_ms, $res.p99_ms, $res.max_ms
Write-Host $line
if ($Out) {
    $res.samples = @($samples)
    [IO.File]::WriteAllText($Out, ($res | ConvertTo-Json -Depth 3), (New-Object Text.UTF8Encoding $false))
}
exit 0
