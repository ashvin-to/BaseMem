# Memory retrieval benchmark baseline

Dataset version: `2026-09-25.1`
Dataset SHA-256: `15bfa50bab0f0ea9f7702c5b76aba214fc48cbd10df7ca3e20467b6bc67ab462`
Code version: `d4c33501748757c2415b13311ce189355797d524`
Timestamp UTC: `2026-09-25T06:33:14.644389+00:00`
Command: `uv run python -m benchmarks.memory_benchmark --output benchmark/after.json --repeats 3`
Queries: 120 (answerable: 108, no-answer: 12, repeats: 3)

## Environment
- Python: `3.14.0`
- SQLite: `3.50.4`
- Platform: `Linux-7.2.6-arch2-1-x86_64-with-glibc2.44`
- Working directory: `/mnt/Storage/BaseMem`

## Baseline metrics
- Recall@1/3/5/10: `0.6481` / `0.7963` / `0.7963` / `0.7963`
- Precision@1/3/5/10: `0.6417` / `0.2667` / `0.1600` / `0.0800`
- MRR: `0.7593`
- nDCG@10: `0.7339`
- Irrelevant rate: `0.1531`
- No-answer false positive rate: `0.0000`
- Latency mean/p95 ms: `4.1107` / `5.1739`
- Tokens mean/p95/total: `27.43` / `43` / `3291`
- Superseded retrieval rate: `0.0000`
- Historical accuracy: `1.0000`
- Contradiction accuracy: `1.0000`

## Failure classification counts
- lexical: `24`
- scope: `12`
- temporal: `12`
- supersession: `6`
- type: `0`
- importance: `9`
- confidence: `9`
- graph: `9`
- ranking: `32`
- noise: `7`
