# BaseMem Galaxy: Windows Setup
# Installs kb CLI, MCP server, and agent integrations.

param(
    [string]$BasememBinDir = "$env:USERPROFILE\.basemem\bin",
    [string]$DataDir = "$env:USERPROFILE\.basemem",
    [switch]$NoGemini
)

$ErrorActionPreference = "Stop"
$BaseDir = Split-Path -Parent $PSCommandPath
Write-Host "Initializing your Universal Knowledge Galaxy..." -ForegroundColor Cyan

# --- Auto-detect Python ---
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

New-Item -ItemType Directory -Path "$DataDir\sessions" -Force | Out-Null

# Virtual environment
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

Write-Host "Installing kb CLI..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $BasememBinDir -Force | Out-Null
$MemBat = "$BasememBinDir\mem.bat"
@"
@echo off
"$Python" "$BaseDir\mem.py" --db "$DataDir\basemem.db" %*
"@ | Set-Content -Path $MemBat -Encoding ASCII

$KbBat = "$BasememBinDir\kb.bat"
@"
@echo off
"$Python" "$BaseDir\mem.py" --db "$DataDir\basemem.db" %*
"@ | Set-Content -Path $KbBat -Encoding ASCII

Write-Host "Installing MCP server entry point..." -ForegroundColor Yellow
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

# --- Helper: write JSON file ---
function Write-JsonFile {
    param($FilePath, $ScriptBlock)
    $Dir = Split-Path -Parent $FilePath
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    $config = @{}
    if (Test-Path $FilePath) {
        try {
            $config = Get-Content -Path $FilePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            $config = ConvertTo-DeepHashtable $config
        } catch {
            $config = @{}
        }
    }
    & $ScriptBlock $config
    $json = $config | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($FilePath, $json, [System.Text.UTF8Encoding]::new($false))
}

function ConvertTo-DeepHashtable {
    param($InputObject)
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $ht = @{}
        $InputObject.PSObject.Properties | ForEach-Object {
            $ht[$_.Name] = ConvertTo-DeepHashtable $_.Value
        }
        return $ht
    } elseif ($InputObject -is [array]) {
        return @($InputObject | ForEach-Object { ConvertTo-DeepHashtable $_ })
    } elseif ($InputObject -is [hashtable]) {
        $ht = @{}
        $InputObject.Keys | ForEach-Object {
            $ht[$_] = ConvertTo-DeepHashtable $InputObject[$_]
        }
        return $ht
    } else {
        return $InputObject
    }
}

# --- Delegate agent rules + MCP + hooks to install.js ---
$env:BASEMEM_ROOT = $BaseDir
$env:BASEMEM_MCP_PYTHON = $McpPython
$env:BASEMEM_MCP_SCRIPT = $McpScriptArg
$env:BASEMEM_DB_PATH = $BasememDbPath

Write-Host "Installing agent guidance files..." -ForegroundColor Yellow
$InstallJs = "$BaseDir\bin\lib\install.js"
if (Test-Path $InstallJs) {
    & node $InstallJs install-all
    if (-not $?) { Write-Host "  (install.js skipped — node not available)" -ForegroundColor Gray }
} else {
    Write-Host "  (install.js not found — skipping agent config)" -ForegroundColor Gray
}

# --- Gemini extension ---
if (-not $NoGemini) {
$GeminiExtDir = "$env:USERPROFILE\.gemini\extensions\00-basemem"
if (Test-Path $GeminiExtDir) { Remove-Item -Recurse -Force $GeminiExtDir }
New-Item -ItemType Directory -Path $GeminiExtDir -Force | Out-Null
Copy-Item -Recurse -Force "$BaseDir\extensions\gemini\*" $GeminiExtDir

# Antigravity plugin
$PluginDir = "$env:USERPROFILE\.gemini\config\plugins\basemem"
New-Item -ItemType Directory -Path "$env:USERPROFILE\.gemini\config\plugins" -Force | Out-Null
if (Test-Path $PluginDir) { Remove-Item -Recurse -Force $PluginDir }
New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null
Copy-Item -Recurse -Force "$BaseDir\extensions\gemini\*" $PluginDir
Copy-Item -Path "$PluginDir\gemini-extension.json" -Destination "$PluginDir\plugin.json" -Force

# Gemini MCP config (install.js also writes this, but write it here too for Windows paths)
$GeminiMcp = "$env:USERPROFILE\.gemini\config\mcp_config.json"
Write-JsonFile -FilePath $GeminiMcp -ScriptBlock {
    param($config)
    if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
    $config["mcpServers"]["mem"] = @{
        command = $McpPython
        args    = @($McpScriptArg)
        env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
    }
}

# Extension enablement
$EnablementFile = "$env:USERPROFILE\.gemini\extensions\extension-enablement.json"
Write-JsonFile -FilePath $EnablementFile -ScriptBlock {
    param($config)
    $config["00-basemem"] = @{
        overrides = @("$env:USERPROFILE/*")
    }
}

# Try gemini CLI mcp add
try {
    $geminiExe = Get-Command "gemini" -ErrorAction SilentlyContinue
    if ($geminiExe) {
        & gemini mcp add mem $McpPython $McpScriptArg --scope user --trust -e "BASEMEM_DB_PATH=$BasememDbPath" 2>$null
    }
} catch {
    Write-Host "  (gemini CLI not found - MCP config written directly)" -ForegroundColor Gray
}
}

# --- Add bin directory to PATH ---
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($CurrentPath -notlike "*$BasememBinDir*") {
    Write-Host "Adding $BasememBinDir to user PATH..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("Path", "$CurrentPath;$BasememBinDir", "User")
    $env:Path = "$env:Path;$BasememBinDir"
}

Write-Host "------------------------------------------------" -ForegroundColor Cyan
Write-Host "UNIVERSAL KNOWLEDGE GALAXY READY (Windows)" -ForegroundColor Green
Write-Host ""
Write-Host "Installed:" -ForegroundColor White
Write-Host "  MCP server            mem (via venv)" -ForegroundColor Gray
Write-Host "  kb                    CLI for BaseMem ($BasememBinDir\kb.bat)" -ForegroundColor Gray
Write-Host "  Agent rules + MCP     via install.js (all detected agents)" -ForegroundColor Gray
if (-not $NoGemini) {
Write-Host "  Gemini extension      $GeminiExtDir" -ForegroundColor Gray
Write-Host "  Antigravity plugin    $PluginDir" -ForegroundColor Gray
}
Write-Host ""
Write-Host "Usage:" -ForegroundColor White
Write-Host "  kb planet create my-project --goal 'Build X'" -ForegroundColor Gray
Write-Host "  kb agent-context --topic my-project --query 'what are we doing?'" -ForegroundColor Gray
Write-Host ""
Write-Host "NOTE: You may need to restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
Write-Host "      Or run: `$env:Path = [Environment]::GetEnvironmentVariable('Path','User')" -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Cyan
