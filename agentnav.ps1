# AgentNav — envoltorio de agentnav.py para PowerShell.
# Alias "agentnav" en el perfil de PowerShell apunta acá.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
& py -I "$PSScriptRoot\agentnav.py" @Rest
exit $LASTEXITCODE
