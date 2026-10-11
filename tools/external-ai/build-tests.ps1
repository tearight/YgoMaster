param([ValidateSet('All','Client','Server')][string]$Suite = 'All')
$ErrorActionPreference = 'Stop'
$taskRepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskTestOutput = Join-Path $taskRepoRoot '.local\external-ai-tests'
New-Item -ItemType Directory -Path $taskTestOutput -Force | Out-Null
Push-Location $taskRepoRoot
try {
    if ($Suite -ne 'Server') {
        $taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        $taskExe = Join-Path $taskTestOutput 'InputSessionChecks.exe'
        & $taskCompiler /nologo /target:exe /r:System.Web.Extensions.dll /out:$taskExe 'ExternalAi\Protocol.cs' 'YgoMasterServer\Lib\MiniJSON.cs' 'YgoMasterClient\ExternalAi\InputSession.cs' 'tests\ExternalAi\InputSessionChecks.cs'
        if ($LASTEXITCODE -ne 0) { throw 'Input session test compile failed' }
        & $taskExe
        if ($LASTEXITCODE -ne 0) { throw 'Input session checks failed' }
    }
    if ($Suite -ne 'Client') {
        py -3 -m unittest discover -s JevApp/tests -v
        if ($LASTEXITCODE -ne 0) { throw 'Bridge/app checks failed' }
    }
} finally { Pop-Location }
