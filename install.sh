#!/bin/bash
#
# BaseMem — standalone installer
# Usage: curl -fsSL https://example.com/install.sh | bash
#        bash install.sh --dir ~/.basemem
#        bash install.sh --version v0.1.0
#
set -euo pipefail

REPO="https://github.com/ashvin-to/basemem.git"
TARBALL_BASE="https://github.com/ashvin-to/basemem/archive"

INSTALL_DIR=""
REQUESTED_VERSION=""
SKIP_GEMINI=""

print_usage() {
  cat <<'EOF'
Usage: install.sh [options]

Options:
  --dir <path>     Install directory (default: $HOME/.basemem)
  --version <ref>  Git ref or tag to install (default: main)
  --no-gemini      Skip Gemini extension installation
  -h, --help       Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --version) REQUESTED_VERSION="$2"; shift 2 ;;
    --no-gemini) SKIP_GEMINI="1"; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "Unknown option: $1"; print_usage; exit 1 ;;
  esac
done

INSTALL_DIR="${INSTALL_DIR:-$HOME/.basemem}"
REF="${REQUESTED_VERSION:-main}"

# ── Resolve source directory ──────────────────────────────────────
# If we're already inside a basemem repo, use it directly.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
if [[ -f "$SCRIPT_DIR/setup.sh" && -f "$SCRIPT_DIR/bin/lib/install.js" ]]; then
  BASE_DIR="$SCRIPT_DIR"
  echo "Using existing checkout at $BASE_DIR"
