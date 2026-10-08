"""Code CLI: index and query source code symbols."""

import os

import click


def _get_code_indexer(project_root: str):
    """Create a CodeIndexer from a project root directory."""
    from indexer import CODE_DB_FILENAME, CodeIndexer
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return None
    db_path = os.path.join(root, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index found at {db_path}. Run `mem code init {root}` first.")
        return None
    return CodeIndexer(root)


def _fmt_loc(file_path: str, _line: int = 0) -> str:
    path = file_path.replace("\\", "/")
    for prefix in ("src/basemem/", "basemem/"):
        if path.startswith(prefix):
            path = path.removeprefix(prefix)
            break
    parts = path.split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else path


@click.group()
def code():
    """Code intelligence: index and query source code symbols."""
    pass


@code.command("init")
@click.argument('project_root', required=False, default='.')
@click.option('--workers', default=4, help='Number of parallel workers')
@click.option('--watch', is_flag=True, help='Watch for file changes and auto-reindex')
@click.option('--force', is_flag=True, help='Rebuild from scratch even if the index is current')
@click.option('--quiet', is_flag=True, help='Suppress the progress bar and log noise')
@click.option('--verbose', is_flag=True, help='Show the indexer log stream')
def code_init(project_root, workers, watch, force, quiet, verbose):
    """Index a project into a per-project .basemem.code.db."""
    import logging
    import signal
    import time as _time

    from indexer import CodeIndexer

    # The indexer logs an INFO line per phase. Those duplicate the summary
    # printed below and land in the middle of the progress bar, so quiet them
    # unless asked. Targeted at this logger rather than basicConfig so no other
    # subcommand's diagnostics change. Set explicitly in both directions, since
    # the logger is a process-wide singleton and a second call in the same
    # process would otherwise inherit whatever the first one chose.
    logging.getLogger("basemem.indexer").setLevel(
        logging.INFO if verbose else logging.WARNING
    )

    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        click.echo(click.style("  ✗ not a directory  ", fg="red", bold=True) + root)
        return
    indexer = CodeIndexer(root)

    # A live count is only possible once discovery has run, which is why the
    # indexer reports a "scan" phase before "indexing".
    state = {"total": 0, "reported": 0}

    def on_progress(phase, done, total):
        if phase == "scan":
            # Discovery has finished, so the real total is known and the bar can
            # be resized from its placeholder to the actual file count.
            state["total"] = total
            if bar is not None:
                bar.length = total
                bar.label = click.style("  indexing  ", fg="cyan", bold=True) + click.style(
                    os.path.basename(root), fg="white"
                )
        elif bar is not None:
            # Advance by the delta rather than by one, so a missed or repeated
            # callback cannot desynchronise the bar.
            delta = done - state["reported"]
            if delta > 0:
                bar.update(delta)
                state["reported"] = done

    try:
        t0 = _time.time()
        # An index that is already current should not be rebuilt: on the kernel
        # that is ten minutes thrown away to arrive at the same answer, so
        # `init` means "make sure this is indexed" and `--force` means rebuild.
        report = {} if force else indexer.staleness()
        if report.get("indexed") and not report.get("stale"):
            stats = indexer.get_project_stats()
            indexer.close()
            if not quiet:
                click.echo()
                click.echo(
                    click.style("  ✔  ", fg="green", bold=True)
                    + f"{stats.get('file_count', 0):,} files"
                    + click.style(f" · {stats.get('symbol_count', 0):,} symbols", fg="bright_black")
                )
                click.echo(
                    "  " + click.style("→ ", fg="bright_black")
                    + click.style(str(indexer.db_path), fg="bright_black")
                    + click.style("   up to date, nothing to do", fg="bright_black")
                )
                click.echo(click.style("    (--force rebuilds from scratch)", fg="bright_black"))
            return
        if quiet:
            bar = None
            result = indexer.index_project(_max_workers=workers, progress_cb=on_progress)
        else:
            with click.progressbar(
                length=1, label=click.style("  scanning   ", fg="cyan", bold=True), file=click.get_text_stream("stderr")
            ) as bar:
                result = indexer.index_project(_max_workers=workers, progress_cb=on_progress)
        elapsed = result["elapsed"]

        if not quiet:
            click.echo()
            n = result["files"]
            rate = f"{n / elapsed:.0f} files/s" if elapsed > 0.01 else ""
            parts = [
                f"{n:,} files",
                f"{result['symbols']:,} symbols",
                f"{result['edges']:,} edges",
                f"{elapsed:.1f}s",
            ]
            if rate:
                parts.append(click.style(f"({rate})", fg="bright_black"))
            click.echo(
                click.style("  ✔  ", fg="green", bold=True)
                + click.style(" · ", fg="bright_black").join(parts)
            )
        click.echo("  " + click.style("→ ", fg="bright_black") + click.style(str(indexer.db_path), fg="bright_black"))

        if watch:
            from indexer.watcher import CodeGraphWatcher
            watcher = CodeGraphWatcher(root, indexer)
            watcher.start()
            click.echo(f" Watching {root} for changes (Ctrl+C to stop)...")
            signal.signal(signal.SIGINT, lambda *_: (watcher.stop(), exit(0)))
            import time
            from pathlib import Path
            pid_file = Path(root) / ".basemem.daemon.pid"
            while True:
                time.sleep(5)
                if pid_file.exists():
                    try:
                        if time.time() - pid_file.stat().st_mtime > 300:
                            click.echo("Daemon idle timeout reached. Shutting down.")
                            watcher.stop()
                            pid_file.unlink(missing_ok=True)
                            break
                    except Exception:
                        pass
    finally:
        if not watch:
            indexer.close()


@code.command("list")
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=100, type=int, help='Max symbols')
@click.option('--offset', default=0, type=int, help='Pagination offset')
def code_list(root, limit, offset):
    """List all indexed code symbols in a project."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code indexed.")
            return
        results = indexer.list_symbols(limit=limit, offset=offset)
        if not results:
            click.echo("No symbols found.")
            return
        total = stats.get('symbol_count', 0)
        click.echo(f"sym {offset+1}-{offset+len(results)}/{total}")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}) {r['symbol_type'][:4]}")
    finally:
        indexer.close()


@code.command("search")
@click.argument('query')
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=20, type=int)
@click.option('--regex', is_flag=True, help='Interpret query as Python regex pattern')
def code_search(query, root, limit, regex):
    """Search code symbols by name or signature."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.search_symbols(query, limit=limit, use_regex=regex)
        if not results:
            click.echo(f"No match for '{query}'.")
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("node")
@click.argument('identifier')
@click.option('--root', default='.', help='Project root directory')
def code_node(identifier, root):
    """Show details of a code symbol by ID or name."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        sym = None
        try:
            sid = int(identifier)
            sym = indexer.get_symbol(sid)
        except ValueError:
            pass
        if not sym:
            symbols = indexer.get_symbol_by_name(identifier)
            if not symbols:
                click.echo(f"Not found: {identifier}")
                return
            if len(symbols) == 1:
                sym = symbols[0]
            else:
                click.echo(f"Multiple '{identifier}':")
                for s in symbols:
                    loc = _fmt_loc(s['file_path'], s['start_line'])
                    click.echo(f"  [{s['id']}] ({loc})")
                return

        callers = indexer.get_callers(sym['symbol_name'])
        callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
        loc = _fmt_loc(sym['file_path'], sym['start_line'])

        click.echo(f"{sym['symbol_name']} ({loc}) {sym['language']}")
        if sym.get('signature'):
            click.echo(f"  sig: {sym['signature']}")
        if sym.get('docstring'):
            click.echo(f"  doc: {sym['docstring'][:200]}")
        callers_str = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10]) if callers else "(none)"
        click.echo(f"  callers: {callers_str}")
        if callees:
            callees_str = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
            click.echo(f"  calls: {callees_str}")
    finally:
        indexer.close()


@code.command("callers")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
def code_callers(symbol_name, root):
    """Find what calls a given symbol."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_callers(symbol_name)
        if not results:
            click.echo(f"No callers for '{symbol_name}'.")
            return
        results_str = ", ".join(
            f"{r['symbol_name']} ({r['file_path']}:{r['line_number']})" for r in results[:20]
        )
        click.echo(f"callers of {symbol_name}: {results_str}")
    finally:
        indexer.close()


