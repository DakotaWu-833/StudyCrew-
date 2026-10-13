#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Demo,
    [ValidateRange(1024, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$advanceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$advancePython = Join-Path $advanceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $advancePython -PathType Leaf)) {
    throw 'The local virtual environment is missing. Install documented dependencies before using this launcher.'
}

$advanceNames = @('DJANGO_ENVIRONMENT', 'DJANGO_DEBUG', 'DJANGO_ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS', 'DB_ENGINE', 'SQLITE_PATH', 'MEDIA_PATH', 'EMAIL_BACKEND', 'EMAIL_FILE_PATH', 'PUBLIC_BASE_URL', 'ASYNC_EXPORTS', 'ASYNC_REMINDERS', 'MAINTENANCE_MODE')
$advancePrevious = @{}
foreach ($advanceName in $advanceNames) { $advancePrevious[$advanceName] = [Environment]::GetEnvironmentVariable($advanceName, 'Process') }
$advanceProcesses = @()
$advancePreviousDirectory = Get-Location
$advanceStarted = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$advanceLogRoot = Join-Path $advanceRoot 'var\logs'
New-Item -ItemType Directory -Path $advanceLogRoot -Force | Out-Null

try {
    Set-Location -LiteralPath $advanceRoot
    $env:DJANGO_ENVIRONMENT = 'development'
    $env:DJANGO_DEBUG = 'false'
    $env:DJANGO_ALLOWED_HOSTS = '127.0.0.1,localhost,[::1]'
    $env:DJANGO_CSRF_TRUSTED_ORIGINS = "http://127.0.0.1:$Port"
    $env:DB_ENGINE = 'sqlite'
    $env:SQLITE_PATH = if ($Demo) { 'var/advance-preview.sqlite3' } else { 'var/studycrew.sqlite3' }
    $env:MEDIA_PATH = if ($Demo) { 'var/advance-preview-media' } else { 'var/media' }
    $env:EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
    $env:EMAIL_FILE_PATH = if ($Demo) { 'var/advance-preview-emails' } else { 'var/emails' }
    $env:PUBLIC_BASE_URL = "http://127.0.0.1:$Port"
    $env:ASYNC_EXPORTS = 'true'
    $env:ASYNC_REMINDERS = 'true'
    $env:MAINTENANCE_MODE = 'false'

    # Reserve only a loopback endpoint check; an occupied port is never stopped.
    $advanceListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $advanceListener.Start() } finally { $advanceListener.Stop() }
    & $advancePython 'manage.py' 'check'
    if ($LASTEXITCODE -ne 0) { throw 'Django configuration checks failed.' }
    & $advancePython 'manage.py' 'migrate' '--noinput'
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    New-Item -ItemType Directory -Path (Join-Path $advanceRoot $env:MEDIA_PATH) -Force | Out-Null
    if ($Demo) {
        & $advancePython 'manage.py' 'seed_demo'
        if ($LASTEXITCODE -ne 0) { throw 'Demo seeding failed.' }
    }

    $advanceAppOut = Join-Path $advanceLogRoot "advance-$advanceStarted-app.out.log"
    $advanceAppError = Join-Path $advanceLogRoot "advance-$advanceStarted-app.err.log"
    $advanceWorkerOut = Join-Path $advanceLogRoot "advance-$advanceStarted-worker.out.log"
    $advanceWorkerError = Join-Path $advanceLogRoot "advance-$advanceStarted-worker.err.log"
    # DEBUG=false avoids exposing debug tracebacks. Local-only --insecure serves
    # the reviewed static bundle; the listener is always bound to loopback.
    $advanceApplication = Start-Process -FilePath $advancePython -WorkingDirectory $advanceRoot -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$Port", '--noreload', '--insecure') -WindowStyle Hidden -PassThru -RedirectStandardOutput $advanceAppOut -RedirectStandardError $advanceAppError
    $advanceProcesses += $advanceApplication
    $advanceWorker = Start-Process -FilePath $advancePython -WorkingDirectory $advanceRoot -ArgumentList @('manage.py', 'run_delivery_worker', '--interval', '10', '--limit', '50') -WindowStyle Hidden -PassThru -RedirectStandardOutput $advanceWorkerOut -RedirectStandardError $advanceWorkerError
    $advanceProcesses += $advanceWorker
    Write-Host "StudyCrew advance is starting at http://127.0.0.1:$Port/app/"
    Write-Host "Mode: $(if ($Demo) { 'isolated demo' } else { 'normal local database' }). Logs: $advanceLogRoot"
    Write-Host 'Keep this terminal open. Ctrl+C stops only the application and worker created by this run.'

    while ($true) {
        foreach ($advanceProcess in $advanceProcesses) {
            $advanceProcess.Refresh()
            if ($advanceProcess.HasExited) { throw "A launcher-owned process exited ($($advanceProcess.Id)). Check its log in var/logs." }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    foreach ($advanceProcess in $advanceProcesses) {
        try {
            $advanceProcess.Refresh()
            if (-not $advanceProcess.HasExited) {
                # The retained Process object identifies a child created by this
                # launch. Never discover/kill all Python processes or occupied ports.
                $advanceProcess.Kill($true)
                $advanceProcess.WaitForExit(5000) | Out-Null
            }
        } catch { Write-Warning 'A launcher-owned process was already unavailable during cleanup.' }
        finally { $advanceProcess.Dispose() }
    }
    foreach ($advanceName in $advanceNames) { [Environment]::SetEnvironmentVariable($advanceName, $advancePrevious[$advanceName], 'Process') }
    Set-Location -LiteralPath $advancePreviousDirectory.Path
}
