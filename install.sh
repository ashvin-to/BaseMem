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

EXPLICIT_INSTALL_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; EXPLICIT_INSTALL_DIR="$2"; shift 2 ;;
    --version) REQUESTED_VERSION="$2"; shift 2 ;;
    --no-gemini) SKIP_GEMINI="1"; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "Unknown option: $1"; print_usage; exit 1 ;;
  esac
done

INSTALL_DIR="${INSTALL_DIR:-$HOME/.basemem}"
REF="${REQUESTED_VERSION:-main}"

# ── Resolve source directory ──────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

if [[ -n "$EXPLICIT_INSTALL_DIR" ]]; then
  BASE_DIR="$EXPLICIT_INSTALL_DIR"
  if [[ ! -d "$BASE_DIR" || ! -f "$BASE_DIR/setup.sh" ]]; then
    if [[ -f "$SCRIPT_DIR/setup.sh" && -f "$SCRIPT_DIR/bin/lib/install.js" ]]; then
      echo "Copying local checkout from $SCRIPT_DIR to $BASE_DIR..."
      mkdir -p "$BASE_DIR"
      cp -r "$SCRIPT_DIR/." "$BASE_DIR/"
    elif command -v git &>/dev/null; then
      echo "Cloning $REPO (ref: $REF) into $BASE_DIR..."
      mkdir -p "$(dirname "$BASE_DIR")"
      git clone --quiet "$REPO" "$BASE_DIR"
      if [[ "$REF" != "main" ]]; then
        git -C "$BASE_DIR" checkout --quiet "$REF"
      fi
    fi
  fi
elif [[ -f "$SCRIPT_DIR/setup.sh" && -f "$SCRIPT_DIR/bin/lib/install.js" ]]; then
  BASE_DIR="$SCRIPT_DIR"
  echo "Using existing checkout at $BASE_DIR"
else
  BASE_DIR="$HOME/.basemem"
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
  if command -v uv &>/dev/null; then
    uv venv "$BASE_DIR/venv" --python "$PYTHON"
  else
    $PYTHON -m venv "$BASE_DIR/venv"
  fi
fi

if command -v uv &>/dev/null; then
  echo "Installing dependencies with uv..."
  uv pip install --python "$BASE_DIR/venv/bin/python" -q -r "$BASE_DIR/requirements.txt"
  uv pip install --python "$BASE_DIR/venv/bin/python" -q -e "$BASE_DIR"
else
  echo "Installing dependencies with pip..."
  PIP="$BASE_DIR/venv/bin/pip"
  $PIP install -q -r "$BASE_DIR/requirements.txt"
  $PIP install -q -e "$BASE_DIR"
fi

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

# ── MCP entry point wrapper ───────────────────────────────────────
if [[ -f "$MCP_SCRIPT" ]]; then
  chmod 755 "$MCP_SCRIPT"
fi
BASEMEM_MCP_BIN="$MEM_BIN_DIR/basemem-mcp"
BASEMEM_MCP_WRAPPER="#!/bin/bash
exec \"$MCP_PYTHON\" \"$MCP_SCRIPT\" \"\$@\""
write_executable "$BASEMEM_MCP_BIN" "$BASEMEM_MCP_WRAPPER"

# ── Agent rules + hooks + MCP via install.js ──────────────────────
if [[ -f "$BASE_DIR/bin/lib/install.js" ]]; then
  echo "Installing agent guidance files..."
  BASEMEM_MCP_PYTHON="$MCP_PYTHON" \
  BASEMEM_MCP_SCRIPT="$MCP_SCRIPT" \
  BASEMEM_DB_PATH="$BASEMEM_DB_PATH" \
  node "$BASE_DIR/bin/lib/install.js" install-all
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

# ## Token Saving Guidelines
#
# - **`logInteraction` / `mem_note_update`** – keep facts ≤ 30 words; store only the essential decision.
# - **Prefer `code_find(query, grep=True)`** over `code_read`.  It returns line numbers only (≈ 0 tokens).  
# - **Tight reads** – when a read is unavoidable, use `code_read(path, offset=X, limit=Y)` with `Y ≤ 50`.  
# - **Structural queries via the BaseMem index** –  
#   * `SELECT from_id FROM edges WHERE to_id = "func:handleSaveTurnServer"` → callers (≈ 0 tokens).  
#   * `SELECT id FROM nodes_fts WHERE nodes_fts MATCH "TURN"` → full‑text match (≈ 0 tokens).  
# - **Avoid whole‑file reads** unless absolutely necessary; each full‑file read costs hundreds of tokens.  
# - **Keep `mem_task_create` notes to a single concise sentence** (≤ 20 words).  
# - **Cache frequently‑asked structural queries** in `mem_note` so they are not recomputed.

echo "  Data     $BASEMEM_DB_PATH"
echo ""
echo "Run 'mem planet create my-topic --goal \"...\"' to start."
echo "------------------------------------------------"
