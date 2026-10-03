$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskConfigPath = Join-Path $PSScriptRoot 'config.local.json'
if (-not (Test-Path -LiteralPath $taskConfigPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.example.json') -Destination $taskConfigPath
}
$taskConfig = Get-Content -LiteralPath $taskConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskRuntime = $taskConfig.python
if (-not $taskRuntime) { $taskRuntime = (Get-Command python -ErrorAction Stop).Source }
if (-not [IO.Path]::IsPathRooted($taskRuntime)) { $taskRuntime = Join-Path $PSScriptRoot $taskRuntime }
if (-not (Test-Path -LiteralPath $taskRuntime)) { throw 'Configure python in config.local.json.' }
& $taskRuntime -m venv --system-site-packages .venv
if ($LASTEXITCODE -ne 0) { throw 'Python環境の作成に失敗しました。' }
& .\.venv\Scripts\python.exe -c 'import PIL'
if ($LASTEXITCODE -ne 0) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Pillowの導入に失敗しました。' }
}
Write-Host '準備完了: .\Start-Checker.ps1 を実行してください。'
