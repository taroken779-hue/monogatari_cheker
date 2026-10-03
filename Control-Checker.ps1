param([ValidateSet('Start','Stop')][string]$Action, [int]$Port = 8095)
$ErrorActionPreference = 'Stop'
$taskBase = "http://127.0.0.1:$Port"
function Get-Checker {
    try { $taskConfig = Invoke-RestMethod -Uri "$taskBase/api/config" -TimeoutSec 2 }
    catch { return $null }
    if ($taskConfig.app -ne 'monogatari-checker' -or $taskConfig.root -ne $PSScriptRoot) {
        throw 'The port is used by another application. No process was stopped.'
    }
    return $taskConfig
}
try {
    $taskExisting = Get-Checker
    if ($Action -eq 'Stop') {
        if (-not $taskExisting) { Write-Host 'Monogatari Checker is already stopped.'; exit 0 }
        Invoke-RestMethod -Method Post -Uri "$taskBase/api/shutdown" -Headers @{ 'X-Checker-Token' = $taskExisting.token } -TimeoutSec 5 | Out-Null
        for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
            Start-Sleep -Milliseconds 200
            if (-not (Get-Checker)) { Write-Host 'Monogatari Checker stopped.'; exit 0 }
        }
        throw 'Shutdown is taking longer than expected. Run Start-Checker.ps1 to view diagnostics.'
    }
    if (-not $taskExisting) {
        $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run Setup.ps1 first.' }
        $taskRuntimeDir = Join-Path $PSScriptRoot '.runtime'
        New-Item -ItemType Directory -Force -Path $taskRuntimeDir | Out-Null
        $taskStart = New-Object System.Diagnostics.ProcessStartInfo
        $taskStart.FileName = $taskPython
        $taskStart.Arguments = "-m app.server --port $Port"
        $taskStart.WorkingDirectory = $PSScriptRoot
        $taskStart.UseShellExecute = $false
        $taskStart.CreateNoWindow = $true
        [System.Diagnostics.Process]::Start($taskStart) | Out-Null
        for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
            Start-Sleep -Milliseconds 250
            $taskExisting = Get-Checker
            if ($taskExisting) { break }
        }
        if (-not $taskExisting) { throw 'Server startup failed. Run Start-Checker.ps1 to view diagnostics.' }
    }
    Write-Host "Monogatari Checker is running: $taskBase"
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
