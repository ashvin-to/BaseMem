# Memory retrieval benchmark baseline

Dataset SHA-256: `7cf59f4a2719557b545d8c44126b08fadc91d0094b3bec6f527d56151badd1c7`
Command: `uv run python -m benchmarks.memory_benchmark --output benchmark/baseline.json --repeats 3`
Queries: 7 (repeats: 3)

## Environment
- Python: `3.14.0`
- SQLite: `3.50.4`
- Platform: `Linux-7.2.6-arch2-1-x86_64-with-glibc2.44`
- Working directory: `/tmp/opencode/basemem-benchmark`

## Baseline metrics
- Recall@1: `1.0000`
- Recall@5: `1.0000`
- Recall@10: `1.0000`
- MRR: `1.0000`
- Precision@10: `0.3918`
- Irrelevant-result rate: `0.6082`
- Latency mean/p50/max ms: `0.1136` / `0.0962` / `0.2937`
- Tokens mean/total: `71.57` / `501`
