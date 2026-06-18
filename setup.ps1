# BaseMem Galaxy: Windows Setup
# Installs kb CLI, MCP server, and agent integrations.

param(
    [string]$BasememBinDir = "$env:USERPROFILE\.basemem\bin",
    [string]$DataDir = "$env:USERPROFILE\.basemem",
    [switch]$NoGemini,
    [switch]$NoClaude,
    [switch]$NoOpencode,
    [switch]$NoCursor,
    [switch]$NoWindsurf
)

$ErrorActionPreference = "Stop"
$BaseDir = Split-Path -Parent $PSCommandPath
Write-Host "Initializing your Universal Knowledge Galaxy..." -ForegroundColor Cyan

# --- Auto-detect Python ---
$PythonExe = ""
# Try common commands
foreach ($cmd in @("python", "python3", "py -3", "py")) {
    try {
        $ver = cmd /c "$cmd --version" 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3\.(1[0-9]|[2-9]\d)") {
            $PythonExe = $cmd
            break
        }
    } catch {}
}
# Probe common install paths
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

# Create data directory
New-Item -ItemType Directory -Path "$DataDir\sessions" -Force | Out-Null

# Create virtual environment if not exists
$VenvDir = "$BaseDir\venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    if ($PythonExe -match '^python') {
        & cmd /c "$PythonExe -m venv $VenvDir"
    } else {
        & $PythonExe -m venv $VenvDir
    }
    if (-not $?) { throw "Failed to create venv. Make sure Python 3.10+ is installed." }
}

$Python = "$VenvDir\Scripts\python.exe"

Write-Host "Installing core engine..." -ForegroundColor Yellow
& $Python -m pip install -q -r "$BaseDir\requirements.txt"
if (-not $?) { throw "pip install failed" }

# Install basemem package in venv
& $Python -m pip install -q -e $BaseDir
if (-not $?) { throw "pip install -e failed" }

# Create bin directory
New-Item -ItemType Directory -Path $BasememBinDir -Force | Out-Null

# Install mem command (primary batch wrapper)
$MemBat = "$BasememBinDir\mem.bat"
@"
@echo off
"$Python" "$BaseDir\mem.py" --db "$DataDir\basemem.db" %*
"@ | Set-Content -Path $MemBat -Encoding ASCII

# Also install as kb for README compatibility
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
sys.path.insert(0, str(BASE_DIR / "src"))
from basemem.mcp.server import server
if __name__ == "__main__":
    server.run()
"@ | Set-Content -Path $McpScript -Encoding ASCII
}

$BasememDbPath = "$DataDir\basemem.db"

