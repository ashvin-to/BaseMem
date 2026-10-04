# Query quality benchmark

Repo: `/mnt/Storage/cbm-bench/go`  
Questions: 14  
Graded on evidence: the answer must name a file or symbol that a correct
answer must contain. Format is not compared, because the two tools report
very differently.

## Scores

| tool | passed | avg latency |
|---|---|---|
| basemem | 13/14 | 131 ms |
| cbm | 9/14 | 1911 ms |

## Per question

| question | basemem | cbm |
|---|---|---|
| `find-by-name` Find the symbol trimRightSpace | PASS | PASS |
| `who-calls` Which functions call Execute | PASS | PASS |
| `what-calls` What does the Execute function call | PASS | PASS |
| `types-of-symbol` List the methods defined on the Command type | PASS | fail (no expected evidence in answer) |
| `locate-definition` Where is the OutOrStdout function defined | PASS | PASS |
| `unused-or-orphan` Find a function defined in this repo but never called from within it | PASS | fail (exit 1) |
| `file-inventory` List the Go source files in this repository | PASS | PASS |
| `most-connected` Which symbols have the most callers in this repository | PASS | PASS |
| `two-hop-reach` Which functions does Execute reach within two hops | PASS | PASS |
| `either-or` Functions defined in command.go or in args.go | PASS | PASS |
| `named-set` Definition of Execute, ExecuteC or ExecuteContext | PASS | fail (no expected evidence in answer) |
| `cross-file-calls` Which functions does command.go call in cobra.go | fail (no expected evidence in answer) | fail (no expected evidence in answer) |
| `most-called-files` Which symbols have the most callers | PASS | fail (no expected evidence in answer) |
| `multi-file-filter` Functions defined in command.go | PASS | PASS |

## Detail

### `find-by-name` — Find the symbol trimRightSpace

*Baseline lookup. Both tools should nail this.*

- **basemem** PASS in 140 ms — evidence: cobra.go
  - `1 match(es): [300] trimRightSpace (cobra.go)`
