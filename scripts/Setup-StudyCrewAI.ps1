#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(30, 600)][int]$WarmupTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$aiSetupRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$aiSetupStore = Join-Path $aiSetupRoot 'var\ai'
$aiSetupRuntime = Join-Path $aiSetupStore 'runtime'
$aiSetupModels = Join-Path $aiSetupStore 'models'
$aiSetupArchive = Join-Path $aiSetupStore 'ollama-windows-amd64-v0.40.3.zip'
$aiSetupBinary = Join-Path $aiSetupRuntime 'ollama.exe'
$aiSetupVersion = 'v0.40.3'
$aiSetupSHA256 = 'e5ecff02dfc7cae8ddf6d6b7a7ac5f727ffeedf4491f44ae75ff5b0820dbbbd5'
$aiSetupExistingBinary = Join-Path $aiSetupStore 'ollama-v0.40.3\ollama.exe'
# Reuse the pinned runtime prepared for this checkout instead of extracting a
# second copy. The cached archive must still match the official release digest.
if ((Test-Path -LiteralPath $aiSetupExistingBinary -PathType Leaf) -and (Test-Path -LiteralPath $aiSetupArchive -PathType Leaf) -and
    (Get-FileHash -LiteralPath $aiSetupArchive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $aiSetupSHA256) {
    $aiSetupBinary = $aiSetupExistingBinary
}
$aiSetupReleaseAPI = 'https://api.github.com/repos/ollama/ollama/releases/tags/v0.40.3'
$aiSetupDownload = 'https://github.com/ollama/ollama/releases/download/v0.40.3/ollama-windows-amd64.zip'
$aiSetupChatModel = 'qwen3.5:9b-q4_K_M'
$aiSetupEmbeddingModel = 'qwen3-embedding:0.6b'
$aiSetupEndpoint = 'http://127.0.0.1:11434'
$aiSetupOwned = $null
$aiSetupStage = $null
$aiSetupPartial = $null
$aiSetupNames = @('OLLAMA_HOST', 'OLLAMA_MODELS', 'OLLAMA_CONTEXT_LENGTH', 'OLLAMA_NUM_PARALLEL',
    'OLLAMA_MAX_LOADED_MODELS', 'OLLAMA_MAX_QUEUE', 'OLLAMA_KEEP_ALIVE', 'OLLAMA_NO_CLOUD', 'OLLAMA_NOHISTORY',
    'OLLAMA_DEBUG', 'OLLAMA_DEBUG_LOG_REQUESTS')
$aiSetupPrevious = @{}
foreach ($aiSetupName in $aiSetupNames) {
    $aiSetupPrevious[$aiSetupName] = [Environment]::GetEnvironmentVariable($aiSetupName, 'Process')
}

function Assert-AISetupPath([string]$Path) {
    $aiSetupAbsolute = [IO.Path]::GetFullPath($Path)
    $aiSetupBoundary = [IO.Path]::GetFullPath($aiSetupStore).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $aiSetupAbsolute.StartsWith($aiSetupBoundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The AI runtime path must stay inside this workspace var/ai directory.'
    }
    if ((Test-Path -LiteralPath $aiSetupAbsolute) -and ((Get-Item -LiteralPath $aiSetupAbsolute).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'AI runtime paths must not be symbolic links or junctions.'
    }
    return $aiSetupAbsolute
}

function Assert-AISetupLoopback {
    $aiSetupListeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    foreach ($aiSetupListener in $aiSetupListeners) {
        if ($aiSetupListener.Port -eq 11434 -and -not [Net.IPAddress]::IsLoopback($aiSetupListener.Address)) {
            throw 'Port 11434 is listening outside loopback. Restrict the existing service before continuing.'
        }
    }
}

function Get-AISetupHealth {
    Assert-AISetupLoopback
    try {
        $aiSetupHealth = Invoke-RestMethod -Uri "$aiSetupEndpoint/api/version" -NoProxy -MaximumRedirection 0 -TimeoutSec 3
        if ($aiSetupHealth.version -is [string] -and $aiSetupHealth.version) { return $aiSetupHealth }
    } catch { return $null }
    return $null
}

function Get-AISetupModels {
    $aiSetupTags = Invoke-RestMethod -Uri "$aiSetupEndpoint/api/tags" -NoProxy -MaximumRedirection 0 -TimeoutSec 5
    return @($aiSetupTags.models)
}

try {
    $aiSetupVar = Join-Path $aiSetupRoot 'var'
    if ((Test-Path -LiteralPath $aiSetupVar) -and ((Get-Item -LiteralPath $aiSetupVar).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The workspace var directory must not be a symbolic link or junction.'
    }
    New-Item -ItemType Directory -Path $aiSetupStore -Force | Out-Null
    if ((Get-Item -LiteralPath $aiSetupStore).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'The workspace var/ai directory must not be a symbolic link or junction.'
    }
    Assert-AISetupPath $aiSetupRuntime | Out-Null
    Assert-AISetupPath $aiSetupModels | Out-Null
    New-Item -ItemType Directory -Path $aiSetupModels -Force | Out-Null
    if (-not (Test-Path -LiteralPath $aiSetupBinary -PathType Leaf)) {
        if (Test-Path -LiteralPath $aiSetupRuntime) {
            throw 'An incomplete var/ai/runtime already exists. Inspect it before replacing it.'
        }
        if (-not (Test-Path -LiteralPath $aiSetupArchive -PathType Leaf)) {
            $aiSetupDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($aiSetupStore))
            if ($aiSetupDrive.AvailableFreeSpace -lt 16GB) { throw 'Reserve at least 16 GiB free on the workspace drive for runtime and model files.' }
            $aiSetupRelease = Invoke-RestMethod -Uri $aiSetupReleaseAPI -Headers @{ 'User-Agent' = 'StudyCrew-AI-Setup'; Accept = 'application/vnd.github+json' } -TimeoutSec 30
            $aiSetupAsset = @($aiSetupRelease.assets | Where-Object name -eq 'ollama-windows-amd64.zip')
            if ($aiSetupAsset.Count -ne 1 -or $aiSetupAsset[0].digest -ne "sha256:$aiSetupSHA256" -or $aiSetupAsset[0].browser_download_url -ne $aiSetupDownload) {
                throw 'The official release metadata does not match the pinned runtime checksum.'
            }
            $aiSetupPartial = Assert-AISetupPath (Join-Path $aiSetupStore ("download-{0}.partial" -f [Guid]::NewGuid().ToString('N')))
            Write-Host 'Downloading the pinned portable Ollama runtime to this workspace drive.'
            Invoke-WebRequest -Uri $aiSetupDownload -OutFile $aiSetupPartial -TimeoutSec 1800
            if ((Get-FileHash -LiteralPath $aiSetupPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $aiSetupSHA256) {
                throw 'The runtime download failed its SHA-256 check.'
            }
            Assert-AISetupPath $aiSetupArchive | Out-Null
            Move-Item -LiteralPath $aiSetupPartial -Destination $aiSetupArchive
            $aiSetupPartial = $null
        }
        if ((Get-FileHash -LiteralPath $aiSetupArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $aiSetupSHA256) {
            throw 'The cached runtime archive is incomplete or failed SHA-256 verification. It was not overwritten.'
        }
        $aiSetupStage = Assert-AISetupPath (Join-Path $aiSetupStore ("extract-{0}" -f [Guid]::NewGuid().ToString('N')))
        New-Item -ItemType Directory -Path $aiSetupStage | Out-Null
        $aiSetupZip = [IO.Compression.ZipFile]::OpenRead($aiSetupArchive)
        try {
            $aiSetupStageBoundary = [IO.Path]::GetFullPath($aiSetupStage).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
            foreach ($aiSetupEntry in $aiSetupZip.Entries) {
                $aiSetupEntryPath = [IO.Path]::GetFullPath((Join-Path $aiSetupStage $aiSetupEntry.FullName))
                $aiSetupEntryType = ($aiSetupEntry.ExternalAttributes -shr 16) -band 0xF000
                if (-not $aiSetupEntryPath.StartsWith($aiSetupStageBoundary, [StringComparison]::OrdinalIgnoreCase) -or $aiSetupEntryType -eq 0xA000) {
                    throw 'The runtime archive contains an unsafe extraction path.'
                }
            }
        } finally { $aiSetupZip.Dispose() }
        [IO.Compression.ZipFile]::ExtractToDirectory($aiSetupArchive, $aiSetupStage)
        if (-not (Test-Path -LiteralPath (Join-Path $aiSetupStage 'ollama.exe') -PathType Leaf)) { throw 'The runtime archive has no Ollama executable.' }
        Set-Content -LiteralPath (Join-Path $aiSetupStage '.release-sha256') -Value $aiSetupSHA256 -NoNewline
        Assert-AISetupPath $aiSetupStage | Out-Null
        Assert-AISetupPath $aiSetupRuntime | Out-Null
        Move-Item -LiteralPath $aiSetupStage -Destination $aiSetupRuntime
        $aiSetupStage = $null
    }

    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_MODELS = $aiSetupModels
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '2'
    $env:OLLAMA_MAX_QUEUE = '8'
    $env:OLLAMA_KEEP_ALIVE = '10m'
    $env:OLLAMA_NO_CLOUD = 'true'
    $env:OLLAMA_NOHISTORY = 'true'
    $env:OLLAMA_DEBUG = 'false'
    $env:OLLAMA_DEBUG_LOG_REQUESTS = 'false'
    $aiSetupHealth = Get-AISetupHealth
    if ($aiSetupHealth) {
        $aiSetupPresent = @(Get-AISetupModels | ForEach-Object name)
        if ($aiSetupChatModel -notin $aiSetupPresent -or $aiSetupEmbeddingModel -notin $aiSetupPresent) {
            throw 'An existing Ollama server lacks the selected models. Its model-store drive is unknown. Quit it yourself, then rerun setup so downloads stay on the workspace drive.'
        }
        Write-Host 'Reusing the existing healthy loopback Ollama server. No models will be pulled into its unknown store.'
    } else {
        $aiSetupProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 11434)
        try { $aiSetupProbe.Start() } finally { $aiSetupProbe.Stop() }
        $aiSetupLogs = Join-Path $aiSetupStore 'logs'
        New-Item -ItemType Directory -Path $aiSetupLogs -Force | Out-Null
        $aiSetupStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $aiSetupOwned = Start-Process -FilePath $aiSetupBinary -ArgumentList @('serve') -WorkingDirectory $aiSetupRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $aiSetupLogs "setup-$aiSetupStamp.out.log") -RedirectStandardError (Join-Path $aiSetupLogs "setup-$aiSetupStamp.err.log")
        $aiSetupReadyBy = [DateTime]::UtcNow.AddSeconds(30)
        do {
            $aiSetupOwned.Refresh()
            if ($aiSetupOwned.HasExited) { throw 'The launcher-owned model server exited. Check var/ai/logs.' }
            $aiSetupHealth = Get-AISetupHealth
            if (-not $aiSetupHealth) { Start-Sleep -Milliseconds 250 }
        } while (-not $aiSetupHealth -and [DateTime]::UtcNow -lt $aiSetupReadyBy)
        if (-not $aiSetupHealth) { throw 'The launcher-owned model server did not become healthy.' }
        $aiSetupDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($aiSetupModels))
        if ($aiSetupDrive.AvailableFreeSpace -lt 12GB) { throw 'Reserve at least 12 GiB free on the workspace drive before pulling the selected models.' }
        foreach ($aiSetupModel in @($aiSetupChatModel, $aiSetupEmbeddingModel)) {
            & $aiSetupBinary 'pull' $aiSetupModel
            if ($LASTEXITCODE -ne 0) { throw "Model pull failed for $aiSetupModel. Existing model files were retained." }
        }
    }
    $aiSetupGPU = @()
    $aiSetupNvidia = Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue
    if ($aiSetupNvidia) {
        $aiSetupGPU = @(& $aiSetupNvidia.Source '--query-gpu=name,memory.total,memory.free' '--format=csv,noheader,nounits')
        if ($LASTEXITCODE -ne 0) { $aiSetupGPU = @(); Write-Warning 'GPU information was unavailable. Confirm offload with Ollama ps after warmup.' }
        else { $aiSetupGPU | ForEach-Object { Write-Host "GPU (name, total MiB, free MiB): $_" } }
    } else { Write-Warning 'nvidia-smi was not found. Ollama may use another GPU backend or CPU; measure performance before deployment.' }
    Write-Host 'Warming the chat and embedding models with synthetic input only.'
    $aiSetupWarmChat = @{ model = $aiSetupChatModel; messages = @(@{ role = 'user'; content = 'Reply only READY.' }); stream = $false; think = $false; keep_alive = '10m'; options = @{ num_ctx = 8192; num_predict = 16; temperature = 0 } } | ConvertTo-Json -Depth 8 -Compress
    $aiSetupChatReply = Invoke-RestMethod -Uri "$aiSetupEndpoint/api/chat" -Method Post -Body $aiSetupWarmChat -ContentType 'application/json' -NoProxy -MaximumRedirection 0 -TimeoutSec $WarmupTimeoutSeconds
    if ($aiSetupChatReply.done -ne $true -or -not $aiSetupChatReply.message.content) { throw 'Chat model warmup did not return a complete response.' }
    $aiSetupWarmEmbedding = @{ model = $aiSetupEmbeddingModel; input = @('StudyCrew project knowledge.'); keep_alive = '10m' } | ConvertTo-Json -Depth 4 -Compress
    $aiSetupEmbedReply = Invoke-RestMethod -Uri "$aiSetupEndpoint/api/embed" -Method Post -Body $aiSetupWarmEmbedding -ContentType 'application/json' -NoProxy -MaximumRedirection 0 -TimeoutSec $WarmupTimeoutSeconds
    if (-not $aiSetupEmbedReply.embeddings -or $aiSetupEmbedReply.embeddings[0].Count -eq 0) { throw 'Embedding model warmup returned no vector.' }
    & $aiSetupBinary 'ps'
    $aiSetupReceipt = @{ runtime_release = $aiSetupVersion; archive_sha256 = $aiSetupSHA256; server_version = $aiSetupHealth.version;
        configured_model_store = $aiSetupModels; model_store_verified = ($null -ne $aiSetupOwned); reused_existing_server = ($null -eq $aiSetupOwned); models = @(Get-AISetupModels | Select-Object name,digest,size);
        gpu = $aiSetupGPU; warmed_at_utc = [DateTime]::UtcNow.ToString('o'); embedding_dimensions = $aiSetupEmbedReply.embeddings[0].Count }
    $aiSetupReceipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $aiSetupStore 'setup-receipt.json') -Encoding utf8
    Write-Host 'AI setup finished. Run scripts/Start-StudyCrewAI.ps1 to start the application, worker and model service.'
}
finally {
    try {
        if ($aiSetupOwned) {
            try { $aiSetupOwned.Refresh(); if (-not $aiSetupOwned.HasExited) { $aiSetupOwned.Kill($true); $aiSetupOwned.WaitForExit(5000) | Out-Null } }
            finally { $aiSetupOwned.Dispose() }
        }
        if ($aiSetupStage -and (Test-Path -LiteralPath $aiSetupStage)) {
            $aiSetupCleanup = Assert-AISetupPath $aiSetupStage
            Remove-Item -LiteralPath $aiSetupCleanup -Recurse -Force
        }
        if ($aiSetupPartial -and (Test-Path -LiteralPath $aiSetupPartial)) {
            $aiSetupCleanup = Assert-AISetupPath $aiSetupPartial
            Remove-Item -LiteralPath $aiSetupCleanup -Force
        }
    } finally {
        foreach ($aiSetupName in $aiSetupNames) { [Environment]::SetEnvironmentVariable($aiSetupName, $aiSetupPrevious[$aiSetupName], 'Process') }
    }
}