@code.command("callees")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--file-path', help='Limit to a specific file')
def code_callees(symbol_name, root, file_path):
    """Find what a given symbol calls."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_callees(symbol_name, file_path or "")
        if not results:
            click.echo(f"No callees for '{symbol_name}'.")
            return
        results_str = ", ".join(
            f"{r['to_name']} ({r['file_path']}:{r['line_number']})" for r in results[:20]
        )
        click.echo(f"callees of {symbol_name}: {results_str}")
    finally:
        indexer.close()


@code.command("trace")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--direction', default='both', type=click.Choice(['inbound', 'outbound', 'both']))
def code_trace(symbol_name, root, direction):
    """Trace call chain: inbound (callers), outbound (callees), or both."""
    from indexer import CODE_DB_FILENAME, CodeIndexer
    db_path = os.path.join(os.path.abspath(root), CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"No code index at {db_path}. Run `mem code init {root}` first.")
        return
    indexer = CodeIndexer(root)
    try:
        out = []
        if direction in ('inbound', 'both'):
            callers = indexer.get_callers(symbol_name)
            if callers:
                out.append(f"<- {', '.join(c['symbol_name'] for c in callers[:8])}")
        if direction in ('outbound', 'both'):
            callees = indexer.get_callees(symbol_name)
            if callees:
                out.append(f"-> {', '.join(c['to_name'] for c in callees[:8])}")
        if not out:
            click.echo(f"{symbol_name}: no call chain")
            return
        click.echo(f"{symbol_name}: {'; '.join(out)}")
    finally:
        indexer.close()


@code.command("sync")
@click.argument('path', required=False, default='.')
@click.option('--workers', default=4, help='Number of parallel workers')
def code_sync(path, workers):
    """Incremental re-index: only re-index files changed since last index."""
    from indexer import CodeIndexer
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        click.echo(f"[!] Not a directory: {root}")
        return
    indexer = CodeIndexer(root)
    try:
        result = indexer.sync_index(max_workers=workers)
        if result.get("status") == "unchanged":
            click.echo("No changes detected.")
            return
        click.echo(f"[ok] Synced: {result.get('files_changed', 0)} files changed, "
                   f"{result['symbols_added']} symbols, {result['edges_added']} edges, "
                   f"{result.get('files_removed', 0)} removed")
    finally:
        indexer.close()


@code.command("find")
@click.argument('query', required=False, default='')
@click.option('--root', default='.', help='Project root directory')
@click.option('--dead', is_flag=True, help='Find files never imported by other files (import-chain analysis)')
@click.option('--verbose', is_flag=True, help='Show symbols within dead files')
@click.option('--file-path', help='Filter to a specific file')
@click.option('--limit', default=20, type=int, help='Max results')
@click.option('--regex', is_flag=True, help='Interpret query as regex')
def code_find_cli(query, root, dead, verbose, file_path, limit, regex):
    """Find code symbols by name, detail, dead, or file. Mirrors MCP code_find."""
    from indexer import CODE_DB_FILENAME, CodeIndexer
    root_path = os.path.abspath(root)
    db_path = os.path.join(root_path, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index at {db_path}. Auto-indexing...")
        try:
            indexer = CodeIndexer(root_path)
            try:
                result = indexer.index_project(_max_workers=4)
                click.echo(f"[ok] Indexed {result['files']} files, {result['symbols']} symbols in {result['elapsed']:.1f}s")
            finally:
                indexer.close()
        except Exception as e:
            click.echo(f"[!] Auto-index failed: {e}")
            return
    indexer = CodeIndexer(root_path)
    try:
        if dead:
            results = indexer.find_dead_exports(limit=0)
            if not results:
                click.echo("All files are reachable via imports.")
                return
            click.echo(f"{len(results)} file(s) never imported by other files:")
            if verbose:
                for r in results:
                    click.echo(f"\n  {r['file_path']} ({r['symbol_count']} symbols):")
                    symbols = indexer.list_symbols_by_file(r['file_path'], limit=0)
                    for s in symbols[:10]:
                        sig = f" {s['signature'][:60]}" if s.get('signature') else ""
                        click.echo(f"    [{s['symbol_type'][:4]}] {s['symbol_name']}{sig}")
                    if len(symbols) > 10:
                        click.echo(f"    ... and {len(symbols) - 10} more")
            else:
                for r in results:
                    click.echo(f"  {r['file_path']} ({r['symbol_count']} symbols)")
            return

        if file_path and not query:
            results = indexer.list_symbols_by_file(file_path, limit=limit)
            if not results:
                click.echo(f"No symbols in '{file_path}'.")
                return
            click.echo(f"{len(results)} symbol(s) in {file_path}:")
            for r in results:
                sig = f" {r['signature'][:60]}" if r.get('signature') else ""
                click.echo(f"  [{r['id']}] {r['symbol_name']} ({r['symbol_type'][:4]}){sig}")
            return

        if not query:
            browse = indexer.list_symbols(limit=limit)
            click.echo(f"{len(browse)} symbol(s):")
            for r in browse:
                loc = _fmt_loc(r['file_path'], r['start_line'])
                click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}) {r['symbol_type'][:4]}")
            return

        # Try exact match first
        sym = None
        try:
            sid = int(query)
            sym = indexer.get_symbol(sid)
        except ValueError:
            pass
        if not sym:
            symbols = indexer.get_symbol_by_name(query)
            if len(symbols) == 1:
                sym = symbols[0]
            elif len(symbols) > 1:
                click.echo(f"Multiple '{query}':")
                for s in symbols:
                    loc = _fmt_loc(s['file_path'], s['start_line'])
                    click.echo(f"  [{s['id']}] {s['symbol_name']} ({loc})")
                return

        if sym:
            callers = indexer.get_callers(sym['symbol_name'])
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            loc = _fmt_loc(sym['file_path'], sym['start_line'])
            click.echo(f"{sym['symbol_name']} ({loc}) {sym['language']}")
            if sym.get('signature'):
                click.echo(f"  sig: {sym['signature']}")
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:10])
                click.echo(f"  callers: {cstr}")
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:10])
                click.echo(f"  calls: {cstr}")
            return

        # Fall through to search
        results = indexer.search_symbols(query, limit=limit, use_regex=regex)
        if not results:
            click.echo(f"No match for '{query}'.")
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("unreferenced")
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=200, type=int, help='Scan at most this many candidates')
@click.option('--include-tests', is_flag=True, help='Keep symbols in test paths')
@click.option('--include-entry-points', is_flag=True, help='Keep main/init/Test style names')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_unreferenced(root, limit, include_tests, include_entry_points, as_json):
    """List symbols with no caller found in this repository.

    Reports absence of a static caller, not deadness: exported library API and
    reflection are invisible to this check.
    """
    from indexer import CODE_DB_FILENAME
    from indexer.deadcode import unreferenced
    from indexer.indexer import CodeIndexer

    db_path = os.path.join(os.path.abspath(root), CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index found at {db_path}. Run `mem code init {os.path.abspath(root)}` first.")
        return
    indexer = CodeIndexer(os.path.abspath(root))
    try:
        result = unreferenced(
            indexer, limit=limit, include_tests=include_tests,
            include_entry_points=include_entry_points,
        )
    finally:
        indexer.close()

    if as_json:
        import json
        click.echo(json.dumps(result, indent=2))
        return

    click.echo(
        f"unreferenced: {result['kept']} symbol(s) "
        f"from {result['candidates_scanned']} candidate(s)"
        f"{' [capped]' if result['capped'] else ''}"
    )
    click.echo(
        f"  skipped: {result['skipped_test_paths']} in test paths, "
        f"{result['skipped_standalone_paths']} in standalone dirs, "
        f"{result['skipped_entry_points']} entry points"
    )
    for s in result["sample"]:
        click.echo(f"  {s}")
    click.echo(f"  confidence: {result['confidence']}")


@code.command("gquery")
@click.argument('search')
@click.option('--root', default='.', help='Project root directory')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_graph_query(search, root, as_json):
    """Query the code graph. Run `code gquery --help` or code_status_query for syntax."""
    from indexer import CODE_DB_FILENAME
    from indexer.indexer import CodeIndexer
    from indexer.query import QueryError, describe
    from indexer.query_execute import run as run_query

    db_path = os.path.join(os.path.abspath(root), CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index found at {db_path}. Run `mem code init {os.path.abspath(root)}` first.")
        return
    indexer = CodeIndexer(os.path.abspath(root))
    try:
        try:
            rows = run_query(indexer, search)
        except QueryError as e:
            click.echo(f"code gquery: {e}\n\n{describe()}")
            return
        except Exception as e:
            click.echo(f"code gquery: {type(e).__name__}: {e}")
            return
        if not rows:
            click.echo("code gquery: no matches")
            return
        if as_json:
            import json
            click.echo(json.dumps(rows, indent=2, default=str))
            return
        click.echo(f"code gquery: {len(rows)} row(s)")
        for row in rows:
            click.echo("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
    finally:
        indexer.close()


@code.command("query")
@click.argument('search')
@click.option('--root', default='.', help='Project root directory')
@click.option('--limit', default=20, type=int, help='Max results')
@click.option('--kind', help='Filter by symbol type (function, class, method, etc.)')
@click.option('--regex', is_flag=True, help='Interpret query as Python regex')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_query(search, root, limit, kind, regex, as_json):
    """Search for symbols in the codebase."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.search_symbols(search, limit=limit, use_regex=regex)
        if kind:
            results = [r for r in results if r.get('symbol_type') == kind]
        if not results:
            click.echo(f"No match for '{search}'.")
            return
        if as_json:
            import json
            click.echo(json.dumps(results, indent=2, default=str))
            return
        click.echo(f"{len(results)} match(es):")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            sig = f" {r['signature'][:60]}" if r.get('signature') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}){sig}")
    finally:
        indexer.close()


