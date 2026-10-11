param(
    [Parameter(Mandatory=$true)][string]$CardData,
    [string]$Config,
    [ValidateSet('jev','mock')][string]$Provider = 'jev'
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Config) { $Config = Join-Path $taskRoot 'ExternalAi.local.json' }
$Config = [IO.Path]::GetFullPath($Config)
$CardData = [IO.Path]::GetFullPath($CardData)
if ($Provider -eq 'jev' -and [string]::IsNullOrWhiteSpace($env:JEV_API_KEY)) {
    $env:JEV_API_KEY = [Environment]::GetEnvironmentVariable('JEV_API_KEY', 'User')
    if ([string]::IsNullOrWhiteSpace($env:JEV_API_KEY)) { $env:JEV_API_KEY = [Environment]::GetEnvironmentVariable('JEV_API_KEY', 'Machine') }
    if ([string]::IsNullOrWhiteSpace($env:JEV_API_KEY)) { throw 'JEV_API_KEY is not set. The key is read only by the Jev app.' }
}
Push-Location (Join-Path $taskRoot 'JevApp')
try {
    py -3 -m jev_app --bridge-config $Config --provider $Provider --card-data $CardData
    exit $LASTEXITCODE
} finally { Pop-Location }