else
  # Download the repo
  if command -v git &>/dev/null; then
    echo "Cloning $REPO (ref: $REF) into $INSTALL_DIR..."
    if [[ -d "$INSTALL_DIR/.git" ]]; then
      BASE_DIR="$INSTALL_DIR"
      echo "  Repo already exists at $INSTALL_DIR, updating..."
      git -C "$BASE_DIR" fetch --quiet --tags --force
      git -C "$BASE_DIR" checkout --quiet "$REF"
    else
      mkdir -p "$(dirname "$INSTALL_DIR")"
      git clone --quiet "$REPO" "$INSTALL_DIR"
      BASE_DIR="$INSTALL_DIR"
      if [[ "$REF" != "main" ]]; then
        git -C "$BASE_DIR" checkout --quiet "$REF"
      fi
    fi
  else
    echo "git not found — downloading tarball..."
    TAR_URL="${TARBALL_BASE}/${REF}.tar.gz"
    mkdir -p "$INSTALL_DIR"
    TMP_TAR="$(mktemp)"
    if command -v curl &>/dev/null; then
      curl -fsSL "$TAR_URL" -o "$TMP_TAR"
    elif command -v wget &>/dev/null; then
      wget -q "$TAR_URL" -O "$TMP_TAR"
    else
      echo "ERROR: need curl or wget to download tarball"; exit 1
    fi
    TMP_EXTRACT="$(mktemp -d)"
    tar -xzf "$TMP_TAR" -C "$TMP_EXTRACT"
    # The tarball contains a single top-level dir like basemem-<ref>
    EXTRACTED_DIR=("$TMP_EXTRACT"/*)
    if [[ ${#EXTRACTED_DIR[@]} -eq 1 ]]; then
      rm -rf "$INSTALL_DIR"
      mv "${EXTRACTED_DIR[0]}" "$INSTALL_DIR"
    else
      echo "ERROR: unexpected tarball structure"; exit 1
    fi
    rm -rf "$TMP_TAR" "$TMP_EXTRACT"
    BASE_DIR="$INSTALL_DIR"
  fi
fi

echo "Installing to $BASE_DIR"

# ── Python / venv ─────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON="$cmd"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: Python 3 not found"; exit 1
fi

$PYTHON -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' ||
  { echo "ERROR: Python 3.10+ required"; exit 1; }

DATA_DIR="$HOME/.basemem"
mkdir -p "$DATA_DIR/sessions"

if [[ ! -d "$BASE_DIR/venv" ]]; then
  echo "Creating virtual environment..."
  $PYTHON -m venv "$BASE_DIR/venv"
fi

PIP="$BASE_DIR/venv/bin/pip"
$PIP install -q -r "$BASE_DIR/requirements.txt"
$PIP install -q -e "$BASE_DIR"

# ── CLI wrappers ──────────────────────────────────────────────────
MEM_BIN_DIR="${BASEMEM_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$MEM_BIN_DIR"

write_executable() {
  local target="$1" content="$2"
  if [[ -w "$(dirname "$target")" ]]; then
    printf "%s\n" "$content" >"$target" && chmod 755 "$target"
  else
    printf "%s\n" "$content" | sudo tee "$target" >/dev/null && sudo chmod 755 "$target"
  fi
}

MCP_PYTHON="$BASE_DIR/venv/bin/python3"
MCP_SCRIPT="$BASE_DIR/mem-mcp.py"
BASEMEM_DB_PATH="$DATA_DIR/basemem.db"

MEM_WRAPPER="#!/bin/bash
$MCP_PYTHON $BASE_DIR/mem.py --db $BASEMEM_DB_PATH \"\$@\""
write_executable "$MEM_BIN_DIR/mem" "$MEM_WRAPPER"

# ── MCP entry point ───────────────────────────────────────────────
if [[ ! -f "$MCP_SCRIPT" ]]; then
  cat <<'PYEOF' >"$MCP_SCRIPT"
#!/usr/bin/env python3
"""MCP server entry point for BaseMem agent memory."""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))
from mcp_server.server import server
if __name__ == "__main__":
    server.run()
PYEOF
  chmod 755 "$MCP_SCRIPT"
fi

# ── Agent rules + hooks + MCP via install.js ──────────────────────
if [[ -f "$BASE_DIR/bin/lib/install.js" ]]; then
  echo "Installing agent guidance files..."
  BASEMEM_MCP_PYTHON="$MCP_PYTHON" \
  BASEMEM_MCP_SCRIPT="$MCP_SCRIPT" \
  BASEMEM_DB_PATH="$BASEMEM_DB_PATH" \
  node "$BASE_DIR/bin/lib/install.js" install-all
fi

# ── Gemini extension ──────────────────────────────────────────────
if [[ -z "$SKIP_GEMINI" && -d "$BASE_DIR/extensions/gemini" ]]; then
  echo "Installing Gemini extension..."
  EXT_DIR="$HOME/.gemini/extensions/00-basemem"
  rm -rf "$EXT_DIR"
  cp -r "$BASE_DIR/extensions/gemini/." "$EXT_DIR"

  echo "Installing Antigravity plugin..."
  PLUGIN_DIR="$HOME/.gemini/config/plugins/basemem"
  mkdir -p "$HOME/.gemini/config/plugins"
  rm -rf "$PLUGIN_DIR"
  cp -r "$BASE_DIR/extensions/gemini/." "$PLUGIN_DIR"
  mv "$PLUGIN_DIR/gemini-extension.json" "$PLUGIN_DIR/plugin.json"

  if [[ -f "$BASE_DIR/generate_antigravity_schemas.py" ]]; then
    echo "Generating Antigravity MCP tool schemas..."
    python3 "$BASE_DIR/generate_antigravity_schemas.py" || true
  fi

  ENABLEMENT_FILE="$HOME/.gemini/extensions/extension-enablement.json"
  mkdir -p "$(dirname "$ENABLEMENT_FILE")"
  python3 - "$ENABLEMENT_FILE" <<'PY'
import os, json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text()) if path.exists() else {}
data["00-basemem"] = {"overrides": [os.environ.get("HOME", "~") + "/*"]}
path.write_text(json.dumps(data, indent=2) + "\n")
PY

  echo "Configuring MCP for Gemini CLI..."
  gemini mcp add mem "$MCP_PYTHON" "$MCP_SCRIPT" --scope user --trust \
    -e "BASEMEM_DB_PATH=$BASEMEM_DB_PATH" 2>/dev/null || true
fi

# ── PATH ──────────────────────────────────────────────────────────
SHELL_CONFIG=""
case "$(basename "${SHELL:-bash}")" in
  bash) SHELL_CONFIG="$HOME/.bashrc" ;;
  zsh)  SHELL_CONFIG="$HOME/.zshrc"  ;;
  fish) SHELL_CONFIG="$HOME/.config/fish/config.fish" ;;
esac
if [[ -n "$SHELL_CONFIG" && -f "$SHELL_CONFIG" ]]; then
  if ! grep -q "$MEM_BIN_DIR" "$SHELL_CONFIG" 2>/dev/null; then
    echo "export PATH=\"\$PATH:$MEM_BIN_DIR\"" >>"$SHELL_CONFIG"
    echo "Added $MEM_BIN_DIR to PATH in $SHELL_CONFIG"
  fi
fi

echo "------------------------------------------------"
echo "BASEMEM READY"
echo ""
echo "  CLI      $MEM_BIN_DIR/mem"
echo "  MCP      $MCP_SCRIPT"
echo "  Data     $BASEMEM_DB_PATH"
echo ""
echo "Run 'mem planet create my-topic --goal \"...\"' to start."
echo "------------------------------------------------"