@code.command("explore")
@click.argument('query')
@click.option('--root', default='.', help='Project root directory')
@click.option('--max-files', default=3, type=int, help='Max files to show source from')
def code_explore(query, root, max_files):
    """Explore an area: relevant symbols' source + call paths in one shot. Auto-indexes if needed. Falls back to text search for natural language queries."""
    from indexer import CODE_DB_FILENAME, CodeIndexer
    root_path = os.path.abspath(root)
    db_path = os.path.join(root_path, CODE_DB_FILENAME)
    if not os.path.exists(db_path):
        click.echo(f"[!] No code index at {db_path}. Auto-indexing...")
        try:
            indexer = CodeIndexer(root_path)
            try:
                result = indexer.index_project(_max_workers=4)
                click.echo(f"[ok] Indexed {result['files']} files, {result['symbols']} symbols in {result['elapsed']:.1f}s")
            finally:
                indexer.close()
        except Exception as e:
            click.echo(f"[!] Auto-index failed: {e}")
            return
    indexer = CodeIndexer(root_path)
    try:
        symbols = indexer.search_symbols(query, limit=10)
        if not symbols:
            import subprocess as _sp
            try:
                cmd = ["rg", "-n", "--no-heading", query, root_path]
                result = _sp.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode in (0, 1) and result.stdout.strip():
                    lines = result.stdout.strip().splitlines()[:max_files]
                    click.echo(f"Text matches for '{query}':")
                    for line in lines:
                        click.echo(f"  {line}")
                    return
            except FileNotFoundError:
                pass
            except _sp.TimeoutExpired:
                pass
            click.echo(f"No matches for '{query}'.")
            return
        shown_files = set()
        for sym in symbols[:10]:
            loc = _fmt_loc(sym['file_path'], sym['start_line'])
            click.echo(f"\n── {sym['symbol_name']} ({loc}) {sym['symbol_type']} ──")
            if sym.get('signature'):
                click.echo(f"  sig: {sym['signature']}")
            callers = indexer.get_callers(sym['symbol_name'])
            if callers:
                cstr = ", ".join(f"{c['symbol_name']}:{c['line_number']}" for c in callers[:5])
                click.echo(f"  callers: {cstr}")
            callees = indexer.get_callees(sym['symbol_name'], sym['file_path'])
            if callees:
                cstr = ", ".join(f"{c['to_name']}:{c['line_number']}" for c in callees[:5])
                click.echo(f"  calls: {cstr}")
            if sym['file_path'] not in shown_files and len(shown_files) < max_files:
                shown_files.add(sym['file_path'])
                abs_fp = os.path.join(root_path, sym['file_path'])
                if os.path.isfile(abs_fp):
                    with open(abs_fp) as fh:
                        lines = fh.read().splitlines()
                    start = max(0, sym['start_line'] - 2)
                    end = min(len(lines), sym['end_line'] + 1)
                    click.echo(f"  source ({sym['start_line']}-{sym['end_line']}):")
                    for i in range(start, end):
                        marker = "→" if i == sym['start_line'] - 1 else " "
                        click.echo(f"    {marker} L{i + 1}: {lines[i]}")
    finally:
        indexer.close()


