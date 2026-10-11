param([ValidateRange(1024,65535)][int]$Port = 49173)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Push-Location (Join-Path $taskRoot 'JevApp')
try {
    py -3 -m jev_app.human --port $Port
    exit $LASTEXITCODE
} finally { Pop-Location }
