param([ValidateRange(1024,65535)][int]$Port = 49173, [switch]$Practice)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Push-Location (Join-Path $taskRoot 'JevApp')
try {
    $terminalArgs = @('-3', '-m', 'jev_app.human', '--port', $Port)
    if ($Practice) { $terminalArgs += '--practice' }
    py @terminalArgs
    exit $LASTEXITCODE
} finally { Pop-Location }
