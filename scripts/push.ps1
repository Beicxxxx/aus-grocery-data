#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Push the local repository to GitHub with a self-contained gh config dir.

.DESCRIPTION
  The Codex sandbox cannot write to the user's system-level gh config
  (C:\Users\...\AppData\Roaming\GitHub CLI\hosts.yml), and git's HTTPS helper
  can crash inside the sandbox.  This script:

    1. uses a dedicated gh config dir under %TEMP%\gh-codex-config;
    2. re-authenticates via GitHub device flow when the token is missing/expired
       (prints a one-time code the user approves in the browser);
    3. pushes with a temporary credential store so no system config is touched;
    4. removes the temporary credential file afterwards.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\push.ps1
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$GhBin = Join-Path $env:TEMP "gh-cli\bin\gh.exe"
$ConfigDir = Join-Path $env:TEMP "gh-codex-config"
$CredFile = (Join-Path $env:TEMP "gh-codex-credentials").Replace("\", "/")

if (-not (Test-Path $GhBin)) {
    Write-Error "gh CLI not found at $GhBin"
    exit 1
}

$env:GH_CONFIG_DIR = $ConfigDir
$env:PATH = (Split-Path $GhBin) + ";" + $env:PATH

# 1) Make sure we have a valid token.
$token = (& $GhBin auth token 2>$null | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "No valid GitHub token found. Starting device-flow login..." -ForegroundColor Yellow
    & $GhBin auth login -h github.com -p https -w
    if ($LASTEXITCODE -ne 0) {
        Write-Error "gh auth login failed"
        exit 1
    }
    $token = (& $GhBin auth token | Out-String).Trim()
}

# 2) Write a temporary credential file and push.
try {
    "https://Beicxxxx:$token@github.com" | Set-Content -Path $CredFile -Encoding ascii -NoNewline
    Push-Location $RepoRoot
    try {
        git -c credential.helper= `
            -c credential.https://github.com.helper= `
            -c "credential.helper=store --file=$CredFile" `
            push origin master
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git push failed"
            exit 1
        }
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item -LiteralPath $CredFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Push complete." -ForegroundColor Green
