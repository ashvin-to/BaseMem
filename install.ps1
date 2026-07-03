<#
.SYNOPSIS
  BaseMem standalone installer for Windows.
.DESCRIPTION
  Downloads BaseMem and installs the CLI, MCP server, and agent integrations.
  Can be run standalone without cloning the repo first.
.PARAMETER Dir
  Install directory (default: $env:USERPROFILE\.basemem)
.PARAMETER Version
  Git ref or tag to install (default: main)
.PARAMETER NoGemini
  Skip Gemini extension installation
.EXAMPLE
  irm https://example.com/install.ps1 | iex
  .\install.ps1 -Dir C:\tools\basemem -Version v0.1.0
#>

param(
    [string]$Dir = "",
    [string]$Version = "main",
    [switch]$NoGemini
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/ashvin-to/basemem.git"
$TarballBase = "https://github.com/ashvin-to/basemem/archive"

if (-not $Dir) { $Dir = "$env:USERPROFILE\.basemem" }

# ── Resolve source directory ──────────────────────────────────────
$ScriptDir = Split-Path -Parent $PSCommandPath
$BaseDir = ""

# Check if running from within the repo
if (Test-Path "$ScriptDir\setup.ps1" -and (Test-Path "$ScriptDir\bin\lib\install.js" -or (Test-Path "$ScriptDir\bin\lib"))) {
    $BaseDir = $ScriptDir
    Write-Host "Using existing checkout at $BaseDir" -ForegroundColor Cyan
} else {
    # Download the repo
    if (Get-Command "git" -ErrorAction SilentlyContinue) {
        Write-Host "Cloning $RepoUrl (ref: $Version) into $Dir..." -ForegroundColor Yellow
        if (Test-Path "$Dir\.git") {
            $BaseDir = $Dir
            Write-Host "  Repo already exists, updating..." -ForegroundColor Gray
            git -C $BaseDir fetch --quiet --tags --force
            git -C $BaseDir checkout --quiet $Version
        } else {
            $parent = Split-Path -Parent $Dir
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            git clone --quiet $RepoUrl $Dir
            $BaseDir = $Dir
            if ($Version -ne "main") {
                git -C $BaseDir checkout --quiet $Version
            }
        }
    } else {
        Write-Host "git not found — downloading tarball..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        $TarUrl = "$TarballBase/$Version.tar.gz"
        $TmpTar = [System.IO.Path]::GetTempFileName()
        
        if (Get-Command "curl" -ErrorAction SilentlyContinue) {
            curl.exe -fsSL $TarUrl -o $TmpTar 2>$null
        } elseif (Get-Command "wget" -ErrorAction SilentlyContinue) {
            wget.exe -q $TarUrl -O $TmpTar
        } else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $web = New-Object System.Net.WebClient
            $web.DownloadFile($TarUrl, $TmpTar)
        }
        
        $TmpExtract = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
        New-Item -ItemType Directory -Path $TmpExtract -Force | Out-Null
        tar -xzf $TmpTar -C $TmpExtract
        
        $extractedDirs = Get-ChildItem -Path $TmpExtract -Directory
        if ($extractedDirs.Count -eq 1) {
            if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
            Move-Item -Path $extractedDirs[0].FullName -Destination $Dir
        } else {
            throw "Unexpected tarball structure"
        }
        Remove-Item -Force $TmpTar -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $TmpExtract -ErrorAction SilentlyContinue
        $BaseDir = $Dir
    }
}

Write-Host "Installing to $BaseDir" -ForegroundColor Cyan

# ── Python / venv ─────────────────────────────────────────────────
$PythonExe = ""
foreach ($cmd in @("python", "python3", "py -3", "py")) {
    try {
        $ver = cmd /c "$cmd --version" 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3\.(1[0-9]|[2-9]\d)") {
            $PythonExe = $cmd
            break
        }
    } catch {}
}
if (-not $PythonExe) {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending | Select-Object -First 1
    if (-not $found) {
        $found = Get-ChildItem "C:\Python3*\python.exe" -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1
    }
    if ($found) { $PythonExe = $found.FullName }
}
if (-not $PythonExe) {
    throw "Python 3.10+ not found. Install from https://python.org"
}
Write-Host "Using Python: $PythonExe" -ForegroundColor Cyan

$DataDir = "$env:USERPROFILE\.basemem"
New-Item -ItemType Directory -Path "$DataDir\sessions" -Force | Out-Null

$VenvDir = "$BaseDir\venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    if ($PythonExe -match '^python') {
        & cmd /c "$PythonExe -m venv $VenvDir"
    } else {
        & $PythonExe -m venv $VenvDir
    }
    if (-not $?) { throw "Failed to create venv" }
}

$Python = "$VenvDir\Scripts\python.exe"

Write-Host "Installing core engine..." -ForegroundColor Yellow
& $Python -m pip install -q -r "$BaseDir\requirements.txt"
if (-not $?) { throw "pip install failed" }
& $Python -m pip install -q -e $BaseDir
if (-not $?) { throw "pip install -e failed" }

