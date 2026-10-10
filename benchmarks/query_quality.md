# Query quality benchmark

Repo: `/mnt/Storage/cbm-bench/go`  
Questions: 14  
Graded on evidence: the answer must name a file or symbol that a correct
answer must contain. Format is not compared, because the two tools report
very differently.

## Scores

| tool | passed | avg latency |
|---|---|---|
| basemem | 14/14 | 100 ms |
| cbm | 13/14 | 1604 ms |

## Per question

| question | basemem | cbm |
|---|---|---|
| `find-by-name` Find the symbol trimRightSpace | PASS | PASS |
| `who-calls` Which functions call Execute | PASS | PASS |
| `what-calls` What does the Execute function call | PASS | PASS |
| `types-of-symbol` List the methods defined on the Command type | PASS | PASS |
| `locate-definition` Where is the OutOrStdout function defined | PASS | PASS |
| `unused-or-orphan` Find a function defined in this repo but never called from within it | PASS | fail (exit 1) |
| `file-inventory` List the Go source files in this repository | PASS | PASS |
| `most-connected` Which symbols have the most callers in this repository | PASS | PASS |
| `two-hop-reach` Which functions does Execute reach within two hops | PASS | PASS |
| `either-or` Functions defined in command.go or in args.go | PASS | PASS |
| `named-set` Definition of Execute, ExecuteC or ExecuteContext | PASS | PASS |
| `cross-file-calls` Which functions does command.go call in cobra.go | PASS | PASS |
| `most-called-files` Which symbols have the most callers | PASS | PASS |
| `multi-file-filter` Functions defined in command.go | PASS | PASS |

## Detail

### `find-by-name` — Find the symbol trimRightSpace

*Baseline lookup. Both tools should nail this.*

- **basemem** PASS in 100 ms — evidence: cobra.go
  - `1 match(es): [300] trimRightSpace (cobra.go)`
- **cbm** PASS in 1588 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.trimRightSpace Function cobra.go 159-161 3 1\ntotal:...`

### `who-calls` — Which functions call Execute

*Callers is the single most-used navigation query.*

- **basemem** PASS in 100 ms — evidence: command.go, completions_test.go
  - `callers of Execute: ExecuteContext (command.go:1064), TestValidateFlagGroups (flag_groups_test.go:186), TestDefaultCompletionCmd (completions_test.go:2469), Tes...`
- **cbm** PASS in 1776 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `what-calls` — What does the Execute function call

*Callees, same traversal in the other direction.*

- **basemem** PASS in 101 ms — evidence: command.go
  - `callees of Execute: ExecuteC (command.go:1071)`
- **cbm** PASS in 1559 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 30 (rows: name label lines in out connected; group prefix \"-\" means empty; qn = prefix empty ? name : prefix + \"....`

### `types-of-symbol` — List the methods defined on the Command type

*Needs the class->method relation, not just name matching.*

- **basemem** PASS in 105 ms — evidence: command.go
  - `Command (command.go) go callers: TestDeadcodeElimination:289, TestDeadcodeElimination:294, runShellCheck:57, TestBashCompletions:221`
- **cbm** PASS in 1812 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"s.name\",\"m.name\",\"m.file\"],\"rows\":[[\"Command\",\"GenFishCompletion\",\"fish_completions.go\"],[\"Comm...`

### `locate-definition` — Where is the OutOrStdout function defined

*Precision matters more than recall here.*

- **basemem** PASS in 105 ms — evidence: command.go
  - `1 match(es): [53] OutOrStdout (command.go)`
- **cbm** PASS in 1590 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"results: 1 (cols: qn label file lines in out)\n mnt-Storage-cbm-bench-go.OutOrStdout Method command.go 393-395 7 2\ntotal: 1\...`

### `unused-or-orphan` — Find a function defined in this repo but never called from within it

*Negative query. Needs NOT, which neither tool expressed before this.*

- **basemem** PASS in 102 ms — evidence: OnInitialize, OnFinalize, appendIfNotPresent
  - `code gquery: 15 row(s) a_symbol_name=NoArgs, a_file_path=args.go a_symbol_name=OnlyValidArgs, a_file_path=args.go a_symbol_name=NoDuplicateArgs, a_file_path=arg...`
- **cbm** FAIL in 1714 ms — exit 1
  - `{"content":[{"type":"text","text":"unexpected operator at pos 31"}],"structuredContent":{"error":"unexpected operator at pos 31"},"isError":true} warning: passi...`

### `file-inventory` — List the Go source files in this repository

*Cheap sanity check that the repo was ingested at all.*

- **basemem** PASS in 90 ms — evidence: cobra.go
  - `[dir] .github [file] dependabot.yml [file] labeler.yml [dir] workflows [file] labeler.yml [file] test.yml [file] .golangci.yml [file] active_help.go [file] acti...`