@code.command("files")
@click.option('--root', default='.', help='Project root directory')
@click.option('--prefix', default='', help='Filter to files matching this prefix')
@click.option('--limit', default=100, type=int, help='Max files to show')
@click.option('--tree', is_flag=True, help='Show as tree (default: flat list)')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_files(root, prefix, limit, tree, as_json):
    """Show project file structure from the index."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        files = indexer.list_files(prefix=prefix, limit=limit)
        if not files:
            click.echo("No files in index.")
            return
        if as_json:
            import json
            click.echo(json.dumps(files, indent=2, default=str))
            return
        if tree:
            tree_data = {}
            for f in files:
                parts = f['file_path'].split('/')
                node = tree_data
                for p in parts:
                    node = node.setdefault(p, {})
            def _print_tree(d, indent=""):
                for k, v in sorted(d.items()):
                    is_leaf = not v
                    click.echo(f"{indent}{'[file] ' if is_leaf else '[dir] '}{k}")
                    if not is_leaf:
                        _print_tree(v, indent + "  ")
            _print_tree(tree_data)
        else:
            total = len(files)
            click.echo(f"{total} file(s):")
            for f in files:
                click.echo(f"  {f['file_path']} ({f['symbol_count']}s)")
    finally:
        indexer.close()


@code.command("impact")
@click.argument('symbol_name')
@click.option('--root', default='.', help='Project root directory')
@click.option('--depth', default=2, type=int, help='Traversal depth')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def code_impact(symbol_name, root, depth, as_json):
    """Analyze what code is affected by changing a symbol."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        results = indexer.get_impact(symbol_name, depth=depth)
        if not results:
            click.echo(f"No impact found for '{symbol_name}'.")
            return
        if as_json:
            import json
            click.echo(json.dumps(results, indent=2, default=str))
            return
        click.echo(f"Impact analysis for '{symbol_name}' (depth={depth}):\n")
        for r in results:
            loc = _fmt_loc(r['file_path'], r['start_line'])
            via = f" (via {r['via']})" if r.get('via') else ""
            click.echo(f"  [{r['id']}] {r['symbol_name']} ({loc}:{r['line_number']}){via}")
    finally:
        indexer.close()


