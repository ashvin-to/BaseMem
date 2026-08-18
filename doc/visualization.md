# BaseMem: Interactive Visualization & REST API

BaseMem includes an interactive web server (`server.py`) providing D3.js knowledge graph visualizers and REST API endpoints for memory and AST code symbol call graphs.

## Quick Start

Launch the visualization web server directly via the CLI:

```bash
# Launch server on default http://127.0.0.1:5000
mem viz

# Custom port and interface
mem viz --port 8080 --host 0.0.0.0

# Point to custom database
mem --db /path/to/custom.db viz
```

Open `http://127.0.0.1:5000` in your web browser to explore your planets, notes, and symbol call graphs.

---

## Features

### 1. D3.js Memory & Planet Graph (`/`)
- Visualizes **planets (projects)**, **notes**, and **linked edges**.
- Node colors reflect memory type (Planets, Decisions, Facts, Issues, Tasks).
- Interactive drag, zoom, node selection, and note connection inspection.

### 2. AST Symbol Call Graph (`/api/code/graph`)
- Visualizes function declarations, classes, and inbound/outbound call edges per project.
- Automatically populated via BaseMem's Tree-Sitter code index (`.basemem.code.db`).

---

## REST API Reference

The visualization server exposes standard REST API endpoints for agent & dashboard integration:

### Memory Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /` | `GET` | API health check, service info, & endpoint index |
| `GET /api/planets` | `GET` | List all active planets with status, goals, and current state |
| `GET /api/notes?topic=<slug>` | `GET` | Fetch all notes for a topic planet |
| `GET /api/notes/graph?topic=<slug>` | `GET` | Fetch D3 graph schema (`nodes` + `edges`) for topic visualization |
| `GET /api/search?q=<query>` | `GET` | Full-text search across planets, notes, and nodes |
| `GET /api/graph` | `GET` | Global knowledge graph data |

### Code Intelligence Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /api/code/status?root=<path>` | `GET` | Indexing status, symbol count, and edge count for a project |
| `GET /api/code/search?q=<query>&root=<path>` | `GET` | Search symbol names and AST signatures |
| `GET /api/code/graph?root=<path>` | `GET` | Symbol call graph JSON (`nodes` + `edges`) for flow visualizers |

---

## Configuration Options

The visualization server can be configured via command flags or environment variables:

| Setting | Flag | Environment Variable | Default |
| :--- | :--- | :--- | :--- |
| Database Path | `--db <path>` | `BASEMEM_DB_PATH` | `~/.basemem/basemem.db` |
| Host Interface | `--host <ip>` | `BASEMEM_VIZ_HOST` | `127.0.0.1` |
| Port | `--port <num>` | `BASEMEM_VIZ_PORT` | `5000` |
