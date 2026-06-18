# BaseMem Galaxy: Windows Uninstaller
# Removes kb CLI, MCP configs, and agent integrations.

param(
    [switch]$PurgeData,
    [switch]$PurgeEnv,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$BaseDir = Split-Path -Parent $PSCommandPath
$DataDir = "$env:USERPROFILE\.basemem"

function Confirm-Action {
    param([string]$Prompt)
    if ($Yes) { return $true }
    $answer = Read-Host "$Prompt [y/N]"
    return $answer -match '^(y|yes)$'
}

function Remove-McpEntry {
    param([string]$FilePath, [string]$Key)
    if (-not (Test-Path $FilePath)) { return }
    try {
        $text = Get-Content -Path $FilePath -Raw -ErrorAction Stop
        $config = $text | ConvertFrom-Json -ErrorAction SilentlyContinue
        if (-not $config) { return }
        $changed = $false

        # Claude/Cursor/Windsurf format: mcpServers
        if ($config.PSObject.Properties.Name -contains 'mcpServers' -and
            $config.mcpServers.PSObject.Properties.Name -contains $Key) {
            $config.mcpServers.PSObject.Properties.Remove($Key)
            $changed = $true
            if ($config.mcpServers.PSObject.Properties.Name.Count -eq 0) {
                $config.PSObject.Properties.Remove('mcpServers')
            }
        }

        # opencode format: mcp
        if ($config.PSObject.Properties.Name -contains 'mcp' -and
            $config.mcp.PSObject.Properties.Name -contains $Key) {
            $config.mcp.PSObject.Properties.Remove($Key)
            $changed = $true
            if ($config.mcp.PSObject.Properties.Name.Count -eq 0) {
                $config.PSObject.Properties.Remove('mcp')
            }
        }

        if ($changed) {
            $json = $config | ConvertTo-Json -Depth 10
            Set-Content -Path $FilePath -Value $json -Encoding UTF8
            Write-Host "  Cleaned $FilePath" -ForegroundColor Gray
        }
    } catch {
        Write-Host "  Error processing $FilePath : $_" -ForegroundColor DarkGray
    }
}

function Remove-IfContainsMarker {
    param([string]$FilePath, [string]$Marker)
    if (-not (Test-Path $FilePath)) { return }
    $content = Get-Content -Path $FilePath -Raw -ErrorAction SilentlyContinue
    if ($content -and $content -match [regex]::Escape($Marker)) {
        Remove-Item -Path $FilePath -Force
        Write-Host "  Removed $FilePath" -ForegroundColor Gray
    }
}

function Remove-ManagedBlock {
    param([string]$FilePath, [string]$Marker)
    if (-not (Test-Path $FilePath)) { return }
    $StartMarker = "# >>> $Marker >>>"
    $EndMarker = "# <<< $Marker <<<"
    $text = Get-Content -Path $FilePath -Raw -ErrorAction SilentlyContinue
    if (-not $text) { return }
    if ($text -match [regex]::Escape($StartMarker) -and $text -match [regex]::Escape($EndMarker)) {
        $prefix = $text -split [regex]::Escape($StartMarker), 2 | Select-Object -First 1
        $suffix = $text -split [regex]::Escape($EndMarker), 2 | Select-Object -Last 1
        $newText = ($prefix.TrimEnd() + "`r`n" + $suffix.TrimStart()).Trim()
        if ($newText) { $newText += "`r`n" }
        Set-Content -Path $FilePath -Value $newText -Encoding ASCII
        Write-Host "  Cleaned block from $FilePath" -ForegroundColor Gray
    }
}

Write-Host "Uninstalling BaseMem Galaxy components..." -ForegroundColor Cyan

# Remove batch wrappers
$binFiles = @(
    "$env:USERPROFILE\.basemem\kb.bat",
    "$env:USERPROFILE\.basemem\kb.cmd",
    "$env:USERPROFILE\.basemem\mem.bat"
)
foreach ($f in $binFiles) {
    if (Test-Path $f) {
        Remove-Item -Path $f -Force
        Write-Host "  Removed $f" -ForegroundColor Gray
    }
}

# Remove MCP server entry point
$mcpScript = "$BaseDir\mem-mcp.py"
if (Test-Path $mcpScript) {
    $content = Get-Content $mcpScript -Raw -ErrorAction SilentlyContinue
    if ($content -and $content -match "basemem.mcp.server") {
        Remove-Item -Path $mcpScript -Force
        Write-Host "  Removed $mcpScript" -ForegroundColor Gray
    }
}

# Remove MCP config entries from agent settings
Write-Host "Removing MCP config entries from agent settings..." -ForegroundColor Yellow
Remove-McpEntry -FilePath "$env:USERPROFILE\.gemini\settings.json" -Key "basemem-memory"
Remove-McpEntry -FilePath "$env:USERPROFILE\.gemini\config\mcp_config.json" -Key "basemem-memory"
Remove-McpEntry -FilePath "$env:USERPROFILE\.claude\settings.json" -Key "basemem-memory"
Remove-McpEntry -FilePath "$env:USERPROFILE\.config\opencode\opencode.jsonc" -Key "basemem-memory"
Remove-McpEntry -FilePath "$env:USERPROFILE\.cursor\mcp.json" -Key "basemem-memory"
Remove-McpEntry -FilePath "$env:USERPROFILE\.windsurf\mcp_config.json" -Key "basemem-memory"

# Remove host guidance files
Write-Host "Removing host guidance files..." -ForegroundColor Yellow
Remove-IfContainsMarker -FilePath "$env:USERPROFILE\.codex\CODEX.md" -Marker "BaseMem"
Remove-IfContainsMarker -FilePath "$env:USERPROFILE\.claude\CLAUDE.md" -Marker "BaseMem"
Remove-IfContainsMarker -FilePath "$env:USERPROFILE\.config\opencode\AGENTS.md" -Marker "BaseMem"

# Remove Gemini extension
Write-Host "Removing Gemini extension..." -ForegroundColor Yellow
$geminiExt = "$env:USERPROFILE\.gemini\extensions\00-basemem"
if (Test-Path $geminiExt) {
    Remove-Item -Recurse -Force $geminiExt
    Write-Host "  Removed $geminiExt" -ForegroundColor Gray
}

# Remove Antigravity plugin
$antigravityPlugin = "$env:USERPROFILE\.gemini\config\plugins\basemem"
if (Test-Path $antigravityPlugin) {
    Remove-Item -Recurse -Force $antigravityPlugin
    Write-Host "  Removed $antigravityPlugin" -ForegroundColor Gray
}

$antigravityMcp = "$env:USERPROFILE\.gemini\antigravity\mcp\basemem-memory"
if (Test-Path $antigravityMcp) {
    Remove-Item -Recurse -Force $antigravityMcp
    Write-Host "  Removed $antigravityMcp" -ForegroundColor Gray
}

# Clean extension enablement
$enablementFile = "$env:USERPROFILE\.gemini\extensions\extension-enablement.json"
if (Test-Path $enablementFile) {
    try {
        $config = Get-Content -Path $enablementFile -Raw | ConvertFrom-Json
        if ($config.PSObject.Properties.Name -contains '00-basemem') {
            $config.PSObject.Properties.Remove('00-basemem')
            $json = $config | ConvertTo-Json -Depth 10
            Set-Content -Path $enablementFile -Value $json -Encoding UTF8
            Write-Host "  Cleaned $enablementFile" -ForegroundColor Gray
        }
    } catch { Write-Host "  Skipped $enablementFile" -ForegroundColor DarkGray }
}

# Remove venv
if ($PurgeEnv -and (Test-Path "$BaseDir\venv")) {
    if (Confirm-Action "Remove $BaseDir\venv?") {
        Remove-Item -Recurse -Force "$BaseDir\venv"
        Write-Host "  Removed $BaseDir\venv" -ForegroundColor Gray
    }
}

# Remove data
if ($PurgeData -and (Test-Path $DataDir)) {
    if (Confirm-Action "Remove $DataDir?") {
        Remove-Item -Recurse -Force $DataDir
        Write-Host "  Removed $DataDir" -ForegroundColor Gray
    }
}

# Remove PATH entry
$binDir = "$env:USERPROFILE\.basemem\bin"
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -like "*$binDir*") {
    $newPath = ($currentPath -split ';' | Where-Object { $_ -ne $binDir }) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "  Removed $binDir from user PATH" -ForegroundColor Gray
}

Write-Host "------------------------------------------------" -ForegroundColor Cyan
Write-Host "BaseMem uninstall complete." -ForegroundColor Green
Write-Host "MCP configs cleaned from Claude Code, opencode, Cursor, Windsurf."
Write-Host "Open a new terminal session to refresh PATH." -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Cyan
