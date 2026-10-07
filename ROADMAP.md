# BaseMem roadmap

Open issues and planned changes, in priority order. Every claim here traces to a
measurement; where something is unmeasured it says so.

Last updated: 2026-10-04, on `feat/query-surface`.

---

## 1. Query quality

The largest gap versus cbm. Measured on `benchmarks/query_quality.md` (8 questions,
`go/cobra`): **cbm 6/8 at 1623 ms, BaseMem 4/8 at 93 ms**.

### 1.1 No aggregation or ordering — the clearest structural gap

cbm answers "which symbols have the most callers" with
`MATCH (a)<-[:CALLS]-(b) RETURN a.name, count(b) AS callers ORDER BY callers DESC`.
BaseMem cannot: `code_query` supports no `count()`, no `ORDER BY`, no `GROUP BY`.
This is the single question type BaseMem structurally cannot answer.

- Add aggregation to `indexer/query_execute.py`: `count(x)`, `min`/`max`, `GROUP BY`, `ORDER BY`
- Extend `describe()` alongside it, and add a test that every documented form parses
  *(the documented syntax was never executed by a test, so a mismatch would be silent)*

### 1.2 `code_query` fails silently on an unknown label

`MATCH (a:function)` — lowercase — returns no rows rather than reporting that
`function` is not one of the five labels (`function`, `method`, `class`, `type`,
`symbol`). A typo looks identical to a legitimately empty result.

- Validate labels and relations at parse time; error with the valid set
- Same for relation names and field names

### 1.3 Traversal questions score worse than lookup

`who-calls` and `what-calls` both fail for BaseMem and pass for cbm.
`code_trace` exists but the MCP tool list does not expose callers/callees directly,
so an agent has to know to reach for `code_trace`.

- Verify whether this is a capability gap or a discoverability gap before building
- Consider a `code_callers` / `code_callees` pair on the MCP surface

### 1.4 No semantic search

cbm has BM25 *and* vector search. BaseMem has FTS5 lexical only — `storage/notes.py`
records `"semantic": False` explicitly on every result.

- This is a design question, not a flag: which model, where vectors live, how they
  interact with FTS, and the cost on a 47 MB database
- Deliberately deferred. Nothing is stubbed for it today.

### 1.5 No multi-hop

`code_query` handles single-hop patterns. Real questions are often two hops
("who calls the callers of X").

- Decide whether to extend the pattern grammar or add a `trace_path`-style primitive

---

## 2. Language coverage

Measured with `bench_lang.py` (resolution rate on 44-file to 115-file samples):

| lang | symbols | edges | resolved |
|---|---|---|---|
| go | 675 | 5,816 | 55% |
| nim | 712 | 2,261 | 21% |
| lua | 700 | 5,474 | 24% |

### 2.1 nim — fixed, low resolution remains

`nim.py` queried a `methodCall` node that does not exist in the grammar, so nim
emitted **zero** member calls. Fixed in `52ec84c`; now 1,527 member calls, and 623
bogus free calls removed.

Resolution is still 21% because nim receivers are untyped locals (`path:splitFile()`).
That needs local type inference, which is the same problem as JavaScript's.

### 2.2 lua — 24%, and mostly correct

The unresolved edges are `assert` (341), `print` (169), `require` (144),
`tostring` (61), `lua_pushstring` (100) — stdlib and C-API calls with no definition
in the repo. **These are correct.** A receiver-suffix heuristic was evaluated and
rejected: it would resolve 21 of 1,949.

The real gap is `local x = require("mod")`, which binds `x` to a module. That
binding is not recorded, so `x:method()` cannot resolve.

### 2.3 Untyped receivers are the shared blocker

nim, lua and JavaScript all fail the same way: the receiver is a local with no
declared type. cbm has the same limitation — it does not index nim at all.

- One mechanism would help all three: record `x = require(...)` / `x = new T()` /
  `x := SomeType()` as a typed binding, then feed it to the existing `var_types` path

### 2.4 No guard against the nim failure class

`test_query_slots.py` catches queries under names the parser never runs. It cannot
catch **a valid slot name referencing a node type that does not exist** — which is
what silently zeroed nim's call graph.

