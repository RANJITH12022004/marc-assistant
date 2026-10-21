# Stays running for the signed-in session and restarts the laptop worker if it stops.
$ErrorActionPreference = "Continue"
$root = "C:\Users\ranjith\mark-laptop"
$log = Join-Path $env:USERPROFILE ".marc\worker.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Write-Log($message) {
    Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format o), $message)
}

function Test-Worker {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8092/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$python = $null
$bundled = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe"
if (Test-Path $bundled) { $python = $bundled }
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source }
}
if (-not $python) {
    Write-Log "python missing"
    exit 1
}

$tokenPath = Join-Path $env:USERPROFILE ".marc\token"
if (-not (Test-Path $tokenPath)) {
    Write-Log "token missing"
    exit 1
}
$env:MARC_TOKEN = (Get-Content -Raw $tokenPath).Trim()
$env:MARC_BIND = "0.0.0.0"
$env:MARC_WORKER_PORT = "8092"
$env:MARC_LAPTOP_ROOT = $root
Set-Location $root
Write-Log "supervisor"

while ($true) {
    if (Test-Worker) {
        Start-Sleep -Seconds 15
        continue
    }
    Write-Log "starting"
    & $python -u "$root\_island\laptop_worker.py" *>> $log
    Write-Log "exited $LASTEXITCODE"
    Start-Sleep -Seconds 3
}
