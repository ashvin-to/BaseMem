# Query quality benchmark

Repo: `/mnt/Storage/cbm-bench/go`  
Questions: 8  
Graded on evidence: the answer must name a file or symbol that a correct
answer must contain. Format is not compared, because the two tools report
very differently.

## Scores

| tool | passed | avg latency |
|---|---|---|
| basemem | 6/8 | 94 ms |
| cbm | 6/8 | 1665 ms |

## Per question

| question | basemem | cbm |
|---|---|---|
| `find-by-name` Find the symbol trimRightSpace | PASS | PASS |
| `who-calls` Which functions call Execute | PASS | PASS |
| `what-calls` What does the Execute function call | PASS | PASS |
| `types-of-symbol` List the methods defined on the Command type | PASS | fail (no expected evidence in answer) |
| `locate-definition` Where is the OutOrStdout function defined | PASS | PASS |
| `unused-or-orphan` Find a function defined in this repo but never called from within it | fail (no expected evidence in answer) | fail (exit 1) |
| `file-inventory` List the Go source files in this repository | PASS | PASS |
| `most-connected` Which symbols have the most callers in this repository | fail (no expected evidence in answer) | PASS |

## Detail

### `find-by-name` — Find the symbol trimRightSpace

*Baseline lookup. Both tools should nail this.*

- **basemem** PASS in 96 ms — evidence: cobra.go
  - `1 match(es): [300] trimRightSpace (cobra.go)`
- **cbm** PASS in 1546 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.trimRightSpace Function cobra.go 159-161 3 1\ntotal:...`

### `who-calls` — Which functions call Execute

*Callers is the single most-used navigation query.*

- **basemem** PASS in 90 ms — evidence: command.go, completions_test.go
  - `callers of Execute: ExecuteContext (command.go:1064), TestValidateFlagGroups (flag_groups_test.go:186), TestDefaultCompletionCmd (completions_test.go:2469), Tes...`
- **cbm** PASS in 1774 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `what-calls` — What does the Execute function call

*Callees, same traversal in the other direction.*

- **basemem** PASS in 93 ms — evidence: command.go
  - `callees of Execute: ExecuteC (command.go:1071)`
- **cbm** PASS in 1596 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `types-of-symbol` — List the methods defined on the Command type

*Needs the class->method relation, not just name matching.*

- **basemem** PASS in 101 ms — evidence: command.go
  - `Command (command.go) go callers: TestDeadcodeElimination:289, TestDeadcodeElimination:294, runShellCheck:57, TestBashCompletions:221`
- **cbm** FAIL in 1783 ms — no expected evidence in answer
  - `{"content":[{"type":"text","text":"{\"columns\":[\"c.name\",\"m.name\",\"m.file\"],\"rows\":[],\"returned\":0,\"total\":0,\"total_relation\":\"eq\",\"has_more\"...`

### `locate-definition` — Where is the OutOrStdout function defined

*Precision matters more than recall here.*

- **basemem** PASS in 92 ms — evidence: command.go
  - `1 match(es): [53] OutOrStdout (command.go)`
- **cbm** PASS in 1772 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.OutOrStdout Method command.go 393-395 7 2\ntotal: 1\...`

### `unused-or-orphan` — Find a function defined in this repo but never called from within it

*Negative query. Hard for a name-matching tool, trivial for a graph.*

- **basemem** FAIL in 91 ms — no expected evidence in answer
  - `No match for 'MATCH (a:Function) WHERE a.caller_count = 0 RETURN a.name, a.file LIMIT 400'.`
- **cbm** FAIL in 1550 ms — exit 1
  - `{"content":[{"type":"text","text":"unexpected operator at pos 31"}],"structuredContent":{"error":"unexpected operator at pos 31"},"isError":true} warning: passi...`

### `file-inventory` — List the Go source files in this repository

*Cheap sanity check that the repo was ingested at all.*

- **basemem** PASS in 103 ms — evidence: cobra.go
  - `[dir] .github [file] dependabot.yml [file] labeler.yml [dir] workflows [file] labeler.yml [file] test.yml [file] .golangci.yml [file] active_help.go [file] acti...`
- **cbm** PASS in 1724 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"f.path\"],\"rows\":[[\"SECURITY.md\"],[\"bash_completionsV2_test.go\"],[\"cobra_test.go\"],[\"Makefile\"],[\"...`

### `most-connected` — Which symbols have the most callers in this repository

*Aggregation over the graph. The clearest divide between the tools.*

- **basemem** FAIL in 87 ms — no expected evidence in answer
  - `No match for 'MATCH (a)-[:calls]->(b) RETURN a.name, a.file LIMIT 400'.`
- **cbm** PASS in 1575 ms — evidence: command.go, cobra.go, args.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\",\"callers\"],\"rows\":[[\"executeCommand\",\"command_test.go\",\"193\"],[\"AddCommand\",\...`
