param([int]$Port = 8095)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '先に Setup.ps1 を実行してください。'
}
& $taskPython -m app.server --port $Port