# ── CLI wrappers ──────────────────────────────────────────────────
$MemBinDir = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Path $MemBinDir -Force | Out-Null

$MemBat = "$MemBinDir\mem.bat"
@"
@echo off
"$Python" "$BaseDir\mem.py" --db "$DataDir\basemem.db" %*
"@ | Set-Content -Path $MemBat -Encoding ASCII

# ── MCP entry point ───────────────────────────────────────────────
$McpScript = "$BaseDir\mem-mcp.py"
if (-not (Test-Path $McpScript)) {
    @"
#!/usr/bin/env python3
\"\"\"MCP server entry point for BaseMem agent memory.\"\"\"
import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))
from mcp_server.server import server
if __name__ == "__main__":
    server.run()
"@ | Set-Content -Path $McpScript -Encoding ASCII
}

$BasememDbPath = "$DataDir\basemem.db"
$McpPython = $Python
$McpScriptArg = $McpScript

# ── Agent rules + hooks + MCP via install.js ──────────────────────
$env:BASEMEM_ROOT = $BaseDir
$env:BASEMEM_MCP_PYTHON = $McpPython
$env:BASEMEM_MCP_SCRIPT = $McpScriptArg
$env:BASEMEM_DB_PATH = $BasememDbPath

$InstallJs = "$BaseDir\bin\lib\install.js"
if (Test-Path $InstallJs) {
    Write-Host "Installing agent guidance files..." -ForegroundColor Yellow
    & node $InstallJs install-all
    if (-not $?) { Write-Host "  (install.js skipped)" -ForegroundColor Gray }
}

# ── Gemini extension ──────────────────────────────────────────────
if (-not $NoGemini -and (Test-Path "$BaseDir\extensions\gemini")) {
    Write-Host "Installing Gemini extension..." -ForegroundColor Yellow
    $GeminiExtDir = "$env:USERPROFILE\.gemini\extensions\00-basemem"
    if (Test-Path $GeminiExtDir) { Remove-Item -Recurse -Force $GeminiExtDir }
    New-Item -ItemType Directory -Path $GeminiExtDir -Force | Out-Null
    Copy-Item -Recurse -Force "$BaseDir\extensions\gemini\*" $GeminiExtDir

    Write-Host "Installing Antigravity plugin..." -ForegroundColor Yellow
    $PluginDir = "$env:USERPROFILE\.gemini\config\plugins\basemem"
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.gemini\config\plugins" -Force | Out-Null
    if (Test-Path $PluginDir) { Remove-Item -Recurse -Force $PluginDir }
    New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null
    Copy-Item -Recurse -Force "$BaseDir\extensions\gemini\*" $PluginDir
    Copy-Item -Path "$PluginDir\gemini-extension.json" -Destination "$PluginDir\plugin.json" -Force

    # Gemini MCP config
    $GeminiMcp = "$env:USERPROFILE\.gemini\config\mcp_config.json"
    $GeminiConfig = @{}
    if (Test-Path $GeminiMcp) {
        try { $GeminiConfig = Get-Content $GeminiMcp -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    $GeminiConfig.mcpServers = @{ mem = @{ command = $McpPython; args = @($McpScriptArg); env = @{ BASEMEM_DB_PATH = $BasememDbPath } } }
    $json = $GeminiConfig | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($GeminiMcp, $json, [System.Text.UTF8Encoding]::new($false))

    # Extension enablement
    $EnablementFile = "$env:USERPROFILE\.gemini\extensions\extension-enablement.json"
    $EnableConfig = @{}
    if (Test-Path $EnablementFile) {
        try { $EnableConfig = Get-Content $EnablementFile -Raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    $EnableConfig."00-basemem" = @{ overrides = @("$env:USERPROFILE/*") }
    $json = $EnableConfig | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($EnablementFile, $json, [System.Text.UTF8Encoding]::new($false))

    # Try gemini CLI
    try {
        $geminiExe = Get-Command "gemini" -ErrorAction SilentlyContinue
        if ($geminiExe) {
            & gemini mcp add mem $McpPython $McpScriptArg --scope user --trust -e "BASEMEM_DB_PATH=$BasememDbPath" 2>$null
        }
    } catch {}
}

# ── PATH ──────────────────────────────────────────────────────────
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($CurrentPath -notlike "*$MemBinDir*") {
    Write-Host "Adding $MemBinDir to user PATH..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("Path", "$CurrentPath;$MemBinDir", "User")
    $env:Path = "$env:Path;$MemBinDir"
}

Write-Host "------------------------------------------------" -ForegroundColor Cyan
Write-Host "BASEMEM READY (Windows)" -ForegroundColor Green
Write-Host ""
Write-Host "  CLI      $MemBinDir\mem.bat" -ForegroundColor White
Write-Host "  MCP      $McpScript" -ForegroundColor Gray
Write-Host "  Data     $BasememDbPath" -ForegroundColor Gray
Write-Host ""
Write-Host "Run 'mem planet create my-topic' to start." -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor Cyan