- **cbm** PASS in 1902 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.trimRightSpace Function cobra.go 159-161 3 1\ntotal:...`

### `who-calls` — Which functions call Execute

*Callers is the single most-used navigation query.*

- **basemem** PASS in 132 ms — evidence: command.go, completions_test.go
  - `callers of Execute: ExecuteContext (command.go:1064), TestValidateFlagGroups (flag_groups_test.go:186), TestDefaultCompletionCmd (completions_test.go:2469), Tes...`
- **cbm** PASS in 1809 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `what-calls` — What does the Execute function call

*Callees, same traversal in the other direction.*

- **basemem** PASS in 141 ms — evidence: command.go
  - `callees of Execute: ExecuteC (command.go:1071)`
- **cbm** PASS in 1806 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `types-of-symbol` — List the methods defined on the Command type

*Needs the class->method relation, not just name matching.*

- **basemem** PASS in 127 ms — evidence: command.go
  - `Command (command.go) go callers: TestDeadcodeElimination:289, TestDeadcodeElimination:294, runShellCheck:57, TestBashCompletions:221`
- **cbm** FAIL in 2023 ms — no expected evidence in answer
  - `{"content":[{"type":"text","text":"{\"columns\":[\"c.name\",\"m.name\",\"m.file\"],\"rows\":[],\"returned\":0,\"total\":0,\"total_relation\":\"eq\",\"has_more\"...`

### `locate-definition` — Where is the OutOrStdout function defined

*Precision matters more than recall here.*

- **basemem** PASS in 128 ms — evidence: command.go
  - `1 match(es): [53] OutOrStdout (command.go)`
- **cbm** PASS in 1893 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.OutOrStdout Method command.go 393-395 7 2\ntotal: 1\...`

### `unused-or-orphan` — Find a function defined in this repo but never called from within it

*Negative query. Needs NOT, which neither tool expressed before this.*

- **basemem** PASS in 177 ms — evidence: .go
  - `code gquery: 40 row(s) a_symbol_name=TestActiveHelpAlone, a_file_path=active_help_test.go a_symbol_name=TestActiveHelpWithComps, a_file_path=active_help_test.go...`
- **cbm** FAIL in 1830 ms — exit 1
  - `{"content":[{"type":"text","text":"unexpected operator at pos 31"}],"structuredContent":{"error":"unexpected operator at pos 31"},"isError":true} warning: passi...`

### `file-inventory` — List the Go source files in this repository

*Cheap sanity check that the repo was ingested at all.*

- **basemem** PASS in 121 ms — evidence: cobra.go
  - `[dir] .github [file] dependabot.yml [file] labeler.yml [dir] workflows [file] labeler.yml [file] test.yml [file] .golangci.yml [file] active_help.go [file] acti...`
- **cbm** PASS in 2025 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"f.path\"],\"rows\":[[\"SECURITY.md\"],[\"bash_completionsV2_test.go\"],[\"cobra_test.go\"],[\"Makefile\"],[\"...`

### `most-connected` — Which symbols have the most callers in this repository

*Aggregation over the graph. The clearest divide between the tools.*

- **basemem** PASS in 114 ms — evidence: cobra.go, args.go
  - `code gquery: 10 row(s) b_symbol_name=executeCommand, b_file_path=command_test.go, callers=193 b_symbol_name=checkStringContains, b_file_path=command_test.go, ca...`
- **cbm** PASS in 1846 ms — evidence: command.go, cobra.go, args.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\",\"callers\"],\"rows\":[[\"executeCommand\",\"command_test.go\",\"193\"],[\"AddCommand\",\...`

### `two-hop-reach` — Which functions does Execute reach within two hops

*Multi-hop traversal. Needs a path pattern, not a single relation.*

- **basemem** PASS in 124 ms — evidence: .go
  - `code gquery: 40 row(s) a_symbol_name=GetActiveHelpConfig, a_file_path=active_help.go a_symbol_name=TestActiveHelpAlone, a_file_path=active_help_test.go a_symbol...`
- **cbm** PASS in 2153 ms — evidence: .go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\",\"b.name\"],\"rows\":[[\"GetActiveHelpConfig\",\"active_help.go\",\"configEnvVar\"],[\"Ge...`

### `either-or` — Functions defined in command.go or in args.go

*Disjunction in WHERE. Currently only conjunctions are expressible.*

- **basemem** PASS in 116 ms — evidence: command.go, args.go
  - `code gquery: 20 row(s) a_symbol_name=PositionalArgs, a_file_path=args.go a_symbol_name=legacyArgs, a_file_path=args.go a_symbol_name=NoArgs, a_file_path=args.go...`
- **cbm** PASS in 1758 ms — evidence: command.go, args.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[[\"hasNoOptDefVal\",\"command.go\"],[\"shortHasNoOptDefVal\",\"command.go\"],[...`

### `named-set` — Definition of Execute, ExecuteC or ExecuteContext

*Membership test over a list of names.*

- **basemem** PASS in 117 ms — evidence: command.go
  - `code gquery: 3 row(s) a_symbol_name=ExecuteContext, a_file_path=command.go a_symbol_name=Execute, a_file_path=command.go a_symbol_name=ExecuteC, a_file_path=com...`
- **cbm** FAIL in 1977 ms — no expected evidence in answer
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[],\"returned\":0,\"total\":0,\"total_relation\":\"eq\",\"has_more\":false,\"tr...`

### `cross-file-calls` — Which functions does command.go call in cobra.go

*Cross-file reachability, which is how a refactor blast radius is judged.*

- **basemem** FAIL in 141 ms — no expected evidence in answer
  - `code gquery: 14 row(s) a_symbol_name=SetUsageTemplate, b_symbol_name=tmpl a_symbol_name=SetHelpTemplate, b_symbol_name=tmpl a_symbol_name=SetVersionTemplate, b_...`
- **cbm** FAIL in 1863 ms — no expected evidence in answer
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"b.name\",\"b.file\"],\"rows\":[[\"customMultiString\",\"SliceValue\",\"completions.go\"]],\"return...`

### `most-called-files` — Which symbols have the most callers

*Fan-in across the repo; needs aggregation over an inbound relation.*

- **basemem** PASS in 125 ms — evidence: .go
  - `code gquery: 10 row(s) b_symbol_name=executeCommand, b_file_path=command_test.go, callers=193 b_symbol_name=checkStringContains, b_file_path=command_test.go, ca...`
- **cbm** FAIL in 1926 ms — no expected evidence in answer
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[],\"returned\":0,\"total\":0,\"total_relation\":\"eq\",\"has_more\":false,\"tr...`

### `multi-file-filter` — Functions defined in command.go

*Import fan-out, an ordering signal.*

- **basemem** PASS in 125 ms — evidence: .go
  - `code gquery: 20 row(s) a_symbol_name=FParseErrWhitelist, a_file_path=command.go a_symbol_name=Group, a_file_path=command.go a_symbol_name=Command, a_file_path=c...`
- **cbm** PASS in 1940 ms — evidence: .go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.file\",\"deps\"],\"rows\":[[\"doc/man_examples_test.go\",\"2\"],[\"doc/cmd_test.go\",\"1\"],[\"doc/man_docs...`
