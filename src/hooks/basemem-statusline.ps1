# Statusline indicator for Claude Code / compatible agents (Windows)
$configDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { "$env:APPDATA\claude" }
$flagFile = "$configDir\.basemem-active"

$resolvedConfig = Resolve-Path -Path $configDir -ErrorAction SilentlyContinue
if (-not $resolvedConfig) { exit 0 }

$resolvedFlag = Resolve-Path -Path $flagFile -ErrorAction SilentlyContinue
if ($resolvedFlag) {
  if (-not ($resolvedFlag.Path -like "$($resolvedConfig.Path)*")) {
    exit 0
  }
}

if (Test-Path -Path $flagFile) {
  $content = Get-Content -Path $flagFile -Raw -ErrorAction SilentlyContinue
  if ($content -eq 'active') {
    Write-Output '[BASEMEM] [MEM]'
  }
}

exit 0