- **cbm** PASS in 1538 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"f.path\"],\"rows\":[[\"SECURITY.md\"],[\"bash_completionsV2_test.go\"],[\"cobra_test.go\"],[\"Makefile\"],[\"...`

### `most-connected` — Which symbols have the most callers in this repository

*Aggregation over the graph. The clearest divide between the tools.*

- **basemem** PASS in 129 ms — evidence: cobra.go, args.go
  - `code gquery: 10 row(s) b_symbol_name=executeCommand, b_file_path=command_test.go, callers=193 b_symbol_name=checkStringContains, b_file_path=command_test.go, ca...`
- **cbm** PASS in 1555 ms — evidence: command.go, cobra.go, args.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\",\"callers\"],\"rows\":[[\"executeCommand\",\"command_test.go\",\"193\"],[\"AddCommand\",\...`

### `two-hop-reach` — Which functions does Execute reach within two hops

*Multi-hop traversal. Needs a path pattern, not a single relation.*

- **basemem** PASS in 100 ms — evidence: HasParent, Traverse, checkCommandGroups
  - `code gquery: 21 row(s) a_symbol_name=Execute, a_file_path=command.go, m_symbol_name=ExecuteC, b_symbol_name=HasParent a_symbol_name=Execute, a_file_path=command...`
- **cbm** PASS in 1570 ms — evidence: HasParent, Traverse, checkCommandGroups
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\",\"b.name\"],\"rows\":[[\"Execute\",\"command.go\",\"HelpFunc\"],[\"Execute\",\"command.go...`

### `either-or` — Functions defined in command.go or in args.go

*Disjunction in WHERE. Currently only conjunctions are expressible.*

- **basemem** PASS in 91 ms — evidence: command.go, args.go
  - `code gquery: 20 row(s) a_symbol_name=PositionalArgs, a_file_path=args.go a_symbol_name=legacyArgs, a_file_path=args.go a_symbol_name=NoArgs, a_file_path=args.go...`
- **cbm** PASS in 1534 ms — evidence: command.go, args.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[[\"hasNoOptDefVal\",\"command.go\"],[\"shortHasNoOptDefVal\",\"command.go\"],[...`

### `named-set` — Definition of Execute, ExecuteC or ExecuteContext

*Membership test over a list of names.*

- **basemem** PASS in 90 ms — evidence: command.go
  - `code gquery: 3 row(s) a_symbol_name=ExecuteContext, a_file_path=command.go a_symbol_name=Execute, a_file_path=command.go a_symbol_name=ExecuteC, a_file_path=com...`
- **cbm** PASS in 1541 ms — evidence: command.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[[\"ExecuteContext\",\"command.go\"],[\"Execute\",\"command.go\"],[\"ExecuteC\"...`

### `cross-file-calls` — Which functions does command.go call in cobra.go

*Cross-file reachability, which is how a refactor blast radius is judged.*

- **basemem** PASS in 90 ms — evidence: cobra.go
  - `code gquery: 14 row(s) a_symbol_name=SetUsageTemplate, b_symbol_name=tmpl, b_file_path=cobra.go a_symbol_name=SetHelpTemplate, b_symbol_name=tmpl, b_file_path=c...`
- **cbm** PASS in 1549 ms — evidence: cobra.go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"b.name\",\"b.file\"],\"rows\":[[\"SetUsageTemplate\",\"tmpl\",\"cobra.go\"],[\"SetHelpTemplate\",\...`

### `most-called-files` — Which symbols have the most callers

*Fan-in across the repo; needs aggregation over an inbound relation.*

- **basemem** PASS in 100 ms — evidence: .go
  - `code gquery: 10 row(s) b_symbol_name=executeCommand, b_file_path=command_test.go, callers=193 b_symbol_name=checkStringContains, b_file_path=command_test.go, ca...`
- **cbm** PASS in 1567 ms — evidence: .go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.file\",\"callers\"],\"rows\":[[\"command.go\",\"826\"],[\"command_test.go\",\"257\"],[\"args_test.go\",\"10...`

### `multi-file-filter` — Functions defined in command.go

*Import fan-out, an ordering signal.*

- **basemem** PASS in 90 ms — evidence: .go
  - `code gquery: 20 row(s) a_symbol_name=FParseErrWhitelist, a_file_path=command.go a_symbol_name=Group, a_file_path=command.go a_symbol_name=Command, a_file_path=c...`
- **cbm** PASS in 1565 ms — evidence: .go
  - `{"content":[{"type":"text","text":"{\"columns\":[\"a.name\",\"a.file\"],\"rows\":[[\"hasNoOptDefVal\",\"command.go\"],[\"shortHasNoOptDefVal\",\"command.go\"],[...`