@code.command("status")
@click.option('--root', default='.', help='Project root directory')
def code_status(root):
    """Show code graph indexing stats for a project."""
    indexer = _get_code_indexer(root)
    if indexer is None:
        return
    try:
        stats = indexer.get_project_stats()
        if not stats.get("indexed"):
            click.echo("No code indexed. Run `mem code init` first.")
            return
        click.echo(f"{stats.get('name', '?')}: {stats['file_count']}f {stats['symbol_count']}s {stats.get('edges', 0)}e")
        diagnostics = indexer.get_index_diagnostics()
        click.echo(f"Status: {diagnostics['status']} | unresolved calls: {diagnostics['unresolved_calls']}")
        if diagnostics["languages"]:
            langs = ", ".join(f"{item['language']}={item['symbols']}" for item in diagnostics["languages"][:8])
            click.echo(f"Languages: {langs}")
    finally:
        indexer.close()


@code.command("list-projects")
@click.option('--search-root', default='', help='Comma-separated paths to scan (default: ~,/mnt,/media,/opt)')
def code_list_projects(search_root):
    """Scan for all indexed projects on the system."""
    from indexer.indexer import find_code_projects
    projects = find_code_projects(search_root)
    if not projects:
        click.echo("No indexed projects found.")
        return
    click.echo(f"\nFound {len(projects)} project(s):\n")
    for p in sorted(projects, key=lambda x: x["name"]):
        click.echo(f"  {p['name']}")
        click.echo(f"    Root: {p['root']}")
        click.echo(f"    Symbols: {p['symbols']}  Files: {p['files']}")
