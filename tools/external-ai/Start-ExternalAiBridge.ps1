param([string]$Config)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Config) { $Config = Join-Path $taskRoot 'ExternalAi.local.json' }
& (Join-Path $taskRoot 'YgoMaster\YgoMaster.exe') --external-ai-bridge-only --external-ai-config $Config
exit $LASTEXITCODE
