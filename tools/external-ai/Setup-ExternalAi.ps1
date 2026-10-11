$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskConfig = Join-Path $taskRoot 'ExternalAi.local.json'
$taskTokenPath = Join-Path $taskRoot 'external-ai.token'
if (Test-Path -LiteralPath $taskConfig) {
    if (-not (Test-Path -LiteralPath $taskTokenPath)) { throw 'The local config exists but its token file is missing.' }
    Write-Output $taskConfig
    exit 0
}
if (-not (Test-Path -LiteralPath $taskTokenPath)) {
    $taskRandom = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $taskBytes = New-Object byte[] 32
        $taskRandom.GetBytes($taskBytes)
        [IO.File]::WriteAllText($taskTokenPath, [Convert]::ToBase64String($taskBytes))
    } finally { $taskRandom.Dispose() }
}
$taskSettings = [ordered]@{ enabled = $true; prefix = 'http://127.0.0.1:49172/'; tokenFile = 'external-ai.token'; deadlineSeconds = 120 }
[IO.File]::WriteAllText($taskConfig, ($taskSettings | ConvertTo-Json))
Write-Output $taskConfig