- Add a cross-language check: every query file must produce at least one match
  against a sample of its own language

---

## 3. Indexing performance

Kernel: **2214s → 617.3s** (3.59x) at 4 workers, byte-identical output.

Shipped: deferred `code_symbols` index build (1.36x on the store phase),
`_module_to_file` stem index (25x on the resolve pass), resolver maps interned
(4238 → 2649 MiB), `known_files` via `SELECT DISTINCT`, `parent_of` map replacing a
per-edge SQL JOIN.

### 3.1 Parse and store are now the majority

Of the remaining 617s, roughly 557s is parse and store. Resolution is now minor.

- The store is serial by design; 4 → 8 workers buys only 1.18x because of it
- Measured and rejected: `executemany` (slightly worse), `page_size=16384` (noise),
  `synchronous=OFF` (noise)

### 3.2 Fixed overhead that will not scale away

- FTS rebuild: 46.3s over 8.3M rows
- Resolution map build: 32.8s, 2.6 GiB resident
- These do not shrink with more workers. Below ~600s they become the visible cost.

### 3.3 C macro default — an open policy decision

75% of the kernel's 8.3M symbols are macros. Indexing them on by default is what
made the kernel take 2214s in the first place. Off returns it to roughly the 500s
range.

- **This is a user decision, not an engineering one.** It is larger than any
  remaining optimisation in this document.

---

## 4. Robustness

### 4.1 Auto-index could index an entire disk — fixed

A wrong `projectRoot` made `code_context` begin indexing the whole BaseMem tree.
Now refused above 20,000 files, and the refusal names the explicit command.
Building moved to a subprocess, killing a fork-in-server deadlock that wedged two
sessions in a day.

- Committed `00eafcd`

### 4.2 Process count: investigated, not a defect

Three `mem-mcp` processes appeared for one client. Measured rather than assumed:

- `opencode run --standalone` spawns exactly one server per session and exits cleanly
  when the session ends
- The server exits within **0.5s** of stdin closing
- The multiplier is opencode spawning one server **per working directory touched** —
  cbm behaves identically, and antigravity's single server is a difference in client
  scope, not in BaseMem

No fix needed. A daemon would not remove it; thin clients would still be spawned
per directory.

### 4.3 Data layout drift — fixed

`install.sh`, `install.js` and `storage/db.py` each named the database path
independently and had drifted apart; all three wrote `~/.basemem`. Now XDG-aware and
pinned together by `tests/test_data_dir_xdg.py`.

### 4.4 The installer clones into the install directory

`install.sh` clones the full repo, which is why 349 MB of code sat beside 48 MB of
data. `BASE_DIR` already defaults outside home, and `frontend/` is 184 MB of
untracked `node_modules` that a clean clone does not carry.

### 4.5 One MCP server per tool call site

Nine `_ensure_code_index` call sites exist in `server.py`. Two return a friendly
refusal message; the other seven still raise. Inconsistent behaviour depending on
which tool was called.

---

## 5. Benchmarking infrastructure

### 5.1 Query quality: exists now, thin

`benchmarks/query_quality.py` — 8 evidence-graded questions, both tools, side by
side. First real quality measurement of either tool.

- **Extend to the 35-repo corpus.** `go/cobra` is 42 files with heavy test coverage,
  which flatters both tools
- **Add harder questions:** multi-hop, cross-file, interface dispatch, refactor impact
- **Grade precision, not just recall.** A tool that returns everything passes a
  `must_include` check by accident
- **Run it in CI** so a regression in query quality is caught, not discovered later

### 5.2 Extraction benchmarks exist, quality does not

`bench_lang.py` measures symbols, edges and resolution rate. `bench_resolve.py`
measures the resolve pass. Neither measures whether an answer is *right*.

---

## 6. Not planned

Recorded so these are not re-litigated:

- **Daemon process** — see 4.2. Would not reduce process count
- **Chasing cbm's symbol counts** — nim proved the metric is vanity: adding 1,527
  member calls moved resolution 2 points. Lua sits at 24% and is mostly *correct*
- **Vector embeddings as a config flag** — there is no flag. It is a design project,
  see 1.4