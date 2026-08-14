# Stop stale API on port 8000, reinstall editable package, start current server.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$port = 8000
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping PID $procId ($($proc.ProcessName)) on port $port ..."
            Stop-Process -Id $procId -Force
        }
    }
    Start-Sleep -Seconds 2
}

Write-Host "Installing editable package ..."
py -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install -e . failed."
    exit 1
}

Write-Host "Starting API from repo source ..."
& "$PSScriptRoot\start-enterprise-ui.ps1"