# --- Helper: write JSON file ---
function Write-JsonFile {
    param($FilePath, $ScriptBlock)
    $Dir = Split-Path -Parent $FilePath
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    $config = @{}
    if (Test-Path $FilePath) {
        try {
            $config = Get-Content -Path $FilePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            # Convert PSCustomObject to hashtable for easier manipulation
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

$McpCommand = $Python
$McpArgs = @($McpScript)

# --- Agent guidance content (shared across multiple tools) ---
$AgentGuidance = @'
# BaseMem Memory Protocol

<EXTREMELY-IMPORTANT>
**FAILURE MODE:** Without this protocol, every session starts from zero. You will repeat past work, forget prior decisions, and waste context on what was already resolved.

IF A MEMORY CHECK COULD BE RELEVANT TO WHAT THE USER IS ASKING, YOU DO NOT HAVE A CHOICE. YOU MUST CHECK MEMORY FIRST. This is not negotiable. This is not optional.
</EXTREMELY-IMPORTANT>

## Mandatory Startup (BEFORE answering)

BaseMem MCP tools are available. Use them in this order:

1. `list_planets` — discover what topics exist
2. `get_agent_context(topic, query="<user request>")` — ALWAYS call this before your first answer
3. Review the returned context. Prefer existing decisions. Do NOT re-ask what's already recorded.

## Mandatory Write-Back (AFTER completing work)

1. `add_note(topic, kind="decision", content="...")` for every architectural choice, fact learned, or issue found
2. `update_planet(topic, current_state="...", next_step="...")` to persist progress
3. `log_turn(topic, content="what I did")` for lightweight activity tracking

## Red Flags

If you think any of these, STOP and check memory instead:
- "I don't need to check memory yet" → Check before answering anything
- "I can check later" → Later means after starting without context
- "The topic is obvious" → You don't know what prior decisions exist
- "I already know about this" → You only know what's in this session
- "Checking memory wastes tokens" → Wasting work because you ignored prior decisions wastes more
- "The user would have told me if there was context" → Users forget; that's why memory exists
'@

# --- Gemini extension ---
if (-not $NoGemini) {
    Write-Host "Installing Gemini extension..." -ForegroundColor Yellow
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

    # Generate Antigravity MCP tool schemas (skip on Windows - schema gen script uses Linux venv path)
    # The MCP config is written directly above; schema files are optional plugin metadata.

    # Extension enablement
    $EnablementFile = "$env:USERPROFILE\.gemini\extensions\extension-enablement.json"
    Write-JsonFile -FilePath $EnablementFile -ScriptBlock {
        param($config)
        $config["00-basemem"] = @{
            overrides = @("$env:USERPROFILE/*")
        }
    }

    # Gemini MCP config
    $GeminiMcp = "$env:USERPROFILE\.gemini\config\mcp_config.json"
    Write-JsonFile -FilePath $GeminiMcp -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
        $config["mcpServers"]["basemem-memory"] = @{
            command = $McpCommand
            args    = $McpArgs
            env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }

    # Gemini settings
    $GeminiSettings = "$env:USERPROFILE\.gemini\settings.json"
    Write-JsonFile -FilePath $GeminiSettings -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
        $config["mcpServers"]["basemem-memory"] = @{
            command = $McpCommand
            args    = $McpArgs
            env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }

    # Try gemini CLI mcp add
    try {
        $geminiExe = Get-Command "gemini" -ErrorAction SilentlyContinue
        if ($geminiExe) {
            & gemini mcp add basemem-memory $McpCommand "$McpScript" --scope user --trust -e "BASEMEM_DB_PATH=$BasememDbPath" 2>$null
        }
    } catch {
        Write-Host "  (gemini CLI not found - MCP config written directly)" -ForegroundColor Gray
    }
}

# --- Claude Code ---
if (-not $NoClaude) {
    Write-Host "Configuring MCP for Claude Code..." -ForegroundColor Yellow
    $ClaudeSettings = "$env:USERPROFILE\.claude\settings.json"
    Write-JsonFile -FilePath $ClaudeSettings -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
        $config["mcpServers"]["basemem-memory"] = @{
            command = $McpCommand
            args    = $McpArgs
            env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }

    $ClaudeMd = "$env:USERPROFILE\.claude\CLAUDE.md"
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.claude" -Force | Out-Null
    Set-Content -Path $ClaudeMd -Value $AgentGuidance -Encoding UTF8
}

# --- opencode ---
if (-not $NoOpencode) {
    Write-Host "Configuring MCP for opencode..." -ForegroundColor Yellow
    $OpencodeConfig = "$env:USERPROFILE\.config\opencode\opencode.jsonc"
    Write-JsonFile -FilePath $OpencodeConfig -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey('$schema')) { $config['$schema'] = 'https://opencode.ai/config.json' }
        if (-not $config.ContainsKey('mcp')) { $config['mcp'] = @{} }
        $config['mcp']['basemem-memory'] = @{
            type        = 'local'
            command     = @($McpCommand) + $McpArgs
            enabled     = $true
            environment = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }

    # opencode global rules
    $AgentsMd = "$env:USERPROFILE\.config\opencode\AGENTS.md"
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.config\opencode" -Force | Out-Null
    Set-Content -Path $AgentsMd -Value $AgentGuidance -Encoding UTF8
}

# --- Cursor ---
if (-not $NoCursor) {
    Write-Host "Configuring MCP for Cursor..." -ForegroundColor Yellow
    $CursorMcp = "$env:USERPROFILE\.cursor\mcp.json"
    Write-JsonFile -FilePath $CursorMcp -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
        $config["mcpServers"]["basemem-memory"] = @{
            command = $McpCommand
            args    = $McpArgs
            env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }
}

# --- Windsurf ---
if (-not $NoWindsurf) {
    Write-Host "Configuring MCP for Windsurf..." -ForegroundColor Yellow
    $WindsurfMcp = "$env:USERPROFILE\.windsurf\mcp_config.json"
    Write-JsonFile -FilePath $WindsurfMcp -ScriptBlock {
        param($config)
        if (-not $config.ContainsKey("mcpServers")) { $config["mcpServers"] = @{} }
        $config["mcpServers"]["basemem-memory"] = @{
            command = $McpCommand
            args    = $McpArgs
            env     = @{ BASEMEM_DB_PATH = $BasememDbPath }
        }
    }
}

# --- Codex CLI ---
Write-Host "Installing host guidance for Codex CLI..." -ForegroundColor Yellow
$CodexDir = "$env:USERPROFILE\.codex"
New-Item -ItemType Directory -Path $CodexDir -Force | Out-Null
$CodexMd = "$CodexDir\CODEX.md"
Set-Content -Path $CodexMd -Value $AgentGuidance -Encoding UTF8

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
Write-Host "  MCP server            basemem-memory (via venv)" -ForegroundColor Gray
Write-Host "  kb                    CLI for BaseMem ($BasememBinDir\kb.bat)" -ForegroundColor Gray
Write-Host ""
Write-Host "MCP configured for:" -ForegroundColor White
if (-not $NoGemini) { Write-Host "  Gemini CLI      ~\.gemini\settings.json" -ForegroundColor Gray }
if (-not $NoClaude) { Write-Host "  Claude Code     ~\.claude\settings.json" -ForegroundColor Gray }
if (-not $NoOpencode) { Write-Host "  opencode        ~\.config\opencode\opencode.jsonc" -ForegroundColor Gray }
if (-not $NoCursor) { Write-Host "  Cursor          ~\.cursor\mcp.json" -ForegroundColor Gray }
if (-not $NoWindsurf) { Write-Host "  Windsurf        ~\.windsurf\mcp_config.json" -ForegroundColor Gray }
Write-Host ""
Write-Host "Usage:" -ForegroundColor White
Write-Host "  kb planet create my-project --goal 'Build X'" -ForegroundColor Gray
Write-Host "  kb agent-context --topic my-project --query 'what are we doing?'" -ForegroundColor Gray
Write-Host ""
Write-Host "NOTE: You may need to restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
Write-Host "      Or run: `$env:Path = [Environment]::GetEnvironmentVariable('Path','User')" -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Cyan
