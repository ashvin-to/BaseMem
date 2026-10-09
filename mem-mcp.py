#!/usr/bin/env python3
"""MCP server entry point for BaseMem agent memory."""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("basemem")
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mem-mcp",
        description=(
            "Run the BaseMem MCP server over stdio, or query a flag from the terminal.\n"
            "With no flags this speaks MCP on stdin/stdout, which is how agents launch it."
        ),
        epilog=(
            "examples:\n"
            "  mem-mcp                     serve MCP on stdio (what agents use)\n"
            "  mem-mcp --help              this message\n"
            "  mem-mcp --version           print the installed version\n"
            "  mem-mcp --check             verify the database opens and report its size"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="print the installed version and exit")
    parser.add_argument("--check", action="store_true", help="verify the memory database and exit")
    parser.add_argument(
        "--db",
        default=None,
        help="path to the memory database (overrides BASEMEM_DB_PATH) when serving",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(f"basemem {_version()}")
        return 0

    if args.check:
        from mcp_server.server import _env_path

        db_path = args.db or _env_path()
        try:
            import os

            size = os.path.getsize(db_path) if os.path.isfile(db_path) else 0
        except OSError as exc:
            print(f"mem-mcp check: cannot stat {db_path}: {exc}")
            return 1
        if not size:
            print(f"mem-mcp check: no database at {db_path} (it will be created on first write)")
            return 0
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.execute("SELECT COUNT(*) FROM notes").fetchone()
            conn.close()
        except sqlite3.Error as exc:
            print(f"mem-mcp check: {db_path} is unreadable: {exc}")
            return 1
        print(f"mem-mcp check: ok  db={db_path}  size={size / 1e6:.1f}MB")
        return 0

    if args.db:
        import os

        os.environ["BASEMEM_DB_PATH"] = args.db

    from mcp_server.server import server

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
