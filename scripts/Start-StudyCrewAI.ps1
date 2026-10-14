#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Demo,
    [ValidateRange(1024, 65535)][int]$Port = 8003,
    [ValidateRange(1, 20)][int]$ModelTimeoutSeconds = 20,
    [ValidateRange(1, 24)][int]$AgentTimeoutSeconds = 24,
    [ValidateRange(30, 600)][int]$WarmupTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$aiStartRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$aiStartPython = Join-Path $aiStartRoot '.venv\Scripts\python.exe'
$aiStartStore = Join-Path $aiStartRoot 'var\ai'
$aiStartModels = Join-Path $aiStartStore 'models'
$aiStartEndpoint = 'http://127.0.0.1:11434'
$aiStartChatModel = 'qwen3.5:9b-q4_K_M'
$aiStartEmbeddingModel = 'qwen3-embedding:0.6b'
$aiStartBinary = @('runtime\ollama.exe', 'ollama-v0.40.3\ollama.exe', 'ollama\ollama.exe') |
    ForEach-Object { Join-Path $aiStartStore $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not (Test-Path -LiteralPath $aiStartPython -PathType Leaf)) { throw 'Install the documented Python dependencies before starting StudyCrew AI.' }
if (-not $aiStartBinary) { throw 'The portable model runtime is missing. Run scripts/Setup-StudyCrewAI.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $aiStartRoot 'static\workspace\index.html') -PathType Leaf)) { throw 'Build the frontend before starting StudyCrew AI.' }

$aiStartNames = @('DJANGO_ENVIRONMENT', 'DJANGO_DEBUG', 'DJANGO_ALLOWED_HOSTS', 'DJANGO_CSRF_TRUSTED_ORIGINS',
    'DB_ENGINE', 'SQLITE_PATH', 'MEDIA_PATH', 'EMAIL_BACKEND', 'EMAIL_FILE_PATH', 'PUBLIC_BASE_URL',
    'ASYNC_EXPORTS', 'ASYNC_REMINDERS', 'MAINTENANCE_MODE', 'OLLAMA_HOST', 'OLLAMA_MODELS', 'OLLAMA_CONTEXT_LENGTH',
    'OLLAMA_NUM_PARALLEL', 'OLLAMA_MAX_LOADED_MODELS', 'OLLAMA_MAX_QUEUE', 'OLLAMA_KEEP_ALIVE', 'OLLAMA_NO_CLOUD', 'OLLAMA_NOHISTORY',
    'OLLAMA_DEBUG', 'OLLAMA_DEBUG_LOG_REQUESTS',
    'RAG_PROVIDER', 'RAG_BASE_URL', 'RAG_MODEL', 'RAG_EMBEDDING_MODEL', 'RAG_EMBEDDING_DIMENSIONS',
    'RAG_EMBEDDING_BATCH_SIZE', 'RAG_EMBEDDING_REVISION', 'RAG_RETRIEVAL_MODE', 'RAG_DISABLE_THINKING',
    'RAG_NUM_CTX', 'RAG_MAX_OUTPUT_TOKENS', 'RAG_KEEP_ALIVE', 'RAG_TIMEOUT_SECONDS', 'RAG_AGENT_TIMEOUT_SECONDS', 'RAG_API_KEY')
$aiStartPrevious = @{}
foreach ($aiStartName in $aiStartNames) { $aiStartPrevious[$aiStartName] = [Environment]::GetEnvironmentVariable($aiStartName, 'Process') }
$aiStartOwned = @()
$aiStartPreviousDirectory = Get-Location
$aiStartStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$aiStartLogs = Join-Path $aiStartStore 'logs'

function Assert-AIStartLoopback {
    foreach ($aiStartListener in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
        if ($aiStartListener.Port -eq 11434 -and -not [Net.IPAddress]::IsLoopback($aiStartListener.Address)) {
            throw 'Port 11434 is listening outside loopback. Restrict the existing model server first.'
        }
    }
}

function Test-AIStartHealth {
    Assert-AIStartLoopback
    try {
        $aiStartHealth = Invoke-RestMethod -Uri "$aiStartEndpoint/api/version" -NoProxy -MaximumRedirection 0 -TimeoutSec 3
        return ($aiStartHealth.version -is [string] -and [bool]$aiStartHealth.version)
    } catch { return $false }
}

try {
    Set-Location -LiteralPath $aiStartRoot
    foreach ($aiStartDataPath in @((Join-Path $aiStartRoot 'var'), $aiStartStore, $aiStartModels)) {
        if ((Test-Path -LiteralPath $aiStartDataPath) -and ((Get-Item -LiteralPath $aiStartDataPath).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'AI model storage must not use symbolic links or junctions outside the workspace drive.'
        }
    }
    New-Item -ItemType Directory -Path $aiStartModels -Force | Out-Null
    New-Item -ItemType Directory -Path $aiStartLogs -Force | Out-Null
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_MODELS = $aiStartModels
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '2'
    $env:OLLAMA_MAX_QUEUE = '8'
    $env:OLLAMA_KEEP_ALIVE = '10m'
    $env:OLLAMA_NO_CLOUD = 'true'
    $env:OLLAMA_NOHISTORY = 'true'
    $env:OLLAMA_DEBUG = 'false'
    $env:OLLAMA_DEBUG_LOG_REQUESTS = 'false'
    $env:RAG_PROVIDER = 'ollama'
    $env:RAG_BASE_URL = $aiStartEndpoint
    $env:RAG_MODEL = $aiStartChatModel
    $env:RAG_EMBEDDING_MODEL = $aiStartEmbeddingModel
    $env:RAG_EMBEDDING_DIMENSIONS = '1024'
    $env:RAG_EMBEDDING_BATCH_SIZE = '16'
    $env:RAG_RETRIEVAL_MODE = 'hybrid'
    $env:RAG_DISABLE_THINKING = 'true'
    $env:RAG_NUM_CTX = '8192'
    $env:RAG_MAX_OUTPUT_TOKENS = '1200'
    $env:RAG_KEEP_ALIVE = '10m'
    $env:RAG_TIMEOUT_SECONDS = [string]$ModelTimeoutSeconds
    $env:RAG_AGENT_TIMEOUT_SECONDS = [string]$AgentTimeoutSeconds
    $env:RAG_API_KEY = ''
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
    $aiStartWebProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $aiStartWebProbe.Start() } finally { $aiStartWebProbe.Stop() }
    if (Test-AIStartHealth) {
        Write-Host 'Reusing the healthy loopback Ollama service; this launcher will leave it running.'
    } else {
        $aiStartModelProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 11434)
        try { $aiStartModelProbe.Start() } finally { $aiStartModelProbe.Stop() }
        $aiStartModelProcess = Start-Process -FilePath $aiStartBinary -WorkingDirectory $aiStartRoot -ArgumentList @('serve') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $aiStartLogs "launch-$aiStartStamp-model.out.log") -RedirectStandardError (Join-Path $aiStartLogs "launch-$aiStartStamp-model.err.log")
        $aiStartOwned += $aiStartModelProcess
        $aiStartReadyBy = [DateTime]::UtcNow.AddSeconds(30)
        do {
            $aiStartModelProcess.Refresh()
            if ($aiStartModelProcess.HasExited) { throw 'The launcher-owned model server exited. Check var/ai/logs.' }
            $aiStartModelReady = Test-AIStartHealth
            if (-not $aiStartModelReady) { Start-Sleep -Milliseconds 250 }
        } while (-not $aiStartModelReady -and [DateTime]::UtcNow -lt $aiStartReadyBy)
        if (-not $aiStartModelReady) { throw 'The model server did not become healthy.' }
    }
    $aiStartTags = Invoke-RestMethod -Uri "$aiStartEndpoint/api/tags" -NoProxy -MaximumRedirection 0 -TimeoutSec 5
    $aiStartPresent = @($aiStartTags.models | ForEach-Object name)
    if ($aiStartChatModel -notin $aiStartPresent -or $aiStartEmbeddingModel -notin $aiStartPresent) { throw 'The selected models are missing. Run scripts/Setup-StudyCrewAI.ps1 first.' }
    $aiStartEmbeddingDigest = @($aiStartTags.models | Where-Object name -eq $aiStartEmbeddingModel)[0].digest
    if ($aiStartEmbeddingDigest -notmatch '^[0-9a-f]{64}$') { throw 'The embedding model has no verifiable cache revision.' }
    $env:RAG_EMBEDDING_REVISION = $aiStartEmbeddingDigest
    Write-Host 'Warming both models with synthetic input before accepting project questions.'
    $aiStartChatBody = @{ model = $aiStartChatModel; messages = @(@{ role = 'user'; content = 'Reply only READY.' }); think = $false; stream = $false; keep_alive = '10m'; options = @{ num_ctx = 8192; num_predict = 16; temperature = 0 } } | ConvertTo-Json -Depth 8 -Compress
    $aiStartChatReply = Invoke-RestMethod -Uri "$aiStartEndpoint/api/chat" -Method Post -Body $aiStartChatBody -ContentType 'application/json' -NoProxy -MaximumRedirection 0 -TimeoutSec $WarmupTimeoutSeconds
    if ($aiStartChatReply.done -ne $true -or -not $aiStartChatReply.message.content) { throw 'Chat model warmup did not return a complete response.' }
    $aiStartEmbeddingBody = @{ model = $aiStartEmbeddingModel; input = @('StudyCrew project knowledge.'); keep_alive = '10m' } | ConvertTo-Json -Depth 4 -Compress
    $aiStartEmbeddingReply = Invoke-RestMethod -Uri "$aiStartEndpoint/api/embed" -Method Post -Body $aiStartEmbeddingBody -ContentType 'application/json' -NoProxy -MaximumRedirection 0 -TimeoutSec $WarmupTimeoutSeconds
    if (-not $aiStartEmbeddingReply.embeddings -or $aiStartEmbeddingReply.embeddings[0].Count -eq 0) { throw 'Embedding model warmup returned no vector.' }
    & $aiStartBinary 'ps'
    & $aiStartPython 'manage.py' 'check'
    if ($LASTEXITCODE -ne 0) { throw 'Django configuration checks failed.' }
    & $aiStartPython 'manage.py' 'migrate' '--noinput'
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    if ($Demo) {
        & $aiStartPython 'manage.py' 'seed_demo'
        if ($LASTEXITCODE -ne 0) { throw 'Demo seeding failed.' }
    }
    $aiStartApplication = Start-Process -FilePath $aiStartPython -WorkingDirectory $aiStartRoot -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$Port", '--noreload', '--insecure') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $aiStartLogs "launch-$aiStartStamp-app.out.log") -RedirectStandardError (Join-Path $aiStartLogs "launch-$aiStartStamp-app.err.log")
    $aiStartOwned += $aiStartApplication
    $aiStartWorker = Start-Process -FilePath $aiStartPython -WorkingDirectory $aiStartRoot -ArgumentList @('manage.py', 'run_delivery_worker', '--interval', '10', '--limit', '50') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $aiStartLogs "launch-$aiStartStamp-worker.out.log") -RedirectStandardError (Join-Path $aiStartLogs "launch-$aiStartStamp-worker.err.log")
    $aiStartOwned += $aiStartWorker
    Write-Host "StudyCrew AI is starting at http://127.0.0.1:$Port/app/"
    Write-Host "Data: $(if ($Demo) { 'isolated demo' } else { 'existing local accounts' }); models: $aiStartChatModel / $aiStartEmbeddingModel."
    Write-Host 'Keep this terminal open. Ctrl+C stops only this run''s application, worker and any model server it created.'
    while ($true) {
        foreach ($aiStartProcess in $aiStartOwned) {
            $aiStartProcess.Refresh()
            if ($aiStartProcess.HasExited) { throw 'A launcher-owned process exited. Check var/ai/logs.' }
        }
        if (-not (Test-AIStartHealth)) { throw 'The model service stopped responding. The launcher-owned application will be stopped.' }
        Start-Sleep -Seconds 2
    }
}
finally {
    for ($aiStartIndex = $aiStartOwned.Count - 1; $aiStartIndex -ge 0; $aiStartIndex--) {
        $aiStartProcess = $aiStartOwned[$aiStartIndex]
        try { $aiStartProcess.Refresh(); if (-not $aiStartProcess.HasExited) { $aiStartProcess.Kill($true); $aiStartProcess.WaitForExit(5000) | Out-Null } }
        catch { Write-Warning 'A launcher-owned process was already unavailable during cleanup.' }
        finally { $aiStartProcess.Dispose() }
    }
    foreach ($aiStartName in $aiStartNames) { [Environment]::SetEnvironmentVariable($aiStartName, $aiStartPrevious[$aiStartName], 'Process') }
    Set-Location -LiteralPath $aiStartPreviousDirectory.Path
}
